"""
goniometry_overlay.py — Sobreposição visual da mão e goniometria
================================================================

Este módulo gera o painel visual exibido sobre o fluxo da câmera.

Responsabilidades:
- Desenhar o esqueleto da mão.
- Desenhar os braços do goniômetro virtual.
- Desenhar arcos e rótulos angulares.
- Colorir estruturas de acordo com a faixa clínica.
- Exibir a estabilidade qualitativa do filtro por articulação.

O ponto de entrada do módulo é _build_skeleton(), consumido por
workers/processing_worker.py — é o único símbolo daqui que chega à tela.

As métricas clínicas e os cartões por dedo são responsabilidade dos widgets
PyQt6 (ui/finger_card_widget.py e ui/metrics_widget.py); este módulo não
desenha painéis de dados.
"""

import math
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from goniometry import is_in_normal_range

# =============================================================================
# PALETA VISUAL
# =============================================================================

BG_DARK = (26, 26, 26)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GRAY_LIGHT = (180, 180, 180)
GRAY_MID = (110, 110, 110)

COLOR_WRIST = (255, 255, 255)
COLOR_MCP = (0, 220, 220)
COLOR_PIP = (220, 220, 0)
COLOR_DIP = (80, 220, 50)
COLOR_TIP = (200, 200, 200)
COLOR_THUMB = (220, 80, 220)

COLOR_STAT = (60, 60, 230)
COLOR_MOB = (230, 120, 50)
COLOR_AXIS = (255, 255, 0)

COLOR_NORMAL = (50, 220, 130)
COLOR_BORDER = (40, 200, 255)
COLOR_ABNORM = (60, 60, 255)

STAB_STABLE = (50, 220, 130)
STAB_CONV = (40, 200, 255)
STAB_UNSTAB = (60, 60, 255)
STAB_UNINIT = (80, 80, 80)

# Modos sem etapa Kalman (RAW e EMA). Cinza claro: neutro de propósito —
# vermelho acusaria um defeito que não existe, e verde afirmaria uma
# convergência de Kalman que esses modos nem chegam a calcular. Cor própria,
# e não STAB_UNINIT, para continuar distinguindo uma série que está medindo
# de uma que ainda não recebeu nenhuma amostra.
STAB_NO_KALMAN = (150, 150, 150)

ARM_LEN = 55
ARC_RAD = 28
ARC_TICK = 3
ARM_TICK = 3

# =============================================================================
# TOPOLOGIA DA MÃO
# =============================================================================

CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (0, 9), (9, 10), (10, 11), (11, 12),
    (0, 13), (13, 14), (14, 15), (15, 16),
    (0, 17), (17, 18), (18, 19), (19, 20),
    (5, 9), (9, 13), (13, 17),
]

WRIST_CONNS = {(0, 5), (0, 9), (0, 13), (0, 17)}

LM_STYLE = {
    **{0: ("wrist", COLOR_WRIST, 8)},
    **{i: ("thumb", COLOR_THUMB, 5) for i in (1, 2, 3, 4)},
    **{i: ("mcp", COLOR_MCP, 7) for i in (5, 9, 13, 17)},
    **{i: ("pip", COLOR_PIP, 6) for i in (6, 10, 14, 18)},
    **{i: ("dip", COLOR_DIP, 5) for i in (7, 11, 15, 19)},
    **{i: ("tip", COLOR_TIP, 4) for i in (8, 12, 16, 20)},
}

GONIO_JOINTS = [
    (5, 0, 6, "MCP", "INDEX"),
    (6, 5, 7, "PIP", "INDEX"),
    (7, 6, 8, "DIP", "INDEX"),
    (9, 0, 10, "MCP", "MIDDLE"),
    (10, 9, 11, "PIP", "MIDDLE"),
    (11, 10, 12, "DIP", "MIDDLE"),
    (13, 0, 14, "MCP", "RING"),
    (14, 13, 15, "PIP", "RING"),
    (15, 14, 16, "DIP", "RING"),
    (17, 0, 18, "MCP", "PINKY"),
    (18, 17, 19, "PIP", "PINKY"),
    (19, 18, 20, "DIP", "PINKY"),
    (2, 1, 3, "MCP", "THUMB"),
    (3, 2, 4, "IP", "THUMB"),
]

# =============================================================================
# FUNÇÕES AUXILIARES DE DESENHO
# =============================================================================

def _stability_color(status: str) -> Tuple[int, int, int]:
    """
    Cor do ponto de estabilidade, a partir do status de SeriesFilter.stability.

    "sem_filtro" (RAW) e "suavizacao_ema" (EMA) são estados normais de
    operação, não avarias — por isso recebem cinza neutro em vez das cores de
    qualidade de convergência, que só fazem sentido onde o Kalman roda.

    Um status desconhecido cai em STAB_UNINIT: preferimos um ponto neutro a
    uma exceção no meio do desenho do quadro.
    """
    return {
        "estavel": STAB_STABLE,
        "convergindo": STAB_CONV,
        "instavel": STAB_UNSTAB,
        "nao_inicializado": STAB_UNINIT,
        "sem_filtro": STAB_NO_KALMAN,
        "suavizacao_ema": STAB_NO_KALMAN,
    }.get(status, STAB_UNINIT)


def _clinical_color(status: str) -> Tuple[int, int, int]:
    return {
        "normal": COLOR_NORMAL,
        "borderline": COLOR_BORDER,
        "abnormal": COLOR_ABNORM,
    }.get(status, GRAY_LIGHT)


def _lm_px(lm, idx: int, width: int, height: int) -> Tuple[int, int]:
    return int(lm[idx].x * width), int(lm[idx].y * height)


def _n2(v: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(v)
    return v / norm if norm > 1e-6 else v


def _dashed(
    img: np.ndarray,
    p1: Tuple[int, int],
    p2: Tuple[int, int],
    color: Tuple[int, int, int],
    thickness: int = 1,
    dash: int = 8,
    gap: int = 5,
) -> None:
    """
    Desenha uma linha tracejada simples para conexões do punho.
    """
    x1, y1 = p1
    x2, y2 = p2

    length = math.hypot(x2 - x1, y2 - y1)
    if length < 1:
        return

    ux = (x2 - x1) / length
    uy = (y2 - y1) / length

    pos = 0.0
    draw = True
    while pos < length:
        seg = dash if draw else gap
        next_pos = min(pos + seg, length)

        if draw:
            a = (int(x1 + ux * pos), int(y1 + uy * pos))
            b = (int(x1 + ux * next_pos), int(y1 + uy * next_pos))
            cv2.line(img, a, b, color, thickness, cv2.LINE_AA)

        draw = not draw
        pos = next_pos


def _arc(
    img: np.ndarray,
    ctr: Tuple[int, int],
    v1: np.ndarray,
    v2: np.ndarray,
    radius: int,
    color: Tuple[int, int, int],
    thickness: int,
) -> None:
    """
    Desenha um arco angular entre dois vetores 2D.
    """
    a1 = math.degrees(math.atan2(-v1[1], v1[0]))
    a2 = math.degrees(math.atan2(-v2[1], v2[0]))

    diff = (a2 - a1) % 360
    if diff > 180:
        a1, a2 = a2, a1
        diff = 360 - diff

    steps = max(int(diff / 3), 4)
    pts = [
        (
            int(ctr[0] + radius * math.cos(math.radians(a1 + diff * i / steps))),
            int(ctr[1] - radius * math.sin(math.radians(a1 + diff * i / steps))),
        )
        for i in range(steps + 1)
    ]

    for i in range(len(pts) - 1):
        cv2.line(img, pts[i], pts[i + 1], color, thickness, cv2.LINE_AA)


def _alpha_rect(
    img: np.ndarray,
    x: int,
    y: int,
    w: int,
    h: int,
    color: Tuple[int, int, int],
    alpha: float = 0.60,
) -> None:
    """
    Desenha um retângulo semitransparente operando apenas na ROI.

    Otimizado: em vez de copiar a imagem completa (img.copy()),
    opera apenas na região do retângulo, reduzindo a alocação de memória
    de ~1MB para ~500 bytes por chamada.
    """
    img_h, img_w = img.shape[:2]
    # Ajuste para evitar acesso fora dos limites da imagem.
    x1 = max(0, x)
    y1 = max(0, y)
    x2 = min(img_w, x + w)
    y2 = min(img_h, y + h)
    if x2 <= x1 or y2 <= y1:
        return
    roi = img[y1:y2, x1:x2]
    blend = np.full_like(roi, color, dtype=np.uint8)
    cv2.addWeighted(blend, alpha, roi, 1 - alpha, 0, roi)


def _center_text(
    img: np.ndarray,
    text: str,
    y: int,
    width: int,
    color: Tuple[int, int, int] = WHITE,
    scale: float = 0.55,
    thickness: int = 1,
) -> None:
    (tw, _), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_DUPLEX, scale, thickness)
    cv2.putText(
        img,
        text,
        ((width - tw) // 2, y),
        cv2.FONT_HERSHEY_DUPLEX,
        scale,
        color,
        thickness,
        cv2.LINE_AA,
    )


def _put(
    img: np.ndarray,
    text: str,
    x: int,
    y: int,
    color: Tuple[int, int, int] = WHITE,
    scale: float = 0.40,
    thickness: int = 1,
) -> None:
    cv2.putText(
        img,
        text,
        (x, y),
        cv2.FONT_HERSHEY_DUPLEX,
        scale,
        color,
        thickness,
        cv2.LINE_AA,
    )


def _tw(text: str, scale: float = 0.40, thickness: int = 1) -> int:
    (w, _), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_DUPLEX, scale, thickness)
    return w


# =============================================================================
# PAINEL DE ESQUELETO + GONIÔMETRO
# =============================================================================

def _build_skeleton(
    frame: np.ndarray,
    landmarks: List[Any],
    angles: Dict[str, Dict[str, float]],
    pw: int,
    ph: int,
    frozen: bool,
    stability_map: Optional[Dict],
) -> np.ndarray:
    """
    Constrói o painel com o esqueleto da mão e o goniômetro virtual.
    """
    canvas = np.full((ph, pw, 3), BG_DARK, dtype=np.uint8)
    _center_text(canvas, "GONIOMETRIA DIGITAL", 26, pw, WHITE, 0.60)

    if not landmarks:
        _center_text(canvas, "Aguardando detecção da mão...", ph // 2, pw, GRAY_MID, 0.45)
        return canvas

    width, height = pw, ph

    # Desenha o esqueleto básico.
    for a, b in CONNECTIONS:
        p1 = _lm_px(landmarks, a, width, height)
        p2 = _lm_px(landmarks, b, width, height)

        if (a, b) in WRIST_CONNS or (b, a) in WRIST_CONNS:
            _dashed(canvas, p1, p2, (140, 140, 140), 1)
        else:
            cv2.line(canvas, p1, p2, (185, 185, 185), 2, cv2.LINE_AA)

    # Landmarks por categoria anatômica.
    for idx, (_, color, radius) in LM_STYLE.items():
        pt = _lm_px(landmarks, idx, width, height)
        cv2.circle(canvas, pt, radius + 1, BLACK, -1)
        cv2.circle(canvas, pt, radius, color, -1, cv2.LINE_AA)

    # Goniômetro virtual por articulação.
    for ax_i, prox_i, dist_i, joint_type, finger in GONIO_JOINTS:
        center = _lm_px(landmarks, ax_i, width, height)
        pt_prox = _lm_px(landmarks, prox_i, width, height)
        pt_dist = _lm_px(landmarks, dist_i, width, height)

        vs = np.array([center[0] - pt_prox[0], center[1] - pt_prox[1]], dtype=float)
        vm = np.array([pt_dist[0] - center[0], pt_dist[1] - center[1]], dtype=float)

        vsn = _n2(vs)
        vmn = _n2(vm)

        es = (int(center[0] + vsn[0] * ARM_LEN), int(center[1] + vsn[1] * ARM_LEN))
        em = (int(center[0] + vmn[0] * ARM_LEN), int(center[1] + vmn[1] * ARM_LEN))

        angle_val = angles.get(finger, {}).get(joint_type)
        if angle_val is None:
            continue

        clinical_status = is_in_normal_range(finger, joint_type, angle_val)
        arc_color = _clinical_color(clinical_status)

        stability_status = (stability_map or {}).get(finger, {}).get(joint_type, "nao_inicializado")
        stability_color = _stability_color(stability_status)

        cv2.line(canvas, center, es, COLOR_STAT, ARM_TICK, cv2.LINE_AA)
        cv2.circle(canvas, es, 4, COLOR_STAT, -1, cv2.LINE_AA)

        cv2.line(canvas, center, em, COLOR_MOB, ARM_TICK, cv2.LINE_AA)
        cv2.circle(canvas, em, 4, COLOR_MOB, -1, cv2.LINE_AA)

        cv2.circle(canvas, center, 6, COLOR_AXIS, -1, cv2.LINE_AA)
        cv2.circle(canvas, center, 6, WHITE, 1, cv2.LINE_AA)

        _arc(canvas, center, vsn, vmn, ARC_RAD, arc_color, ARC_TICK)

        sign = "-" if angle_val < 0 else ""
        label = f"{joint_type} {sign}{abs(angle_val):.0f}"
        lx, ly = center[0] + 10, center[1] - 8

        tw = _tw(label, 0.42)
        _alpha_rect(canvas, lx - 3, ly - 14, tw + 12, 18, (8, 8, 8), 0.72)
        _put(canvas, label, lx, ly, arc_color, 0.42)
        cv2.circle(canvas, (lx + tw + 8, ly - 6), 4, stability_color, -1, cv2.LINE_AA)

    xs = [int(landmarks[i].x * width) for i in range(21)]
    ys = [int(landmarks[i].y * height) for i in range(21)]
    pad = 22

    cv2.rectangle(
        canvas,
        (max(0, min(xs) - pad), max(0, min(ys) - pad)),
        (min(width - 1, max(xs) + pad), min(height - 1, max(ys) + pad)),
        GRAY_MID,
        1,
    )

    lx, ly = 8, ph - 30
    cv2.line(canvas, (lx, ly), (lx + 20, ly), COLOR_STAT, 2)
    _put(canvas, "Fixo", lx + 24, ly + 4, GRAY_LIGHT, 0.28)

    cv2.line(canvas, (lx + 130, ly), (lx + 150, ly), COLOR_MOB, 2)
    _put(canvas, "Móvel", lx + 154, ly + 4, GRAY_LIGHT, 0.28)

    cv2.circle(canvas, (lx + 210, ly), 4, COLOR_AXIS, -1)
    _put(canvas, "Eixo", lx + 218, ly + 4, GRAY_LIGHT, 0.28)

    if frozen:
        _center_text(canvas, "[ QUADRO CONGELADO ]", ph - 14, pw, COLOR_BORDER, 0.38)
        cv2.rectangle(canvas, (2, 2), (pw - 2, ph - 2), COLOR_BORDER, 2)

    return canvas
