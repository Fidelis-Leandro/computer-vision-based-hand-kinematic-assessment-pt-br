"""
workers/camera_worker.py — Thread de captura de quadros da câmera
=================================================================

Este módulo isola a captura de vídeo em uma thread dedicada (CameraWorker),
garantindo que a interface gráfica (MainWindow) nunca seja bloqueada à
espera dos quadros da câmera.

Problema resolvido por este módulo:
    cap.read() é uma chamada BLOQUEANTE: o programa é interrompido e aguarda
    até que um quadro chegue da câmera (~33ms a 30 FPS). Se essa espera
    ocorresse na thread principal, a janela do PyQt6 congelaria a cada quadro,
    tornando a interface não responsiva.

Solução:
    CameraWorker executa em sua própria thread via QThread. Ele captura quadros
    em um laço contínuo e os entrega à thread principal via pyqtSignal —
    mecanismo de comunicação seguro entre threads (thread-safe) do Qt.

Fluxo de dados:
    Câmera -> cap.read() -> espelhamento horizontal -> pyqtSignal(frame_bgr)
                                                              |
                                                   ProcessingWorker.put_frame()

Regras seguidas:
    - Widgets NUNCA são chamados de dentro desta thread.
    - time.sleep ou chamadas bloqueantes NUNCA são usadas na thread principal.
    - Toda comunicação com a interface é via pyqtSignal (segura por concepção).
"""

import sys
import threading
import time
from typing import Optional

import cv2
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

# Importa todas as constantes do arquivo de configuração centralizado.
# NUNCA utilize números mágicos neste módulo — sempre via config.
import config


class CameraWorker(QThread):
    """
    Thread de captura de vídeo em tempo real utilizando OpenCV.

    Herda de QThread (e não de threading.Thread) porque o Qt exige que
    toda comunicação com a interface gráfica passe pelo seu próprio sistema
    de sinais (pyqtSignal). Threads puras do Python não possuem acesso ao laço
    de eventos do Qt e causariam falhas ao tentar atualizar widgets.

    Ciclo de vida:
        1. Instanciado por MainWindow em __init__() — ainda não iniciado.
        2. camera_worker.start() é chamado quando a sessão é iniciada.
        3. O Qt chama run() automaticamente em uma thread separada.
        4. camera_worker.stop() é chamado quando a sessão é encerrada ou a janela é fechada.
        5. O laço é encerrado e cap.release() libera a câmera.

    Sinais emitidos (comunicação thread-safe com MainWindow):
        frame_ready(np.ndarray) : quadro BGR capturado, espelhado e pronto
                                  para processamento pelo ProcessingWorker.
        fps_updated(float)      : taxa de quadros atual, calculada com EMA.
                                  Recebida pelo MetricsWidget para exibição.
        camera_error(str)       : mensagem de erro para o LogWidget quando a
                                  câmera não puder ser aberta ou travar.
    """

    # --- Definições de sinais ---
    # pyqtSignal declara os tipos de dados carregados por cada sinal.
    # O Qt utiliza isso para roteamento seguro entre threads.

    # Carrega um array NumPy BGR — o quadro capturado e espelhado.
    frame_ready: pyqtSignal = pyqtSignal(np.ndarray)

    # Carrega um float — o FPS suavizado para exibição na interface.
    fps_updated: pyqtSignal = pyqtSignal(float)

    # Carrega uma string — mensagem de erro legível por humanos para o LogWidget.
    camera_error: pyqtSignal = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        """
        Inicializa o CameraWorker com um estado inicial seguro.

        Apenas configura atributos internos. A câmera NÃO é aberta aqui —
        isso ocorre em run() quando a thread é iniciada. Esta separação é
        importante: __init__ executa na thread principal, enquanto a câmera
        deve ser aberta e utilizada exclusivamente na thread trabalhadora (worker thread).

        Parâmetros:
            parent: widget pai do Qt (opcional). Utilizado pelo Qt para gerenciar o
                    ciclo de vida do objeto. Normalmente None para workers.
        """
        super().__init__(parent)

        # Evento de thread usado para sinalizar que o laço deve parar.
        # Utilizamos threading.Event (e não um booleano simples) porque ele é
        # seguro entre threads (thread-safe): pode ser lido/escrito de qualquer
        # thread sem condições de corrida.
        self._stop_event: threading.Event = threading.Event()

        # Referência ao objeto da câmera. Inicialmente None porque a câmera
        # só é aberta quando run() é chamado pela thread trabalhadora.
        self._cap: Optional[cv2.VideoCapture] = None

        # Armazena o FPS suavizado por EMA entre as emissões.
        # Inicializado em 0.0 para indicar que nenhum quadro foi capturado ainda.
        self._fps_ema: float = 0.0

        # Contador de quadros capturados com sucesso nesta execução.
        # Utilizado para controlar a frequência de emissão do sinal fps_updated.
        self._frame_count: int = 0

    # =========================================================================
    # ABERTURA DA CÂMERA
    # =========================================================================

    def _open_camera(self) -> Optional[cv2.VideoCapture]:
        """
        Tenta abrir a câmera com a melhor configuração disponível.

        Estratégia de contingência (fallback):
            1. Tenta CAP_DSHOW (DirectShow — backend nativo do Windows).
               CAP_DSHOW reduz significativamente a latência no Windows ao
               eliminar a camada de abstração genérica do driver. Sem ele,
               cada cap.read() pode ter 50–150ms de latência adicional.
            2. Se CAP_DSHOW falhar (Linux/macOS ou driver incompatível),
               tenta o backend padrão do OpenCV (automático pelo SO).
            3. Se ambos falharem, retorna None para que run() possa emitir
               camera_error e sair do laço com segurança.

        Retorna:
            cv2.VideoCapture: objeto de câmera aberto e configurado, ou
            None caso a câmera não possa ser aberta.
        """
        # CAP_DSHOW é exclusivo do Windows — tentativa apenas nesta plataforma.
        # No Linux/macOS, cv2.CAP_DSHOW não existe ou é ignorado.
        if sys.platform == "win32":
            cap = cv2.VideoCapture(config.CAMERA_INDEX, cv2.CAP_DSHOW)

            # Verifica se CAP_DSHOW abriu com sucesso antes de configurar.
            if cap.isOpened():
                self._configure_camera(cap)
                return cap

            # Se CAP_DSHOW falhou, libera antes de tentar novamente.
            cap.release()

        # Fallback: backend padrão do OpenCV (V4L2 no Linux, AVFoundation no macOS).
        cap = cv2.VideoCapture(config.CAMERA_INDEX)

        if cap.isOpened():
            self._configure_camera(cap)
            return cap

        # Nenhum backend funcionou — a câmera está indisponível.
        return None

    def _configure_camera(self, cap: cv2.VideoCapture) -> None:
        """
        Aplica as configurações de resolução e FPS ao objeto da câmera.

        O OpenCV não garante que o driver respeitará os ajustes solicitados —
        ele tenta, mas a câmera pode retornar a resolução suportada mais próxima.
        Utilizamos CAP_PROP_BUFFERSIZE = 1 para garantir que o buffer interno do driver
        mantenha no máximo 1 quadro em fila, mantendo a latência mínima
        independentemente da resolução real.

        Parâmetros:
            cap: objeto cv2.VideoCapture já aberto e válido.
        """
        # Solicita a resolução definida em config.py.
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.CAMERA_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.CAMERA_HEIGHT)

        # Solicita o FPS desejado ao driver.
        cap.set(cv2.CAP_PROP_FPS, config.TARGET_FPS)

        # Define o buffer interno do driver para 1 quadro.
        # Com buffers maiores (padrão = 4 no Windows), cap.read() retorna
        # quadros ANTIGOS do buffer antes de capturar o quadro atual.
        # Isso causa latência acumulada: a imagem exibida fica cada vez mais
        # atrasada em relação ao movimento real. Com BUFFERSIZE = 1,
        # recebemos sempre o quadro mais recente.
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    # =========================================================================
    # LAÇO PRINCIPAL (executa na thread dedicada)
    # =========================================================================

    def run(self) -> None:
        """
        Método principal do QThread — chamado automaticamente pelo Qt quando
        camera_worker.start() é executado. Executa inteiramente na thread trabalhadora,
        nunca na thread principal.

        Este método NÃO DEVE ser chamado diretamente. Utilize start() para
        iniciar a thread corretamente.

        Fluxo interno:
            1. Tenta abrir a câmera.
            2. Em caso de falha, emite camera_error e encerra.
            3. Laço de captura: cap.read() -> flip -> calcula FPS -> emite sinais.
            4. Ao parar (_stop_event ativado ou falhas consecutivas), libera a câmera.

        Retorna:
            None. Os resultados são entregues via pyqtSignal (frame_ready, etc.).
        """
        # Tenta abrir a câmera antes de entrar no laço.
        self._cap = self._open_camera()

        if self._cap is None:
            # Emitir o sinal de erro é seguro entre threads (thread-safe): o Qt roteará a chamada
            # para a thread principal automaticamente, onde reside o LogWidget.
            self.camera_error.emit(
                f"Não foi possível abrir a câmera (índice {config.CAMERA_INDEX}). "
                "Verifique se ela está conectada e não está em uso por outro programa."
            )
            return

        # Contador de falhas consecutivas de cap.read().
        # Se este contador atingir o limite, interpretamos como falha de hardware.
        consecutive_failures: int = 0

        # Limite de falhas antes de parar. ~10 falhas consecutivas a ~30fps = ~333ms
        # sem resposta da câmera, indicando travamento real.
        max_consecutive_failures: int = 10

        # Timestamp do último quadro capturado com sucesso — para cálculo de FPS.
        t_last: float = time.perf_counter()

        # Laço principal de captura — executa até stop() ser chamado
        # ou o limite de falhas consecutivas ser atingido.
        while not self._stop_event.is_set():

            # cap.read() é BLOQUEANTE: aguarda até que um quadro esteja disponível.
            # Retorna (True, frame) em caso de sucesso ou (False, None) em falha.
            ret, frame = self._cap.read()

            if not ret or frame is None:
                consecutive_failures += 1

                if consecutive_failures >= max_consecutive_failures:
                    # A câmera parou de responder por tempo suficiente para ser considerada
                    # uma falha real de hardware (desconexão, driver, etc.)
                    self.camera_error.emit(
                        f"Conexão com a câmera perdida após {max_consecutive_failures} quadros "
                        "inválidos consecutivos. Verifique a conexão USB."
                    )
                    break

                # Aguarda 10ms antes de tentar novamente.
                # Sem esta pausa, o laço rodaria em velocidade máxima consumindo
                # 100% de um núcleo da CPU apenas tentando ler quadros inválidos.
                time.sleep(0.01)
                continue

            # Quadro válido — reinicia o contador de falhas.
            consecutive_failures = 0
            self._frame_count += 1

            # Espelhamento horizontal do quadro.
            # O MediaPipe opera com a imagem original, mas da perspectiva do
            # usuário, ver a própria mão espelhada (como em um espelho físico)
            # é mais intuitivo para posicionar a mão na câmera.
            # cv2.flip(frame, 1): 1 = eixo vertical (espelhamento horizontal).
            frame = cv2.flip(frame, 1)

            # Calcula o FPS real e atualiza o valor suavizado por EMA.
            self._update_fps(t_last)
            t_last = time.perf_counter()

            # Emite o quadro capturado para qualquer slot conectado.
            # Em produção, o ProcessingWorker o recebe via put_frame().
            # O sinal é thread-safe por concepção do Qt — sem risco de condição
            # de corrida ao emitir de dentro desta thread.
            self.frame_ready.emit(frame)

            # Emite o FPS suavizado a cada N quadros para evitar sobrecarregar a interface.
            # Emitir a cada quadro (30x/s) sobrecarregaria desnecessariamente o
            # MetricsWidget com atualizações rápidas demais para o olho humano perceber.
            # A cada 30 quadros ≈ uma vez por segundo é suficiente.
            if self._frame_count % 30 == 0:
                self.fps_updated.emit(self._fps_ema)

        # --- Limpeza após o laço ---
        # Laço encerrado (por stop() ou por falha). Libera recursos da câmera.
        self._release_camera()

    # =========================================================================
    # CÁLCULO DE FPS
    # =========================================================================

    def _update_fps(self, t_last: float) -> None:
        """
        Atualiza o FPS suavizado utilizando Média Móvel Exponencial (EMA).

        Por que EMA em vez de uma média simples?
            A média simples (total_quadros / tempo_total) possui dois problemas:
            1. Reage muito lentamente a variações de desempenho (necessita de muitos quadros
               para refletir a velocidade atual).
            2. Nunca "esquece" quadros antigos — se o sistema esteve lento por 1 segundo
               no início, isso afeta a média de toda a sessão.

            O EMA com α=0.15 resolve ambos:
            - Reage rapidamente a mudanças (α controla a capacidade de resposta).
            - "Esquece" gradualmente valores antigos, mantendo o valor suavizado estável.
            - Computacionalmente trivial: apenas uma multiplicação e uma adição.

        Parâmetros:
            t_last: timestamp (em segundos) do quadro anterior, obtido via
                    time.perf_counter(). Utilizado para calcular o intervalo de tempo (dt).
        """
        t_now: float = time.perf_counter()
        dt: float = t_now - t_last

        # Proteção contra divisão por zero: se dt for absurdamente pequeno
        # (dois quadros no mesmo instante — impossível na prática, mas defensivo),
        # ignoramos a atualização de FPS para evitar valores infinitos.
        if dt <= 0.0:
            return

        # FPS instantâneo para este quadro: inverso do intervalo entre quadros.
        fps_instant: float = 1.0 / dt

        # Fator de suavização EMA — α=0.15 (15% valor novo + 85% histórico).
        # Ajustado empiricamente: suaviza picos de FPS causados por variações de
        # latência do driver da câmera sem introduzir atraso visível no indicador de FPS.
        ema_alpha: float = 0.15

        if self._fps_ema == 0.0:
            # Na primeira leitura, inicializa com o valor instantâneo.
            # Utilizar a fórmula EMA aqui puxaria o FPS para baixo a partir de 0.0
            # pelas primeiras dezenas de quadros.
            self._fps_ema = fps_instant
        else:
            # Fórmula EMA: novo = α × atual + (1-α) × anterior
            self._fps_ema = ema_alpha * fps_instant + (1.0 - ema_alpha) * self._fps_ema

    # =========================================================================
    # CONTROLE DE CICLO DE VIDA
    # =========================================================================

    def stop(self) -> None:
        """
        Sinaliza o encerramento seguro do laço de captura.

        Chamado pela thread principal (por exemplo, quando a sessão é encerrada
        ou a janela é fechada). NÃO força a thread a parar imediatamente — o laço
        verifica o evento a cada iteração e sai na oportunidade seguinte.

        Por que threading.Event em vez de um booleano simples?
            Booleanos puros do Python não são thread-safe: leituras e escritas de
            threads diferentes podem resultar em dados corrompidos (condição de corrida).
            threading.Event utiliza primitivas de sincronização em nível de SO que
            garantem acesso seguro a partir de qualquer thread sem travas manuais.

        Retorna:
            None. O encerramento real ocorre assincronamente no laço de run().
        """
        self._stop_event.set()

    def _release_camera(self) -> None:
        """
        Libera os recursos da câmera com segurança quando a thread é encerrada.

        Por que liberar explicitamente?
            O Python possui coleta de lixo automática, mas não garante QUANDO
            um objeto será destruído. Se cap.release() não for chamado
            explicitamente, o driver da câmera pode permanecer ocupado, impedindo
            outros programas (ou uma nova instância nossa) de abrir a câmera.

            No Windows, isso resulta no erro: "a câmera já está em uso
            por outro processo" ao tentar reiniciar a aplicação sem fechar
            o processo anterior.

        Retorna:
            None.
        """
        if self._cap is not None and self._cap.isOpened():
            # Libera o descritor da câmera no driver do sistema operacional.
            self._cap.release()

        # Redefine a referência para None para evitar uso acidental após a liberação.
        self._cap = None

    def is_camera_open(self) -> bool:
        """
        Verifica se a câmera está atualmente aberta e disponível.

        Útil para verificações de estado na MainWindow antes de tentar iniciar
        uma nova sessão de captura.

        Retorna:
            bool: True se a câmera estiver aberta e operacional, False caso contrário.
        """
        return self._cap is not None and self._cap.isOpened()
