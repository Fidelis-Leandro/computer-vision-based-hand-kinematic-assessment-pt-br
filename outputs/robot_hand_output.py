"""
outputs/robot_hand_output.py — Worker de comunicação com a mão robótica (Arduino)
===================================================================================

Este módulo é o único ponto de contato entre a goniometria e o hardware da mão
robótica. Ele NÃO importa nada do projeto "Mão robo" (nem PySide6, nem
HubController, nem arduino_output.py) — é uma reimplementação limpa e mínima,
usando apenas pyfirmata + pyserial, seguindo o mesmo padrão de QThread já
usado por workers/camera_worker.py e workers/processing_worker.py nesta
mesma aplicação.

Responsabilidades:
    - Localizar e conectar à porta serial do Arduino (autodetecção por
      descrição da porta; nenhuma porta é assumida como fixa).
    - Configurar os 5 pinos como SERVO via StandardFirmata (pyfirmata).
    - Manter um loop de envio à taxa definida por SEND_INTERVAL_S (ver
      constante abaixo), independente da taxa de vídeo (~30 Hz).
    - Aplicar suavização (limite de variação por ciclo) e a regra de segurança
      "mão não detectada além do timeout de perda de mão -> posição aberta".
    - Encerrar de forma segura: posição aberta -> liberação da porta.

A escrita na porta serial NUNCA ocorre na thread da interface (Qt). Toda
comunicação com o Arduino acontece dentro de run(), executado pela QThread.

AVISOS DE SEGURANÇA (recomendações preventivas, não verificadas com
instrumento de medição — ver INTEGRACAO_MAO_ROBOTICA.md para o detalhamento
completo):
    - Os servos devem ser alimentados por fonte externa dedicada, nunca pelo
      USB do Arduino (o USB não fornece corrente suficiente para 5 servos
      fechando ao mesmo tempo).
    - A fonte externa dos servos e o Arduino devem compartilhar o mesmo GND.
    - Nunca executar este módulo e Mão robo/main.py ao mesmo tempo apontando
      para a mesma porta COM — os dois processos disputariam o mesmo Arduino.
    - Antes de qualquer alteração nos limites de servo (SERVO_CLOSED,
      MAX_STEP_PER_UPDATE), testar um servo por vez antes dos cinco juntos.
"""

import inspect
import logging
import threading
import time
from typing import Dict, List, Optional

# Polyfill de compatibilidade: o pyFirmata (versão 1.1.0, ver requirements.txt)
# chama inspect.getargspec() internamente durante o import. Essa função foi
# removida da biblioteca padrão do Python a partir da versão 3.11 (em favor de
# inspect.getfullargspec) — sem este polyfill, "import pyfirmata" levanta
# AttributeError e a conexão com o Arduino nunca chega a ser tentada.
#
# O mesmo polyfill também existe em outputs/__init__.py. Repetir aqui é
# defensivo: como outputs/robot_hand_output.py só é normalmente alcançado
# através de "import outputs.robot_hand_output" (o que já executa
# outputs/__init__.py primeiro), a cópia em __init__.py já seria suficiente
# no fluxo padrão da aplicação — mas isso deixa de ser garantido se este
# arquivo for importado de outra forma (ex.: um script de teste isolado que
# manipula sys.path diretamente para o pacote outputs/). Por isso o polyfill
# também é aplicado aqui.
#
# Remover ambas as cópias quando pyfirmata for substituído por uma alternativa
# mantida (ex.: pyfirmata2) que já seja compatível com Python 3.11+ nativamente.
if not hasattr(inspect, "getargspec"):
    inspect.getargspec = inspect.getfullargspec  # type: ignore[attr-defined]

from PyQt6.QtCore import QThread, pyqtSignal

from outputs.tam_to_servo import FINGER_ORDER, PIN_MAP, SERVO_OPEN

logger = logging.getLogger(__name__)

try:
    from pyfirmata import Arduino, SERVO
except ImportError:  # pragma: no cover - ambiente sem pyfirmata instalado
    Arduino = None
    SERVO = None

try:
    import serial.tools.list_ports
except ImportError:  # pragma: no cover - pyserial vem junto com pyfirmata
    serial = None  # type: ignore[assignment]


# =============================================================================
# CONSTANTES DE COMUNICAÇÃO
# =============================================================================

# Baud rate padrão do StandardFirmata. Não alterar sem reconfigurar o firmware
# do Arduino.
BAUD_RATE: int = 57600

# Taxa de envio ao Arduino: ~20 Hz (atualização rápida a cada 50ms)
SEND_INTERVAL_S: float = 1.0 / 20.0

# Após este intervalo sem detectar a mão, os servos vão para a posição aberta.
#
# Risco conhecido: o MediaPipe tende a perder ou degradar a detecção de
# landmarks exatamente quando a mão está mais fechada (dedos se sobrepõem e se
# ocluem mutuamente do ponto de vista da câmera). Se essa perda de detecção
# durar mais que HAND_LOST_TIMEOUT_S bem no momento em que o usuário consegue
# fechar a mão por completo, a mão robótica é reaberta automaticamente pela
# regra de segurança logo depois de fechar — um comportamento que pode
# parecer "ela não fica fechada", mas é a regra de segurança agindo como
# projetado diante de uma limitação de percepção do MediaPipe, não um bug de
# suavização. Ver "Limitações conhecidas e amplitude observada" em
# INTEGRACAO_MAO_ROBOTICA.md antes de alterar este valor.
HAND_LOST_TIMEOUT_S: float = 1.0

# Variação máxima de posição de servo por ciclo de envio. Com o valor 180, a
# diferença máxima possível entre SERVO_OPEN (0) e qualquer SERVO_CLOSED (no
# máximo 180) sempre cabe em um único ciclo — ou seja, _step_towards() é uma
# função identidade e este limitador não restringe a velocidade. Um valor
# menor limita o deslocamento por ciclo, o que é útil em testes iniciais.
#
# IMPORTANTE: responsividade total do servo (este valor) NÃO garante, por si
# só, que a mão feche completamente. A amplitude observada (ver
# INTEGRACAO_MAO_ROBOTICA.md) mostra que o TAM medido pela goniometria
# para indicador e polegar frequentemente não chega perto do teto configurado
# em outputs/tam_to_servo.TAM_MAX — nesse caso, tam_to_servo() nunca calcula a
# posição de "fechado" para esses dedos, e nenhum valor de
# MAX_STEP_PER_UPDATE resolveria isso, porque o problema está a montante
# (na entrada TAM), não na suavização de saída.
MAX_STEP_PER_UPDATE: int = 180

# Limite de iterações do laço de desligamento seguro (posição aberta antes de
# liberar a porta). Garante um "timeout" determinístico em vez de esperar
# indefinidamente por convergência. Tempo máximo real resultante =
# SHUTDOWN_MAX_STEPS * SEND_INTERVAL_S; com os valores atuais (30 * 0.05s),
# isso é até ~1,5s antes de a porta ser liberada.
SHUTDOWN_MAX_STEPS: int = 30

# Palavras-chave usadas para identificar portas candidatas a Arduino pela
# descrição relatada pelo sistema operacional.
PORT_KEYWORDS: tuple = ("arduino", "ch340", "ch341", "usb serial", "usb-serial", "cp210")

# Porta fixa opcional, usada apenas como ÚLTIMO recurso se a autodetecção por
# palavra-chave não encontrar nenhuma candidata. A autodetecção tem sempre
# prioridade. None = nenhum fallback fixo (recomendado).
DEFAULT_FALLBACK_PORT: Optional[str] = None


def _find_candidate_ports() -> List[str]:
    """
    Retorna portas candidatas a Arduino, na ordem em que devem ser tentadas.

    Prioriza portas cuja descrição contenha uma das PORT_KEYWORDS. Se nenhuma
    for encontrada, usa DEFAULT_FALLBACK_PORT (se configurado) como último
    recurso — nunca abre portas "às cegas" sem nenhum critério.

    Risco conhecido: a busca é por palavra-chave na descrição do sistema
    operacional, não por identidade de hardware (VID/PID). Se mais de um
    dispositivo conectado corresponder a uma das PORT_KEYWORDS (por exemplo,
    um adaptador USB-serial não relacionado ao Arduino, mas cuja descrição
    também contenha "usb serial" ou "ch340"), ambos entram na lista de
    candidatas e a ordem de tentativa passa a depender da ordem retornada
    pelo sistema operacional — não há garantia de que o Arduino da mão
    robótica seja tentado primeiro nesse cenário. Isso não é tratado como
    erro porque _connect_and_configure() já tenta cada candidata em sequência
    e segue para a próxima em caso de falha; o risco real é conectar com
    sucesso na porta errada (um dispositivo diferente que também aceite a
    conexão serial), não uma falha visível.
    """
    if serial is None:
        return []

    candidates: List[str] = []
    try:
        ports = list(serial.tools.list_ports.comports())
    except Exception as exc:
        logger.warning("Falha ao listar portas seriais: %s", exc)
        ports = []

    for p in ports:
        desc = (p.description or "").lower()
        if any(keyword in desc for keyword in PORT_KEYWORDS):
            candidates.append(p.device)

    if not candidates and DEFAULT_FALLBACK_PORT:
        candidates.append(DEFAULT_FALLBACK_PORT)

    return candidates


def _step_towards(current: int, target: int, max_step: int) -> int:
    """Move 'current' em direção a 'target', no máximo 'max_step' unidades."""
    diff = target - current
    if abs(diff) <= max_step:
        return target
    return current + max_step if diff > 0 else current - max_step


class RobotHandWorker(QThread):
    """
    Thread dedicada à comunicação com o Arduino da mão robótica.

    Sinais:
        connected_signal(bool): emitido uma vez, ao final da tentativa de
            conexão inicial. True = conectado e pinos configurados; False =
            falha (nenhuma porta candidata ou todas as tentativas falharam).
        error_signal(str): mensagem de erro legível, para log/status da UI.
        finished: sinal nativo de QThread, emitido quando run() retorna —
            usado pela UI para saber que o desligamento (seguro ou por
            erro) terminou por completo e a porta já foi liberada.
    """

    connected_signal = pyqtSignal(bool)
    error_signal = pyqtSignal(str)

    def __init__(
        self,
        parent=None,
        hand_lost_timeout_s: float = HAND_LOST_TIMEOUT_S,
    ) -> None:
        """
        Parâmetros:
            parent: pai Qt (ver QThread).
            hand_lost_timeout_s: tolerância sem detecção de mão antes da
                reabertura de segurança. O default é HAND_LOST_TIMEOUT_S
                (1.0s, perfil clínico) para todo chamador que não informar
                este argumento. O perfil "Evento" (demonstração em estande)
                passa um valor maior (1.5s, valor manual de demonstração)
                para tolerar mais a oclusão do MediaPipe durante o punho
                fechado — ver "Limitações conhecidas e amplitude observada"
                em INTEGRACAO_MAO_ROBOTICA.md. Guardado por instância, nunca
                escrito na constante de módulo: uma instância com timeout
                customizado não pode vazar esse valor para outra.
        """
        super().__init__(parent)

        self._stop_requested = threading.Event()
        self._lock = threading.Lock()

        # Últimos alvos válidos recebidos de MainWindow._on_result(), um por dedo.
        self._current_targets: Dict[str, int] = {f: SERVO_OPEN[f] for f in FINGER_ORDER}
        # Posição real (suavizada) que foi escrita no servo pela última vez.
        self._servo_state: Dict[str, int] = {f: SERVO_OPEN[f] for f in FINGER_ORDER}

        self._hand_detected: bool = False
        self._last_hand_time: Optional[float] = None
        self._hand_lost_timeout_s: float = hand_lost_timeout_s

        self._board = None
        self._port: Optional[str] = None
        self._connection_lost: bool = False

    # =========================================================================
    # API PÚBLICA — chamada pela thread principal (Qt)
    # =========================================================================

    def update_targets(self, positions: Dict[str, Optional[int]], hand_detected: bool) -> None:
        """
        Atualiza os alvos de servo a partir do resultado do pipeline goniométrico.

        Thread-safe: apenas grava valores sob lock, sem nenhuma E/S. Chamado
        pela thread principal a cada ProcessingResult (~30 Hz); o loop de
        envio real roda de forma independente, a SEND_INTERVAL_S.

        Parâmetros:
            positions: {"polegar": int|None, "indicador": int|None, ...}.
                       Um valor None mantém o alvo anterior daquele dedo
                       específico (dado inválido/ausente naquele quadro).
            hand_detected: se a mão foi detectada neste quadro.
        """
        with self._lock:
            for finger, pos in positions.items():
                if pos is not None and finger in self._current_targets:
                    self._current_targets[finger] = pos

            self._hand_detected = hand_detected
            if hand_detected:
                self._last_hand_time = time.monotonic()

    def request_stop(self) -> None:
        """
        Solicita o encerramento seguro (posição aberta + liberação da porta).

        Não bloqueia quem chama. O encerramento real acontece dentro de
        run() (thread do worker); a UI é notificada via o sinal nativo
        'finished' quando o processo estiver completo.
        """
        self._stop_requested.set()

    # =========================================================================
    # LOOP PRINCIPAL — executado na thread do worker
    # =========================================================================

    def run(self) -> None:
        if Arduino is None:
            self.error_signal.emit("Biblioteca pyfirmata não instalada.")
            self.connected_signal.emit(False)
            return

        if not self._connect_and_configure():
            self.connected_signal.emit(False)
            return

        self.connected_signal.emit(True)

        try:
            while not self._stop_requested.is_set() and not self._connection_lost:
                cycle_start = time.monotonic()
                self._send_cycle()
                elapsed = time.monotonic() - cycle_start
                remaining = SEND_INTERVAL_S - elapsed
                if remaining > 0:
                    # wait() em vez de sleep(): acorda imediatamente se
                    # request_stop() for chamado, sem esperar o ciclo inteiro.
                    self._stop_requested.wait(timeout=remaining)
        finally:
            self._safe_shutdown()

    def _connect_and_configure(self) -> bool:
        """Tenta conectar e configurar os 5 pinos, testando cada porta candidata."""
        candidates = _find_candidate_ports()

        if not candidates:
            self.error_signal.emit(
                "Nenhuma porta candidata a Arduino encontrada "
                f"(procurado por: {', '.join(PORT_KEYWORDS)})."
            )
            return False

        for port in candidates:
            board = None
            try:
                board = Arduino(port, baudrate=BAUD_RATE)
                for pin in PIN_MAP.values():
                    board.digital[pin].mode = SERVO
                # Estado inicial seguro: todos os servos na posição aberta.
                for finger, pin in PIN_MAP.items():
                    board.digital[pin].write(SERVO_OPEN[finger])

                self._board = board
                self._port = port
                self._servo_state = {f: SERVO_OPEN[f] for f in FINGER_ORDER}
                logger.info("Mão robótica conectada na porta %s.", port)
                return True
            except Exception as exc:
                logger.warning("Falha ao conectar/configurar em %s: %s", port, exc)
                self._safe_release(board)
                continue

        self.error_signal.emit(
            f"Falha ao conectar em todas as portas candidatas: {', '.join(candidates)}."
        )
        return False

    def _send_cycle(self) -> None:
        """Um ciclo de envio: decide o alvo, suaviza, escreve nos 5 servos."""
        with self._lock:
            targets = dict(self._current_targets)
            hand_detected = self._hand_detected
            last_hand_time = self._last_hand_time

        now = time.monotonic()
        hand_lost_too_long = (
            not hand_detected
            and (last_hand_time is None or (now - last_hand_time) > self._hand_lost_timeout_s)
        )

        for finger in FINGER_ORDER:
            target = SERVO_OPEN[finger] if hand_lost_too_long else targets[finger]
            self._servo_state[finger] = _step_towards(
                self._servo_state[finger], target, MAX_STEP_PER_UPDATE
            )

        self._write_current_state()

    def _write_current_state(self) -> None:
        """Escreve self._servo_state nos 5 pinos. Marca perda de conexão em falha."""
        if self._board is None:
            return
        try:
            for finger, pin in PIN_MAP.items():
                self._board.digital[pin].write(self._servo_state[finger])
        except Exception as exc:
            logger.error("Conexão com o Arduino perdida durante o envio: %s", exc)
            self.error_signal.emit(f"Conexão com o Arduino perdida: {exc}")
            self._connection_lost = True

    def _safe_shutdown(self) -> None:
        """
        Move os 5 servos para a posição aberta (se a conexão ainda estiver
        viva) e libera a porta serial, com um número máximo e determinístico
        de passos (SHUTDOWN_MAX_STEPS) — o "timeout" do desligamento seguro.

        Comportamento se o Arduino for desconectado fisicamente durante o
        próprio desligamento: a exceção do board.digital[pin].write() dentro
        do loop é capturada (bloco except mais abaixo), registrada em log, e
        o loop de "mover para aberto" é interrompido imediatamente — não há
        nova tentativa de escrita. Em seguida, _safe_release() ainda é
        chamado normalmente para liberar o que restar da porta/objeto board;
        como a conexão física já não existe mais, isso é uma limpeza de
        estado em memória, não uma operação que depende do hardware responder.
        O resultado prático é que os servos podem não chegar à posição
        aberta nesse cenário específico (cabo já desconectado) — não há como
        evitar isso, já que não existe mais canal de comunicação com o Arduino.
        """
        if self._board is not None and not self._connection_lost:
            for _ in range(SHUTDOWN_MAX_STEPS):
                all_open = True
                for finger, pin in PIN_MAP.items():
                    target = SERVO_OPEN[finger]
                    if self._servo_state[finger] != target:
                        all_open = False
                    self._servo_state[finger] = _step_towards(
                        self._servo_state[finger], target, MAX_STEP_PER_UPDATE
                    )
                try:
                    for finger, pin in PIN_MAP.items():
                        self._board.digital[pin].write(self._servo_state[finger])
                except Exception as exc:
                    logger.warning("Erro ao mover para posição aberta no desligamento: %s", exc)
                    break
                if all_open:
                    break
                time.sleep(SEND_INTERVAL_S)

        self._safe_release(self._board)
        self._board = None

    @staticmethod
    def _safe_release(board) -> None:
        """Libera a placa/porta serial, sem levantar exceção em caso de falha."""
        if board is None:
            return
        try:
            board.exit()
        except Exception as exc:
            logger.warning("Erro ao liberar a porta serial: %s", exc)
