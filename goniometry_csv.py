"""
goniometry_csv.py — Goniometric session data logger (CSV)
==========================================================

This module writes one row per frame containing:
- timestamp;
- frame_id;
- smoothed angles per finger and joint.
"""

import csv
import os
import time
from typing import Any, Dict

# =============================================================================
# CANONICAL CSV HEADER
# =============================================================================

CSV_FIELDS = [
    "timestamp",
    "frame_id",
    "INDEX_MCP",
    "INDEX_PIP",
    "INDEX_DIP",
    "INDEX_ABD",
    "INDEX_TAM",
    "MIDDLE_MCP",
    "MIDDLE_PIP",
    "MIDDLE_DIP",
    "MIDDLE_ABD",
    "MIDDLE_TAM",
    "RING_MCP",
    "RING_PIP",
    "RING_DIP",
    "RING_ABD",
    "RING_TAM",
    "PINKY_MCP",
    "PINKY_PIP",
    "PINKY_DIP",
    "PINKY_ABD",
    "PINKY_TAM",
    "THUMB_MCP",
    "THUMB_IP",
    "THUMB_TAM",
]


class GoniometryCSVLogger:
    """
    Goniometric session data logger.

    The file is opened in append mode to preserve history when desired.
    The header is written only if the file does not yet exist or is empty.
    """

    def __init__(self, filepath: str = "session_goniometry.csv"):
        self.filepath = filepath
        self._file_exists = os.path.isfile(filepath) and os.path.getsize(filepath) > 0
        self._file = open(filepath, "a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=CSV_FIELDS)

        if not self._file_exists:
            self._writer.writeheader()
            self._file.flush()

    def log(self, frame_id: int, angles: Dict[str, Dict[str, float]]) -> None:
        """
        Writes one row corresponding to a processed frame.

        Expects the angles dictionary in the same format returned by:
        DigitalGoniometer.compute_all() / GoniometryFilterBank.smooth_all()
        """
        row: Dict[str, Any] = {
            "timestamp": time.time(),
            "frame_id": frame_id,
        }

        for finger in ("INDEX", "MIDDLE", "RING", "PINKY"):
            data = angles.get(finger, {})
            row[f"{finger}_MCP"] = round(data.get("MCP", 0.0), 2)
            row[f"{finger}_PIP"] = round(data.get("PIP", 0.0), 2)
            row[f"{finger}_DIP"] = round(data.get("DIP", 0.0), 2)
            row[f"{finger}_ABD"] = round(data.get("ABD", 0.0), 2)
            row[f"{finger}_TAM"] = round(data.get("TAM", 0.0), 2)

        thumb = angles.get("THUMB", {})
        row["THUMB_MCP"] = round(thumb.get("MCP", 0.0), 2)
        row["THUMB_IP"]  = round(thumb.get("IP",  0.0), 2)
        row["THUMB_TAM"] = round(thumb.get("TAM", 0.0), 2)

        self._writer.writerow(row)

    def flush(self) -> None:
        """
        Forces the file buffer to be written to disk.
        """
        self._file.flush()

    def close(self) -> None:
        """
        Safely closes the CSV file.
        """
        if hasattr(self, "_file") and self._file and not self._file.closed:
            self._file.flush()
            self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __del__(self):
        if hasattr(self, "_file"):
            self.close()