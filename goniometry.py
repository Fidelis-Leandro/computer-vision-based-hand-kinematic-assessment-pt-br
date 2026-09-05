"""
goniometry.py — Digital goniometry based on 3D landmarks
=========================================================

This module computes hand joint angles from MediaPipe landmarks.

Responsibilities:
    - Convert landmarks to 3D numpy vectors.
    - Compute the hand reference plane.
    - Measure signed clinical angles.
    - Calculate MCP, PIP, DIP, ABD, and TAM for each finger.
    - Calculate MCP and IP for the thumb.
    - Classify TAM and validate clinical ranges.

This module is independent of OpenCV.
"""

from typing import Any, Dict, List

import numpy as np

import config

# =============================================================================
# LANDMARK INDICES
# =============================================================================

WRIST = 0

THUMB_CMC, THUMB_MCP, THUMB_IP, THUMB_TIP = 1, 2, 3, 4

INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_TIP = 5, 6, 7, 8
MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP = 9, 10, 11, 12
RING_MCP, RING_PIP, RING_DIP, RING_TIP = 13, 14, 15, 16
PINKY_MCP, PINKY_PIP, PINKY_DIP, PINKY_TIP = 17, 18, 19, 20

# =============================================================================
# CLINICAL REFERENCE
# =============================================================================

NORMAL_RANGES: Dict[str, tuple] = {
    "MCP_flex":  (70.0, 90.0),   # ASSH: MCP flexion 70–90° is normal for active motion
    "MCP_hyper": (0.0, 45.0),
    "PIP_flex":  (100.0, 120.0),
    "DIP_flex":  (60.0, 80.0),
    "ABD":       (15.0, 20.0),
    "TAM":       (250.0, 270.0),
    "THUMB_MCP": (50.0, 60.0),
    "THUMB_IP":  (70.0, 90.0),
    "THUMB_TAM": (100.0, 130.0),
}

TAM_CLASSIFICATION = [
    (260.0, float("inf"), "Excellent", (50, 220, 130)),
    (195.0, 260.0, "Good",      (40, 200, 255)),
    (130.0, 195.0, "Fair",      (50, 130, 255)),
    (0.0,   130.0, "Poor",      (60, 60, 255)),
]

TAM_CLASSIFICATION_THUMB = [
    (110.0, float("inf"), "Excellent", (50, 220, 130)),
    (80.0,  110.0,        "Good",      (40, 200, 255)),
    (50.0,   80.0,        "Fair",      (50, 130, 255)),
    (0.0,    50.0,        "Poor",      (60, 60, 255)),
]


# =============================================================================
# VECTOR FUNCTIONS
# =============================================================================

def _lm_to_array(landmark: Any) -> np.ndarray:
    """
    Convert a MediaPipe landmark to a numpy vector [x, y, z].
    """
    return np.array([landmark.x, landmark.y, landmark.z], dtype=np.float64)


def _normalize(v: np.ndarray) -> np.ndarray:
    """
    Normalize a vector to unit length.
    """
    norm = np.linalg.norm(v)
    return v / norm if norm > 1e-9 else np.zeros(3, dtype=np.float64)


def angle_between_vectors_3d(v1: np.ndarray, v2: np.ndarray, normal: np.ndarray) -> float:
    """
    Compute the signed angle between two 3D vectors.

    The sign uses the hand plane as a reference to distinguish:
    - flexion / abduction (positive);
    - extension / hyperextension / adduction (negative).
    """
    v1 = _normalize(v1)
    v2 = _normalize(v2)

    cos_angle = float(np.clip(np.dot(v1, v2), -1.0, 1.0))
    angle_deg = float(np.degrees(np.arccos(cos_angle)))

    cross = np.cross(v1, v2)
    sign = float(np.dot(cross, normal))

    return angle_deg if sign >= 0 else -angle_deg


def _hand_normal(landmarks: List[Any], is_right_hand: bool = True) -> np.ndarray:
    """
    Compute the normal vector of the hand plane.

    The normal points outward from the palm of the right hand.
    For the left hand (is_right_hand=False), the vector is negated
    to maintain the correct sign convention for flexion/extension.

    Note: cv2.flip() mirrors the frame visually but does not alter the
    .x/.y/.z coordinates of MediaPipe landmarks — therefore handedness
    correction must be applied here, in the normal vector.
    """
    wrist = _lm_to_array(landmarks[WRIST])
    mcp_index = _lm_to_array(landmarks[INDEX_MCP])
    mcp_pinky = _lm_to_array(landmarks[PINKY_MCP])

    v1 = mcp_index - wrist
    v2 = mcp_pinky - wrist

    normal = _normalize(np.cross(v2, v1))
    if not is_right_hand:
        normal = -normal
    return normal


def _thumb_local_normal(landmarks: List[Any], hand_normal: np.ndarray) -> np.ndarray:
    """
    Stable normal for the thumb movement plane.

    Derived solely from the thumb metacarpal axis (CMC->MCP) and the
    dorsal hand normal. By using only CMC and MCP — not IP or TIP — it
    is completely independent of the thumb's current joint position.
    This eliminates the circular dependency that caused sign inversion
    during flexion.

    Resulting sign convention:
    - Flexion toward the palm -> positive
    - Extension / abduction outward -> zero or negative

    Parameters:
        landmarks   : list of 21 MediaPipe landmarks.
        hand_normal : correct dorsal normal (already adjusted for handedness)
                      from _hand_normal() in compute_all().
    """
    cmc = _lm_to_array(landmarks[THUMB_CMC])
    mcp = _lm_to_array(landmarks[THUMB_MCP])

    # Thumb metacarpal axis — stable, does not change with MCP/IP flexion.
    thumb_shaft = _normalize(mcp - cmc)

    # Palmar direction = opposite of the dorsal normal.
    palmar = -hand_normal

    # cross(thumb_axis, palmar) produces the perpendicular vector
    # pointing in the direction that defines palmar flexion as positive.
    raw = np.cross(thumb_shaft, palmar)

    norm_mag = np.linalg.norm(raw)
    if norm_mag < 1e-9:
        # Fallback: thumb is parallel to the hand normal (anatomically extreme pose).
        return hand_normal

    return _normalize(raw)


# =============================================================================
# DIGITAL GONIOMETER
# =============================================================================

class DigitalGoniometer:
    """
    Implements hand joint angle calculations.

    This class encapsulates the clinical formulas and sign conventions
    to produce a structured dictionary organized by finger and joint.
    """

    def mcp_flex(self, landmarks: List[Any], mcp_idx: int, pip_idx: int, normal: np.ndarray) -> float:
        """
        Compute MCP flexion for a non-thumb finger.
        """
        wrist = _lm_to_array(landmarks[WRIST])
        mcp = _lm_to_array(landmarks[mcp_idx])
        pip = _lm_to_array(landmarks[pip_idx])

        return angle_between_vectors_3d(mcp - wrist, pip - mcp, normal)

    def pip_flex(
        self,
        landmarks: List[Any],
        mcp_idx: int,
        pip_idx: int,
        dip_idx: int,
        normal: np.ndarray,
    ) -> float:
        """
        Compute PIP flexion.
        """
        mcp = _lm_to_array(landmarks[mcp_idx])
        pip = _lm_to_array(landmarks[pip_idx])
        dip = _lm_to_array(landmarks[dip_idx])

        return angle_between_vectors_3d(pip - mcp, dip - pip, normal)

    def dip_flex(
        self,
        landmarks: List[Any],
        pip_idx: int,
        dip_idx: int,
        tip_idx: int,
        normal: np.ndarray,
    ) -> float:
        """
        Compute DIP flexion.
        """
        pip = _lm_to_array(landmarks[pip_idx])
        dip = _lm_to_array(landmarks[dip_idx])
        tip = _lm_to_array(landmarks[tip_idx])

        return angle_between_vectors_3d(dip - pip, tip - dip, normal)

    # Abduction reference per finger: uses the immediately adjacent finger.
    # Using the middle finger as an absolute reference for all fingers
    # overestimated index abduction and distorted the little finger.
    _ABD_REFERENCE = {
        INDEX_MCP:  MIDDLE_MCP,   # index  -> middle
        MIDDLE_MCP: MIDDLE_MCP,   # middle -> itself (result 0, no ABD defined)
        RING_MCP:   MIDDLE_MCP,   # ring   -> middle
        PINKY_MCP:  RING_MCP,     # little -> ring
    }

    def mcp_abduction(self, landmarks: List[Any], mcp_idx: int) -> float:
        """
        Compute MCP abduction using the adjacent finger as reference.

        Clinical references:
        - Index and Ring: reference is the Middle finger.
        - Little: reference is the Ring finger.
        - Middle: returns 0 (no abduction reference defined clinically).
        """
        ref_idx = self._ABD_REFERENCE.get(mcp_idx, MIDDLE_MCP)
        wrist = _lm_to_array(landmarks[WRIST])
        ref_mcp = _lm_to_array(landmarks[ref_idx])
        current_mcp = _lm_to_array(landmarks[mcp_idx])

        if mcp_idx == ref_idx:
            return 0.0  # middle finger has no adjacent reference

        ref = _normalize(ref_mcp - wrist)
        cur = _normalize(current_mcp - wrist)

        cos_angle = float(np.clip(np.dot(ref, cur), -1.0, 1.0))
        return float(np.degrees(np.arccos(cos_angle)))

    def total_active_motion(self, mcp: float, pip: float, dip: float) -> float:
        """
        Compute TAM (Total Active Motion) using the full ASSH formula.

        ASSH formula:
            TAM = (MCP + PIP + DIP)_flex - (MCP + PIP + DIP)_deficit

        Deficit = negative angle (incomplete extension / flexion contracture).
        A patient with PIP locked at -30° has that deficit subtracted from TAM,
        which was not reflected in the previous formula that ignored negative values.
        """
        flex_sum    = max(mcp, 0.0) + max(pip, 0.0) + max(dip, 0.0)
        deficit_sum = abs(min(mcp, 0.0)) + abs(min(pip, 0.0)) + abs(min(dip, 0.0))
        return max(0.0, flex_sum - deficit_sum)

    def total_active_motion_thumb(self, mcp: float, ip: float) -> float:
        """
        Thumb TAM: sum of MCP + IP using the adapted ASSH clinical protocol.

        Different anatomy — the thumb has only two mobile joints:
          - MCP: normal range 50–60°
          - IP:  normal range 70–90°
        Expected maximum TAM: ~120–130° (full thumb flexion).
        Negative values (extension deficit) are subtracted from the total.
        """
        flex_sum    = max(0.0, mcp) + max(0.0, ip)
        deficit_sum = abs(min(0.0, mcp)) + abs(min(0.0, ip))
        return max(0.0, flex_sum - deficit_sum)

    def thumb_mcp_flex(self, landmarks: List[Any], normal: np.ndarray) -> float:
        """
        Thumb MCP flexion using a stable LOCAL normal.

        Stationary arm = THUMB_CMC -> THUMB_MCP (metacarpal)
        Mobile arm     = THUMB_MCP -> THUMB_IP  (proximal phalanx)

        The movement plane normal is computed by _thumb_local_normal(),
        which uses only CMC, MCP, and the dorsal hand normal — without
        depending on IP or TIP. This eliminates the circular dependency
        that previously inverted the sign during palmar flexion.

        Expected:
        - Thumb flexed toward the palm (opposition): +40° to +60°
        - Thumb extended/abducted outward           : near 0° or negative
        """
        cmc = _lm_to_array(landmarks[THUMB_CMC])
        mcp = _lm_to_array(landmarks[THUMB_MCP])
        ip  = _lm_to_array(landmarks[THUMB_IP])

        # Pass the correct dorsal normal (with handedness) to the local calculation.
        thumb_normal = _thumb_local_normal(landmarks, normal)
        return angle_between_vectors_3d(mcp - cmc, ip - mcp, thumb_normal)

    def thumb_ip_flex(self, landmarks: List[Any], normal: np.ndarray) -> float:
        """
        Thumb IP joint flexion using a stable LOCAL normal.

        Stationary arm = THUMB_MCP -> THUMB_IP  (proximal phalanx)
        Mobile arm     = THUMB_IP  -> THUMB_TIP (distal phalanx)

        Uses the same local normal as MCP to maintain consistent sign convention.

        Expected:
        - IP flexed (thumb tip curling toward palm): +70° to +90°
        - IP extended                              : near 0°
        """
        mcp = _lm_to_array(landmarks[THUMB_MCP])
        ip  = _lm_to_array(landmarks[THUMB_IP])
        tip = _lm_to_array(landmarks[THUMB_TIP])

        thumb_normal = _thumb_local_normal(landmarks, normal)
        return angle_between_vectors_3d(ip - mcp, tip - ip, thumb_normal)

    def compute_all(
        self,
        landmarks: List[Any],
        is_right_hand: bool = True,
    ) -> Dict[str, Dict[str, float]]:
        """
        Compute all hand joint metrics.

        Parameters:
            landmarks    : list of MediaPipe landmarks (21 points).
            is_right_hand: True for the right hand, False for the left hand.
                           Negates the plane normal to correct the
                           flexion/extension sign for mirrored hands.
        """
        normal = _hand_normal(landmarks, is_right_hand=is_right_hand)

        result: Dict[str, Dict[str, float]] = {}

        fingers = {
            "INDEX":  (INDEX_MCP,  INDEX_PIP,  INDEX_DIP,  INDEX_TIP),
            "MIDDLE": (MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP),
            "RING":   (RING_MCP,   RING_PIP,   RING_DIP,   RING_TIP),
            "PINKY":  (PINKY_MCP,  PINKY_PIP,  PINKY_DIP,  PINKY_TIP),
        }

        for finger_name, (mcp_i, pip_i, dip_i, tip_i) in fingers.items():
            mcp_angle = self.mcp_flex(landmarks, mcp_i, pip_i, normal)
            pip_angle = self.pip_flex(landmarks, mcp_i, pip_i, dip_i, normal)
            dip_angle = self.dip_flex(landmarks, pip_i, dip_i, tip_i, normal)
            abd_angle = self.mcp_abduction(landmarks, mcp_i)

            # TAM uses absolute values because the sign convention
            # (positive = flexion for right hand, negative = flexion for left hand)
            # is a geometric artifact of the normal direction, not a clinical
            # distinction. TAM measures total range of motion regardless of hand side.
            tam = self.total_active_motion(abs(mcp_angle), abs(pip_angle), abs(dip_angle))

            # Biomechanical ceiling — clamp TAM to the anatomical maximum for this finger
            ceiling = config.TAM_CEILING.get(finger_name, 270.0)
            if tam > ceiling:
                tam = ceiling

            result[finger_name] = {
                "MCP": round(mcp_angle, 2),
                "PIP": round(pip_angle, 2),
                "DIP": round(dip_angle, 2),
                "ABD": round(abd_angle, 2),
                "TAM": round(tam, 2),
            }

        thumb_mcp = round(self.thumb_mcp_flex(landmarks, normal), 2)
        thumb_ip  = round(self.thumb_ip_flex(landmarks, normal), 2)
        thumb_tam = self.total_active_motion_thumb(abs(thumb_mcp), abs(thumb_ip))

        # Biomechanical ceiling — clamp thumb TAM to anatomical maximum
        ceiling_thumb = config.TAM_CEILING.get("THUMB", 130.0)
        if thumb_tam > ceiling_thumb:
            thumb_tam = ceiling_thumb

        result["THUMB"] = {
            "MCP": thumb_mcp,
            "IP":  thumb_ip,
            "TAM": round(thumb_tam, 2),
        }

        return result

    @staticmethod
    def classify_tam(tam: float, is_thumb: bool = False) -> Dict[str, object]:
        """
        Classify a TAM value according to the functional reference ranges.

        Parameters:
            tam      : TAM value to classify.
            is_thumb : if True, uses adapted ranges for the thumb
                       (maximum TAM ~120° instead of ~270°).
        """
        table = TAM_CLASSIFICATION_THUMB if is_thumb else TAM_CLASSIFICATION
        for lo, hi, label, color_bgr in table:
            if lo <= tam < hi:
                return {
                    "label": label,
                    "color_bgr": color_bgr,
                }

        return {
            "label": "Poor",
            "color_bgr": (60, 60, 255),
        }


# =============================================================================
# NORMAL RANGE CLASSIFICATION
# =============================================================================

def is_in_normal_range(finger: str, metric: str, value: float) -> str:
    """
    Determine whether a value is:
    - within the normal range;
    - borderline;
    - outside the expected range.
    """
    key_map = {
        ("INDEX", "MCP"): "MCP_flex",
        ("MIDDLE", "MCP"): "MCP_flex",
        ("RING", "MCP"): "MCP_flex",
        ("PINKY", "MCP"): "MCP_flex",
        ("INDEX", "PIP"): "PIP_flex",
        ("MIDDLE", "PIP"): "PIP_flex",
        ("RING", "PIP"): "PIP_flex",
        ("PINKY", "PIP"): "PIP_flex",
        ("INDEX", "DIP"): "DIP_flex",
        ("MIDDLE", "DIP"): "DIP_flex",
        ("RING", "DIP"): "DIP_flex",
        ("PINKY", "DIP"): "DIP_flex",
        ("INDEX", "ABD"): "ABD",
        ("MIDDLE", "ABD"): "ABD",
        ("RING", "ABD"): "ABD",
        ("PINKY", "ABD"): "ABD",
        ("INDEX", "TAM"): "TAM",
        ("MIDDLE", "TAM"): "TAM",
        ("RING", "TAM"): "TAM",
        ("PINKY", "TAM"): "TAM",
        ("THUMB", "MCP"): "THUMB_MCP",
        ("THUMB", "IP"): "THUMB_IP",
        ("THUMB", "TAM"): "THUMB_TAM",
    }

    range_key = key_map.get((finger, metric))
    if range_key is None:
        return "normal"

    lo, hi = NORMAL_RANGES[range_key]
    margin = (hi - lo) * 0.15

    if value < 0:
        return "abnormal"
    elif lo <= value <= hi:
        return "normal"
    elif lo - margin <= value <= hi + margin:
        return "borderline"
    else:
        return "abnormal"