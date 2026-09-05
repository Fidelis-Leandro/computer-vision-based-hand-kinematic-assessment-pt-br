"""
ui/video_widget.py — Real-time video display widget
=====================================================

This module implements the VideoWidget: a specialized QLabel that receives
NumPy BGR frames from the ProcessingWorker and displays them on screen with
minimal latency.

Single responsibility (SRP principle):
    This widget DOES ONE THING ONLY: transform a NumPy array (camera/OpenCV format)
    into a visible Qt image. It does not process pixels, does not analyze the image,
    does not compute angles — it only displays.

    All analysis has already happened in the ProcessingWorker. The VideoWidget
    receives the ready result (frame with drawn overlay) and displays it.

Why QLabel instead of a custom QWidget?
    QLabel already has native support for displaying QPixmap (images) in an
    optimized way. Inheriting from QLabel gives us setPixmap(), setAlignment(),
    and automatic scaling for free, without needing to implement paintEvent()
    from scratch to draw the base image.
    We override paintEvent() ONLY to add the FPS overlay on top of the image
    already rendered by the parent QLabel.

Data flow:
    ProcessingWorker
        → pyqtSignal result_ready(ProcessingResult)
        → MainWindow._on_result()
        → video_widget.update_frame(result.frame_overlay)   ← this widget's input
        → cv2.cvtColor(BGR→RGB)
        → QImage → QPixmap → self.setPixmap()               ← output: pixels on screen
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
    Real-time video display widget for the goniometry interface.

    Inherits from QLabel to leverage native QPixmap support, adding:
    - Automatic format conversion from BGR (OpenCV) to RGB (Qt).
    - FPS overlay drawn via QPainter, without affecting the main image.
    - "No signal" state with visual message when the camera fails.
    - Proportional image scaling when the window is resized.

    Typical usage in MainWindow:
        self.video_widget = VideoWidget()
        layout.addWidget(self.video_widget)
        processing_worker.result_ready.connect(
            lambda result: self.video_widget.update_frame(result.frame_overlay)
        )
        camera_worker.camera_error.connect(self.video_widget.set_no_signal)
    """

    def __init__(self, parent=None) -> None:
        """
        Initializes the VideoWidget with default visual settings.

        Configures minimum size, alignment, resize policy, and initial state
        ("no signal"). Does not open the camera or process any data.

        Parameters:
            parent: Qt parent widget (optional). Usually the layout container.
        """
        super().__init__(parent)

        # Minimum guaranteed size for the widget — below this the layout
        # will not allow the window to shrink further.
        # 480×360 is the smallest size that still allows the goniometric overlay
        # with angle labels to be legible.
        self.setMinimumSize(480, 360)

        # Center the content (pixmap) within the QLabel space.
        # Without this, the image would be stuck in the top-left corner
        # when the widget is larger than the frame.
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Allows the widget to grow and shrink freely in the layout,
        # while respecting the minimum size defined above.
        # Expanding in both directions allows the widget to fill the available
        # space in the left column of the main layout.
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        # Dark black background while no frame is available.
        # Matches the application's dark theme and avoids flickering when
        # the first real frame is displayed.
        self.setStyleSheet("QLabel { background-color: #0d1117; }")

        # Stores the current FPS value to be drawn in paintEvent.
        # Initialized as None to indicate no FPS reading is available yet.
        self._fps: Optional[float] = None

        # Flag indicating whether the widget is in the "no signal" state.
        # Controls which text is displayed when no frame is available.
        self._no_signal: bool = True

        # Display the initial "no signal" state immediately.
        self.set_no_signal()

    # =========================================================================
    # VIDEO FRAME UPDATE
    # =========================================================================

    def update_frame(self, frame_bgr: np.ndarray) -> None:
        """
        Receives a BGR frame from ProcessingWorker and displays it.

        This is the widget's performance-critical method. It is called on
        every processed frame (~30 times/second) and must be fast.

        Required conversion sequence:
            BGR (OpenCV/camera) → RGB (Qt) → QImage → QPixmap → screen

        Why is BGR → RGB mandatory?
            OpenCV uses the Blue-Green-Red order by historical convention from
            the Windows DirectShow standard. Qt uses Red-Green-Blue (modern standard).
            Without this conversion, all colors are inverted: human skin appears
            bluish, red text appears blue, etc.

        Why is bytes_per_line critical?
            QImage needs to know how many bytes exist per pixel row.
            For an image of width W with 3 channels (RGB), each row has exactly
            W*3 bytes. If we omit this parameter, Qt may assume a different value
            (based on memory alignment), making the image appear diagonally
            distorted — a subtle and hard-to-diagnose bug.

        Why use ascontiguousarray() before creating QImage?
            NumPy arrays are not always contiguous in memory (e.g., after
            slice or reshape operations). QImage expects contiguous data.
            We enforce this explicitly.

        Parameters:
            frame_bgr: NumPy array of shape (height, width, 3), dtype uint8,
                       in BGR format. Usually frame_overlay from ProcessingResult.
        """
        # Exit the "no signal" state when a valid frame is received.
        self._no_signal = False

        # Convert BGR → RGB because Qt expects channels in R-G-B order.
        # cv2.cvtColor is internally optimized with SIMD — much faster than
        # manually reversing channels with numpy slicing.
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

        # Ensure the array is contiguous in memory before creating QImage.
        # Non-contiguous arrays cause incorrect pixel reads by Qt.
        frame_rgb = np.ascontiguousarray(frame_rgb)

        # Extract dimensions to compute bytes_per_line.
        height, width, channels = frame_rgb.shape

        # bytes_per_line: number of bytes in a single horizontal row of the image.
        # For RGB without padding, it is always width × 3 channels.
        # This value MUST be passed explicitly to QImage — do not rely on the
        # default value, which may differ on systems with memory alignment.
        bytes_per_line: int = channels * width

        # Create QImage referencing the NumPy array memory directly.
        # Format_RGB888 = 3 bytes per pixel, R-G-B order, no alpha channel.
        # CAUTION: frame_rgb must remain in memory while QImage exists.
        # Since we convert to QPixmap immediately below, this is safe.
        q_image = QImage(
            frame_rgb.data,
            width,
            height,
            bytes_per_line,
            QImage.Format.Format_RGB888,
        )

        # Convert QImage → QPixmap (format optimized for on-screen display).
        # QPixmap is kept in video memory (GPU when available),
        # while QImage lives in main memory (CPU). The conversion is done
        # once here and the resulting QPixmap is displayed at no additional cost.
        pixmap = QPixmap.fromImage(q_image)

        # Scale the pixmap to fit the current widget size, preserving aspect ratio.
        # KeepAspectRatio: never distorts the image; adds black bars if necessary.
        # SmoothTransformation: uses bilinear interpolation — slower than Fast,
        # but produces aliasing-free images, especially when downscaling.
        scaled_pixmap = pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        # Update the QLabel content with the new frame.
        # setPixmap() automatically schedules a repaint — no need to call
        # update() or repaint() manually.
        self.setPixmap(scaled_pixmap)

    # =========================================================================
    # FPS OVERLAY
    # =========================================================================

    def set_fps(self, fps: float) -> None:
        """
        Stores the FPS value to be drawn on the next paintEvent.

        Why store instead of drawing immediately?
            Drawing directly on the pixmap (modifying the QPixmap) would be
            irreversible — the text would be "burned" into the image and accumulate
            on each update. Storing the value and redrawing via QPainter in
            paintEvent() ensures the text always appears clean, on top of the
            current image, without modifying the original pixmap.

            Also avoids double-draw: calling update() here would repaint the widget
            TWICE per frame (once from setPixmap in update_frame, once here).
            Storing the value and using paintEvent consolidates both operations
            into a single rendering cycle.

        Parameters:
            fps: Current FPS value of the processing pipeline (float).
                 Received from CameraWorker via the fps_updated signal.
        """
        self._fps = fps
        # Request repaint only if a pixmap is displayed.
        # Avoids unnecessary redraws in the "no signal" state.
        if self.pixmap() and not self.pixmap().isNull():
            self.update()

    def paintEvent(self, event) -> None:
        """
        Qt paint event — called whenever the widget needs to be redrawn.

        We override paintEvent() to add the FPS overlay on top of the
        standard QLabel content (the pixmap). The sequence is:
            1. Call super().paintEvent() to draw the pixmap normally.
            2. Draw the FPS text on top using QPainter.

        Why black shadow + white text?
            Pure white text (#FFFFFF) may disappear over light areas of the image
            (bright camera background, intense lighting). The black shadow offset
            by 1px creates a dark outline that makes the text readable on ANY
            background — a standard technique in game HUDs and video applications.

        Parameters:
            event: QPaintEvent provided automatically by Qt.
                   Contains the region that needs to be redrawn (rect()).
        """
        # First, let QLabel draw normally (the pixmap, alignment, background).
        # Without this call, the video frame disappears.
        super().paintEvent(event)

        # Only overlay the FPS if we have a valid value to display.
        if self._fps is None:
            return

        # Start the QPainter on this widget (not on the pixmap —
        # painting on the pixmap would be permanent; painting on the widget
        # is temporary and redrawn on each paintEvent).
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        # Format the text with one decimal place — "FPS: 28.7"
        fps_text: str = f"FPS: {self._fps:.1f}"

        # Bold font, size 13 — readable without taking up too much space.
        font = QFont("Segoe UI", 13, QFont.Weight.Bold)
        painter.setFont(font)

        # Text area: top-right corner with 10px margin.
        # QRect(x, y, width, height) — width 120 is enough for "FPS: XX.X"
        text_rect = QRect(self.width() - 130, 10, 120, 28)

        # --- Black shadow offset by 1 pixel ---
        # Shifting the text by (+1, +1) creates the illusion of a drop shadow.
        shadow_rect = QRect(text_rect.x() + 1, text_rect.y() + 1,
                            text_rect.width(), text_rect.height())
        painter.setPen(QPen(QColor("#000000")))
        painter.drawText(shadow_rect, Qt.AlignmentFlag.AlignRight, fps_text)

        # --- Main white text ---
        painter.setPen(QPen(QColor("#FFFFFF")))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignRight, fps_text)

        # Finalize the QPainter — MANDATORY to release the paint context.
        # Without end(), Qt may leave the paint device locked, causing
        # visual artifacts or crashes on older Qt versions.
        painter.end()

    # =========================================================================
    # NO SIGNAL STATE
    # =========================================================================

    def set_no_signal(self, message: str = "") -> None:
        """
        Places the widget in the "no camera signal" visual state.

        Called when:
        - The widget is initialized (before the camera is opened).
        - CameraWorker emits camera_error (camera disconnected, driver failed).
        - The session ends and the camera is released.

        Creates a black QPixmap with centered text explaining the situation,
        preventing the widget from appearing empty or showing stale content.

        Parameters:
            message: Optional error message from CameraWorker to display below
                     the default "No camera signal" text.
                     If empty, only the default message is displayed.
        """
        self._no_signal = True
        self._fps = None

        # Create a black pixmap of the current widget size.
        # If the widget does not yet have a defined size (e.g., before show()),
        # use the minimum size configured in __init__.
        w = max(self.width(), 480)
        h = max(self.height(), 360)

        # Create an empty (uninitialized) pixmap and fill it with black.
        no_signal_pixmap = QPixmap(w, h)
        no_signal_pixmap.fill(QColor("#0d1117"))

        # Start a QPainter on the pixmap to draw the text.
        painter = QPainter(no_signal_pixmap)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        # Main line: "📷 No camera signal"
        # Large font to be visible even with the window minimized.
        font_main = QFont("Segoe UI", 18, QFont.Weight.Bold)
        painter.setFont(font_main)
        painter.setPen(QPen(QColor("#64748b")))

        # Central area of the pixmap for the main text.
        main_rect = QRect(0, h // 2 - 40, w, 40)
        painter.drawText(
            main_rect,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            "No camera signal",
        )

        # Secondary instruction for the user.
        font_sub = QFont("Segoe UI", 12)
        painter.setFont(font_sub)
        painter.setPen(QPen(QColor("#334155")))

        sub_rect = QRect(0, h // 2 + 10, w, 30)
        painter.drawText(
            sub_rect,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            "Click Start Session to activate the camera",
        )

        # If there is a specific error message from CameraWorker, display it in red.
        if message:
            font_err = QFont("Consolas", 10)
            painter.setFont(font_err)
            painter.setPen(QPen(QColor("#ef4444")))

            err_rect = QRect(20, h // 2 + 50, w - 40, 50)
            painter.drawText(
                err_rect,
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
                | Qt.TextFlag.TextWordWrap,
                f"Error: {message}",
            )

        # Finalize the painter before using the pixmap.
        painter.end()

        # Display the "no signal" pixmap in the QLabel.
        self.setPixmap(no_signal_pixmap)

    # =========================================================================
    # RESPONSIVE RESIZING
    # =========================================================================

    def resizeEvent(self, event) -> None:
        """
        Called by Qt whenever the widget is resized by the user.

        We rescale the last displayed pixmap to fill the new widget size,
        maintaining the aspect ratio. Without this, the image would remain
        at the fixed size of the first received frame — when the window is
        resized, unnecessary black bars would appear or the image would be clipped.

        Parameters:
            event: QResizeEvent provided by Qt with the new size (newSize)
                   and the previous size (oldSize).
        """
        super().resizeEvent(event)

        # If in "no signal" state, recreate the error pixmap with the new size
        # to correctly fill the widget.
        if self._no_signal:
            self.set_no_signal()
            return

        # If a valid pixmap is displayed, rescale it to the new size.
        current_pixmap = self.pixmap()
        if current_pixmap and not current_pixmap.isNull():
            scaled = current_pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.setPixmap(scaled)
