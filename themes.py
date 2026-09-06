"""
themes.py — Tema visual escuro profissional para a interface PyQt6
====================================================================

Este módulo é responsável pela identidade visual de TODA a aplicação.
Ao centralizar cores, fontes e estilos aqui, garantimos que qualquer
alteração visual futura seja feita em um único ponto e propagada
automaticamente para todos os widgets.

Uso:
    No app_pyqt.py, após criar a QApplication, chame:
        from themes import apply_dark_theme
        apply_dark_theme(app)

    Em widgets individuais, importe as constantes de estilo:
        from themes import CARD_STYLE, LABEL_TITLE_STYLE

Filosofia de design:
    O tema escuro foi escolhido porque:
    1. Reduz o cansaço visual durante longas sessões clínicas.
    2. Aumenta o contraste dos gráficos coloridos (PyQtGraph).
    3. É o padrão de fato em aplicações médicas e científicas modernas.
    4. O overlay de vídeo com fundo escuro (produzido por goniometry_overlay.py)
       integra-se de forma natural e uniforme ao restante da janela.
"""

from PyQt6.QtGui import QColor, QPalette, QFont
from PyQt6.QtWidgets import QApplication


# =============================================================================
# PALETA DE CORES BASE
# =============================================================================
# Estas constantes definem os tons fundamentais do tema.
# Todos os estilos abaixo derivam dessas definições.
# Alterar estes valores afeta toda a aplicação — utilize com cuidado.

# Cor de fundo principal da janela e dos painéis.
# #1a1a2e: azul marinho muito escuro. Escolhido por ser menos plano que o preto puro (#000000)
# e criar profundidade visual sem causar cansaço aos olhos.
COLOR_BG_DARK = "#1a1a2e"

# Cor de fundo secundária dos widgets (cartões, grupos, painéis internos).
# Levemente mais clara que BG_DARK para criar hierarquia visual sem contraste excessivo.
COLOR_BG_MEDIUM = "#16213e"

# Cor de fundo para elementos interativos em repouso (botões, campos de texto).
COLOR_BG_LIGHT = "#0f3460"

# Cor do texto principal — branco suave.
# Evitamos o branco puro (#ffffff) porque em fundos escuros ele provoca vibração
# visual (conhecida como "irradiação simultânea"). #e2e8f0 é mais confortável para leitura.
COLOR_TEXT_PRIMARY = "#e2e8f0"

# Cor do texto secundário — para legendas, valores auxiliares, marcadores de posição.
COLOR_TEXT_SECONDARY = "#94a3b8"

# Cor de destaque — azul ciano vibrante.
# Usada em bordas de foco, indicadores ativos e elementos de ação primária.
COLOR_ACCENT = "#38bdf8"

# Cor de sucesso — verde para estados positivos (mão detectada, sessão ativa, "Regular").
COLOR_SUCCESS = "#22c55e"

# Cor de aviso — amarelo para estados de alerta, como resultado clínico "Bom" e regularidade "Moderado".
COLOR_WARNING = "#eab308"

# Cor de perigo — vermelho para estados críticos (mão fechada, erros, "Ruim").
COLOR_DANGER = "#ef4444"

# Cor padrão de borda — cinza escuro para separar seções sem agressividade visual.
COLOR_BORDER = "#334155"

# Cor de fundo dos cartões de métrica — sutilmente diferente do fundo médio
# para criar "elevação" visual sem recorrer a sombras (que têm custo elevado no PyQt6).
COLOR_CARD_BG = "#1e293b"


# =============================================================================
# FUNÇÃO PRINCIPAL DE APLICAÇÃO DO TEMA
# =============================================================================

def apply_dark_theme(app: QApplication) -> None:
    """
    Aplica o tema escuro profissional à instância da QApplication.

    Esta função deve ser chamada UMA VEZ, imediatamente após criar a
    QApplication e ANTES de criar qualquer janela ou widget. Isso garante
    que todos os elementos criados posteriormente herdem o tema correto.

    O Qt propaga o QPalette automaticamente para todos os widgets filhos.
    Portanto, configurar apenas a paleta da QApplication é suficiente —
    não há necessidade de definir cores individualmente por widget.

    Parâmetros:
        app: Instância da QApplication criada no app_pyqt.py.
             Deve ser o objeto retornado por QApplication(sys.argv).

    Retorna:
        None. A modificação é aplicada diretamente ao objeto app.
    """
    # Cria uma nova paleta de cores do zero para evitar herdar valores
    # inesperados do tema padrão do sistema operacional.
    palette = QPalette()

    # --- Definição da paleta de cores ---
    # O Qt organiza cores por "grupo" (Normal, Disabled, Inactive) e por "função" (role).
    # Configuramos apenas o grupo Normal — os grupos Disabled e Inactive herdam
    # automaticamente com tons suavizados aplicados pelo Qt.

    # Fundo das janelas principais (QMainWindow, QDialog).
    palette.setColor(QPalette.ColorRole.Window, QColor(COLOR_BG_DARK))

    # Texto sobre fundos de janela — deve ter contraste suficiente com Window.
    palette.setColor(QPalette.ColorRole.WindowText, QColor(COLOR_TEXT_PRIMARY))

    # Fundo dos widgets de entrada (QLineEdit, QTextEdit, QComboBox).
    # Usando BG_MEDIUM para distinguir campos de texto do fundo da janela.
    palette.setColor(QPalette.ColorRole.Base, QColor(COLOR_BG_MEDIUM))

    # Fundo alternado em listas e tabelas (linhas pares vs ímpares).
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(COLOR_BG_LIGHT))

    # Cor do texto dentro dos campos de entrada (QLineEdit, QTextEdit).
    palette.setColor(QPalette.ColorRole.Text, QColor(COLOR_TEXT_PRIMARY))

    # Fundo dos botões (QPushButton).
    palette.setColor(QPalette.ColorRole.Button, QColor(COLOR_BG_LIGHT))

    # Texto sobre os botões — claro para contraste com BG_LIGHT.
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(COLOR_TEXT_PRIMARY))

    # Cor de destaque: fundo de itens selecionados, barras de progresso, etc.
    palette.setColor(QPalette.ColorRole.Highlight, QColor(COLOR_ACCENT))

    # Texto sobre fundo de destaque — escuro para garantir legibilidade
    # quando o item estiver selecionado (contraste com o azul ciano de Highlight).
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#0f172a"))

    # Cor do texto em campos desabilitados — cinza mais escuro para indicar visualmente
    # que o campo está indisponível.
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.WindowText,
        QColor("#475569"),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        QColor("#475569"),
    )

    # Cor utilizada para dicas de ferramenta (tooltips).
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(COLOR_BG_LIGHT))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(COLOR_TEXT_PRIMARY))

    # Aplica a paleta configurada a toda a aplicação.
    # Este é o único ponto onde a paleta precisa ser definida —
    # todos os widgets criados posteriormente a herdarão automaticamente.
    app.setPalette(palette)

    # Aplica uma folha de estilo Qt (QSS) global para refinar elementos que o QPalette
    # não controla diretamente. A folha de estilo tem precedência sobre o QPalette.
    app.setStyleSheet(_build_global_stylesheet())


def _build_global_stylesheet() -> str:
    """
    Constrói e retorna a folha de estilo Qt (QSS) global da aplicação.

    O Qt utiliza uma sintaxe similar ao CSS padrão para estilizar widgets.
    Esta função centraliza todos os estilos que exigem mais controle
    do que o QPalette oferece (bordas, arredondamento, espaçamento, foco, etc.).

    Retorna:
        str: String contendo a Qt StyleSheet (QSS) completa.
    """
    return f"""
        /* ── Janela principal ── */
        QMainWindow {{
            background-color: {COLOR_BG_DARK};
        }}

        /* ── Widgets genéricos ── */
        QWidget {{
            background-color: {COLOR_BG_DARK};
            color: {COLOR_TEXT_PRIMARY};
            font-family: 'Segoe UI', 'Inter', 'Helvetica Neue', sans-serif;
            font-size: 13px;
        }}

        /* ── Grupos de widgets (QGroupBox) ──
           Usados como contêineres visuais para cada seção do layout.
           O border-radius confere aspecto moderno sem excesso. */
        QGroupBox {{
            background-color: {COLOR_BG_MEDIUM};
            border: 1px solid {COLOR_BORDER};
            border-radius: 8px;
            margin-top: 12px;
            padding: 8px;
            font-weight: bold;
            font-size: 12px;
            color: {COLOR_TEXT_SECONDARY};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 0 6px;
            color: {COLOR_ACCENT};
        }}

        /* ── Botões principais ──
           Estilo base com cantos arredondados. Os estados hover e pressionado
           fornecem feedback visual imediato ao clique. */
        QPushButton {{
            background-color: {COLOR_BG_LIGHT};
            color: {COLOR_TEXT_PRIMARY};
            border: 1px solid {COLOR_BORDER};
            border-radius: 6px;
            padding: 8px 18px;
            font-weight: bold;
            min-height: 32px;
        }}
        QPushButton:hover {{
            background-color: {COLOR_ACCENT};
            color: #0f172a;
            border-color: {COLOR_ACCENT};
        }}
        QPushButton:pressed {{
            background-color: #0284c7;
            color: #ffffff;
        }}
        QPushButton:disabled {{
            background-color: #1e293b;
            color: #475569;
            border-color: #1e293b;
        }}

        /* ── Campos de entrada de texto (QLineEdit) ── */
        QLineEdit {{
            background-color: {COLOR_BG_MEDIUM};
            color: {COLOR_TEXT_PRIMARY};
            border: 1px solid {COLOR_BORDER};
            border-radius: 5px;
            padding: 5px 8px;
            min-height: 28px;
        }}
        QLineEdit:focus {{
            border-color: {COLOR_ACCENT};
        }}
        QLineEdit:disabled {{
            color: #475569;
            background-color: #0f172a;
        }}

        /* ── ComboBox (listas suspensas) ── */
        QComboBox {{
            background-color: {COLOR_BG_MEDIUM};
            color: {COLOR_TEXT_PRIMARY};
            border: 1px solid {COLOR_BORDER};
            border-radius: 5px;
            padding: 4px 8px;
            min-height: 28px;
        }}
        QComboBox:focus {{
            border-color: {COLOR_ACCENT};
        }}
        QComboBox QAbstractItemView {{
            background-color: {COLOR_BG_MEDIUM};
            color: {COLOR_TEXT_PRIMARY};
            selection-background-color: {COLOR_ACCENT};
            selection-color: #0f172a;
            border: 1px solid {COLOR_BORDER};
        }}

        /* ── SpinBox (campos numéricos incrementais) ── */
        QSpinBox {{
            background-color: {COLOR_BG_MEDIUM};
            color: {COLOR_TEXT_PRIMARY};
            border: 1px solid {COLOR_BORDER};
            border-radius: 5px;
            padding: 4px 8px;
            min-height: 28px;
        }}
        QSpinBox:focus {{
            border-color: {COLOR_ACCENT};
        }}

        /* ── Área de texto (QTextEdit) — usada pelo LogWidget ── */
        QTextEdit {{
            background-color: #0d1117;
            color: {COLOR_TEXT_SECONDARY};
            border: 1px solid {COLOR_BORDER};
            border-radius: 5px;
            padding: 4px;
            font-family: 'Consolas', 'Courier New', monospace;
            font-size: 11px;
        }}

        /* ── Barras de rolagem ──
           Finas e discretas para evitar competição visual com o conteúdo principal. */
        QScrollBar:vertical {{
            background: {COLOR_BG_DARK};
            width: 8px;
            border-radius: 4px;
        }}
        QScrollBar::handle:vertical {{
            background: {COLOR_BORDER};
            border-radius: 4px;
            min-height: 20px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {COLOR_ACCENT};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}

        /* ── Separadores horizontais (QFrame::HLine) ── */
        QFrame[frameShape="4"] {{
            color: {COLOR_BORDER};
            max-height: 1px;
        }}

        /* ── Rótulos genéricos (QLabel) ── */
        QLabel {{
            color: {COLOR_TEXT_PRIMARY};
            background: transparent;
        }}

        /* ── Dicas de ferramenta (Tooltips / QToolTip) ── */
        QToolTip {{
            background-color: {COLOR_BG_LIGHT};
            color: {COLOR_TEXT_PRIMARY};
            border: 1px solid {COLOR_ACCENT};
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
        }}
    """


# =============================================================================
# CONSTANTES DE ESTILO REUTILIZÁVEIS
# =============================================================================
# Estas strings de StyleSheet são importadas por widgets individuais
# e aplicadas via widget.setStyleSheet(CONSTANTE). Centralizá-las aqui evita
# duplicação de código e assegura consistência visual em todos os widgets.

# Estilo base para cartões de métrica (FPS, CPU, RAM, estado da mão).
# Usado por: ui/metrics_widget.py -> MetricsWidget
# QFrame com fundo levemente mais claro que o painel e borda sutil para "elevação".
CARD_STYLE: str = f"""
    .QFrame {{
        background-color: {COLOR_CARD_BG};
        border: 1px solid {COLOR_BORDER};
        border-radius: 8px;
        padding: 8px;
    }}
"""

# Estilo para o título dentro dos cartões de métrica (ex: "FPS", "CPU").
# Texto pequeno em cor secundária — não deve competir com o valor principal.
# Usado por: ui/metrics_widget.py -> rótulos dos cartões
LABEL_TITLE_STYLE: str = f"""
    QLabel {{
        color: {COLOR_TEXT_SECONDARY};
        font-size: 11px;
        font-weight: normal;
        background: transparent;
        border: none;
    }}
"""

# Estilo para o valor numérico principal dentro dos cartões (ex: "58.3", "24%").
# Texto grande em negrito — deve ser o elemento mais legível do cartão.
# Usado por: ui/metrics_widget.py -> valores dos cartões
LABEL_VALUE_STYLE: str = f"""
    QLabel {{
        color: {COLOR_TEXT_PRIMARY};
        font-size: 22px;
        font-weight: bold;
        background: transparent;
        border: none;
    }}
"""

# Estilo para o cartão de estado da mão quando MÃO ABERTA.
# Fundo verde suave — indicador positivo e não agressivo.
# Usado por: ui/metrics_widget.py -> cartão de estado
CARD_HAND_OPEN_STYLE: str = f"""
    .QFrame {{
        background-color: #14532d;
        border: 1px solid {COLOR_SUCCESS};
        border-radius: 8px;
        padding: 8px;
    }}
"""

# Estilo para o cartão de estado da mão quando MÃO FECHADA.
# Fundo vermelho escuro — indicador de alerta clínico.
# Usado por: ui/metrics_widget.py -> cartão de estado
CARD_HAND_CLOSED_STYLE: str = f"""
    .QFrame {{
        background-color: #7f1d1d;
        border: 1px solid {COLOR_DANGER};
        border-radius: 8px;
        padding: 8px;
    }}
"""

# Estilo para o texto de estado da mão (grande, centralizado, negrito).
# Usado por: ui/metrics_widget.py -> rótulo dentro do cartão de estado
LABEL_HAND_STATE_STYLE: str = f"""
    QLabel {{
        color: {COLOR_TEXT_PRIMARY};
        font-size: 18px;
        font-weight: bold;
        background: transparent;
        border: none;
    }}
"""

# Estilo para o cabeçalho da sessão (SessionHeaderWidget).
# Fundo diferenciado para separá-lo visualmente do restante do layout.
# Usado por: ui/session_header.py -> contêiner principal
SESSION_HEADER_STYLE: str = f"""
    .QWidget {{
        background-color: {COLOR_BG_MEDIUM};
        border-bottom: 2px solid {COLOR_ACCENT};
    }}
"""

# Estilo para os rótulos de título de seção dentro do cabeçalho.
# Texto destacado na cor de acento — identifica com clareza a finalidade do campo.
# Usado por: ui/session_header.py -> rótulos dos campos
LABEL_SECTION_TITLE_STYLE: str = f"""
    QLabel {{
        color: {COLOR_ACCENT};
        font-size: 12px;
        font-weight: bold;
        background: transparent;
    }}
"""

# Estilo para cada cartão de dedo (FingerCardWidget).
# Mais compacto que CARD_STYLE — 5 cartões organizados lado a lado no layout.
# Usado por: ui/finger_card_widget.py -> contêiner de cada dedo
FINGER_CARD_STYLE: str = f"""
    QGroupBox {{
        background-color: {COLOR_CARD_BG};
        border: 1px solid {COLOR_BORDER};
        border-radius: 8px;
        margin-top: 10px;
        padding: 6px;
    }}
    QGroupBox::title {{
        color: {COLOR_ACCENT};
        font-weight: bold;
        font-size: 12px;
        subcontrol-origin: margin;
        subcontrol-position: top center;
        padding: 0 4px;
    }}
"""

# Estilo para rótulos de valores clínicos dentro dos cartões de dedos.
# Tamanho intermediário — legível sem dominar visualmente o cartão.
# Usado por: ui/finger_card_widget.py -> TAM, velocidade, frequência
LABEL_CLINICAL_VALUE_STYLE: str = f"""
    QLabel {{
        color: {COLOR_TEXT_PRIMARY};
        font-size: 14px;
        font-weight: bold;
        background: transparent;
    }}
"""

# Estilo para rótulos de métricas secundárias dentro dos cartões de dedos.
# Texto menor — informação complementar de apoio ao valor principal.
# Usado por: ui/finger_card_widget.py -> ROM, regularidade
LABEL_CLINICAL_SECONDARY_STYLE: str = f"""
    QLabel {{
        color: {COLOR_TEXT_SECONDARY};
        font-size: 11px;
        background: transparent;
    }}
"""

# Estilo para o botão de ação principal (Iniciar Sessão).
# Destacado com a cor de sucesso para indicar ação positiva e segura.
# Usado por: ui/main_window.py -> botão Iniciar
BUTTON_PRIMARY_STYLE: str = f"""
    QPushButton {{
        background-color: #15803d;
        color: #ffffff;
        border: 1px solid {COLOR_SUCCESS};
        border-radius: 6px;
        padding: 8px 18px;
        font-weight: bold;
        min-height: 36px;
        font-size: 13px;
    }}
    QPushButton:hover {{
        background-color: {COLOR_SUCCESS};
        color: #0f172a;
    }}
    QPushButton:pressed {{
        background-color: #166534;
    }}
    QPushButton:disabled {{
        background-color: #1e293b;
        color: #475569;
        border-color: #1e293b;
    }}
"""

# Estilo para o botão de ação destrutiva (Finalizar Sessão).
# Vermelho para alertar que esta ação encerra a sessão e não pode ser desfeita facilmente.
# Usado por: ui/main_window.py -> botão Finalizar
BUTTON_DANGER_STYLE: str = f"""
    QPushButton {{
        background-color: #991b1b;
        color: #ffffff;
        border: 1px solid {COLOR_DANGER};
        border-radius: 6px;
        padding: 8px 18px;
        font-weight: bold;
        min-height: 36px;
        font-size: 13px;
    }}
    QPushButton:hover {{
        background-color: {COLOR_DANGER};
        color: #ffffff;
    }}
    QPushButton:pressed {{
        background-color: #7f1d1d;
    }}
    QPushButton:disabled {{
        background-color: #1e293b;
        color: #475569;
        border-color: #1e293b;
    }}
"""
