"""
ui/metrics_widget.py — System metrics and hand state panel
===========================================================

This module implements the MetricsWidget: a side panel that displays in
real time the system performance metrics (FPS, CPU, RAM) and the
clinical hand state (open/closed, finger count, identification).

Responsibility:
    Receive a ready ProcessingResult (computed by ProcessingWorker) and
    update the corresponding visual cards. Performs no calculations — it
    only formats and displays the incoming data.

Card layout (2-row × 3-column grid):
    ┌──────────┬──────────┬──────────┐
    │   FPS    │   CPU    │   RAM    │
    ├──────────┼──────────┼──────────┤
    │  Frame#  │  State   │  State   │
    │          │  (hand)  │  (wide)  │
    └──────────┴──────────┴──────────┘

    The Hand State card occupies 2 columns in the second row to have
    enough space for text like "🟢 HAND OPEN (X/5)" and "🔴 HAND CLOSED".

Integration in MainWindow:
    self.metrics_widget = MetricsWidget()
    processing_worker.result_ready.connect(
        lambda result: self.metrics_widget.update_from_result(result)
    )
"""

from typing import Optional, Tuple

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# Import centralized styles from the dark theme module.
from themes import (
    CARD_STYLE,
    CARD_HAND_CLOSED_STYLE,
    CARD_HAND_OPEN_STYLE,
    LABEL_HAND_STATE_STYLE,
    LABEL_TITLE_STYLE,
    LABEL_VALUE_STYLE,
)

# Import the worker result dataclass for correct typing.
# Conditional import avoids circular imports if modules are reorganized.
from workers.processing_worker import ProcessingResult

# Try to import psutil for OS metrics collection.
# psutil is an OPTIONAL dependency: if not installed, the CPU and RAM cards
# display "—" instead of raising a fatal exception.
try:
    import psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    _PSUTIL_AVAILABLE = False


class _MetricCard(QWidget):
    """
    Reusable visual card for displaying a single metric.

    Each card has:
    - A QFrame container with rounded border (visual "card" appearance).
    - A title QLabel (e.g., "FPS") in small secondary text.
    - A value QLabel (e.g., "58.3") in large bold text.

    This internal component (_MetricCard, underscore = module-private)
    is instantiated by MetricsWidget for each metric. Centralizing
    construction logic here avoids code repetition for the 5 cards.
    """

    def __init__(
        self,
        title: str,
        initial_value: str = "—",
        parent: Optional[QWidget] = None,
    ) -> None:
        """
        Builds a metric card with a title and initial value.

        Parameters:
            title: Static label shown at the top of the card. E.g.: "FPS", "CPU".
            initial_value: Value shown before any real data arrives.
                           Default "—" indicates "no data available".
            parent: Qt parent widget (optional).
        """
        super().__init__(parent)

        # Vertical internal layout: title on top, value below.
        layout = QVBoxLayout(self)
        # Small inner margins to avoid wasting space on the side panel.
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)

        # Container with rounded border (style comes from themes.py).
        self._frame = QFrame()
        self._frame.setStyleSheet(CARD_STYLE)

        frame_layout = QVBoxLayout(self._frame)
        frame_layout.setContentsMargins(8, 6, 8, 6)
        frame_layout.setSpacing(2)
        frame_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Title label — small text in secondary gray.
        self._label_title = QLabel(title)
        self._label_title.setStyleSheet(LABEL_TITLE_STYLE)
        self._label_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Value label — large bold text, visual emphasis.
        self._label_value = QLabel(initial_value)
        self._label_value.setStyleSheet(LABEL_VALUE_STYLE)
        self._label_value.setAlignment(Qt.AlignmentFlag.AlignCenter)

        frame_layout.addWidget(self._label_title)
        frame_layout.addWidget(self._label_value)

        layout.addWidget(self._frame)

        # Allows the card to shrink vertically without distorting the layout.
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

    def set_value(self, value: str) -> None:
        """
        Updates the text of the card's value label.

        Called by MetricsWidget update methods on each new result.

        Parameters:
            value: Formatted string to display. E.g.: "58.3", "23%", "4.1 GB".
        """
        self._label_value.setText(value)

    def set_frame_style(self, style: str) -> None:
        """
        Replaces the visual style of the inner QFrame (background color, border).

        Used by the Hand State card to alternate between green background
        (open hand) and red background (closed hand).

        Parameters:
            style: Qt StyleSheet string for the QFrame.
                   Usually CARD_HAND_OPEN_STYLE or CARD_HAND_CLOSED_STYLE.
        """
        self._frame.setStyleSheet(style)


class HandStateCard(QWidget):
    """
    Specialized card for displaying the clinical hand state.

    Unlike other cards (_MetricCard), this one shows:
    - Colored icon (🟢 or 🔴).
    - Large text indicating OPEN or CLOSED.
    - Count of closed fingers in parentheses: "(X/5)".
    - Background that changes color (green / red) according to the state.

    The background color change is the most important element: it allows
    the physiotherapist to assess the hand state with a quick side glance,
    without needing to read the text.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """
        Initializes the state card with default visual (no data).

        Parameters:
            parent: Qt parent widget (optional).
        """
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)

        # Main card container.
        self._frame = QFrame()
        self._frame.setStyleSheet(CARD_STYLE)

        frame_layout = QVBoxLayout(self._frame)
        frame_layout.setContentsMargins(10, 8, 10, 8)
        frame_layout.setSpacing(4)
        frame_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Static title label.
        self._label_title = QLabel("HAND STATE")
        self._label_title.setStyleSheet(LABEL_TITLE_STYLE)
        self._label_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Main state label — large text, changes based on detection.
        self._label_state = QLabel("⬜ WAITING")
        self._label_state.setStyleSheet(LABEL_HAND_STATE_STYLE)
        self._label_state.setAlignment(Qt.AlignmentFlag.AlignCenter)

        frame_layout.addWidget(self._label_title)
        frame_layout.addWidget(self._label_state)

        layout.addWidget(self._frame)

        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

    def update_state(self, hand_open: bool, closed_count: int, hand_detected: bool) -> None:
        """
        Updates the full visual state of the hand card.

        Simultaneously changes:
        1. The text and icon (🟢/🔴).
        2. The frame background color (green/red).

        When no hand is detected, displays a neutral state without alert color
        to avoid confusing the clinician during camera positioning.

        Parameters:
            hand_open: True if the hand is considered open (majority of fingers
                       with TAM above the threshold), False if closed.
            closed_count: Number of fingers considered closed (0–5).
            hand_detected: True if MediaPipe found a hand in this frame.
        """
        if not hand_detected:
            # No hand detected: neutral state without error indication.
            self._frame.setStyleSheet(CARD_STYLE)
            self._label_state.setText("⬜ NO DETECTION")
            return

        # Calculate how many fingers are open (complement of closed).
        # We display OPEN fingers because it is more clinically intuitive:
        # "2/5 fingers open" communicates the degree of opening, not closure.
        open_count: int = 5 - closed_count

        if hand_open:
            # Dark green background: hand considered open — positive functional state.
            self._frame.setStyleSheet(CARD_HAND_OPEN_STYLE)
            self._label_state.setText(f"🟢 HAND OPEN ({open_count}/5)")
        else:
            # Dark red background: hand considered closed — clinical alert.
            self._frame.setStyleSheet(CARD_HAND_CLOSED_STYLE)
            self._label_state.setText(f"🔴 HAND CLOSED ({open_count}/5)")


# =============================================================================
# MAIN WIDGET
# =============================================================================

class MetricsWidget(QGroupBox):
    """
    Side panel for system metrics and clinical hand state.

    Organizes individual cards in a 2×3 grid and connects data sources
    (ProcessingResult and psutil) to each corresponding card.

    Widget hierarchy:
        MetricsWidget (QGroupBox)
        └── QGridLayout
            ├── _MetricCard("FPS")          [row 0, column 0]
            ├── _MetricCard("CPU")          [row 0, column 1]
            ├── _MetricCard("RAM")          [row 0, column 2]
            ├── _MetricCard("Frame #")      [row 1, column 0]
            └── HandStateCard               [row 1, columns 1–2, colspan=2]
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """
        Initializes the MetricsWidget with all cards and the system timer.

        The system QTimer (_stats_timer) is started here and fires every
        1000ms to update CPU and RAM independently of processed frames.
        This ensures system metrics remain updated even when the camera
        is not active (e.g., IDLE state).

        Parameters:
            parent: Qt parent widget (optional).
        """
        super().__init__("System Metrics", parent)

        # 2-row × 3-column grid for metric cards.
        self._grid = QGridLayout(self)
        self._grid.setSpacing(8)
        self._grid.setContentsMargins(10, 16, 10, 10)

        # --- Row 0: performance metrics ---

        # Processing pipeline FPS (not camera FPS).
        # Reflects the REAL speed of the ProcessingWorker.
        self._card_fps = _MetricCard("FPS", "—")

        # Overall system CPU usage percentage.
        # psutil.cpu_percent() measures all cores.
        self._card_cpu = _MetricCard("CPU", "—")

        # RAM usage in Gigabytes.
        # Important to monitor: MediaPipe + buffers can use significant memory.
        self._card_ram = _MetricCard("RAM", "—")

        self._grid.addWidget(self._card_fps, 0, 0)
        self._grid.addWidget(self._card_cpu, 0, 1)
        self._grid.addWidget(self._card_ram, 0, 2)

        # --- Row 1: frame counter + hand state ---

        # Processed frame counter for this session.
        # Useful for correlating log events with frames in the CSV.
        self._card_frame = _MetricCard("Frame #", "—")

        # Specialized card with color change for the hand state.
        # Occupies 2 columns (colspan=2) to have space for the full text.
        self._card_hand = HandStateCard()

        self._grid.addWidget(self._card_frame, 1, 0)

        # colspan=2: the state card occupies columns 1 and 2 of row 1.
        # This gives more horizontal space for text like "HAND OPEN (5/5)".
        self._grid.addWidget(self._card_hand, 1, 1, 1, 2)

        # Ensures the 3 grid columns have equal weight.
        # Without this, columns with smaller content would be narrower.
        for col in range(3):
            self._grid.setColumnStretch(col, 1)

        # --- System metrics update timer ---
        # Fires every 1000ms (1 second) — adequate rate for CPU and RAM.
        # Updating faster would not provide additional useful information, since
        # psutil.cpu_percent() already applies internal smoothing.
        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(1000)
        self._stats_timer.timeout.connect(self._update_system_stats)

        # Start the timer immediately — displays CPU/RAM values from the
        # beginning, even before the camera is turned on.
        self._stats_timer.start()

        # Force the first CPU/RAM reading immediately on widget creation.
        self._update_system_stats()

    # =========================================================================
    # UPDATE WITH PROCESSING DATA
    # =========================================================================

    def update_from_result(self, result: ProcessingResult) -> None:
        """
        Updates the FPS, Frame#, and Hand State cards with worker data.

        Called by MainWindow on each emission of the result_ready signal
        from ProcessingWorker (~30 times/second). Must be fast — only updates
        text, no calculations or disk access.

        Parameters:
            result: ProcessingResult emitted by the ProcessingWorker.
                    Contains fps, frame_id, hand_state, and hand_detected.
        """
        # Format FPS with one decimal for stable readability.
        # Two decimal places cause "jitter" (58.33 → 58.21 → 58.45),
        # making reading difficult. One decimal is sufficient for monitoring.
        self._card_fps.set_value(f"{result.fps:.1f}")

        # Frame# displayed without special formatting — it is a simple sequential integer.
        self._card_frame.set_value(str(result.frame_id))

        # Extract hand state from the dictionary returned by classify_hand_state().
        # Expected keys: "hand_open" (bool) and "closed_count" (int, 0–5).
        hand_open: bool = result.hand_state.get("hand_open", True)
        closed_count: int = result.hand_state.get("closed_count", 0)

        # Propagate data to the specialized state card.
        self._card_hand.update_state(
            hand_open=hand_open,
            closed_count=closed_count,
            hand_detected=result.hand_detected,
        )

    # =========================================================================
    # SYSTEM METRICS UPDATE (CPU and RAM)
    # =========================================================================

    def _update_system_stats(self) -> None:
        """
        Collects and displays operating system performance metrics.

        Called by QTimer every 1000ms — not tied to frame processing.
        CPU and RAM are system resources, not camera resources.

        Graceful degradation:
            If psutil is not installed, displays "—" in the cards
            without raising an exception. This allows the application to work
            correctly in environments where psutil is unavailable,
            just without resource monitoring.

        Why interval=None in cpu_percent()?
            psutil.cpu_percent(interval=N) would BLOCK for N seconds.
            With interval=None, returns the value computed since the last call,
            without blocking. Since we call it every 1s via QTimer, the effective
            interval is always ~1 second — ideal for monitoring.
        """
        if not _PSUTIL_AVAILABLE:
            # psutil not installed — display placeholder without error.
            self._card_cpu.set_value("—")
            self._card_ram.set_value("—")
            return

        try:
            # CPU usage percentage (average across all cores).
            # interval=None: non-blocking, uses the interval since the last call.
            cpu_percent: float = psutil.cpu_percent(interval=None)
            self._card_cpu.set_value(f"{cpu_percent:.0f}%")

            # RAM in use, converted from bytes to Gigabytes.
            # 1024**3 = 1 GiB. One decimal place for adequate precision.
            ram_bytes: int = psutil.virtual_memory().used
            ram_gb: float = ram_bytes / (1024 ** 3)
            self._card_ram.set_value(f"{ram_gb:.1f} GB")

        except Exception as exc:
            # Catch unexpected psutil errors (e.g., permission denied
            # on some Linux systems with /proc access restrictions).
            # Do not propagate the error to avoid interrupting the QTimer loop.
            self._card_cpu.set_value("!")
            self._card_ram.set_value("!")

    # =========================================================================
    # TIMER CONTROL
    # =========================================================================

    def start_monitoring(self) -> None:
        """
        Starts or restarts the CPU and RAM monitoring timer.

        Called by MainWindow when starting a session, in case the timer
        was previously stopped by stop_monitoring().
        """
        if not self._stats_timer.isActive():
            self._stats_timer.start()

    def stop_monitoring(self) -> None:
        """
        Stops the CPU and RAM monitoring timer.

        Can be called by MainWindow when ending the session to reduce
        CPU overhead when the application is in STOPPED or IDLE state.
        The timer can be restarted with start_monitoring() at any time.
        """
        if self._stats_timer.isActive():
            self._stats_timer.stop()

    def reset_display(self) -> None:
        """
        Resets all cards to the initial "no data" state (—).

        Called by MainWindow when starting a new session to clear
        the previous session's values, preventing old data from being
        confused with new session data during the initial warmup.
        """
        self._card_fps.set_value("—")
        self._card_frame.set_value("—")
        self._card_hand.update_state(
            hand_open=True,
            closed_count=0,
            hand_detected=False,
        )
