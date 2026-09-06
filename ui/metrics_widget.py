"""
ui/metrics_widget.py — Painel de métricas do sistema e estado da mão
===================================================================

Este módulo implementa o MetricsWidget: um painel lateral que exibe em
tempo real as métricas de desempenho do sistema (FPS, CPU, RAM) e o
estado clínico da mão (aberta/fechada, contagem de dedos, identificação).

Responsabilidade:
    Receber um ProcessingResult pronto (calculado pelo ProcessingWorker) e
    atualizar os cards visuais correspondentes. Não executa cálculos — apenas
    formata e exibe os dados recebidos.

Layout dos cards (grade de 2 linhas × 3 colunas):
    ┌──────────┬──────────┬──────────┐
    │   FPS    │   CPU    │   RAM    │
    ├──────────┼──────────┼──────────┤
    │ Quadro # │  Estado  │  Estado  │
    │          │  (mão)   │ (amplo)  │
    └──────────┴──────────┴──────────┘

    O card de Estado da Mão ocupa 2 colunas na segunda linha para ter
    espaço suficiente para textos como "🟢 MÃO ABERTA (X/5)" e "🔴 MÃO FECHADA".

Integração na MainWindow:
    self.metrics_widget = MetricsWidget()
    processing_worker.result_ready.connect(
        lambda result: self.metrics_widget.update_from_result(result)
    )
"""

from typing import Optional, Tuple

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# Importa estilos centralizados a partir do módulo de tema escuro.
from themes import (
    CARD_STYLE,
    CARD_HAND_CLOSED_STYLE,
    CARD_HAND_OPEN_STYLE,
    LABEL_HAND_STATE_STYLE,
    LABEL_TITLE_STYLE,
    LABEL_VALUE_STYLE,
)

# Importa a dataclass de resultado do worker para tipagem correta.
# A importação condicional evita importações circulares caso os módulos sejam reorganizados.
from workers.processing_worker import ProcessingResult

# Tenta importar psutil para coleta de métricas do sistema operacional.
# psutil é uma dependência OPCIONAL: se não estiver instalado, os cards de CPU e RAM
# exibem "—" em vez de lançar uma exceção fatal.
try:
    import psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    _PSUTIL_AVAILABLE = False


class _MetricCard(QWidget):
    """
    Card visual reutilizável para exibição de uma única métrica.

    Cada card possui:
    - Um contêiner QFrame com borda arredondada (aparência visual de "card").
    - Um QLabel de título (ex.: "FPS") em texto secundário pequeno.
    - Um QLabel de valor (ex.: "58.3") em texto grande em negrito.

    Este componente interno (_MetricCard, sublinhado = privado do módulo)
    é instanciado pelo MetricsWidget para cada métrica. Centralizar a
    lógica de construção aqui evita repetição de código para os 5 cards.
    """

    def __init__(
        self,
        title: str,
        initial_value: str = "—",
        parent: Optional[QWidget] = None,
    ) -> None:
        """
        Constrói um card de métrica com título e valor inicial.

        Parâmetros:
            title: Rótulo estático exibido no topo do card. Ex.: "FPS", "CPU".
            initial_value: Valor exibido antes da chegada de dados reais.
                           O padrão "—" indica "nenhum dado disponível".
            parent: Widget pai do Qt (opcional).
        """
        super().__init__(parent)

        # Layout interno vertical: título em cima, valor abaixo.
        layout = QVBoxLayout(self)
        # Margens internas pequenas para não desperdiçar espaço no painel lateral.
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)

        # Contêiner com borda arredondada (o estilo provém de themes.py).
        self._frame = QFrame()
        self._frame.setStyleSheet(CARD_STYLE)

        frame_layout = QVBoxLayout(self._frame)
        frame_layout.setContentsMargins(8, 6, 8, 6)
        frame_layout.setSpacing(2)
        frame_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Rótulo de título — texto pequeno em cinza secundário.
        self._label_title = QLabel(title)
        self._label_title.setStyleSheet(LABEL_TITLE_STYLE)
        self._label_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Rótulo de valor — texto grande em negrito, ênfase visual.
        self._label_value = QLabel(initial_value)
        self._label_value.setStyleSheet(LABEL_VALUE_STYLE)
        self._label_value.setAlignment(Qt.AlignmentFlag.AlignCenter)

        frame_layout.addWidget(self._label_title)
        frame_layout.addWidget(self._label_value)

        layout.addWidget(self._frame)

        # Permite que o card encolha verticalmente sem distorcer o layout.
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

    def set_value(self, value: str) -> None:
        """
        Atualiza o texto do rótulo de valor do card.

        Chamado pelos métodos de atualização do MetricsWidget a cada novo resultado.

        Parâmetros:
            value: String formatada para exibição. Ex.: "58.3", "23%", "4.1 GB".
        """
        self._label_value.setText(value)

    def set_frame_style(self, style: str) -> None:
        """
        Substitui o estilo visual do QFrame interno (cor de fundo, borda).

        Utilizado pelo card de Estado da Mão para alternar entre fundo verde
        (mão aberta) e fundo vermelho (mão fechada).

        Parâmetros:
            style: String de folha de estilos Qt para o QFrame.
                   Geralmente CARD_HAND_OPEN_STYLE ou CARD_HAND_CLOSED_STYLE.
        """
        self._frame.setStyleSheet(style)


class HandStateCard(QWidget):
    """
    Card especializado para exibição do estado clínico da mão.

    Diferente dos outros cards (_MetricCard), este exibe:
    - Ícone colorido (🟢 ou 🔴).
    - Texto grande indicando ABERTA ou FECHADA.
    - Contagem de dedos fechados entre parênteses: "(X/5)".
    - Fundo que altera de cor (verde / vermelho) de acordo com o estado.

    A alteração da cor de fundo é o elemento mais importante: permite
    ao fisioterapeuta avaliar o estado da mão com uma rápida olhada lateral,
    sem precisar ler o texto.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """
        Inicializa o card de estado com o visual padrão (sem dados).

        Parâmetros:
            parent: Widget pai do Qt (opcional).
        """
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)

        # Contêiner principal do card.
        self._frame = QFrame()
        self._frame.setStyleSheet(CARD_STYLE)

        frame_layout = QVBoxLayout(self._frame)
        frame_layout.setContentsMargins(10, 8, 10, 8)
        frame_layout.setSpacing(4)
        frame_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Rótulo de título estático.
        self._label_title = QLabel("ESTADO DA MÃO")
        self._label_title.setStyleSheet(LABEL_TITLE_STYLE)
        self._label_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Rótulo principal de estado — texto grande, altera com base na detecção.
        self._label_state = QLabel("⬜ AGUARDANDO")
        self._label_state.setStyleSheet(LABEL_HAND_STATE_STYLE)
        self._label_state.setAlignment(Qt.AlignmentFlag.AlignCenter)

        frame_layout.addWidget(self._label_title)
        frame_layout.addWidget(self._label_state)

        layout.addWidget(self._frame)

        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

    def update_state(self, hand_open: bool, closed_count: int, hand_detected: bool) -> None:
        """
        Atualiza o estado visual completo do card da mão.

        Altera simultaneamente:
        1. O texto e o ícone (🟢/🔴).
        2. A cor de fundo do quadro (verde/vermelho).

        Quando nenhuma mão é detectada, exibe um estado neutro sem cor de alerta
        para não confundir o clínico durante o posicionamento da câmera.

        Parâmetros:
            hand_open: True se a mão for considerada aberta (maioria dos dedos
                       com TAM acima do limiar), False se fechada.
            closed_count: Número de dedos considerados fechados (0–5).
            hand_detected: True se o MediaPipe encontrou uma mão neste quadro.
        """
        if not hand_detected:
            # Nenhuma mão detectada: estado neutro sem indicação de erro.
            self._frame.setStyleSheet(CARD_STYLE)
            self._label_state.setText("⬜ SEM DETECÇÃO")
            return

        # Calcula quantos dedos estão abertos (complemento dos fechados).
        # Exibimos dedos ABERTOS porque é mais intuitivo clinicamente:
        # "2/5 dedos abertos" comunica o grau de abertura, não de fechamento.
        open_count: int = 5 - closed_count

        if hand_open:
            # Fundo verde escuro: mão considerada aberta — estado funcional positivo.
            self._frame.setStyleSheet(CARD_HAND_OPEN_STYLE)
            self._label_state.setText(f"🟢 MÃO ABERTA ({open_count}/5)")
        else:
            # Fundo vermelho escuro: mão considerada fechada — alerta clínico.
            self._frame.setStyleSheet(CARD_HAND_CLOSED_STYLE)
            self._label_state.setText(f"🔴 MÃO FECHADA ({open_count}/5)")


# =============================================================================
# WIDGET PRINCIPAL
# =============================================================================

class MetricsWidget(QGroupBox):
    """
    Painel lateral para métricas do sistema e estado clínico da mão.

    Organiza cards individuais em uma grade 2×3 e conecta as fontes de dados
    (ProcessingResult e psutil) a cada card correspondente.

    Hierarquia do widget:
        MetricsWidget (QGroupBox)
        └── QGridLayout
            ├── _MetricCard("FPS")          [linha 0, coluna 0]
            ├── _MetricCard("CPU")          [linha 0, coluna 1]
            ├── _MetricCard("RAM")          [linha 0, coluna 2]
            ├── _MetricCard("Quadro #")     [linha 1, coluna 0]
            └── HandStateCard               [linha 1, colunas 1–2, colspan=2]
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """
        Inicializa o MetricsWidget com todos os cards e o timer do sistema.

        O QTimer do sistema (_stats_timer) é iniciado aqui e dispara a cada
        1000ms para atualizar CPU e RAM independentemente dos quadros processados.
        Isso garante que as métricas do sistema permaneçam atualizadas mesmo quando a câmera
        não estiver ativa (ex.: estado IDLE).

        Parâmetros:
            parent: Widget pai do Qt (opcional).
        """
        super().__init__("Métricas do Sistema", parent)

        # Grade de 2 linhas × 3 colunas para os cards de métricas.
        self._grid = QGridLayout(self)
        self._grid.setSpacing(8)
        self._grid.setContentsMargins(10, 16, 10, 10)

        # --- Linha 0: métricas de desempenho ---

        # FPS do pipeline de processamento (não o FPS da câmera).
        # Reflete a velocidade REAL do ProcessingWorker.
        self._card_fps = _MetricCard("FPS", "—")

        # Porcentagem de uso geral da CPU do sistema.
        # psutil.cpu_percent() mede todos os núcleos.
        self._card_cpu = _MetricCard("CPU", "—")

        # Uso de RAM em Gigabytes.
        # Importante monitorar: MediaPipe + buffers podem consumir memória significativa.
        self._card_ram = _MetricCard("RAM", "—")

        self._grid.addWidget(self._card_fps, 0, 0)
        self._grid.addWidget(self._card_cpu, 0, 1)
        self._grid.addWidget(self._card_ram, 0, 2)

        # --- Linha 1: contador de quadros + estado da mão ---

        # Contador de quadros processados para esta sessão.
        # Útil para correlacionar eventos de log com quadros no CSV.
        self._card_frame = _MetricCard("Quadro #", "—")

        # Card especializado com mudança de cor para o estado da mão.
        # Ocupa 2 colunas (colspan=2) para ter espaço para o texto completo.
        self._card_hand = HandStateCard()

        self._grid.addWidget(self._card_frame, 1, 0)

        # colspan=2: o card de estado ocupa as colunas 1 e 2 da linha 1.
        # Isso dá mais espaço horizontal para textos como "MÃO ABERTA (5/5)".
        self._grid.addWidget(self._card_hand, 1, 1, 1, 2)

        # Garante que as 3 colunas da grade tenham peso igual.
        # Sem isso, colunas com conteúdo menor ficariam mais estreitas.
        for col in range(3):
            self._grid.setColumnStretch(col, 1)

        # Estado do modo clínico (True = oculta telemetria; False = modo completo).
        self._clinical_mode: bool = False

        # --- Timer de atualização das métricas do sistema ---
        # Dispara a cada 1000ms (1 segundo) — taxa adequada para CPU e RAM.
        # Atualizar mais rápido não traria informações úteis adicionais, pois
        # psutil.cpu_percent() já aplica suavização interna.
        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(1000)
        self._stats_timer.timeout.connect(self._update_system_stats)

        # Inicia o timer imediatamente — exibe valores de CPU/RAM desde o
        # início, mesmo antes de a câmera ser ligada.
        self._stats_timer.start()

        # Força a primeira leitura de CPU/RAM imediatamente na criação do widget.
        self._update_system_stats()

    # =========================================================================
    # CONTROLE DE MODO CLÍNICO
    # =========================================================================

    def set_clinical_mode(self, enabled: bool = True) -> None:
        """
        Alterna entre o modo de métricas completo e o modo clínico simplificado.

        No modo clínico (enabled=True):
        - Oculta os cards de telemetria de hardware (FPS, CPU, RAM, Quadro #).
        - Reposiciona o HandStateCard para ocupar a largura total da grade (linha 0, colunas 0-2).
        - Altera o título do grupo para 'Estado Clínico da Mão'.
        - Preserva a coleta de dados interna em update_from_result() e o timer psutil.

        No modo completo (enabled=False):
        - Restaura a visibilidade dos quatro cards de telemetria.
        - Reposiciona o HandStateCard na sua localização original (linha 1, colunas 1-2).
        - Restaura o título do grupo para 'Métricas do Sistema'.
        """
        if hasattr(self, "_clinical_mode") and self._clinical_mode == enabled:
            return

        self._clinical_mode = enabled

        if enabled:
            # 1. Oculta cards de telemetria de sistema
            self._card_fps.setVisible(False)
            self._card_cpu.setVisible(False)
            self._card_ram.setVisible(False)
            self._card_frame.setVisible(False)

            # 2. Atualiza título
            self.setTitle("Estado Clínico da Mão")

            # 3. Reposiciona o HandStateCard para ocupar a largura total (linha 0, colspan=3)
            self._grid.removeWidget(self._card_hand)
            self._grid.addWidget(self._card_hand, 0, 0, 1, 3)
            self._card_hand.setVisible(True)
        else:
            # 1. Atualiza título
            self.setTitle("Métricas do Sistema")

            # 2. Reposiciona o HandStateCard na posição original (linha 1, col 1, colspan=2)
            self._grid.removeWidget(self._card_hand)
            self._grid.addWidget(self._card_hand, 1, 1, 1, 2)
            self._card_hand.setVisible(True)

            # 3. Reexibe cards de telemetria de sistema
            self._card_fps.setVisible(True)
            self._card_cpu.setVisible(True)
            self._card_ram.setVisible(True)
            self._card_frame.setVisible(True)

    # =========================================================================
    # ATUALIZAÇÃO COM DADOS DE PROCESSAMENTO
    # =========================================================================

    def update_from_result(self, result: ProcessingResult) -> None:
        """
        Atualiza os cards de FPS, Quadro# e Estado da Mão com dados do worker.

        Chamado pela MainWindow a cada emissão do sinal result_ready
        do ProcessingWorker (~30 vezes/segundo). Deve ser rápido — apenas atualiza
        texto, sem cálculos ou acesso a disco.

        Parâmetros:
            result: ProcessingResult emitido pelo ProcessingWorker.
                    Contém fps, frame_id, hand_state e hand_detected.
        """
        # Formata o FPS com uma casa decimal para leitura estável.
        # Duas casas decimais causam oscilação visual ("jitter", ex.: 58.33 → 58.21 → 58.45),
        # dificultando a leitura. Uma casa decimal é suficiente para monitoramento.
        self._card_fps.set_value(f"{result.fps:.1f}")

        # Quadro# exibido sem formatação especial — é um inteiro sequencial simples.
        self._card_frame.set_value(str(result.frame_id))

        # Extrai o estado da mão do dicionário retornado por classify_hand_state().
        # Chaves esperadas: "mao_aberta" (bool) e "dedos_fechados" (int, 0–5).
        hand_open: bool = result.hand_state.get("mao_aberta", True)
        closed_count: int = result.hand_state.get("dedos_fechados", 0)

        # Propaga os dados para o card de estado especializado.
        self._card_hand.update_state(
            hand_open=hand_open,
            closed_count=closed_count,
            hand_detected=result.hand_detected,
        )

    # =========================================================================
    # ATUALIZAÇÃO DE MÉTRICAS DO SISTEMA (CPU E RAM)
    # =========================================================================

    def _update_system_stats(self) -> None:
        """
        Coleta e exibe métricas de desempenho do sistema operacional.

        Chamado pelo QTimer a cada 1000ms — desvinculado do processamento de quadros.
        CPU e RAM são recursos do sistema, não da câmera.

        Degradação suave:
            Se o psutil não estiver instalado, exibe "—" nos cards
            sem lançar exceção. Isso permite que a aplicação funcione
            corretamente em ambientes onde psutil não está disponível,
            apenas sem o monitoramento de recursos.

        Por que interval=None em cpu_percent()?
            psutil.cpu_percent(interval=N) BLOQUEARIA por N segundos.
            Com interval=None, retorna o valor calculado desde a última chamada,
            sem bloqueio. Como o chamamos a cada 1s via QTimer, o intervalo
            efetivo é sempre de ~1 segundo — ideal para monitoramento.
        """
        if not _PSUTIL_AVAILABLE:
            # psutil não instalado — exibe placeholder sem erro.
            self._card_cpu.set_value("—")
            self._card_ram.set_value("—")
            return

        try:
            # Porcentagem de uso da CPU (média de todos os núcleos).
            # interval=None: não bloqueante, utiliza o intervalo desde a última chamada.
            cpu_percent: float = psutil.cpu_percent(interval=None)
            self._card_cpu.set_value(f"{cpu_percent:.0f}%")

            # RAM em uso, convertida de bytes para Gigabytes.
            # 1024**3 = 1 GiB. Uma casa decimal para precisão adequada.
            ram_bytes: int = psutil.virtual_memory().used
            ram_gb: float = ram_bytes / (1024 ** 3)
            self._card_ram.set_value(f"{ram_gb:.1f} GB")

        except Exception as exc:
            # Captura erros inesperados do psutil (ex.: permissão negada
            # em alguns sistemas Linux com restrições de acesso ao /proc).
            # Não propaga o erro para não interromper o loop do QTimer.
            self._card_cpu.set_value("!")
            self._card_ram.set_value("!")

    # =========================================================================
    # CONTROLE DO TIMER
    # =========================================================================

    def start_monitoring(self) -> None:
        """
        Inicia ou reinicia o timer de monitoramento de CPU e RAM.

        Chamado pela MainWindow ao iniciar uma sessão, caso o timer
        tenha sido parado anteriormente por stop_monitoring().
        """
        if not self._stats_timer.isActive():
            self._stats_timer.start()

    def stop_monitoring(self) -> None:
        """
        Para o timer de monitoramento de CPU e RAM.

        Pode ser chamado pela MainWindow ao encerrar a sessão para reduzir
        a carga de CPU quando a aplicação estiver no estado STOPPED ou IDLE.
        O timer pode ser reiniciado com start_monitoring() a qualquer momento.
        """
        if self._stats_timer.isActive():
            self._stats_timer.stop()

    def reset_display(self) -> None:
        """
        Redefine todos os cards para o estado inicial "sem dados" (—).

        Chamado pela MainWindow ao iniciar uma nova sessão para limpar
        os valores da sessão anterior, evitando que dados antigos sejam
        confundidos com os da nova sessão durante o aquecimento inicial.
        """
        self._card_fps.set_value("—")
        self._card_frame.set_value("—")
        self._card_hand.update_state(
            hand_open=True,
            closed_count=0,
            hand_detected=False,
        )
