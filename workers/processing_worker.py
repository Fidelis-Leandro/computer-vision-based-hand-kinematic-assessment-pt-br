"""
workers/processing_worker.py — Real-time goniometric processing thread
=======================================================================

This module implements the scientific core of the PyQt6 application: it receives
raw frames from the camera, executes the complete analysis pipeline, and delivers
results ready for the graphical interface — without ever blocking the main thread.

Problem solved by this module:
    The MediaPipe + angle calculation + filter smoothing pipeline is heavy:
    it can take 15ms to 50ms per frame depending on hardware. Running it on
    the main thread would make the PyQt6 window unresponsive during each analysis.

Solution:
    ProcessingWorker runs in its own QThread. It receives frames from CameraWorker
    via Queue(maxsize=1) and delivers results to MainWindow via pyqtSignal —
    never touching any widget directly.

Per-frame data pipeline:
    frame_bgr (np.ndarray)
        -> MediaPipe Hands                    [3D landmark detection]
        -> DigitalGoniometer.compute_all()    [raw angles per joint]
        -> GoniometryFilterBank.smooth_all()  [EMA -> Kalman, removes jitter]
        -> _build_skeleton()                  [BGR visual overlay]
        -> classify_hand_state()              [open/closed hand, ASSH]
        -> compute_realtime_metrics()         [velocity, frequency, regularity]
        -> ProcessingResult                   [dataclass bundling everything]
        -> pyqtSignal result_ready            [thread-safe delivery to MainWindow]

Rules followed:
    - Widgets are NEVER called here (violation causes silent crashes in Qt).
    - Scientific pipeline (goniometry.py, smoothing.py etc.) is never modified.
    - All numeric parameters come from config.py.
"""

import queue
import threading
import time
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional

import cv2
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

# Scientific modules — imported but NEVER modified.
from goniometry import DigitalGoniometer
from smoothing import GoniometryFilterBank
from goniometry_overlay import _build_skeleton
from goniometry_csv import GoniometryCSVLogger
from dashboard_utils import (
    FINGERS,
    FINGER_JOINTS,
    classify_hand_state,
    compute_realtime_metrics,
)

import config

try:
    import mediapipe as mp
except ImportError:
    raise ImportError(
        "MediaPipe not found. Run: pip install mediapipe\n"
        "This package is required for hand landmark detection."
    )


# =============================================================================
# RESULT DATACLASS
# =============================================================================

@dataclass
class ProcessingResult:
    """
    Data structure that bundles all results from ONE processed frame.

    This dataclass is the "delivery package" that ProcessingWorker assembles
    after executing the full pipeline and sends to MainWindow via pyqtSignal.
    MainWindow then distributes each field to the corresponding widget.

    Why a dataclass?
        Dataclasses are more readable than dictionaries (attribute access, not
        string keys), have explicit typing, and can be made immutable when needed.
        They also self-document the fields the pipeline produces.

    Fields:
        frame_overlay: NumPy BGR array with the camera frame + hand skeleton
                       drawn by _build_skeleton(). Sent to VideoWidget.

        angles_smooth: Dictionary {finger: {joint: smoothed_angle}} returned
                       by GoniometryFilterBank.smooth_all(). Contains MCP, PIP, DIP,
                       ABD and TAM for long fingers; MCP, IP and TAM for the thumb.

        hand_state: Dictionary returned by classify_hand_state(). Contains
                    finger_states (each finger's state), closed_count and hand_open.

        metrics_per_finger: {finger_name: metrics_dict} where each dict is the
                            output of compute_realtime_metrics() — rom,
                            mean velocity, peak velocity, frequency Hz,
                            coefficient of variation, and regularity.

        hand_detected: True if MediaPipe found a hand in this frame.
                       False if no hand was visible (frame skipped).

        frame_id: Sequential counter of frames processed in this session.
                  Used by MetricsWidget and logged in the CSV.

        fps: Processing frame rate in frames per second, computed by EMA.
             Reflects the REAL pipeline speed, not the camera speed.

        tam_buffers_snapshot: Thread-safe copy of the TAM circular buffers per
                              finger. Used by FingerCardWidgets for individual
                              mini-charts.
    """
    frame_overlay: np.ndarray
    angles_smooth: dict
    hand_state: dict
    metrics_per_finger: dict
    hand_detected: bool
    frame_id: int
    fps: float

    # TAM buffers snapshot — list[] is safe to copy outside the lock
    # because Python lists are copied by value with list().
    tam_buffers_snapshot: Dict[str, List[float]] = field(default_factory=dict)


# =============================================================================
# PROCESSING WORKER
# =============================================================================

class ProcessingWorker(QThread):
    """
    Goniometric processing thread — the scientific core of the application.

    Receives raw frames from CameraWorker, executes the full analysis pipeline,
    and emits results encapsulated in ProcessingResult to MainWindow.

    Internal architecture:
        Communication between CameraWorker and ProcessingWorker uses Queue(maxsize=1).

        Why Queue(maxsize=1) and not a list or deque?
            In real-time, we always want to process the MOST RECENT frame.
            With maxsize=1:
            - If the processor is busy when a new frame arrives, the old frame
              IN THE QUEUE is discarded and the new one takes its place.
            - This keeps latency always minimal, avoiding the "queued frames"
              problem: processing frames that are 2-3 seconds behind the real movement.
            - With an unbounded list or deque, frames would accumulate indefinitely,
              causing latency to grow until the system stalls.

    CSV session:
        The CSV is started by start_session() and closed by stop_session().
        The worker only writes to the CSV if a session is active — allowing
        the camera to be on without recording (READY state) before formal start.

    Signals emitted:
        result_ready(object): complete ProcessingResult for MainWindow.
                              Type 'object' because PyQt6 does not support
                              pyqtSignal(ProcessingResult) directly.
        processing_error(str): non-fatal error message for the LogWidget.
    """

    # Signal carrying the complete ProcessingResult.
    # We use 'object' as type because pyqtSignal does not support custom
    # dataclasses directly. MainWindow receives it as 'object' and casts.
    result_ready: pyqtSignal = pyqtSignal(object)

    # Non-fatal error signal (e.g., isolated corrupted frame).
    # Fatal errors (e.g., MediaPipe not installed) use raise ImportError.
    processing_error: pyqtSignal = pyqtSignal(str)

    # Emitted when the evaluated hand side changes and all internal
    # buffers have been reset. MainWindow connects this to clear
    # the plot widget's own display buffers.
    hand_side_reset: pyqtSignal = pyqtSignal()

    def __init__(self, parent=None) -> None:
        """
        Initializes ProcessingWorker with all pipeline components.

        Scientific objects (MediaPipe, DigitalGoniometer, etc.) are created
        here in __init__ because:
        1. Creation is lightweight (no camera I/O).
        2. __init__ runs on the main thread — good practice for detecting
           import errors (MediaPipe not installed) before starting the thread.
        3. Objects ARE used in run() (worker thread) — this is safe because
           only one thread (the worker) accesses them after start().

        Parameters:
            parent: Qt parent widget (optional). Typically None for workers.
        """
        super().__init__(parent)

        # Thread-safe stop event — same pattern as CameraWorker.
        self._stop_event: threading.Event = threading.Event()

        # Frame queue between CameraWorker -> ProcessingWorker.
        # maxsize=1: never accumulates old frames, always processes the most recent.
        self._frame_queue: queue.Queue = queue.Queue(maxsize=config.QUEUE_SIZE)

        # --- Scientific pipeline components ---

        # MediaPipe hand detector.
        # static_image_mode=False: video mode — reuses tracking between frames
        # (faster than detecting from scratch each frame).
        # max_num_hands=1: one hand at a time, sufficient for clinical goniometry.
        self._hands = mp.solutions.hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            min_detection_confidence=config.MP_DETECT_CONF,
            min_tracking_confidence=config.MP_TRACK_CONF,
        )

        # Digital goniometer — computes raw joint angles.
        self._gonio: DigitalGoniometer = DigitalGoniometer()

        # EMA -> Kalman filter bank — smooths raw angles.
        # One SeriesFilter instance per series (e.g., "INDEX_MCP", "THUMB_IP").
        self._filter_bank: GoniometryFilterBank = GoniometryFilterBank(
            ema_alpha=config.EMA_ALPHA,
            kalman_q=config.KALMAN_Q,
            kalman_r=config.KALMAN_R,
        )

        # --- Temporal circular buffers ---
        # One deque per finger to store the TAM history.
        # deque(maxlen=N) automatically discards the oldest value when full,
        # ensuring memory never grows beyond BUFFER_SIZE entries.
        self._tam_buffers: Dict[str, Deque[float]] = {
            finger: deque(maxlen=config.BUFFER_SIZE)
            for finger in FINGERS
        }

        # One deque per finger to store frame timestamps.
        # Used by compute_realtime_metrics() to calculate velocity (°/s)
        # and frequency (Hz) — quantities that depend on elapsed time.
        self._time_buffers: Dict[str, Deque[float]] = {
            finger: deque(maxlen=config.BUFFER_SIZE)
            for finger in FINGERS
        }

        # Counts consecutive frames without hand detection.
        # When it exceeds NO_HAND_RESET_FRAMES, filters are reset.
        self._no_hand_frames: int = 0

        # Total frame counter for this worker session.
        self._frame_id: int = 0

        # Processing pipeline FPS (EMA, same as CameraWorker).
        self._fps_ema: float = 0.0

        # Timestamp of the last successfully processed frame.
        self._t_last_frame: float = 0.0

        # --- CSV logger (inactive until start_session() is called) ---
        self._csv_logger: Optional[GoniometryCSVLogger] = None
        self._csv_path: str = ""
        self._session_active: bool = False

        # Lock protecting _session_active and _csv_logger.
        # MainWindow may call start_session()/stop_session() from outside
        # the worker thread, so we need synchronization.
        self._session_lock: threading.Lock = threading.Lock()

        # State for hand-side logic tracking
        self.current_hand_side: str = "Right"
        self.previous_hand_side: str = "Right"
        self._hand_side_lock: threading.Lock = threading.Lock()

    def set_evaluated_hand(self, side: str) -> None:
        """Updates the evaluated hand side ('Right' or 'Left') safely from UI."""
        side = side.strip().title()
        if side in ("Right", "Left"):
            with self._hand_side_lock:
                self.current_hand_side = side

    def _reset_for_hand_change(self) -> None:
        """Resets filters and temporal history when the evaluated hand side changes."""
        self._filter_bank.reset_all()
        for finger in FINGERS:
            self._tam_buffers[finger].clear()
            self._time_buffers[finger].clear()
        self.hand_side_reset.emit()
        logging.info("Evaluated hand changed. Filters and history reset.")

    def reset_state(self) -> None:
        """
        Resets the worker's internal state. Called when starting a New Session.
        Clears the frame queue, resets filters, and zeroes all numeric buffers.
        """
        # Empty the pending queue without blocking
        while not self._frame_queue.empty():
            try:
                self._frame_queue.get_nowait()
            except queue.Empty:
                break

        # Reset scientific state
        self._filter_bank.reset_all()

        # Clear historical measurements for all fingers
        for finger in FINGERS:
            self._tam_buffers[finger].clear()
            self._time_buffers[finger].clear()

        # Reset frame counters
        self._no_hand_frames = 0
        self._frame_id = 0
        self._fps_ema = 0.0

    # =========================================================================
    # INTERFACE WITH CameraWorker
    # =========================================================================

    def put_frame(self, frame: np.ndarray) -> None:
        """
        Receives a frame from CameraWorker and places it in the processing queue.

        Called by MainWindow when connecting the frame_ready signal from
        CameraWorker. Runs on the Qt thread (main or CameraWorker thread,
        depending on signal connection type).

        "Discard old, keep new" strategy:
            Queue.put_nowait() raises queue.Full if the queue is full.
            In that case, we remove the old frame with get_nowait() and insert
            the new one. This ensures the processor ALWAYS receives the most
            recent frame, keeping latency minimal regardless of processor speed.

        Parameters:
            frame: Flipped NumPy BGR array received directly from CameraWorker.
        """
        try:
            # Try non-blocking insert.
            self._frame_queue.put_nowait(frame)
        except queue.Full:
            # Queue is full (already has 1 frame waiting).
            # Remove the old unprocessed frame...
            try:
                self._frame_queue.get_nowait()
            except queue.Empty:
                # Extremely unlikely race condition: between put_nowait
                # failing and get_nowait executing, the worker emptied the queue.
                # No action needed — proceed normally.
                pass

            # ...and insert the most recent frame in its place.
            try:
                self._frame_queue.put_nowait(frame)
            except queue.Full:
                # Still full after removal — discard this frame.
                # Should not occur in practice, but handled defensively.
                pass

    # =========================================================================
    # MAIN LOOP (runs in the separate thread)
    # =========================================================================

    def run(self) -> None:
        """
        Main QThread method — called automatically by Qt when
        processing_worker.start() is executed. Runs entirely on the worker thread.

        This method MUST NOT be called directly. Use start().

        Flow:
            1. Wait for a frame in the queue with a 100ms timeout.
            2. If no frame arrived, check if we should stop and go to step 1.
            3. Execute the full pipeline (MediaPipe -> angles -> filters -> metrics).
            4. Build ProcessingResult and emit result_ready.
            5. Repeat until stop() is called.
        """
        while not self._stop_event.is_set():

            # Wait for a frame with 100ms timeout.
            # Timeout is necessary so the loop can check _stop_event
            # even without receiving frames (e.g., camera paused).
            try:
                frame_bgr = self._frame_queue.get(timeout=0.1)
            except queue.Empty:
                # No frame available within timeout — loop back to
                # check _stop_event before waiting again.
                continue

            # Frame received — execute the full pipeline.
            try:
                self._process_frame(frame_bgr)
            except Exception as exc:
                # Catch non-fatal errors (e.g., isolated corrupted frame).
                # Do not interrupt the thread — just log and continue.
                self.processing_error.emit(
                    f"Error processing frame #{self._frame_id}: {exc}"
                )

        # Loop ended — release MediaPipe resources.
        self._cleanup()

    def _process_frame(self, frame_bgr: np.ndarray) -> None:
        """
        Executes the complete goniometric pipeline on a single BGR frame.

        This function orchestrates all scientific modules in sequence.
        The order of steps is deterministic and cannot be changed — each
        step depends on the output of the previous one.

        Parameters:
            frame_bgr: NumPy array of shape (height, width, 3), BGR format,
                       with the frame already horizontally flipped by CameraWorker.
        """
        self._frame_id += 1
        t_now: float = time.monotonic()

        # Compute pipeline processing FPS.
        self._update_fps(t_now)
        self._t_last_frame = t_now

        # --- Step 1: MediaPipe Hands ---
        # Convert BGR -> RGB because MediaPipe expects RGB images.
        # OpenCV uses BGR by historical convention from DirectShow on Windows.
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

        # Mark as non-writable for optimization: MediaPipe can reference
        # the array memory directly without copying, saving ~2-5ms per frame.
        frame_rgb.flags.writeable = False
        results = self._hands.process(frame_rgb)
        frame_rgb.flags.writeable = True

        # Check if MediaPipe detected at least one hand in the frame.
        hand_detected: bool = results.multi_hand_landmarks is not None

        if not hand_detected:
            # No hand visible in this frame.
            self._no_hand_frames += 1
            self._handle_no_hand(frame_bgr)
            return

        # --- Step 2: Hand identification (handedness) ---
        # The hand side is controlled explicitly by the UI. 
        # This prevents issues with MediaPipe guessing incorrectly 
        # when dealing with mirrored cameras and front-facing poses.
        with self._hand_side_lock:
            local_hand_side = self.current_hand_side
            
        if local_hand_side != self.previous_hand_side:
            self._reset_for_hand_change()
            self.previous_hand_side = local_hand_side
            
        is_right_hand: bool = (local_hand_side == "Right")

        # --- Step 3: Raw angle calculation ---
        # compute_all() receives the 21 normalized 3D landmarks (coordinates 0.0-1.0)
        # and returns a dict {finger: {joint: angle_in_degrees}}.
        landmarks = results.multi_hand_landmarks[0].landmark
        angles_raw: dict = self._gonio.compute_all(landmarks, is_right_hand=is_right_hand)

        # --- Step 4: EMA -> Kalman smoothing ---
        # Why does the order EMA BEFORE Kalman matter?
        #   EMA removes HIGH-FREQUENCY noise (frame-to-frame jitter from MediaPipe).
        #   Kalman removes LOW-FREQUENCY noise (slow drift, fine tremor).
        #   If we reversed the order (Kalman -> EMA), the Kalman would receive
        #   high-frequency noise directly, losing efficiency as an estimator of
        #   the "true" angle value. The EMA->Kalman combination produces angles
        #   smooth at both high and low frequencies.
        angles_smooth: dict = self._filter_bank.smooth_all(angles_raw)

        # Valid frame with hand detected — reset no-hand counter.
        self._no_hand_frames = 0

        # --- Step 5: Temporal buffer update ---
        # Store TAM and timestamp for each finger for metrics calculation.
        self._update_buffers(angles_smooth, t_now)

        # --- Step 6: Visual overlay generation ---
        # Why does _build_skeleton() run here (in the worker) and not in the UI?
        #   The overlay involves heavy OpenCV drawing operations:
        #   skeleton lines, landmark circles, angular arcs, and text with angle values.
        #   Doing this on the main thread would block the interface for ~5-15ms per frame.
        #   Here in the worker, the overhead is "hidden" behind MediaPipe's processing
        #   time, with no perceptible impact on the UI.
        #
        # Stability map: informs the overlay the color of each joint
        # (green=stable, yellow=converging, blue=unstable), derived from the
        # current Kalman gain of each filter.
        stability_map: dict = {
            finger: {
                joint: self._filter_bank.get_stability(finger, joint)
                for joint in angles_smooth.get(finger, {}).keys()
            }
            for finger in FINGERS
            if finger in angles_smooth
        }

        # _build_skeleton() generates only the panel with the hand skeleton.
        frame_overlay: np.ndarray = _build_skeleton(
            frame=frame_bgr,
            landmarks=landmarks,
            angles=angles_smooth,
            pw=config.CAMERA_WIDTH,
            ph=config.CAMERA_HEIGHT,
            frozen=False,
            stability_map=stability_map,
        )

        # --- Step 7: Hand state classification ---
        hand_state: dict = classify_hand_state(angles_smooth)

        # --- Step 8: Per-finger metrics calculation ---
        metrics_per_finger: dict = {}
        for finger in FINGERS:
            tam_buf = list(self._tam_buffers[finger])
            time_buf = list(self._time_buffers[finger])

            # Need at least 2 points to compute velocity and frequency.
            if len(tam_buf) >= 2 and len(tam_buf) == len(time_buf):
                metrics_per_finger[finger] = compute_realtime_metrics(
                    angle_buffer=tam_buf,
                    time_buffer=time_buf,
                )
            else:
                # Insufficient data — return zeroed metrics to avoid
                # displaying NaN or errors in the interface.
                metrics_per_finger[finger] = {
                    "rom": 0.0,
                    "vel_media": 0.0,
                    "vel_pico": 0.0,
                    "freq_hz": 0.0,
                    "cv": 0.0,
                    "regularidade": "—",
                    "n_picos": 0,
                }

        # --- Step 9: TAM buffer snapshot for mini-charts ---
        # Convert from deque to list() to create an independent copy.
        # A copy is necessary because the original deque continues to be
        # modified by the worker while MainWindow distributes the data.
        tam_snapshot: Dict[str, List[float]] = {
            finger: list(self._tam_buffers[finger])
            for finger in FINGERS
        }

        # --- Step 10: Bundle and emit result ---
        result = ProcessingResult(
            frame_overlay=frame_overlay,
            angles_smooth=angles_smooth,
            hand_state=hand_state,
            metrics_per_finger=metrics_per_finger,
            hand_detected=True,
            frame_id=self._frame_id,
            fps=self._fps_ema,
            tam_buffers_snapshot=tam_snapshot,
        )

        # Emit result to MainWindow via thread-safe signal.
        # Qt guarantees the receiving slot (on the main thread) is only
        # invoked when the main thread is ready to process it.
        self.result_ready.emit(result)

        # --- Step 11: CSV logging (only if session is active) ---
        # Log every CSV_LOG_INTERVAL frames to reduce disk I/O.
        if self._frame_id % config.CSV_LOG_INTERVAL == 0:
            self._try_log_csv(angles_smooth)

    def _handle_no_hand(self, frame_bgr: np.ndarray) -> None:
        """
        Handles the case where no hand was detected in the current frame.

        Two main behaviors:
        1. After NO_HAND_RESET_FRAMES frames without a hand, reset Kalman filters.
           Without this reset, when the hand returns, the filter would try to
           "converge" from the old position to the new one, causing erroneous angles
           in the first frames (false transient). The reset ensures the first detection
           after a long absence is treated as an "initial state".

        2. Emits a ProcessingResult with hand_detected=False and the original frame.
           This allows MainWindow to clear the interface (e.g., VideoWidget
           displays the frame without overlay, MetricsWidget clears values).

        Parameters:
            frame_bgr: Original BGR frame, without overlay, for UI display.
        """
        # Reset filters only after prolonged absence to avoid unnecessary resets
        # due to momentary finger occlusions.
        if self._no_hand_frames >= config.NO_HAND_RESET_FRAMES:
            self._filter_bank.reset_all()
            self._no_hand_frames = 0

        # Emit result indicating no hand for the UI.
        result = ProcessingResult(
            frame_overlay=frame_bgr.copy(),
            angles_smooth={},
            hand_state={"finger_states": {}, "closed_count": 0, "hand_open": True},
            metrics_per_finger={},
            hand_detected=False,
            frame_id=self._frame_id,
            fps=self._fps_ema,
            tam_buffers_snapshot={f: [] for f in FINGERS},
        )
        self.result_ready.emit(result)

    # =========================================================================
    # TEMPORAL BUFFERS
    # =========================================================================

    def _update_buffers(self, angles_smooth: dict, timestamp: float) -> None:
        """
        Updates the TAM and timestamp circular buffers for each finger.

        Buffers are maintained by the worker and updated frame by frame.
        They accumulate a history of the BUFFER_SIZE most recent entries,
        used by compute_realtime_metrics() to calculate sliding-window metrics
        (rom, velocity, frequency).

        Parameters:
            angles_smooth: Dictionary with smoothed angles for all fingers.
            timestamp: Current time in seconds (time.monotonic()) — same origin
                       for all fingers in the same frame.
        """
        for finger in FINGERS:
            finger_data = angles_smooth.get(finger, {})

            # Extract TAM (Total Active Motion) for the finger.
            # TAM is the most important clinical metric: it represents the total
            # active movement rom of all joints of a finger combined.
            tam_value: float = float(finger_data.get("TAM", 0.0))

            # Only add to buffer if the value is valid (> 0).
            # TAM = 0.0 usually indicates a frame without detection or absent joint,
            # not a real angle — including zeros would distort rom and frequency
            # metrics calculated from this buffer.
            if tam_value > 0.0:
                self._tam_buffers[finger].append(tam_value)
                self._time_buffers[finger].append(timestamp)

    def get_tam_buffers(self) -> Dict[str, List[float]]:
        """
        Returns a thread-safe copy of the current TAM buffers.

        Used by MainWindow to feed the mini-charts of FingerCardWidgets.
        Returns copies (list()) instead of the original deques so the
        caller does not need additional synchronization.

        Returns:
            Dict mapping finger name (e.g., "INDEX") to a list of floats
            with the TAM values of the last BUFFER_SIZE valid frames.
        """
        return {
            finger: list(self._tam_buffers[finger])
            for finger in FINGERS
        }

    # =========================================================================
    # PIPELINE FPS CALCULATION
    # =========================================================================

    def _update_fps(self, t_now: float) -> None:
        """
        Updates the processing pipeline FPS using EMA.

        Pipeline FPS != camera FPS.
        The camera may capture at 30 FPS, but processing can be slower
        (e.g., 20 FPS on a slow CPU) or faster (e.g., 25 FPS if the camera
        occasionally drops frames). This method measures the REAL processing speed.

        Parameters:
            t_now: Current timestamp in seconds (time.monotonic()).
                   Compared with the previous frame's timestamp to compute dt.
        """
        if self._t_last_frame <= 0.0:
            # First frame — no previous reference to compute interval.
            return

        dt: float = t_now - self._t_last_frame

        # Guard against zero dt (two frames processed at the same instant).
        if dt <= 0.0:
            return

        fps_instant: float = 1.0 / dt

        # EMA with α=0.15 — same value as CameraWorker for consistency.
        ema_alpha: float = 0.15

        if self._fps_ema == 0.0:
            self._fps_ema = fps_instant
        else:
            self._fps_ema = ema_alpha * fps_instant + (1.0 - ema_alpha) * self._fps_ema

    # =========================================================================
    # CSV SESSION MANAGEMENT
    # =========================================================================

    def start_session(self, csv_path: str) -> None:
        """
        Starts a new CSV recording session.

        Called by MainWindow on clicking "Start Session", BEFORE start().
        Creates the GoniometryCSVLogger that will record angles each frame.

        The _session_lock protects _csv_logger and _session_active because
        this method is called from the main thread while the worker may be
        reading _session_active in the run() loop. Without the lock, there
        would be a race condition.

        Parameters:
            csv_path: Full path of the CSV file to create/open.
                      Example: "session_goniometry_20260623_143512.csv"
        """
        with self._session_lock:
            # Close any previously open session.
            if self._csv_logger is not None:
                self._csv_logger.close()

            self._csv_path = csv_path
            self._csv_logger = GoniometryCSVLogger(csv_path)
            self._session_active = True

    def stop_session(self) -> None:
        """
        Safely ends the CSV recording session.

        Called by MainWindow on clicking "End Session". Ensures all pending
        data in the logger's buffer is written to disk (flush) before closing
        the file.

        Why flush() before close()?
            Python uses write buffers for performance: data is kept in memory
            and written in batches. If the file is closed without flush(),
            buffered data may be lost (especially on a subsequent crash).
            flush() forces immediate write to disk.
        """
        with self._session_lock:
            if self._csv_logger is not None:
                self._csv_logger.flush()
                self._csv_logger.close()
                self._csv_logger = None
            self._session_active = False

    def _try_log_csv(self, angles_smooth: dict) -> None:
        """
        Attempts to log the current frame to the CSV, if a session is active.

        Runs inside the run() loop (worker thread). Uses the same lock as
        start_session() and stop_session() for thread-safe access.

        The _session_active check is done inside the lock to avoid the
        "check-then-act" race condition: without the lock, _session_active
        could be True when checked, but _csv_logger could be closed (None)
        by stop_session() before reaching csv_logger.log().

        Parameters:
            angles_smooth: Dictionary of smoothed angles for the current frame.
        """
        with self._session_lock:
            if self._session_active and self._csv_logger is not None:
                self._csv_logger.log(self._frame_id, angles_smooth)

                # Flush every 60 frames to reduce I/O without risk of data loss.
                if self._frame_id % 60 == 0:
                    self._csv_logger.flush()

    # =========================================================================
    # LIFECYCLE CONTROL
    # =========================================================================

    def stop(self) -> None:
        """
        Signals the processing loop to shut down cleanly.

        Called by MainWindow in closeEvent() or on clicking "End Session".
        Does not force immediate shutdown — the loop finishes the current frame
        and then checks _stop_event on the next iteration.

        Returns:
            None. The actual shutdown is asynchronous — use wait() to block.
        """
        self._stop_event.set()

    def _cleanup(self) -> None:
        """
        Releases all pipeline resources after the loop ends.

        Called automatically at the end of run() when the loop exits.
        Ensures MediaPipe releases GPU/CPU memory and the CSV is closed.

        Why close MediaPipe explicitly?
            mp.solutions.hands.Hands maintains TensorFlow Lite resources internally.
            Without close(), these resources may persist until Python's GC collects
            the object — which may never happen until the process terminates, causing
            memory leaks in long-running sessions.
        """
        # Close the MediaPipe detector and release ML model resources.
        if self._hands is not None:
            self._hands.close()

        # Ensure the CSV is closed even if stop_session() was not explicitly
        # called (e.g., crash or abrupt window close).
        self.stop_session()
