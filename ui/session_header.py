"""
ui/session_header.py — Cabeçalho de sessão com formulário do paciente e cronômetro
=================================================================================

Este módulo implementa o SessionHeaderWidget: a barra superior da interface que
coleta dados de identificação da sessão ANTES de iniciar a câmera.

Responsabilidades:
    1. Formulário de identificação: nome do paciente, mão avaliada, número de sessão.
    2. Controle do cronômetro: registra o horário de início e exibe o tempo decorrido.
    3. Validação de pré-condição: is_ready() garante que a sessão só inicie quando
       os dados mínimos necessários estiverem preenchidos (nome do paciente é obrigatório).

Por que coletar esses dados aqui e não no início do processamento?
    O CSV gerado pelo GoniometryCSVLogger e o PDF do session_report.py
    precisam do nome do paciente, mão avaliada e número de sessão em seus metadados.
    Coletar antes de iniciar garante que esses campos estejam sempre disponíveis
    quando o ProcessingWorker começar a gravar — sem campos em branco no arquivo de saída.

Fluxo de uso no MainWindow:
    1. Usuário preenche o formulário.
    2. MainWindow chama is_ready() — monitora via QLineEdit.textChanged.
    3. Quando pronto, o botão Iniciar é habilitado.
    4. Ao clicar em Iniciar: MainWindow chama get_session_info() e start_timer().
    5. Ao clicar em Encerrar: MainWindow chama stop_timer().
"""

from datetime import datetime, timedelta
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from themes import (
    COLOR_ACCENT,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    LABEL_SECTION_TITLE_STYLE,
    SESSION_HEADER_STYLE,
)


class SessionHeaderWidget(QWidget):
    """
    Cabeçalho da sessão clínica com dados do paciente e cronômetro em tempo real.

    Inserido no topo do painel clínico rolável da Tela de Avaliação (Página 0),
    permanecendo visível durante a avaliação ativa (estado RUNNING) para exibir
    a identificação do paciente, a mão avaliada, o número da sessão e a contagem
    progressiva de tempo de coleta.

    Layout visual:
        ┌───────────────────────────────────────────────────────────────────────┐
        │ Paciente: [___________________] Mão: [▾] Sessão: [▲1▼] │Início: 14:35│
        │                                                          │Decorrido: 00:12:48│
        └───────────────────────────────────────────────────────────────────────┘

    Campos e cronômetro:
        - Identificação: exibe nome do paciente, mão avaliada (Direita/Esquerda) e sessão.
        - Cronômetro: registra o horário de início (start_timer) e formata o tempo
          decorrido em HH:MM:SS a cada segundo via QTimer interno.
    """

    hand_changed = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """
        Inicializa o cabeçalho com todos os campos do formulário e o cronômetro de sessão.

        O QTimer interno (_timer) é criado aqui mas NÃO iniciado —
        é ativado apenas quando start_timer() é chamado pelo MainWindow.
        Isso garante que o cronômetro não inicie antes do início da sessão.

        Parâmetros:
            parent: Widget pai Qt (opcional). Geralmente o MainWindow.
        """
        super().__init__(parent)

        # Aplica estilo visual diferenciado para separar o cabeçalho do restante.
        self.setStyleSheet(SESSION_HEADER_STYLE)

        # Política de tamanho: expande horizontalmente, altura fixa.
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

        # Layout horizontal principal — todos os campos estão na mesma linha.
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(12, 8, 12, 8)
        main_layout.setSpacing(16)

        # === CAMPO: Nome do Paciente ===
        self._build_patient_field(main_layout)

        # === CAMPO: Mão Avaliada ===
        self._build_hand_field(main_layout)

        # === CAMPO: Número de Sessão ===
        self._build_session_number_field(main_layout)

        # Separador vertical entre formulário e cronômetro.
        self._add_vertical_separator(main_layout)

        # === CRONÔMETRO: Horário de Início + Tempo Decorrido ===
        self._build_timer_display(main_layout)

        # Empurra o conteúdo à esquerda, mantendo o cronômetro alinhado à direita.
        main_layout.addStretch()

        # === CRONÔMETRO INTERNO ===
        # QTimer que dispara a cada 1000ms para atualizar o tempo decorrido.
        # interval=1000ms garante precisão em nível de segundo sem sobrecarga de CPU.
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

        # Timestamp de quando start_timer() foi chamado.
        # None indica que a sessão ainda não iniciou.
        self._start_time: Optional[datetime] = None

    # =========================================================================
    # CONSTRUTORES DO FORMULÁRIO
    # =========================================================================

    def _build_patient_field(self, layout: QHBoxLayout) -> None:
        """
        Cria o campo de nome do paciente com rótulo e QLineEdit.

        O nome é o único campo OBRIGATÓRIO — is_ready() retorna False
        enquanto este campo estiver vazio ou contiver apenas espaços.

        Parâmetros:
            layout: Layout pai onde o grupo de widgets será adicionado.
        """
        # Container vertical: rótulo em cima, campo de texto abaixo.
        container = QVBoxLayout()
        container.setSpacing(2)
        container.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel("Paciente")
        lbl.setStyleSheet(LABEL_SECTION_TITLE_STYLE)

        # QLineEdit com placeholder para orientar o usuário.
        # maxLength=100: evita nomes excessivamente longos que poderiam
        # causar problemas no nome do arquivo CSV gerado.
        self._input_patient = QLineEdit()
        self._input_patient.setPlaceholderText("Nome completo do paciente...")
        self._input_patient.setMaxLength(100)
        self._input_patient.setMinimumWidth(220)
        self._input_patient.setStyleSheet(
            f"QLineEdit {{ color: {COLOR_TEXT_PRIMARY}; padding: 4px 8px; "
            f"border: 1px solid #334155; border-radius: 5px; "
            f"background: #16213e; font-size: 13px; }}"
            f"QLineEdit:focus {{ border-color: {COLOR_ACCENT}; }}"
        )

        container.addWidget(lbl)
        container.addWidget(self._input_patient)
        layout.addLayout(container)

    def _build_hand_field(self, layout: QHBoxLayout) -> None:
        """
        Cria o seletor de mão avaliada com QComboBox.

        "Direita" e "Esquerda" correspondem ao parâmetro 'side' do
        generate_pdf_report() e ao parâmetro eh_mao_direita do DigitalGoniometer.

        Parâmetros:
            layout: Layout pai onde o grupo de widgets será adicionado.
        """
        container = QVBoxLayout()
        container.setSpacing(2)
        container.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel("Mão Avaliada")
        lbl.setStyleSheet(LABEL_SECTION_TITLE_STYLE)

        self._combo_hand = QComboBox()
        self._combo_hand.addItems(["Direita", "Esquerda"])
        self._combo_hand.setMinimumWidth(100)
        self._combo_hand.currentTextChanged.connect(self.hand_changed.emit)
        self._combo_hand.setStyleSheet(
            f"QComboBox {{ color: {COLOR_TEXT_PRIMARY}; padding: 4px 8px; "
            f"border: 1px solid #334155; border-radius: 5px; "
            f"background: #16213e; font-size: 13px; }}"
            f"QComboBox:focus {{ border-color: {COLOR_ACCENT}; }}"
            f"QComboBox QAbstractItemView {{ background: #16213e; "
            f"color: {COLOR_TEXT_PRIMARY}; selection-background-color: {COLOR_ACCENT}; }}"
        )

        container.addWidget(lbl)
        container.addWidget(self._combo_hand)
        layout.addLayout(container)

    def _build_session_number_field(self, layout: QHBoxLayout) -> None:
        """
        Cria o campo de número de sessão com QSpinBox.

        O número de sessão identifica cronologicamente as avaliações do mesmo
        paciente. Padrão é 1; o clínico incrementa manualmente
        para cada nova sessão com o mesmo paciente.

        Parâmetros:
            layout: Layout pai onde o grupo de widgets será adicionado.
        """
        container = QVBoxLayout()
        container.setSpacing(2)
        container.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel("Sessão Nº")
        lbl.setStyleSheet(LABEL_SECTION_TITLE_STYLE)

        # Mínimo 1: sessão 0 ou negativa não faz sentido.
        # Máximo 999: razoável para qualquer histórico clínico real.
        self._spin_session = QSpinBox()
        self._spin_session.setMinimum(1)
        self._spin_session.setMaximum(999)
        self._spin_session.setValue(1)
        self._spin_session.setMinimumWidth(70)
        self._spin_session.setStyleSheet(
            f"QSpinBox {{ color: {COLOR_TEXT_PRIMARY}; padding: 4px 8px; "
            f"border: 1px solid #334155; border-radius: 5px; "
            f"background: #16213e; font-size: 13px; }}"
            f"QSpinBox:focus {{ border-color: {COLOR_ACCENT}; }}"
        )

        container.addWidget(lbl)
        container.addWidget(self._spin_session)
        layout.addLayout(container)

    def _build_timer_display(self, layout: QHBoxLayout) -> None:
        """
        Cria o display do cronômetro com horário de início e tempo decorrido.

        Ambos os rótulos são empilhados verticalmente, alinhados à direita.
        O horário de início é preenchido por start_timer().
        O tempo decorrido é atualizado por _tick() a cada segundo.

        Parâmetros:
            layout: Layout pai onde o display será adicionado.
        """
        container = QVBoxLayout()
        container.setSpacing(4)
        container.setContentsMargins(0, 0, 0, 0)
        container.setAlignment(Qt.AlignmentFlag.AlignRight)

        # --- Linha "Início:" ---
        row_start = QHBoxLayout()
        row_start.setSpacing(6)

        lbl_start_title = QLabel("Início:")
        lbl_start_title.setStyleSheet(LABEL_SECTION_TITLE_STYLE)

        # Preenchido por start_timer() com o horário real de início.
        self._lbl_start_time = QLabel("—")
        self._lbl_start_time.setStyleSheet(
            f"QLabel {{ color: {COLOR_TEXT_PRIMARY}; font-size: 14px; "
            f"font-weight: bold; font-family: 'Consolas', monospace; }}"
        )

        row_start.addWidget(lbl_start_title)
        row_start.addWidget(self._lbl_start_time)

        # --- Linha "Decorrido:" ---
        row_elapsed = QHBoxLayout()
        row_elapsed.setSpacing(6)

        lbl_elapsed_title = QLabel("Decorrido:")
        lbl_elapsed_title.setStyleSheet(LABEL_SECTION_TITLE_STYLE)

        # Atualizado a cada segundo pelo QTimer via _tick().
        # Fonte monoespaçada: evita "pulo" no layout quando dígitos mudam
        # (dígitos de largura variável em fontes proporcionais causam deslocamento do texto).
        self._lbl_elapsed = QLabel("00:00:00")
        self._lbl_elapsed.setStyleSheet(
            f"QLabel {{ color: {COLOR_ACCENT}; font-size: 18px; "
            f"font-weight: bold; font-family: 'Consolas', monospace; }}"
        )

        row_elapsed.addWidget(lbl_elapsed_title)
        row_elapsed.addWidget(self._lbl_elapsed)

        container.addLayout(row_start)
        container.addLayout(row_elapsed)
        layout.addLayout(container)

    def _add_vertical_separator(self, layout: QHBoxLayout) -> None:
        """
        Adiciona um separador vertical entre o formulário e o cronômetro.

        QFrame com frameShape=VLine cria uma barra vertical fina usada como
        divisor visual para separar logicamente as duas seções do cabeçalho:
        dados de identificação (à esquerda) e cronômetro (à direita).

        Parâmetros:
            layout: Layout pai onde o separador será inserido.
        """
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        separator.setStyleSheet("color: #334155;")
        separator.setFixedWidth(2)
        layout.addWidget(separator)

    # =========================================================================
    # INTERFACE PÚBLICA — usada pelo MainWindow
    # =========================================================================

    def is_ready(self) -> bool:
        """
        Verifica se as condições mínimas para iniciar uma sessão estão satisfeitas.

        Condição obrigatória: nome do paciente preenchido (não vazio, não apenas espaços).
        A mão avaliada e o número de sessão sempre possuem valores padrão válidos,
        portanto não precisam de validação separada.

        Usado pelo MainWindow para habilitar/desabilitar o botão "Iniciar Sessão"
        em resposta a eventos QLineEdit.textChanged.

        Retorna:
            bool: True se o nome do paciente estiver preenchido, False caso contrário.
        """
        # strip() remove espaços iniciais/finais — evita que "   " (somente espaços)
        # seja aceito como nome válido, o que criaria arquivos CSV sem
        # identificação real.
        return bool(self._input_patient.text().strip())

    def get_session_info(self) -> dict:
        """
        Retorna os dados do formulário como dicionário para uso no pipeline.

        Deve ser chamado pelo MainWindow ao iniciar a sessão, DEPOIS que is_ready()
        retornar True. Os dados retornados alimentam:
        - ProcessingWorker.start_session(csv_path): nome + sessão para o nome do arquivo.
        - generate_pdf_report(): patient_name e side para o relatório PDF.
        - GoniometryCSVLogger: metadados no cabeçalho do CSV.

        Retorna:
            dict com chaves:
                patient_name (str): Nome completo do paciente sem espaços extras.
                hand (str): "Direita" ou "Esquerda" — conforme selecionado no ComboBox.
                session_number (int): Número da sessão (1–999).
                start_time (datetime | None): Horário de início da sessão,
                    ou None se start_timer() ainda não foi chamado.
        """
        return {
            # strip() garante que o nome não contenha espaços desnecessários
            # que poderiam aparecer no nome do arquivo CSV ou no PDF.
            "patient_name": self._input_patient.text().strip(),
            "hand": self._combo_hand.currentText(),
            "session_number": self._spin_session.value(),
            "start_time": self._start_time,
        }

    def start_timer(self) -> None:
        """
        Registra o horário de início da sessão e ativa o cronômetro.

        Chamado pelo MainWindow imediatamente após iniciar os workers.
        Faz três coisas:
        1. Registra datetime.now() como ponto zero do cronômetro.
        2. Exibe o horário de início no rótulo correspondente.
        3. Inicia o QTimer que chamará _tick() a cada 1000ms.

        Por que datetime.now() e não time.monotonic()?
            datetime.now() fornece o horário real do relógio (para exibir "14:35:12")
            E permite calcular o tempo decorrido subtraindo datetimes.
            time.monotonic() seria mais preciso para intervalos, mas não fornece
            o horário do dia — seriam necessárias duas variáveis separadas.
        """
        # Registra o momento exato de início com precisão de microssegundos.
        # Os microssegundos são truncados na exibição mas mantidos internamente
        # para que _tick() calcule o tempo decorrido com precisão em nível de segundo.
        self._start_time = datetime.now()

        # Exibe o horário de início formatado como HH:MM:SS.
        self._lbl_start_time.setText(
            self._start_time.strftime("%H:%M:%S")
        )

        # Reseta a exibição do tempo decorrido para garantir que mostre 00:00:00
        # antes do primeiro _tick() ser chamado (após ~1 segundo).
        self._lbl_elapsed.setText("00:00:00")

        # Inicia o cronômetro — a partir de agora _tick() será chamado a cada segundo.
        # Se o cronômetro já estiver ativo (chamada duplicada), start() o reinicia.
        self._timer.start()

    def stop_timer(self) -> None:
        """
        Para o cronômetro e congela a exibição do tempo decorrido.

        Chamado pelo MainWindow ao encerrar a sessão. A exibição congela no
        último valor mostrado, permitindo que o clínico leia a duração total
        da sessão mesmo após o processamento parar.

        Este método não limpa o horário de início nem o tempo decorrido —
        esses permanecem visíveis para referência até uma nova sessão iniciar.
        """
        # Para o QTimer — _tick() não será mais chamado.
        if self._timer.isActive():
            self._timer.stop()

    def reset(self) -> None:
        """
        Redefine o formulário e o cronômetro para o estado inicial.

        Chamado pelo MainWindow ao iniciar uma nova sessão após uma anterior
        ter terminado, ou ao clicar no botão "Nova Sessão".
        Não incrementa o número de sessão — isso deve ser feito manualmente
        pelo clínico para manter controle sobre a numeração das sessões.

        Nota: não limpa o nome do paciente — o clínico pode querer
        iniciar outra sessão para o mesmo paciente sem redigitar.
        """
        # Para o cronômetro se estiver ativo.
        self.stop_timer()

        # Limpa referências de tempo.
        self._start_time = None

        # Redefine os displays para o estado "sem dados".
        self._lbl_start_time.setText("—")
        self._lbl_elapsed.setText("00:00:00")

    def set_fields_enabled(self, enabled: bool) -> None:
        """
        Habilita ou desabilita os campos de entrada do formulário.

        Chamado pelo MainWindow ao transitar entre estados:
        - RUNNING: desabilita os campos (não alterar dados durante a gravação).
        - STOPPED/IDLE: habilita os campos (permite edição para a próxima sessão).

        Parâmetros:
            enabled: True para habilitar edição, False para bloquear.
        """
        self._input_patient.setEnabled(enabled)
        self._combo_hand.setEnabled(enabled)
        self._spin_session.setEnabled(enabled)

    # =========================================================================
    # LÓGICA INTERNA DO CRONÔMETRO
    # =========================================================================

    def _tick(self) -> None:
        """
        Calcula e exibe o tempo decorrido desde o início da sessão.

        Chamado pelo QTimer interno a cada 1000ms (1 segundo).
        Não deve ser chamado diretamente — está conectado ao cronômetro em start_timer().

        Por que calcular o decorrido a cada tick em vez de incrementar um contador?
            Incrementar um contador inteiro (seconds += 1) acumula erros: se algum
            tick demorar mais de 1 segundo (ex., CPU sobrecarregada), o contador ficaria
            atrás do relógio real. Calcular o decorrido como (agora - início) sempre
            dá o tempo real correto independentemente das variações do intervalo do QTimer.
        """
        if self._start_time is None:
            # Guarda defensiva: cronômetro rodando sem horário de início definido.
            return

        # Calcula o intervalo real decorrido desde o início da sessão.
        elapsed: timedelta = datetime.now() - self._start_time

        # Extrai horas, minutos e segundos do timedelta.
        # total_seconds() retorna o total como float.
        # Dividimos e aplicamos módulo para obter H:M:S independentemente.
        total_seconds: int = int(elapsed.total_seconds())

        # Horas, minutos e segundos restantes.
        hours: int = total_seconds // 3600
        minutes: int = (total_seconds % 3600) // 60
        seconds: int = total_seconds % 60

        # Formata como "HH:MM:SS" com zeros à esquerda.
        # :02d = inteiro com mínimo 2 dígitos, preenchido com zero.
        elapsed_str: str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        self._lbl_elapsed.setText(elapsed_str)
