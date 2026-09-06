"""
ui/finger_card_widget.py — Cards individuais por dedo com minigráfico
=====================================================================

Este módulo implementa dois componentes visuais:

1. FingerCardWidget(QGroupBox):
   Exibe TODAS as métricas clínicas para UM único dedo em um card compacto.
   Cada instância é dedicada a um dedo específico (Polegar, Indicador, etc.).

2. FingerCardsPanel(QWidget):
   Contêiner que organiza os 5 FingerCardWidgets lado a lado em uma linha.
   É o único componente que a MainWindow precisa instanciar — ele
   gerencia os 5 cards internamente.

Métricas exibidas por card (provenientes do pipeline científico):
    TAM (°)       : Total Active Motion — amplitude ativa de movimento total.
    ASSH          : Classificação funcional (Excelente / Bom / Razoável / Ruim).
    ROM (°)       : Diferença entre o TAM máximo e mínimo na janela de tempo.
    Vel. Média    : Velocidade angular média (°/s) — velocidade geral do movimento.
    Vel. Pico     : Velocidade angular máxima (°/s) — esforço de pico.
    Frequência    : Taxa de ciclos completos por segundo (Hz).
    Regularidade  : Avaliação qualitativa da consistência do movimento.
    Minigráfico   : Histórico de TAM nos últimos BUFFER_SIZE pontos (PyQtGraph).

Fontes de dados:
    state   ← classify_hand_state()["estados_dedos"][finger]
    metrics ← compute_realtime_metrics(angle_buffer, time_buffer)

Por que um card por dedo?
    O fisioterapeuta frequentemente precisa comparar rapidamente o desempenho de
    dedos adjacentes (ex.: Indicador vs Médio após uma lesão). Exibir todos
    em uma linha permite comparação visual instantânea sem navegar por menus.
"""

from typing import Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# Importa estilos centralizados a partir do módulo de tema.
from themes import (
    FINGER_CARD_STYLE,
    LABEL_CLINICAL_SECONDARY_STYLE,
    LABEL_CLINICAL_VALUE_STYLE,
    LABEL_SECTION_TITLE_STYLE,
)
import config

# Tenta importar o PyQtGraph para os minigráficos.
# Se não estiver instalado, os minigráficos são substituídos por um rótulo.
try:
    import pyqtgraph as pg
    _PG_AVAILABLE = True
except ImportError:
    _PG_AVAILABLE = False


class FingerCardWidget(QGroupBox):
    """
    Card clínico completo para um único dedo da mão.

    Exibe métricas de goniometria, métricas cinemáticas e um minigráfico
    de TAM em tempo real em um espaço compacto projetado para ficar lado a lado com outros 4 cards.

    Layout interno (QVBoxLayout):
        ┌──────────────────────────────┐
        │ [nome do dedo]               │  ← Título do QGroupBox
        │ TAM: 127.3°  [Razoável] 🟡  │  ← TAM + ASSH em uma linha
        │ ─────────────────────────── │
        │ ROM          : 45.2°        │
        │ Vel. Média   : 38.1 °/s     │
        │ Vel. Pico    : 112.4 °/s    │
        │ Frequência   : 0.33 Hz      │
        │ Regularidade : ✅ Regular   │
        │ ─────────────────────────── │
        │ [minigráfico TAM, 80px]     │
        └──────────────────────────────┘
    """

    def __init__(
        self,
        finger_key: str,
        name_en: str,
        color_hex: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        """
        Inicializa o card para um dedo específico.

        Parâmetros:
            finger_key: Identificador interno do dedo no pipeline científico.
                        Valores: "INDEX", "MIDDLE", "RING", "PINKY", "THUMB".
            name_en: Nome de exibição do dedo para o título do grupo.
                     Ex.: "Index", "Middle", "Thumb".
            color_hex: Cor hexadecimal do dedo (de config.FINGER_COLORS).
                       Utilizada no minigráfico e elementos destacados.
            parent: Widget pai do Qt (opcional).
        """
        super().__init__(name_en, parent)

        # Armazena a chave do dedo para uso futuro (ex.: depuração, registro de log).
        self._finger_key: str = finger_key
        self._color_hex: str = color_hex

        # Aplica o estilo visual do card (borda, fundo, título).
        self.setStyleSheet(FINGER_CARD_STYLE)

        # Largura mínima para que os 5 cards não fiquem espremidos.
        # Com 5 cards em linha em uma janela de 1280px: 1280/5 = 256px por card.
        self.setMinimumWidth(200)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

        # Layout vertical principal do card.
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 16, 8, 8)
        layout.setSpacing(4)

        # --- Linha de TAM + Classificação ASSH ---
        self._build_tam_row(layout)

        # --- Separador visual ---
        self._add_separator(layout)

        # --- Grade de métricas cinemáticas ---
        self._build_metrics_grid(layout)

        # --- Separador visual ---
        self._add_separator(layout)

        # --- Minigráfico de TAM em tempo real ---
        self._build_mini_chart(layout, color_hex)

    # =========================================================================
    # CONSTRUTORES DE SEÇÕES INTERNAS
    # =========================================================================

    def _build_tam_row(self, parent_layout: QVBoxLayout) -> None:
        """
        Constrói a linha principal com o valor de TAM e classificação ASSH.

        Posiciona TAM e ASSH na mesma linha horizontal para economizar espaço vertical
        sem sacrificar a legibilidade — o TAM é o valor mais importante
        e deve ter ênfase visual imediata.

        Parâmetros:
            parent_layout: Layout pai onde a linha será adicionada.
        """
        row = QHBoxLayout()
        row.setSpacing(6)

        # Rótulo "TAM:" — indica a grandeza exibida.
        lbl_tam_title = QLabel("TAM:")
        lbl_tam_title.setStyleSheet(LABEL_SECTION_TITLE_STYLE)
        lbl_tam_title.setFixedWidth(36)

        # Valor numérico de TAM — maior ênfase visual.
        self._lbl_tam_value = QLabel("—")
        self._lbl_tam_value.setStyleSheet(LABEL_CLINICAL_VALUE_STYLE)

        # Classificação ASSH com cor dinâmica (verde/amarelo/laranja/vermelho).
        # A cor é aplicada via setStyleSheet em update(), não aqui.
        self._lbl_assh = QLabel("—")
        self._lbl_assh.setStyleSheet(LABEL_CLINICAL_SECONDARY_STYLE)
        self._lbl_assh.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        row.addWidget(lbl_tam_title)
        row.addWidget(self._lbl_tam_value)
        row.addStretch()
        row.addWidget(self._lbl_assh)

        parent_layout.addLayout(row)

    def _build_metrics_grid(self, parent_layout: QVBoxLayout) -> None:
        """
        Constrói a grade com métricas cinemáticas (ROM, velocidade, frequência).

        Utiliza uma grade de 2 colunas (rótulo | valor) para alinhar corretamente os dados sem
        desperdiçar espaço. Cada linha representa uma métrica diferente.

        Parâmetros:
            parent_layout: Layout pai onde a grade será adicionada.
        """
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(2)

        # Nomes das métricas (rótulos estáticos) e referências aos rótulos de valores.
        # A ordem segue a relevância clínica: ROM primeiro, depois velocidade,
        # frequência e regularidade (do mais objetivo ao mais interpretado).
        metrics_rows = [
            ("ROM",          "—"),
            ("Vel. Média",   "—"),
            ("Vel. Pico",    "—"),
            ("Frequência",   "—"),
            ("Regularidade", "—"),
        ]

        # Dicionário para acesso rápido em update() — mapeamento nome interno → QLabel.
        self._metric_labels: Dict[str, QLabel] = {}

        for row_idx, (label_text, init_value) in enumerate(metrics_rows):
            # Rótulo estático à esquerda.
            lbl_title = QLabel(f"{label_text}:")
            lbl_title.setStyleSheet(LABEL_CLINICAL_SECONDARY_STYLE)
            lbl_title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

            # Valor dinâmico à direita — atualizado a cada quadro com dados reais.
            lbl_value = QLabel(init_value)
            lbl_value.setStyleSheet(LABEL_CLINICAL_SECONDARY_STYLE)
            lbl_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            grid.addWidget(lbl_title, row_idx, 0)
            grid.addWidget(lbl_value, row_idx, 1)

            # Armazena referência utilizando o nome sem ":" como chave.
            self._metric_labels[label_text] = lbl_value

        # Coluna 0 (rótulos): largura fixa. Coluna 1 (valores): expande.
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)

        parent_layout.addLayout(grid)

    def _build_mini_chart(self, parent_layout: QVBoxLayout, color_hex: str) -> None:
        """
        Constrói o minigráfico de TAM em tempo real via PyQtGraph dentro do card.

        O minigráfico possui altura=80px, sem eixos visíveis, apenas a curva.
        Seu propósito é fornecer contexto temporal para o valor numérico de TAM —
        o clínico pode observar se o valor está subindo, descendo ou oscilando.

        Por que sem eixos?
            Com 5 cards em linha, cada um com apenas ~200px de largura, eixos com rótulos
            ocupariam ~30% do espaço do gráfico. A própria curva comunica a tendência
            sem a necessidade de escalas numéricas.

        Parâmetros:
            parent_layout: Layout pai onde o minigráfico será adicionado.
            color_hex: Cor da curva, correspondente ao dedo (config.FINGER_COLORS).
        """
        self._mini_curve = None
        self._mini_plot = None

        if not _PG_AVAILABLE:
            # Fallback sem PyQtGraph: exibe mensagem no lugar do gráfico.
            lbl_no_pg = QLabel("(PyQtGraph não instalado)")
            lbl_no_pg.setStyleSheet(LABEL_CLINICAL_SECONDARY_STYLE)
            lbl_no_pg.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_no_pg.setFixedHeight(80)
            parent_layout.addWidget(lbl_no_pg)
            return

        # Configura o fundo do minigráfico com o mesmo tom escuro do card.
        self._mini_plot = pg.PlotWidget()
        self._mini_plot.setBackground("#1e293b")

        # Remove a borda do widget — o QGroupBox já possui uma.
        self._mini_plot.setStyleSheet("border: none;")

        # Altura fixa de 80px — compacta porém suficiente para exibir a tendência.
        self._mini_plot.setFixedHeight(80)

        # Remove TODOS os eixos para máxima compacidade visual.
        # Eixos consumiriam ~40% da altura em um gráfico tão pequeno.
        plot_item = self._mini_plot.getPlotItem()
        plot_item.hideAxis("left")
        plot_item.hideAxis("bottom")

        # Remove o menu de contexto do botão direito — desnecessário em um minigráfico.
        plot_item.setMenuEnabled(False)

        # Desativa a interação com o mouse — o minigráfico é somente para visualização.
        self._mini_plot.setMouseEnabled(x=False, y=False)

        # Cria a curva única do minigráfico: TAM ao longo do tempo.
        # Largura 1.5px: visível em 80px de altura sem ficar espessa demais.
        self._mini_curve = plot_item.plot(
            pen=pg.mkPen(color=color_hex, width=1.5),
        )

        parent_layout.addWidget(self._mini_plot)

    def _add_separator(self, parent_layout: QVBoxLayout) -> None:
        """
        Adiciona um separador horizontal sutil entre as seções do card.

        QFrame com frameShape=HLine cria uma linha horizontal fina, utilizada
        como divisor visual entre o TAM, as métricas e o minigráfico.

        Parâmetros:
            parent_layout: Layout pai onde o separador será adicionado.
        """
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        # Sombra rebaixada: cria o efeito de uma linha sutilmente em baixo-relevo.
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        separator.setStyleSheet("color: #334155; max-height: 1px;")
        parent_layout.addWidget(separator)

    # =========================================================================
    # ATUALIZAÇÃO DE DADOS
    # =========================================================================

    def update(
        self,
        state: dict,
        metrics: dict,
        tam_buffer: List[float],
    ) -> None:
        """
        Atualiza todos os campos do card com dados do quadro atual.

        Este método é chamado pelo FingerCardsPanel a cada emissão de result_ready
        (~30x/s). Deve ser rápido: apenas atualiza textos e dados do gráfico, sem cálculos.

        Estrutura esperada de 'state' (de classify_hand_state()):
            Dedos longos: {"MCP": float, "PIP": float, "DIP": float,
                           "ABD": float, "TAM": float,
                           "fechado": bool, "rotulo_assh": str, "cor_assh": str}
            Polegar:      {"MCP": float, "IP": float, "TAM": float,
                           "fechado": bool, "rotulo_assh": str, "cor_assh": str}

        Estrutura esperada de 'metrics' (de compute_realtime_metrics()):
            {"rom": float, "vel_media": float, "vel_pico": float,
             "freq_hz": float, "cv": float, "regularidade": str, "n_picos": int}

        Parâmetros:
            state: Dicionário com ângulos atuais e classificação ASSH para o dedo.
            metrics: Dicionário com métricas cinemáticas calculadas sobre o buffer.
            tam_buffer: Lista dos últimos N valores de TAM para o minigráfico.
        """
        # --- TAM primário ---
        tam: float = float(state.get("TAM", 0.0))
        self._lbl_tam_value.setText(f"{tam:.1f}°")

        # --- Classificação ASSH com cor dinâmica ---
        assh_label: str = state.get("rotulo_assh", "—")
        assh_color: str = state.get("cor_assh", "#94a3b8")

        self._lbl_assh.setText(assh_label)

        # Aplica a cor da classificação via setStyleSheet.
        # Cada nível ASSH possui uma cor predefinida (verde/amarelo/laranja/vermelho)
        # que o clínico reconhece instantaneamente sem ler o texto.
        self._lbl_assh.setStyleSheet(
            f"QLabel {{ color: {assh_color}; font-size: 12px; font-weight: bold; }}"
        )

        # --- Métricas cinemáticas ---
        rom: float = float(metrics.get("rom", 0.0))
        vel_media: float = float(metrics.get("vel_media", 0.0))
        vel_pico: float  = float(metrics.get("vel_pico",  0.0))
        freq_hz: float   = float(metrics.get("freq_hz",   0.0))
        regularity: str = str(metrics.get("regularidade", "—"))

        # Formata ROM em graus com uma casa decimal.
        self._metric_labels["ROM"].setText(f"{rom:.1f}°")

        # Formata velocidades em graus por segundo com uma casa decimal.
        self._metric_labels["Vel. Média"].setText(f"{vel_media:.1f} °/s")
        self._metric_labels["Vel. Pico"].setText(f"{vel_pico:.1f} °/s")

        # Formata frequência em Hz com duas casas decimais.
        # Duas casas decimais são necessárias porque movimentos lentos (0.25Hz) e
        # rápidos (2.00Hz) devem ser distinguíveis com precisão.
        self._metric_labels["Frequência"].setText(f"{freq_hz:.2f} Hz")

        # Adiciona um ícone visual à regularidade para reconhecimento instantâneo.
        # O clínico pode avaliar em uma olhada rápida sem ler a palavra.
        if regularity == "Regular":
            reg_text = "✅ Regular"
        elif regularity in ("Irregular", "Moderado"):
            reg_text = f"{'❌' if regularity == 'Irregular' else '🟡'} {regularity}"
        else:
            reg_text = regularity
        self._metric_labels["Regularidade"].setText(reg_text)

        # --- Minigráfico ---
        self._update_mini_chart(tam_buffer)

    def _update_mini_chart(self, tam_buffer: List[float]) -> None:
        """
        Atualiza a curva do minigráfico com o buffer de TAM atual.

        Chamado internamente por update() a cada quadro. Se o PyQtGraph não estiver
        disponível, este método retorna silenciosamente.

        O eixo Y do minigráfico é auto-escalonado pelo PyQtGraph para se ajustar ao
        intervalo de dados atual — sem configuração explícita de limites.
        Isso faz com que a curva sempre preencha toda a altura de 80px, independentemente
        do ROM real do movimento.

        Parâmetros:
            tam_buffer: Lista de floats com valores históricos de TAM.
                        Vazia se ainda não houver dados suficientes.
        """
        if self._mini_curve is None or not _PG_AVAILABLE:
            return

        if tam_buffer:
            # setData() apenas com y: eixo X = 0, 1, 2, ... (índice da amostra).
            # Timestamps reais não são necessários no minigráfico — a tendência visual
            # é suficiente para comunicar a evolução do movimento.
            self._mini_curve.setData(y=tam_buffer)
        else:
            # Buffer vazio: limpa o gráfico para evitar exibição de dados desatualizados.
            self._mini_curve.setData(y=[])

    def clear(self) -> None:
        """
        Redefine todos os campos do card para o estado inicial sem dados.

        Chamado pelo FingerCardsPanel ao iniciar uma nova sessão, para que os
        dados da sessão anterior não sejam confundidos com os da nova sessão.
        """
        self._lbl_tam_value.setText("—")
        self._lbl_assh.setText("—")
        self._lbl_assh.setStyleSheet(LABEL_CLINICAL_SECONDARY_STYLE)

        for lbl in self._metric_labels.values():
            lbl.setText("—")

        if self._mini_curve is not None:
            self._mini_curve.setData(y=[])


# =============================================================================
# PAINEL COM OS 5 CARDS
# =============================================================================

class FingerCardsPanel(QWidget):
    """
    Contêiner que organiza os 5 FingerCardWidgets lado a lado em uma linha.

    Este é o único componente deste módulo que a MainWindow instancia diretamente.
    Internamente, ele cria e gerencia os 5 cards individuais.

    Ordem de exibição dos cards (esquerda para a direita):
        Polegar | Indicador | Médio | Anelar | Mínimo

    A ordem segue a anatomia da mão vista de frente, facilitando a
    correlação visual entre cada card na tela e o dedo real do paciente.

    Uso na MainWindow:
        self.finger_cards = FingerCardsPanel()
        layout.addWidget(self.finger_cards)
        # Em _on_result():
        self.finger_cards.update_all(
            result.hand_state["estados_dedos"],
            result.metrics_per_finger,
            result.tam_buffers_snapshot,
        )
    """

    # Ordem de exibição dos cards (da esquerda para a direita).
    # THUMB primeiro porque é anatomicamente o primeiro dedo na mão vista de frente.
    DISPLAY_ORDER: List[str] = ["THUMB", "INDEX", "MIDDLE", "RING", "PINKY"]

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """
        Inicializa o painel criando os 5 cards em uma linha.

        Cada card recebe sua chave de dedo, nome de exibição e cor identificadora
        a partir dos dicionários de config.py.

        Parâmetros:
            parent: Widget pai do Qt (opcional).
        """
        super().__init__(parent)

        # Layout horizontal: os 5 cards ficam lado a lado.
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # Espaçamento de 6px entre cards — visualmente separados porém compactos.
        layout.setSpacing(6)

        # Dicionário para acesso rápido em update_all() — chave = nome do dedo.
        self._cards: Dict[str, FingerCardWidget] = {}

        for finger_key in self.DISPLAY_ORDER:
            name_en = config.FINGER_NAMES.get(finger_key, finger_key)
            color_hex = config.FINGER_COLORS.get(finger_key, "#ffffff")

            card = FingerCardWidget(
                finger_key=finger_key,
                name_en=name_en,
                color_hex=color_hex,
                parent=self,
            )
            self._cards[finger_key] = card
            layout.addWidget(card)

        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

    def update_all(
        self,
        finger_states: Dict[str, dict],
        metrics_per_finger: Dict[str, dict],
        tam_buffers_per_finger: Dict[str, List[float]],
    ) -> None:
        """
        Atualiza todos os 5 cards com os dados do quadro atual.

        Chamado pela MainWindow a cada emissão de result_ready do ProcessingWorker.
        Itera sobre os 5 dedos e delega a atualização de cada card ao
        FingerCardWidget correspondente.

        Tolerância para dados faltantes:
            Se um dedo não estiver presente em finger_states ou metrics_per_finger
            (ex.: MediaPipe perdeu o rastreamento de um dedo específico), utilizamos dicionários
            vazios como fallback para que o card exiba "—" em vez de lançar KeyError.

        Parâmetros:
            finger_states: Dicionário {finger: state_dict} retornado por
                           classify_hand_state()["estados_dedos"].
                           Contém ângulos atuais e classificação ASSH por dedo.

            metrics_per_finger: Dicionário {finger: metrics_dict} onde cada dict é
                                a saída de compute_realtime_metrics() para aquele dedo.
                                Contém rom, vel_media, vel_pico, freq_hz, etc.

            tam_buffers_per_finger: Dicionário {finger: [float]} com o histórico de TAM
                                    para o minigráfico de cada card.
                                    Geralmente provém de ProcessingResult.tam_buffers_snapshot.
        """
        for finger_key, card in self._cards.items():
            # Acesso seguro com fallback: se o dedo não foi detectado neste quadro,
            # passamos dicionários vazios e o card exibirá "—".
            state = finger_states.get(finger_key, {})
            metrics = metrics_per_finger.get(finger_key, {})
            tam_buf = tam_buffers_per_finger.get(finger_key, [])

            card.update(state=state, metrics=metrics, tam_buffer=tam_buf)

    def clear_all(self) -> None:
        """
        Redefine todos os 5 cards para o estado inicial sem dados.

        Chamado pela MainWindow ao iniciar uma nova sessão, para limpar todos os dados
        da sessão anterior antes da câmera ser ativada.
        """
        for card in self._cards.values():
            card.clear()

    def get_card(self, finger_key: str) -> Optional[FingerCardWidget]:
        """
        Retorna o FingerCardWidget para um dedo específico.

        Útil para operações direcionadas (ex.: destacar o card de um dedo específico
        durante uma análise individual, ou ocultar temporariamente um dedo não avaliado).

        Parâmetros:
            finger_key: Chave do dedo. Ex.: "INDEX", "THUMB", "PINKY".

        Retorno:
            FingerCardWidget correspondente, ou None se a chave não existir.
        """
        return self._cards.get(finger_key)
