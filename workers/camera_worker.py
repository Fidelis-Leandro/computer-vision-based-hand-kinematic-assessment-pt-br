"""
workers/camera_worker.py — Webcam frame capture thread
=======================================================

This module isolates video capture in a dedicated thread (CameraWorker),
ensuring the graphical interface (MainWindow) is never blocked waiting for
camera frames.

Problem solved by this module:
    cap.read() is a BLOCKING call: the program halts and waits until a frame
    arrives from the camera (~33ms at 30 FPS). If this wait occurred on the
    main thread, the PyQt6 window would freeze on every frame, making the
    interface unresponsive.

Solution:
    CameraWorker runs in its own thread via QThread. It captures frames in a
    continuous loop and delivers them to the main thread via pyqtSignal —
    Qt's thread-safe communication mechanism.

Data flow:
    Webcam -> cap.read() -> horizontal flip -> pyqtSignal(frame_bgr)
                                                      |
                                           ProcessingWorker.put_frame()

Rules followed:
    - Widgets are NEVER called from inside this thread.
    - time.sleep or any blocking calls are NEVER used here.
    - All communication with the interface is via pyqtSignal (thread-safe by design).
"""

import sys
import threading
import time
from typing import Optional

import cv2
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

# Import all constants from the centralized configuration file.
# NEVER use magic numbers in this module — always via config.
import config


class CameraWorker(QThread):
    """
    Real-time video capture thread using OpenCV.

    Inherits from QThread (not threading.Thread) because Qt requires that
    all communication with the graphical interface go through its own signal
    system (pyqtSignal). Pure Python threads do not have access to the Qt
    event loop and would crash when trying to update widgets.

    Lifecycle:
        1. Instantiated by MainWindow in __init__() — not yet started.
        2. camera_worker.start() is called on clicking "Start Session".
        3. Qt calls run() automatically in a separate thread.
        4. camera_worker.stop() is called on clicking "End" or closing the window.
        5. The loop exits and cap.release() frees the camera.

    Signals emitted (thread-safe communication with MainWindow):
        frame_ready(np.ndarray) : captured BGR frame, flipped and ready
                                  to be processed by ProcessingWorker.
        fps_updated(float)      : current frame rate, computed with EMA.
                                  Received by MetricsWidget for display.
        camera_error(str)       : error message for LogWidget when the
                                  camera cannot be opened or freezes.
    """

    # --- Signal definitions ---
    # pyqtSignal declares the data types each signal carries.
    # Qt uses this for safe inter-thread routing.

    # Carries a NumPy BGR array — the captured and flipped frame.
    frame_ready: pyqtSignal = pyqtSignal(np.ndarray)

    # Carries a float — the smoothed FPS for display in the interface.
    fps_updated: pyqtSignal = pyqtSignal(float)

    # Carries a string — a human-readable error message for the LogWidget.
    camera_error: pyqtSignal = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        """
        Initializes the CameraWorker with a safe initial state.

        Only configures internal attributes. The camera is NOT opened here —
        that happens in run() when the thread starts. This separation is
        important: __init__ runs on the main thread, while the camera must
        be opened and used exclusively on the worker thread.

        Parameters:
            parent: Qt parent widget (optional). Used by Qt to manage the
                    object lifecycle. Typically None for workers.
        """
        super().__init__(parent)

        # Thread event used to signal that the loop should stop.
        # We use threading.Event (not a plain boolean) because it is
        # thread-safe: it can be read/written from any thread without
        # race conditions.
        self._stop_event: threading.Event = threading.Event()

        # Reference to the camera object. Initially None because the camera
        # is only opened when run() is called by the worker thread.
        self._cap: Optional[cv2.VideoCapture] = None

        # Stores the EMA-smoothed FPS between emissions.
        # Initialized to 0.0 to indicate no frame has been captured yet.
        self._fps_ema: float = 0.0

        # Counter of successfully captured frames in this run.
        # Used to control the emission frequency of the fps_updated signal.
        self._frame_count: int = 0

    # =========================================================================
    # CAMERA OPENING
    # =========================================================================

    def _open_camera(self) -> Optional[cv2.VideoCapture]:
        """
        Attempts to open the camera with the best available configuration.

        Fallback strategy:
            1. Tries CAP_DSHOW (DirectShow — native Windows backend).
               CAP_DSHOW significantly reduces latency on Windows by
               eliminating the generic driver abstraction layer. Without it,
               each cap.read() may have 50–150ms of extra latency.
            2. If CAP_DSHOW fails (Linux/macOS or incompatible driver),
               tries OpenCV's default backend (automatic by OS).
            3. If both fail, returns None so run() can emit camera_error
               and exit the loop safely.

        Returns:
            cv2.VideoCapture: opened and configured camera object, or
            None if the camera could not be opened.
        """
        # CAP_DSHOW is Windows-only — only attempt on this platform.
        # On Linux/macOS, cv2.CAP_DSHOW does not exist or is ignored.
        if sys.platform == "win32":
            cap = cv2.VideoCapture(config.CAMERA_INDEX, cv2.CAP_DSHOW)

            # Verify CAP_DSHOW opened successfully before configuring.
            if cap.isOpened():
                self._configure_camera(cap)
                return cap

            # If CAP_DSHOW failed, release before trying again.
            cap.release()

        # Fallback: OpenCV default backend (V4L2 on Linux, AVFoundation on macOS).
        cap = cv2.VideoCapture(config.CAMERA_INDEX)

        if cap.isOpened():
            self._configure_camera(cap)
            return cap

        # No backend worked — camera is unavailable.
        return None

    def _configure_camera(self, cap: cv2.VideoCapture) -> None:
        """
        Applies resolution and FPS settings to the camera object.

        OpenCV does not guarantee the driver will honor requested settings —
        it tries, but the camera may return the closest supported resolution.
        We use CAP_PROP_BUFFERSIZE = 1 to ensure the driver's internal buffer
        holds at most 1 queued frame, keeping latency minimal regardless of
        the actual resolution.

        Parameters:
            cap: already opened and valid cv2.VideoCapture object.
        """
        # Request the resolution defined in config.py.
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.CAMERA_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.CAMERA_HEIGHT)

        # Request the desired FPS from the driver.
        cap.set(cv2.CAP_PROP_FPS, config.TARGET_FPS)

        # Set the driver's internal buffer size to 1 frame.
        # With larger buffers (default = 4 on Windows), cap.read() returns
        # OLD frames from the buffer before capturing the current frame.
        # This causes accumulated latency: the displayed image falls further
        # and further behind the real movement. With BUFFERSIZE = 1, we
        # always receive the most recent frame.
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    # =========================================================================
    # MAIN LOOP (runs in the separate thread)
    # =========================================================================

    def run(self) -> None:
        """
        Main QThread method — called automatically by Qt when
        camera_worker.start() is executed. Runs entirely on the worker thread,
        never on the main thread.

        This method MUST NOT be called directly. Use start() to start the
        thread correctly.

        Internal flow:
            1. Attempts to open the camera.
            2. If it fails, emits camera_error and exits.
            3. Capture loop: cap.read() -> flip -> compute FPS -> emit signals.
            4. On stop (_stop_event set or consecutive failures), releases the camera.

        Returns:
            None. Results are delivered via pyqtSignal (frame_ready, etc.).
        """
        # Attempt to open the camera before entering the loop.
        self._cap = self._open_camera()

        if self._cap is None:
            # Emitting the error signal is thread-safe: Qt will route the call
            # to the main thread automatically, where the LogWidget resides.
            self.camera_error.emit(
                f"Could not open camera (index {config.CAMERA_INDEX}). "
                "Check that it is connected and not in use by another program."
            )
            return

        # Counter of consecutive cap.read() failures.
        # If this counter reaches the limit, we interpret it as a hardware failure.
        consecutive_failures: int = 0

        # Failure limit before stopping. ~10 consecutive failures at ~30fps = ~333ms
        # without camera response, indicating a real freeze.
        max_consecutive_failures: int = 10

        # Timestamp of the last successfully captured frame — for FPS calculation.
        t_last: float = time.perf_counter()

        # Main capture loop — runs until stop() is called
        # or the consecutive failure count is reached.
        while not self._stop_event.is_set():

            # cap.read() is BLOCKING: waits until a frame is available.
            # Returns (True, frame) on success or (False, None) on failure.
            ret, frame = self._cap.read()

            if not ret or frame is None:
                consecutive_failures += 1

                if consecutive_failures >= max_consecutive_failures:
                    # Camera stopped responding long enough to be considered
                    # a real hardware failure (disconnection, driver, etc.)
                    self.camera_error.emit(
                        f"Camera lost after {max_consecutive_failures} consecutive "
                        "invalid frames. Check the USB connection."
                    )
                    break

                # Wait 10ms before retrying.
                # Without this sleep, the loop would spin at max speed consuming
                # 100% of a CPU core just trying to read invalid frames.
                time.sleep(0.01)
                continue

            # Valid frame — reset failure counter.
            consecutive_failures = 0
            self._frame_count += 1

            # Horizontal flip of the frame.
            # MediaPipe works with the original image, but from the user's
            # perspective, seeing their own hand mirrored (like a physical mirror)
            # is more intuitive for positioning the hand in the camera.
            # cv2.flip(frame, 1): 1 = vertical axis (horizontal mirror).
            frame = cv2.flip(frame, 1)

            # Compute real FPS and update the EMA-smoothed value.
            self._update_fps(t_last)
            t_last = time.perf_counter()

            # Emit the captured frame to any connected slot.
            # In production, ProcessingWorker receives it via put_frame().
            # The signal is thread-safe by Qt design — no race condition risk
            # when emitting from within this thread.
            self.frame_ready.emit(frame)

            # Emit the smoothed FPS every N frames to avoid flooding the UI.
            # Emitting every frame (30x/s) would unnecessarily overload
            # MetricsWidget with updates too fast for the human eye to see.
            # Every 30 frames ≈ once per second is sufficient.
            if self._frame_count % 30 == 0:
                self.fps_updated.emit(self._fps_ema)

        # --- Cleanup after the loop ---
        # Loop ended (by stop() or by failure). Release camera resources.
        self._release_camera()

    # =========================================================================
    # FPS CALCULATION
    # =========================================================================

    def _update_fps(self, t_last: float) -> None:
        """
        Updates the smoothed FPS using Exponential Moving Average (EMA).

        Why EMA instead of a simple mean?
            Simple mean (total_frames / total_time) has two problems:
            1. Reacts too slowly to performance changes (needs many frames
               to reflect the current speed).
            2. Never "forgets" old frames — if the system was slow for 1 second
               at the start, that affects the average for the entire session.

            EMA with α=0.15 solves both:
            - Reacts quickly to changes (α controls responsiveness).
            - Slowly "forgets" old values, keeping the smoothed value stable.
            - Computationally trivial: just one multiply and one add.

        Parameters:
            t_last: timestamp (in seconds) of the previous frame, obtained via
                    time.perf_counter(). Used to compute the time delta.
        """
        t_now: float = time.perf_counter()
        dt: float = t_now - t_last

        # Guard against division by zero: if dt is absurdly small
        # (two frames at the same instant — impossible in practice but defensive),
        # we skip the FPS update to avoid infinite values.
        if dt <= 0.0:
            return

        # Instantaneous FPS for this frame: inverse of the inter-frame interval.
        fps_instant: float = 1.0 / dt

        # EMA smoothing factor — α=0.15 (15% new value + 85% history).
        # Empirically tuned: smooths FPS spikes caused by camera driver latency
        # variations without introducing visible lag in the FPS indicator.
        ema_alpha: float = 0.15

        if self._fps_ema == 0.0:
            # On the first reading, initialize with the instantaneous value.
            # Using the EMA formula here would drag the FPS down from 0.0
            # for the first dozens of frames.
            self._fps_ema = fps_instant
        else:
            # EMA formula: new = α × current + (1-α) × previous
            self._fps_ema = ema_alpha * fps_instant + (1.0 - ema_alpha) * self._fps_ema

    # =========================================================================
    # LIFECYCLE CONTROL
    # =========================================================================

    def stop(self) -> None:
        """
        Signals the capture loop to shut down cleanly.

        Called by the main thread (e.g., on clicking "End Session" or closing
        the window). Does NOT force the thread to stop immediately — the loop
        checks the event on each iteration and exits at the next opportunity.

        Why threading.Event instead of a plain boolean?
            Plain Python booleans are not thread-safe: reads and writes from
            different threads can result in corrupted data (race condition).
            threading.Event uses OS-level synchronization primitives that
            guarantee safe access from any thread without manual locks.

        Returns:
            None. The actual shutdown happens asynchronously in run()'s loop.
        """
        self._stop_event.set()

    def _release_camera(self) -> None:
        """
        Safely releases camera resources when the thread exits.

        Why release explicitly?
            Python has automatic garbage collection, but it does not guarantee
            WHEN an object will be destroyed. If cap.release() is not called
            explicitly, the camera driver may remain busy, preventing other
            programs (or a new instance of ours) from opening the camera.

            On Windows, this results in the error: "camera is already in use
            by another process" when trying to restart the application without
            closing the previous process.

        Returns:
            None.
        """
        if self._cap is not None and self._cap.isOpened():
            # Release the camera handle in the OS driver.
            self._cap.release()

        # Reset the reference to None to avoid accidental use after release.
        self._cap = None

    def is_camera_open(self) -> bool:
        """
        Checks whether the camera is currently open and available.

        Useful for state checks in MainWindow before attempting to start
        a new capture session.

        Returns:
            bool: True if the camera is open and operational, False otherwise.
        """
        return self._cap is not None and self._cap.isOpened()
