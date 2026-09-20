"""
session_report.py — Gerador de relatórios clínicos pós-sessão em PDF
=====================================================================

Lê o CSV da sessão de goniometria, calcula métricas de resumo por dedo,
gera gráficos de TAM e monta o relatório clínico em formato PDF.

Funções principais:
- load_session_csv()          : lê o CSV e estrutura os dados por dedo
- compute_session_summary()   : calcula métricas clínicas por dedo
- generate_tam_plot()         : gráfico de TAM versus tempo geral
- generate_individual_plots() : 5 gráficos individuais (um por dedo)
- build_clinical_observation(): gera texto interpretativo automático
- generate_pdf_report()       : monta o relatório completo em PDF

Dependências externas: fpdf2, matplotlib
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
matplotlib.use("Agg")  # backend sem janela — gera apenas PNG
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
# SANITIZAÇÃO DE TEXTO PARA PDF
# =============================================================================

def sanitize_for_pdf(text: str) -> str:
    """
    Converte caracteres Unicode não suportados pelas fontes padrão do FPDF
    (faixa WinAnsi / Latin-1) para equivalentes seguros em ASCII.
    """
    if not isinstance(text, str):
        return text
    replacements = {
        "\u2014": "-",   # travessão duplo —
        "\u2013": "-",   # traço en –
        "\u2018": "'",   # aspas simples esquerda '
        "\u2019": "'",   # aspas simples direita '
        "\u201C": '"',   # aspas duplas esquerda "
        "\u201D": '"',   # aspas duplas direita "
        "\u2026": "...", # reticências …
        "\u00B0": " deg",# símbolo de grau °
        "\u00B1": "+/-", # mais-ou-menos ±
        "\u2264": "<=",  # menor ou igual ≤
        "\u2265": ">=",  # maior ou igual ≥
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
# CONSTANTES
# =============================================================================

FINGER_LABELS: Dict[str, str] = {
    "INDEX":  "Indicador",
    "MIDDLE": "Médio",
    "RING":   "Anelar",
    "PINKY":  "Mínimo",
    "THUMB":  "Polegar",
}

FINGER_COLORS: Dict[str, str] = {
    "INDEX":  "#2563eb",   # azul
    "MIDDLE": "#16a34a",   # verde
    "RING":   "#ea580c",   # laranja
    "PINKY":  "#9333ea",   # roxo
    "THUMB":  "#dc2626",   # vermelho
}

ASSH_COLORS_RGB: Dict[str, Tuple[int, int, int]] = {
    "Excelente": (34, 197, 94),
    "Bom":       (234, 179, 8),
    "Razoável":  (249, 115, 22),
    "Regular":   (249, 115, 22),
    "Ruim":      (239, 68, 68),
}

REPORT_TITLE = "Goniometria Digital da Mão — Relatório de Sessão"

# Rótulo legível de cada modo de filtro (smoothing.py) para o rodapé do PDF.
# Dicionário simples em vez de Enum/classe — são só 4 rótulos fixos.
_FILTER_MODE_LABELS = {
    "RAW": "RAW",
    "EMA": "EMA",
    "KALMAN": "Kalman",
    "EMA_KALMAN": "EMA + Kalman",
}


def build_footer_method_text(filter_mode: Optional[str], assumed: bool) -> str:
    """
    Monta a frase de método do rodapé técnico do PDF.

    Antes da Fase 5, o sistema só usava EMA_KALMAN, então um texto fixo
    ("... + suavização EMA/Kalman.") era sempre verdade. Agora que RAW,
    EMA, KALMAN e EMA_KALMAN existem, um texto fixo mentiria sobre
    qualquer sessão que tenha usado um modo diferente — por isso o texto
    precisa ser montado a partir do modo real gravado no CSV da sessão.

    `assumed=True` (CSV gravado antes da Fase 5, sem a coluna filter_mode)
    é tratado à parte: sabemos que só existia EMA_KALMAN até aqui, mas
    isso é uma suposição sobre o passado, não um dado medido — o relatório
    nunca pode apresentar essa suposição como se fosse um fato confirmado.
    """
    base = "Método: webcam + rastreamento de marcos anatômicos (MediaPipe Hands)"

    if assumed:
        return (
            f"{base}. Modo de filtragem: EMA + Kalman "
            "(assumido para sessão antiga sem registro de modo)."
        )

    label = _FILTER_MODE_LABELS.get(filter_mode)
    if label is None:
        # Modo ausente/desconhecido sem ser um CSV antigo (ex.: valor
        # corrompido) — texto transparente, nunca afirma EMA + Kalman.
        return f"{base}. Modo de filtragem: não identificado ({filter_mode!r})."

    return f"{base}. Modo de filtragem: {label}."


def build_demo_mode_warning_text(demo_mode: bool) -> str:
    """
    Monta o aviso de demonstração do rodapé técnico do PDF, separado do
    texto de método (build_footer_method_text) — os dois são metadados
    independentes: um descreve o filtro real usado, o outro identifica se
    a sessão foi o perfil Evento. Não os combino na mesma frase para que
    nenhuma mudança em um afete o texto do outro.

    demo_mode=False (sessão clínica, ou CSV antigo sem a coluna) devolve
    string vazia — o rodapé de uma sessão normal não deve ganhar nenhuma
    linha extra.
    """
    if not demo_mode:
        return ""

    return (
        "⚠ SESSÃO GERADA NO PERFIL EVENTO (DEMONSTRAÇÃO) — a resposta da mão "
        "robótica foi ampliada artificialmente para exibição em estande. Os "
        "ângulos e classificações clínicas acima permanecem medições reais."
    )


FOOTER_DISCLAIMER = (
    "Este relatório destina-se a uso acadêmico e suporte à documentação funcional. "
    "Não substitui validação clínica formal."
)


# =============================================================================
# 1. CARREGAMENTO DE CSV
# =============================================================================

def load_session_csv(csv_path: str) -> Dict[str, Any]:
    """
    Lê o CSV da sessão e retorna os dados estruturados por dedo.

    Retorna:
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
                "TAM": [float, ...],   # calculado: MCP + IP
            },
            ...
        },
        "session_start": float,   # primeiro timestamp
        "session_end":   float,   # último timestamp
        "n_frames":      int,
        "filter_mode": str | None,      # modo lido do CSV, ou None se ausente
        "filter_mode_assumed": bool,    # True = CSV antigo, sem essa coluna
        "demo_mode": bool,              # True = sessão do perfil Evento
    }

    filter_mode vem da coluna "filter_mode" (Fase 5), a mesma em toda linha
    da sessão — basta ler uma vez. CSVs gravados antes da Fase 5 não têm
    essa coluna; nesse caso, filter_mode fica None e filter_mode_assumed
    fica True, para que quem gera o relatório saiba que o modo não foi
    registrado e não pode ser afirmado como fato.

    demo_mode vem da coluna "demo_mode" (Fase 7E), lida como texto
    "True"/"False". Ao contrário de filter_mode, não existe aqui um
    "demo_mode_assumed": um CSV sem essa coluna é sempre de antes do perfil
    Evento existir, então False é um FATO sobre esse CSV, não uma suposição
    — a ausência da coluna já responde a pergunta.
    """
    timestamps: List[float] = []
    frame_ids: List[int] = []
    filter_mode_from_csv: Optional[str] = None
    demo_mode_from_csv: bool = False

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

            # filter_mode é o mesmo em toda linha da sessão — sobrescrever
            # a cada linha é inofensivo e mais simples do que só ler na
            # primeira. row.get() devolve None se a coluna não existir
            # (CSV antigo) ou "" se existir mas vier vazia; os dois casos
            # devem virar None aqui.
            filter_mode_from_csv = row.get("filter_mode") or None

            # demo_mode é gravado como texto ("True"/"False") em toda linha
            # de CSVs a partir da Fase 7E. Um CSV sem a coluna (row.get()
            # devolve None) ou com célula vazia cai no default "" -> False,
            # que é exatamente o comportamento correto: nunca existiu perfil
            # Evento antes desta fase.
            demo_mode_from_csv = (row.get("demo_mode") or "").strip().lower() == "true"

            # Dedos longos
            for finger in ("INDEX", "MIDDLE", "RING", "PINKY"):
                for joint in FINGER_JOINTS[finger]:
                    col = f"{finger}_{joint}"
                    try:
                        val = float(row.get(col, 0.0))
                    except (ValueError, TypeError):
                        val = 0.0
                    fingers_data[finger][joint].append(val)

            # Polegar
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

            # Fallback: se um CSV mais antigo não possuir THUMB_TAM, calcula-o.
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
        "filter_mode": filter_mode_from_csv,
        "filter_mode_assumed": filter_mode_from_csv is None,
        "demo_mode": demo_mode_from_csv,
    }


# =============================================================================
# 2. MÉTRICAS DE RESUMO POR DEDO
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
    Calcula métricas clínicas de resumo para cada dedo.

    Retorna um dicionário por dedo contendo:
    - tam_final, tam_medio, tam_max, tam_min
    - rom
    - vel_media, vel_pico (°/s)
    - freq_hz
    - regularidade, cv
    - assh_label, assh_color
    - mcp_medio, pip_medio, dip_medio (ou ip_medio para o polegar)
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

        # Filtra valores nulos/zero que indicam quadros sem detecção.
        valid_tam = [v for v in tam_values if v > 0.01]
        if not valid_tam:
            valid_tam = tam_values  # fallback: usa todos

        tam_final = tam_values[-1]
        tam_medio = _safe_mean(valid_tam)
        tam_max = max(valid_tam)
        tam_min = min(valid_tam)
        rom = tam_max - tam_min

        # Velocidades angulares
        velocities: List[float] = []
        for i in range(1, len(tam_values)):
            d_angle = abs(tam_values[i] - tam_values[i - 1])
            d_time = timestamps[i] - timestamps[i - 1] if i < len(timestamps) else 0.0
            if d_time > 1e-6:
                velocities.append(d_angle / d_time)

        vel_media = _safe_mean(velocities)
        vel_pico = max(velocities) if velocities else 0.0

        # Frequência e regularidade via detecção de picos
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
                regularity = "Moderado"
            else:
                regularity = "Irregular"
        else:
            cv = 0.0
            regularity = "-"  # indeterminado

        # Classificações híbridas
        articular_class = classify_articular_tam(finger, tam_max)

        realtime_metrics_for_hybrid = {
            "rom": rom,
            "vel_media": vel_media,
            "vel_pico": vel_pico,
            "freq_hz": freq_hz,
            "cv": cv,
            "regularidade": regularity,
        }

        repetition_stats = detect_valid_repetitions(tam_values, timestamps, finger)

        functional_class = classify_functional_session(
            finger, articular_class, repetition_stats, realtime_metrics_for_hybrid
        )

        hybrid_class = classify_final_session_result(
            finger, articular_class, functional_class, repetition_stats
        )

        # Médias articulares
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
            "vel_media": round(vel_media, 1),
            "vel_pico": round(vel_pico, 1),
            "freq_hz": round(freq_hz, 2),
            "regularidade": regularity,
            "cv": round(cv, 3),
            "n_picos": n_picos,
            "articular_class": articular_class,
            "functional_class": functional_class,
            "hybrid_class": hybrid_class,
        }

        # Adiciona médias articulares específicas
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
    """Retorna um resumo vazio para dedos sem dados."""
    entry: Dict[str, Any] = {
        "tam_final": 0.0,
        "tam_medio": 0.0,
        "tam_max": 0.0,
        "tam_min": 0.0,
        "rom": 0.0,
        "vel_media": 0.0,
        "vel_pico": 0.0,
        "freq_hz": 0.0,
        "regularidade": "-",
        "cv": 0.0,
        "n_picos": 0,
        "articular_class": {"rotulo": "Ruim", "cor": "#ef4444"},
        "functional_class": {"rotulo": "Ruim", "cor": "#ef4444"},
        "hybrid_class": {"rotulo": "Ruim", "cor": "#ef4444", "explicacao": "Sem dados disponíveis para análise."},
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
# 3. GRÁFICOS
# =============================================================================

def _time_axis(timestamps: List[float]) -> List[float]:
    """Converte timestamps absolutos para segundos relativos ao início."""
    if not timestamps:
        return []
    t0 = timestamps[0]
    return [t - t0 for t in timestamps]


def generate_tam_plot(data: Dict[str, Any], output_path: str) -> str:
    """
    Gera um gráfico de linhas de TAM ao longo do tempo para todos os dedos.

    Retorna o caminho do arquivo PNG gerado.
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

    ax.set_xlabel("Tempo (s)", fontsize=10)
    ax.set_ylabel("TAM (°)", fontsize=10)
    ax.set_title("TAM ao longo da sessão — todos os dedos", fontsize=12, fontweight="bold")
    ax.legend(loc="upper right", fontsize=8, framealpha=0.9)
    ax.grid(True, alpha=0.3, linestyle="--")
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True, nbins=10))

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    return output_path


def generate_individual_plots(data: Dict[str, Any], output_dir: str) -> Dict[str, str]:
    """
    Gera 5 gráficos individuais (um por dedo) de TAM ao longo do tempo.

    Retorna dicionário {finger: png_path}.
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

        ax.set_xlabel("Tempo (s)", fontsize=8)
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
# 4. OBSERVAÇÃO CLÍNICA AUTOMÁTICA
# =============================================================================

def build_clinical_observation(summary: Dict[str, Dict[str, Any]]) -> str:
    """Gera um texto interpretativo geral para a sessão com base na classificação híbrida global."""
    valid = {f: s for f, s in summary.items() if s["tam_medio"] > 0.01}
    if not valid:
        return "Dados insuficientes para gerar observação clínica."

    ranks = {"Excelente": 4, "Bom": 3, "Razoável": 2, "Ruim": 1}
    worst_label = "Excelente"
    worst_rank = 4

    for s in valid.values():
        label = s["hybrid_class"]["rotulo"]
        rank = ranks.get(label, 1)
        if rank < worst_rank:
            worst_rank = rank
            worst_label = label

    return generate_clinical_observation_text({"rotulo": worst_label})


def _build_interpretation(summary: Dict[str, Dict[str, Any]]) -> str:
    """
    Gera 1–2 parágrafos de interpretação clínica sumarizada.
    """
    valid = {f: s for f, s in summary.items() if s["tam_medio"] > 0.01}
    if not valid:
        return "Dados insuficientes para interpretação clínica."

    sorted_by_tam = sorted(valid.items(), key=lambda x: x[1]["tam_medio"], reverse=True)

    # Nomes dos melhores e piores desempenhos
    top_names = [FINGER_LABELS[f].lower() for f, _ in sorted_by_tam[:2]]
    bottom_names = [FINGER_LABELS[f].lower() for f, _ in sorted_by_tam[-2:]] if len(sorted_by_tam) >= 3 else []

    # Nível geral de mobilidade
    tam_medio_geral = _safe_mean([s["tam_medio"] for s in valid.values()])
    if tam_medio_geral >= 260:
        nivel = "boa"
    elif tam_medio_geral >= 195:
        nivel = "moderada"
    elif tam_medio_geral >= 130:
        nivel = "reduzida"
    else:
        nivel = "severamente reduzida"

    paragraphs: List[str] = []

    p1 = (
        f"A análise da sessão demonstra mobilidade geral {nivel} "
        f"(TAM médio global: {tam_medio_geral:.1f}°). "
    )
    if top_names:
        p1 += (
            f"O melhor desempenho funcional foi observado no(s) dedo(s) "
            f"{' e '.join(top_names)}, com maiores valores de TAM médio"
        )
        # Verifica boa regularidade
        top_regular = [
            FINGER_LABELS[f].lower()
            for f, s in sorted_by_tam[:2]
            if s["regularidade"] == "Regular"
        ]
        if top_regular:
            p1 += " e maior regularidade temporal"
        p1 += "."

    paragraphs.append(p1)

    if bottom_names and len(sorted_by_tam) >= 3:
        p2_parts: List[str] = []
        for f, s in sorted_by_tam[-2:]:
            nome = FINGER_LABELS[f].lower()
            issues: List[str] = []
            if s["rom"] < 30:
                issues.append("amplitude reduzida")
            if s["vel_media"] < 20:
                issues.append("menor velocidade média")
            if s["regularidade"] == "Irregular":
                issues.append("maior irregularidade")
            if issues:
                p2_parts.append(f"O dedo {nome} apresentou {', '.join(issues)}.")
        if p2_parts:
            paragraphs.append(" ".join(p2_parts))

    return "\n\n".join(paragraphs)


# =============================================================================
# 5. GERAÇÃO DO PDF
# =============================================================================

class _ReportPDF(FPDF):
    """PDF customizado com cabeçalho e rodapé de página."""

    def __init__(self, logo_path: Optional[str] = None):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.logo_path = logo_path
        self.set_auto_page_break(auto=True, margin=20)

    def header(self):
        # Fundo do cabeçalho
        self.set_fill_color(230, 242, 255)  # azul claro
        self.rect(0, 0, 210, 28, style="F")

        # Logotipo (se presente)
        x_text = 10
        if self.logo_path and os.path.isfile(self.logo_path):
            try:
                self.image(self.logo_path, x=8, y=3, h=22)
                x_text = 35
            except Exception:
                pass

        # Título do relatório
        self.set_text_color(30, 50, 80)
        self.set_font("Helvetica", "B", 11)
        self.set_xy(x_text, 12)
        _cell(self, 0, 5, REPORT_TITLE, align="L")

        # Linha decorativa
        self.set_draw_color(100, 150, 220)
        self.set_line_width(0.8)
        self.line(10, 28, 200, 28)

        self.ln(32)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(130, 130, 130)
        _cell(self, 0, 5, f"Página {self.page_no()}/{{nb}}", align="C")


def _add_identification_block(
    pdf: _ReportPDF,
    patient_name: str,
    session_start: float,
    session_end: float,
    side: str,
    observation: str,
) -> None:
    """Adiciona o bloco de identificação do paciente e da sessão."""
    y_start = pdf.get_y()
    pdf.set_draw_color(180, 180, 190)
    pdf.set_line_width(0.3)

    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(40, 40, 50)
    _cell(pdf, 0, 7, "Identificação do Paciente e da Sessão", ln=True)

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(60, 60, 70)

    start_dt = datetime.fromtimestamp(session_start) if session_start > 0 else None
    end_dt = datetime.fromtimestamp(session_end) if session_end > 0 else None
    now_dt = datetime.now()

    duration_s = session_end - session_start if session_end > session_start else 0
    duration_min = duration_s / 60.0

    fields = [
        ("Paciente:",        patient_name or "Não informado"),
        ("Data da sessão:",  start_dt.strftime("%Y-%m-%d") if start_dt else "-"),
        ("Horário:",         f"{start_dt.strftime('%H:%M:%S') if start_dt else '-'} às {end_dt.strftime('%H:%M:%S') if end_dt else '-'} ({duration_min:.1f} min)"),
        ("Relatório gerado:", now_dt.strftime("%Y-%m-%d %H:%M:%S")),
        ("Lado avaliado:",   side or "Não informado"),
    ]

    for label, value in fields:
        pdf.set_font("Helvetica", "B", 9)
        _cell(pdf, 42, 5, label)
        pdf.set_font("Helvetica", "", 9)
        _cell(pdf, 0, 5, value, ln=True)

    # Observação automática
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(40, 40, 50)
    _cell(pdf, 42, 5, "Observação:")
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(80, 80, 90)
    _multi_cell(pdf, 0, 4.5, observation)

    # Borda ao redor do bloco
    y_end = pdf.get_y() + 2
    pdf.rect(8, y_start - 2, 194, y_end - y_start + 4, style="D")
    pdf.ln(5)


def _add_main_table(
    pdf: _ReportPDF,
    summary: Dict[str, Dict[str, Any]],
) -> None:
    """Adiciona a tabela principal de métricas por dedo."""
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(40, 40, 50)
    _cell(pdf, 0, 7, "Tabela Principal — Métricas por Dedo", ln=True)

    headers = [
        "Dedo", "TAM\nfinal", "TAM\nmédio", "TAM\nmáx.", "TAM\nmín.",
        "Ampl.", "Vel.\nMédia", "Vel.\nPico", "Freq.", "Reg.", "Articular",
    ]
    col_widths = [22, 15, 15, 15, 15, 15, 15, 15, 14, 17, 18]

    # Cabeçalho da tabela
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

    # Dados por dedo
    pdf.set_font("Helvetica", "", 7)
    row_h = 7

    for idx, finger in enumerate(FINGERS):
        s = summary.get(finger, _empty_finger_summary(finger))

        # Efeito zebrado
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
            f"{s['vel_media']:.0f}°/s",
            f"{s['vel_pico']:.0f}°/s",
            f"{s['freq_hz']:.2f}Hz",
            s["regularidade"],
            s["articular_class"]["rotulo"],
        ]

        for i, val in enumerate(values):
            # Cor especial para a classificação ASSH
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
    """Adiciona blocos explicativos de classificação funcional por dedo."""
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(40, 40, 50)
    _cell(pdf, 0, 7, "Avaliação Funcional Híbrida", ln=True)
    pdf.ln(2)

    for idx, finger in enumerate(FINGERS):
        s = summary.get(finger, _empty_finger_summary(finger))

        pdf.set_fill_color(248, 248, 252) if idx % 2 == 0 else pdf.set_fill_color(255, 255, 255)
        pdf.rect(10, pdf.get_y(), 190, 24, style="F")

        # Cabeçalho do dedo
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(30, 30, 40)
        _cell(pdf, 0, 5, f" {FINGER_LABELS[finger]}:", ln=True)

        # Itens
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(50, 50, 60)

        # Articular
        _cell(pdf, 5, 4, "")
        _cell(pdf, 55, 4, "Classificação articular (TAM):")
        pdf.set_font("Helvetica", "B", 8)
        color_art = _hex_to_rgb(s["articular_class"]["cor"])
        pdf.set_text_color(*color_art)
        _cell(pdf, 0, 4, s["articular_class"]["rotulo"], ln=True)

        # Funcional
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(50, 50, 60)
        _cell(pdf, 5, 4, "")
        _cell(pdf, 55, 4, "Classificação funcional da sessão:")
        pdf.set_font("Helvetica", "B", 8)
        color_func = _hex_to_rgb(s["functional_class"]["cor"])
        pdf.set_text_color(*color_func)
        _cell(pdf, 0, 4, s["functional_class"]["rotulo"], ln=True)

        # Híbrida
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(50, 50, 60)
        _cell(pdf, 5, 4, "")
        _cell(pdf, 55, 4, "Classificação híbrida final:")
        pdf.set_font("Helvetica", "B", 8)
        color_hyb = _hex_to_rgb(s["hybrid_class"]["cor"])
        pdf.set_text_color(*color_hyb)
        _cell(pdf, 0, 4, s["hybrid_class"]["rotulo"], ln=True)

        # Justificativa
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(80, 80, 90)
        _cell(pdf, 5, 4, "")
        _multi_cell(pdf, 0, 4, f"Justificativa: {s['hybrid_class']['explicacao']}")
        pdf.ln(3)

    pdf.ln(3)


def _add_complementary_table(
    pdf: _ReportPDF,
    summary: Dict[str, Dict[str, Any]],
) -> None:
    """Adiciona a tabela suplementar com médias articulares."""
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(40, 40, 50)
    _cell(pdf, 0, 7, "Tabela Suplementar — Médias Articulares", ln=True)

    headers = ["Dedo", "MCP média", "PIP / IP média", "DIP média"]
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
    """Adiciona a legenda clínica de abreviações."""
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(40, 40, 50)
    _cell(pdf, 0, 7, "Legenda Clínica", ln=True)

    legends = [
        ("TAM (Total Active Motion)",
         "Soma das amplitudes de movimento ativo das principais articulações do dedo, utilizada como indicador funcional global de movimento."),
        ("TAM do Polegar",
         "Soma de MCP e IP do polegar. TAM anatômico máximo ~120°. Classificação ASSH adaptada proporcionalmente."),
        ("MCP (Metacarpofalângica)",
         "Articulação na base do dedo."),
        ("PIP (Interfalângica Proximal)",
         "Articulação intermediária do dedo."),
        ("DIP (Interfalângica Distal)",
         "Articulação próxima à ponta do dedo."),
        ("IP (Interfalângica — Polegar)",
         "Articulação entre as falanges do polegar (equivalente à DIP dos dedos longos)."),
        ("ASSH",
         "Classificação funcional (dedos longos): Excelente (>=260°), Bom (195–259°), Razoável (130–194°), Ruim (<130°)."),
        ("ASSH (Polegar)",
         "Classificação funcional adaptada (polegar): Excelente (>=110°), Bom (80–109°), Razoável (50–79°), Ruim (<50°)."),
        ("TAM final",
         "Valor de mobilidade total do dedo no encerramento da sessão."),
        ("TAM médio",
         "Mobilidade total média do dedo ao longo de toda a sessão."),
        ("ROM (Amplitude)",
         "Diferença entre os valores máximo e mínimo de movimento durante a sessão."),
        ("Velocidade média",
         "Velocidade angular média do movimento durante a sessão (°/s)."),
        ("Velocidade de pico",
         "Velocidade angular máxima registrada (°/s)."),
        ("Frequência",
         "Taxa de repetições de movimento durante a sessão (Hz)."),
        ("Regularidade temporal",
         "Consistência do padrão de movimento ao longo do tempo (CV dos intervalos entre picos)."),
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


def _add_footer_technical(
    pdf: _ReportPDF,
    filter_mode: Optional[str],
    filter_mode_assumed: bool,
    demo_mode: bool = False,
) -> None:
    """Adiciona o rodapé técnico, incluindo o modo de filtragem real da sessão."""
    pdf.set_draw_color(180, 180, 190)
    pdf.set_line_width(0.3)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(3)

    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(100, 100, 110)
    footer_method = build_footer_method_text(filter_mode, filter_mode_assumed)
    _multi_cell(pdf, 0, 4, footer_method)
    pdf.ln(1)

    # Aviso de demonstração: bloco próprio, separado do texto de método
    # acima — build_demo_mode_warning_text() devolve "" para sessões
    # clínicas, então nada é desenhado nesse caso. Fonte maior, negrito e
    # vermelho mais saturado que o aviso legal abaixo, para se destacar
    # como o alerta mais sério do rodapé.
    demo_warning = build_demo_mode_warning_text(demo_mode)
    if demo_warning:
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(200, 30, 30)
        _multi_cell(pdf, 0, 4.5, demo_warning)
        pdf.ln(1)

    pdf.set_font("Helvetica", "B", 7)
    pdf.set_text_color(180, 80, 80)
    _multi_cell(pdf, 0, 4, f"Aviso legal: {FOOTER_DISCLAIMER}")


# =============================================================================
# 6. FUNÇÃO PRINCIPAL
# =============================================================================

def generate_pdf_report(
    csv_path: str,
    patient_name: str = "",
    side: str = "",
    logo_path: Optional[str] = None,
    output_path: Optional[str] = None,
) -> str:
    """
    Gera o relatório clínico completo em PDF a partir do CSV da sessão.

    Parâmetros:
        csv_path     : caminho do CSV gerado pela sessão
        patient_name : nome completo do paciente
        side         : lado avaliado (ex.: "Direita", "Esquerda")
        logo_path    : caminho para logotipo institucional (PNG/JPG), opcional
        output_path  : caminho de saída do PDF; se None, gerado automaticamente

    Retorna:
        caminho do arquivo PDF gerado
    """
    if output_path is None:
        base = os.path.splitext(csv_path)[0]
        output_path = f"{base}_report.pdf"

    # Diretório temporário para gráficos
    plot_dir = os.path.join(os.path.dirname(csv_path) or ".", "_report_plots")
    os.makedirs(plot_dir, exist_ok=True)

    print("  [1/5] Lendo CSV da sessão...")
    data = load_session_csv(csv_path)

    if data["n_frames"] < 5:
        print("  AVISO: CSV possui pouquíssimos quadros. Os dados do relatório podem ser limitados.")

    print("  [2/5] Calculando métricas por dedo...")
    summary = compute_session_summary(data)

    print("  [3/5] Gerando gráficos...")
    tam_plot_path = os.path.join(plot_dir, "tam_overall.png")
    generate_tam_plot(data, tam_plot_path)
    individual_paths = generate_individual_plots(data, plot_dir)

    print("  [4/5] Gerando texto interpretativo...")
    observation = build_clinical_observation(summary)
    interpretation = _build_interpretation(summary)

    print("  [5/5] Montando PDF...")
    pdf = _ReportPDF(logo_path=logo_path)
    pdf.alias_nb_pages()
    pdf.add_page()

    # --- PÁGINA 1 ---

    # Bloco de identificação
    _add_identification_block(
        pdf,
        patient_name=patient_name,
        session_start=data["session_start"],
        session_end=data["session_end"],
        side=side,
        observation=observation,
    )

    # Tabela principal
    _add_main_table(pdf, summary)

    # Blocos funcionais
    _add_functional_blocks(pdf, summary)

    # Tabela suplementar
    _add_complementary_table(pdf, summary)

    # --- PÁGINA 2 ---
    pdf.add_page()

    # Gráfico geral
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(40, 40, 50)
    _cell(pdf, 0, 7, "Gráfico de TAM ao Longo da Sessão", ln=True)

    if os.path.isfile(tam_plot_path):
        pdf.image(tam_plot_path, x=10, w=190)
        pdf.ln(3)

    # Gráficos individuais
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(40, 40, 50)
    _cell(pdf, 0, 7, "Gráficos Individuais por Dedo", ln=True)

    # Layout de grade 2×3
    x_positions = [10, 105]
    img_w = 90
    col_idx = 0

    for finger in FINGERS:
        path = individual_paths.get(finger)
        if path and os.path.isfile(path):
            x = x_positions[col_idx % 2]
            # Verifica se é necessária uma nova página
            if pdf.get_y() > 230:
                pdf.add_page()

            pdf.image(path, x=x, y=pdf.get_y(), w=img_w)
            col_idx += 1
            if col_idx % 2 == 0:
                pdf.ln(65)  # altura aproximada do gráfico

    if col_idx % 2 != 0:
        pdf.ln(65)

    # Verifica espaço para o texto
    if pdf.get_y() > 200:
        pdf.add_page()

    # Texto interpretativo
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(40, 40, 50)
    _cell(pdf, 0, 7, "Interpretação Clínica", ln=True)

    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(50, 50, 60)
    _multi_cell(pdf, 0, 4.5, interpretation)
    pdf.ln(5)

    # Legenda clínica
    if pdf.get_y() > 220:
        pdf.add_page()
    _add_legend(pdf)

    # Rodapé técnico
    if pdf.get_y() > 250:
        pdf.add_page()
    _add_footer_technical(
        pdf, data["filter_mode"], data["filter_mode_assumed"], data["demo_mode"]
    )

    # Salva o PDF
    pdf.output(output_path)

    # Limpeza dos gráficos temporários
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

    print(f"\n  Relatório PDF gerado: {output_path}")
    return output_path
