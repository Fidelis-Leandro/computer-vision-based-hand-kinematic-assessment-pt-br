"""
app_pyqt.py — Ponto de entrada da interface desktop (PyQt6)
============================================================

Este é o ponto de entrada principal da aplicação Goniometria Digital da Mão,
substituindo a interface anterior baseada em web construída com Streamlit.

Responsabilidades:
    1. Configurar o sistema de logging global (handlers de arquivo e console).
    2. Otimizar a renderização gráfica no Windows (desativando OpenGL se necessário).
    3. Inicializar a aplicação Qt e aplicar o tema visual escuro.
    4. Instanciar e exibir o MainWindow.
    5. Capturar exceções fatais não tratadas para evitar travamentos silenciosos.

Comandos de execução:
    - Interface PyQt6 (principal)  : python app_pyqt.py
"""

import logging
import os
import sys
import traceback

from PyQt6.QtWidgets import QApplication

import config
import themes
from ui.main_window import MainWindow

# Tenta carregar o pyqtgraph. Em algumas máquinas Windows, o pyqtgraph tenta
# usar OpenGL e trava quando há drivers de vídeo básicos instalados.
try:
    import pyqtgraph as pg
    # Desativa o OpenGL nativo como precaução. O renderizador de software (raster)
    # do PyQtGraph é extremamente rápido e mais do que suficiente para gráficos
    # de linha 2D, sendo 100% estável em qualquer configuração de PC.
    pg.setConfigOption("useOpenGL", False)
except ImportError:
    # Tratado dentro dos widgets que usam pyqtgraph.
    pass


def setup_logging() -> None:
    """
    Configura o sistema de logging global para saída em console e arquivo.

    Por que configurar globalmente no ponto de entrada?
        Qualquer módulo (MainWindow, CameraWorker, etc.) pode chamar
        logging.getLogger(__name__) e automaticamente herdar esta
        formatação, sem configurar um logger individualmente por arquivo.

    Formato:
        "2026-06-23 14:35:12,123 | INFO | ui.main_window | Sessão iniciada"
    """
    # Garante que o diretório de log exista
    os.makedirs(config.LOG_DIR, exist_ok=True)
    log_file = os.path.join(config.LOG_DIR, "app.log")

    # Formato padronizado: data/hora | nível | módulo | mensagem
    log_format = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"

    # Configura o logger raiz
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),  # Handler de arquivo
            logging.StreamHandler(sys.stdout),                 # Handler de console
        ]
    )


def exception_hook(exc_type, exc_value, exc_traceback) -> None:
    """
    Handler global para exceções não capturadas.

    Por que usar sys.excepthook?
        Em aplicações PyQt, exceções levantadas dentro de slots ou sinais
        às vezes são silenciosamente engolidas pelo Qt, causando o travamento
        do programa sem nenhum erro visível. O excepthook garante que
        NENHUMA exceção fatal passe despercebida: todas serão registradas em app.log
        com o traceback completo antes do encerramento da aplicação.
    """
    # Se a exceção for uma interrupção por teclado (Ctrl+C no terminal),
    # não tratar como erro fatal — apenas deixar a aplicação fechar.
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    # Registra o erro fatal com a pilha de chamadas completa (traceback)
    logger = logging.getLogger("sys.excepthook")
    logger.critical(
        "Exceção Fatal não tratada:\n",
        exc_info=(exc_type, exc_value, exc_traceback),
    )


def main() -> None:
    """
    Ponto de entrada principal da aplicação.
    Configura o ambiente, cria a interface e inicia o loop de eventos Qt.
    """
    # 1. Configura o logging e a captura global de exceções
    setup_logging()
    sys.excepthook = exception_hook

    logger = logging.getLogger("app_pyqt")
    logger.info("Inicializando Goniometria Digital da Mão (interface PyQt6)...")

    # Envolve toda a execução da aplicação em try/except para garantir
    # que erros de inicialização sejam sempre registrados.
    try:
        # 2. Cria a instância principal da aplicação Qt
        # sys.argv permite que a aplicação aceite parâmetros de linha de comando
        # (ex.: parâmetros nativos de estilo Qt)
        app = QApplication(sys.argv)

        # 3. Define o nome da aplicação (usado internamente pelo SO e pelo Qt)
        app.setApplicationName(config.APP_TITLE)

        # 4. Aplica o tema escuro padronizado a todos os componentes nativos
        themes.apply_dark_theme(app)

        # 5. Instancia a janela principal, que orquestra todo o restante
        window = MainWindow()

        # 6. Exibe a janela (show() respeita os limites da tela por padrão)
        window.show()

        logger.info("Interface iniciada com sucesso. Loop de eventos Qt ativo.")

        # 7. Inicia o loop de eventos (bloqueante até o fechamento da janela)
        # sys.exit passa o código de retorno de app.exec() ao sistema operacional
        sys.exit(app.exec())

    except Exception as e:
        logger.critical("Erro fatal ao iniciar a aplicação: %s", e, exc_info=True)
        # Encerra com código de erro 1
        sys.exit(1)


# Executa somente quando este arquivo é executado diretamente (python app_pyqt.py)
if __name__ == "__main__":
    main()
