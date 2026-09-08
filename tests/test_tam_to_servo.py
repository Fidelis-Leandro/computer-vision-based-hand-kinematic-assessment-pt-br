"""
tests/test_tam_to_servo.py — Testes unitários do mapeamento TAM -> servo
==========================================================================

Cobre apenas outputs/tam_to_servo.py, que é puro (sem I/O, sem Qt, sem
pyfirmata) e portanto não requer hardware nem mocks para ser testado.
"""

import math

import pytest

from outputs.tam_to_servo import (
    FINGER_ORDER,
    SERVO_CLOSED,
    SERVO_OPEN,
    TAM_MAX,
    map_all,
    tam_to_servo,
)


class TestTamToServo:
    @pytest.mark.parametrize("finger", FINGER_ORDER)
    def test_tam_zero_returns_open(self, finger):
        assert tam_to_servo(finger, 0.0) == SERVO_OPEN[finger]

    @pytest.mark.parametrize("finger", FINGER_ORDER)
    def test_tam_negative_clamps_to_open(self, finger):
        assert tam_to_servo(finger, -50.0) == SERVO_OPEN[finger]

    @pytest.mark.parametrize("finger", FINGER_ORDER)
    def test_tam_at_max_returns_closed(self, finger):
        assert tam_to_servo(finger, TAM_MAX[finger]) == SERVO_CLOSED[finger]

    @pytest.mark.parametrize("finger", FINGER_ORDER)
    def test_tam_above_max_clamps_to_closed(self, finger):
        assert tam_to_servo(finger, TAM_MAX[finger] + 1000.0) == SERVO_CLOSED[finger]

    def test_tam_half_scale_is_between_open_and_closed(self):
        finger = "indicador"
        half = TAM_MAX[finger] / 2.0
        pos = tam_to_servo(finger, half)
        lo, hi = sorted((SERVO_OPEN[finger], SERVO_CLOSED[finger]))
        assert lo <= pos <= hi
        # Aproximadamente o ponto médio da escala (mapeamento linear).
        expected_mid = SERVO_OPEN[finger] + 0.5 * (SERVO_CLOSED[finger] - SERVO_OPEN[finger])
        assert abs(pos - expected_mid) <= 1

    @pytest.mark.parametrize("invalid", [None, math.nan, math.inf, -math.inf])
    def test_invalid_values_return_none(self, invalid):
        assert tam_to_servo("polegar", invalid) is None

    def test_unknown_finger_returns_none(self):
        assert tam_to_servo("mao_fantasma", 100.0) is None

    def test_non_numeric_value_returns_none(self):
        assert tam_to_servo("polegar", "abc") is None

    def test_boolean_value_returns_none(self):
        # bool é subclasse de int em Python; deve ser rejeitado explicitamente.
        assert tam_to_servo("polegar", True) is None


class TestMapAll:
    def test_full_angles_smooth_maps_all_fingers(self):
        angles_smooth = {
            "THUMB": {"MCP": 40.0, "IP": 60.0, "TAM": 65.0},
            "INDEX": {"MCP": 80.0, "PIP": 90.0, "DIP": 60.0, "ABD": 5.0, "TAM": 135.0},
            "MIDDLE": {"MCP": 80.0, "PIP": 90.0, "DIP": 60.0, "ABD": 0.0, "TAM": 270.0},
            "RING": {"MCP": 0.0, "PIP": 0.0, "DIP": 0.0, "ABD": 0.0, "TAM": 0.0},
            "PINKY": {"MCP": 80.0, "PIP": 90.0, "DIP": 60.0, "ABD": 5.0, "TAM": 135.0},
        }
        result = map_all(angles_smooth)

        assert set(result.keys()) == set(FINGER_ORDER)
        assert result["polegar"] is not None
        assert result["medio"] == SERVO_CLOSED["medio"]
        assert result["anelar"] == SERVO_OPEN["anelar"]
        for finger in FINGER_ORDER:
            assert result[finger] is not None

    def test_empty_angles_smooth_returns_all_none(self):
        result = map_all({})
        assert result == {finger: None for finger in FINGER_ORDER}

    def test_missing_finger_returns_none_for_that_finger_only(self):
        angles_smooth = {
            "THUMB": {"TAM": 50.0},
            # INDEX, MIDDLE, RING, PINKY ausentes.
        }
        result = map_all(angles_smooth)
        assert result["polegar"] is not None
        assert result["indicador"] is None
        assert result["medio"] is None
        assert result["anelar"] is None
        assert result["minimo"] is None

    def test_invalid_tam_in_one_finger_does_not_affect_others(self):
        angles_smooth = {
            "THUMB": {"TAM": float("nan")},
            "INDEX": {"TAM": 100.0},
        }
        result = map_all(angles_smooth)
        assert result["polegar"] is None
        assert result["indicador"] is not None
