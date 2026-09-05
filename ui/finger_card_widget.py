"""
ui/finger_card_widget.py — Individual finger cards with mini-chart
===================================================================

This module implements two visual components:

1. FingerCardWidget(QGroupBox):
   Displays ALL clinical metrics for ONE single finger in a compact card.
   Each instance is dedicated to a specific finger (Thumb, Index, etc.).

2. FingerCardsPanel(QWidget):
   Container that organizes the 5 FingerCardWidgets side by side in a row.
   It is the only component that MainWindow needs to instantiate — it
   manages the 5 cards internally.

Metrics displayed per card (from the scientific pipeline):
    TAM (°)       : Total Active Motion — total active range of motion.
    ASSH          : Functional classification (Excellent / Good / Fair / Poor).
    ROM (°) : Difference between maximum and minimum TAM in the time window.
    Avg. Vel.     : Mean angular velocity (°/s) — overall movement speed.
    Peak Vel.     : Maximum angular velocity (°/s) — peak effort.
    Frequency     : Rate of complete cycles per second (Hz).
    Regularity    : Qualitative assessment of movement consistency.
    Mini-chart    : TAM history over the last BUFFER_SIZE points (PyQtGraph).

Data sources:
    state   ← classify_hand_state()["finger_states"][finger]
    metrics ← compute_realtime_metrics(angle_buffer, time_buffer)

Why one card per finger?
    The physiotherapist often needs to quickly compare the performance of
    adjacent fingers (e.g., Index vs Middle after an injury). Displaying all
    in a row allows instant visual comparison without navigating through menus.
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

# Import centralized styles from the theme module.
from themes import (
    FINGER_CARD_STYLE,
    LABEL_CLINICAL_SECONDARY_STYLE,
    LABEL_CLINICAL_VALUE_STYLE,
    LABEL_SECTION_TITLE_STYLE,
)
import config

# Try to import PyQtGraph for mini-charts.
# If not installed, mini-charts are replaced by a label.
try:
    import pyqtgraph as pg
    _PG_AVAILABLE = True
except ImportError:
    _PG_AVAILABLE = False


class FingerCardWidget(QGroupBox):
    """
    Complete clinical card for a single hand finger.

    Displays goniometry metrics, kinetic metrics, and a live TAM mini-chart
    in a compact space designed to sit side by side with 4 other cards.

    Internal layout (QVBoxLayout):
        ┌──────────────────────────────┐
        │ [finger name]                │  ← QGroupBox title
        │ TAM: 127.3°  [Fair] 🟡      │  ← TAM + ASSH in one row
        │ ─────────────────────────── │
        │ ROM  : 45.2°          │
        │ Avg. Vel.  : 38.1 °/s       │
        │ Peak Vel.  : 112.4 °/s      │
        │ Frequency  : 0.33 Hz        │
        │ Regularity : ✅ Regular     │
        │ ─────────────────────────── │
        │ [TAM mini-chart, 80px]      │
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
        Initializes the card for a specific finger.

        Parameters:
            finger_key: Internal finger identifier in the scientific pipeline.
                        Values: "INDEX", "MIDDLE", "RING", "PINKY", "THUMB".
            name_en: Finger display name for the group title.
                     E.g.: "Index", "Middle", "Thumb".
            color_hex: Finger hex color (from config.FINGER_COLORS).
                       Used in the mini-chart and highlighted elements.
            parent: Qt parent widget (optional).
        """
        super().__init__(name_en, parent)

        # Store the finger key for future use (e.g., debugging, logging).
        self._finger_key: str = finger_key
        self._color_hex: str = color_hex

        # Apply the card's visual style (border, background, title).
        self.setStyleSheet(FINGER_CARD_STYLE)

        # Minimum width so the 5 cards don't get squashed.
        # With 5 cards in a row in a 1280px window: 1280/5 = 256px per card.
        self.setMinimumWidth(200)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

        # Main vertical layout of the card.
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 16, 8, 8)
        layout.setSpacing(4)

        # --- TAM + ASSH Classification row ---
        self._build_tam_row(layout)

        # --- Visual separator ---
        self._add_separator(layout)

        # --- Kinetic metrics grid ---
        self._build_metrics_grid(layout)

        # --- Visual separator ---
        self._add_separator(layout)

        # --- Live TAM mini-chart ---
        self._build_mini_chart(layout, color_hex)

    # =========================================================================
    # INTERNAL SECTION BUILDERS
    # =========================================================================

    def _build_tam_row(self, parent_layout: QVBoxLayout) -> None:
        """
        Builds the main row with TAM value and ASSH classification.

        Places TAM and ASSH on the same horizontal row to save vertical space
        without sacrificing readability — TAM is the most important value
        and must have immediate visual emphasis.

        Parameters:
            parent_layout: Parent layout where the row will be added.
        """
        row = QHBoxLayout()
        row.setSpacing(6)

        # "TAM" label — indicates the displayed quantity.
        lbl_tam_title = QLabel("TAM:")
        lbl_tam_title.setStyleSheet(LABEL_SECTION_TITLE_STYLE)
        lbl_tam_title.setFixedWidth(36)

        # Numeric TAM value — highest visual emphasis.
        self._lbl_tam_value = QLabel("—")
        self._lbl_tam_value.setStyleSheet(LABEL_CLINICAL_VALUE_STYLE)

        # ASSH classification with dynamic color (green/yellow/orange/red).
        # Color is applied via setStyleSheet in update(), not here.
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
        Builds the grid with kinetic metrics (rom, velocity, frequency).

        Uses a 2-column grid (label | value) to correctly align data without
        wasting space. Each row represents a different metric.

        Parameters:
            parent_layout: Parent layout where the grid will be added.
        """
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(2)

        # Metric names (static labels) and references to value labels.
        # Order follows clinical relevance: rom first, then velocity,
        # frequency and regularity (from most objective to most interpreted).
        metrics_rows = [
            ("ROM",   "—"),
            ("Avg. Vel.",   "—"),
            ("Peak Vel.",   "—"),
            ("Frequency",   "—"),
            ("Regularity",  "—"),
        ]

        # Dictionary for quick access in update() — mapping internal name → QLabel.
        self._metric_labels: Dict[str, QLabel] = {}

        for row_idx, (label_text, init_value) in enumerate(metrics_rows):
            # Static label on the left.
            lbl_title = QLabel(f"{label_text}:")
            lbl_title.setStyleSheet(LABEL_CLINICAL_SECONDARY_STYLE)
            lbl_title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

            # Dynamic value on the right — updated each frame with real data.
            lbl_value = QLabel(init_value)
            lbl_value.setStyleSheet(LABEL_CLINICAL_SECONDARY_STYLE)
            lbl_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            grid.addWidget(lbl_title, row_idx, 0)
            grid.addWidget(lbl_value, row_idx, 1)

            # Store reference using the name without ":" as key.
            self._metric_labels[label_text] = lbl_value

        # Column 0 (labels): fixed width. Column 1 (values): stretches.
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)

        parent_layout.addLayout(grid)

    def _build_mini_chart(self, parent_layout: QVBoxLayout, color_hex: str) -> None:
        """
        Builds the live PyQtGraph TAM mini-chart inside the card.

        The mini-chart has height=80px, no visible axes, only the curve.
        Its purpose is to provide temporal context for the numeric TAM value —
        the clinician can see whether the value is rising, falling, or oscillating.

        Why no axes?
            With 5 cards in a row, each only ~200px wide, axes with labels would
            take ~30% of the chart space. The curve itself communicates the trend
            without needing numeric scales.

        Parameters:
            parent_layout: Parent layout where the mini-chart will be added.
            color_hex: Curve color, corresponding to the finger (config.FINGER_COLORS).
        """
        self._mini_curve = None
        self._mini_plot = None

        if not _PG_AVAILABLE:
            # Fallback without PyQtGraph: display message in place of chart.
            lbl_no_pg = QLabel("(PyQtGraph not installed)")
            lbl_no_pg.setStyleSheet(LABEL_CLINICAL_SECONDARY_STYLE)
            lbl_no_pg.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_no_pg.setFixedHeight(80)
            parent_layout.addWidget(lbl_no_pg)
            return

        # Configure mini-chart background with the same dark tone as the card.
        self._mini_plot = pg.PlotWidget()
        self._mini_plot.setBackground("#1e293b")

        # Remove the widget border — the QGroupBox already has one.
        self._mini_plot.setStyleSheet("border: none;")

        # Fixed height of 80px — compact but sufficient to show the trend.
        self._mini_plot.setFixedHeight(80)

        # Remove ALL axes for maximum visual compactness.
        # Axes would consume ~40% of the height in such a small chart.
        plot_item = self._mini_plot.getPlotItem()
        plot_item.hideAxis("left")
        plot_item.hideAxis("bottom")

        # Remove the right-click context menu — unnecessary in a mini-chart.
        plot_item.setMenuEnabled(False)

        # Disable mouse interaction — the mini-chart is view-only.
        self._mini_plot.setMouseEnabled(x=False, y=False)

        # Create the single curve of the mini-chart: TAM over time.
        # Width 1.5px: visible in 80px height without being too thick.
        self._mini_curve = plot_item.plot(
            pen=pg.mkPen(color=color_hex, width=1.5),
        )

        parent_layout.addWidget(self._mini_plot)

    def _add_separator(self, parent_layout: QVBoxLayout) -> None:
        """
        Adds a subtle horizontal separator between card sections.

        QFrame with frameShape=HLine creates a thin horizontal line, used
        as a visual divider between TAM, metrics, and the mini-chart.

        Parameters:
            parent_layout: Parent layout where the separator will be added.
        """
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        # Sunken shadow: creates the effect of a slightly recessed line.
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        separator.setStyleSheet("color: #334155; max-height: 1px;")
        parent_layout.addWidget(separator)

    # =========================================================================
    # DATA UPDATE
    # =========================================================================

    def update(
        self,
        state: dict,
        metrics: dict,
        tam_buffer: List[float],
    ) -> None:
        """
        Updates all card fields with data from the current frame.

        This method is called by FingerCardsPanel on each result_ready emission
        (~30x/s). Must be fast: only updates text and chart data, no calculations.

        Expected structure of 'state' (from classify_hand_state()):
            Long fingers: {"MCP": float, "PIP": float, "DIP": float,
                          "ABD": float, "TAM": float,
                          "closed": bool, "assh_label": str, "assh_color": str}
            Thumb:        {"MCP": float, "IP": float, "TAM": float,
                          "closed": bool, "assh_label": str, "assh_color": str}

        Expected structure of 'metrics' (from compute_realtime_metrics()):
            {"rom": float, "avg_velocity": float, "peak_velocity": float,
             "freq_hz": float, "cv": float, "regularity": str, "n_picos": int}

        Parameters:
            state: Dictionary with current angles and ASSH classification for the finger.
            metrics: Dictionary with kinetic metrics computed over the buffer.
            tam_buffer: List of the last N TAM values for the mini-chart.
        """
        # --- Primary TAM ---
        tam: float = float(state.get("TAM", 0.0))
        self._lbl_tam_value.setText(f"{tam:.1f}°")

        # --- ASSH classification with dynamic color ---
        assh_label: str = state.get("assh_label", "—")
        assh_color: str = state.get("assh_color", "#94a3b8")

        self._lbl_assh.setText(assh_label)

        # Apply the classification color via setStyleSheet.
        # Each ASSH level has a predefined color (green/yellow/orange/red)
        # that the clinician recognizes instantly without reading the text.
        self._lbl_assh.setStyleSheet(
            f"QLabel {{ color: {assh_color}; font-size: 12px; font-weight: bold; }}"
        )

        # --- Kinetic metrics ---
        rom: float = float(metrics.get("rom", 0.0))
        avg_velocity: float = float(metrics.get("avg_velocity", 0.0))
        peak_velocity: float  = float(metrics.get("peak_velocity",  0.0))
        freq_hz: float   = float(metrics.get("freq_hz",   0.0))
        regularity: str = str(metrics.get("regularity", "—"))

        # Format rom in degrees with one decimal place.
        self._metric_labels["ROM"].setText(f"{rom:.1f}°")

        # Format velocities in degrees per second with one decimal place.
        self._metric_labels["Avg. Vel."].setText(f"{avg_velocity:.1f} °/s")
        self._metric_labels["Peak Vel."].setText(f"{peak_velocity:.1f} °/s")

        # Format frequency in Hz with two decimal places.
        # Two decimals are needed because slow movements (0.25Hz) and
        # fast ones (2.00Hz) must be distinguishable with precision.
        self._metric_labels["Frequency"].setText(f"{freq_hz:.2f} Hz")

        # Add a visual icon to regularity for instant recognition.
        # The clinician can assess at a glance without reading the word.
        if regularity == "Regular":
            reg_text = "✅ Regular"
        elif regularity in ("Irregular", "Moderate"):
            reg_text = f"{'❌' if regularity == 'Irregular' else '🟡'} {regularity}"
        else:
            reg_text = regularity
        self._metric_labels["Regularity"].setText(reg_text)

        # --- Mini-chart ---
        self._update_mini_chart(tam_buffer)

    def _update_mini_chart(self, tam_buffer: List[float]) -> None:
        """
        Updates the mini-chart curve with the current TAM buffer.

        Called internally by update() on each frame. If PyQtGraph is not
        available, this method returns silently.

        The mini-chart's Y axis is auto-scaled by PyQtGraph to fit the
        current data range — without explicit limit configuration.
        This causes the curve to always fill the full 80px height, regardless
        of the real movement rom.

        Parameters:
            tam_buffer: List of floats with historical TAM values.
                        Empty if there is not yet sufficient data.
        """
        if self._mini_curve is None or not _PG_AVAILABLE:
            return

        if tam_buffer:
            # setData() with only y: X axis = 0, 1, 2, ... (sample index).
            # Real timestamps are not needed in the mini-chart — the visual
            # trend is sufficient to communicate movement evolution.
            self._mini_curve.setData(y=tam_buffer)
        else:
            # Empty buffer: clear the chart to avoid displaying stale data.
            self._mini_curve.setData(y=[])

    def clear(self) -> None:
        """
        Resets all card fields to the initial state without data.

        Called by FingerCardsPanel when starting a new session, so that the
        previous session's data is not confused with the new session's data.
        """
        self._lbl_tam_value.setText("—")
        self._lbl_assh.setText("—")
        self._lbl_assh.setStyleSheet(LABEL_CLINICAL_SECONDARY_STYLE)

        for lbl in self._metric_labels.values():
            lbl.setText("—")

        if self._mini_curve is not None:
            self._mini_curve.setData(y=[])


# =============================================================================
# PANEL WITH THE 5 CARDS
# =============================================================================

class FingerCardsPanel(QWidget):
    """
    Container that organizes the 5 FingerCardWidgets side by side in a row.

    This is the only component from this module that MainWindow instantiates directly.
    Internally, it creates and manages the 5 individual cards.

    Card display order (left to right):
        Thumb | Index | Middle | Ring | Pinky

    The order follows the anatomy of the hand viewed from the front, making it
    easy to visually correlate each card on screen with the patient's actual finger.

    Usage in MainWindow:
        self.finger_cards = FingerCardsPanel()
        layout.addWidget(self.finger_cards)
        # In _on_result():
        self.finger_cards.update_all(
            result.hand_state["finger_states"],
            result.metrics_per_finger,
            result.tam_buffers_snapshot,
        )
    """

    # Display order of the cards (left to right).
    # THUMB first because it is anatomically the first finger in the front-facing hand.
    DISPLAY_ORDER: List[str] = ["THUMB", "INDEX", "MIDDLE", "RING", "PINKY"]

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """
        Initializes the panel by creating the 5 cards in a row.

        Each card receives its finger key, display name, and identifying color
        from the config.py dictionaries.

        Parameters:
            parent: Qt parent widget (optional).
        """
        super().__init__(parent)

        # Horizontal layout: the 5 cards sit side by side.
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # 6px spacing between cards — visually separated but compact.
        layout.setSpacing(6)

        # Dictionary for quick access in update_all() — key = finger name.
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
        Updates all 5 cards with current frame data.

        Called by MainWindow on each result_ready emission from ProcessingWorker.
        Iterates over the 5 fingers and delegates each card's update to the
        corresponding FingerCardWidget.

        Tolerance for missing data:
            If a finger is not present in finger_states or metrics_per_finger
            (e.g., MediaPipe lost tracking of a specific finger), we use empty
            dictionaries as fallback so the card displays "—" instead of raising KeyError.

        Parameters:
            finger_states: Dictionary {finger: state_dict} returned by
                           classify_hand_state()["finger_states"].
                           Contains current angles and ASSH classification per finger.

            metrics_per_finger: Dictionary {finger: metrics_dict} where each dict is
                                the output of compute_realtime_metrics() for that finger.
                                Contains rom, avg_velocity, peak_velocity, freq_hz, etc.

            tam_buffers_per_finger: Dictionary {finger: [float]} with the TAM history
                                    for each card's mini-chart.
                                    Usually comes from ProcessingResult.tam_buffers_snapshot.
        """
        for finger_key, card in self._cards.items():
            # Safe access with fallback: if the finger was not detected this frame,
            # we pass empty dictionaries and the card will display "—".
            state = finger_states.get(finger_key, {})
            metrics = metrics_per_finger.get(finger_key, {})
            tam_buf = tam_buffers_per_finger.get(finger_key, [])

            card.update(state=state, metrics=metrics, tam_buffer=tam_buf)

    def clear_all(self) -> None:
        """
        Resets all 5 cards to the initial state without data.

        Called by MainWindow when starting a new session, to clear all previous
        session data before the camera is activated.
        """
        for card in self._cards.values():
            card.clear()

    def get_card(self, finger_key: str) -> Optional[FingerCardWidget]:
        """
        Returns the FingerCardWidget for a specific finger.

        Useful for targeted operations (e.g., highlighting a specific finger's card
        during an individual analysis, or temporarily hiding an unevaluated finger).

        Parameters:
            finger_key: Finger key. E.g.: "INDEX", "THUMB", "PINKY".

        Returns:
            Corresponding FingerCardWidget, or None if the key does not exist.
        """
        return self._cards.get(finger_key)
