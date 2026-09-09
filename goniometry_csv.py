"""
goniometry_csv.py — Registrador de dados de sessão goniométrica (CSV)
====================================================================

Este módulo grava uma linha por quadro contendo:
- timestamp;
- frame_id;
- ângulos suavizados por dedo e articulação.
"""

import csv
import math
import os
import time
from typing import Any, Dict, Optional


def _safe_round(value: Optional[float], ndigits: int = 2) -> Any:
    """
    Arredonda um valor válido; devolve "" (célula vazia no CSV) para
    None/NaN/+inf/-inf.

    Nunca grava as strings "None"/"nan"/"inf"/"-inf" — célula vazia é o
    marcador de "sem dado válido neste quadro", nunca 0.0 (0.0 é uma
    extensão real de articulação).
    """
    if value is None:
        return ""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(value):
        return ""
    return round(value, ndigits)

# =============================================================================
# CABEÇALHO CANÔNICO DO CSV
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
    Registrador de dados de sessão goniométrica em formato CSV.

    O arquivo é aberto em modo append para preservar o histórico quando desejado.
    O cabeçalho é gravado apenas se o arquivo ainda não existir ou estiver vazio.
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
        Grava uma linha correspondente a um quadro processado.

        Espera o dicionário de ângulos no mesmo formato retornado por:
        DigitalGoniometer.compute_all() / GoniometryFilterBank.smooth_all()
        """
        row: Dict[str, Any] = {
            "timestamp": time.time(),
            "frame_id": frame_id,
        }

        for finger in ("INDEX", "MIDDLE", "RING", "PINKY"):
            data = angles.get(finger, {})
            row[f"{finger}_MCP"] = _safe_round(data.get("MCP"))
            row[f"{finger}_PIP"] = _safe_round(data.get("PIP"))
            row[f"{finger}_DIP"] = _safe_round(data.get("DIP"))
            row[f"{finger}_ABD"] = _safe_round(data.get("ABD"))
            row[f"{finger}_TAM"] = _safe_round(data.get("TAM"))

        thumb = angles.get("THUMB", {})
        row["THUMB_MCP"] = _safe_round(thumb.get("MCP"))
        row["THUMB_IP"]  = _safe_round(thumb.get("IP"))
        row["THUMB_TAM"] = _safe_round(thumb.get("TAM"))

        self._writer.writerow(row)

    def flush(self) -> None:
        """
        Força a gravação do buffer do arquivo em disco.
        """
        self._file.flush()

    def close(self) -> None:
        """
        Fecha o arquivo CSV com segurança.
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