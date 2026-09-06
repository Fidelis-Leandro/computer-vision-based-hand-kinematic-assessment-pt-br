"""
goniometry.py — Goniometria digital baseada em landmarks 3D
===========================================================

Este módulo calcula ângulos articulares da mão a partir dos landmarks do MediaPipe.

Responsabilidades:
    - Converter landmarks anatômicos para vetores numpy 3D.
    - Calcular o plano de referência da mão.
    - Medir ângulos clínicos com sinal.
    - Calcular MCP, PIP, DIP, ABD e TAM para cada dedo.
    - Calcular MCP e IP para o polegar.
    - Classificar o TAM e validar faixas clínicas.

Este módulo é independente de OpenCV.
"""

from typing import Any, Dict, List

import numpy as np

import config

# =============================================================================
# ÍNDICES DOS MARCOS ANATÔMICOS (LANDMARKS)
# =============================================================================

WRIST = 0

THUMB_CMC, THUMB_MCP, THUMB_IP, THUMB_TIP = 1, 2, 3, 4

INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_TIP = 5, 6, 7, 8
MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP = 9, 10, 11, 12
RING_MCP, RING_PIP, RING_DIP, RING_TIP = 13, 14, 15, 16
PINKY_MCP, PINKY_PIP, PINKY_DIP, PINKY_TIP = 17, 18, 19, 20

# =============================================================================
# REFERÊNCIA CLÍNICA
# =============================================================================

NORMAL_RANGES: Dict[str, tuple] = {
    "MCP_flex":  (70.0, 90.0),   # ASSH: flexão da MCP de 70–90° é normal para movimento ativo
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
    (260.0, float("inf"), "Excelente", (50, 220, 130)),
    (195.0, 260.0, "Bom",       (40, 200, 255)),
    (130.0, 195.0, "Razoável",  (50, 130, 255)),
    (0.0,   130.0, "Ruim",      (60, 60, 255)),
]

TAM_CLASSIFICATION_THUMB = [
    (110.0, float("inf"), "Excelente", (50, 220, 130)),
    (80.0,  110.0,        "Bom",       (40, 200, 255)),
    (50.0,   80.0,        "Razoável",  (50, 130, 255)),
    (0.0,    50.0,        "Ruim",      (60, 60, 255)),
]


# =============================================================================
# FUNÇÕES VETORIAIS
# =============================================================================

def _lm_to_array(landmark: Any) -> np.ndarray:
    """
    Converte um landmark do MediaPipe para um vetor numpy [x, y, z].
    """
    return np.array([landmark.x, landmark.y, landmark.z], dtype=np.float64)


def _normalize(v: np.ndarray) -> np.ndarray:
    """
    Normaliza um vetor para comprimento unitário.
    """
    norm = np.linalg.norm(v)
    return v / norm if norm > 1e-9 else np.zeros(3, dtype=np.float64)


def angle_between_vectors_3d(v1: np.ndarray, v2: np.ndarray, normal: np.ndarray) -> float:
    """
    Calcula o ângulo com sinal entre dois vetores 3D.

    O sinal utiliza o plano da mão como referência para distinguir:
    - flexão / abdução (positivo);
    - extensão / hiperextensão / adução (negativo).
    """
    v1 = _normalize(v1)
    v2 = _normalize(v2)

    cos_angle = float(np.clip(np.dot(v1, v2), -1.0, 1.0))
    angle_deg = float(np.degrees(np.arccos(cos_angle)))

    cross = np.cross(v1, v2)
    sign = float(np.dot(cross, normal))

    return angle_deg if sign >= 0 else -angle_deg


def _hand_normal(landmarks: List[Any], eh_mao_direita: bool = True) -> np.ndarray:
    """
    Calcula o vetor normal usado como referência para o plano da mão.

    Para a mão esquerda (`eh_mao_direita=False`), o vetor é invertido
    para preservar a convenção de sinais de flexão/extensão.

    Observação: `cv2.flip()` espelha o quadro visualmente, mas não altera as
    coordenadas `.x`/`.y`/`.z` dos landmarks do MediaPipe — portanto, a correção
    de lateralidade deve ser aplicada aqui, no vetor normal.
    """
    wrist = _lm_to_array(landmarks[WRIST])
    mcp_index = _lm_to_array(landmarks[INDEX_MCP])
    mcp_pinky = _lm_to_array(landmarks[PINKY_MCP])

    v1 = mcp_index - wrist
    v2 = mcp_pinky - wrist

    normal = _normalize(np.cross(v2, v1))
    if not eh_mao_direita:
        normal = -normal
    return normal


def _thumb_local_normal(landmarks: List[Any], hand_normal: np.ndarray) -> np.ndarray:
    """
    Normal estável para o plano de movimento do polegar.

    Derivada exclusivamente do eixo do metacarpo do polegar (`THUMB_CMC -> THUMB_MCP`)
    e da normal dorsal da mão. Ao utilizar apenas `CMC` e `MCP` — sem `IP` ou `TIP` —,
    é completamente independente da posição articular atual do polegar.
    Isso elimina a dependência circular que causava inversão de sinal
    durante a flexão.

    Convenção de sinal resultante:
    - Flexão em direção à palma -> positivo
    - Extensão / abdução para fora -> zero ou negativo

    Parâmetros:
        landmarks   : lista de 21 landmarks do MediaPipe.
        hand_normal : normal dorsal correta (já ajustada para lateralidade)
                      de `_hand_normal()` em `compute_all()`.
    """
    cmc = _lm_to_array(landmarks[THUMB_CMC])
    mcp = _lm_to_array(landmarks[THUMB_MCP])

    # Eixo do metacarpo do polegar — estável, não varia com a flexão da MCP/IP.
    thumb_shaft = _normalize(mcp - cmc)

    # Direção palmar = oposta à normal dorsal.
    palmar = -hand_normal

    # `cross(thumb_axis, palmar)` produz o vetor perpendicular
    # apontando na direção que define a flexão palmar como positiva.
    raw = np.cross(thumb_shaft, palmar)

    norm_mag = np.linalg.norm(raw)
    if norm_mag < 1e-9:
        # Fallback: polegar paralelo à normal da mão (pose anatomicamente extrema).
        return hand_normal

    return _normalize(raw)


# =============================================================================
# GONIÔMETRO DIGITAL
# =============================================================================

class DigitalGoniometer:
    """
    Implementa o cálculo dos ângulos articulares da mão.

    Esta classe encapsula as fórmulas clínicas e convenções de sinal
    para produzir um dicionário estruturado organizado por dedo e articulação.
    """

    def mcp_flex(self, landmarks: List[Any], mcp_idx: int, pip_idx: int, normal: np.ndarray) -> float:
        """
        Calcula a flexão da MCP para um dedo que não seja o polegar.
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
        Calcula a flexão da PIP.
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
        Calcula a flexão da DIP.
        """
        pip = _lm_to_array(landmarks[pip_idx])
        dip = _lm_to_array(landmarks[dip_idx])
        tip = _lm_to_array(landmarks[tip_idx])

        return angle_between_vectors_3d(dip - pip, tip - dip, normal)

    # Referência de abdução por dedo: utiliza o dedo imediatamente adjacente.
    # O uso do dedo médio como referência absoluta para todos os dedos
    # superestimava a abdução do indicador e distorcia a do mínimo.
    _ABD_REFERENCE = {
        INDEX_MCP:  MIDDLE_MCP,   # indicador -> médio
        MIDDLE_MCP: MIDDLE_MCP,   # médio     -> ele mesmo (resultado 0, sem ABD definida)
        RING_MCP:   MIDDLE_MCP,   # anelar    -> médio
        PINKY_MCP:  RING_MCP,     # mínimo    -> anelar
    }

    def mcp_abduction(self, landmarks: List[Any], mcp_idx: int) -> float:
        """
        Calcula a abdução da MCP utilizando o dedo adjacente como referência.

        Referências clínicas:
        - Indicador e Anelar: referência é o dedo Médio.
        - Mínimo: referência é o dedo Anelar.
        - Médio: retorna 0 (nenhuma referência de abdução definida clinicamente).
        """
        ref_idx = self._ABD_REFERENCE.get(mcp_idx, MIDDLE_MCP)
        wrist = _lm_to_array(landmarks[WRIST])
        ref_mcp = _lm_to_array(landmarks[ref_idx])
        current_mcp = _lm_to_array(landmarks[mcp_idx])

        if mcp_idx == ref_idx:
            return 0.0  # o dedo médio não possui referência adjacente

        ref = _normalize(ref_mcp - wrist)
        cur = _normalize(current_mcp - wrist)

        cos_angle = float(np.clip(np.dot(ref, cur), -1.0, 1.0))
        return float(np.degrees(np.arccos(cos_angle)))

    def total_active_motion(self, mcp: float, pip: float, dip: float) -> float:
        """
        Calcula o TAM (Total Active Motion) utilizando a fórmula completa da ASSH.

        Fórmula ASSH:
            `TAM = (MCP + PIP + DIP)_flex - (MCP + PIP + DIP)_deficit`

        Déficit = ângulo negativo (extensão incompleta / contratura em flexão).
        Um paciente com PIP travada em -30° tem esse déficit subtraído do TAM,
        o que não era refletido na fórmula anterior que ignorava valores negativos.
        """
        flex_sum    = max(mcp, 0.0) + max(pip, 0.0) + max(dip, 0.0)
        deficit_sum = abs(min(mcp, 0.0)) + abs(min(pip, 0.0)) + abs(min(dip, 0.0))
        return max(0.0, flex_sum - deficit_sum)

    def total_active_motion_thumb(self, mcp: float, ip: float) -> float:
        """
        TAM do polegar: soma de MCP + IP utilizando protocolo clínico adaptado da ASSH.

        Anatomia diferenciada — o polegar possui apenas duas articulações móveis:
          - MCP: faixa normal de 50–60°
          - IP:  faixa normal de 70–90°
        TAM máximo esperado: ~120–130° (flexão completa do polegar).
        Valores negativos (déficit de extensão) são subtraídos do total.
        """
        flex_sum    = max(0.0, mcp) + max(0.0, ip)
        deficit_sum = abs(min(0.0, mcp)) + abs(min(0.0, ip))
        return max(0.0, flex_sum - deficit_sum)

    def thumb_mcp_flex(self, landmarks: List[Any], normal: np.ndarray) -> float:
        """
        Flexão da MCP do polegar utilizando uma normal LOCAL estável.

        Braço fixo = `THUMB_CMC -> THUMB_MCP` (metacarpo)
        Braço móvel = `THUMB_MCP -> THUMB_IP` (falange proximal)

        A normal do plano de movimento é calculada por `_thumb_local_normal()`,
        que utiliza apenas `CMC`, `MCP` e a normal dorsal da mão — sem depender
        de `IP` ou `TIP`. Isso elimina a dependência circular que anteriormente
        invertia o sinal durante a flexão palmar.

        Esperado:
        - Polegar flexionado em direção à palma (oposição): +40° a +60°
        - Polegar estendido/abduzido para fora            : próximo de 0° ou negativo
        """
        cmc = _lm_to_array(landmarks[THUMB_CMC])
        mcp = _lm_to_array(landmarks[THUMB_MCP])
        ip  = _lm_to_array(landmarks[THUMB_IP])

        # Passa a normal dorsal correta (com lateralidade) para o cálculo local.
        thumb_normal = _thumb_local_normal(landmarks, normal)
        return angle_between_vectors_3d(mcp - cmc, ip - mcp, thumb_normal)

    def thumb_ip_flex(self, landmarks: List[Any], normal: np.ndarray) -> float:
        """
        Flexão da articulação IP do polegar utilizando uma normal LOCAL estável.

        Braço fixo = `THUMB_MCP -> THUMB_IP` (falange proximal)
        Braço móvel = `THUMB_IP -> THUMB_TIP` (falange distal)

        Utiliza a mesma normal local da MCP para manter convenção de sinais coerente.

        Esperado:
        - IP flexionada (ponta do polegar curvando para a palma): +70° a +90°
        - IP estendida                                         : próximo de 0°
        """
        mcp = _lm_to_array(landmarks[THUMB_MCP])
        ip  = _lm_to_array(landmarks[THUMB_IP])
        tip = _lm_to_array(landmarks[THUMB_TIP])

        thumb_normal = _thumb_local_normal(landmarks, normal)
        return angle_between_vectors_3d(ip - mcp, tip - ip, thumb_normal)

    def compute_all(
        self,
        landmarks: List[Any],
        eh_mao_direita: bool = True,
    ) -> Dict[str, Dict[str, float]]:
        """
        Calcula todas as métricas articulares da mão.

        Parâmetros:
            landmarks     : lista de landmarks do MediaPipe (21 pontos).
            eh_mao_direita: True para mão direita, False para mão esquerda.
                            Inverte a normal do plano para corrigir o
                            sinal de flexão/extensão em mãos espelhadas.
        """
        normal = _hand_normal(landmarks, eh_mao_direita=eh_mao_direita)

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

            # O TAM utiliza valores absolutos porque a convenção de sinais
            # (positivo = flexão para mão direita, negativo = flexão para mão esquerda)
            # é um artefato geométrico do sentido da normal, não uma distinção
            # clínica. O TAM mede a amplitude total de movimento independente do lado da mão.
            tam = self.total_active_motion(abs(mcp_angle), abs(pip_angle), abs(dip_angle))

            # Teto biomecânico — limita o TAM ao máximo anatômico deste dedo
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

        # Teto biomecânico — limita o TAM do polegar ao máximo anatômico
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
        Classifica um valor de TAM de acordo com as faixas funcionais de referência.

        Parâmetros:
            tam      : valor de TAM a classificar.
            is_thumb : se `True`, utiliza faixas adaptadas para o polegar
                       (TAM máximo ~120° em vez de ~270°).
        """
        table = TAM_CLASSIFICATION_THUMB if is_thumb else TAM_CLASSIFICATION
        for lo, hi, label, color_bgr in table:
            if lo <= tam < hi:
                return {
                    "label": label,
                    "color_bgr": color_bgr,
                }

        return {
            "label": "Ruim",
            "color_bgr": (60, 60, 255),
        }


# =============================================================================
# CLASSIFICAÇÃO DE INTERVALO NORMAL
# =============================================================================

def is_in_normal_range(finger: str, metric: str, value: float) -> str:
    """
    Determina se um valor está:
    - dentro do intervalo normal;
    - limítrofe (borderline);
    - fora do intervalo esperado.
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