"""
ui/plot_widget.py — Real-time TAM chart for all 5 fingers
==========================================================

This module implements the GoniometryPlotWidget: a live line chart that
displays the TAM (Total Active Motion) history of each finger simultaneously,
allowing the clinician to monitor movement evolution in real time.

What is TAM (Total Active Motion)?
    TAM is the most important clinical metric in hand function assessment.
    Defined by the ASSH (American Society for Surgery of the Hand), it represents
    the SUM of active ranges of motion across all joints of a finger:

        TAM = MCP + PIP + DIP  (long fingers: Index, Middle, Ring, Pinky)
        TAM = MCP + IP          (Thumb, which has no DIP)

    A TAM of 270° (theoretical maximum: MCP 90° + PIP 110° + DIP 70°)
    indicates full function. The chart allows visualization of whether TAM is:
    - Increasing (functional improvement during the session).
    - Stable (maintenance).
    - Decreasing (fatigue or worsening).

Why PyQtGraph instead of Matplotlib?
    Matplotlib generates STATIC charts — redrawing at each frame (~30x/s)
    would be catastrophically slow (150–400ms per redraw). PyQtGraph is
    optimized for real-time data: uses OpenGL when available and updates
    only the changed pixels. Updates at 30 FPS with PyQtGraph cost ~1–3ms,
    versus 150–400ms with Matplotlib.

Data structure:
    A deque(maxlen=BUFFER_SIZE) per finger holds the last N TAM values.
    On each frame, the new TAM is appended and the oldest is discarded
    automatically by the deque. The chart's X axis is implicitly the
    sample index (0 to N-1) — it does not represent absolute time.
"""

from collections import deque
from typing import Deque, Dict, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

# Import pyqtgraph with availability check.
try:
    import pyqtgraph as pg
    _PG_AVAILABLE = True
except ImportError:
    _PG_AVAILABLE = False

import config


class GoniometryPlotWidget(QWidget):
    """
    This module implements GoniometryPlotWidget, responsible for drawing the
    live Total Active Motion (TAM) chart for the 5 fingers.
    It uses pyqtgraph for high performance, maintaining a thread-safe sliding
    window of historical data (self._buffers) and managing 5 separate curves
    with finger names (config.FINGER_NAMES).

    Why inherit from QWidget instead of pg.PlotWidget directly?
        Inheriting directly from pg.PlotWidget limits layout flexibility:
        we cannot add extra widgets (e.g., title, controls) without creating
        an external container. By inheriting from QWidget and CONTAINING an
        internal PlotWidget, we retain full layout control and can add
        future elements without refactoring.

    Graceful degradation:
        If PyQtGraph is not installed, the widget displays an informational
        message instead of crashing the application. This allows the rest
        of the interface to work even without the chart.

    Usage in MainWindow:
        self.plot_widget = GoniometryPlotWidget()
        layout.addWidget(self.plot_widget)
        # In _on_result():
        self.plot_widget.update_data(result.angles_smooth, result.hand_detected)
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """
        Initializes the chart with 5 curves, legend, grid, and circular buffers.

        Configures PyQtGraph BEFORE instantiating any widget, because
        pg.setConfigOption() must be called before PlotWidget creation to
        take effect. Settings applied afterwards are ignored.

        Parameters:
            parent: Qt parent widget (optional). Usually the layout container.
        """
        super().__init__(parent)

        # Vertical layout containing only the PlotWidget (or the error message).
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Fixed height for the chart — enough to see the 5 curves with
        # visible rom, without dominating the main window layout.
        self.setFixedHeight(220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        if not _PG_AVAILABLE:
            # PyQtGraph not installed — display warning without crashing.
            from PyQt6.QtWidgets import QLabel
            lbl = QLabel("⚠️ PyQtGraph not installed.\nRun: pip install pyqtgraph")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("color: #ef4444; font-size: 13px;")
            layout.addWidget(lbl)
            # Empty dictionaries so update_data() does not break.
            self._curves: Dict[str, object] = {}
            self._buffers: Dict[str, Deque[float]] = {}
            self._plot_widget = None
            return

        # --- Global PyQtGraph settings ---
        # Must be set BEFORE any PlotWidget instance is created.

        # Default background for all PlotWidgets created after this call.
        # Using the same dark tone as the application theme (COLOR_BG_MEDIUM).
        pg.setConfigOption("background", "#16213e")

        # Default color for chart axes and text.
        pg.setConfigOption("foreground", "#94a3b8")

        # Disable OpenGL by default for maximum Windows compatibility.
        # If the system supports OpenGL, it can be enabled in app_pyqt.py
        # with pg.setConfigOption('useOpenGL', True) BEFORE creating this widget.
        pg.setConfigOption("useOpenGL", False)

        # --- PlotWidget creation ---
        self._plot_widget = pg.PlotWidget()
        self._plot_widget.setBackground("#16213e")

        # Remove the default PlotWidget border — the parent QGroupBox already has one.
        self._plot_widget.setStyleSheet("border: none;")

        layout.addWidget(self._plot_widget)

        # --- PlotItem configuration (the chart inside the PlotWidget) ---
        plot_item: pg.PlotItem = self._plot_widget.getPlotItem()

        # --- Chart title ---
        plot_item.setTitle(
            "Real-Time TAM — Total Active Motion per Finger",
            color="#94a3b8",
            size="11pt",
        )

        # --- Axis labels ---
        # Y axis: "TAM (°)" — the displayed quantity and its unit.
        plot_item.setLabel("left", "TAM", units="°", color="#94a3b8")

        # X axis: no label because it represents only the sequential sample index,
        # not absolute time. Displaying "Samples" or "Frames" would be technically
        # correct but confusing for the clinician.
        plot_item.hideAxis("bottom")

        # --- Subtle grid ---
        # alpha=0.3: visible but discreet grid — does not compete with the curves.
        # Higher values (0.5+) make the grid too prominent and hinder reading
        # the overlaid colored curves.
        plot_item.showGrid(x=True, y=True, alpha=0.3)

        # --- Y axis limits ---
        # TAM ranges from 0° (fully closed hand) to ~270° for long fingers
        # and ~130° for the thumb. Fixed at 280° so the chart does not "jump"
        # when approaching the upper limit.
        self._plot_widget.setYRange(0, 280, padding=0.05)

        # --- Legend ---
        # addLegend() creates the legend in the top-right corner by default.
        # offset=(10, 10): position relative to the corner — 10px margin.
        legend = plot_item.addLegend(offset=(10, 10))
        legend.setLabelTextColor("#e2e8f0")

        # --- Curve and buffer creation ---
        # One PlotDataItem per finger + one deque per finger.
        self._curves: Dict[str, pg.PlotDataItem] = {}
        self._buffers: Dict[str, Deque[float]] = {}

        for finger in config.FINGERS:
            # Retrieve this finger's hex color from the configuration dictionary.
            color_hex: str = config.FINGER_COLORS.get(finger, "#ffffff")

            # Display name for the legend.
            name_en: str = config.FINGER_NAMES.get(finger, finger)

            # Create the curve with:
            # - pen: pen with the finger's color and 2px width (readable thickness).
            # - name: name shown in the legend.
            # We do not pass x/y here — they will be set in update_data() via setData().
            curve = plot_item.plot(
                pen=pg.mkPen(color=color_hex, width=2),
                name=name_en,
            )
            self._curves[finger] = curve

            # Circular buffer per finger.
            # Why deque(maxlen=BUFFER_SIZE) instead of a growing list?
            #   1. FIXED memory: a growing list never discards old data and would
            #      grow indefinitely over a long session.
            #      At 30 FPS for 60 minutes = 108,000 floats per finger ≈ 840KB.
            #      With BUFFER_SIZE=500, we cap at ~3.9KB per finger regardless
            #      of session duration.
            #   2. Automatic FIFO: when adding a new value at maxlen capacity, the
            #      oldest is discarded automatically — no extra management code.
            #   3. Sliding window: the chart always displays the LAST N points,
            #      creating the "window advancing with time" effect.
            self._buffers[finger] = deque(maxlen=config.BUFFER_SIZE)

    # =========================================================================
    # CHART DATA UPDATE
    # =========================================================================

    def update_data(self, angles_smooth: dict, hand_detected: bool) -> None:
        """
        Updates the chart with smoothed angles from the current frame.

        Called by MainWindow on each result_ready emission from ProcessingWorker
        (~30 times/second). Must be fast: only append() to the deque and
        setData() on the curve — no calculations, no disk access.

        Why not add a point if hand_detected is False?
            When the hand is not visible (out of frame, covered), the pipeline
            returns zero angles or those from the last valid detection. Adding
            zeros to the chart would create abrupt drops to 0 that do not represent
            real movement — they are artifacts of missing detection. By keeping
            the history static, the chart "pauses" while waiting for the hand
            to return to the field of view.

        Parameters:
            angles_smooth: Dictionary {finger: {joint: angle}} returned by
                           GoniometryFilterBank.smooth_all(). E.g.:
                           {"INDEX": {"MCP": 45.2, "PIP": 88.1, "DIP": 62.3, "TAM": 195.6}}
            hand_detected: True if MediaPipe detected the hand in this frame.
                           False when no hand is visible.
        """
        # If PyQtGraph is not available, there are no curves to update.
        if not _PG_AVAILABLE:
            return

        # Without detection, keep the current history without adding zeroed points.
        if not hand_detected:
            return

        for finger in config.FINGERS:
            # Extract this finger's TAM from the smoothed angles dictionary.
            # TAM is chosen as the chart metric because:
            #   1. It summarizes the whole finger's function in ONE NUMBER (sum of all angles).
            #   2. It is the ASSH's official clinical metric for functional assessment.
            #   3. It is stable enough for real-time visualization (does not oscillate
            #      like individual MCP or PIP values during movement).
            # .get(finger, {}).get("TAM", 0.0): safe access with fallback 0.0
            # in case the dictionary does not contain this finger (e.g., partial occlusion).
            tam: float = float(angles_smooth.get(finger, {}).get("TAM", 0.0))

            # Only add to the buffer if the value is positive.
            # TAM = 0.0 indicates absent data, not a real angle.
            # Including zeros would distort the chart's scale and visualization.
            if tam > 0.0:
                self._buffers[finger].append(tam)

            # Convert the deque to list() to pass to PyQtGraph.
            # list(deque) creates a linear copy of the deque in O(n).
            # setData() with a list of Python floats is accepted by PyQtGraph,
            # which converts internally to numpy only at rendering time.
            # This is more efficient than maintaining a separate NumPy array
            # and concatenating on every frame.
            data = list(self._buffers[finger])

            if data:
                # setData() with only y: the X axis is automatically
                # 0, 1, 2, ..., len(data)-1 — the sample index.
                # We do not need an explicit X array because the chart is
                # a sliding index window, not timestamps.
                self._curves[finger].setData(y=data)

    # =========================================================================
    # DATA RESET
    # =========================================================================

    def clear_data(self) -> None:
        """
        Clears all buffers and redraws the curves as empty.

        Called by MainWindow when starting a new session, so that the previous
        session's data does not appear in the new session's chart.
        Also useful for "zeroing" the chart without restarting the widget.

        After clear_data(), update_data() begins building the history from
        scratch — curves grow gradually from left to right until BUFFER_SIZE
        samples have accumulated.
        """
        if not _PG_AVAILABLE:
            return

        for finger in config.FINGERS:
            # Clear the deque without recreating the object — more efficient than
            # replacing it with deque(maxlen=BUFFER_SIZE) because no reallocation.
            self._buffers[finger].clear()

            # Redraw the curve with an empty array to visually clear the chart.
            # Passing y=[] instructs PyQtGraph not to draw any point.
            self._curves[finger].setData(y=[])

    # =========================================================================
    # CLINICAL RANGE CONFIGURATION
    # =========================================================================

    def set_y_range(self, y_min: float, y_max: float) -> None:
        """
        Adjusts the visible range of the chart's Y axis.

        Useful when the clinician wants to focus on a specific TAM range,
        for example when evaluating patients with very limited range of motion
        (TAM < 100°) where the default 0–280° scale would be too sparse.

        Parameters:
            y_min: Minimum Y axis value in degrees. Usually 0.0.
            y_max: Maximum Y axis value in degrees. Application default: 280.0.
        """
        if not _PG_AVAILABLE or self._plot_widget is None:
            return

        # padding=0: no extra margin above and below the defined range.
        # With default padding (~0.05), PyQtGraph adds 5% of space beyond
        # the limits, which could clip the axis labels.
        self._plot_widget.setYRange(y_min, y_max, padding=0)

    # =========================================================================
    # CURVE VISIBILITY
    # =========================================================================

    def set_finger_visible(self, finger: str, visible: bool) -> None:
        """
        Shows or hides the curve for a specific finger.

        Allows the clinician to focus on a single finger by hiding the others,
        or re-enable all after an individual assessment.

        Parameters:
            finger: Finger key in the format used by the scientific pipeline.
                    Valid values: "INDEX", "MIDDLE", "RING", "PINKY", "THUMB".
            visible: True to show the curve, False to hide it.
        """
        if not _PG_AVAILABLE:
            return

        curve = self._curves.get(finger)
        if curve is not None:
            # setVisible() affects rendering but does not remove data from the buffer.
            # When the curve is made visible again, the historical data is retained.
            curve.setVisible(visible)
