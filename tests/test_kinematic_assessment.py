"""
tests/test_kinematic_assessment.py — Suíte de testes do motor de cálculo goniométrico
========================================================================================

Testa o pipeline científico puro (sem UI, sem câmera, sem threads):
  - DigitalGoniometer.compute_all() e classify_tam() (goniometry.py) — cálculo
    de ângulos e classificação clínica do TAM a partir de landmarks sintéticos.
  - assh_classify() / assh_classify_thumb() / classify_hand_state()
    (dashboard_utils.py) — classificação ASSH usada pelo painel em tempo real.
  - GoniometryCSVLogger (goniometry_csv.py) — gravação e formato do CSV de sessão.

Landmarks de teste são construídos manualmente via MockLandmark (não vêm do
MediaPipe), permitindo validar casos anatômicos conhecidos (mão reta, mão
fechada) sem depender de captura de vídeo real.
"""

import pytest
import numpy as np
from goniometry import DigitalGoniometer, TAM_CLASSIFICATION_THUMB
from dashboard_utils import assh_classify, assh_classify_thumb, classify_hand_state
from goniometry_csv import GoniometryCSVLogger
import os
import tempfile
import csv

class MockLandmark:
    def __init__(self, x, y, z):
        self.x = x
        self.y = y
        self.z = z

def create_straight_hand():
    """Cria uma mão aberta com todos os dedos retos (ângulos ≈ 0)."""
    lms = [MockLandmark(0, 0, 0) for _ in range(21)]
    
    # Punho
    lms[0] = MockLandmark(0.5, 1.0, 0.0)
    
    # Indicador (colinear)
    lms[5] = MockLandmark(0.4, 0.8, 0.0)
    lms[6] = MockLandmark(0.3, 0.6, 0.0)
    lms[7] = MockLandmark(0.2, 0.4, 0.0)
    lms[8] = MockLandmark(0.1, 0.2, 0.0)
    
    # Médio
    lms[9]  = MockLandmark(0.5, 0.8, 0.0)
    lms[10] = MockLandmark(0.5, 0.6, 0.0)
    lms[11] = MockLandmark(0.5, 0.4, 0.0)
    lms[12] = MockLandmark(0.5, 0.2, 0.0)
    
    # Anelar
    lms[13] = MockLandmark(0.6, 0.8, 0.0)
    lms[14] = MockLandmark(0.7, 0.6, 0.0)
    lms[15] = MockLandmark(0.8, 0.4, 0.0)
    lms[16] = MockLandmark(0.9, 0.2, 0.0)
    
    # Mínimo
    lms[17] = MockLandmark(0.7, 0.8, 0.0)
    lms[18] = MockLandmark(0.9, 0.6, 0.0)
    lms[19] = MockLandmark(1.1, 0.4, 0.0)
    lms[20] = MockLandmark(1.3, 0.2, 0.0)
    
    # Polegar
    lms[1] = MockLandmark(0.3, 0.9, 0.0)
    lms[2] = MockLandmark(0.1, 0.8, 0.0)
    lms[3] = MockLandmark(-0.1, 0.7, 0.0)
    lms[4] = MockLandmark(-0.3, 0.6, 0.0)
    
    return lms

def create_flexed_hand():
    """Cria uma mão flexionada para dentro (dobrada no eixo Z)."""
    lms = create_straight_hand()
    
    # A normal será baseada em wrist(0.5, 1.0, 0), index_mcp(0.4, 0.8, 0), pinky_mcp(0.7, 0.8, 0)
    # v1 = index_mcp - wrist = (-0.1, -0.2, 0)
    # v2 = pinky_mcp - wrist = (0.2, -0.2, 0)
    # normal (após correção v2 x v1) = (0.2, -0.2, 0) x (-0.1, -0.2, 0) = (0, 0, -0.04 - 0.02) = (0, 0, -0.06)
    # Portanto, a normal aponta para -Z (dorso da mão nas coordenadas do MediaPipe)
    # A flexão deve ocorrer na direção +Z para ter sinal positivo.
    
    # Flexiona o indicador em Z positivo
    lms[6] = MockLandmark(0.4, 0.8, 0.2)  # PIP flexionado
    lms[7] = MockLandmark(0.4, 0.9, 0.3)  # DIP flexionado
    lms[8] = MockLandmark(0.4, 1.0, 0.2)  # TIP flexionado
    
    # Flexiona o médio
    lms[10] = MockLandmark(0.5, 0.8, 0.2)
    lms[11] = MockLandmark(0.5, 0.9, 0.3)
    lms[12] = MockLandmark(0.5, 1.0, 0.2)
    
    # Flexiona o anelar
    lms[14] = MockLandmark(0.6, 0.8, 0.2)
    lms[15] = MockLandmark(0.6, 0.9, 0.3)
    lms[16] = MockLandmark(0.6, 1.0, 0.2)
    
    # Flexiona o mínimo
    lms[18] = MockLandmark(0.7, 0.8, 0.2)
    lms[19] = MockLandmark(0.7, 0.9, 0.3)
    lms[20] = MockLandmark(0.7, 1.0, 0.2)
    
    # Flexiona o polegar
    lms[3] = MockLandmark(0.1, 0.8, 0.2)
    lms[4] = MockLandmark(0.1, 0.9, 0.3)
    
    return lms

def test_straight_hand_angles():
    # 1. Mão aberta → ângulos próximos de 0°
    lms = create_straight_hand()
    gonio = DigitalGoniometer()
    res = gonio.compute_all(lms, eh_mao_direita=True)
    
    for finger in ["INDEX", "MIDDLE", "RING", "PINKY"]:
        assert abs(res[finger]["MCP"]) < 5.0
        assert abs(res[finger]["PIP"]) < 5.0
        assert abs(res[finger]["DIP"]) < 5.0
        assert abs(res[finger]["TAM"]) < 10.0

def test_flexed_hand_angles_positive():
    # 2. Mão fechada → ângulos positivos fisiológicos
    # 8. Valores negativos não ocorrem na flexão normal
    lms = create_flexed_hand()
    gonio = DigitalGoniometer()
    res = gonio.compute_all(lms, eh_mao_direita=True)
    
    for finger in ["INDEX", "MIDDLE", "RING", "PINKY"]:
        assert res[finger]["MCP"] > 0
        assert res[finger]["PIP"] > 0
        assert res[finger]["DIP"] > 0

    assert res["THUMB"]["MCP"] > 0
    assert res["THUMB"]["IP"] > 0

def test_tam_increases_with_flexion():
    # 3. TAM dos dedos longos aumenta com a flexão
    gonio = DigitalGoniometer()
    res_straight = gonio.compute_all(create_straight_hand(), eh_mao_direita=True)
    res_flexed = gonio.compute_all(create_flexed_hand(), eh_mao_direita=True)
    
    for finger in ["INDEX", "MIDDLE", "RING", "PINKY"]:
        assert res_flexed[finger]["TAM"] > res_straight[finger]["TAM"]

def test_thumb_tam_is_calculated():
    # 4. TAM do polegar é calculado e incluído no resultado
    gonio = DigitalGoniometer()
    res = gonio.compute_all(create_straight_hand(), eh_mao_direita=True)
    
    assert "THUMB" in res
    assert "TAM" in res["THUMB"]
    assert res["THUMB"]["TAM"] >= 0

def test_csv_contains_thumb_tam():
    # 5. CSV contém THUMB_TAM — verifica cabeçalho e gravação
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "test.csv")
        logger = GoniometryCSVLogger(csv_path)
        
        gonio = DigitalGoniometer()
        angles = gonio.compute_all(create_flexed_hand(), eh_mao_direita=True)
        
        logger.log(1, angles)
        logger.close()
        
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            assert "THUMB_TAM" in reader.fieldnames
            
            rows = list(reader)
            assert len(rows) == 1
            assert float(rows[0]["THUMB_TAM"]) == angles["THUMB"]["TAM"]

def test_csv_writes_empty_cell_for_none_value():
    # 5b. Valor None em uma articulação deve gravar célula vazia no CSV,
    # nunca a string literal "None" — e não deve levantar exceção.
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "test_none.csv")
        logger = GoniometryCSVLogger(csv_path)

        gonio = DigitalGoniometer()
        angles = gonio.compute_all(create_flexed_hand(), eh_mao_direita=True)
        angles["INDEX"]["MCP"] = None

        logger.log(1, angles)
        logger.close()

        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert rows[0]["INDEX_MCP"] == ""

def test_csv_writes_empty_cell_for_nan_and_inf_values():
    # 5c. NaN e infinito também devem virar célula vazia, nunca "nan"/"inf".
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "test_naninf.csv")
        logger = GoniometryCSVLogger(csv_path)

        gonio = DigitalGoniometer()
        angles = gonio.compute_all(create_flexed_hand(), eh_mao_direita=True)
        angles["INDEX"]["MCP"] = float("nan")
        angles["INDEX"]["PIP"] = float("inf")
        angles["MIDDLE"]["MCP"] = float("-inf")

        logger.log(1, angles)
        logger.close()

        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert rows[0]["INDEX_MCP"] == ""
            assert rows[0]["INDEX_PIP"] == ""
            assert rows[0]["MIDDLE_MCP"] == ""
            # Garantia extra: nenhuma célula desta linha contém as strings proibidas.
            for value in rows[0].values():
                assert value.lower() not in ("none", "nan", "inf", "-inf")

def test_thumb_classification_logic():
    # 6. Classificação do polegar não utiliza a escala dos outros dedos
    label_thumb, _ = assh_classify_thumb(100.0)
    label_others, _ = assh_classify(100.0)
    
    # 100 graus é "Bom" para o polegar (máx ~120), mas "Ruim" para dedo longo (máx ~270)
    assert label_thumb == "Bom"
    assert label_others == "Ruim"
    
def test_dashboard_utils_classify_hand_state():
    # 7. Funções utilitárias e do painel não quebram com THUMB_TAM
    gonio = DigitalGoniometer()
    angles = gonio.compute_all(create_flexed_hand(), eh_mao_direita=True)
    
    # Força o TAM do polegar para estado fechado (>= 85.0)
    angles["THUMB"]["TAM"] = 90.0
    
    state = classify_hand_state(angles)
    assert "estados_dedos" in state
    assert "THUMB" in state["estados_dedos"]
    assert state["estados_dedos"]["THUMB"]["TAM"] == 90.0
    assert state["estados_dedos"]["THUMB"]["fechado"] == True
    assert state["estados_dedos"]["THUMB"]["rotulo_assh"] == "Bom"


# =============================================================================
# Fase 5 — testes de regressão para filter_mode no CSV
# =============================================================================
#
# GoniometryCSVLogger.log() aceita filter_mode (default "EMA_KALMAN" para
# preservar chamadas antigas sem esse parâmetro) e grava a coluna sempre
# como a última do cabeçalho.

@pytest.mark.parametrize("mode", ["RAW", "EMA", "KALMAN", "EMA_KALMAN"])
def test_csv_logger_writes_filter_mode_as_last_column(mode):
    # A. filter_mode deve aparecer como a ÚLTIMA coluna do cabeçalho, com o
    # valor exato do modo informado, sem afetar nenhuma coluna existente.
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "test_filter_mode.csv")
        logger = GoniometryCSVLogger(csv_path)

        gonio = DigitalGoniometer()
        angles = gonio.compute_all(create_flexed_hand(), eh_mao_direita=True)

        logger.log(1, angles, filter_mode=mode)
        logger.close()

        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames[-1] == "filter_mode"
            # As 24 colunas atuais continuam presentes, na mesma ordem.
            assert reader.fieldnames[:-1] == [
                "timestamp", "frame_id",
                "INDEX_MCP", "INDEX_PIP", "INDEX_DIP", "INDEX_ABD", "INDEX_TAM",
                "MIDDLE_MCP", "MIDDLE_PIP", "MIDDLE_DIP", "MIDDLE_ABD", "MIDDLE_TAM",
                "RING_MCP", "RING_PIP", "RING_DIP", "RING_ABD", "RING_TAM",
                "PINKY_MCP", "PINKY_PIP", "PINKY_DIP", "PINKY_ABD", "PINKY_TAM",
                "THUMB_MCP", "THUMB_IP", "THUMB_TAM",
            ]

            row = list(reader)[0]
            assert row["filter_mode"] == mode
            # Continua sendo o mesmo valor clínico de sempre, sem mudança de precisão.
            assert float(row["THUMB_TAM"]) == angles["THUMB"]["TAM"]


def test_csv_logger_filter_mode_is_not_written_as_numeric_data():
    # A. filter_mode é um rótulo textual, não deve ser interpretável como
    # número — protege contra alguém tratar essa coluna como dado clínico.
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "test_filter_mode_text.csv")
        logger = GoniometryCSVLogger(csv_path)

        gonio = DigitalGoniometer()
        angles = gonio.compute_all(create_flexed_hand(), eh_mao_direita=True)
        logger.log(1, angles, filter_mode="EMA_KALMAN")
        logger.close()

        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            row = list(reader)[0]
            with pytest.raises(ValueError):
                float(row["filter_mode"])


def test_csv_logger_without_filter_mode_defaults_to_ema_kalman():
    # B. Retrocompatibilidade da API Python: chamar log() sem informar
    # filter_mode (como todo o código anterior à Fase 5 já faz) deve
    # continuar funcionando, e a coluna nova deve assumir "EMA_KALMAN" —
    # o modo padrão seguro. Isto testa o DEFAULT DO MÉTODO, não uma
    # afirmação sobre como CSVs já gravados no passado devem ser lidos
    # (isso é responsabilidade de load_session_csv(), testado em
    # tests/test_session_report.py).
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "test_no_mode_arg.csv")
        logger = GoniometryCSVLogger(csv_path)

        gonio = DigitalGoniometer()
        angles = gonio.compute_all(create_flexed_hand(), eh_mao_direita=True)

        logger.log(1, angles)  # chamada antiga, sem filter_mode
        logger.close()

        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            row = list(reader)[0]
            assert row.get("filter_mode") == "EMA_KALMAN"
