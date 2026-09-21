"""
ui/pdf_viewer_dialog.py — Visualizador do relatório PDF da sessão
=================================================================

Este módulo implementa o PdfViewerDialog: uma janela não modal que exibe o
relatório PDF gerado ao final da avaliação, sem depender de nenhum leitor
externo instalado na máquina.

Por que um visualizador embutido?
    Conferir o relatório num leitor externo exigiria abrir a pasta de
    sessões e tiraria o operador da tela de resultado justamente no momento
    em que ele decide manter ou descartar a sessão. O visualizador permite
    essa conferência sem sair da aplicação.

Por que não modal?
    A Tela de Resultado continua utilizável com o relatório aberto ao lado:
    o clínico pode conferir o PDF e, na mesma janela principal, exportar o
    CSV ou descartar a sessão. Um diálogo modal bloquearia a interface
    inteira enquanto o relatório estivesse na tela.

Por que QPdfView e não QWebEngineView ou um leitor externo?
    QPdfView e QPdfDocument fazem parte do PyQt6 (módulos PyQt6.QtPdf e
    PyQt6.QtPdfWidgets) — sem dependência adicional, sem processo externo
    e sem navegador embutido de dezenas de megabytes.

Liberação do arquivo (crítico):
    No Windows, um PDF mantido aberto pelo próprio aplicativo pode bloquear
    os.remove() e transformar o "Não Salvar Esta Sessão" num PermissionError.
    Por isso closeEvent() chama QPdfDocument.close() explicitamente: fechar a
    janela precisa significar soltar o handle do arquivo, não apenas esconder
    o widget.

Uso no MainWindow:
    self._pdf_viewer_dialog = PdfViewerDialog(pdf_path, parent=self)
    self._pdf_viewer_dialog.show()
"""

import logging
import os
from typing import Optional

from PyQt6.QtGui import QCloseEvent
from PyQt6.QtPdf import QPdfDocument
from PyQt6.QtPdfWidgets import QPdfView
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from themes import BUTTON_PRIMARY_STYLE, COLOR_BG_DARK

# Logger específico do módulo — facilita o rastreamento de falhas de leitura.
logger = logging.getLogger(__name__)

# Tamanho inicial da janela. Suficiente para uma página A4 inteira legível
# sem ocupar a tela toda, já que o diálogo é não modal e convive com a
# janela principal.
_LARGURA_INICIAL = 800
_ALTURA_INICIAL = 600


class PdfViewerDialog(QDialog):
    """Janela não modal que exibe um arquivo PDF já existente em disco.

    A classe não gera nem valida o conteúdo do relatório: recebe um caminho
    pronto e apenas o apresenta. Se o arquivo não puder ser lido, avisa o
    operador e não monta a área de visualização — uma janela vazia seria
    pior que nenhuma janela.

    Atributos públicos:
        load_failed: True quando o PDF não pôde ser carregado. O chamador
            usa isso para não guardar referência a um visualizador inútil.
    """

    def __init__(self, pdf_path: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._pdf_path = pdf_path
        self.load_failed = False
        self._doc: Optional[QPdfDocument] = None
        self._view: Optional[QPdfView] = None

        self.setWindowTitle(f"Relatório — {os.path.basename(pdf_path)}")
        self.resize(_LARGURA_INICIAL, _ALTURA_INICIAL)
        self.setStyleSheet(f"background-color: {COLOR_BG_DARK};")

        # O documento é criado antes do layout: se a leitura falhar, não há
        # motivo para construir a QPdfView.
        self._doc = QPdfDocument(self)
        erro = self._doc.load(pdf_path)
        if erro != QPdfDocument.Error.None_:
            self.load_failed = True
            logger.warning(
                "Falha ao carregar o PDF para visualização (%s): %s", pdf_path, erro
            )
            QMessageBox.warning(
                parent,
                "Não foi possível abrir o relatório",
                "O arquivo do relatório não pôde ser lido. Ele pode estar "
                "corrompido, ter sido movido ou estar em uso por outro "
                f"programa.\n\nArquivo:\n{pdf_path}",
            )
            self._doc.close()
            self.close()
            return

        self._build_ui()

    def _build_ui(self) -> None:
        """Monta a área de visualização e a barra inferior com o botão Fechar."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self._view = QPdfView(self)
        self._view.setDocument(self._doc)
        # MultiPage permite rolar o relatório inteiro continuamente, em vez
        # de exigir navegação página a página.
        self._view.setPageMode(QPdfView.PageMode.MultiPage)
        layout.addWidget(self._view, stretch=1)

        barra = QHBoxLayout()
        barra.addStretch(1)
        btn_fechar = QPushButton("Fechar")
        btn_fechar.setStyleSheet(BUTTON_PRIMARY_STYLE)
        btn_fechar.setMinimumWidth(120)
        btn_fechar.clicked.connect(self.close)
        barra.addWidget(btn_fechar)
        layout.addLayout(barra)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Libera o handle do arquivo ao fechar a janela.

        Sem este fechamento explícito, o QPdfDocument continuaria segurando o
        PDF aberto enquanto o objeto não fosse coletado — e a remoção dos
        arquivos da sessão poderia falhar com PermissionError no Windows.
        """
        if self._doc is not None:
            self._doc.close()
        super().closeEvent(event)


__all__ = ["PdfViewerDialog"]
