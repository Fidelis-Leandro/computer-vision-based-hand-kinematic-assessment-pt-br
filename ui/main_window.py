"""
ui/main_window.py — Janela principal e orquestrador do sistema
==============================================================

Este módulo implementa o MainWindow: o orquestrador da aplicação de goniometria PyQt6.
Instancia todos os componentes, conecta sinais entre threads e controla o ciclo
de vida completo da avaliação através de uma arquitetura multitelas desacoplada
gerenciada por um QStackedWidget central e uma barra fixa superior de encerramento.

Telas do sistema (QStackedWidget):
    - Página 1: Tela de Configuração da Sessão (formulário do paciente e início).
    - Página 0: Tela de Avaliação em Andamento (área rolável clínica com vídeo,
      métricas clínicas, gráficos temporais, cartões por dedo e gaveta de logs).
    - Página 2: Tela de Resultado da Sessão (resumo informativo e ações pós-sessão:
      geração de PDF sob demanda, exportação de CSV, nova avaliação e limpeza de dados).

Barra fixa superior de avaliação (_assessment_bar):
    - Localizada fora da área de rolagem clínica, no topo da janela principal.
    - Exibe o status da avaliação e o botão "■ Encerrar Sessão", garantindo
      acesso visual permanente e encerramento seguro com diálogo de confirmação.
    - Visível exclusivamente durante a avaliação clínica (Página 0 e estado RUNNING).

Responsabilidades do MainWindow:
    1. Instanciar e orquestrar as três páginas da interface e a barra fixa superior.
    2. Instanciar os workers (CameraWorker, ProcessingWorker) SEM iniciá-los.
    3. Conectar sinais dos workers aos widgets de forma thread-safe.
    4. Gerenciar a máquina de estados (IDLE → READY → RUNNING → STOPPED).
    5. Controlar o ciclo de vida dos workers (iniciar, parar, aguardar).
    6. Gerar o relatório PDF sob demanda sem congelar a interface (thread separada).
    7. Encerrar a aplicação de forma limpa ao fechar a janela.
    8. Controlar a mão robótica (Arduino) através de um único botão liga/desliga
       (btn_robot_hand, visível apenas durante RUNNING, na _assessment_bar):
       instancia e encerra o RobotHandWorker, e em cada ProcessingResult recebido
       encaminha angles_smooth convertido em posições de servo (via
       outputs.tam_to_servo.map_all) para o worker — sem nunca escrever na porta
       serial diretamente. Ver INTEGRACAO_MAO_ROBOTICA.md para o fluxo completo.

Máquina de estados:
    IDLE    → Estado inicial na Tela de Configuração. Câmera desligada.
    READY   → Nome do paciente preenchido. Botão "▶ Iniciar Avaliação" habilitado.
    RUNNING → Avaliação ativa na Tela 2. Gravação em CSV e barra fixa visível.
    STOPPED → Sessão encerrada. Transição para Tela 3 com ações pós-sessão disponíveis.

Fluxo de dados (thread-safe via pyqtSignal):
    CameraWorker ──frame_ready──► ProcessingWorker (via put_frame, fila)
    ProcessingWorker ──result_ready──► MainWindow._on_result()
    MainWindow._on_result() ──distribui──► VideoWidget, MetricsWidget,
                                           PlotWidget, FingerCardsPanel
    MainWindow._on_result() ──(se mão robótica LIGADA)──► outputs.tam_to_servo.map_all()
                                           ──► RobotHandWorker.update_targets()
"""

import logging
import os
import shutil
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

import config
from session_report import generate_pdf_report
from themes import (
    BUTTON_DANGER_STYLE,
    BUTTON_PRIMARY_STYLE,
    COLOR_ACCENT,
    COLOR_BG_DARK,
    COLOR_BG_MEDIUM,
    COLOR_DANGER,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_WARNING,
)

# Importa os workers.
from workers.camera_worker import CameraWorker
from workers.processing_worker import ProcessingResult, ProcessingWorker

# Importa o worker e o mapeamento da mão robótica (Arduino).
# Módulo independente: não importa nada do projeto "Mão robo".
from outputs.robot_hand_output import RobotHandWorker
from outputs.tam_to_servo import map_all as robot_hand_map_all

# Importa os widgets de interface.
from ui.finger_card_widget import FingerCardsPanel
from ui.log_widget import LogWidget
from ui.metrics_widget import MetricsWidget
from ui.plot_widget import GoniometryPlotWidget
from ui.session_header import SessionHeaderWidget
from ui.video_widget import VideoWidget

# Logger específico do módulo — facilita o rastreamento de eventos da janela.
logger = logging.getLogger(__name__)


# Modos de filtro oferecidos na tela de configuração, na ordem em que aparecem
# no seletor: o recomendado primeiro e RAW por último, para afastar o modo sem
# suavização do clique acidental de quem abre a lista com pressa.
#
# Cada entrada é (modo interno, rótulo visível, tooltip, linha de ajuda). O modo
# interno é a mesma string que smoothing.py e a coluna filter_mode do CSV usam —
# ela viaja como userData do QComboBox, sem nenhum dicionário de tradução
# paralelo na interface.
FILTER_MODE_OPTIONS = (
    (
        "EMA_KALMAN",
        "EMA + Kalman — recomendado",
        "Pipeline clínico validado (EMA seguido de Kalman). "
        "Elimina oscilação sem atraso perceptível.",
        "Pipeline clínico validado. Use este modo para avaliações reais.",
    ),
    (
        "EMA",
        "EMA — suavização exponencial",
        "Só média móvel exponencial. Mais simples e levemente mais responsivo, "
        "com mais oscilação residual.",
        "Suavização simples. Levemente mais responsivo, com mais oscilação residual.",
    ),
    (
        "KALMAN",
        "Kalman — filtro preditivo",
        "Só filtro preditivo. Bom para movimento contínuo; pode oscilar mais "
        "em movimentos bruscos.",
        "Filtro preditivo. Bom para movimento contínuo.",
    ),
    (
        "RAW",
        "Dados brutos (RAW) — sem suavização",
        "Sem nenhuma suavização. Uso para demonstração, comparação ou "
        "diagnóstico técnico — não recomendado para avaliação clínica.",
        "⚠ Sem suavização — os valores oscilam. Uso técnico/demonstração.",
    ),
)


# =============================================================================
# WORKER AUXILIAR PARA GERAÇÃO DE PDF
# =============================================================================

class _PdfGeneratorWorker(QThread):
    """
    Thread auxiliar para gerar o relatório PDF sem bloquear a interface.

    Por que generate_pdf_report() precisa de uma thread separada?
        A função generate_pdf_report() em session_report.py é PESADA:
        - Lê e analisa o arquivo CSV inteiro (pode ter milhares de linhas).
        - Gera múltiplos gráficos com Matplotlib (100–400ms cada).
        - Monta o PDF com FPDF (inclui renderização de imagens).
        Em hardware lento, esse processo pode levar de 5 a 15 segundos.
        Se rodasse na thread principal, a janela ficaria completamente congelada
        durante esse período — o SO exibiria "Aplicação Sem Resposta",
        e o usuário poderia forçar o fechamento.

        Executando em QThread:
        - A janela permanece responsiva durante todo o processo.
        - O usuário pode ver a barra de progresso ou o log atualizando.
        - O finished_signal notifica o MainWindow quando o PDF
          estiver pronto, de forma thread-safe.

    Sinais:
        finished_signal(str): Caminho do PDF gerado ao concluir com sucesso.
        error_signal(str): Mensagem de erro se a geração falhar.
    """

    # Carrega o caminho do PDF gerado ao concluir com sucesso.
    finished_signal: pyqtSignal = pyqtSignal(str)

    # Carrega a mensagem de erro se a geração falhar.
    error_signal: pyqtSignal = pyqtSignal(str)

    def __init__(
        self,
        csv_path: str,
        patient_name: str,
        side: str,
        logo_path: Optional[str] = None,
        parent=None,
    ) -> None:
        """
        Configura os parâmetros de geração do PDF.

        Parâmetros:
            csv_path: Caminho para o CSV gerado pela sessão encerrada.
            patient_name: Nome do paciente para o relatório.
            side: Mão avaliada ("Direita" ou "Esquerda").
            logo_path: Caminho para o logotipo institucional (opcional).
            parent: Widget pai Qt (opcional).
        """
        super().__init__(parent)
        self._csv_path = csv_path
        self._patient_name = patient_name
        self._side = side
        self._logo_path = logo_path

    def run(self) -> None:
        """
        Executa a geração do PDF na thread separada.

        Chama generate_pdf_report() com os parâmetros configurados e
        emite finished_signal com o caminho do PDF ou error_signal com
        a descrição do erro. Nunca lança exceções fora do QThread —
        os erros são comunicados via sinal.
        """
        try:
            pdf_path: str = generate_pdf_report(
                csv_path=self._csv_path,
                patient_name=self._patient_name,
                side=self._side,
                logo_path=self._logo_path,
            )
            # Emite o caminho do PDF gerado para o MainWindow exibir no diálogo.
            self.finished_signal.emit(pdf_path)

        except Exception as exc:
            # Captura qualquer erro (CSV vazio, Matplotlib falhou, disco cheio etc.)
            # e notifica o MainWindow via sinal thread-safe.
            logger.error("Falha ao gerar PDF: %s", exc, exc_info=True)
            self.error_signal.emit(str(exc))


# =============================================================================
# JANELA PRINCIPAL
# =============================================================================

class MainWindow(QMainWindow):
    """
    Janela principal da aplicação de Goniometria Digital.

    Implementa o padrão "Controlador" do MVC: concentra toda a lógica de
    coordenação em um único lugar, enquanto cada widget tem responsabilidade única.
    O MainWindow NÃO realiza processamento científico — apenas conecta
    produtores de dados (workers) com exibidores de dados (widgets).

    Estado atual da aplicação:
        self._state: str — um de: "IDLE", "READY", "RUNNING", "STOPPED"
        self._csv_path: str — caminho para o CSV da sessão ativa (vazio se nenhum)
        self._pdf_worker: QThread auxiliar para geração de PDF (ou None)
    """

    def __init__(self, parent=None) -> None:
        """
        Inicializa a janela principal: widgets, workers, sinais e estado inicial.

        Ordem de inicialização:
            1. Configuração da janela (título, tamanho mínimo).
            2. Criação de todos os widgets da interface.
            3. Instanciação dos workers (SEM iniciar as threads).
            4. Conexão de todos os sinais entre workers e widgets.
            5. Montagem do layout visual (barra fixa superior e QStackedWidget).
            6. Definição da Página 1 (Tela de Configuração) como ponto de partida inicial.
            7. Estado inicial definido como "IDLE".

        Por que instanciar workers em __init__ mas não iniciá-los?
            Os workers precisam existir para que seus sinais possam ser conectados.
            Mas iniciar as threads (start()) antes de o usuário clicar em "Iniciar Avaliação"
            na Tela de Configuração desperdiçaria recursos de CPU e câmera mesmo quando
            a aplicação está ociosa.

        Parâmetros:
            parent: Widget pai Qt (opcional). Geralmente None para a janela principal.
        """
        super().__init__(parent)

        # --- Título e tamanho da janela ---
        self.setWindowTitle(config.APP_TITLE)
        self.setMinimumSize(config.WINDOW_MIN_WIDTH, config.WINDOW_MIN_HEIGHT)
        self.setStyleSheet(f"QMainWindow {{ background-color: {COLOR_BG_DARK}; }}")

        # --- Estado interno ---
        # String que controla quais botões estão habilitados e o comportamento dos métodos.
        # Centralizar em uma variável evita lógica dispersa.
        self._state: str = "IDLE"

        # Caminho para o CSV da sessão ativa. Definido em _start_session().
        # Usado por _gerar_relatorio() e _exportar_csv().
        self._csv_path: str = ""

        # Worker de geração de PDF — mantemos referência para evitar coleta de lixo
        # antes de o PDF terminar de ser gerado.
        self._pdf_worker: Optional[_PdfGeneratorWorker] = None

        # Controle de visibilidade da gaveta de logs (Fase 4B)
        self._logs_visible: bool = False

        # --- Estado do worker da mão robótica (Arduino) ---
        # None enquanto desligada. Instanciado somente ao clicar no botão.
        self._robot_hand_worker: Optional[RobotHandWorker] = None
        # "off" | "connecting" | "on" | "error"
        self._robot_hand_state: str = "off"
        # True se algum error_signal chegou durante a tentativa/sessão atual.
        self._robot_hand_had_error: bool = False

        # === CRIAÇÃO DOS COMPONENTES ===
        self._create_widgets()

        # === INSTANCIAÇÃO DOS WORKERS ===
        self._create_workers()

        # === CONEXÃO DOS SINAIS ===
        self._connect_signals()

        # === MONTAGEM DO LAYOUT ===
        self._build_layout()

        # === BARRA DE STATUS ===
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("Pronto. Preencha os dados do paciente para iniciar.")

        # === ESTADO INICIAL ===
        # Inicia em IDLE na Tela de Configuração (Página 1), aguardando dados do paciente.
        self._set_state("IDLE")

        # Mão robótica começa sempre desligada; nenhum comando é enviado
        # ao Arduino antes do primeiro clique no botão.
        self._set_robot_hand_state("off")

        logger.info("MainWindow inicializado com sucesso.")

    # =========================================================================
    # CRIAÇÃO DOS COMPONENTES
    # =========================================================================

    def _create_widgets(self) -> None:
        """
        Instancia todos os widgets da interface.

        Separado de __init__ para melhor organização e facilitar
        testes unitários individuais dos widgets.
        """
        # Cabeçalho com formulário do paciente e cronômetro.
        self.session_header = SessionHeaderWidget()

        # Exibição do quadro de vídeo com overlay goniométrico.
        self.video_widget = VideoWidget()

        # Painel lateral com cards de métricas do sistema.
        self.metrics_widget = MetricsWidget()

        # Gráfico TAM em tempo real para os 5 dedos.
        self.plot_widget = GoniometryPlotWidget()

        # Painel com 5 cards clínicos individuais por dedo.
        self.finger_cards = FingerCardsPanel()

        # Log de eventos do sistema com timestamps.
        self.log_widget = LogWidget()

        # Botão para alternar a gaveta de logs (Fase 4B)
        self.btn_toggle_logs = QPushButton("📋  Exibir Logs do Sistema")
        self.btn_toggle_logs.setFixedHeight(28)
        self.btn_toggle_logs.setToolTip("Exibe ou oculta a gaveta de logs do sistema.")
        self.btn_toggle_logs.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLOR_BG_MEDIUM};
                color: {COLOR_TEXT_SECONDARY};
                border: 1px solid {COLOR_TEXT_SECONDARY};
                border-radius: 4px;
                font-size: 11px;
                padding: 4px 12px;
            }}
            QPushButton:hover {{
                color: {COLOR_TEXT_PRIMARY};
                border-color: {COLOR_ACCENT};
            }}
            """
        )

        # --- Botões de controle de sessão ---
        # Botão Encerrar Sessão — estilo vermelho para ação destrutiva/final.
        # Fica na barra fixa superior (_assessment_bar), visível durante RUNNING.
        self.btn_end = QPushButton("■  Encerrar Sessão")
        self.btn_end.setStyleSheet(BUTTON_DANGER_STYLE)
        self.btn_end.setMinimumHeight(42)
        self.btn_end.setToolTip("Encerra a captura e finaliza o arquivo CSV.")

        # Botão único de liga/desliga da mão robótica (Arduino).
        # Não é setCheckable(True): o estado visual é controlado explicitamente
        # por _set_robot_hand_state(), pois a transição "conectando" é
        # assíncrona e pode falhar — um QPushButton checkable exigiria reverter
        # o estado 'checked' manualmente no mesmo cenário, o que é mais frágil.
        self.btn_robot_hand = QPushButton()
        self.btn_robot_hand.setMinimumHeight(42)
        self.btn_robot_hand.setToolTip(
            "Liga ou desliga a replicação de movimento na mão robótica (Arduino)."
        )

    def _create_workers(self) -> None:
        """
        Instancia os workers de câmera e processamento SEM iniciar as threads.

        Os workers são criados aqui para que seus sinais possam ser conectados em
        _connect_signals(). As threads só iniciam quando o usuário clicar em
        "Iniciar Sessão" — não antes.
        """
        self.camera_worker = CameraWorker(parent=self)
        self.processing_worker = ProcessingWorker(parent=self)
        # Inicializa o worker com o valor atual da interface
        self.processing_worker.set_evaluated_hand(self.session_header.get_session_info()["hand"])

    def _connect_signals(self) -> None:
        """
        Conecta todos os sinais entre workers, widgets e métodos do MainWindow.

        Por que centralizar aqui?
            Manter todas as conexões em um único método cria uma "tabela de roteamento"
            legível para o sistema. Ao depurar a comunicação entre componentes,
            basta olhar aqui para ver quem fala com quem.

        Conexões estabelecidas:
            camera_worker.frame_ready   → processing_worker.put_frame()
            camera_worker.fps_updated   → video_widget.set_fps()
            camera_worker.camera_error  → _on_camera_error()
            processing_worker.result_ready   → _on_result()
            processing_worker.processing_error → log_widget.log()
            session_header textChanged  → _on_patient_name_changed()
            btn_* .clicked              → slots de ação
        """
        # --- Camera Worker → Processing Worker ---
        # AutoConnection (padrão): Qt detecta que estão em threads diferentes
        # e usa conexão em fila (thread-safe).
        # NÃO usamos DirectConnection aqui porque executaria diretamente na
        # thread do CameraWorker, e put_frame() acessa a Queue — operação segura,
        # mas DirectConnection é desnecessário quando AutoConnection funciona.
        self.camera_worker.frame_ready.connect(self.processing_worker.put_frame)

        # --- Camera Worker → VideoWidget (FPS) ---
        self.camera_worker.fps_updated.connect(self.video_widget.set_fps)

        # --- Camera Worker → Tratamento de erros ---
        self.camera_worker.camera_error.connect(self._on_camera_error)

        # --- Processing Worker → MainWindow (resultado principal) ---
        self.processing_worker.result_ready.connect(self._on_result)

        # --- Processing Worker → LogWidget (erros não fatais) ---
        self.processing_worker.processing_error.connect(self.log_widget.log_error)
        
        # --- Cabeçalho da interface → Processing Worker (mudanças de mão) ---
        self.session_header.hand_changed.connect(self.processing_worker.set_evaluated_hand)

        # --- Processing Worker → PlotWidget (limpa gráficos na troca de mão) ---
        self.processing_worker.hand_side_reset.connect(self.plot_widget.clear_data)

        # --- Formulário → verificação de prontidão ---
        # Cada vez que o texto do campo de nome muda, verificamos se o botão Iniciar
        # deve ser habilitado. textChanged dispara para cada caractere.
        self.session_header._input_patient.textChanged.connect(
            self._on_patient_name_changed
        )

        # --- Botões → ações ---
        self.btn_toggle_logs.clicked.connect(self._toggle_logs)
        self.btn_end.clicked.connect(self._confirm_end_session)
        self.btn_robot_hand.clicked.connect(self._on_robot_hand_clicked)

    # =========================================================================
    # MONTAGEM DO LAYOUT
    # =========================================================================

    def _build_layout(self) -> None:
        """
        Monta a hierarquia visual central da MainWindow com arquitetura multitelas.

        Hierarquia de widgets do Central Widget:
            root_widget (QWidget)
            └── root_layout (QVBoxLayout, sem margens)
                ├── self._assessment_bar (barra fixa superior com botão 'Encerrar Sessão')
                └── self._stack (QStackedWidget gerenciador de telas, stretch=1)
                    ├── Página 0: QScrollArea contendo o painel clínico de avaliação:
                    │   ├── SessionHeaderWidget (cabeçalho da sessão ativa)
                    │   ├── QHBoxLayout (Vídeo 60% stretch=3 │ Métricas Clínicas 40% stretch=2)
                    │   ├── GoniometryPlotWidget (gráfico dinâmico de TAM)
                    │   ├── FingerCardsPanel (cartões individuais por dedo)
                    │   └── LogWidget recolhível (painel diagnóstico com botão de alternância)
                    ├── Página 1: Tela de Configuração da Sessão (_page_setup)
                    └── Página 2: Tela de Resultado da Sessão (_page_result)

        Por que a Página 0 é encapsulada em uma QScrollArea?
            Em monitores de menor resolução vertical, o conjunto de vídeo (450px),
            métricas, gráfico TAM (280px), cards e logs ultrapassa a altura disponível.
            A QScrollArea garante que todos os elementos clínicos sejam acessíveis via rolagem,
            enquanto a barra superior (_assessment_bar) permanece estática e sempre visível.
        """
        # =========================================================
        # 1. Configuração da ScrollArea central (Página 0)
        # =========================================================
        self._page_current_layout = QScrollArea()
        self._page_current_layout.setWidgetResizable(True)
        self._page_current_layout.setStyleSheet(f"QScrollArea {{ border: none; background: {COLOR_BG_DARK}; }}")

        # Widget contêiner dentro da ScrollArea.
        container_widget = QWidget()
        self._page_current_layout.setWidget(container_widget)

        # Layout vertical principal.
        main_layout = QVBoxLayout(container_widget)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        # Aumenta a altura mínima do vídeo e das métricas
        # para garantir boa visualização. A rolagem cuidará do restante.
        self.video_widget.setMinimumHeight(450)
        self.metrics_widget.setMinimumHeight(450)

        # --- 1. Cabeçalho de sessão ---
        main_layout.addWidget(self.session_header)

        # --- 2. Linha do meio: Vídeo + Métricas ---
        mid_row = QHBoxLayout()
        mid_row.setSpacing(6)

        # Vídeo: ocupa ~60% da largura da linha do meio.
        mid_row.addWidget(self.video_widget, stretch=3)

        # Métricas: ocupa ~40% da largura da linha do meio.
        # Ativa o modo clínico (oculta CPU, RAM, FPS e Quadro #; destaca estado da mão).
        self.metrics_widget.set_clinical_mode(True)
        mid_row.addWidget(self.metrics_widget, stretch=2)

        main_layout.addLayout(mid_row)

        # --- 3. Gráfico TAM em tempo real ---
        # Aumenta a altura do gráfico para melhor legibilidade
        self.plot_widget.setMinimumHeight(280)
        main_layout.addWidget(self.plot_widget)

        # --- 4. Cards individuais por dedo ---
        # Mantém rolagem interna para os cards (se a tela for muito estreita)
        # ou apenas define altura fixa para eles.
        cards_scroll = QScrollArea()
        cards_scroll.setWidget(self.finger_cards)
        cards_scroll.setWidgetResizable(True)
        cards_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        cards_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        cards_scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background: {COLOR_BG_DARK}; }}"
        )
        cards_scroll.setFixedHeight(310)

        main_layout.addWidget(cards_scroll)

        # --- 5. Log de eventos com gaveta recolhível (Fase 4B) ---
        main_layout.addWidget(self.btn_toggle_logs)
        self.log_widget.setMinimumHeight(80)
        self.log_widget.setMaximumHeight(100)
        main_layout.addWidget(self.log_widget)
        self._set_logs_visible(False)

        # =========================================================
        # Barra Fixa Superior de Avaliação (Fase 6)
        # =========================================================
        self._assessment_bar = QWidget()
        self._assessment_bar.setStyleSheet(
            f"QWidget {{ background-color: {COLOR_BG_MEDIUM}; border-bottom: 1px solid {COLOR_TEXT_SECONDARY}; }}"
        )
        bar_layout = QHBoxLayout(self._assessment_bar)
        bar_layout.setContentsMargins(16, 8, 16, 8)
        bar_layout.setSpacing(12)

        self._assessment_bar_label = QLabel("Avaliação em andamento")
        self._assessment_bar_label.setStyleSheet(
            f"QLabel {{ color: {COLOR_TEXT_PRIMARY}; font-size: 14px; font-weight: bold; border: none; }}"
        )
        bar_layout.addWidget(self._assessment_bar_label)
        bar_layout.addStretch()
        bar_layout.addWidget(self.btn_robot_hand)
        bar_layout.addWidget(self.btn_end)

        # =========================================================
        # Contêiner de Navegação (QStackedWidget)
        # =========================================================
        self._stack = QStackedWidget()

        # Página 0: Tela de Avaliação em Andamento (painel clínico rolável)
        self._stack.addWidget(self._page_current_layout)

        # Página 1: Tela de Configuração da Sessão (Fase 2)
        self._page_setup = self._build_setup_page()
        self._stack.addWidget(self._page_setup)

        # Página 2: Tela de Resultado da Sessão (Fase 5A)
        self._page_result = self._build_result_page()
        self._stack.addWidget(self._page_result)

        # Define Página 1 como inicial (Tela de Configuração)
        self._stack.setCurrentIndex(1)

        # =========================================================
        # Contêiner Raiz (Barra Fixa Superior + QStackedWidget)
        # =========================================================
        root_widget = QWidget()
        root_layout = QVBoxLayout(root_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._assessment_bar)
        root_layout.addWidget(self._stack, stretch=1)
        self.setCentralWidget(root_widget)

        # Conecta a navegação de páginas à atualização da barra de navegação
        self._stack.currentChanged.connect(
            lambda _: self._update_navigation_chrome()
        )
        self._update_navigation_chrome()

    def _build_setup_page(self) -> QWidget:
        """
        Constrói a Tela de Configuração da Sessão (Página 1 do QStackedWidget).

        Fornece formulário centralizado para inserção do nome do paciente,
        seleção da mão avaliada e número da sessão antes de iniciar a captura.
        """
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(24, 24, 24, 24)

        page_layout.addStretch(1)

        center_row = QHBoxLayout()
        center_row.addStretch(1)

        # Cartão centralizado baseado em QFrame
        card_frame = QFrame()
        card_frame.setFixedWidth(520)
        card_frame.setStyleSheet(
            f"QFrame {{ background-color: {COLOR_BG_MEDIUM}; "
            f"border: 1px solid #334155; border-radius: 8px; }}"
        )

        card_layout = QVBoxLayout(card_frame)
        card_layout.setContentsMargins(32, 28, 32, 28)
        card_layout.setSpacing(12)

        # Título
        lbl_title = QLabel("Goniometria Digital da Mão")
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_title.setStyleSheet(
            f"QLabel {{ color: {COLOR_TEXT_PRIMARY}; font-size: 20px; font-weight: bold; border: none; }}"
        )
        card_layout.addWidget(lbl_title)

        # Subtítulo
        lbl_subtitle = QLabel("Nova Avaliação Clínica")
        lbl_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_subtitle.setStyleSheet(
            f"QLabel {{ color: {COLOR_TEXT_SECONDARY}; font-size: 13px; margin-bottom: 8px; border: none; }}"
        )
        card_layout.addWidget(lbl_subtitle)

        # Campo: Paciente
        lbl_paciente = QLabel("Paciente")
        lbl_paciente.setStyleSheet(
            f"QLabel {{ color: {COLOR_TEXT_SECONDARY}; font-size: 11px; font-weight: bold; text-transform: uppercase; border: none; }}"
        )
        card_layout.addWidget(lbl_paciente)

        self._setup_input_patient = QLineEdit()
        self._setup_input_patient.setPlaceholderText("Nome completo do paciente...")
        self._setup_input_patient.setMaxLength(100)
        self._setup_input_patient.setStyleSheet(
            f"QLineEdit {{ color: {COLOR_TEXT_PRIMARY}; padding: 8px 12px; "
            f"border: 1px solid #334155; border-radius: 5px; "
            f"background: #0f172a; font-size: 14px; }}"
            f"QLineEdit:focus {{ border-color: {COLOR_ACCENT}; }}"
        )
        self._setup_input_patient.textChanged.connect(self._on_setup_patient_changed)
        card_layout.addWidget(self._setup_input_patient)

        # Campo: Mão Avaliada
        lbl_mao = QLabel("Mão Avaliada")
        lbl_mao.setStyleSheet(
            f"QLabel {{ color: {COLOR_TEXT_SECONDARY}; font-size: 11px; font-weight: bold; text-transform: uppercase; border: none; }}"
        )
        card_layout.addWidget(lbl_mao)

        self._setup_combo_hand = QComboBox()
        self._setup_combo_hand.addItems(["Direita", "Esquerda"])
        self._setup_combo_hand.setStyleSheet(
            f"QComboBox {{ color: {COLOR_TEXT_PRIMARY}; padding: 8px 12px; "
            f"border: 1px solid #334155; border-radius: 5px; "
            f"background: #0f172a; font-size: 14px; }}"
            f"QComboBox:focus {{ border-color: {COLOR_ACCENT}; }}"
            f"QComboBox QAbstractItemView {{ background: #0f172a; color: {COLOR_TEXT_PRIMARY}; selection-background-color: {COLOR_ACCENT}; }}"
        )
        card_layout.addWidget(self._setup_combo_hand)

        # Campo: Sessão Nº
        lbl_sessao = QLabel("Sessão Nº")
        lbl_sessao.setStyleSheet(
            f"QLabel {{ color: {COLOR_TEXT_SECONDARY}; font-size: 11px; font-weight: bold; text-transform: uppercase; border: none; }}"
        )
        card_layout.addWidget(lbl_sessao)

        self._setup_spin_session = QSpinBox()
        self._setup_spin_session.setMinimum(1)
        self._setup_spin_session.setMaximum(999)
        self._setup_spin_session.setValue(1)
        self._setup_spin_session.setStyleSheet(
            f"QSpinBox {{ color: {COLOR_TEXT_PRIMARY}; padding: 8px 12px; "
            f"border: 1px solid #334155; border-radius: 5px; "
            f"background: #0f172a; font-size: 14px; }}"
            f"QSpinBox:focus {{ border-color: {COLOR_ACCENT}; }}"
        )
        card_layout.addWidget(self._setup_spin_session)

        # Campo: Modo de Filtro
        # Fica por último, colado ao botão Iniciar: é a última coisa que o
        # operador vê antes de começar, reforçando que a escolha vale para a
        # sessão que está prestes a iniciar — e não para a que acabou.
        lbl_filtro = QLabel("Modo de Filtro")
        lbl_filtro.setStyleSheet(
            f"QLabel {{ color: {COLOR_TEXT_SECONDARY}; font-size: 11px; font-weight: bold; text-transform: uppercase; border: none; }}"
        )
        card_layout.addWidget(lbl_filtro)

        self._setup_combo_filter = QComboBox()
        for mode, label, tooltip, _help_text in FILTER_MODE_OPTIONS:
            self._setup_combo_filter.addItem(label, mode)
            self._setup_combo_filter.setItemData(
                self._setup_combo_filter.count() - 1,
                tooltip,
                Qt.ItemDataRole.ToolTipRole,
            )
        self._setup_combo_filter.setToolTip(
            "Define como os ângulos são suavizados antes de aparecerem na tela, "
            "serem gravados no CSV e usados no relatório PDF. O modo escolhido "
            "vale a partir da próxima sessão iniciada."
        )
        self._setup_combo_filter.setStyleSheet(
            f"QComboBox {{ color: {COLOR_TEXT_PRIMARY}; padding: 8px 12px; "
            f"border: 1px solid #334155; border-radius: 5px; "
            f"background: #0f172a; font-size: 14px; }}"
            f"QComboBox:focus {{ border-color: {COLOR_ACCENT}; }}"
            f"QComboBox QAbstractItemView {{ background: #0f172a; color: {COLOR_TEXT_PRIMARY}; selection-background-color: {COLOR_ACCENT}; }}"
        )
        card_layout.addWidget(self._setup_combo_filter)

        # Linha de ajuda: descreve o modo selecionado sem exigir que o operador
        # abra a lista ou espere o tooltip. É o que dá a um QComboBox a clareza
        # que botões de rádio teriam, sem gastar o espaço vertical deles.
        self._setup_lbl_filter_help = QLabel()
        self._setup_lbl_filter_help.setWordWrap(True)
        card_layout.addWidget(self._setup_lbl_filter_help)

        self._setup_combo_filter.currentIndexChanged.connect(
            self._on_filter_mode_changed
        )
        # O padrão vem só de config.FILTER_MODE_DEFAULT: nenhuma segunda cópia
        # do modo padrão vive na interface.
        self._setup_combo_filter.setCurrentIndex(
            self._setup_combo_filter.findData(config.FILTER_MODE_DEFAULT)
        )
        # setCurrentIndex() não emite currentIndexChanged quando o índice pedido
        # já é o atual — e o padrão é justamente o primeiro item. Sem esta
        # chamada explícita, a linha de ajuda nasceria vazia.
        self._on_filter_mode_changed(self._setup_combo_filter.currentIndex())

        card_layout.addSpacing(8)

        # Botão: Iniciar Avaliação
        self._setup_btn_start = QPushButton("▶  Iniciar Avaliação")
        self._setup_btn_start.setStyleSheet(BUTTON_PRIMARY_STYLE)
        self._setup_btn_start.setMinimumHeight(44)
        self._setup_btn_start.setEnabled(False)
        self._setup_btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self._setup_btn_start.clicked.connect(self._on_setup_start_clicked)
        card_layout.addWidget(self._setup_btn_start)

        center_row.addWidget(card_frame)
        center_row.addStretch(1)

        page_layout.addLayout(center_row)
        page_layout.addStretch(1)

        return page

    def _on_setup_patient_changed(self, text: str) -> None:
        """
        Habilita o botão Iniciar na Tela de Configuração se o nome não for vazio.
        """
        self._setup_btn_start.setEnabled(bool(text.strip()))

    def _on_filter_mode_changed(self, index: int) -> None:
        """
        Atualiza a linha de ajuda com a descrição do modo de filtro selecionado.

        O índice indexa FILTER_MODE_OPTIONS diretamente porque o combo é
        preenchido a partir dessa mesma tupla, na mesma ordem — as duas não
        têm como divergir.

        RAW recebe cor âmbar porque é o único modo que entrega ângulos sem
        nenhuma suavização: os valores oscilam de forma visível e ele não
        deve ser usado em avaliação clínica. Os demais modos compartilham a
        cor neutra do formulário — se o destaque valesse para todos, deixaria
        de comunicar qualquer coisa.
        """
        mode, _label, _tooltip, help_text = FILTER_MODE_OPTIONS[index]
        color = COLOR_WARNING if mode == "RAW" else COLOR_TEXT_SECONDARY

        self._setup_lbl_filter_help.setText(help_text)
        self._setup_lbl_filter_help.setStyleSheet(
            f"QLabel {{ color: {color}; font-size: 11px; border: none; }}"
        )

    def _on_setup_start_clicked(self) -> None:
        """
        Processa o clique em 'Iniciar Avaliação' na Tela de Configuração.

        Desabilita o botão para evitar duplo clique, sincroniza os dados
        com o SessionHeaderWidget e invoca o fluxo central de _start_session().
        """
        self._setup_btn_start.setEnabled(False)

        # Copia somente uma vez os dados para SessionHeaderWidget
        self.session_header._input_patient.setText(self._setup_input_patient.text().strip())
        self.session_header._combo_hand.setCurrentText(self._setup_combo_hand.currentText())
        self.session_header._spin_session.setValue(self._setup_spin_session.value())

        # Dispara o método oficial de início de sessão
        self._start_session()

        # Se por qualquer motivo a sessão não atingiu RUNNING, reabilita o botão
        if self._state != "RUNNING":
            self._setup_btn_start.setEnabled(bool(self._setup_input_patient.text().strip()))

    def _build_result_page(self) -> QWidget:
        """
        Constrói a Tela de Resultado da Sessão (Página 2 do QStackedWidget).

        Apresenta resumo informativo pós-sessão e botões de ação para
        geração de PDF, exportação de CSV e abertura da pasta de histórico.
        """
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(24, 24, 24, 24)

        page_layout.addStretch(1)

        center_row = QHBoxLayout()
        center_row.addStretch(1)

        # Cartão centralizado baseado em QFrame
        card_frame = QFrame()
        card_frame.setFixedWidth(560)
        card_frame.setStyleSheet(
            f"QFrame {{ background-color: {COLOR_BG_MEDIUM}; "
            f"border: 1px solid #334155; border-radius: 8px; }}"
        )

        card_layout = QVBoxLayout(card_frame)
        card_layout.setContentsMargins(32, 28, 32, 28)
        card_layout.setSpacing(12)

        # Título
        lbl_title = QLabel("Sessão Encerrada com Sucesso")
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_title.setStyleSheet(
            f"QLabel {{ color: {COLOR_TEXT_PRIMARY}; font-size: 20px; font-weight: bold; border: none; }}"
        )
        card_layout.addWidget(lbl_title)

        # Subtítulo
        lbl_subtitle = QLabel("Resumo da Avaliação Goniométrica")
        lbl_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_subtitle.setStyleSheet(
            f"QLabel {{ color: {COLOR_TEXT_SECONDARY}; font-size: 13px; margin-bottom: 8px; border: none; }}"
        )
        card_layout.addWidget(lbl_subtitle)

        card_layout.addSpacing(4)

        # Linhas de informação estruturadas
        info_items = [
            ("Paciente:", "_lbl_result_patient"),
            ("Mão Avaliada:", "_lbl_result_hand"),
            ("Sessão Nº:", "_lbl_result_session"),
            ("Início:", "_lbl_result_start"),
            ("Duração:", "_lbl_result_duration"),
        ]

        for text_label, attr_name in info_items:
            row_layout = QHBoxLayout()
            row_layout.setSpacing(8)

            lbl_name = QLabel(text_label)
            lbl_name.setFixedWidth(120)
            lbl_name.setStyleSheet(
                f"QLabel {{ color: {COLOR_TEXT_SECONDARY}; font-size: 12px; font-weight: bold; border: none; }}"
            )

            lbl_val = QLabel("—")
            lbl_val.setStyleSheet(
                f"QLabel {{ color: {COLOR_TEXT_PRIMARY}; font-size: 13px; border: none; }}"
            )
            setattr(self, attr_name, lbl_val)

            row_layout.addWidget(lbl_name)
            row_layout.addWidget(lbl_val, stretch=1)
            card_layout.addLayout(row_layout)

        # Campo: CSV salvo em:
        lbl_csv_title = QLabel("CSV salvo em:")
        lbl_csv_title.setStyleSheet(
            f"QLabel {{ color: {COLOR_TEXT_SECONDARY}; font-size: 12px; font-weight: bold; margin-top: 4px; border: none; }}"
        )
        card_layout.addWidget(lbl_csv_title)

        self._lbl_result_csv = QLabel("—")
        self._lbl_result_csv.setWordWrap(True)
        self._lbl_result_csv.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._lbl_result_csv.setStyleSheet(
            f"QLabel {{ color: {COLOR_TEXT_SECONDARY}; font-size: 11px; padding: 6px 8px; "
            f"background-color: #0f172a; border: 1px solid #334155; border-radius: 4px; }}"
        )
        card_layout.addWidget(self._lbl_result_csv)

        card_layout.addSpacing(12)

        # Linha de ações principais: PDF e CSV
        btn_action_row = QHBoxLayout()
        btn_action_row.setSpacing(10)

        self._btn_result_pdf = QPushButton("📄  Gerar Relatório PDF")
        self._btn_result_pdf.setMinimumHeight(42)
        self._btn_result_pdf.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_result_pdf.setToolTip("Gera o relatório clínico em PDF a partir do CSV da sessão encerrada.")
        self._btn_result_pdf.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLOR_BG_MEDIUM};
                color: {COLOR_TEXT_PRIMARY};
                border: 1px solid #334155;
                border-radius: 5px;
                font-size: 13px;
                padding: 6px 14px;
            }}
            QPushButton:hover {{
                border-color: {COLOR_ACCENT};
            }}
            QPushButton:disabled {{
                color: #64748b;
                border-color: #334155;
                background-color: #0f172a;
            }}
            """
        )
        self._btn_result_pdf.clicked.connect(self._gerar_relatorio)
        btn_action_row.addWidget(self._btn_result_pdf)

        self._btn_result_csv = QPushButton("💾  Exportar CSV")
        self._btn_result_csv.setMinimumHeight(42)
        self._btn_result_csv.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_result_csv.setToolTip("Copia o arquivo CSV da sessão para um local escolhido.")
        self._btn_result_csv.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLOR_BG_MEDIUM};
                color: {COLOR_TEXT_PRIMARY};
                border: 1px solid #334155;
                border-radius: 5px;
                font-size: 13px;
                padding: 6px 14px;
            }}
            QPushButton:hover {{
                border-color: {COLOR_ACCENT};
            }}
            QPushButton:disabled {{
                color: #64748b;
                border-color: #334155;
                background-color: #0f172a;
            }}
            """
        )
        self._btn_result_csv.clicked.connect(self._exportar_csv)
        btn_action_row.addWidget(self._btn_result_csv)

        card_layout.addLayout(btn_action_row)

        # Botão: Abrir Pasta de Sessões
        self._btn_result_history = QPushButton("📁  Abrir Pasta de Sessões")
        self._btn_result_history.setMinimumHeight(38)
        self._btn_result_history.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_result_history.setToolTip("Abre a pasta onde os arquivos de sessão são salvos.")
        self._btn_result_history.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLOR_BG_MEDIUM};
                color: {COLOR_TEXT_SECONDARY};
                border: 1px solid #334155;
                border-radius: 5px;
                font-size: 12px;
                padding: 6px 12px;
            }}
            QPushButton:hover {{
                color: {COLOR_TEXT_PRIMARY};
                border-color: {COLOR_ACCENT};
            }}
            """
        )
        self._btn_result_history.clicked.connect(self._abrir_historico)
        card_layout.addWidget(self._btn_result_history)

        card_layout.addSpacing(6)

        # Botão: Nova Avaliação — único caminho de reset da aplicação.
        # Hover em COLOR_DANGER porque a ação é sempre destrutiva para os dados
        # em tela; no estado normal permanece neutro, para não competir com os
        # botões de exportação logo acima. A proteção real continua sendo o
        # diálogo de confirmação, não a cor.
        self._btn_result_next = QPushButton("🔄  Nova Avaliação")
        self._btn_result_next.setMinimumHeight(42)
        self._btn_result_next.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_result_next.setToolTip(
            "Reinicia o sistema por completo e apaga a identificação do paciente, "
            "retornando à tela de configuração para uma nova avaliação."
        )
        self._btn_result_next.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLOR_BG_MEDIUM};
                color: {COLOR_TEXT_PRIMARY};
                border: 1px solid {COLOR_TEXT_SECONDARY};
                border-radius: 5px;
                font-size: 13px;
                padding: 6px 14px;
            }}
            QPushButton:hover {{
                border-color: {COLOR_DANGER};
            }}
            """
        )
        self._btn_result_next.clicked.connect(self._on_result_new_session)
        card_layout.addWidget(self._btn_result_next)

        center_row.addWidget(card_frame)
        center_row.addStretch(1)

        page_layout.addLayout(center_row)
        page_layout.addStretch(1)

        return page

    def _update_result_page_data(self) -> None:
        """
        Atualiza os rótulos da Tela de Resultado com os dados da sessão encerrada.

        Lê dados exclusivamente de SessionHeaderWidget e self._csv_path, sem
        realizar cálculos ou parsing de arquivos.
        """
        session_info = self.session_header.get_session_info()
        start_time_text = self.session_header._lbl_start_time.text()
        elapsed_text = self.session_header._lbl_elapsed.text()

        self._lbl_result_patient.setText(session_info.get("patient_name", "—") or "—")
        self._lbl_result_hand.setText(session_info.get("hand", "—") or "—")
        self._lbl_result_session.setText(str(session_info.get("session_number", "—")))
        self._lbl_result_start.setText(start_time_text or "—")
        self._lbl_result_duration.setText(elapsed_text or "—")
        self._lbl_result_csv.setText(self._csv_path or "—")

        # Habilita botões de PDF e CSV com base na existência do arquivo
        has_csv = bool(self._csv_path and os.path.exists(self._csv_path))
        self._btn_result_pdf.setEnabled(has_csv)
        self._btn_result_csv.setEnabled(has_csv)

    def _on_result_new_session(self) -> None:
        """
        Reinicia o sistema por completo e retorna à Tela de Configuração em IDLE.

        Este é o único caminho de reset da aplicação. Antes existiam dois
        botões na Tela de Resultado — "Nova Avaliação" e "Limpar Dados do
        Paciente" — visualmente idênticos e ambos executando o mesmo reset
        completo de workers, gráficos e métricas. A única diferença entre eles
        era preservar ou apagar a identificação do paciente, distinção
        invisível para quem olhava a tela. Consolidar em um botão que sempre
        limpa tudo elimina a ambiguidade na raiz: o resultado é sempre o mesmo,
        e o diálogo de confirmação enuncia esse alcance antes de qualquer dano.

        A ordem das etapas abaixo é obrigatória e não deve ser simplificada:
        session_header.reset(), chamado dentro de _new_session(), deliberadamente
        NÃO limpa o nome do paciente (ver o docstring dele). Por isso
        _new_session() sozinho termina em READY, não em IDLE — quem apaga a
        identificação e leva o estado a IDLE é a limpeza explícita dos campos
        feita aqui.
        """
        if not self._confirm_new_session():
            return

        # 1. Reset do motor: para os workers, recria as threads do zero e
        #    limpa gráficos, métricas, widgets e log.
        #    confirm=False porque a confirmação já foi obtida acima, com o
        #    texto que descreve este fluxo.
        if not self._new_session(confirm=False):
            return

        # 2. Identificação do paciente — o que _new_session() não apaga.
        self.session_header._input_patient.clear()
        self.session_header._combo_hand.setCurrentText("Direita")
        self.session_header._spin_session.setValue(1)

        self._setup_input_patient.clear()
        self._setup_combo_hand.setCurrentText("Direita")
        self._setup_spin_session.setValue(1)
        self._setup_btn_start.setEnabled(False)

        # 3. Modo de filtro de volta ao padrão: uma avaliação nova começa
        #    sempre no pipeline clínico validado, a menos que o operador
        #    escolha outro explicitamente.
        self._setup_combo_filter.setCurrentIndex(
            self._setup_combo_filter.findData(config.FILTER_MODE_DEFAULT)
        )

        # 4. Estado final.
        self._set_state("IDLE")
        self._stack.setCurrentIndex(1)
        self._update_navigation_chrome()

    def _confirm_new_session(self) -> bool:
        """
        Pede confirmação para o reset completo. Retorna True se autorizado.

        Cancelar é o botão padrão: o reset é sempre destrutivo para os dados
        em tela, e a confirmação é a única proteção contra o clique acidental.
        """
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setWindowTitle("Iniciar Nova Avaliação?")
        msg.setText("Deseja iniciar uma nova avaliação?")
        msg.setInformativeText(
            "Todos os gráficos, métricas e dados da sessão atual serão limpos.\n"
            "A identificação do paciente — nome, mão e número da sessão — será apagada.\n"
            "O modo de filtro voltará ao padrão: EMA + Kalman.\n\n"
            "Os arquivos de relatórios (CSV e PDF) já salvos NÃO serão apagados."
        )
        btn_nova = msg.addButton("Nova Avaliação", QMessageBox.ButtonRole.AcceptRole)
        btn_cancelar = msg.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        msg.setDefaultButton(btn_cancelar)

        msg.exec()

        return msg.clickedButton() == btn_nova

    def _update_navigation_chrome(self) -> None:
        """
        Controla a visibilidade dos elementos cromáticos globais de navegação.

        Determina dinamicamente se a barra superior fixa (_assessment_bar) deve ser
        exibida com base no índice da página atual do QStackedWidget e no estado da sessão:
        - Exibida (True): exclusivamente na Página 0 (Tela de Avaliação) quando o estado
          for "RUNNING". Isso mantém o botão 'Encerrar Sessão' sempre acessível no topo.
        - Oculta (False): na Página 1 (Configuração), na Página 2 (Resultado) ou quando
          a avaliação estiver encerrada/em transição (IDLE, READY, STOPPED).
        """
        is_eval_active = (
            self._stack.currentIndex() == 0
            and self._state == "RUNNING"
        )
        self._assessment_bar.setVisible(is_eval_active)

    # =========================================================================
    # CONTROLE DA GAVETA DE LOGS (FASE 4B)
    # =========================================================================

    def _toggle_logs(self) -> None:
        """
        Alterna a visibilidade da gaveta do LogWidget.
        """
        self._set_logs_visible(not self._logs_visible)

    def _set_logs_visible(self, visible: bool) -> None:
        """
        Define a visibilidade da gaveta do LogWidget e atualiza o texto do botão.

        Parâmetros:
            visible: True para exibir a gaveta, False para recolher.
        """
        self._logs_visible = visible
        self.log_widget.setVisible(visible)
        if visible:
            self.btn_toggle_logs.setText("📋  Ocultar Logs do Sistema")
        else:
            self.btn_toggle_logs.setText("📋  Exibir Logs do Sistema")

    # =========================================================================
    # MÁQUINA DE ESTADOS
    # =========================================================================

    def _set_state(self, state: str) -> None:
        """
        Centraliza a habilitação e desabilitação de botões com base no estado.

        Por que centralizar em _set_state() em vez de habilitar/desabilitar
        botões diretamente em cada método de ação?

            Sem centralização, cada método (iniciar, encerrar etc.) precisaria
            conhecer e manipular TODOS os botões. Se um novo botão for adicionado
            no futuro, TODOS os métodos precisariam ser atualizados. Com _set_state(),
            basta adicionar o novo botão aqui e ele será gerenciado corretamente
            em todos os estados sem alterar mais nada.

            Este é o padrão "Máquina de Estados" aplicado à interface: o estado é
            a fonte da verdade, e os botões reagem ao estado — não o contrário.

        Transições válidas:
            IDLE    → READY  (quando o nome é preenchido)
            READY   → RUNNING (ao clicar em Iniciar)
            RUNNING → STOPPED (ao clicar em Encerrar)
            STOPPED → READY  (ao preencher nome para nova sessão)

        Parâmetros:
            state: String identificando o novo estado.
                   Valores válidos: "IDLE", "READY", "RUNNING", "STOPPED".
        """
        self._state = state

        # --- Botões de controle de sessão ---
        # Encerrar: habilitado apenas durante gravação ativa (RUNNING).
        self.btn_end.setEnabled(state == "RUNNING")

        # Os botões de exportação (PDF, CSV, pasta de sessões) não aparecem
        # aqui: vivem na Tela de Resultado, que só é alcançada depois de
        # _end_session(). O próprio fluxo de navegação já garante que não
        # sejam usados com uma sessão em andamento.

        # --- Campos do formulário ---
        # Bloqueados durante RUNNING para evitar alteração acidental dos
        # dados de identificação enquanto a sessão está gravando.
        self.session_header.set_fields_enabled(state != "RUNNING")

        # Seletor de filtro: bloqueado durante RUNNING pelo mesmo motivo, com
        # um agravante — o modo já foi aplicado ao banco de filtros no início
        # da sessão e está sendo gravado em cada linha do CSV. Deixá-lo
        # editável sugeriria que trocar de modo agora surtiria algum efeito,
        # quando na verdade a troca só valeria para a próxima sessão.
        self._setup_combo_filter.setEnabled(state != "RUNNING")

        # --- Mensagem da barra de status ---
        status_messages = {
            "IDLE":    "Preencha os dados do paciente para habilitar o início da sessão.",
            "READY":   "Pronto para iniciar. Clique em 'Iniciar Sessão'.",
            "RUNNING": "Sessão em andamento — capturando e processando dados...",
            "STOPPED": "Sessão encerrada. Você pode gerar o relatório PDF ou exportar o CSV.",
        }
        self._status_bar.showMessage(status_messages.get(state, ""))

        logger.debug("Estado alterado para: %s", state)

    # =========================================================================
    # SLOTS DE RESULTADO E ERRO
    # =========================================================================

    def _on_result(self, result: object) -> None:
        """
        Recebe e distribui o ProcessingResult para todos os widgets.

        Chamado ~30 vezes/segundo pelo sinal result_ready do ProcessingWorker.
        Deve ser rápido: apenas distribui dados, sem cálculos.

        Este método é executado na thread principal (thread Qt), garantido pelo
        sistema de sinais do Qt. Nunca acessamos widgets de dentro de um
        QThread — sempre via este slot conectado.

        Parâmetros:
            result: Objeto ProcessingResult emitido pelo ProcessingWorker.
                    Tipado como 'object' porque pyqtSignal(ProcessingResult)
                    não é suportado diretamente — fazemos o cast aqui.
        """
        # Cast para o tipo correto — seguro porque apenas o ProcessingWorker
        # emite result_ready, sempre com ProcessingResult.
        r: ProcessingResult = result  # type: ignore[assignment]

        # Atualiza o quadro de vídeo com overlay goniométrico.
        self.video_widget.update_frame(r.frame_overlay)

        # Atualiza FPS, Nº de quadro e cards de estado da mão.
        self.metrics_widget.update_from_result(r)

        # Atualiza o gráfico TAM em tempo real para 5 dedos.
        self.plot_widget.update_data(r.angles_smooth, r.hand_detected)

        # Atualiza os 5 cards individuais com métricas clínicas e mini-gráficos.
        # get_tam_buffers() retorna uma cópia thread-safe dos deques do worker.
        self.finger_cards.update_all(
            finger_states=r.hand_state.get("estados_dedos", {}),
            metrics_per_finger=r.metrics_per_finger,
            tam_buffers_per_finger=r.tam_buffers_snapshot,
        )

        # Mão robótica: só envia alvos se estiver LIGADA e conectada.
        # update_targets() é barato (grava sob lock, sem I/O) — não há risco
        # de atrasar a distribuição do resultado para os demais widgets.
        if self._robot_hand_worker is not None and self._robot_hand_state == "on":
            servo_positions = robot_hand_map_all(r.angles_smooth)
            self._robot_hand_worker.update_targets(servo_positions, r.hand_detected)

    def _on_camera_error(self, message: str) -> None:
        """
        Trata erros fatais de câmera emitidos pelo CameraWorker.

        Quando a câmera para de funcionar durante uma sessão ativa,
        encerra automaticamente a sessão para evitar gravar
        quadros inválidos no CSV. Exibe o erro no log e na barra de status.

        Parâmetros:
            message: Descrição do erro enviada pelo CameraWorker via sinal.
        """
        was_running = self._state == "RUNNING"
        self.log_widget.log_error(f"Câmera: {message}")
        if was_running:
            self._set_logs_visible(True)
        self.video_widget.set_no_signal(message)
        self._status_bar.showMessage(f"ERRO DE CÂMERA: {message}")
        logger.error("Erro de câmera: %s", message)

        # Se a sessão estava em andamento, encerra automaticamente.
        # Continuar gravando sem quadros cria um CSV corrompido.
        if was_running:
            self._end_session()

    # =========================================================================
    # MÃO ROBÓTICA (ARDUINO) — botão único liga/desliga
    # =========================================================================

    def _on_robot_hand_clicked(self) -> None:
        """
        Slot do clique único em btn_robot_hand.

        Comportamento depende do estado atual:
            "off"/"error" -> inicia tentativa de conexão.
            "on"          -> inicia desligamento seguro.
            "connecting"  -> ignorado (botão fica desabilitado nesse estado,
                              mas o guard aqui é defensivo).
        """
        if self._robot_hand_state in ("off", "error"):
            self._start_robot_hand()
        elif self._robot_hand_state == "on":
            self._stop_robot_hand()
        # "connecting": nenhuma ação — o botão já está desabilitado.

    def _start_robot_hand(self) -> None:
        """
        Cria e inicia o RobotHandWorker. Não bloqueia a UI: a conexão real
        acontece dentro da QThread (RobotHandWorker.run()).
        """
        if self._robot_hand_worker is not None:
            return  # já existe uma tentativa/conexão em andamento.

        self._robot_hand_had_error = False
        self._set_robot_hand_state("connecting")

        self._robot_hand_worker = RobotHandWorker(parent=self)
        self._robot_hand_worker.connected_signal.connect(self._on_robot_hand_connected)
        self._robot_hand_worker.error_signal.connect(self._on_robot_hand_error)
        self._robot_hand_worker.finished.connect(self._on_robot_hand_finished)
        self._robot_hand_worker.start()

    def _stop_robot_hand(self) -> None:
        """
        Solicita o desligamento seguro (posição aberta + liberação da porta).

        Não bloqueia: o botão é desabilitado até _on_robot_hand_finished()
        confirmar que o worker terminou por completo.
        """
        if self._robot_hand_worker is None:
            return
        self.btn_robot_hand.setEnabled(False)
        self._status_bar.showMessage("Desligando mão robótica...")
        self._robot_hand_worker.request_stop()

    def _on_robot_hand_connected(self, success: bool) -> None:
        """
        Recebe o resultado da tentativa de conexão inicial (connected_signal).

        Em caso de sucesso, habilita a replicação (estado "on") imediatamente.
        Em caso de falha, não faz nada aqui — o estado final ("error") é
        decidido em _on_robot_hand_finished(), quando a thread já tiver
        retornado por completo (garante que nunca fica em estado intermediário).
        """
        if success:
            self._set_robot_hand_state("on")
            self._status_bar.showMessage("Mão robótica conectada e replicando.")

    def _on_robot_hand_error(self, message: str) -> None:
        """
        Recebe mensagens de erro do worker (error_signal): falha de conexão,
        falha ao configurar pinos ou perda de comunicação durante o uso.
        """
        self._robot_hand_had_error = True
        self._status_bar.showMessage(f"Mão robótica: {message}")
        self.log_widget.log_error(f"Mão robótica: {message}")
        logger.error("Mão robótica: %s", message)

    def _on_robot_hand_finished(self) -> None:
        """
        Chamado quando RobotHandWorker.run() retorna por completo (sinal
        nativo 'finished' da QThread) — seja por desligamento pedido pelo
        usuário, seja por falha de conexão, seja por perda de comunicação.

        Neste ponto a porta serial já foi liberada (run() garante isso em seu
        bloco finally). É seguro permitir uma nova tentativa de conexão.
        """
        had_error = self._robot_hand_had_error
        self._robot_hand_worker = None
        self.btn_robot_hand.setEnabled(True)

        if had_error:
            self._set_robot_hand_state("error")
        else:
            self._set_robot_hand_state("off")
            self._status_bar.showMessage("Mão robótica desligada.")

    def _set_robot_hand_state(self, state: str) -> None:
        """
        Atualiza texto, cor e habilitação de btn_robot_hand para um dos 4
        estados: "off", "connecting", "on", "error".

        Centralizado aqui para que nunca haja divergência entre o texto e a
        cor exibidos (ex.: nunca fica verde com o texto de erro).
        """
        self._robot_hand_state = state

        style_off = (
            "QPushButton {"
            " background-color: #7f1d1d;"
            " border: 1px solid #ef4444;"
            " color: #ffffff;"
            " padding: 8px 16px;"
            " border-radius: 8px;"
            " font-weight: bold;"
            " }"
            " QPushButton:hover { border-color: #f87171; }"
            " QPushButton:disabled { color: #d1a3a3; }"
        )
        style_connecting = (
            "QPushButton {"
            " background-color: #78350f;"
            " border: 1px solid #f59e0b;"
            " color: #ffffff;"
            " padding: 8px 16px;"
            " border-radius: 8px;"
            " font-weight: bold;"
            " }"
        )
        style_on = (
            "QPushButton {"
            " background-color: #14532d;"
            " border: 1px solid #22c55e;"
            " color: #ffffff;"
            " padding: 8px 16px;"
            " border-radius: 8px;"
            " font-weight: bold;"
            " }"
            " QPushButton:hover { border-color: #4ade80; }"
        )

        if state == "off":
            self.btn_robot_hand.setText("●  MÃO ROBÓTICA: DESLIGADA")
            self.btn_robot_hand.setStyleSheet(style_off)
            self.btn_robot_hand.setEnabled(True)
        elif state == "connecting":
            self.btn_robot_hand.setText("●  CONECTANDO...")
            self.btn_robot_hand.setStyleSheet(style_connecting)
            self.btn_robot_hand.setEnabled(False)
        elif state == "on":
            self.btn_robot_hand.setText("●  MÃO ROBÓTICA: LIGADA")
            self.btn_robot_hand.setStyleSheet(style_on)
            self.btn_robot_hand.setEnabled(True)
        elif state == "error":
            self.btn_robot_hand.setText("●  ERRO: ARDUINO NÃO CONECTADO")
            self.btn_robot_hand.setStyleSheet(style_off)
            self.btn_robot_hand.setEnabled(True)

    def _on_patient_name_changed(self, text: str) -> None:
        """
        Reage a mudanças no nome do paciente no formulário.

        Chamado pelo sinal textChanged do QLineEdit de nome a cada tecla pressionada.
        Verifica se o formulário está pronto (is_ready()) e transita entre
        os estados IDLE e READY conforme necessário.

        Parâmetros:
            text: Texto atual no campo de nome (string bruta, incluindo espaços).
        """
        # Altera o estado apenas se não estiver em RUNNING ou STOPPED.
        # Não queremos que a digitação do nome mude o estado durante uma sessão.
        if self._state in ("IDLE", "READY"):
            if self.session_header.is_ready():
                self._set_state("READY")
            else:
                self._set_state("IDLE")

    # =========================================================================
    # AÇÕES DOS BOTÕES
    # =========================================================================

    def _new_session(self, confirm: bool = True) -> bool:
        """
        Reinicia completamente o estado do sistema e prepara a interface para um novo paciente.

        Por que recriar os workers em vez de apenas resetá-los?
            O QThread no Qt tem ciclo de vida unidirecional: uma vez que run()
            retorna e a thread encerra, o objeto QThread não pode ser reiniciado
            com start() novamente. Além disso, _cleanup() no ProcessingWorker
            fecha o MediaPipe (self._hands.close()), e _release_camera() no
            CameraWorker libera o cv2.VideoCapture. Esses recursos precisam ser
            recriados do zero para uma nova sessão funcionar.

            A solução segura é: destruir os workers antigos, criar novos e
            reconectar todos os sinais.

        Parâmetros:
            confirm: Se True, solicita confirmação via QMessageBox antes do reset.
                     Se False, executa o reset diretamente sem abrir diálogo.

        Retorna:
            bool: True se o reset foi executado com sucesso, False se cancelado.
        """
        if self._state == "RUNNING":
            QMessageBox.warning(self, "Aviso", "Por favor, encerre a sessão atual antes de iniciar uma nova.")
            return False

        # Confirmação do usuário para evitar perda acidental de dados em tela
        if confirm:
            resp = QMessageBox.question(
                self,
                "Atenção: Nova Sessão",
                "Iniciar uma nova sessão limpará todos os gráficos e métricas atuais da tela.\n\n"
                "Certifique-se de ter exportado o CSV ou gerado o Relatório PDF se precisar desses dados.\n\n"
                "Tem certeza que deseja começar do zero?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No  # Padrão No para segurança
            )
            if resp != QMessageBox.StandardButton.Yes:
                return False

        # === 1. Garante que os workers antigos estejam completamente parados ===
        if self.camera_worker.isRunning():
            self.camera_worker.stop()
            self.camera_worker.wait(3000)

        if self.processing_worker.isRunning():
            self.processing_worker.stop()
            self.processing_worker.wait(3000)

        # === 2. Recria os workers do zero (novos objetos QThread) ===
        self._create_workers()

        # === 3. Reconecta todos os sinais aos novos workers ===
        self._connect_signals()

        # === 4. Limpa todos os widgets da interface ===
        self.video_widget.set_no_signal("Aguardando nova sessão...")
        self.plot_widget.clear_data()
        self.finger_cards.clear_all()
        self.metrics_widget.reset_display()
        self.metrics_widget.stop_monitoring()
        self.session_header.reset()

        # === 5. Limpa o log e exibe confirmação ===
        self.log_widget.clear_log()
        self.log_widget.log_success("Sistema reiniciado. Pronto para nova sessão.")
        self._set_logs_visible(False)

        # === 6. Reinicia referências de sessão ===
        self._csv_path = ""
        self._pdf_worker = None

        # === 7. Reavalia o estado ===
        if self.session_header.is_ready():
            self._set_state("READY")
        else:
            self._set_state("IDLE")

        return True

    def _start_session(self) -> None:
        """
        Inicia a sessão de captura e processamento goniométrico.

        Sequência de operações:
            1. Valida se o formulário está completo (is_ready()).
            2. Cria o diretório de logs se não existir.
            3. Gera o caminho do CSV com timestamp para unicidade.
            4. Inicia a sessão no ProcessingWorker (abre o CSV).
            5. Inicia as threads dos workers.
            6. Atualiza o cronômetro e o log.
            7. Transita para o estado RUNNING.

        Chamado por _on_setup_start_clicked(), a partir do botão "Iniciar
        Avaliação" da Tela de Configuração (_setup_btn_start).
        """
        # Validação de pré-condição — linha extra de defesa além do estado READY.
        if not self.session_header.is_ready():
            QMessageBox.warning(
                self,
                "Dados Incompletos",
                "Por favor, preencha o nome completo do paciente antes de iniciar.",
            )
            return

        # Coleta dados do formulário para uso no CSV e PDF.
        session_info = self.session_header.get_session_info()
        patient_name: str = session_info["patient_name"]
        hand: str = session_info["hand"]
        session_number: int = session_info["session_number"]

        # Cria a pasta de logs se não existir.
        # exist_ok=True: sem erro se a pasta já existir.
        os.makedirs(config.LOG_DIR, exist_ok=True)

        # Gera o nome do arquivo CSV com timestamp para garantir unicidade.
        # Formato: "logs/sessao_Joao_Silva_20260623_143512_s1.csv"
        # O timestamp evita sobrescrever sessões anteriores do mesmo paciente.
        timestamp_str: str = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Remove caracteres inválidos no nome do arquivo (espaços → sublinhados).
        safe_name: str = patient_name.replace(" ", "_").replace("/", "_")
        csv_filename: str = f"session_{safe_name}_{timestamp_str}_s{session_number}.csv"
        self._csv_path = os.path.join(config.LOG_DIR, csv_filename)

        # Aplica o modo de filtro escolhido ANTES de abrir o CSV. A ordem
        # importa: start_session() abre o arquivo e, a partir daí, cada linha
        # gravada carrega o modo do banco atualmente instalado. Trocar o banco
        # depois faria as primeiras linhas saírem com o modo anterior — um erro
        # silencioso, que só apareceria no rodapé de um PDF já entregue.
        selected_mode = self._setup_combo_filter.currentData()
        self.processing_worker.set_filter_mode(selected_mode)

        # Inicia a sessão CSV no worker ANTES de iniciar as threads.
        # Isso garante que o logger esteja pronto quando os primeiros quadros chegarem.
        self.processing_worker.start_session(self._csv_path)

        # Limpa dados de widgets da sessão anterior.
        self.plot_widget.clear_data()
        self.finger_cards.clear_all()
        self.metrics_widget.reset_display()

        # Inicia as threads dos workers.
        # start() do QThread chama run() em uma thread separada.
        # Os workers já existem desde __init__ — apenas iniciamos a execução.
        if not self.camera_worker.isRunning():
            self.camera_worker.start()

        if not self.processing_worker.isRunning():
            self.processing_worker.start()

        # Inicia o cronômetro no cabeçalho.
        self.session_header.start_timer()

        # Registra início no log e transita para RUNNING.
        self.log_widget.log_success(
            f"Sessão {session_number} iniciada — {patient_name} | Mão {hand} | "
            f"Filtro {selected_mode} | {csv_filename}"
        )

        self._set_state("RUNNING")
        self._set_logs_visible(False)
        logger.info(
            "Sessão iniciada: paciente=%s, mão=%s, sessão=%d, filtro=%s, csv=%s",
            patient_name, hand, session_number, selected_mode, self._csv_path,
        )

        # Transição autorizada para a Página 0 (avaliação em tempo real)
        self._stack.setCurrentIndex(0)
        self._update_navigation_chrome()

    def _confirm_end_session(self) -> None:
        """
        Solicita confirmação do usuário antes de encerrar a sessão ativa.

        Protege contra cliques acidentais no botão 'Encerrar Sessão'.
        Se confirmado, desabilita o botão imediatamente contra duplo clique
        e chama o encerramento operacional em _end_session().
        """
        msg = QMessageBox(self)
        msg.setWindowTitle("Encerrar Avaliação?")
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setText("Deseja encerrar a avaliação clínica?")
        msg.setInformativeText(
            "Os dados coletados até agora serão salvos e a sessão será finalizada."
        )
        btn_encerrar = msg.addButton(
            "Encerrar e Salvar", QMessageBox.ButtonRole.AcceptRole
        )
        btn_cancelar = msg.addButton(
            "Cancelar", QMessageBox.ButtonRole.RejectRole
        )
        msg.setDefaultButton(btn_cancelar)

        msg.exec()

        if msg.clickedButton() == btn_encerrar:
            self.btn_end.setEnabled(False)
            self._end_session()

    def _end_session(self) -> None:
        """
        Encerra a sessão de captura e finaliza o arquivo CSV.

        Sequência de operações:
            1. Sinaliza ao ProcessingWorker para fechar a sessão CSV.
            2. Sinaliza ao CameraWorker para parar o loop de captura.
            3. Para o cronômetro.
            4. Registra o evento no log.
            5. Transita para o estado STOPPED.

        Chamado pelo botão "Encerrar Sessão" (btn_end) OU automaticamente
        por _on_camera_error() quando a câmera falha durante uma sessão ativa.

        Nota: wait() não é usado aqui para evitar bloquear a thread principal.
        closeEvent() usa wait() com timeout ao fechar a janela.
        """
        # Se a mão robótica estiver ligada, desliga com segurança (posição
        # aberta + liberação da porta) antes de encerrar a sessão. Assíncrono
        # (não bloqueia a thread principal) — mesmo motivo já documentado
        # acima para não usar wait() aqui: a janela continua visível e
        # responsiva durante _end_session(), então travar por até ~1,5s
        # (SHUTDOWN_MAX_STEPS * SEND_INTERVAL_S, ver robot_hand_output.py)
        # esperando o Arduino desligar seria perceptível ao usuário. A
        # confirmação de que o worker terminou por completo chega depois,
        # de forma assíncrona, em _on_robot_hand_finished() (via o sinal
        # nativo 'finished' da QThread) — não neste ponto do código.
        # Em closeEvent() (mais abaixo), o mesmo desligamento É aguardado
        # com wait() bloqueante, porque ali a janela já está fechando de
        # qualquer forma e não há problema de responsividade a preservar.
        if self._robot_hand_worker is not None:
            self._stop_robot_hand()

        # Fecha a gravação CSV com segurança (flush + close).
        self.processing_worker.stop_session()

        # Sinaliza ao CameraWorker para parar o loop de captura.
        # O loop em run() verificará o evento na próxima iteração.
        self.camera_worker.stop()

        # Para o cronômetro — o display congela no tempo total da sessão.
        self.session_header.stop_timer()

        self.log_widget.log_success(
            f"Sessão encerrada. CSV salvo em: {self._csv_path}"
        )
        self._set_state("STOPPED")
        self._update_result_page_data()
        self._stack.setCurrentIndex(2)
        self._update_navigation_chrome()
        logger.info("Sessão encerrada. CSV: %s", self._csv_path)

    def _gerar_relatorio(self) -> None:
        """
        Gera o relatório PDF da sessão encerrada em uma thread separada.

        Por que uma thread separada? (Veja _PdfGeneratorWorker para explicação completa)
        Em resumo: generate_pdf_report() pode levar de 5 a 15 segundos (Matplotlib +
        FPDF) e congelaria completamente a interface se executado na thread principal.

        Comportamento:
            - Desabilita o botão PDF durante a geração (evita duplo clique).
            - Exibe mensagem na barra de status indicando o progresso.
            - Ao concluir, _on_pdf_finished() exibe diálogo de sucesso.
            - Em falha, _on_pdf_error() exibe diálogo de erro.

        Chamado pelo botão "Gerar Relatório PDF" da Tela de Resultado
        (_btn_result_pdf).
        """
        if not self._csv_path or not os.path.exists(self._csv_path):
            QMessageBox.warning(
                self,
                "CSV Não Encontrado",
                f"O arquivo CSV da sessão não foi encontrado:\n{self._csv_path}\n\n"
                "Verifique se a sessão foi encerrada corretamente.",
            )
            return

        session_info = self.session_header.get_session_info()

        # Desabilita o botão durante a geração para evitar duplos cliques.
        self._btn_result_pdf.setEnabled(False)
        self._btn_result_pdf.setText("⏳  Gerando PDF...")
        self._status_bar.showMessage("Gerando relatório PDF... Aguarde.")
        self.log_widget.log("Iniciando geração do relatório PDF...")

        # Cria e configura o worker de geração de PDF.
        self._pdf_worker = _PdfGeneratorWorker(
            csv_path=self._csv_path,
            patient_name=session_info["patient_name"],
            side=session_info["hand"],
            logo_path=os.path.abspath(os.path.join("assets", "logo_clinic.png")),
            parent=self,
        )

        # Conecta os sinais de conclusão e erro ao worker.
        self._pdf_worker.finished_signal.connect(self._on_pdf_finished)
        self._pdf_worker.error_signal.connect(self._on_pdf_error)

        # Inicia o worker de PDF na thread separada.
        self._pdf_worker.start()

    def _on_pdf_finished(self, pdf_path: str) -> None:
        """
        Trata a conclusão bem-sucedida da geração do PDF.

        Chamado pelo finished_signal do _PdfGeneratorWorker quando
        o PDF foi gerado com sucesso. Restaura o botão e exibe o resultado.

        Parâmetros:
            pdf_path: Caminho absoluto para o arquivo PDF gerado.
        """
        # Restaura o botão ao estado original.
        self._btn_result_pdf.setEnabled(True)
        self._btn_result_pdf.setText("📄  Gerar Relatório PDF")
        self._status_bar.showMessage(f"PDF gerado: {pdf_path}")
        self.log_widget.log_success(f"Relatório PDF gerado: {pdf_path}")

        # Exibe diálogo com o caminho do PDF.
        msg = QMessageBox(self)
        msg.setWindowTitle("Relatório Gerado")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setText("✅ Relatório PDF gerado com sucesso!")
        msg.setInformativeText(f"Arquivo salvo em:\n{pdf_path}")
        msg.exec()

    def _on_pdf_error(self, error_message: str) -> None:
        """
        Trata uma falha na geração do PDF.

        Chamado pelo error_signal do _PdfGeneratorWorker quando
        a geração falha (CSV inválido, disco cheio, Matplotlib ausente etc.).

        Parâmetros:
            error_message: Descrição do erro retornada pela exceção.
        """
        # Restaura o botão e reporta o erro: sem isso a interface ficaria
        # presa em "Gerando PDF..." e o operador não teria como tentar de novo.
        self._btn_result_pdf.setEnabled(True)
        self._btn_result_pdf.setText("📄  Gerar Relatório PDF")
        self._status_bar.showMessage("Falha ao gerar relatório PDF.")
        self.log_widget.log_error(f"Falha ao gerar PDF: {error_message}")

        QMessageBox.critical(
            self,
            "Erro na Geração do PDF",
            f"Não foi possível gerar o relatório PDF.\n\nDetalhe:\n{error_message}",
        )

    def _exportar_csv(self) -> None:
        """
        Exporta o CSV da sessão para um local escolhido pelo usuário.

        Abre um diálogo de arquivo para o usuário escolher onde salvar
        uma cópia do CSV. Usa shutil.copy() para preservar os dados originais.
        O arquivo original em config.LOG_DIR não é movido ou excluído.

        Chamado pelo botão "Exportar CSV" da Tela de Resultado (_btn_result_csv).
        """
        if not self._csv_path or not os.path.exists(self._csv_path):
            QMessageBox.warning(
                self,
                "CSV Não Encontrado",
                "Não há arquivo CSV disponível para exportação.",
            )
            return

        # QFileDialog.getSaveFileName: diálogo nativo "Salvar Como".
        # Sugere o nome original do arquivo por padrão.
        default_name = os.path.basename(self._csv_path)
        destination, selected_filter = QFileDialog.getSaveFileName(
            parent=self,
            caption="Exportar CSV da Sessão",
            directory=default_name,
            filter="CSV Files (*.csv);;All Files (*)",
        )

        # Se o usuário cancelou o diálogo, destination é uma string vazia.
        if not destination:
            return

        try:
            # Copia o arquivo CSV original para o destino escolhido.
            # shutil.copy() copia conteúdo E permissões, mais robusto que open().
            shutil.copy(self._csv_path, destination)
            self.log_widget.log_success(f"CSV exportado para: {destination}")
            self._status_bar.showMessage(f"CSV exportado: {destination}")

            QMessageBox.information(
                self,
                "Exportação Concluída",
                f"✅ CSV exportado com sucesso para:\n{destination}",
            )

        except (OSError, shutil.Error) as exc:
            self.log_widget.log_error(f"Falha ao exportar CSV: {exc}")
            QMessageBox.critical(
                self,
                "Erro na Exportação",
                f"Não foi possível exportar o CSV.\n\nDetalhe:\n{exc}",
            )

    def _abrir_historico(self) -> None:
        """
        Abre a pasta onde os arquivos de sessão são salvos no explorador de arquivos.

        Usa os.startfile() no Windows para abrir a pasta no Explorador de Arquivos.
        A pasta é criada se não existir antes de tentar abrir.

        Chamado pelo botão "Abrir Pasta de Sessões" da Tela de Resultado
        (_btn_result_history).
        """
        # Garante que a pasta exista antes de tentar abrir.
        os.makedirs(config.LOG_DIR, exist_ok=True)
        abs_log_dir: str = os.path.abspath(config.LOG_DIR)

        try:
            # os.startfile() é exclusivo do Windows — abre com o programa padrão.
            # No Windows, abre o Explorador de Arquivos na pasta especificada.
            os.startfile(abs_log_dir)
        except AttributeError:
            # Fallback para Linux/macOS onde os.startfile() não existe.
            import subprocess
            subprocess.Popen(["xdg-open", abs_log_dir])
        except Exception as exc:
            self.log_widget.log_error(f"Não foi possível abrir a pasta: {exc}")

    # =========================================================================
    # CICLO DE VIDA DA JANELA
    # =========================================================================

    def closeEvent(self, event) -> None:
        """
        Intercepta o evento de fechamento da janela para encerrar os workers.

        Chamado pelo Qt quando o usuário clica no botão "X" da janela ou
        quando QApplication.quit() é chamado.

        Por que wait() com timeout aqui e não em _end_session()?
            _end_session() é chamado durante a sessão enquanto a janela
            ainda está visível — bloquear a thread principal com wait() ali
            congelaria a interface por alguns quadros. Aqui, a janela está
            fechando de qualquer forma, então o bloqueio temporário é aceitável
            para garantir que os workers encerrem de forma limpa.

        Sequência:
            1. Para os workers (sinaliza encerramento).
            2. Aguarda até 3000ms por worker para finalizar.
            3. Aceita o evento de fechamento (janela fecha).

        Parâmetros:
            event: QCloseEvent fornecido pelo Qt com o evento de fechamento.
        """
        logger.info("closeEvent: encerrando workers antes de fechar.")

        # Se a mão robótica estiver ligada, desliga com segurança (posição
        # aberta + liberação da porta) ANTES de fechar a janela. Diferente de
        # _end_session() (que só chama request_stop() e retorna, sem esperar
        # — ver comentário lá), aqui é aceitável bloquear com wait(3000): a
        # janela já está fechando de qualquer forma, então não há
        # responsividade a preservar, e queremos garantir que a porta serial
        # seja liberada antes do processo terminar (mesmo raciocínio já usado
        # para camera/processing worker abaixo).
        if self._robot_hand_worker is not None:
            self._robot_hand_worker.request_stop()
            self._robot_hand_worker.wait(3000)

        # Encerra sessão ativa se houver uma.
        if self._state == "RUNNING":
            self.processing_worker.stop_session()

        # Para e aguarda o CameraWorker.
        if self.camera_worker.isRunning():
            self.camera_worker.stop()
            # wait(3000): aguarda até 3 segundos. Se o worker não finalizar,
            # o Qt forçará o encerramento da thread ao fechar o aplicativo.
            self.camera_worker.wait(3000)

        # Para e aguarda o ProcessingWorker.
        if self.processing_worker.isRunning():
            self.processing_worker.stop()
            self.processing_worker.wait(3000)

        # Para o worker de PDF se estiver gerando.
        if self._pdf_worker is not None and self._pdf_worker.isRunning():
            self._pdf_worker.wait(5000)

        logger.info("closeEvent: workers encerrados. Fechando janela.")

        # Aceita o evento — a janela fecha normalmente.
        event.accept()
