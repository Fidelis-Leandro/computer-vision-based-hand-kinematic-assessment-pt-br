"""
app_pyqt.py — Desktop interface entry point (PyQt6)
====================================================

This is the main entry point for the Digital Hand Goniometry application,
replacing the previous web-based interface built on Streamlit.

Responsibilities:
    1. Configure the global logging system (file and console handlers).
    2. Optimize graphics rendering on Windows (disabling OpenGL if needed).
    3. Initialize the Qt application and apply the dark visual theme.
    4. Instantiate and display the MainWindow.
    5. Catch unhandled fatal exceptions to prevent silent crashes.

Run commands:
    - PyQt6 interface (main)      : python app_pyqt.py
"""

import logging
import os
import sys
import traceback

from PyQt6.QtWidgets import QApplication

import config
import themes
from ui.main_window import MainWindow

# Attempt to load pyqtgraph. On some Windows machines, pyqtgraph tries to
# use OpenGL and crashes when basic video drivers are present.
try:
    import pyqtgraph as pg
    # Disable native OpenGL as a precaution. The software (raster) renderer
    # in PyQtGraph is extremely fast and more than sufficient for 2D line
    # charts, and is 100% stable on any PC configuration.
    pg.setConfigOption("useOpenGL", False)
except ImportError:
    # Handled inside the widgets that use pyqtgraph.
    pass


def setup_logging() -> None:
    """
    Configure the global logging system for console and file output.

    Why configure this globally at the entry point?
        Any module (MainWindow, CameraWorker, etc.) can call
        logging.getLogger(__name__) and automatically inherit this
        formatting, without configuring a logger individually per file.

    Format:
        "2026-06-23 14:35:12,123 | INFO | ui.main_window | Session started"
    """
    # Ensure the log directory exists
    os.makedirs(config.LOG_DIR, exist_ok=True)
    log_file = os.path.join(config.LOG_DIR, "app.log")

    # Standardized format: date/time | level | module | message
    log_format = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"

    # Configure the root logger
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),  # File handler
            logging.StreamHandler(sys.stdout),                 # Console handler
        ]
    )


def exception_hook(exc_type, exc_value, exc_traceback) -> None:
    """
    Global handler for uncaught exceptions.

    Why use sys.excepthook?
        In PyQt applications, exceptions raised inside slots or signals
        are sometimes silently swallowed by Qt, causing the program to
        crash without any visible error. The excepthook guarantees that
        NO fatal exception goes unnoticed: all will be recorded in app.log
        with a full traceback before the application terminates.
    """
    # If the exception is a keyboard interrupt (Ctrl+C in terminal),
    # do not treat it as a fatal error — just let the application close.
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    # Log the fatal error with the full call stack (traceback)
    logger = logging.getLogger("sys.excepthook")
    logger.critical(
        "Unhandled Fatal Exception:\n",
        exc_info=(exc_type, exc_value, exc_traceback),
    )


def main() -> None:
    """
    Main application entry point.
    Configures the environment, creates the UI, and starts the Qt event loop.
    """
    # 1. Configure logging and global exception capture
    setup_logging()
    sys.excepthook = exception_hook

    logger = logging.getLogger("app_pyqt")
    logger.info("Initializing Digital Hand Goniometry (PyQt6 interface)...")

    # Wrap the entire application execution in try/except to ensure
    # initialization errors are always logged.
    try:
        # 2. Create the main Qt application instance
        # sys.argv allows the application to accept command-line parameters
        # (e.g., native Qt style parameters)
        app = QApplication(sys.argv)

        # 3. Set the application name (used internally by the OS and Qt)
        app.setApplicationName(config.APP_TITLE)

        # 4. Apply the standardized dark theme to all native components
        themes.apply_dark_theme(app)

        # 5. Instantiate the main window, which orchestrates everything else
        window = MainWindow()

        # 6. Display the window (show() respects screen boundaries by default)
        window.show()

        logger.info("Interface started successfully. Qt event loop active.")

        # 7. Start the event loop (blocking until the window is closed)
        # sys.exit passes the return code from app.exec() to the OS
        sys.exit(app.exec())

    except Exception as e:
        logger.critical("Fatal error starting the application: %s", e, exc_info=True)
        # Exit with error code 1
        sys.exit(1)


# Execute only when this file is run directly (python app_pyqt.py)
if __name__ == "__main__":
    main()
