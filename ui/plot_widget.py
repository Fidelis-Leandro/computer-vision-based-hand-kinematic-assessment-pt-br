"""
ui/plot_widget.py — Gráfico de TAM em tempo real para todos os 5 dedos
======================================================================

Este módulo implementa o GoniometryPlotWidget: um gráfico de linhas em tempo real que
exibe o histórico de TAM (Total Active Motion / Movimento Ativo Total) de cada dedo simultaneamente,
permitindo ao clínico monitorar a evolução do movimento em tempo real.

O que é TAM (Total Active Motion)?
    O TAM é a métrica clínica mais importante na avaliação funcional da mão.
    Definido pela ASSH (American Society for Surgery of the Hand), ele representa
    a SOMA das amplitudes ativas de movimento em todas as articulações de um dedo:

        TAM = MCP + PIP + DIP  (dedos longos: Indicador, Médio, Anelar, Mínimo)
        TAM = MCP + IP          (Polegar, que não possui DIP)

    Um TAM de 270° (máximo teórico: MCP 90° + PIP 110° + DIP 70°)
    indica função completa. O gráfico permite visualizar se o TAM está:
    - Aumentando (melhora funcional durante a sessão).
    - Estável (manutenção).
    - Diminuindo (fadiga ou piora).

Por que PyQtGraph em vez de Matplotlib?
    O Matplotlib gera gráficos ESTÁTICOS — redesenhar a cada quadro (~30x/s)
    seria catastroficamente lento (150–400ms por redesenho). O PyQtGraph é
    otimizado para dados em tempo real: usa OpenGL quando disponível e atualiza
    apenas os pixels alterados. Atualizações a 30 FPS com PyQtGraph custam ~1–3ms,
    contra 150–400ms com Matplotlib.

Estrutura de dados:
    Um deque(maxlen=BUFFER_SIZE) por dedo armazena os últimos N valores de TAM.
    A cada quadro, o novo TAM é anexado e o mais antigo é descartado
    automaticamente pelo deque. O eixo X do gráfico é implicitamente o
    índice da amostra (0 a N-1) — não representa tempo absoluto.
"""

import math
from collections import deque
from typing import Deque, Dict, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

# Importa pyqtgraph com verificação de disponibilidade.
try:
    import pyqtgraph as pg
    _PG_AVAILABLE = True
except ImportError:
    _PG_AVAILABLE = False

import config


class GoniometryPlotWidget(QWidget):
    """
    Este módulo implementa GoniometryPlotWidget, responsável por desenhar o
    gráfico de TAM (Total Active Motion) em tempo real para os 5 dedos.
    Utiliza pyqtgraph para alto desempenho, mantendo uma janela deslizante thread-safe
    de dados históricos (self._buffers) e gerenciando 5 curvas separadas
    com os nomes dos dedos (config.FINGER_NAMES).

    Por que herdar de QWidget em vez de pg.PlotWidget diretamente?
        Herdar diretamente de pg.PlotWidget limita a flexibilidade de layout:
        não podemos adicionar widgets extras (ex.: título, controles) sem criar
        um contêiner externo. Ao herdar de QWidget e CONTER um
        PlotWidget interno, mantemos controle total do layout e podemos adicionar
        elementos futuros sem refatoração.

    Degradação suave:
        Se o PyQtGraph não estiver instalado, o widget exibe uma mensagem
        informativa em vez de travar a aplicação. Isso permite que o restante
        da interface funcione mesmo sem o gráfico.

    Uso na MainWindow:
        self.plot_widget = GoniometryPlotWidget()
        layout.addWidget(self.plot_widget)
        # Em _on_result():
        self.plot_widget.update_data(result.angles_smooth, result.hand_detected)
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """
        Inicializa o gráfico com 5 curvas, legenda, grade e buffers circulares.

        Configura o PyQtGraph ANTES de instanciar qualquer widget, porque
        pg.setConfigOption() deve ser chamado antes da criação do PlotWidget para
        ter efeito. Configurações aplicadas posteriormente são ignoradas.

        Parâmetros:
            parent: Widget pai do Qt (opcional). Geralmente o contêiner de layout.
        """
        super().__init__(parent)

        # Layout vertical contendo apenas o PlotWidget (ou a mensagem de erro).
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Altura fixa para o gráfico — suficiente para visualizar as 5 curvas com
        # amplitude visível, sem dominar o layout da janela principal.
        self.setFixedHeight(220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        if not _PG_AVAILABLE:
            # PyQtGraph não instalado — exibe aviso sem travar a aplicação.
            from PyQt6.QtWidgets import QLabel
            lbl = QLabel("⚠️ PyQtGraph não instalado.\nExecute: pip install pyqtgraph")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("color: #ef4444; font-size: 13px;")
            layout.addWidget(lbl)
            # Dicionários vazios para que update_data() não falhe.
            self._curves: Dict[str, object] = {}
            self._buffers: Dict[str, Deque[float]] = {}
            self._plot_widget = None
            return

        # --- Configurações globais do PyQtGraph ---
        # Devem ser definidas ANTES de qualquer instância de PlotWidget ser criada.

        # Cor de fundo padrão para todos os PlotWidgets criados após esta chamada.
        # Utiliza o mesmo tom escuro do tema da aplicação (COLOR_BG_MEDIUM).
        pg.setConfigOption("background", "#16213e")

        # Cor padrão para eixos e textos do gráfico.
        pg.setConfigOption("foreground", "#94a3b8")

        # Desativa OpenGL por padrão para compatibilidade máxima no Windows.
        # Se o sistema suportar OpenGL, pode ser ativado em app_pyqt.py
        # com pg.setConfigOption('useOpenGL', True) ANTES de criar este widget.
        pg.setConfigOption("useOpenGL", False)

        # --- Criação do PlotWidget ---
        self._plot_widget = pg.PlotWidget()
        self._plot_widget.setBackground("#16213e")

        # Remove a borda padrão do PlotWidget — o QGroupBox pai já possui uma.
        self._plot_widget.setStyleSheet("border: none;")

        layout.addWidget(self._plot_widget)

        # --- Configuração do PlotItem (o gráfico dentro do PlotWidget) ---
        plot_item: pg.PlotItem = self._plot_widget.getPlotItem()

        # --- Título do gráfico ---
        plot_item.setTitle(
            "TAM em Tempo Real — Movimento Ativo Total por Dedo",
            color="#94a3b8",
            size="11pt",
        )

        # --- Rótulos dos eixos ---
        # Eixo Y: "TAM (°)" — a grandeza exibida e sua unidade.
        plot_item.setLabel("left", "TAM", units="°", color="#94a3b8")

        # Eixo X: sem rótulo porque representa apenas o índice sequencial da amostra,
        # não tempo absoluto. Exibir "Amostras" ou "Quadros" seria tecnicamente
        # correto, mas confuso para o clínico.
        plot_item.hideAxis("bottom")

        # --- Grade sutil ---
        # alpha=0.3: grade visível porém discreta — não compete com as curvas.
        # Valores mais altos (0.5+) tornam a grade proeminente demais e dificultam
        # a leitura das curvas coloridas sobrepostas.
        plot_item.showGrid(x=True, y=True, alpha=0.3)

        # --- Limites do eixo Y ---
        # O TAM varia de 0° (mão totalmente fechada) a ~270° para dedos longos
        # e ~130° para o polegar. Fixo em 280° para que o gráfico não dê "saltos"
        # ao se aproximar do limite superior.
        self._plot_widget.setYRange(0, 280, padding=0.05)

        # --- Legenda ---
        # addLegend() cria a legenda no canto superior direito por padrão.
        # offset=(10, 10): posição relativa ao canto — margem de 10px.
        legend = plot_item.addLegend(offset=(10, 10))
        legend.setLabelTextColor("#e2e8f0")

        # --- Criação de curvas e buffers ---
        # Um PlotDataItem por dedo + um deque por dedo.
        self._curves: Dict[str, pg.PlotDataItem] = {}
        self._buffers: Dict[str, Deque[float]] = {}

        for finger in config.FINGERS:
            # Recupera a cor hexadecimal deste dedo a partir do dicionário de configuração.
            color_hex: str = config.FINGER_COLORS.get(finger, "#ffffff")

            # Nome de exibição para a legenda.
            name_en: str = config.FINGER_NAMES.get(finger, finger)

            # Cria a curva com:
            # - pen: caneta com a cor do dedo e largura de 2px (espessura legível).
            # - name: nome exibido na legenda.
            # Não passamos x/y aqui — serão definidos em update_data() via setData().
            curve = plot_item.plot(
                pen=pg.mkPen(color=color_hex, width=2),
                name=name_en,
            )
            self._curves[finger] = curve

            # Buffer circular por dedo.
            # Por que deque(maxlen=BUFFER_SIZE) em vez de uma lista crescente?
            #   1. Memória FIXA: uma lista crescente nunca descarta dados antigos e
            #      cresceria indefinidamente em uma sessão longa.
            #      A 30 FPS por 60 minutos = 108.000 floats por dedo ≈ 840KB.
            #      Com BUFFER_SIZE=500, limitamos a ~3.9KB por dedo independentemente
            #      da duração da sessão.
            #   2. FIFO automático: ao adicionar um novo valor na capacidade maxlen, o
            #      mais antigo é descartado automaticamente — sem código extra de gerenciamento.
            #   3. Janela deslizante: o gráfico sempre exibe os ÚLTIMOS N pontos,
            #      criando o efeito de "janela avançando com o tempo".
            self._buffers[finger] = deque(maxlen=config.BUFFER_SIZE)

    # =========================================================================
    # ATUALIZAÇÃO DE DADOS DO GRÁFICO
    # =========================================================================

    def update_data(self, angles_smooth: dict, hand_detected: bool) -> None:
        """
        Atualiza o gráfico com os ângulos suavizados do quadro atual.

        Chamado pela MainWindow a cada emissão de result_ready do ProcessingWorker
        (~30 vezes/segundo). Deve ser rápido: apenas append() ao deque e
        setData() na curva — sem cálculos, sem acesso a disco.

        Por que não adicionar um ponto se hand_detected for False?
            Quando a mão não está visível (fora de quadro, encoberta), o
            ProcessingWorker emite um resultado com hand_detected=False e
            angles_smooth={} — um dicionário vazio, sem nenhum ângulo. Não há
            valor a desenhar, e inventar um zero criaria uma queda abrupta no
            gráfico que não representa movimento real: seria um artefato da
            ausência de detecção, não uma medição. Ao não adicionar ponto, o
            histórico fica pausado aguardando a mão voltar ao campo de visão.

        Parâmetros:
            angles_smooth: Dicionário {finger: {joint: angle}} retornado por
                           GoniometryFilterBank.smooth_all(). Ex.:
                           {"INDEX": {"MCP": 45.2, "PIP": 88.1, "DIP": 62.3, "TAM": 195.6}}
            hand_detected: True se o MediaPipe detectou a mão neste quadro.
                           False quando nenhuma mão está visível.
        """
        # Se o PyQtGraph não estiver disponível, não há curvas para atualizar.
        if not _PG_AVAILABLE:
            return

        # Sem detecção, mantém o histórico atual sem adicionar pontos zerados.
        if not hand_detected:
            return

        for finger in config.FINGERS:
            # Extrai o TAM deste dedo a partir do dicionário de ângulos suavizados.
            # O TAM é escolhido como métrica do gráfico porque:
            #   1. Resume a função de todo o dedo em UM ÚNICO NÚMERO (soma de todos os ângulos).
            #   2. É a métrica clínica oficial da ASSH para avaliação funcional.
            #   3. É suficientemente estável para visualização em tempo real (não oscila
            #      como valores individuais de MCP ou PIP durante o movimento).
            # angles_smooth[finger]["TAM"] pode ser None quando a série de
            # smoothing.py ainda não tem histórico válido (política de
            # valores inválidos) — trata como "sem amostra neste quadro",
            # nunca como 0.0.
            tam_raw = angles_smooth.get(finger, {}).get("TAM")
            tam: Optional[float]
            try:
                tam = float(tam_raw) if tam_raw is not None else None
            except (TypeError, ValueError):
                tam = None
            if tam is not None and not math.isfinite(tam):
                tam = None

            # Adiciona ao buffer somente se o valor for positivo.
            # TAM = 0.0 (ou None/NaN/inf) indica ausência de dados, não um
            # ângulo real. Incluir zeros ou dados inválidos distorceria a
            # escala e a visualização do gráfico — o ponto é simplesmente
            # omitido, criando a pausa visual esperada na curva.
            if tam is not None and tam > 0.0:
                self._buffers[finger].append(tam)

            # Converte o deque para list() para passar ao PyQtGraph.
            # list(deque) cria uma cópia linear do deque em O(n).
            # setData() com uma lista de floats do Python é aceito pelo PyQtGraph,
            # que converte internamente para numpy apenas no momento da renderização.
            # Isso é mais eficiente do que manter um array NumPy separado
            # e concatenar a cada quadro.
            data = list(self._buffers[finger])

            if data:
                # setData() apenas com y: o eixo X é automaticamente
                # 0, 1, 2, ..., len(data)-1 — o índice da amostra.
                # Não precisamos de um array X explícito porque o gráfico é
                # uma janela deslizante de índices, não timestamps.
                self._curves[finger].setData(y=data)

    # =========================================================================
    # REINICIALIZAÇÃO DE DADOS
    # =========================================================================

    def clear_data(self) -> None:
        """
        Limpa todos os buffers e redesenha as curvas como vazias.

        Chamado pela MainWindow ao iniciar uma nova sessão, para que os dados da
        sessão anterior não apareçam no gráfico da nova sessão.
        Também útil para "zerar" o gráfico sem reiniciar o widget.

        Após clear_data(), update_data() começa a construir o histórico do
        zero — as curvas crescem gradualmente da esquerda para a direita até
        acumularem BUFFER_SIZE amostras.
        """
        if not _PG_AVAILABLE:
            return

        for finger in config.FINGERS:
            # Limpa o deque sem recriar o objeto — mais eficiente do que
            # substituí-lo por deque(maxlen=BUFFER_SIZE) por não haver realocação.
            self._buffers[finger].clear()

            # Redesenha a curva com um array vazio para limpar visualmente o gráfico.
            # Passar y=[] instrui o PyQtGraph a não desenhar nenhum ponto.
            self._curves[finger].setData(y=[])

    # =========================================================================
    # CONFIGURAÇÃO DE INTERVALO CLÍNICO
    # =========================================================================

    def set_y_range(self, y_min: float, y_max: float) -> None:
        """
        Ajusta o intervalo visível do eixo Y do gráfico.

        Útil quando o clínico deseja focar em um intervalo específico de TAM,
        por exemplo ao avaliar pacientes com amplitude de movimento muito limitada
        (TAM < 100°) onde a escala padrão de 0–280° ficaria muito espaçada.

        Parâmetros:
            y_min: Valor mínimo do eixo Y em graus. Geralmente 0.0.
            y_max: Valor máximo do eixo Y em graus. Padrão da aplicação: 280.0.
        """
        if not _PG_AVAILABLE or self._plot_widget is None:
            return

        # padding=0: sem margem extra acima e abaixo do intervalo definido.
        # Com o padding padrão (~0.05), o PyQtGraph adiciona 5% de espaço além
        # dos limites, o que poderia cortar os rótulos dos eixos.
        self._plot_widget.setYRange(y_min, y_max, padding=0)

    # =========================================================================
    # VISIBILIDADE DE CURVAS
    # =========================================================================

    def set_finger_visible(self, finger: str, visible: bool) -> None:
        """
        Exibe ou oculta a curva de um dedo específico.

        Permite ao clínico focar em um único dedo ocultando os demais,
        ou reativar todos após uma avaliação individual.

        Parâmetros:
            finger: Chave do dedo no formato utilizado pelo pipeline científico.
                    Valores válidos: "INDEX", "MIDDLE", "RING", "PINKY", "THUMB".
            visible: True para exibir a curva, False para ocultá-la.
        """
        if not _PG_AVAILABLE:
            return

        curve = self._curves.get(finger)
        if curve is not None:
            # setVisible() afeta a renderização, mas não remove dados do buffer.
            # Quando a curva volta a ficar visível, os dados históricos são mantidos.
            curve.setVisible(visible)
