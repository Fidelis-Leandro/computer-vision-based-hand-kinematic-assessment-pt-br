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


# =============================================================================
# Fase 7E-a — teto de TAM do perfil Evento (subfase de testes)
# =============================================================================
#
# TAM_MAX_DEMO é uma tabela PARALELA a TAM_MAX, nunca usada pelo caminho
# padrão — nenhum teste desta classe deve afetar TAM_MAX nem o comportamento
# de tam_to_servo()/map_all() quando chamados sem o parâmetro novo (ver
# TestTamToServo e TestMapAll acima, que continuam cobrindo esse contrato
# sem nenhuma mudança).
#
# Os valores abaixo (70/150/150/150/150) foram definidos manualmente para
# demonstração e ficam bem abaixo dos 100/200/230 sugeridos pela análise de
# amplitude dos CSVs reais em logs/ (ver INTEGRACAO_MAO_ROBOTICA.md). Isso é
# proposital: tetos baixos fazem a mão robótica fechar por completo com
# pouco esforço do visitante, que é o objetivo do perfil Evento. São valores
# de teste manual, não validados contra os CSVs.
#
# Os imports de TAM_MAX_DEMO são feitos dentro de cada teste, e não no topo
# do arquivo. Isso vem da subfase de testes (7E-a), quando o símbolo ainda
# não existia e um import de módulo quebraria a coleta do arquivo inteiro;
# foi mantido por simplicidade e é inofensivo.


class TestTamMaxDemoProfile:
    def test_tam_max_demo_exists_with_the_current_values(self):
        """Guarda de regressão permanente (não é mais uma transição).

        Trava os valores atuais, definidos manualmente para demonstração:
        polegar 70, indicador/médio/anelar/mínimo 150. Se forem alterados
        de propósito, este teste deve ser atualizado junto."""
        import outputs.tam_to_servo as tam_to_servo_module

        assert tam_to_servo_module.TAM_MAX_DEMO == {
            "polegar": 70.0,
            "indicador": 150.0,
            "medio": 150.0,
            "anelar": 150.0,
            "minimo": 150.0,
        }

    def test_tam_max_demo_never_exceeds_the_clinical_ceiling(self):
        """Guarda de regressão permanente (não é mais uma transição).

        Guarda de sanidade: o teto de
        demonstração deve ser sempre <= o teto clínico (TAM_MAX) para cada
        dedo — ele existe para SATURAR mais cedo, nunca mais tarde. Se algum
        dia alguém alterar TAM_MAX_DEMO para um valor maior que TAM_MAX,
        este teste continua de pé para pegar o erro."""
        import outputs.tam_to_servo as tam_to_servo_module

        for finger in tam_to_servo_module.FINGER_ORDER:
            assert (
                tam_to_servo_module.TAM_MAX_DEMO[finger]
                <= tam_to_servo_module.TAM_MAX[finger]
            )


class TestTamToServoAcceptsOptionalTamMaxTable:
    def test_tam_to_servo_accepts_a_custom_tam_max_table(self):
        """Guarda de regressão permanente (não é mais uma transição).

        Com um teto customizado bem menor que o padrão, o mesmo TAM de
        entrada deve saturar em SERVO_CLOSED mais cedo do que satura hoje
        com TAM_MAX — prova de que a tabela passada é a que está sendo
        usada, não TAM_MAX por baixo dos panos."""
        custom_table = {"indicador": 50.0}

        posicao = tam_to_servo("indicador", 50.0, tam_max_table=custom_table)

        assert posicao == SERVO_CLOSED["indicador"]

    def test_tam_to_servo_default_call_is_unaffected_by_the_new_parameter(self):
        """Guarda de regressão permanente (não é mais uma transição).

        TestTamToServo, acima, já cobre o contrato de 2 argumentos; este
        prova que o parâmetro opcional tem o default certo (TAM_MAX),
        chamando explicitamente com a palavra-chave."""
        posicao_com_default_explicito = tam_to_servo(
            "indicador", TAM_MAX["indicador"], tam_max_table=TAM_MAX
        )
        posicao_sem_parametro_novo = tam_to_servo("indicador", TAM_MAX["indicador"])

        assert posicao_com_default_explicito == posicao_sem_parametro_novo

    def test_map_all_accepts_a_custom_tam_max_table(self):
        """Guarda de regressão permanente (não é mais uma transição).

        map_all() deve repassar tam_max_table para cada chamada interna de
        tam_to_servo(), não só aceitar e ignorar o parâmetro."""
        custom_table = {
            "polegar": 50.0, "indicador": 50.0, "medio": 50.0,
            "anelar": 50.0, "minimo": 50.0,
        }
        angles_smooth = {"INDEX": {"TAM": 50.0}}

        result = map_all(angles_smooth, tam_max_table=custom_table)

        assert result["indicador"] == SERVO_CLOSED["indicador"]
