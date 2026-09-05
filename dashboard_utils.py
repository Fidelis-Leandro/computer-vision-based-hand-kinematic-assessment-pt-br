"""
dashboard_utils.py — Clinical utilities for the real-time dashboard
====================================================================

Pure functions for:
- classifying the global hand state;
- computing sliding-window metrics per finger;
- classifying TAM by functional ranges;
- formatting frequency and regularity for display.

Notes:
- this module has no UI framework dependencies;
- all metrics are computed over temporal buffers;
- does not compute frame-by-frame clinical indicators in isolation.
"""

from __future__ import annotations

from collections import deque
from typing import Deque, Dict, List, Optional, Sequence, Tuple
import math
import statistics


FINGERS = ["INDEX", "MIDDLE", "RING", "PINKY", "THUMB"]
JOINTS = ["MCP", "PIP", "DIP", "ABD", "TAM"]

# Valid joints per finger — centralized source of truth.
# The thumb has a different anatomy: only MCP and IP.
# All other fingers: MCP, PIP, DIP, ABD, TAM.
FINGER_JOINTS: Dict[str, Tuple[str, ...]] = {
    "INDEX":  ("MCP", "PIP", "DIP", "ABD", "TAM"),
    "MIDDLE": ("MCP", "PIP", "DIP", "ABD", "TAM"),
    "RING":   ("MCP", "PIP", "DIP", "ABD", "TAM"),
    "PINKY":  ("MCP", "PIP", "DIP", "ABD", "TAM"),
    "THUMB":  ("MCP", "IP", "TAM"),
}


# =============================================================================
# TAM FUNCTIONAL CLASSIFICATION / ASSH
# =============================================================================

def assh_classify(tam: float) -> Tuple[str, str]:
    """
    Classifies TAM by functional range (long fingers).

    Returns:
        (label, color_hex)

    Ranges:
    - >= 260° : Excellent
    - 195–259°: Good
    - 130–194°: Fair
    - < 130°  : Poor
    """
    if tam >= 260.0:
        return "Excellent", "#22c55e"
    if tam >= 195.0:
        return "Good", "#eab308"
    if tam >= 130.0:
        return "Fair", "#f97316"
    return "Poor", "#ef4444"


def assh_classify_thumb(tam: float) -> Tuple[str, str]:
    """
    Classifies thumb TAM by adapted functional ranges.

    The thumb has a maximum anatomical TAM of ~120–130° (MCP + IP),
    so ASSH ranges are proportionally smaller.

    Returns:
        (label, color_hex)

    Ranges:
    - >= 110° : Excellent
    - 80–109° : Good
    - 50–79°  : Fair
    - < 50°   : Poor
    """
    if tam >= 110.0:
        return "Excellent", "#22c55e"
    if tam >= 80.0:
        return "Good", "#eab308"
    if tam >= 50.0:
        return "Fair", "#f97316"
    return "Poor", "#ef4444"


def tam_progress(tam: float, max_tam: float = 270.0) -> float:
    """
    Normalizes TAM to a progress bar value between 0 and 1.
    """
    if max_tam <= 0:
        return 0.0
    return max(0.0, min(1.0, tam / max_tam))


# =============================================================================
# GLOBAL HAND STATE
# =============================================================================

def classify_hand_state(angles_smooth: Dict[str, Dict[str, float]]) -> Dict:
    """
    Classifies the hand state based on the current TAM of each finger.

    Clinical rules:
    - Long fingers (INDEX, MIDDLE, RING, PINKY): closed if TAM >= 130 degrees.
    - Thumb (THUMB): closed if MCP + IP >= 80 degrees (total rom proxy).
    - Hand closed if >= 4 of 5 fingers are closed.

    Returns:
    {
        "finger_states": {
            "INDEX": {
                "MCP": float,
                "PIP": float,
                "DIP": float,
                "ABD": float,
                "TAM": float,
                "closed": bool,
                "assh_label": str,
                "assh_color": str,
            },
            "THUMB": {
                "MCP": float,
                "IP": float,
                "TAM": float,   # proxy: MCP + IP
                "closed": bool,
                "assh_label": str,
                "assh_color": str,
            },
            ...
        },
        "closed_count": int,
        "hand_open": bool,
    }
    """
    finger_states: Dict[str, Dict[str, float]] = {}
    closed_count = 0

    for finger in FINGERS:
        finger_data = angles_smooth.get(finger, {})

        if finger == "THUMB":
            mcp = float(finger_data.get("MCP", 0.0))
            ip  = float(finger_data.get("IP", 0.0))
            tam = float(finger_data.get("TAM", 0.0))
            # Closed threshold proportional to the maximum thumb TAM (~120°).
            closed = tam >= 85.0
            if closed:
                closed_count += 1
            assh_label, assh_color = assh_classify_thumb(tam)
            finger_states[finger] = {
                "MCP": mcp,
                "IP": ip,
                "TAM": tam,
                "closed": closed,
                "assh_label": assh_label,
                "assh_color": assh_color,
            }
        else:
            mcp = float(finger_data.get("MCP", 0.0))
            pip = float(finger_data.get("PIP", 0.0))
            dip = float(finger_data.get("DIP", 0.0))
            abd = float(finger_data.get("ABD", 0.0))
            tam = float(finger_data.get("TAM", 0.0))

            closed = tam >= 130.0
            if closed:
                closed_count += 1

            assh_label, assh_color = assh_classify(tam)

            finger_states[finger] = {
                "MCP": mcp,
                "PIP": pip,
                "DIP": dip,
                "ABD": abd,
                "TAM": tam,
                "closed": closed,
                "assh_label": assh_label,
                "assh_color": assh_color,
            }

    hand_open = closed_count < 4

    return {
        "finger_states": finger_states,
        "closed_count": closed_count,
        "hand_open": hand_open,
    }


# =============================================================================
# PEAK DETECTION
# =============================================================================

def _safe_mean(values: Sequence[float], default: float = 0.0) -> float:
    if not values:
        return default
    return float(statistics.mean(values))


def _safe_std(values: Sequence[float], default: float = 0.0) -> float:
    if len(values) < 2:
        return default
    return float(statistics.pstdev(values))


def _estimate_fps(time_values: Sequence[float]) -> float:
    """
    Estimates average FPS from the buffer timestamps.
    """
    if len(time_values) < 2:
        return 0.0

    dts = []
    for i in range(1, len(time_values)):
        dt = time_values[i] - time_values[i - 1]
        if dt > 1e-6:
            dts.append(dt)

    if not dts:
        return 0.0

    mean_dt = _safe_mean(dts, default=0.0)
    if mean_dt <= 1e-6:
        return 0.0

    return 1.0 / mean_dt


def _detect_peaks(
    angle_values: Sequence[float],
    time_values: Sequence[float],
    min_range_pct: float = 0.30,
    min_dist_s: float = 1.0,
) -> List[int]:
    """
    Detects local peaks (maxima) in a sliding window.

    Criteria:
    - Local maximum with plateau tolerance: curr >= prev AND curr > next
      (the previous criterion curr > prev AND curr >= next failed when the
       smoothed signal produced plateaus, marking the peak at the wrong edge).
    - Peak value above a threshold relative to the local range:
        threshold = min(angle) + min_range_pct * (max(angle) - min(angle))
    - Minimum distance between peaks in seconds, converted to samples.

    Returns:
        List of indices of detected peaks.
    """
    n = len(angle_values)
    if n < 3 or len(time_values) != n:
        return []

    min_val = min(angle_values)
    max_val = max(angle_values)
    rom = max_val - min_val

    if rom <= 1e-6:
        return []

    threshold = min_val + min_range_pct * rom

    fps_est = _estimate_fps(time_values)
    if fps_est <= 0:
        min_dist_samples = 1
    else:
        min_dist_samples = max(1, int(round(min_dist_s * fps_est)))

    candidate_peaks: List[int] = []
    for i in range(1, n - 1):
        prev_v = angle_values[i - 1]
        curr_v = angle_values[i]
        next_v = angle_values[i + 1]

        # Plateau tolerance: accepts curr == prev, but requires curr > next.
        # This ensures the first point of a plateau is accepted as a peak.
        is_local_peak = (curr_v >= prev_v) and (curr_v > next_v)
        if is_local_peak and curr_v >= threshold:
            candidate_peaks.append(i)

    if not candidate_peaks:
        return []

    filtered_peaks: List[int] = [candidate_peaks[0]]
    for idx in candidate_peaks[1:]:
        last_idx = filtered_peaks[-1]
        if idx - last_idx < min_dist_samples:
            if angle_values[idx] > angle_values[last_idx]:
                filtered_peaks[-1] = idx
        else:
            filtered_peaks.append(idx)

    return filtered_peaks


def _detect_valleys(
    angle_values: Sequence[float],
    time_values: Sequence[float],
    min_range_pct: float = 0.30,
    min_dist_s: float = 1.0,
) -> List[int]:
    """
    Detects local valleys (minima) in a sliding window.

    Symmetric to _detect_peaks, but inverts the signal direction.
    Required to count complete cycles (flexion + extension).
    """
    n = len(angle_values)
    if n < 3 or len(time_values) != n:
        return []

    min_val = min(angle_values)
    max_val = max(angle_values)
    rom = max_val - min_val

    if rom <= 1e-6:
        return []

    # Threshold: valley must be below (max - min_range_pct * rom).
    threshold = max_val - min_range_pct * rom

    fps_est = _estimate_fps(time_values)
    if fps_est <= 0:
        min_dist_samples = 1
    else:
        min_dist_samples = max(1, int(round(min_dist_s * fps_est)))

    candidate_valleys: List[int] = []
    for i in range(1, n - 1):
        prev_v = angle_values[i - 1]
        curr_v = angle_values[i]
        next_v = angle_values[i + 1]

        is_local_valley = (curr_v <= prev_v) and (curr_v < next_v)
        if is_local_valley and curr_v <= threshold:
            candidate_valleys.append(i)

    if not candidate_valleys:
        return []

    filtered_valleys: List[int] = [candidate_valleys[0]]
    for idx in candidate_valleys[1:]:
        last_idx = filtered_valleys[-1]
        if idx - last_idx < min_dist_samples:
            if angle_values[idx] < angle_values[last_idx]:
                filtered_valleys[-1] = idx
        else:
            filtered_valleys.append(idx)

    return filtered_valleys


# =============================================================================
# REAL-TIME METRICS
# =============================================================================

def compute_realtime_metrics(
    angle_buffer: Sequence[float] | Deque[float],
    time_buffer: Sequence[float] | Deque[float],
    min_range_pct: float = 0.30,
    min_dist_s: float = 1.0,
) -> Dict[str, float | int | str]:
    """
    Computes real-time metrics for ONE finger based on recent TAM.

    Parameters:
        angle_buffer: TAM values of the last N frames.
        time_buffer:  Corresponding timestamps.
        min_range_pct: Minimum rom percentage to accept a peak.
        min_dist_s:    Minimum distance between consecutive peaks (seconds).

    Returns:
    {
        "rom": float,
        "avg_velocity": float,
        "peak_velocity": float,
        "freq_hz": float,
        "cv": float,
        "regularity": str,
        "n_picos": int,
    }
    """
    angles = list(angle_buffer)
    times = list(time_buffer)

    if len(angles) < 2 or len(times) < 2 or len(angles) != len(times):
        return {
            "rom": 0.0,
            "avg_velocity": 0.0,
            "peak_velocity": 0.0,
            "freq_hz": 0.0,
            "cv": 0.0,
            "regularity": "Regular",
            "n_picos": 0,
        }

    rom = float(max(angles) - min(angles))

    velocities: List[float] = []
    for i in range(1, len(angles)):
        d_angle = abs(angles[i] - angles[i - 1])
        d_time = times[i] - times[i - 1]
        if d_time > 1e-6:
            velocities.append(d_angle / d_time)

    avg_velocity = _safe_mean(velocities, default=0.0)
    peak_velocity = max(velocities) if velocities else 0.0

    peaks = _detect_peaks(
        angle_values=angles,
        time_values=times,
        min_range_pct=min_range_pct,
        min_dist_s=min_dist_s,
    )
    valleys = _detect_valleys(
        angle_values=angles,
        time_values=times,
        min_range_pct=min_range_pct,
        min_dist_s=min_dist_s,
    )
    n_picos = len(peaks)
    n_extremos = len(peaks) + len(valleys)

    # Frequency computed from complete cycles:
    # - one cycle = 1 peak + 1 valley (flexion + extension).
    # - n_extremos / 2 gives complete cycles.
    # - with 2+ peaks: use the interval between first and last peak
    #   to avoid underestimation when peaks are concentrated at the
    #   beginning of the window.
    peak_times = [times[idx] for idx in peaks]
    duration = times[-1] - times[0]
    if n_picos >= 2:
        pico_duration = peak_times[-1] - peak_times[0]
        freq_hz = (n_extremos / 2.0) / pico_duration if pico_duration > 1e-6 else 0.0
    elif n_extremos >= 2:
        freq_hz = (n_extremos / 2.0) / duration if duration > 1e-6 else 0.0
    else:
        freq_hz = 0.0

    intervals = [
        peak_times[i] - peak_times[i - 1]
        for i in range(1, len(peak_times))
        if (peak_times[i] - peak_times[i - 1]) > 1e-6
    ]

    if len(intervals) >= 2:
        mean_interval = _safe_mean(intervals, default=0.0)
        std_interval = _safe_std(intervals, default=0.0)
        cv = std_interval / mean_interval if mean_interval > 1e-6 else 0.0
        if cv <= 0.20:
            regularity = "Regular"
        elif cv <= 0.40:
            regularity = "Moderate"
        else:
            regularity = "Irregular"
    else:
        cv = 0.0
        # Return "-" (undefined) instead of "Regular" to avoid a false positive.
        # "Regular" with n_picos < 2 means only absence of data, not good coordination.
        regularity = "-"

    return {
        "rom": float(rom),
        "avg_velocity": float(avg_velocity),
        "peak_velocity": float(peak_velocity),
        "freq_hz": float(freq_hz),
        "cv": float(cv),
        "regularity": regularity,
        "n_picos": int(n_picos),
    }


# =============================================================================
# TEXT FORMATTERS
# =============================================================================

def freq_label(freq_hz: float) -> str:
    """
    Formats frequency for user-friendly display.
    """
    if freq_hz <= 0:
        return "0.00 Hz"

    period_s = 1.0 / freq_hz if freq_hz > 1e-6 else 0.0

    if freq_hz < 0.15:
        emoji = "🐢"
        status = "slow"
    elif freq_hz > 0.40:
        emoji = "⚡"
        status = "active"
    else:
        emoji = "🔄"
        status = "moderate"

    return f"{emoji} {freq_hz:.2f} Hz ({status}, ≈ 1 cycle/{period_s:.2f}s)"


def regularity_label(regularity: str, cv: float) -> str:
    """
    Formats temporal regularity for user-friendly display.
    """
    if regularity == "Regular":
        emoji = "✅"
    elif regularity == "Moderate":
        emoji = "🟡"
    else:
        emoji = "❌"

    return f"{emoji} CV {cv:.2f} → {regularity}"


# =============================================================================
# AGGREGATED SESSION METRICS (from in-memory buffers)
# =============================================================================

def compute_session_metrics_from_buffers(
    angle_buffers: Dict[str, Dict[str, List[float]]],
    time_buffers: Dict[str, List[float]],
    min_range_pct: float = 0.30,
    min_dist_s: float = 1.0,
) -> Dict[str, Dict]:
    """
    Computes consolidated metrics for all fingers from in-memory buffers.

    Reuses compute_realtime_metrics() for each finger, grouping results
    into a single dictionary indexed by finger name.

    Parameters:
        angle_buffers: dictionary {finger: {joint: [values]}}
        time_buffers:  dictionary {finger: [timestamps]}
        min_range_pct: rom threshold to accept peaks.
        min_dist_s:    minimum distance between peaks (in seconds).

    Returns:
        {
            "INDEX":  {rom, avg_velocity, peak_velocity, freq_hz, cv,
                       regularity, n_picos},
            "MIDDLE": {...},
            "RING":   {...},
            "PINKY":  {...},
        }
    """
    results: Dict[str, Dict] = {}

    for finger in FINGERS:
        tam_buffer = angle_buffers.get(finger, {}).get("TAM", [])
        t_buffer = time_buffers.get(finger, [])

        results[finger] = compute_realtime_metrics(
            angle_buffer=tam_buffer,
            time_buffer=t_buffer,
            min_range_pct=min_range_pct,
            min_dist_s=min_dist_s,
        )

    return results


def build_tam_chart_data(
    angle_buffers: Dict[str, Dict[str, List[float]]],
) -> Dict[str, List[float]]:
    """
    Builds the TAM time-series dictionary per finger, ready to feed
    a line chart.

    For long fingers, uses the "TAM" buffer.
    For the thumb, uses the "MCP" buffer as an rom proxy.

    Returns:
        {
            "Index":  [float, ...],
            "Middle": [float, ...],
            "Ring":   [float, ...],
            "Pinky":  [float, ...],
            "Thumb":  [float, ...],
        }
    """
    name_map = {
        "INDEX":  "Index",
        "MIDDLE": "Middle",
        "RING":   "Ring",
        "PINKY":  "Pinky",
        "THUMB":  "Thumb",
    }

    # Buffer key to use per finger.
    buffer_key = {
        "INDEX":  "TAM",
        "MIDDLE": "TAM",
        "RING":   "TAM",
        "PINKY":  "TAM",
        "THUMB":  "TAM",
    }

    series: Dict[str, List] = {}
    for finger, label in name_map.items():
        key = buffer_key[finger]
        values = angle_buffers.get(finger, {}).get(key, [])
        series[label] = list(values)

    # Align series to the maximum length, padding shorter ones with None
    # (treated as NaN by Vega-Lite = visible gap in the chart).
    # This prevents a finger with 1 fewer frame from truncating all others.
    max_len = max((len(v) for v in series.values()), default=0)
    if max_len > 0:
        for label in series:
            gap = max_len - len(series[label])
            if gap > 0:
                series[label] = [None] * gap + series[label]

    return series