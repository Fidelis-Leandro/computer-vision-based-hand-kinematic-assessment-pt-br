"""
config.py — Centralized system configuration for Digital Hand Goniometry
=========================================================================

This file is the single source of truth for all numeric parameters and
configuration constants. No magic numbers should appear scattered throughout
the rest of the codebase.

Design philosophy:
    In real-time systems like this one, changing a parameter in one place
    and having it propagate to all modules is fundamental for maintenance
    and calibration. Without this file, values would need to be tracked
    and replaced across multiple files, which inevitably causes
    inconsistencies.

Configuration categories:
    1. Camera and video capture
    2. Smoothing pipeline (EMA -> Kalman)
    3. Hand detection (MediaPipe)
    4. Graphical interface (PyQt6 / PyQtGraph)
    5. Session recording (CSV)
    6. Clinical finger mapping
    7. Logging system
    8. Main window
"""

# =============================================================================
# 1. CAMERA AND VIDEO CAPTURE
# =============================================================================

# Camera index in the operating system.
# 0 = default camera (usually the built-in webcam).
# If multiple cameras are available, change to 1, 2, etc.
CAMERA_INDEX: int = 0

# Target camera resolution.
# 1280x720 (HD) provides good quality for landmark tracking,
# but consumes more CPU than 640x480. Adjust if the machine is slow.
CAMERA_WIDTH: int = 1280
CAMERA_HEIGHT: int = 720

# Target frames per second requested from the camera driver.
# The driver may not honor this value exactly — the actual FPS
# is measured and displayed in real time by CameraWorker.
TARGET_FPS: int = 30

# =============================================================================
# 2. SMOOTHING PIPELINE (EMA -> KALMAN)
# =============================================================================

# Exponential Moving Average (EMA) smoothing factor.
# Value between 0 and 1: higher values make the filter react faster to motion
# but reduce smoothing. Lower values produce smoother output with more lag.
# 0.30 was calibrated experimentally for clinical real-time goniometry:
# smooths camera tremor without introducing perceptible lag in slow movements.
EMA_ALPHA: float = 0.30

# Scalar Kalman Filter parameters.
#
# KALMAN_Q (process noise): represents uncertainty in the motion model.
# A small value (0.01) assumes the joint angle changes slowly and smoothly.
# Increasing Q makes the filter react faster to sudden changes.
KALMAN_Q: float = 0.01

# KALMAN_R (measurement noise): represents uncertainty in landmark readings.
# 0.10 indicates moderate trust in the position detected by MediaPipe.
# Increasing R makes the filter trust the measurement less and rely more
# on the previous estimate.
KALMAN_R: float = 0.10

# =============================================================================
# 3. HAND DETECTION (MEDIAPIPE HANDS)
# =============================================================================

# Minimum confidence for DETECTING a hand from scratch.
# A higher value (0.70) reduces false positives but may miss detections
# under poor lighting. Adjust between 0.5 and 0.9.
MP_DETECT_CONF: float = 0.70

# Minimum confidence for TRACKING an already-detected hand between frames.
# Can be lower than MP_DETECT_CONF because tracking is easier than detecting.
# 0.50 keeps tracking smooth even with partial finger occlusions.
MP_TRACK_CONF: float = 0.50

# Number of consecutive frames without hand detection before resetting filters.
# At 30 FPS, 15 frames ≈ 500ms. This prevents the Kalman filter from
# "remembering" a previous position when the hand returns after a long occlusion.
NO_HAND_RESET_FRAMES: int = 15

# =============================================================================
# 4. GRAPHICAL INTERFACE (PyQt6 / PyQtGraph)
# =============================================================================

# Circular buffer size for real-time charts (PyQtGraph).
# 500 points at ~30 FPS = approximately 16 seconds of visible history.
# Using deque(maxlen=BUFFER_SIZE) ensures memory does not grow indefinitely.
BUFFER_SIZE: int = 500

# Maximum queue size between CameraWorker and ProcessingWorker.
# MUST always be 1 in real-time systems. With maxsize=1:
# - If the queue is full, the old frame is discarded.
# - The processor ALWAYS receives the most recent frame.
# - Latency remains minimal, even if processing is temporarily slow.
QUEUE_SIZE: int = 1

# Interval in milliseconds for the QTimer that updates PyQtGraph charts.
# 33ms ≈ 30 FPS visual update rate — smooth to the human eye.
# Increasing this value reduces CPU usage; decreasing makes the UI more fluid.
PANEL_REFRESH_MS: int = 33

# Number of frames between goniometric overlay recalculations.
# Drawing the skeleton and angles is costly. With OVERLAY_FRAME_INTERVAL = 3,
# the overlay updates every 3 frames, saving ~67% of drawing cost
# without a perceptible visual impact (the human eye cannot distinguish
# such rapid differences).
OVERLAY_FRAME_INTERVAL: int = 3

# =============================================================================
# 5. SESSION RECORDING (CSV)
# =============================================================================

# Number of frames between CSV angle recordings.
# CSV_LOG_INTERVAL = 3 with TARGET_FPS = 30 yields ~10 rows/second,
# sufficient for clinical analysis without generating excessively large files.
CSV_LOG_INTERVAL: int = 3

# =============================================================================
# 6. CLINICAL FINGER MAPPING
# =============================================================================

# Processing order for fingers — must remain consistent across all modules
# to avoid indexing bugs.
# THUMB is listed last due to its different anatomy
# (only MCP and IP joints, no DIP or ABD).
FINGERS: list[str] = ["INDEX", "MIDDLE", "RING", "PINKY", "THUMB"]

# Mapping of technical English names to clinical display labels.
# Used in the graphical interface to show readable labels to healthcare professionals.
FINGER_NAMES: dict[str, str] = {
    "INDEX":  "Index",
    "MIDDLE": "Middle",
    "RING":   "Ring",
    "PINKY":  "Little",
    "THUMB":  "Thumb",
}

# Hexadecimal colors for each finger in PyQtGraph charts.
# Colors were chosen for high contrast against the dark background
# and adequate distinction for users with partial color blindness
# (avoids pure red/green combinations).
FINGER_COLORS: dict[str, str] = {
    "INDEX":  "#38bdf8",   # Sky blue    — Index
    "MIDDLE": "#4ade80",   # Light green — Middle
    "RING":   "#facc15",   # Golden yellow — Ring
    "PINKY":  "#f87171",   # Salmon red  — Little
    "THUMB":  "#c084fc",   # Light purple — Thumb
}

# Colors for each finger in (R, G, B) format with values 0–255.
# Used by PyQtGraph to define curve plot colors,
# as PyQtGraph accepts both hex strings and RGB tuples.
FINGER_COLORS_RGB: dict[str, tuple[int, int, int]] = {
    "INDEX":  (56, 189, 248),
    "MIDDLE": (74, 222, 128),
    "RING":   (250, 204, 21),
    "PINKY":  (248, 113, 113),
    "THUMB":  (192, 132, 252),
}

# Biomechanical TAM ceiling per finger (degrees).
# Values derived from ASSH reference ranges and anatomical literature.
# Applied as a hard clamp after EMA + Kalman filtering to prevent
# camera-noise artifacts from producing physically impossible readings.
TAM_CEILING: dict[str, float] = {
    "INDEX":  270.0,
    "MIDDLE": 270.0,
    "RING":   270.0,
    "PINKY":  270.0,
    "THUMB":  130.0,
}

# =============================================================================
# 7. LOGGING SYSTEM
# =============================================================================

# Directory where the application log file will be saved.
# Created automatically if it does not exist (see app_pyqt.py).
LOG_DIR: str = "logs"

# Application log filename.
# Separate from the session CSV — this file contains system events,
# errors, and initialization information, not clinical data.
LOG_FILENAME: str = "app.log"

# Log message format.
# Includes: date/time, level (INFO/WARNING/ERROR), module name, and message.
# Helps trace which module generated each event during debugging.
LOG_FORMAT: str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

# =============================================================================
# 8. MAIN WINDOW
# =============================================================================

# Title displayed in the operating system's window title bar.
APP_TITLE: str = "Digital Hand Goniometry"

# Minimum main window size in pixels (width x height).
# Ensures all widgets remain visible even on smaller monitors.
WINDOW_MIN_WIDTH: int = 1280
WINDOW_MIN_HEIGHT: int = 800
