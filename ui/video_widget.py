"""
ui/video_widget.py — Widget de exibição de vídeo em tempo real
==============================================================

Este módulo implementa o VideoWidget: um QLabel especializado que recebe
quadros NumPy BGR do ProcessingWorker e os exibe na tela com
latência mínima.

Responsabilidade única (princípio SRP):
    Este widget FAZ UMA ÚNICA COISA: transforma um array NumPy (formato câmera/OpenCV)
    em uma imagem Qt visível. Ele não processa pixels, não analisa a imagem,
    não calcula ângulos — apenas exibe.

    Toda a análise já ocorreu no ProcessingWorker. O VideoWidget
    recebe o resultado pronto (quadro com overlay desenhado) e o exibe.

Por que QLabel em vez de um QWidget personalizado?
    QLabel já possui suporte nativo para exibir QPixmap (imagens) de forma
    otimizada. Herdar de QLabel nos dá setPixmap(), setAlignment(),
    e escalonamento automático gratuitamente, sem precisar implementar paintEvent()
    do zero para desenhar a imagem base.
    Sobrescrevemos paintEvent() SOMENTE para adicionar o overlay de FPS sobre a imagem
    já renderizada pelo QLabel pai.

Fluxo de dados:
    ProcessingWorker
        → pyqtSignal result_ready(ProcessingResult)
        → MainWindow._on_result()
        → video_widget.update_frame(result.frame_overlay)   ← entrada deste widget
        → cv2.cvtColor(BGR→RGB)
        → QImage → QPixmap → self.setPixmap()               ← saída: pixels na tela
"""

from typing import Optional

import cv2
import numpy as np
from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QLabel, QSizePolicy

import config


class VideoWidget(QLabel):
    """
    Widget de exibição de vídeo em tempo real para a interface de goniometria.

    Herda de QLabel para aproveitar o suporte nativo a QPixmap, adicionando:
    - Conversão automática de formato BGR (OpenCV) para RGB (Qt).
    - Overlay de FPS desenhado via QPainter, sem afetar a imagem principal.
    - Estado "sem sinal" com mensagem visual quando a câmera falha.
    - Escalonamento proporcional da imagem ao redimensionar a janela.

    Uso típico em MainWindow:
        self.video_widget = VideoWidget()
        layout.addWidget(self.video_widget)
        processing_worker.result_ready.connect(
            lambda result: self.video_widget.update_frame(result.frame_overlay)
        )
        camera_worker.camera_error.connect(self.video_widget.set_no_signal)
    """

    def __init__(self, parent=None) -> None:
        """
        Inicializa o VideoWidget com as configurações visuais padrão.

        Configura o tamanho mínimo, alinhamento, política de redimensionamento e estado inicial
        ("sem sinal"). Não abre a câmera nem processa nenhum dado.

        Parâmetros:
            parent: Widget pai do Qt (opcional). Geralmente o contêiner do layout.
        """
        super().__init__(parent)

        # Tamanho mínimo garantido para o widget — abaixo disso o layout
        # não permitirá que a janela encolha mais.
        # 480×360 é o menor tamanho que ainda permite que o overlay goniométrico
        # com rótulos de ângulos permaneça legível.
        self.setMinimumSize(480, 360)

        # Centraliza o conteúdo (pixmap) dentro do espaço do QLabel.
        # Sem isso, a imagem ficaria presa no canto superior esquerdo
        # quando o widget for maior que o quadro.
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Permite que o widget cresça e encolha livremente no layout,
        # respeitando o tamanho mínimo definido acima.
        # A expansão em ambas as direções permite que o widget ocupe o espaço disponível
        # na coluna esquerda do layout principal.
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        # Fundo preto escuro enquanto nenhum quadro está disponível.
        # Corresponde ao tema escuro da aplicação e evita flickering quando
        # o primeiro quadro real for exibido.
        self.setStyleSheet("QLabel { background-color: #0d1117; }")

        # Armazena o valor atual de FPS para ser desenhado em paintEvent.
        # Inicializado como None para indicar que ainda não há leitura de FPS disponível.
        self._fps: Optional[float] = None

        # Flag indicando se o widget está no estado "sem sinal".
        # Controla qual texto é exibido quando nenhum quadro está disponível.
        self._no_signal: bool = True

        # Exibe o estado inicial "sem sinal" imediatamente.
        self.set_no_signal()

    # =========================================================================
    # ATUALIZAÇÃO DO QUADRO DE VÍDEO
    # =========================================================================

    def update_frame(self, frame_bgr: np.ndarray) -> None:
        """
        Recebe um quadro BGR do ProcessingWorker e o exibe na tela.

        Este é o método de desempenho crítico do widget. É chamado em
        cada quadro processado (~30 vezes/segundo) e deve ser rápido.

        Sequência de conversão obrigatória:
            BGR (OpenCV/câmera) → RGB (Qt) → QImage → QPixmap → tela

        Por que BGR → RGB é obrigatório?
            OpenCV usa a ordem Azul-Verde-Vermelho por convenção histórica do
            padrão Windows DirectShow. Qt usa Vermelho-Verde-Azul (padrão moderno).
            Sem essa conversão, todas as cores ficam invertidas: a pele humana aparece
            azulada, texto vermelho aparece azul, etc.

        Por que bytes_per_line é crítico?
            QImage precisa saber quantos bytes existem por linha de pixel.
            Para uma imagem de largura W com 3 canais (RGB), cada linha tem exatamente
            W*3 bytes. Se omitirmos esse parâmetro, o Qt pode assumir um valor diferente
            (baseado em alinhamento de memória), fazendo a imagem aparecer
            distorcida diagonalmente — um bug sutil e difícil de diagnosticar.

        Por que usar ascontiguousarray() antes de criar QImage?
            Arrays NumPy nem sempre são contíguos em memória (por exemplo, após
            operações de slice ou reshape). QImage espera dados contíguos.
            Aplicamos isso explicitamente.

        Parâmetros:
            frame_bgr: Array NumPy de shape (height, width, 3), dtype uint8,
                       no formato BGR. Geralmente frame_overlay de ProcessingResult.
        """
        # Sai do estado "sem sinal" quando um quadro válido é recebido.
        self._no_signal = False

        # Converte BGR → RGB porque Qt espera os canais na ordem R-G-B.
        # cv2.cvtColor é otimizado internamente com SIMD — muito mais rápido que
        # inverter os canais manualmente com numpy slicing.
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

        # Garante que o array seja contíguo em memória antes de criar o QImage.
        # Arrays não contíguos causam leituras incorretas de pixels pelo Qt.
        frame_rgb = np.ascontiguousarray(frame_rgb)

        # Extrai as dimensões para calcular bytes_per_line.
        height, width, channels = frame_rgb.shape

        # bytes_per_line: número de bytes em uma única linha horizontal da imagem.
        # Para RGB sem padding, é sempre largura × 3 canais.
        # Este valor DEVE ser passado explicitamente ao QImage — não confie no
        # valor padrão, que pode diferir em sistemas com alinhamento de memória.
        bytes_per_line: int = channels * width

        # Cria QImage referenciando diretamente a memória do array NumPy.
        # Format_RGB888 = 3 bytes por pixel, ordem R-G-B, sem canal alfa.
        # ATENÇÃO: frame_rgb deve permanecer em memória enquanto QImage existir.
        # Como convertemos para QPixmap imediatamente abaixo, isso é seguro.
        q_image = QImage(
            frame_rgb.data,
            width,
            height,
            bytes_per_line,
            QImage.Format.Format_RGB888,
        )

        # Converte QImage → QPixmap (formato otimizado para exibição em tela).
        # QPixmap é mantido na memória de vídeo (GPU quando disponível),
        # enquanto QImage vive na memória principal (CPU). A conversão é feita
        # uma vez aqui e o QPixmap resultante é exibido sem custo adicional.
        pixmap = QPixmap.fromImage(q_image)

        # Escala o pixmap para caber no tamanho atual do widget, preservando a proporção.
        # KeepAspectRatio: nunca distorce a imagem; adiciona barras pretas se necessário.
        # SmoothTransformation: usa interpolação bilinear — mais lento que Fast,
        # mas produz imagens sem aliasing, especialmente ao reduzir.
        scaled_pixmap = pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        # Atualiza o conteúdo do QLabel com o novo quadro.
        # setPixmap() agenda automaticamente um repaint — não é necessário chamar
        # update() ou repaint() manualmente.
        self.setPixmap(scaled_pixmap)

    # =========================================================================
    # SOBREPOSIÇÃO DE FPS
    # =========================================================================


    def set_fps(self, fps: float) -> None:
        """
        Armazena o valor de FPS para ser desenhado no próximo paintEvent.

        Por que armazenar em vez de desenhar imediatamente?
            Desenhar diretamente no pixmap (modificando o QPixmap) seria
            irreversível — o texto ficaria "gravado" na imagem e acumularia
            a cada atualização. Armazenar o valor e redesenhar via QPainter em
            paintEvent() garante que o texto sempre apareça limpo, sobre a
            imagem atual, sem modificar o pixmap original.

            Também evita o desenho duplo: chamar update() aqui repintaria o widget
            DUAS VEZES por quadro (uma de setPixmap em update_frame, outra aqui).
            Armazenar o valor e usar paintEvent consolida ambas as operações
            em um único ciclo de renderização.

        Parâmetros:
            fps: Valor atual de FPS do pipeline de processamento (float).
                 Recebido do CameraWorker via sinal fps_updated.
        """
        self._fps = fps
        # Solicita repaint somente se um pixmap estiver exibido.
        # Evita redesenhos desnecessários no estado "sem sinal".
        if self.pixmap() and not self.pixmap().isNull():
            self.update()

    def paintEvent(self, event) -> None:
        """
        Evento de pintura do Qt — chamado sempre que o widget precisa ser redesenhado.

        Sobrescrevemos paintEvent() para adicionar o overlay de FPS sobre o
        conteúdo padrão do QLabel (o pixmap). A sequência é:
            1. Chamar super().paintEvent() para desenhar o pixmap normalmente.
            2. Desenhar o texto de FPS por cima usando QPainter.

        Por que sombra preta + texto branco?
            Texto branco puro (#FFFFFF) pode desaparecer sobre áreas claras da imagem
            (fundo claro da câmera, iluminação intensa). A sombra preta deslocada
            em 1px cria um contorno escuro que torna o texto legível em QUALQUER
            fundo — técnica padrão em HUDs de jogos e aplicações de vídeo.

        Parâmetros:
            event: QPaintEvent fornecido automaticamente pelo Qt.
                   Contém a região que precisa ser redesenhada (rect()).
        """
        # Primeiro, deixa o QLabel desenhar normalmente (pixmap, alinhamento, fundo).
        # Sem essa chamada, o quadro de vídeo desaparece.
        super().paintEvent(event)

        # Sobrepõe o FPS somente se houver um valor válido para exibir.
        if self._fps is None:
            return

        # Inicia o QPainter neste widget (não no pixmap —
        # pintar no pixmap seria permanente; pintar no widget
        # é temporário e redesenhado em cada paintEvent).
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        # Formata o texto com uma casa decimal — "FPS: 28.7"
        fps_text: str = f"FPS: {self._fps:.1f}"

        # Fonte em negrito, tamanho 13 — legível sem ocupar muito espaço.
        font = QFont("Segoe UI", 13, QFont.Weight.Bold)
        painter.setFont(font)

        # Área do texto: canto superior direito com margem de 10px.
        # QRect(x, y, width, height) — largura 120 é suficiente para "FPS: XX.X"
        text_rect = QRect(self.width() - 130, 10, 120, 28)

        # --- Sombra preta deslocada em 1 pixel ---
        # Deslocar o texto em (+1, +1) cria a ilusão de sombra projetada.
        shadow_rect = QRect(text_rect.x() + 1, text_rect.y() + 1,
                            text_rect.width(), text_rect.height())
        painter.setPen(QPen(QColor("#000000")))
        painter.drawText(shadow_rect, Qt.AlignmentFlag.AlignRight, fps_text)

        # --- Texto branco principal ---
        painter.setPen(QPen(QColor("#FFFFFF")))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignRight, fps_text)

        # Finaliza o QPainter — OBRIGATÓRIO para liberar o contexto de pintura.
        # Sem end(), o Qt pode deixar o dispositivo de pintura bloqueado, causando
        # artefatos visuais ou falhas em versões mais antigas do Qt.
        painter.end()

    # =========================================================================
    # ESTADO SEM SINAL
    # =========================================================================


    def set_no_signal(self, message: str = "") -> None:
        """
        Coloca o widget no estado visual "sem sinal de câmera".

        Chamado quando:
        - O widget é inicializado (antes de a câmera ser aberta).
        - CameraWorker emite camera_error (câmera desconectada, falha de driver).
        - A sessão termina e a câmera é liberada.

        Cria um QPixmap preto com texto centralizado explicando a situação,
        evitando que o widget apareça vazio ou exiba conteúdo desatualizado.

        Parâmetros:
            message: Mensagem de erro opcional do CameraWorker para exibir abaixo
                     do texto padrão "Sem sinal de câmera".
                     Se vazia, apenas a mensagem padrão é exibida.
        """
        self._no_signal = True
        self._fps = None

        # Cria um pixmap preto com o tamanho atual do widget.
        # Se o widget ainda não tiver um tamanho definido (por exemplo, antes de show()),
        # usa o tamanho mínimo configurado em __init__.
        w = max(self.width(), 480)
        h = max(self.height(), 360)

        # Cria um pixmap vazio (não inicializado) e preenche com preto.
        no_signal_pixmap = QPixmap(w, h)
        no_signal_pixmap.fill(QColor("#0d1117"))

        # Inicia um QPainter no pixmap para desenhar o texto.
        painter = QPainter(no_signal_pixmap)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        # Linha principal: "📷 Sem sinal de câmera"
        # Fonte grande para ser visível mesmo com a janela minimizada.
        font_main = QFont("Segoe UI", 18, QFont.Weight.Bold)
        painter.setFont(font_main)
        painter.setPen(QPen(QColor("#64748b")))

        # Área central do pixmap para o texto principal.
        main_rect = QRect(0, h // 2 - 40, w, 40)
        painter.drawText(
            main_rect,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            "📷 Sem sinal de câmera",
        )

        # Instrução secundária para o usuário.
        font_sub = QFont("Segoe UI", 12)
        painter.setFont(font_sub)
        painter.setPen(QPen(QColor("#334155")))

        sub_rect = QRect(0, h // 2 + 10, w, 30)
        painter.drawText(
            sub_rect,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            "Clique no botão de iniciar sessão para ativar a câmera",
        )

        # Se houver uma mensagem de erro específica do CameraWorker, exibe em vermelho.
        if message:
            font_err = QFont("Consolas", 10)
            painter.setFont(font_err)
            painter.setPen(QPen(QColor("#ef4444")))

            err_rect = QRect(20, h // 2 + 50, w - 40, 50)
            painter.drawText(
                err_rect,
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
                | Qt.TextFlag.TextWordWrap,
                f"Erro: {message}",
            )

        # Finaliza o painter antes de usar o pixmap.
        painter.end()

        # Exibe o pixmap "sem sinal" no QLabel.
        self.setPixmap(no_signal_pixmap)

    # =========================================================================
    # REDIMENSIONAMENTO RESPONSIVO
    # =========================================================================

    def resizeEvent(self, event) -> None:
        """
        Chamado pelo Qt sempre que o widget é redimensionado pelo usuário.

        Reescalonamos o último pixmap exibido para preencher o novo tamanho do widget,
        mantendo a proporção. Sem isso, a imagem permaneceria
        no tamanho fixo do primeiro quadro recebido — ao redimensionar a janela,
        barras pretas desnecessárias apareceriam ou a imagem seria cortada.

        Parâmetros:
            event: QResizeEvent fornecido pelo Qt com o novo tamanho (newSize)
                   e o tamanho anterior (oldSize).
        """
        super().resizeEvent(event)

        # Se estiver no estado "sem sinal", recria o pixmap de erro com o novo tamanho
        # para preencher corretamente o widget.
        if self._no_signal:
            self.set_no_signal()
            return

        # Se um pixmap válido estiver exibido, reescala para o novo tamanho.
        current_pixmap = self.pixmap()
        if current_pixmap and not current_pixmap.isNull():
            scaled = current_pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.setPixmap(scaled)
