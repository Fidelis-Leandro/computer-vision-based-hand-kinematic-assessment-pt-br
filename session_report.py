"""
session_report.py — Post-session PDF report generator
=======================================================

Reads the goniometry session CSV, computes per-finger summary metrics,
generates TAM charts, and assembles a clinical PDF report.

Main functions:
- load_session_csv()          : reads the CSV and structures data per finger
- compute_session_summary()   : computes clinical metrics per finger
- generate_tam_plot()         : overall TAM-vs-time chart
- generate_individual_plots() : 5 individual plots (one per finger)
- build_clinical_observation(): automatic interpretive text
- generate_pdf_report()       : assembles the complete PDF

External dependencies: fpdf2, matplotlib
"""

import csv
import math
import os
import statistics
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")  # windowless backend — generates PNG only
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

from fpdf import FPDF

from dashboard_utils import (
    FINGER_JOINTS,
    FINGERS,
    _detect_peaks,
    _detect_valleys,
)

from clinical_classification import (
    classify_articular_tam,
    detect_valid_repetitions,
    classify_functional_session,
    classify_final_session_result,
    generate_clinical_observation_text,
)


# =============================================================================
# PDF TEXT SANITIZATION
# =============================================================================

def sanitize_for_pdf(text: str) -> str:
    """
    Converts Unicode characters unsupported by FPDF built-in fonts
    (WinAnsi / Latin-1 range) to safe ASCII equivalents.
    """
    if not isinstance(text, str):
        return text
    replacements = {
        "\u2014": "-",   # em-dash  —
        "\u2013": "-",   # en-dash  –
        "\u2018": "'",   # left single quotation mark  '
        "\u2019": "'",   # right single quotation mark  '
        "\u201C": '"',   # left double quotation mark  "
        "\u201D": '"',   # right double quotation mark  "
        "\u2026": "...", # ellipsis  …
        "\u00B0": " deg",# degree sign  °
        "\u00B1": "+/-", # plus-minus  ±
        "\u2264": "<=",  # less-than or equal  ≤
        "\u2265": ">=",  # greater-than or equal  ≥
    }
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    return text

def _cell(pdf, *args, **kwargs):
    new_args = list(args)
    if len(new_args) > 2:
        new_args[2] = sanitize_for_pdf(str(new_args[2]))
    if 'txt' in kwargs:
        kwargs['txt'] = sanitize_for_pdf(str(kwargs['txt']))
    pdf.cell(*new_args, **kwargs)

def _multi_cell(pdf, *args, **kwargs):
    new_args = list(args)
    if len(new_args) > 2:
        new_args[2] = sanitize_for_pdf(str(new_args[2]))
    if 'txt' in kwargs:
        kwargs['txt'] = sanitize_for_pdf(str(kwargs['txt']))
    pdf.multi_cell(*new_args, **kwargs)


# =============================================================================
# CONSTANTS
# =============================================================================

FINGER_LABELS: Dict[str, str] = {
    "INDEX":  "Index",
    "MIDDLE": "Middle",
    "RING":   "Ring",
    "PINKY":  "Pinky",
    "THUMB":  "Thumb",
}

FINGER_COLORS: Dict[str, str] = {
    "INDEX":  "#2563eb",   # blue
    "MIDDLE": "#16a34a",   # green
    "RING":   "#ea580c",   # orange
    "PINKY":  "#9333ea",   # purple
    "THUMB":  "#dc2626",   # red
}

ASSH_COLORS_RGB: Dict[str, Tuple[int, int, int]] = {
    "Excellent": (34, 197, 94),
    "Good":      (234, 179, 8),
    "Fair":      (249, 115, 22),
    "Regular":   (249, 115, 22),
    "Poor":      (239, 68, 68),
}

REPORT_TITLE = "Digital Hand Goniometry — Session Report"

FOOTER_METHOD = (
    "Method: webcam + landmark tracking (MediaPipe Hands) "
    "+ EMA/Kalman smoothing."
)
FOOTER_DISCLAIMER = (
    "This report is intended for academic use and functional documentation support. "
    "It does not replace formal clinical validation."
)


# =============================================================================
# 1. CSV LOADING
# =============================================================================

def load_session_csv(csv_path: str) -> Dict[str, Any]:
    """
    Reads the session CSV and returns structured data per finger.

    Returns:
    {
        "timestamps": [float, ...],
        "frame_ids":  [int, ...],
        "fingers": {
            "INDEX": {
                "MCP": [float, ...],
                "PIP": [float, ...],
                "DIP": [float, ...],
                "ABD": [float, ...],
                "TAM": [float, ...],
            },
            "THUMB": {
                "MCP": [float, ...],
                "IP":  [float, ...],
                "TAM": [float, ...],   # computed: MCP + IP
            },
            ...
        },
        "session_start": float,   # first timestamp
        "session_end":   float,   # last timestamp
        "n_frames":      int,
    }
    """
    timestamps: List[float] = []
    frame_ids: List[int] = []

    fingers_data: Dict[str, Dict[str, List[float]]] = {}
    for finger in FINGERS:
        fingers_data[finger] = {j: [] for j in FINGER_JOINTS[finger]}
        if finger == "THUMB":
            fingers_data[finger]["TAM"] = []

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                ts = float(row.get("timestamp", 0))
                fid = int(float(row.get("frame_id", 0)))
            except (ValueError, TypeError):
                continue

            timestamps.append(ts)
            frame_ids.append(fid)

            # Long fingers
            for finger in ("INDEX", "MIDDLE", "RING", "PINKY"):
                for joint in FINGER_JOINTS[finger]:
                    col = f"{finger}_{joint}"
                    try:
                        val = float(row.get(col, 0.0))
                    except (ValueError, TypeError):
                        val = 0.0
                    fingers_data[finger][joint].append(val)

            # Thumb
            try:
                thumb_mcp = float(row.get("THUMB_MCP", 0.0))
            except (ValueError, TypeError):
                thumb_mcp = 0.0
            try:
                thumb_ip = float(row.get("THUMB_IP", 0.0))
            except (ValueError, TypeError):
                thumb_ip = 0.0

            fingers_data["THUMB"]["MCP"].append(thumb_mcp)
            fingers_data["THUMB"]["IP"].append(thumb_ip)

            try:
                thumb_tam = float(row.get("THUMB_TAM", 0.0))
            except (ValueError, TypeError):
                thumb_tam = 0.0

            # Fallback: if an older CSV does not have THUMB_TAM, compute it.
            if thumb_tam < 0.01 and (thumb_mcp > 0.01 or thumb_ip > 0.01):
                thumb_tam = max(thumb_mcp, 0.0) + max(thumb_ip, 0.0)

            fingers_data["THUMB"]["TAM"].append(thumb_tam)

    session_start = timestamps[0] if timestamps else 0.0
    session_end = timestamps[-1] if timestamps else 0.0

    return {
        "timestamps": timestamps,
        "frame_ids": frame_ids,
        "fingers": fingers_data,
        "session_start": session_start,
        "session_end": session_end,
        "n_frames": len(timestamps),
    }


# =============================================================================
# 2. PER-FINGER SUMMARY METRICS
# =============================================================================

def _safe_mean(values: List[float]) -> float:
    if not values:
        return 0.0
    return float(statistics.mean(values))


def _safe_stdev(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    return float(statistics.pstdev(values))


def compute_session_summary(data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Computes clinical summary metrics for each finger.

    Returns a dict per finger containing:
    - tam_final, tam_medio, tam_max, tam_min
    - rom
    - avg_velocity, peak_velocity (°/s)
    - freq_hz
    - regularity, cv
    - assh_label, assh_color
    - mcp_medio, pip_medio, dip_medio (or ip_medio for the thumb)
    """
    timestamps = data["timestamps"]
    fingers = data["fingers"]
    summary: Dict[str, Dict[str, Any]] = {}

    for finger in FINGERS:
        fdata = fingers.get(finger, {})
        tam_values = fdata.get("TAM", [])

        if not tam_values:
            summary[finger] = _empty_finger_summary(finger)
            continue

        # Filter null/zero values indicating frames without detection.
        valid_tam = [v for v in tam_values if v > 0.01]
        if not valid_tam:
            valid_tam = tam_values  # fallback: use all

        tam_final = tam_values[-1]
        tam_medio = _safe_mean(valid_tam)
        tam_max = max(valid_tam)
        tam_min = min(valid_tam)
        rom = tam_max - tam_min

        # Angular velocities
        velocities: List[float] = []
        for i in range(1, len(tam_values)):
            d_angle = abs(tam_values[i] - tam_values[i - 1])
            d_time = timestamps[i] - timestamps[i - 1] if i < len(timestamps) else 0.0
            if d_time > 1e-6:
                velocities.append(d_angle / d_time)

        avg_velocity = _safe_mean(velocities)
        peak_velocity = max(velocities) if velocities else 0.0

        # Frequency and regularity via peak detection
        peaks = _detect_peaks(tam_values, timestamps)
        valleys = _detect_valleys(tam_values, timestamps)
        n_picos = len(peaks)
        n_extremos = n_picos + len(valleys)

        peak_times = [timestamps[idx] for idx in peaks]
        duration = timestamps[-1] - timestamps[0] if len(timestamps) >= 2 else 0.0

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
            mean_interval = _safe_mean(intervals)
            std_interval = _safe_stdev(intervals)
            cv = std_interval / mean_interval if mean_interval > 1e-6 else 0.0
            if cv <= 0.20:
                regularity = "Regular"
            elif cv <= 0.40:
                regularity = "Moderate"
            else:
                regularity = "Irregular"
        else:
            cv = 0.0
            regularity = "-"  # indeterminate

        # Hybrid classifications
        articular_class = classify_articular_tam(finger, tam_max)

        realtime_metrics_for_hybrid = {
            "rom": rom,
            "avg_velocity": avg_velocity,
            "peak_velocity": peak_velocity,
            "freq_hz": freq_hz,
            "cv": cv,
            "regularity": regularity,
        }

        repetition_stats = detect_valid_repetitions(tam_values, timestamps, finger)

        functional_class = classify_functional_session(
            finger, articular_class, repetition_stats, realtime_metrics_for_hybrid
        )

        hybrid_class = classify_final_session_result(
            finger, articular_class, functional_class, repetition_stats
        )

        # Joint averages
        joint_means: Dict[str, float] = {}
        for joint in FINGER_JOINTS[finger]:
            vals = fdata.get(joint, [])
            joint_means[joint] = _safe_mean(vals)

        entry: Dict[str, Any] = {
            "tam_final": round(tam_final, 1),
            "tam_medio": round(tam_medio, 1),
            "tam_max": round(tam_max, 1),
            "tam_min": round(tam_min, 1),
            "rom": round(rom, 1),
            "avg_velocity": round(avg_velocity, 1),
            "peak_velocity": round(peak_velocity, 1),
            "freq_hz": round(freq_hz, 2),
            "regularity": regularity,
            "cv": round(cv, 3),
            "n_picos": n_picos,
            "articular_class": articular_class,
            "functional_class": functional_class,
            "hybrid_class": hybrid_class,
        }

        # Add joint-specific averages
        if finger == "THUMB":
            entry["mcp_medio"] = round(joint_means.get("MCP", 0.0), 1)
            entry["ip_medio"] = round(joint_means.get("IP", 0.0), 1)
        else:
            entry["mcp_medio"] = round(joint_means.get("MCP", 0.0), 1)
            entry["pip_medio"] = round(joint_means.get("PIP", 0.0), 1)
            entry["dip_medio"] = round(joint_means.get("DIP", 0.0), 1)

        summary[finger] = entry

    return summary


def _empty_finger_summary(finger: str) -> Dict[str, Any]:
    """Returns an empty summary for fingers with no data."""
    entry: Dict[str, Any] = {
        "tam_final": 0.0,
        "tam_medio": 0.0,
        "tam_max": 0.0,
        "tam_min": 0.0,
        "rom": 0.0,
        "avg_velocity": 0.0,
        "peak_velocity": 0.0,
        "freq_hz": 0.0,
        "regularity": "-",
        "cv": 0.0,
        "n_picos": 0,
        "articular_class": {"label": "Poor", "color": "#ef4444"},
        "functional_class": {"label": "Poor", "color": "#ef4444"},
        "hybrid_class": {"label": "Poor", "color": "#ef4444", "explanation": "No data available for analysis."},
    }
    if finger == "THUMB":
        entry["mcp_medio"] = 0.0
        entry["ip_medio"] = 0.0
    else:
        entry["mcp_medio"] = 0.0
        entry["pip_medio"] = 0.0
        entry["dip_medio"] = 0.0
    return entry


# =============================================================================
# 3. CHARTS
# =============================================================================

def _time_axis(timestamps: List[float]) -> List[float]:
    """Converts absolute timestamps to seconds relative to the start."""
    if not timestamps:
        return []
    t0 = timestamps[0]
    return [t - t0 for t in timestamps]


def generate_tam_plot(data: Dict[str, Any], output_path: str) -> str:
    """
    Generates a line chart of TAM over time for all fingers.

    Returns the path of the generated PNG file.
    """
    timestamps = data["timestamps"]
    fingers = data["fingers"]
    time_s = _time_axis(timestamps)

    fig, ax = plt.subplots(figsize=(10, 4.5), dpi=150)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("#fafafa")

    for finger in FINGERS:
        tam = fingers.get(finger, {}).get("TAM", [])
        if tam and len(tam) == len(time_s):
            ax.plot(
                time_s,
                tam,
                label=FINGER_LABELS[finger],
                color=FINGER_COLORS[finger],
                linewidth=1.4,
                alpha=0.85,
            )

    ax.set_xlabel("Time (s)", fontsize=10)
    ax.set_ylabel("TAM (°)", fontsize=10)
    ax.set_title("TAM over session — all fingers", fontsize=12, fontweight="bold")
    ax.legend(loc="upper right", fontsize=8, framealpha=0.9)
    ax.grid(True, alpha=0.3, linestyle="--")
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True, nbins=10))

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    return output_path


def generate_individual_plots(data: Dict[str, Any], output_dir: str) -> Dict[str, str]:
    """
    Generates 5 individual charts (one per finger) of TAM over time.

    Returns dict {finger: png_path}.
    """
    os.makedirs(output_dir, exist_ok=True)
    timestamps = data["timestamps"]
    fingers = data["fingers"]
    time_s = _time_axis(timestamps)
    paths: Dict[str, str] = {}

    for finger in FINGERS:
        tam = fingers.get(finger, {}).get("TAM", [])
        if not tam or len(tam) != len(time_s):
            continue

        fig, ax = plt.subplots(figsize=(5, 2.5), dpi=150)
        fig.patch.set_facecolor("white")
        ax.set_facecolor("#fafafa")

        ax.plot(
            time_s,
            tam,
            color=FINGER_COLORS[finger],
            linewidth=1.2,
            alpha=0.85,
        )
        ax.fill_between(time_s, tam, alpha=0.08, color=FINGER_COLORS[finger])

        ax.set_xlabel("Time (s)", fontsize=8)
        ax.set_ylabel("TAM (°)", fontsize=8)
        ax.set_title(
            f"TAM — {FINGER_LABELS[finger]}",
            fontsize=9,
            fontweight="bold",
        )
        ax.grid(True, alpha=0.3, linestyle="--")
        ax.tick_params(labelsize=7)

        plt.tight_layout()
        path = os.path.join(output_dir, f"tam_{finger.lower()}.png")
        plt.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        paths[finger] = path

    return paths


# =============================================================================
# 4. AUTOMATIC CLINICAL OBSERVATION
# =============================================================================

def build_clinical_observation(summary: Dict[str, Dict[str, Any]]) -> str:
    """Generates a general interpretive text for the session based on the global hybrid classification."""
    valid = {f: s for f, s in summary.items() if s["tam_medio"] > 0.01}
    if not valid:
        return "Insufficient data to generate a clinical observation."

    ranks = {"Excellent": 4, "Good": 3, "Fair": 2, "Poor": 1}
    worst_label = "Excellent"
    worst_rank = 4

    for s in valid.values():
        label = s["hybrid_class"]["label"]
        rank = ranks.get(label, 1)
        if rank < worst_rank:
            worst_rank = rank
            worst_label = label

    return generate_clinical_observation_text({"label": worst_label})


def _build_interpretation(summary: Dict[str, Dict[str, Any]]) -> str:
    """
    Generates 1–2 paragraphs of summarized clinical interpretation.
    """
    valid = {f: s for f, s in summary.items() if s["tam_medio"] > 0.01}
    if not valid:
        return "Insufficient data for clinical interpretation."

    sorted_by_tam = sorted(valid.items(), key=lambda x: x[1]["tam_medio"], reverse=True)

    # Names of best and worst performers
    top_names = [FINGER_LABELS[f].lower() for f, _ in sorted_by_tam[:2]]
    bottom_names = [FINGER_LABELS[f].lower() for f, _ in sorted_by_tam[-2:]] if len(sorted_by_tam) >= 3 else []

    # Overall mobility level
    tam_medio_geral = _safe_mean([s["tam_medio"] for s in valid.values()])
    if tam_medio_geral >= 260:
        nivel = "good"
    elif tam_medio_geral >= 195:
        nivel = "moderate"
    elif tam_medio_geral >= 130:
        nivel = "reduced"
    else:
        nivel = "severely reduced"

    paragraphs: List[str] = []

    p1 = (
        f"Session analysis shows overall {nivel} mobility "
        f"(mean global TAM: {tam_medio_geral:.1f}°). "
    )
    if top_names:
        p1 += (
            f"The best functional performance was observed in the "
            f"{' and '.join(top_names)} finger(s), with higher mean TAM values"
        )
        # Check for good regularity
        top_regular = [
            FINGER_LABELS[f].lower()
            for f, s in sorted_by_tam[:2]
            if s["regularity"] == "Regular"
        ]
        if top_regular:
            p1 += " and greater temporal regularity"
        p1 += "."

    paragraphs.append(p1)

    if bottom_names and len(sorted_by_tam) >= 3:
        p2_parts: List[str] = []
        for f, s in sorted_by_tam[-2:]:
            nome = FINGER_LABELS[f].lower()
            issues: List[str] = []
            if s["rom"] < 30:
                issues.append("reduced rom")
            if s["avg_velocity"] < 20:
                issues.append("lower mean velocity")
            if s["regularity"] == "Irregular":
                issues.append("higher irregularity")
            if issues:
                p2_parts.append(f"The {nome} finger showed {', '.join(issues)}.")
        if p2_parts:
            paragraphs.append(" ".join(p2_parts))

    return "\n\n".join(paragraphs)


# =============================================================================
# 5. PDF GENERATION
# =============================================================================

class _ReportPDF(FPDF):
    """Custom PDF with page header and footer."""

    def __init__(self, logo_path: Optional[str] = None):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.logo_path = logo_path
        self.set_auto_page_break(auto=True, margin=20)

    def header(self):
        # Header background
        self.set_fill_color(230, 242, 255)  # light blue
        self.rect(0, 0, 210, 28, style="F")

        # Logo (if present)
        x_text = 10
        if self.logo_path and os.path.isfile(self.logo_path):
            try:
                self.image(self.logo_path, x=8, y=3, h=22)
                x_text = 35
            except Exception:
                pass

        # Report title
        self.set_text_color(30, 50, 80)
        self.set_font("Helvetica", "B", 11)
        self.set_xy(x_text, 12)
        _cell(self, 0, 5, REPORT_TITLE, align="L")

        # Decorative line
        self.set_draw_color(100, 150, 220)
        self.set_line_width(0.8)
        self.line(10, 28, 200, 28)

        self.ln(32)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(130, 130, 130)
        _cell(self, 0, 5, f"Page {self.page_no()}/{{nb}}", align="C")


def _add_identification_block(
    pdf: _ReportPDF,
    patient_name: str,
    session_start: float,
    session_end: float,
    side: str,
    observation: str,
) -> None:
    """Adds the patient and session identification block."""
    y_start = pdf.get_y()
    pdf.set_draw_color(180, 180, 190)
    pdf.set_line_width(0.3)

    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(40, 40, 50)
    _cell(pdf, 0, 7, "Patient and Session Identification", ln=True)

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(60, 60, 70)

    start_dt = datetime.fromtimestamp(session_start) if session_start > 0 else None
    end_dt = datetime.fromtimestamp(session_end) if session_end > 0 else None
    now_dt = datetime.now()

    duration_s = session_end - session_start if session_end > session_start else 0
    duration_min = duration_s / 60.0

    fields = [
        ("Patient:",       patient_name or "Not provided"),
        ("Session date:",  start_dt.strftime("%Y-%m-%d") if start_dt else "-"),
        ("Time:",          f"{start_dt.strftime('%H:%M:%S') if start_dt else '-'} to {end_dt.strftime('%H:%M:%S') if end_dt else '-'} ({duration_min:.1f} min)"),
        ("Report generated:", now_dt.strftime("%Y-%m-%d %H:%M:%S")),
        ("Evaluated side:", side or "Not provided"),
    ]

    for label, value in fields:
        pdf.set_font("Helvetica", "B", 9)
        _cell(pdf, 42, 5, label)
        pdf.set_font("Helvetica", "", 9)
        _cell(pdf, 0, 5, value, ln=True)

    # Automatic observation
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(40, 40, 50)
    _cell(pdf, 42, 5, "Observation:")
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(80, 80, 90)
    _multi_cell(pdf, 0, 4.5, observation)

    # Border around the block
    y_end = pdf.get_y() + 2
    pdf.rect(8, y_start - 2, 194, y_end - y_start + 4, style="D")
    pdf.ln(5)


def _add_main_table(
    pdf: _ReportPDF,
    summary: Dict[str, Dict[str, Any]],
) -> None:
    """Adds the main metrics table per finger."""
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(40, 40, 50)
    _cell(pdf, 0, 7, "Main Table — Metrics per Finger", ln=True)

    headers = [
        "Finger", "TAM\nfinal", "TAM\nmean", "TAM\nmax.", "TAM\nmin.",
        "Ampl.", "Avg.\nVel.", "Peak\nVel.", "Freq.", "Reg.", "Articular",
    ]
    col_widths = [22, 15, 15, 15, 15, 15, 15, 15, 14, 17, 18]

    # Table header
    pdf.set_fill_color(220, 225, 235)
    pdf.set_font("Helvetica", "B", 6.5)
    pdf.set_text_color(40, 40, 60)

    row_h = 9
    for i, header in enumerate(headers):
        x = pdf.get_x()
        y = pdf.get_y()
        pdf.rect(x, y, col_widths[i], row_h, style="FD")
        lines = header.split("\n")
        if len(lines) == 2:
            pdf.set_xy(x, y + 1)
            _cell(pdf, col_widths[i], 3.5, lines[0], align="C")
            pdf.set_xy(x, y + 4.5)
            _cell(pdf, col_widths[i], 3.5, lines[1], align="C")
        else:
            pdf.set_xy(x, y + 2.5)
            _cell(pdf, col_widths[i], 4, header, align="C")
        pdf.set_xy(x + col_widths[i], y)

    pdf.ln(row_h)

    # Data per finger
    pdf.set_font("Helvetica", "", 7)
    row_h = 7

    for idx, finger in enumerate(FINGERS):
        s = summary.get(finger, _empty_finger_summary(finger))

        # Zebra coloring
        if idx % 2 == 0:
            pdf.set_fill_color(248, 248, 252)
        else:
            pdf.set_fill_color(255, 255, 255)

        values = [
            FINGER_LABELS[finger],
            f"{s['tam_final']:.0f}°",
            f"{s['tam_medio']:.0f}°",
            f"{s['tam_max']:.0f}°",
            f"{s['tam_min']:.0f}°",
            f"{s['rom']:.0f}°",
            f"{s['avg_velocity']:.0f}°/s",
            f"{s['peak_velocity']:.0f}°/s",
            f"{s['freq_hz']:.2f}Hz",
            s["regularity"],
            s["articular_class"]["label"],
        ]

        for i, val in enumerate(values):
            # Special color for ASSH classification
            if i == len(values) - 1:
                assh_rgb = ASSH_COLORS_RGB.get(val, (130, 130, 130))
                pdf.set_text_color(*assh_rgb)
                pdf.set_font("Helvetica", "B", 7)
            else:
                pdf.set_text_color(50, 50, 60)
                pdf.set_font("Helvetica", "", 7)

            align = "L" if i == 0 else "C"
            _cell(pdf, col_widths[i], row_h, val, border=1, align=align, fill=True)

        pdf.ln(row_h)

    pdf.ln(3)


def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def _add_functional_blocks(pdf: _ReportPDF, summary: Dict[str, Dict[str, Any]]) -> None:
    """Adds explanatory functional classification blocks per finger."""
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(40, 40, 50)
    _cell(pdf, 0, 7, "Hybrid Functional Assessment", ln=True)
    pdf.ln(2)

    for idx, finger in enumerate(FINGERS):
        s = summary.get(finger, _empty_finger_summary(finger))

        pdf.set_fill_color(248, 248, 252) if idx % 2 == 0 else pdf.set_fill_color(255, 255, 255)
        pdf.rect(10, pdf.get_y(), 190, 24, style="F")

        # Finger header
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(30, 30, 40)
        _cell(pdf, 0, 5, f" {FINGER_LABELS[finger]}:", ln=True)

        # Items
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(50, 50, 60)

        # Articular
        _cell(pdf, 5, 4, "")
        _cell(pdf, 55, 4, "Articular classification (TAM):")
        pdf.set_font("Helvetica", "B", 8)
        color_art = _hex_to_rgb(s["articular_class"]["color"])
        pdf.set_text_color(*color_art)
        _cell(pdf, 0, 4, s["articular_class"]["label"], ln=True)

        # Functional
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(50, 50, 60)
        _cell(pdf, 5, 4, "")
        _cell(pdf, 55, 4, "Functional session classification:")
        pdf.set_font("Helvetica", "B", 8)
        color_func = _hex_to_rgb(s["functional_class"]["color"])
        pdf.set_text_color(*color_func)
        _cell(pdf, 0, 4, s["functional_class"]["label"], ln=True)

        # Hybrid
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(50, 50, 60)
        _cell(pdf, 5, 4, "")
        _cell(pdf, 55, 4, "Final hybrid classification:")
        pdf.set_font("Helvetica", "B", 8)
        color_hyb = _hex_to_rgb(s["hybrid_class"]["color"])
        pdf.set_text_color(*color_hyb)
        _cell(pdf, 0, 4, s["hybrid_class"]["label"], ln=True)

        # Rationale
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(80, 80, 90)
        _cell(pdf, 5, 4, "")
        _multi_cell(pdf, 0, 4, f"Rationale: {s['hybrid_class']['explanation']}")
        pdf.ln(3)

    pdf.ln(3)


def _add_complementary_table(
    pdf: _ReportPDF,
    summary: Dict[str, Dict[str, Any]],
) -> None:
    """Adds the supplementary table with joint averages."""
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(40, 40, 50)
    _cell(pdf, 0, 7, "Supplementary Table — Joint Averages", ln=True)

    headers = ["Finger", "MCP mean", "PIP / IP mean", "DIP mean"]
    widths = [35, 35, 35, 35]

    pdf.set_fill_color(220, 225, 235)
    pdf.set_font("Helvetica", "B", 8)
    for i, h in enumerate(headers):
        _cell(pdf, widths[i], 7, h, border=1, align="C", fill=True)
    pdf.ln(7)

    pdf.set_font("Helvetica", "", 8)
    for idx, finger in enumerate(FINGERS):
        s = summary.get(finger, {})
        if idx % 2 == 0:
            pdf.set_fill_color(248, 248, 252)
        else:
            pdf.set_fill_color(255, 255, 255)

        pdf.set_text_color(50, 50, 60)
        _cell(pdf, widths[0], 6, FINGER_LABELS[finger], border=1, align="L", fill=True)
        _cell(pdf, widths[1], 6, f"{s.get('mcp_medio', 0):.1f}°", border=1, align="C", fill=True)

        if finger == "THUMB":
            _cell(pdf, widths[2], 6, f"{s.get('ip_medio', 0):.1f}°", border=1, align="C", fill=True)
            _cell(pdf, widths[3], 6, "-", border=1, align="C", fill=True)
        else:
            _cell(pdf, widths[2], 6, f"{s.get('pip_medio', 0):.1f}°", border=1, align="C", fill=True)
            _cell(pdf, widths[3], 6, f"{s.get('dip_medio', 0):.1f}°", border=1, align="C", fill=True)

        pdf.ln(6)

    pdf.ln(3)


def _add_legend(pdf: _ReportPDF) -> None:
    """Adds the clinical legend for abbreviations."""
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(40, 40, 50)
    _cell(pdf, 0, 7, "Clinical Legend", ln=True)

    legends = [
        ("TAM (Total Active Motion)",
         "Sum of active motion ranges across the main joints of the finger, used as the global functional movement indicator."),
        ("Thumb TAM",
         "Sum of thumb MCP and IP. Maximum anatomical TAM ~120°. ASSH classification is proportionally adapted."),
        ("MCP (Metacarpophalangeal)",
         "Joint at the base of the finger."),
        ("PIP (Proximal Interphalangeal)",
         "Middle joint of the finger."),
        ("DIP (Distal Interphalangeal)",
         "Joint near the fingertip."),
        ("IP (Interphalangeal — Thumb)",
         "Joint between the phalanges of the thumb (equivalent to the DIP of long fingers)."),
        ("ASSH",
         "Functional classification (long fingers): Excellent (>=260°), Good (195–259°), Fair (130–194°), Poor (<130°)."),
        ("ASSH (Thumb)",
         "Adapted functional classification (thumb): Excellent (>=110°), Good (80–109°), Fair (50–79°), Poor (<50°)."),
        ("TAM final",
         "Total finger mobility value at the end of the session."),
        ("TAM mean",
         "Mean total finger mobility throughout the session."),
        ("ROM",
         "Difference between maximum and minimum movement values during the session."),
        ("Mean velocity",
         "Mean angular speed of movement during the session (°/s)."),
        ("Peak velocity",
         "Maximum angular velocity recorded (°/s)."),
        ("Frequency",
         "Rate of movement repetitions during the session (Hz)."),
        ("Temporal regularity",
         "Consistency of the movement pattern over time (CV of inter-peak intervals)."),
    ]

    pdf.set_font("Helvetica", "", 7)
    for term, desc in legends:
        pdf.set_text_color(40, 40, 50)
        pdf.set_font("Helvetica", "B", 7)
        _cell(pdf, 50, 4, f"  {term}:", align="L")
        pdf.set_font("Helvetica", "", 7)
        pdf.set_text_color(70, 70, 80)
        _multi_cell(pdf, 0, 4, desc)
        pdf.ln(0.5)

    pdf.ln(3)


def _add_footer_technical(pdf: _ReportPDF) -> None:
    """Adds the technical footer."""
    pdf.set_draw_color(180, 180, 190)
    pdf.set_line_width(0.3)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(3)

    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(100, 100, 110)
    _multi_cell(pdf, 0, 4, FOOTER_METHOD)
    pdf.ln(1)
    pdf.set_font("Helvetica", "B", 7)
    pdf.set_text_color(180, 80, 80)
    _multi_cell(pdf, 0, 4, f"Disclaimer: {FOOTER_DISCLAIMER}")


# =============================================================================
# 6. MAIN FUNCTION
# =============================================================================

def generate_pdf_report(
    csv_path: str,
    patient_name: str = "",
    side: str = "",
    logo_path: Optional[str] = None,
    output_path: Optional[str] = None,
) -> str:
    """
    Generates the complete PDF report from the session CSV.

    Parameters:
        csv_path     : path of the CSV generated by the session
        patient_name : full patient name
        side         : evaluated side (e.g., "Right", "Left")
        logo_path    : path to an institutional logo (PNG/JPG), optional
        output_path  : PDF output path; if None, generated automatically

    Returns:
        path of the generated PDF file
    """
    if output_path is None:
        base = os.path.splitext(csv_path)[0]
        output_path = f"{base}_report.pdf"

    # Temporary directory for charts
    plot_dir = os.path.join(os.path.dirname(csv_path) or ".", "_report_plots")
    os.makedirs(plot_dir, exist_ok=True)

    print("  [1/5] Reading session CSV...")
    data = load_session_csv(csv_path)

    if data["n_frames"] < 5:
        print("  WARNING: CSV has very few frames. Report data may be limited.")

    print("  [2/5] Computing per-finger metrics...")
    summary = compute_session_summary(data)

    print("  [3/5] Generating charts...")
    tam_plot_path = os.path.join(plot_dir, "tam_overall.png")
    generate_tam_plot(data, tam_plot_path)
    individual_paths = generate_individual_plots(data, plot_dir)

    print("  [4/5] Generating interpretive text...")
    observation = build_clinical_observation(summary)
    interpretation = _build_interpretation(summary)

    print("  [5/5] Assembling PDF...")
    pdf = _ReportPDF(logo_path=logo_path)
    pdf.alias_nb_pages()
    pdf.add_page()

    # --- PAGE 1 ---

    # Identification block
    _add_identification_block(
        pdf,
        patient_name=patient_name,
        session_start=data["session_start"],
        session_end=data["session_end"],
        side=side,
        observation=observation,
    )

    # Main table
    _add_main_table(pdf, summary)

    # Functional blocks
    _add_functional_blocks(pdf, summary)

    # Supplementary table
    _add_complementary_table(pdf, summary)

    # --- PAGE 2 ---
    pdf.add_page()

    # Overall chart
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(40, 40, 50)
    _cell(pdf, 0, 7, "TAM Chart Over Session", ln=True)

    if os.path.isfile(tam_plot_path):
        pdf.image(tam_plot_path, x=10, w=190)
        pdf.ln(3)

    # Individual charts
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(40, 40, 50)
    _cell(pdf, 0, 7, "Individual Charts per Finger", ln=True)

    # 2×3 grid layout
    x_positions = [10, 105]
    img_w = 90
    col_idx = 0

    for finger in FINGERS:
        path = individual_paths.get(finger)
        if path and os.path.isfile(path):
            x = x_positions[col_idx % 2]
            # Check if a new page is needed
            if pdf.get_y() > 230:
                pdf.add_page()

            pdf.image(path, x=x, y=pdf.get_y(), w=img_w)
            col_idx += 1
            if col_idx % 2 == 0:
                pdf.ln(65)  # approximate chart height

    if col_idx % 2 != 0:
        pdf.ln(65)

    # Check space for text
    if pdf.get_y() > 200:
        pdf.add_page()

    # Interpretive text
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(40, 40, 50)
    _cell(pdf, 0, 7, "Clinical Interpretation", ln=True)

    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(50, 50, 60)
    _multi_cell(pdf, 0, 4.5, interpretation)
    pdf.ln(5)

    # Clinical legend
    if pdf.get_y() > 220:
        pdf.add_page()
    _add_legend(pdf)

    # Technical footer
    if pdf.get_y() > 250:
        pdf.add_page()
    _add_footer_technical(pdf)

    # Save PDF
    pdf.output(output_path)

    # Clean up temporary charts
    try:
        for f_path in individual_paths.values():
            if os.path.isfile(f_path):
                os.remove(f_path)
        if os.path.isfile(tam_plot_path):
            os.remove(tam_plot_path)
        if os.path.isdir(plot_dir) and not os.listdir(plot_dir):
            os.rmdir(plot_dir)
    except OSError:
        pass

    print(f"\n  PDF report generated: {output_path}")
    return output_path
