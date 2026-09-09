"""
workers/processing_worker.py — Thread de processamento goniométrico em tempo real
================================================================================

Este módulo implementa o núcleo científico da aplicação PyQt6: recebe quadros
brutos da câmera, executa o pipeline completo de análise e entrega os resultados
prontos para a interface gráfica — sem nunca bloquear a thread principal.

Problema resolvido por este módulo:
    O pipeline do MediaPipe + cálculo angular + suavização por filtros é pesado:
    pode levar de 15ms a 50ms por quadro dependendo do hardware. Executá-lo na
    thread principal tornaria a janela do PyQt6 não responsiva durante cada análise.

Solução:
    ProcessingWorker é executado em sua própria QThread. Ele recebe quadros de
    CameraWorker via Queue(maxsize=1) e entrega os resultados para MainWindow via
    pyqtSignal — sem nunca acessar diretamente nenhum widget.

Pipeline de dados por quadro:
    frame_bgr (np.ndarray)
        -> MediaPipe Hands                    [detecção 3D de landmarks]
        -> DigitalGoniometer.compute_all()    [ângulos brutos por articulação]
        -> GoniometryFilterBank.smooth_all()  [EMA -> Kalman, remove instabilidade/jitter]
        -> _build_skeleton()                  [sobreposição visual BGR]
        -> classify_hand_state()              [mão aberta/fechada, ASSH]
        -> compute_realtime_metrics()         [velocidade, frequência, regularidade]
        -> ProcessingResult                   [dataclass que empacota todos os dados]
        -> pyqtSignal result_ready            [entrega segura entre threads (thread-safe) para MainWindow]

Regras seguidas:
    - Widgets NUNCA são chamados aqui (violações causam encerramento silencioso no Qt).
    - O pipeline científico (goniometry.py, smoothing.py etc.) nunca é modificado.
    - Todos os parâmetros numéricos provêm de config.py.
"""

import math
import queue
import threading
import time
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional

import cv2
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

# Módulos científicos — importados, mas NUNCA modificados.
from goniometry import DigitalGoniometer
from smoothing import GoniometryFilterBank
from goniometry_overlay import _build_skeleton
from goniometry_csv import GoniometryCSVLogger
from dashboard_utils import (
    FINGERS,
    FINGER_JOINTS,
    classify_hand_state,
    compute_realtime_metrics,
)

import config

try:
    import mediapipe as mp
except ImportError:
    raise ImportError(
        "MediaPipe não encontrado. Execute: pip install mediapipe\n"
        "Este pacote é obrigatório para a detecção dos landmarks da mão."
    )


# =============================================================================
# DATACLASS DE RESULTADO
# =============================================================================

@dataclass
class ProcessingResult:
    """
    Estrutura de dados que empacota todos os resultados de UM quadro processado.

    Esta dataclass é o "pacote de entrega" que ProcessingWorker monta
    após executar o pipeline completo e envia para MainWindow via pyqtSignal.
    MainWindow então distribui cada campo para o widget correspondente.

    Por que uma dataclass?
        Dataclasses são mais legíveis do que dicionários (acesso por atributo, não
        chaves de string), possuem tipagem explícita e podem ser tornadas imutáveis
        quando necessário. Elas também documentam diretamente os campos que o
        pipeline produz.

    Campos:
        frame_overlay: Array NumPy BGR com o quadro da câmera + esqueleto da mão
                       desenhado por _build_skeleton(). Enviado para VideoWidget.

        angles_smooth: Dicionário {finger: {joint: smoothed_angle}} retornado
                       por GoniometryFilterBank.smooth_all(). Contém MCP, PIP, DIP,
                       ABD e TAM para dedos longos; MCP, IP e TAM para o polegar.

        hand_state: Dicionário retornado por classify_hand_state(). Contém
                    estados_dedos (estado de cada dedo), dedos_fechados e mao_aberta.

        metrics_per_finger: {finger_name: metrics_dict} onde cada dict é a
                            saída de compute_realtime_metrics() — rom,
                            velocidade média, velocidade de pico, frequência Hz,
                            coeficiente de variação e regularidade.

        hand_detected: True se o MediaPipe encontrou uma mão neste quadro.
                       False se nenhuma mão estava visível (quadro ignorado).

        frame_id: Contador sequencial de quadros processados nesta sessão.
                  Usado por MetricsWidget e registrado no CSV.

        fps: Taxa de quadros do processamento em quadros por segundo, calculada por EMA.
             Reflete a velocidade REAL do pipeline, não a velocidade da câmera.

        tam_buffers_snapshot: Cópia segura entre threads (thread-safe) dos buffers circulares de TAM por
                              dedo. Usado por FingerCardWidgets para os
                              mini-gráficos individuais.
    """
    frame_overlay: np.ndarray
    angles_smooth: dict
    hand_state: dict
    metrics_per_finger: dict
    hand_detected: bool
    frame_id: int
    fps: float

    # Snapshot dos buffers de TAM — list[] é seguro para copiar fora do lock
    # porque listas Python são copiadas por valor com list().
    tam_buffers_snapshot: Dict[str, List[float]] = field(default_factory=dict)


# =============================================================================
# WORKER DE PROCESSAMENTO
# =============================================================================

class ProcessingWorker(QThread):
    """
    Thread de processamento goniométrico — o núcleo científico da aplicação.

    Recebe quadros brutos de CameraWorker, executa o pipeline completo de análise
    e emite os resultados encapsulados em ProcessingResult para MainWindow.

    Arquitetura interna:
        A comunicação entre CameraWorker e ProcessingWorker usa Queue(maxsize=1).

        Por que Queue(maxsize=1) e não uma lista ou deque?
            Em tempo real, queremos sempre processar o quadro MAIS RECENTE.
            Com maxsize=1:
            - Se o processador estiver ocupado quando um novo quadro chegar, o quadro antigo
              NA FILA é descartado e o novo assume seu lugar.
            - Isso mantém a latência sempre mínima, evitando o problema de "quadros acumulados":
              processar quadros que estão 2-3 segundos atrás do movimento real.
            - Com uma lista ou deque sem limite, os quadros se acumulariam indefinidamente,
              fazendo com que a latência crescesse até o sistema travar.

    Sessão CSV:
        O CSV é iniciado por start_session() e fechado por stop_session().
        O worker só grava no CSV se uma sessão estiver ativa — permitindo
        que a câmera esteja ligada sem gravar (estado READY) antes do início formal.

    Sinais emitidos:
        result_ready(object): ProcessingResult completo para MainWindow.
                              Tipo 'object' porque o PyQt6 não suporta
                              pyqtSignal(ProcessingResult) diretamente.
        processing_error(str): mensagem de erro não-fatal para o LogWidget.
    """

    # Sinal transportando o ProcessingResult completo.
    # Usamos o tipo 'object' porque pyqtSignal não suporta dataclasses
    # customizadas diretamente. MainWindow o recebe como 'object' e faz a conversão.
    result_ready: pyqtSignal = pyqtSignal(object)

    # Sinal de erro não-fatal (ex.: quadro corrompido isolado).
    # Erros fatais (ex.: MediaPipe não instalado) usam raise ImportError.
    processing_error: pyqtSignal = pyqtSignal(str)

    # Emitido quando a lateralidade da mão avaliada muda e todos os buffers
    # internos foram redefinidos. MainWindow conecta este sinal para limpar
    # os próprios buffers de exibição do widget de gráficos.
    hand_side_reset: pyqtSignal = pyqtSignal()

    def __init__(self, parent=None) -> None:
        """
        Inicializa ProcessingWorker com todos os componentes do pipeline.

        Objetos científicos (MediaPipe, DigitalGoniometer, etc.) são criados
        aqui em __init__ porque:
        1. A criação é leve (sem E/S de câmera).
        2. __init__ é executado na thread principal — boa prática para detectar
           erros de importação (MediaPipe não instalado) antes de iniciar a thread.
        3. Os objetos SÃO usados em run() (thread do worker) — isso é seguro porque
           apenas uma thread (o worker) os acessa após start().

        Parâmetros:
            parent: Widget pai do Qt (opcional). Tipicamente None para workers.
        """
        super().__init__(parent)

        # Evento de parada seguro entre threads (thread-safe) — mesmo padrão de CameraWorker.
        self._stop_event: threading.Event = threading.Event()

        # Fila de quadros entre CameraWorker -> ProcessingWorker.
        # maxsize=1: nunca acumula quadros antigos, processa sempre o mais recente.
        self._frame_queue: queue.Queue = queue.Queue(maxsize=config.QUEUE_SIZE)

        # --- Componentes do pipeline científico ---

        # Detector de mãos do MediaPipe.
        # static_image_mode=False: modo vídeo — reutiliza o rastreamento entre quadros
        # (mais rápido do que detectar do zero a cada quadro).
        # max_num_hands=1: uma mão por vez, suficiente para a goniometria clínica.
        self._hands = mp.solutions.hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            min_detection_confidence=config.MP_DETECT_CONF,
            min_tracking_confidence=config.MP_TRACK_CONF,
        )

        # Goniômetro digital — calcula os ângulos articulares brutos.
        self._gonio: DigitalGoniometer = DigitalGoniometer()

        # Banco de filtros — modo definido explicitamente por
        # config.FILTER_MODE_DEFAULT (hoje "EMA_KALMAN", preservando o
        # pipeline clínico validado: EMA -> Kalman). Uma instância de
        # SeriesFilter por série (ex.: "INDEX_MCP", "THUMB_IP").
        self._filter_bank: GoniometryFilterBank = GoniometryFilterBank(
            ema_alpha=config.EMA_ALPHA,
            kalman_q=config.KALMAN_Q,
            kalman_r=config.KALMAN_R,
            mode=config.FILTER_MODE_DEFAULT,
        )

        # --- Buffers circulares temporais ---
        # Um deque por dedo para armazenar o histórico de TAM.
        # deque(maxlen=N) descarta automaticamente o valor mais antigo quando cheio,
        # garantindo que a memória nunca cresça além de BUFFER_SIZE entradas.
        self._tam_buffers: Dict[str, Deque[float]] = {
            finger: deque(maxlen=config.BUFFER_SIZE)
            for finger in FINGERS
        }

        # Um deque por dedo para armazenar os timestamps dos quadros.
        # Usado por compute_realtime_metrics() para calcular velocidade (°/s)
        # e frequência (Hz) — grandezas que dependem do tempo decorrido.
        self._time_buffers: Dict[str, Deque[float]] = {
            finger: deque(maxlen=config.BUFFER_SIZE)
            for finger in FINGERS
        }

        # Conta quadros consecutivos sem detecção de mão.
        # Quando excede NO_HAND_RESET_FRAMES, os filtros são redefinidos.
        self._no_hand_frames: int = 0

        # Contador total de quadros para esta sessão do worker.
        self._frame_id: int = 0

        # FPS do pipeline de processamento (EMA, mesmo valor de CameraWorker).
        self._fps_ema: float = 0.0

        # Timestamp do último quadro processado com sucesso.
        self._t_last_frame: float = 0.0

        # --- Logger CSV (inativo até start_session() ser chamado) ---
        self._csv_logger: Optional[GoniometryCSVLogger] = None
        self._csv_path: str = ""
        self._session_active: bool = False

        # Lock que protege _session_active e _csv_logger.
        # MainWindow pode chamar start_session()/stop_session() de fora
        # da thread do worker, portanto precisamos de sincronização.
        self._session_lock: threading.Lock = threading.Lock()

        # Estado para rastreamento da lateralidade da mão
        self.current_hand_side: str = "Direita"
        self.previous_hand_side: str = "Direita"
        self._hand_side_lock: threading.Lock = threading.Lock()

    def set_evaluated_hand(self, side: str) -> None:
        """Atualiza o lado da mão avaliada ('Direita' ou 'Esquerda') de forma segura a partir da UI."""
        side = side.strip().title()
        if side in ("Direita", "Esquerda"):
            with self._hand_side_lock:
                self.current_hand_side = side

    def _reset_for_hand_change(self) -> None:
        """Redefine os filtros e o histórico temporal quando o lado da mão avaliada muda."""
        self._filter_bank.reset_all()
        for finger in FINGERS:
            self._tam_buffers[finger].clear()
            self._time_buffers[finger].clear()
        self.hand_side_reset.emit()
        logging.info("Mão avaliada alterada. Filtros e histórico redefinidos.")

    def reset_state(self) -> None:
        """
        Redefine o estado interno do worker. Chamado quando uma nova sessão é iniciada.
        Esvazia a fila de quadros, redefine os filtros e zera todos os buffers numéricos.
        """
        # Esvazia a fila pendente sem bloquear
        while not self._frame_queue.empty():
            try:
                self._frame_queue.get_nowait()
            except queue.Empty:
                break

        # Redefine o estado científico
        self._filter_bank.reset_all()

        # Limpa medições históricas de todos os dedos
        for finger in FINGERS:
            self._tam_buffers[finger].clear()
            self._time_buffers[finger].clear()

        # Redefine contadores de quadros
        self._no_hand_frames = 0
        self._frame_id = 0
        self._fps_ema = 0.0

    # =========================================================================
    # INTERFACE COM CameraWorker
    # =========================================================================

    def put_frame(self, frame: np.ndarray) -> None:
        """
        Recebe um quadro de CameraWorker e o coloca na fila de processamento.

        Chamado por MainWindow ao conectar o sinal frame_ready de
        CameraWorker. Executado na thread do Qt (thread principal ou de CameraWorker,
        dependendo do tipo de conexão do sinal).

        Estratégia "descartar antigo, manter novo":
            Queue.put_nowait() levanta queue.Full se a fila estiver cheia.
            Nesse caso, removemos o quadro antigo com get_nowait() e inserimos
            o novo. Isso garante que o processador SEMPRE receba o quadro mais
            recente, mantendo a latência mínima independente da velocidade de processamento.

        Parâmetros:
            frame: Array NumPy BGR espelhado recebido diretamente de CameraWorker.
        """
        try:
            # Tenta inserção não bloqueante.
            self._frame_queue.put_nowait(frame)
        except queue.Full:
            # A fila está cheia (já possui 1 quadro aguardando).
            # Remove o quadro antigo não processado...
            try:
                self._frame_queue.get_nowait()
            except queue.Empty:
                # Condição de corrida extremamente improvável: entre put_nowait
                # falhar e get_nowait executar, o worker esvaziou a fila.
                # Nenhuma ação necessária — segue normalmente.
                pass

            # ...e insere o quadro mais recente em seu lugar.
            try:
                self._frame_queue.put_nowait(frame)
            except queue.Full:
                # Ainda cheia após remoção — descarta este quadro.
                # Não deve ocorrer na prática, mas tratado defensivamente.
                pass

    # =========================================================================
    # LOOP PRINCIPAL (executado em thread separada)
    # =========================================================================

    def run(self) -> None:
        """
        Método principal de QThread — chamado automaticamente pelo Qt quando
        processing_worker.start() é executado. Roda inteiramente na thread do worker.

        Este método NÃO DEVE ser chamado diretamente. Use start().

        Fluxo:
            1. Aguarda um quadro na fila com timeout de 100ms.
            2. Se nenhum quadro chegou, verifica se deve parar e volta ao passo 1.
            3. Executa o pipeline completo (MediaPipe -> ângulos -> filtros -> métricas).
            4. Monta ProcessingResult e emite result_ready.
            5. Repete até que stop() seja chamado.
        """
        while not self._stop_event.is_set():

            # Aguarda um quadro com timeout de 100ms.
            # O timeout é necessário para que o loop possa verificar _stop_event
            # mesmo sem receber quadros (ex.: câmera pausada).
            try:
                frame_bgr = self._frame_queue.get(timeout=0.1)
            except queue.Empty:
                # Nenhum quadro disponível no tempo limite — retorna ao loop
                # para verificar _stop_event antes de aguardar novamente.
                continue

            # Quadro recebido — executa o pipeline completo.
            try:
                self._process_frame(frame_bgr)
            except Exception as exc:
                # Captura erros não-fatais (ex.: quadro corrompido isolado).
                # Não interrompe a thread — apenas registra e continua.
                self.processing_error.emit(
                    f"Erro ao processar o quadro #{self._frame_id}: {exc}"
                )

        # Loop finalizado — libera recursos do MediaPipe.
        self._cleanup()

    def _process_frame(self, frame_bgr: np.ndarray) -> None:
        """
        Executa o pipeline goniométrico completo em um único quadro BGR.

        Esta função orquestra todos os módulos científicos em sequência.
        A ordem das etapas é determinística e não pode ser alterada — cada
        etapa depende da saída da anterior.

        Parâmetros:
            frame_bgr: Array NumPy de formato (height, width, 3), formato BGR,
                       com o quadro já espelhado horizontalmente por CameraWorker.
        """
        self._frame_id += 1
        t_now: float = time.monotonic()

        # Calcula o FPS de processamento do pipeline.
        self._update_fps(t_now)
        self._t_last_frame = t_now

        # --- Passo 1: MediaPipe Hands ---
        # Converte BGR -> RGB porque o MediaPipe espera imagens RGB.
        # O OpenCV usa BGR por convenção histórica do DirectShow no Windows.
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

        # Marca como não gravável para otimização: o MediaPipe pode referenciar
        # a memória do array diretamente sem copiar, economizando ~2-5ms por quadro.
        frame_rgb.flags.writeable = False
        results = self._hands.process(frame_rgb)
        frame_rgb.flags.writeable = True

        # Verifica se o MediaPipe detectou ao menos uma mão no quadro.
        hand_detected: bool = results.multi_hand_landmarks is not None

        if not hand_detected:
            # Nenhuma mão visível neste quadro.
            self._no_hand_frames += 1
            self._handle_no_hand(frame_bgr)
            return

        # --- Passo 2: Identificação da mão (lateralidade) ---
        # O lado da mão é controlado explicitamente pela UI. 
        # Isso evita problemas com o MediaPipe adivinhando incorretamente 
        # ao lidar com câmeras espelhadas e poses frontais.
        with self._hand_side_lock:
            local_hand_side = self.current_hand_side
            
        if local_hand_side != self.previous_hand_side:
            self._reset_for_hand_change()
            self.previous_hand_side = local_hand_side
            
        eh_mao_direita: bool = (local_hand_side == "Direita")

        # --- Passo 3: Cálculo dos ângulos brutos ---
        # compute_all() recebe os 21 landmarks 3D normalizados (coordenadas 0.0-1.0)
        # e retorna um dict {finger: {joint: angle_in_degrees}}.
        landmarks = results.multi_hand_landmarks[0].landmark
        angles_raw: dict = self._gonio.compute_all(landmarks, eh_mao_direita=eh_mao_direita)

        # --- Passo 4: Suavização EMA -> Kalman ---
        # Por que a ordem EMA ANTES de Kalman importa?
        #   EMA remove ruído de ALTA FREQUÊNCIA (jitter/instabilidade quadro a quadro do MediaPipe).
        #   Kalman remove ruído de BAIXA FREQUÊNCIA (deriva lenta, tremor fino).
        #   Se invertêssemos a ordem (Kalman -> EMA), o Kalman receberia o ruído
        #   de alta frequência diretamente, perdendo eficiência como estimador do
        #   valor "verdadeiro" do ângulo. A combinação EMA->Kalman produz ângulos
        #   suaves tanto em altas quanto em baixas frequências.
        angles_smooth: dict = self._filter_bank.smooth_all(angles_raw)

        # Quadro válido com mão detectada — zera o contador de ausência de mão.
        self._no_hand_frames = 0

        # --- Passo 5: Atualização dos buffers temporais ---
        # Armazena TAM e timestamp para cada dedo para o cálculo de métricas.
        self._update_buffers(angles_smooth, t_now)

        # --- Passo 6: Geração da sobreposição visual (overlay) ---
        # Por que _build_skeleton() executa aqui (no worker) e não na UI?
        #   O overlay envolve operações pesadas de desenho OpenCV:
        #   linhas do esqueleto, círculos dos landmarks, arcos angulares e texto com valores de ângulos.
        #   Fazer isso na thread principal bloquearia a interface por ~5-15ms por quadro.
        #   Aqui no worker, a sobrecarga fica "escondida" atrás do tempo de processamento
        #   do MediaPipe, sem impacto perceptível na UI.
        #
        # Mapa de estabilidade: informa ao overlay a cor de cada articulação
        # (verde=estável, amarelo=convergindo, azul=instável), derivado do
        # ganho de Kalman atual de cada filtro.
        stability_map: dict = {
            finger: {
                joint: self._filter_bank.get_stability(finger, joint)
                for joint in angles_smooth.get(finger, {}).keys()
            }
            for finger in FINGERS
            if finger in angles_smooth
        }

        # _build_skeleton() gera apenas o painel com o esqueleto da mão.
        frame_overlay: np.ndarray = _build_skeleton(
            frame=frame_bgr,
            landmarks=landmarks,
            angles=angles_smooth,
            pw=config.CAMERA_WIDTH,
            ph=config.CAMERA_HEIGHT,
            frozen=False,
            stability_map=stability_map,
        )

        # --- Passo 7: Classificação do estado da mão ---
        hand_state: dict = classify_hand_state(angles_smooth)

        # --- Passo 8: Cálculo de métricas por dedo ---
        metrics_per_finger: dict = {}
        for finger in FINGERS:
            tam_buf = list(self._tam_buffers[finger])
            time_buf = list(self._time_buffers[finger])

            # Necessário ao menos 2 pontos para calcular velocidade e frequência.
            if len(tam_buf) >= 2 and len(tam_buf) == len(time_buf):
                metrics_per_finger[finger] = compute_realtime_metrics(
                    angle_buffer=tam_buf,
                    time_buffer=time_buf,
                )
            else:
                # Dados insuficientes — retorna métricas zeradas para evitar
                # exibição de NaN ou erros na interface.
                metrics_per_finger[finger] = {
                    "rom": 0.0,
                    "vel_media": 0.0,
                    "vel_pico": 0.0,
                    "freq_hz": 0.0,
                    "cv": 0.0,
                    "regularidade": "—",
                    "n_picos": 0,
                }

        # --- Passo 9: Snapshot do buffer de TAM para mini-gráficos ---
        # Converte de deque para list() para criar uma cópia independente.
        # Uma cópia é necessária porque o deque original continua sendo
        # modificado pelo worker enquanto MainWindow distribui os dados.
        tam_snapshot: Dict[str, List[float]] = {
            finger: list(self._tam_buffers[finger])
            for finger in FINGERS
        }

        # --- Passo 10: Empacotamento e emissão do resultado ---
        result = ProcessingResult(
            frame_overlay=frame_overlay,
            angles_smooth=angles_smooth,
            hand_state=hand_state,
            metrics_per_finger=metrics_per_finger,
            hand_detected=True,
            frame_id=self._frame_id,
            fps=self._fps_ema,
            tam_buffers_snapshot=tam_snapshot,
        )

        # Emite o resultado para MainWindow via sinal seguro entre threads (thread-safe).
        # O Qt garante que o slot receptor (na thread principal) só é
        # invocado quando a thread principal estiver pronta para processá-lo.
        self.result_ready.emit(result)

        # --- Passo 11: Registro CSV (somente se a sessão estiver ativa) ---
        # Registra a cada CSV_LOG_INTERVAL quadros para reduzir E/S de disco.
        if self._frame_id % config.CSV_LOG_INTERVAL == 0:
            self._try_log_csv(angles_smooth)

    def _handle_no_hand(self, frame_bgr: np.ndarray) -> None:
        """
        Trata o caso em que nenhuma mão foi detectada no quadro atual.

        Dois comportamentos principais:
        1. Após NO_HAND_RESET_FRAMES quadros sem mão, redefine os filtros de Kalman.
           Sem essa redefinição, quando a mão retornar, o filtro tentaria
           "convergir" da posição antiga para a nova, gerando ângulos errôneos
           nos primeiros quadros (falso transiente). A redefinição garante que a primeira
           detecção após ausência prolongada seja tratada como um "estado inicial".

        2. Emite um ProcessingResult com hand_detected=False e o quadro original.
           Isso permite que MainWindow limpe a interface (ex.: VideoWidget
           exibe o quadro sem overlay, MetricsWidget limpa os valores).

        Parâmetros:
            frame_bgr: Quadro BGR original, sem overlay, para exibição na UI.
        """
        # Redefine os filtros apenas após ausência prolongada para evitar redefinições desnecessárias
        # decorrentes de oclusões momentâneas dos dedos.
        if self._no_hand_frames >= config.NO_HAND_RESET_FRAMES:
            self._filter_bank.reset_all()
            self._no_hand_frames = 0

        # Emite resultado indicando ausência de mão para a UI.
        result = ProcessingResult(
            frame_overlay=frame_bgr.copy(),
            angles_smooth={},
            hand_state={"estados_dedos": {}, "dedos_fechados": 0, "mao_aberta": True},
            metrics_per_finger={},
            hand_detected=False,
            frame_id=self._frame_id,
            fps=self._fps_ema,
            tam_buffers_snapshot={f: [] for f in FINGERS},
        )
        self.result_ready.emit(result)

    # =========================================================================
    # BUFFERS TEMPORAIS
    # =========================================================================

    def _update_buffers(self, angles_smooth: dict, timestamp: float) -> None:
        """
        Atualiza os buffers circulares de TAM e timestamp para cada dedo.

        Os buffers são mantidos pelo worker e atualizados quadro a quadro.
        Eles acumulam um histórico das BUFFER_SIZE entradas mais recentes,
        usadas por compute_realtime_metrics() para calcular métricas em janela deslizante
        (ROM, velocidade, frequência).

        Parâmetros:
            angles_smooth: Dicionário com ângulos suavizados para todos os dedos.
            timestamp: Tempo atual em segundos (time.monotonic()) — mesma origem
                       para todos os dedos no mesmo quadro.
        """
        for finger in FINGERS:
            finger_data = angles_smooth.get(finger, {})

            # Extrai o TAM (Total Active Motion) para o dedo.
            # O TAM é a métrica clínica mais importante: representa o ROM total
            # de movimento ativo de todas as articulações de um dedo combinadas.
            #
            # angles_smooth[finger]["TAM"] pode ser None quando a série ainda
            # não tem histórico válido (smoothing.py, política de valores
            # inválidos) — nesse caso, pulamos o quadro sem adicionar amostra
            # ao buffer, sem inserir 0.0 e sem limpar o que já existia.
            tam_raw = finger_data.get("TAM")
            if tam_raw is None:
                continue
            try:
                tam_value: float = float(tam_raw)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(tam_value):
                continue

            # Só adiciona ao buffer se o valor for válido (> 0).
            # TAM = 0.0 geralmente indica um quadro sem detecção ou articulação ausente,
            # e não um ângulo real — incluir zeros distorceria as métricas de ROM e frequência
            # calculadas a partir deste buffer.
            if tam_value > 0.0:
                self._tam_buffers[finger].append(tam_value)
                self._time_buffers[finger].append(timestamp)

    def get_tam_buffers(self) -> Dict[str, List[float]]:
        """
        Retorna uma cópia segura entre threads (thread-safe) dos buffers atuais de TAM.

        Usado por MainWindow para alimentar os mini-gráficos dos FingerCardWidgets.
        Retorna cópias (list()) em vez dos deques originais para que o
        chamador não precise de sincronização adicional.

        Retorna:
            Dict mapeando o nome do dedo (ex.: "INDEX") para uma lista de floats
            com os valores de TAM dos últimos BUFFER_SIZE quadros válidos.
        """
        return {
            finger: list(self._tam_buffers[finger])
            for finger in FINGERS
        }

    # =========================================================================
    # CÁLCULO DE FPS DO PIPELINE
    # =========================================================================

    def _update_fps(self, t_now: float) -> None:
        """
        Atualiza o FPS do pipeline de processamento usando EMA.

        FPS do pipeline != FPS da câmera.
        A câmera pode capturar a 30 FPS, mas o processamento pode ser mais lento
        (ex.: 20 FPS em uma CPU lenta) ou mais rápido (ex.: 25 FPS se a câmera
        ocasionalmente descartar quadros). Este método mede a velocidade REAL de processamento.

        Parâmetros:
            t_now: Timestamp atual em segundos (time.monotonic()).
                   Comparado com o timestamp do quadro anterior para calcular dt.
        """
        if self._t_last_frame <= 0.0:
            # Primeiro quadro — sem referência anterior para calcular o intervalo.
            return

        dt: float = t_now - self._t_last_frame

        # Proteção contra dt zero (dois quadros processados no mesmo instante).
        if dt <= 0.0:
            return

        fps_instant: float = 1.0 / dt

        # EMA com α=0.15 — mesmo valor de CameraWorker para consistência.
        ema_alpha: float = 0.15

        if self._fps_ema == 0.0:
            self._fps_ema = fps_instant
        else:
            self._fps_ema = ema_alpha * fps_instant + (1.0 - ema_alpha) * self._fps_ema

    # =========================================================================
    # GERENCIAMENTO DA SESSÃO CSV
    # =========================================================================

    def start_session(self, csv_path: str) -> None:
        """
        Inicia uma nova sessão de gravação em CSV.

        Chamado por MainWindow ao iniciar uma sessão, ANTES de start().
        Cria o GoniometryCSVLogger que registrará os ângulos a cada quadro.

        O _session_lock protege _csv_logger e _session_active porque
        este método é chamado a partir da thread principal enquanto o worker pode
        estar lendo _session_active no loop de run(). Sem o lock, haveria
        uma condição de corrida.

        Parâmetros:
            csv_path: Caminho completo do arquivo CSV a ser criado/aberto.
                      Exemplo: "session_goniometry_20260623_143512.csv"
        """
        with self._session_lock:
            # Fecha qualquer sessão previamente aberta.
            if self._csv_logger is not None:
                self._csv_logger.close()

            self._csv_path = csv_path
            self._csv_logger = GoniometryCSVLogger(csv_path)
            self._session_active = True

    def stop_session(self) -> None:
        """
        Encerra a sessão de gravação em CSV com segurança.

        Chamado por MainWindow ao encerrar a sessão. Garante que todos os dados
        pendentes no buffer do logger sejam gravados em disco (flush) antes de fechar
        o arquivo.

        Por que flush() antes de close()?
            O Python usa buffers de escrita para desempenho: os dados são mantidos em memória
            e gravados em lotes. Se o arquivo for fechado sem flush(),
            dados em buffer podem ser perdidos (especialmente em uma falha subsequente).
            flush() força a escrita imediata no disco.
        """
        with self._session_lock:
            if self._csv_logger is not None:
                self._csv_logger.flush()
                self._csv_logger.close()
                self._csv_logger = None
            self._session_active = False

    def _try_log_csv(self, angles_smooth: dict) -> None:
        """
        Tenta registrar o quadro atual no CSV, caso uma sessão esteja ativa.

        Executado dentro do loop de run() (thread do worker). Usa o mesmo lock de
        start_session() e stop_session() para acesso seguro entre threads (thread-safe).

        A verificação de _session_active é feita dentro do lock para evitar a
        condição de corrida "verificar e agir": sem o lock, _session_active
        poderia ser True na verificação, mas _csv_logger poderia ser fechado (None)
        por stop_session() antes de alcançar csv_logger.log().

        Parâmetros:
            angles_smooth: Dicionário de ângulos suavizados para o quadro atual.
        """
        with self._session_lock:
            if self._session_active and self._csv_logger is not None:
                self._csv_logger.log(self._frame_id, angles_smooth)

                # Executa flush a cada 60 quadros para reduzir E/S sem risco de perda de dados.
                if self._frame_id % 60 == 0:
                    self._csv_logger.flush()

    # =========================================================================
    # CONTROLE DO CICLO DE VIDA
    # =========================================================================

    def stop(self) -> None:
        """
        Sinaliza o encerramento limpo do loop de processamento.

        Chamado por MainWindow em closeEvent() ou ao encerrar a sessão.
        Não força o desligamento imediato — o loop conclui o quadro atual
        e então verifica _stop_event na próxima iteração.

        Retorna:
            None. O encerramento real é assíncrono — use wait() para aguardar o bloqueio.
        """
        self._stop_event.set()

    def _cleanup(self) -> None:
        """
        Libera todos os recursos do pipeline após o término do loop.

        Chamado automaticamente ao final de run() quando o loop é encerrado.
        Garante que o MediaPipe libere a memória de GPU/CPU e o CSV seja fechado.

        Por que fechar o MediaPipe explicitamente?
            mp.solutions.hands.Hands mantém recursos do TensorFlow Lite internamente.
            Sem close(), esses recursos podem persistir até que o GC do Python colete
            o objeto — o que pode nunca acontecer até o término do processo, causando
            vazamentos de memória em sessões longas.
        """
        # Fecha o detector do MediaPipe e libera os recursos do modelo de ML.
        if self._hands is not None:
            self._hands.close()

        # Garante que o CSV seja fechado mesmo que stop_session() não tenha sido
        # explicitamente chamado (ex.: falha ou fechamento abrupto da janela).
        self.stop_session()
