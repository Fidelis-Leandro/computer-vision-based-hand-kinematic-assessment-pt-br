"""
outputs/tam_to_servo.py — Mapeamento fixo TAM (graus) -> posição de servo
==========================================================================

Módulo puro (sem I/O, sem Qt, sem pyfirmata) que converte o TAM (Total Active
Motion) de cada dedo, já calculado e suavizado pelo pipeline goniométrico
existente (goniometry.py + smoothing.py), em uma posição de servo (0-180)
para a mão robótica.

IMPORTANTE — limites iniciais de referência:
    Os valores de TAM_MAX e SERVO_CLOSED abaixo foram copiados dos parâmetros
    já usados pelo projeto "Mão robo" (src/outputs/arduino_output.py,
    VALORES_FECHADOS) para ESTA MESMA mão física. São um ponto de partida,
    não uma calibração validada para todo hardware. Devem ser testados
    cuidadosamente (um servo por vez, ver roteiro de teste manual) antes de
    uso contínuo. Esta versão não implementa calibração nem tela de ajuste —
    qualquer mudança nesses limites é feita editando as constantes abaixo.

Este módulo não conhece pyfirmata, threads ou o Arduino. Isso o torna
testável isoladamente (ver tests/test_tam_to_servo.py).
"""

import math
from typing import Dict, Optional

# =============================================================================
# ORDEM E PINAGEM (referência: src/outputs/arduino_output.py da Mão robo)
# =============================================================================

# Ordem física dos dedos na mão robótica: polegar, indicador, médio, anelar, mínimo.
FINGER_ORDER = ["polegar", "indicador", "medio", "anelar", "minimo"]

# Pinos digitais do Arduino configurados como SERVO (StandardFirmata).
#
# PIN_MAP e GONIO_FINGER_KEY (mais abaixo) são duas tabelas independentes,
# com direções de mapeamento diferentes — não confundir uma com a outra:
#   PIN_MAP:         nome do dedo (português) -> número do pino Arduino.
#   GONIO_FINGER_KEY: nome do dedo (português) -> chave usada pela goniometria
#                      (inglês, em ProcessingResult.angles_smooth).
PIN_MAP: Dict[str, int] = {
    "polegar": 10,
    "indicador": 9,
    "medio": 8,
    "anelar": 7,
    "minimo": 6,
}

# =============================================================================
# LIMITES FIXOS INICIAIS (SEM CALIBRAÇÃO POR USUÁRIO NESTA VERSÃO)
# =============================================================================

# TAM máximo esperado por dedo, em graus. Acima disso, satura em SERVO_CLOSED.
#
# Origem destes números: são idênticos ao teto biomecânico teórico definido
# em config.TAM_CEILING do pipeline goniométrico (INDEX/MIDDLE/RING/PINKY:
# 270.0; THUMB: 130.0) — ou seja, o limite anatômico máximo que a fórmula de
# TAM da ASSH permite, não uma medição da amplitude real desta mão física.
# A investigação de amplitude (ver INTEGRACAO_MAO_ROBOTICA.md) mostrou que,
# na prática, indicador e polegar raramente chegam perto desse teto para esta
# pessoa/câmera, enquanto médio e anelar já o atingiram em sessões reais —
# ou seja, um teto uniforme para os 4 dedos longos provavelmente não reflete
# a amplitude alcançável de cada dedo individualmente. Ajustar exige
# validação com dados reais de sessão, não é uma mudança arbitrária de código.
TAM_MAX: Dict[str, float] = {
    "polegar": 130.0,
    "indicador": 270.0,
    "medio": 270.0,
    "anelar": 270.0,
    "minimo": 270.0,
}

# Posição de servo correspondente à mão aberta. Fixo em 0 para todos os dedos.
SERVO_OPEN: Dict[str, int] = {
    "polegar": 0,
    "indicador": 0,
    "medio": 0,
    "anelar": 0,
    "minimo": 0,
}

# Posição de servo correspondente à mão fechada (valores herdados do projeto
# "Mão robo" para este mesmo hardware — ver aviso no topo do arquivo).
SERVO_CLOSED: Dict[str, int] = {
    "polegar": 150,
    "indicador": 180,
    "medio": 160,
    "anelar": 180,
    "minimo": 130,
}

# =============================================================================
# TRADUÇÃO DE NOMES: goniometria (INGLÊS, ProcessingResult.angles_smooth) ->
# nomenclatura da mão robótica (português, FINGER_ORDER acima)
#
# Tabela independente de PIN_MAP (ver comentário acima) — direção diferente:
# esta mapeia para a chave de angles_smooth, não para um pino do Arduino.
# =============================================================================

GONIO_FINGER_KEY: Dict[str, str] = {
    "polegar": "THUMB",
    "indicador": "INDEX",
    "medio": "MIDDLE",
    "anelar": "RING",
    "minimo": "PINKY",
}


def tam_to_servo(finger: str, tam: Optional[float]) -> Optional[int]:
    """
    Converte o TAM (graus) de UM dedo em posição de servo (inteiro).

    Regras:
        - tam None/NaN/infinito -> None (valor inválido, chamador deve descartar
          e manter a última posição válida daquele dedo).
        - tam <= 0 -> SERVO_OPEN[finger].
        - tam >= TAM_MAX[finger] -> SERVO_CLOSED[finger].
        - caso contrário -> interpolação linear entre SERVO_OPEN e SERVO_CLOSED,
          sempre limitada (clamp) ao intervalo [SERVO_OPEN, SERVO_CLOSED].

    Parâmetros:
        finger: uma das chaves de FINGER_ORDER ("polegar", "indicador", ...).
        tam: TAM em graus, tipicamente vindo de angles_smooth[...]["TAM"].

    Retorna:
        Posição de servo (int) ou None se o valor de entrada for inválido
        ou o dedo for desconhecido.
    """
    if finger not in PIN_MAP:
        return None

    if tam is None or isinstance(tam, bool):
        return None

    try:
        tam_f = float(tam)
    except (TypeError, ValueError):
        return None

    if math.isnan(tam_f) or math.isinf(tam_f):
        return None

    servo_open = SERVO_OPEN[finger]
    servo_closed = SERVO_CLOSED[finger]
    tam_max = TAM_MAX[finger]

    if tam_f <= 0.0:
        return servo_open
    if tam_f >= tam_max:
        return servo_closed

    ratio = tam_f / tam_max
    position = servo_open + ratio * (servo_closed - servo_open)

    lo, hi = min(servo_open, servo_closed), max(servo_open, servo_closed)
    position = max(lo, min(hi, position))

    return int(round(position))


def map_all(angles_smooth: Dict[str, Dict[str, float]]) -> Dict[str, Optional[int]]:
    """
    Converte o dicionário completo angles_smooth (saída do pipeline
    goniométrico) em posições de servo para os 5 dedos.

    Parâmetros:
        angles_smooth: dicionário {"INDEX": {"TAM": ..., ...}, "THUMB": {...}, ...}
                        no formato de ProcessingResult.angles_smooth. Pode ser {}
                        (nenhuma mão detectada) ou conter apenas alguns dedos.

    Retorna:
        {"polegar": int|None, "indicador": int|None, "medio": int|None,
         "anelar": int|None, "minimo": int|None}
        Um valor None indica dado ausente/inválido para aquele dedo específico;
        o chamador deve manter a última posição válida conhecida para ele,
        sem descartar os demais dedos.
    """
    result: Dict[str, Optional[int]] = {}
    for finger in FINGER_ORDER:
        gonio_key = GONIO_FINGER_KEY[finger]
        finger_data = angles_smooth.get(gonio_key, {})
        tam = finger_data.get("TAM")
        result[finger] = tam_to_servo(finger, tam)
    return result
