"""
config.py — Configuração centralizada do sistema de Goniometria Digital da Mão
===============================================================================

Este arquivo é a única fonte de verdade para todos os parâmetros numéricos e
constantes de configuração. Nenhum número mágico deve aparecer disperso pelo
restante do código.

Filosofia de design:
    Em sistemas de tempo real como este, alterar um parâmetro em um único lugar
    e propagá-lo para todos os módulos é fundamental para manutenção e
    calibração. Sem este arquivo, os valores precisariam ser rastreados e
    substituídos em múltiplos arquivos, o que inevitavelmente causa
    inconsistências.

Categorias de configuração:
    1. Câmera e captura de vídeo
    2. Pipeline de suavização (EMA → Kalman)
    3. Detecção de mão (MediaPipe)
    4. Interface gráfica (PyQt6 / PyQtGraph)
    5. Gravação de sessão (CSV)
    6. Mapeamento clínico de dedos
    7. Sistema de log
    8. Janela principal
"""

# =============================================================================
# 1. CÂMERA E CAPTURA DE VÍDEO
# =============================================================================

# Índice da câmera no sistema operacional.
# 0 = câmera padrão (geralmente a webcam integrada).
# Se houver múltiplas câmeras disponíveis, alterar para 1, 2, etc.
CAMERA_INDEX: int = 0

# Resolução alvo da câmera.
# 1280x720 (HD) oferece boa qualidade para rastreamento de landmarks,
# mas consome mais CPU do que 640x480. Ajustar se a máquina for lenta.
CAMERA_WIDTH: int = 1280
CAMERA_HEIGHT: int = 720

# Frames por segundo solicitados ao driver da câmera.
# O driver pode não honrar este valor exatamente — o FPS real
# é medido e exibido em tempo real pelo CameraWorker.
TARGET_FPS: int = 30

# =============================================================================
# 2. PIPELINE DE SUAVIZAÇÃO (EMA → KALMAN)
# =============================================================================

# Fator de suavização EMA (Exponential Moving Average).
# Valor entre 0 e 1: valores maiores fazem o filtro reagir mais rápido ao
# movimento, mas reduzem a suavização. Valores menores produzem saída mais
# suave com maior atraso.
# 0.30 foi calibrado experimentalmente para goniometria clínica em tempo real:
# suaviza o tremor da câmera sem introduzir atraso perceptível em movimentos lentos.
EMA_ALPHA: float = 0.30

# Parâmetros do Filtro de Kalman escalar.
#
# KALMAN_Q (ruído do processo): representa incerteza no modelo de movimento.
# Um valor pequeno (0.01) assume que o ângulo articular muda de forma lenta e suave.
# Aumentar Q faz o filtro reagir mais rápido a mudanças súbitas.
KALMAN_Q: float = 0.01

# KALMAN_R (ruído de medição): representa incerteza nas leituras de landmarks.
# 0.10 indica confiança moderada na posição detectada pelo MediaPipe.
# Aumentar R faz o filtro confiar menos na medição e se apoiar mais
# na estimativa anterior.
KALMAN_R: float = 0.10

# Modo de filtro inicial do sistema (ver smoothing.py para os quatro modos:
# RAW, EMA, KALMAN e EMA_KALMAN). "EMA_KALMAN" mantém o comportamento clínico
# validado — EMA seguido de Kalman.
#
# Esta constante é a fonte única do padrão e tem dois consumidores:
#   - workers/processing_worker.py usa este valor ao criar o banco de filtros
#     no construtor, antes de qualquer sessão existir;
#   - ui/main_window.py usa este valor para pré-selecionar o seletor "Modo de
#     Filtro" na tela de configuração, e para restaurá-lo em Nova Avaliação.
#
# O operador pode escolher outro modo antes de iniciar a sessão. A escolha é
# aplicada ao worker antes de o CSV ser aberto, então vale para a sessão
# inteira e fica registrada na coluna filter_mode de cada linha. Alterar o
# valor aqui muda apenas qual modo vem pré-selecionado — não impede nem força
# nenhuma escolha na interface.
FILTER_MODE_DEFAULT: str = "EMA_KALMAN"

# =============================================================================
# 3. DETECÇÃO DE MÃO (MEDIAPIPE HANDS)
# =============================================================================

# Confiança mínima para DETECTAR uma mão do zero.
# Um valor mais alto (0.70) reduz falsos positivos, mas pode perder detecções
# com iluminação ruim. Ajustar entre 0.5 e 0.9.
MP_DETECT_CONF: float = 0.70

# Confiança mínima para RASTREAR uma mão já detectada entre quadros.
# Pode ser menor que MP_DETECT_CONF porque rastrear é mais fácil que detectar.
# 0.50 mantém o rastreamento estável mesmo com oclusões parciais dos dedos.
MP_TRACK_CONF: float = 0.50

# Número de quadros consecutivos sem detecção de mão antes de resetar os filtros.
# A 30 FPS, 15 quadros ≈ 500ms. Isso impede que o filtro de Kalman
# "lembre" uma posição anterior quando a mão retorna após longa oclusão.
NO_HAND_RESET_FRAMES: int = 15

# =============================================================================
# 4. INTERFACE GRÁFICA (PyQt6 / PyQtGraph)
# =============================================================================

# Tamanho do buffer circular para gráficos em tempo real (PyQtGraph).
# 500 pontos a ~30 FPS = aproximadamente 16 segundos de histórico visível.
# Usar deque(maxlen=BUFFER_SIZE) garante que a memória não cresça indefinidamente.
BUFFER_SIZE: int = 500

# Tamanho máximo da fila entre CameraWorker e ProcessingWorker.
# DEVE ser sempre 1 em sistemas de tempo real. Com maxsize=1:
# - Se a fila estiver cheia, o quadro antigo é descartado.
# - O processador SEMPRE recebe o quadro mais recente.
# - A latência permanece mínima, mesmo se o processamento estiver temporariamente lento.
QUEUE_SIZE: int = 1

# Intervalo em milissegundos para o QTimer que atualiza os gráficos do PyQtGraph.
# 33ms ≈ 30 FPS de atualização visual — suave para o olho humano.
# Aumentar este valor reduz o uso de CPU; diminuir torna a interface mais fluida.
PANEL_REFRESH_MS: int = 33

# Número de quadros entre recálculos do overlay goniométrico.
# Desenhar o esqueleto e os ângulos é custoso. Com OVERLAY_FRAME_INTERVAL = 3,
# o overlay atualiza a cada 3 quadros, economizando ~67% do custo de desenho
# sem impacto visual perceptível (o olho humano não distingue
# diferenças tão rápidas).
OVERLAY_FRAME_INTERVAL: int = 3

# =============================================================================
# 5. GRAVAÇÃO DE SESSÃO (CSV)
# =============================================================================

# Número de quadros entre gravações de ângulos no CSV.
# CSV_LOG_INTERVAL = 3 com TARGET_FPS = 30 gera ~10 linhas/segundo,
# suficiente para análise clínica sem gerar arquivos excessivamente grandes.
CSV_LOG_INTERVAL: int = 3

# =============================================================================
# 6. MAPEAMENTO CLÍNICO DE DEDOS
# =============================================================================

# Ordem de processamento dos dedos — deve permanecer consistente em todos os módulos
# para evitar bugs de indexação.
# THUMB é listado por último devido à sua anatomia diferente
# (apenas articulações MCP e IP, sem DIP ou ABD).
FINGERS: list[str] = ["INDEX", "MIDDLE", "RING", "PINKY", "THUMB"]

# Mapeamento dos nomes técnicos em inglês para rótulos de exibição clínica.
# Usado na interface gráfica para exibir rótulos legíveis aos profissionais de saúde.
FINGER_NAMES: dict[str, str] = {
    "INDEX":  "Indicador",
    "MIDDLE": "Médio",
    "RING":   "Anular",
    "PINKY":  "Mínimo",
    "THUMB":  "Polegar",
}

# Cores hexadecimais para cada dedo nos gráficos do PyQtGraph.
# As cores foram escolhidas para alto contraste com o fundo escuro
# e distinção adequada para usuários com daltonismo parcial
# (evita combinações puro vermelho/verde).
FINGER_COLORS: dict[str, str] = {
    "INDEX":  "#38bdf8",   # Azul-céu      — Indicador
    "MIDDLE": "#4ade80",   # Verde-claro   — Médio
    "RING":   "#facc15",   # Amarelo-ouro  — Anular
    "PINKY":  "#f87171",   # Vermelho-salmão — Mínimo
    "THUMB":  "#c084fc",   # Roxo-claro    — Polegar
}

# Cores para cada dedo no formato (R, G, B) com valores 0–255.
# Usado pelo PyQtGraph para definir cores das curvas dos gráficos,
# pois o PyQtGraph aceita tanto strings hex quanto tuplas RGB.
FINGER_COLORS_RGB: dict[str, tuple[int, int, int]] = {
    "INDEX":  (56, 189, 248),
    "MIDDLE": (74, 222, 128),
    "RING":   (250, 204, 21),
    "PINKY":  (248, 113, 113),
    "THUMB":  (192, 132, 252),
}

# Limite máximo de TAM biomecânico por dedo (graus).
# Valores derivados das faixas de referência ASSH e literatura anatômica.
# Aplicado como limitação rígida após filtragem EMA + Kalman para evitar
# que artefatos de ruído da câmera produzam leituras fisicamente impossíveis.
TAM_CEILING: dict[str, float] = {
    "INDEX":  270.0,
    "MIDDLE": 270.0,
    "RING":   270.0,
    "PINKY":  270.0,
    "THUMB":  130.0,
}

# =============================================================================
# 7. SISTEMA DE LOG
# =============================================================================

# Diretório onde o arquivo de log da aplicação será salvo.
# Criado automaticamente caso não exista (ver app_pyqt.py).
LOG_DIR: str = "logs"

# Nome do arquivo de log da aplicação.
# Separado do CSV de sessão — este arquivo contém eventos do sistema,
# erros e informações de inicialização, não dados clínicos.
LOG_FILENAME: str = "app.log"

# Formato das mensagens de log.
# Inclui: data/hora, nível (INFO/WARNING/ERROR), nome do módulo e mensagem.
# Facilita rastrear qual módulo gerou cada evento durante depuração.
LOG_FORMAT: str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

# =============================================================================
# 8. JANELA PRINCIPAL
# =============================================================================

# Título exibido na barra de título da janela no sistema operacional.
APP_TITLE: str = "Avaliação Cinemática da Mão Baseada em Visão Computacional"

# Tamanho mínimo da janela principal em pixels (largura x altura).
# Garante que todos os widgets permaneçam visíveis mesmo em monitores menores.
WINDOW_MIN_WIDTH: int = 1280
WINDOW_MIN_HEIGHT: int = 800
