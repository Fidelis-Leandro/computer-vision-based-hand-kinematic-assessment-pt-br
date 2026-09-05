"""
smoothing.py — Mandatory EMA -> Kalman smoothing pipeline
==========================================================

This module implements the smoothing layer of the system.

Pipeline per time series:
    raw_angle -> EMA -> Kalman -> smoothed_angle

The classes here are independent of OpenCV and MediaPipe.
They operate solely on numeric values, which simplifies testing and reuse.
"""

from typing import Dict, Optional

# =============================================================================
# SCALAR SERIES FILTER
# =============================================================================


class SeriesFilter:
    """
    Scalar filter for a single angular time series.

    Each joint of each finger receives an independent instance
    to maintain its own history and Kalman state.
    """

    def __init__(
        self,
        ema_alpha: float = 0.30,
        kalman_q: float = 0.01,
        kalman_r: float = 0.10,
    ):
        # EMA parameters.
        self.ema_alpha = ema_alpha

        # Scalar Kalman parameters.
        self.q = kalman_q
        self.r = kalman_r

        # Internal state.
        self._ema_value: Optional[float] = None
        self._x: Optional[float] = None
        self._p: float = 1.0
        self._k_gain: float = 1.0
        self._n_updates: int = 0

    def update(self, raw: float) -> float:
        """
        Process a new raw value and return the smoothed value.

        Step 1 — EMA:
            Reduces high-frequency jitter between frames.

        Step 2 — Kalman:
            Models the recursive estimate of the true value
            and its residual uncertainty.
        """
        self._n_updates += 1

        # EMA
        if self._ema_value is None:
            self._ema_value = raw
        else:
            self._ema_value = (
                self.ema_alpha * raw
                + (1.0 - self.ema_alpha) * self._ema_value
            )

        ema_output = self._ema_value

        # Kalman
        if self._x is None:
            self._x = ema_output
            return float(self._x)

        p_minus = self._p + self.q
        self._k_gain = p_minus / (p_minus + self.r)
        self._x = self._x + self._k_gain * (ema_output - self._x)
        self._p = (1.0 - self._k_gain) * p_minus

        return float(self._x)

    @property
    def kalman_gain(self) -> float:
        """
        Return the last computed Kalman gain.
        """
        return self._k_gain

    @property
    def stability(self) -> str:
        """
        Classify the current filter stability based on the Kalman gain.
        """
        if self._k_gain < 0.15:
            return "stable"
        elif self._k_gain < 0.40:
            return "converging"
        else:
            return "unstable"

    @property
    def is_initialized(self) -> bool:
        """
        Return whether the series has been initialized with at least one sample.
        """
        return self._x is not None

    def reset(self, seed_value: Optional[float] = None) -> None:
        """
        Reset the internal filter state.
        """
        self._ema_value = seed_value
        self._x = seed_value
        self._p = 1.0
        self._k_gain = 1.0 if seed_value is None else 0.5
        self._n_updates = 0


# =============================================================================
# FILTER BANK
# =============================================================================

class GoniometryFilterBank:
    """
    Filter bank indexed by (finger, joint) pairs.

    This class coordinates all time series in the system
    and provides a unified API to smooth the complete angle dictionary.
    """

    def __init__(
        self,
        ema_alpha: float = 0.30,
        kalman_q: float = 0.01,
        kalman_r: float = 0.10,
    ):
        self._ema_alpha = ema_alpha
        self._kalman_q = kalman_q
        self._kalman_r = kalman_r
        self._filters: Dict[str, SeriesFilter] = {}

    def update(self, finger: str, joint: str, raw_angle: float) -> float:
        """
        Update a specific series in the bank.
        """
        key = f"{finger}_{joint}"

        if key not in self._filters:
            self._filters[key] = SeriesFilter(
                ema_alpha=self._ema_alpha,
                kalman_q=self._kalman_q,
                kalman_r=self._kalman_r,
            )

        return self._filters[key].update(raw_angle)

    def smooth_all(self, angles: Dict[str, Dict[str, float]]) -> Dict[str, Dict[str, float]]:
        """
        Smooth the entire angle dictionary at once.

        The input and output format is preserved for easy integration.
        """
        filtered: Dict[str, Dict[str, float]] = {}

        for finger, metrics in angles.items():
            filtered[finger] = {}
            for joint, raw in metrics.items():
                filtered[finger][joint] = round(self.update(finger, joint, raw), 2)

        return filtered

    def get_stability(self, finger: str, joint: str) -> str:
        """
        Return the qualitative filter state for a given series.
        """
        key = f"{finger}_{joint}"
        if key not in self._filters:
            return "uninitialized"
        return self._filters[key].stability

    def get_all_gains(self) -> Dict[str, float]:
        """
        Return the Kalman gain of all active series.
        """
        return {k: f.kalman_gain for k, f in self._filters.items()}

    def reset_finger(self, finger: str) -> None:
        """
        Reset all series associated with a given finger.
        """
        for key, filt in self._filters.items():
            if key.startswith(finger):
                filt.reset()

    def reset_all(self, seed_angles: Optional[Dict] = None) -> None:
        """
        Reset all series in the bank.
        """
        if seed_angles is None:
            for filt in self._filters.values():
                filt.reset()
        else:
            for finger, metrics in seed_angles.items():
                for joint, val in metrics.items():
                    key = f"{finger}_{joint}"
                    if key in self._filters:
                        self._filters[key].reset(seed_value=val)

    def configure(
        self,
        ema_alpha: float = None,
        kalman_q: float = None,
        kalman_r: float = None,
    ) -> None:
        """
        Reconfigure the global bank parameters.

        Changing parameters clears all existing filters so that new
        series are created with the updated configuration.
        """
        if ema_alpha is not None:
            self._ema_alpha = ema_alpha
        if kalman_q is not None:
            self._kalman_q = kalman_q
        if kalman_r is not None:
            self._kalman_r = kalman_r

        self._filters.clear()

    @property
    def active_series_count(self) -> int:
        """
        Number of currently active series.
        """
        return len(self._filters)

    def __repr__(self) -> str:
        return (
            f"GoniometryFilterBank("
            f"alpha={self._ema_alpha}, "
            f"Q={self._kalman_q}, "
            f"R={self._kalman_r}, "
            f"series={self.active_series_count})"
        )