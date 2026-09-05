"""
ui/__init__.py
==============

This empty file makes the ui/ directory a Python package,
enabling imports using the notation:

    from ui.video_widget import VideoWidget
    from ui.metrics_widget import MetricsWidget
    from ui.main_window import MainWindow

Modules contained in this package:
    - video_widget.py       → VideoWidget(QLabel): displays BGR frames in real time
    - metrics_widget.py     → MetricsWidget(QGroupBox): FPS, CPU, hand state cards
    - plot_widget.py        → GoniometryPlotWidget: live TAM chart for 5 fingers (PyQtGraph)
    - finger_card_widget.py → FingerCardWidget + FingerCardsPanel: individual finger cards
    - session_header.py     → SessionHeaderWidget: patient form + session timer
    - log_widget.py         → LogWidget(QTextEdit): event log with timestamps
    - main_window.py        → MainWindow(QMainWindow): main window and orchestration
"""
