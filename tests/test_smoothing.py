"""
tests/test_smoothing.py — Testes de regressão do pipeline EMA -> Kalman
=========================================================================

Esta suíte protege o comportamento clínico de smoothing.py (pipeline
EMA seguido de Kalman, padrão do sistema — UI, CSV, PDF e mão robótica) e os
modos de filtro (RAW / EMA / KALMAN / EMA_KALMAN, ver
INTEGRACAO_MAO_ROBOTICA.md), servindo de referência para qualquer alteração
nesse módulo.

Os valores numéricos usados como referência foram capturados executando o
código real de SeriesFilter/GoniometryFilterBank (não foram calculados à mão),
para que estes testes sirvam como uma "fotografia" fiel do comportamento
existente. Se um valor aqui um dia não corresponder mais ao código, isso
significa que o comportamento do filtro mudou — o que é exatamente o que esta
suíte existe para detectar.

Nenhum teste depende de tempo real, câmera, MediaPipe, Arduino, porta serial
ou interface PyQt6 — SeriesFilter e GoniometryFilterBank são puramente
numéricos.
"""

import logging

import pytest

import config
from smoothing import (
    FILTER_MODE_EMA,
    FILTER_MODE_EMA_KALMAN,
    FILTER_MODE_KALMAN,
    FILTER_MODE_RAW,
    GoniometryFilterBank,
    SeriesFilter,
)


# =============================================================================
# SeriesFilter — comportamento básico
# =============================================================================


class TestSeriesFilterBasics:
    def test_first_sample_returns_raw_value_and_initializes_state(self):
        """A primeira amostra não tem histórico prévio: EMA e Kalman assumem
        o valor bruto diretamente, sem suavização (não há o que suavizar)."""
        f = SeriesFilter()
        result = f.update(50.0)

        assert result == pytest.approx(50.0)
        assert f.is_initialized is True

    def test_successive_updates_are_deterministic(self):
        """Duas instâncias independentes, alimentadas com a mesma sequência,
        devem produzir exatamente a mesma saída — sem aleatoriedade, sem
        dependência de tempo real ou de ordem de execução externa."""
        sequence = [10.0, 12.0, 11.0, 15.0, 9.0]

        f1 = SeriesFilter()
        f2 = SeriesFilter()
        out1 = [f1.update(v) for v in sequence]
        out2 = [f2.update(v) for v in sequence]

        assert out1 == out2

    def test_constant_input_converges_and_stays_constant(self):
        """Para uma entrada constante, EMA e Kalman não têm nada a corrigir:
        a saída deve permanecer exatamente igual ao valor de entrada em
        todas as amostras, sem deriva numérica."""
        f = SeriesFilter()
        outputs = [f.update(25.0) for _ in range(5)]

        assert outputs == [pytest.approx(25.0)] * 5

    def test_ema_runs_before_kalman_not_the_reverse(self):
        """Confirma a ordem EMA -> Kalman documentada no módulo, mostrando
        que a saída real diverge de uma ordem hipotética Kalman -> EMA a
        partir da 3a amostra da mesma sequência de entrada.

        A sequência "kalman_then_ema_reference" é uma reimplementação
        alternativa feita SOMENTE dentro deste teste (não existe em
        smoothing.py) apenas para prova de que a ordem importa — não é uma
        API nova proposta para o projeto.
        """
        sequence = [10.0, 20.0, 10.0, 20.0, 10.0]

        f = SeriesFilter()
        actual = [f.update(v) for v in sequence]

        ema_then_kalman_reference = [
            10.0,
            12.72972972972973,
            12.41331241595697,
            13.186547788873039,
            13.16799003356258,
        ]
        kalman_then_ema_reference = [
            10.0,
            12.72972972972973,
            13.268946176117847,
            14.263675598435633,
            14.322963696491733,
        ]

        assert actual == pytest.approx(ema_then_kalman_reference, abs=1e-9)
        assert actual != pytest.approx(kalman_then_ema_reference, abs=1e-6)

    def test_abrupt_change_is_smoothed_not_instant(self):
        """Após um período estável em 20.0, um salto para 80.0 não deve
        aparecer de imediato na saída — o valor deve subir gradualmente,
        confirmando que a suavização amortece mudanças abruptas."""
        f = SeriesFilter()
        for _ in range(5):
            f.update(20.0)

        post_jump = [f.update(80.0) for _ in range(4)]

        # Nenhuma amostra chega perto do valor bruto imediatamente...
        assert post_jump[0] < 40.0
        # ...e a sequência avança de forma monotonicamente crescente em
        # direção ao novo valor, sem overshoot.
        assert post_jump == sorted(post_jump)
        assert post_jump[-1] < 80.0

    def test_stability_is_instavel_right_after_first_sample(self):
        """Documenta um comportamento não óbvio do código atual: o ganho de
        Kalman só é calculado a partir da SEGUNDA amostra (a primeira só
        inicializa o estado). Como o ganho padrão de __init__ é 1.0, a
        propriedade `stability` classifica a série como "instavel" logo
        após a primeira amostra, mesmo sem nenhuma oscilação real ter
        ocorrido ainda."""
        f = SeriesFilter()
        f.update(10.0)

        assert f.kalman_gain == pytest.approx(1.0)
        assert f.stability == "instavel"


# =============================================================================
# SeriesFilter — reset()
# =============================================================================


class TestSeriesFilterReset:
    def test_reset_without_seed_behaves_like_a_new_filter(self):
        """Sem valor de semente, reset() apaga o histórico por completo: a
        próxima atualização deve se comportar como a primeira amostra de
        uma série nova (nenhuma suavização, valor bruto passa direto)."""
        f = SeriesFilter()
        f.update(10.0)
        f.update(20.0)
        f.update(30.0)

        f.reset()

        assert f.is_initialized is False
        assert f.update(99.0) == pytest.approx(99.0)

    def test_reset_with_seed_value_initializes_directly_to_seed(self):
        """Com valor de semente, reset() já deixa o filtro "pré-aquecido"
        naquele valor — diferente de uma primeira amostra comum, o ganho de
        Kalman começa em 0.5 (não em 1.0), refletindo confiança parcial
        herdada do estado anterior."""
        f = SeriesFilter()
        f.update(10.0)
        f.update(20.0)

        f.reset(seed_value=42.0)

        assert f.is_initialized is True
        assert f.kalman_gain == pytest.approx(0.5)
        # Atualizar com o próprio valor de semente não deve alterar a saída.
        assert f.update(42.0) == pytest.approx(42.0)


# =============================================================================
# GoniometryFilterBank — independência entre séries
# =============================================================================


class TestGoniometryFilterBankIndependence:
    def test_bank_creates_one_independent_series_per_finger_joint(self):
        """Cada combinação (dedo, articulação) recebe seu próprio
        SeriesFilter, criado sob demanda na primeira atualização."""
        bank = GoniometryFilterBank()
        assert bank.active_series_count == 0

        bank.update("INDEX", "MCP", 10.0)
        bank.update("INDEX", "PIP", 10.0)
        bank.update("THUMB", "MCP", 10.0)

        assert bank.active_series_count == 3

    def test_series_do_not_share_state_between_different_keys(self):
        """Uma série que já recebeu várias amostras (e portanto tem estado
        interno acumulado) não deve influenciar uma série vizinha que está
        recebendo sua primeira amostra."""
        bank = GoniometryFilterBank()
        bank.update("INDEX", "MCP", 10.0)
        bank.update("INDEX", "MCP", 90.0)

        first_sample_other_series = bank.update("MIDDLE", "MCP", 10.0)
        second_sample_other_series = bank.update("MIDDLE", "MCP", 10.0)

        # MIDDLE_MCP recebeu entrada constante — deve convergir para o
        # próprio valor, exatamente como uma série nova isolada, sem
        # qualquer resíduo do estado de INDEX_MCP.
        assert first_sample_other_series == pytest.approx(10.0)
        assert second_sample_other_series == pytest.approx(10.0)


# =============================================================================
# GoniometryFilterBank — smooth_all()
# =============================================================================


class TestGoniometryFilterBankSmoothAll:
    def test_smooth_all_preserves_input_structure_and_keys(self):
        """A saída de smooth_all() deve ter exatamente os mesmos dedos e
        articulações da entrada — nenhuma chave criada ou perdida."""
        bank = GoniometryFilterBank()
        angles = {
            "INDEX": {"MCP": 10.0, "PIP": 20.0, "DIP": 5.0, "ABD": 2.0, "TAM": 35.0},
            "THUMB": {"MCP": 8.0, "IP": 4.0, "TAM": 12.0},
        }

        result = bank.smooth_all(angles)

        assert set(result.keys()) == set(angles.keys())
        assert set(result["INDEX"].keys()) == set(angles["INDEX"].keys())
        assert set(result["THUMB"].keys()) == set(angles["THUMB"].keys())

    def test_smooth_all_values_are_floats_rounded_to_two_decimals(self):
        """smooth_all() arredonda cada valor a 2 casas decimais (contrato já
        usado por goniometry_csv.py e pela mão robótica)."""
        bank = GoniometryFilterBank()
        angles = {"INDEX": {"MCP": 10.0, "TAM": 33.333333}}

        result = bank.smooth_all(angles)
        value = result["INDEX"]["TAM"]

        assert isinstance(value, float)
        assert value == round(value, 2)

    def test_smooth_all_carries_state_across_calls(self):
        """Chamar smooth_all() repetidamente para a mesma série continua o
        histórico entre chamadas — não reinicia o filtro a cada quadro."""
        bank = GoniometryFilterBank()

        first = bank.smooth_all({"INDEX": {"MCP": 20.0}})
        second = bank.smooth_all({"INDEX": {"MCP": 80.0}})

        assert first["INDEX"]["MCP"] == pytest.approx(20.0)
        # Segunda chamada não pula direto para 80.0 — prova de que o
        # estado (não só o valor bruto) foi preservado entre as chamadas.
        assert second["INDEX"]["MCP"] < 80.0


# =============================================================================
# GoniometryFilterBank — reset_finger() / reset_all()
# =============================================================================


class TestGoniometryFilterBankResets:
    def test_reset_finger_resets_only_the_target_finger(self):
        """Após reset_finger("INDEX"), a próxima atualização de INDEX_MCP
        deve se comportar como primeira amostra (valor bruto passa direto)."""
        bank = GoniometryFilterBank()
        bank.update("INDEX", "MCP", 10.0)
        bank.update("INDEX", "MCP", 90.0)

        bank.reset_finger("INDEX")

        assert bank.update("INDEX", "MCP", 77.0) == pytest.approx(77.0)

    def test_reset_finger_preserves_other_fingers_state(self):
        """reset_finger() não deve afetar séries de outros dedos: o histórico
        de MIDDLE_MCP deve continuar de onde estava, mesmo depois de
        resetar INDEX."""
        bank = GoniometryFilterBank()
        bank.update("INDEX", "MCP", 10.0)
        bank.update("INDEX", "MCP", 90.0)
        bank.update("MIDDLE", "MCP", 10.0)
        bank.update("MIDDLE", "MCP", 50.0)

        bank.reset_finger("INDEX")
        continued_value = bank.update("MIDDLE", "MCP", 50.0)

        # Referência: um SeriesFilter isolado alimentado com a mesma
        # sequência completa de MIDDLE_MCP (sem nenhum reset) produz o
        # mesmo resultado — prova de que reset_finger("INDEX") não
        # perturbou o estado de MIDDLE.
        reference = SeriesFilter()
        reference.update(10.0)
        reference.update(50.0)
        expected = reference.update(50.0)

        assert continued_value == pytest.approx(expected)

    def test_reset_all_without_seed_reinitializes_every_series(self):
        """Sem seed_angles, reset_all() volta TODAS as séries ao estado "não
        inicializado" — a próxima amostra de cada uma equivale a uma
        primeira amostra."""
        bank = GoniometryFilterBank()
        bank.update("INDEX", "MCP", 10.0)
        bank.update("INDEX", "MCP", 90.0)
        bank.update("MIDDLE", "MCP", 10.0)
        bank.update("MIDDLE", "MCP", 90.0)

        bank.reset_all()

        assert bank.update("INDEX", "MCP", 33.0) == pytest.approx(33.0)
        assert bank.update("MIDDLE", "MCP", 44.0) == pytest.approx(44.0)

    def test_reset_all_with_seed_angles_only_affects_existing_keys(self):
        """reset_all(seed_angles=...) só aplica a semente a séries que já
        existem no banco — não cria séries novas para dedos/articulações
        nunca vistos antes, mesmo que apareçam em seed_angles."""
        bank = GoniometryFilterBank()
        bank.update("INDEX", "MCP", 10.0)

        bank.reset_all(seed_angles={"INDEX": {"MCP": 77.0}, "GHOST": {"X": 1.0}})

        # INDEX_MCP já existia: fica "pré-aquecido" em 77.0, então uma
        # atualização para 100.0 fica ENTRE 77 e 100 (suavizada), nunca
        # exatamente 100.0 (o que só ocorreria numa primeira amostra real).
        seeded_result = bank.update("INDEX", "MCP", 100.0)
        assert 77.0 < seeded_result < 100.0

        # GHOST_X nunca existiu: a semente foi ignorada para essa chave, e
        # sua primeira atualização real se comporta como primeira amostra.
        ghost_result = bank.update("GHOST", "X", 5.0)
        assert ghost_result == pytest.approx(5.0)


# =============================================================================
# GoniometryFilterBank — configure()
# =============================================================================


class TestGoniometryFilterBankConfigure:
    def test_configure_clears_all_existing_filters(self):
        """configure() descarta todas as séries já criadas — a intenção
        documentada é que novas séries sejam criadas com os parâmetros
        atualizados, não que as antigas continuem com parâmetros antigos."""
        bank = GoniometryFilterBank()
        bank.update("INDEX", "MCP", 10.0)
        assert bank.active_series_count == 1

        bank.configure(ema_alpha=0.5)

        assert bank.active_series_count == 0

    def test_configure_updates_parameters_used_by_new_series(self):
        """Após configure(), uma série nova deve se comportar exatamente
        como um SeriesFilter criado diretamente com os mesmos parâmetros
        (mesmo ema_alpha novo, mesmo kalman_q/kalman_r herdados)."""
        bank = GoniometryFilterBank()
        bank.update("INDEX", "MCP", 10.0)
        bank.configure(ema_alpha=0.5)

        from_bank = [bank.update("INDEX", "MCP", v) for v in (10.0, 20.0)]

        reference = SeriesFilter(ema_alpha=0.5, kalman_q=0.01, kalman_r=0.10)
        from_reference = [reference.update(v) for v in (10.0, 20.0)]

        assert from_bank == pytest.approx(from_reference, abs=1e-9)

    def test_configure_does_not_change_the_smooth_all_data_structure(self):
        """configure() é uma mudança de parâmetros numéricos, não de
        contrato de dados — smooth_all() continua devolvendo o mesmo
        formato de dicionário antes e depois de configure()."""
        bank = GoniometryFilterBank()
        angles = {"INDEX": {"MCP": 10.0, "TAM": 20.0}}

        before = bank.smooth_all(angles)
        bank.configure(kalman_q=0.05)
        after = bank.smooth_all(angles)

        assert set(before.keys()) == set(after.keys())
        assert set(before["INDEX"].keys()) == set(after["INDEX"].keys())


# =============================================================================
# Comportamento padrão do sistema (EMA -> Kalman, parâmetros de config.py)
# =============================================================================


class TestDefaultPipelineMatchesProductionConfig:
    def test_series_filter_defaults_match_config_constants(self):
        """Os valores padrão de SeriesFilter (usados quando nenhum parâmetro
        é passado) devem coincidir com as constantes reais de config.py
        (EMA_ALPHA, KALMAN_Q, KALMAN_R) — as mesmas usadas em produção por
        workers/processing_worker.py. Este teste não altera config.py; só lê
        os valores existentes para detectar divergência entre os dois
        arquivos."""
        f = SeriesFilter()

        assert f.ema_alpha == pytest.approx(config.EMA_ALPHA)
        assert f.q == pytest.approx(config.KALMAN_Q)
        assert f.r == pytest.approx(config.KALMAN_R)

    def test_default_pipeline_is_ema_followed_by_kalman(self):
        """Teste de regressão de mais alto nível: com os parâmetros padrão
        (iguais aos de produção), uma sequência conhecida deve produzir
        exatamente a saída já validada nesta suíte para a ordem EMA -> Kalman
        (ver test_ema_runs_before_kalman_not_the_reverse)."""
        f = SeriesFilter(
            ema_alpha=config.EMA_ALPHA,
            kalman_q=config.KALMAN_Q,
            kalman_r=config.KALMAN_R,
        )
        sequence = [10.0, 20.0, 10.0, 20.0, 10.0]
        expected = [
            10.0,
            12.72972972972973,
            12.41331241595697,
            13.186547788873039,
            13.16799003356258,
        ]

        actual = [f.update(v) for v in sequence]

        assert actual == pytest.approx(expected, abs=1e-9)


# =============================================================================
# Modos de filtro (RAW / EMA / KALMAN / EMA_KALMAN)
# =============================================================================
#
# Os testes abaixo cobrem os modos de filtro de smoothing.py. O
# ProcessingWorker instala o modo de filtro do banco (_make_filter_bank e
# set_filter_mode) e o padrão, FILTER_MODE_EMA_KALMAN, preserva o
# comportamento já protegido pelos testes acima.


class TestFilterModeRaw:
    def test_raw_returns_the_input_value_unchanged(self):
        """Em modo RAW, update() devolve o próprio valor bruto, convertido
        para float, sem nenhuma suavização."""
        f = SeriesFilter(mode=FILTER_MODE_RAW)
        sequence = [10.0, 20.0, 10.0, 20.0, 10.0]

        outputs = [f.update(v) for v in sequence]

        assert outputs == pytest.approx(sequence, abs=1e-9)

    def test_raw_does_not_touch_ema_or_kalman_state(self):
        """RAW não deve atualizar nenhum dos dois estados internos —
        confirma que EMA e Kalman realmente não são executados neste modo."""
        f = SeriesFilter(mode=FILTER_MODE_RAW)
        f.update(10.0)
        f.update(20.0)

        assert f._ema_value is None
        assert f._x is None

    def test_raw_does_not_carry_state_between_calls(self):
        """Sem estado interno, cada chamada em modo RAW é independente das
        anteriores — alimentar valores muito diferentes em sequência não
        produz nenhum efeito de suavização ou atraso."""
        f = SeriesFilter(mode=FILTER_MODE_RAW)

        assert f.update(0.0) == pytest.approx(0.0)
        assert f.update(1000.0) == pytest.approx(1000.0)
        assert f.update(0.0) == pytest.approx(0.0)

    def test_raw_reset_does_not_change_behavior(self):
        """Como RAW não mantém estado, reset() não deve alterar o
        comportamento de update() antes e depois de ser chamado."""
        f = SeriesFilter(mode=FILTER_MODE_RAW)
        before = [f.update(v) for v in (5.0, 15.0)]

        f.reset()

        after = [f.update(v) for v in (5.0, 15.0)]
        assert before == pytest.approx(after, abs=1e-9)


class TestFilterModeEma:
    def test_ema_only_matches_a_pure_ema_reference_sequence(self):
        """A saída em modo EMA deve corresponder exatamente à fórmula EMA
        pura (sem Kalman), calculada de forma independente neste teste."""
        alpha = 0.30
        sequence = [10.0, 20.0, 10.0, 20.0, 10.0]

        reference = []
        acc = None
        for raw in sequence:
            acc = raw if acc is None else alpha * raw + (1 - alpha) * acc
            reference.append(acc)

        f = SeriesFilter(ema_alpha=alpha, mode=FILTER_MODE_EMA)
        actual = [f.update(v) for v in sequence]

        assert actual == pytest.approx(reference, abs=1e-9)

    def test_ema_only_never_executes_kalman(self):
        """Em modo EMA, o estado de Kalman (`_x`) nunca deve ser tocado —
        prova de que a etapa Kalman realmente não roda neste modo."""
        f = SeriesFilter(mode=FILTER_MODE_EMA)
        for v in (10.0, 20.0, 30.0):
            f.update(v)

        assert f._x is None

    def test_ema_only_keeps_state_across_calls(self):
        """O estado de EMA deve persistir entre chamadas — a segunda
        atualização não pode se comportar como uma primeira amostra."""
        f = SeriesFilter(mode=FILTER_MODE_EMA)

        first = f.update(20.0)
        second = f.update(80.0)

        assert first == pytest.approx(20.0)
        # Se o estado não fosse mantido, a segunda amostra devolveria 80.0
        # diretamente (comportamento de primeira amostra); em vez disso, o
        # EMA produz um valor intermediário entre 20 e 80.
        assert 20.0 < second < 80.0

    def test_ema_only_reset_restarts_the_series(self):
        """reset() em modo EMA deve fazer a próxima amostra se comportar
        como a primeira de uma série nova."""
        f = SeriesFilter(mode=FILTER_MODE_EMA)
        f.update(10.0)
        f.update(20.0)

        f.reset()

        assert f.is_initialized is False
        assert f.update(99.0) == pytest.approx(99.0)


class TestFilterModeKalman:
    def test_kalman_only_receives_the_raw_value_directly(self):
        """Em modo KALMAN, o filtro de Kalman recebe o valor bruto como
        medição — não a saída de um EMA (que não roda neste modo)."""
        q, r = 0.01, 0.10
        sequence = [10.0, 20.0, 10.0, 20.0, 10.0]

        reference = []
        x = None
        p = 1.0
        for raw in sequence:
            if x is None:
                x = raw
                reference.append(x)
                continue
            p_minus = p + q
            k = p_minus / (p_minus + r)
            x = x + k * (raw - x)
            p = (1.0 - k) * p_minus
            reference.append(x)

        f = SeriesFilter(kalman_q=q, kalman_r=r, mode=FILTER_MODE_KALMAN)
        actual = [f.update(v) for v in sequence]

        assert actual == pytest.approx(reference, abs=1e-9)

    def test_kalman_only_never_executes_ema(self):
        """Em modo KALMAN, o estado de EMA (`_ema_value`) nunca deve ser
        tocado — prova de que a etapa EMA realmente não roda neste modo."""
        f = SeriesFilter(mode=FILTER_MODE_KALMAN)
        for v in (10.0, 20.0, 30.0):
            f.update(v)

        assert f._ema_value is None

    def test_kalman_only_keeps_state_across_calls(self):
        """O estado de Kalman deve persistir entre chamadas — a saída não
        reinicia a cada amostra."""
        f = SeriesFilter(mode=FILTER_MODE_KALMAN)

        first = f.update(20.0)
        second = f.update(80.0)

        assert first == pytest.approx(20.0)
        assert 20.0 < second < 80.0

    def test_kalman_only_reset_restarts_the_series(self):
        """reset() em modo KALMAN deve fazer a próxima amostra se comportar
        como a primeira de uma série nova."""
        f = SeriesFilter(mode=FILTER_MODE_KALMAN)
        f.update(10.0)
        f.update(20.0)

        f.reset()

        assert f.is_initialized is False
        assert f.update(99.0) == pytest.approx(99.0)


class TestFilterModeValidation:
    def test_series_filter_rejects_unknown_mode(self):
        """Um modo fora de VALID_FILTER_MODES deve falhar imediatamente na
        criação do filtro, não silenciosamente em algum update() futuro."""
        with pytest.raises(ValueError):
            SeriesFilter(mode="MODO_INEXISTENTE")

    def test_filter_bank_rejects_unknown_mode(self):
        with pytest.raises(ValueError):
            GoniometryFilterBank(mode="MODO_INEXISTENTE")


class TestGoniometryFilterBankModes:
    @pytest.mark.parametrize(
        "mode", [FILTER_MODE_RAW, FILTER_MODE_EMA, FILTER_MODE_KALMAN, FILTER_MODE_EMA_KALMAN]
    )
    def test_bank_can_be_created_with_each_mode(self, mode):
        bank = GoniometryFilterBank(mode=mode)
        assert bank.mode == mode

    def test_bank_default_mode_is_ema_kalman(self):
        """Sem informar `mode`, o banco usa EMA_KALMAN, o pipeline padrão."""
        bank = GoniometryFilterBank()
        assert bank.mode == FILTER_MODE_EMA_KALMAN

    @pytest.mark.parametrize(
        "mode", [FILTER_MODE_RAW, FILTER_MODE_EMA, FILTER_MODE_KALMAN, FILTER_MODE_EMA_KALMAN]
    )
    def test_smooth_all_preserves_structure_in_every_mode(self, mode):
        """Independentemente do modo, smooth_all() nunca deve criar ou
        perder dedos/articulações da entrada."""
        bank = GoniometryFilterBank(mode=mode)
        angles = {
            "INDEX": {"MCP": 10.0, "TAM": 20.0},
            "THUMB": {"MCP": 5.0, "TAM": 8.0},
        }

        result = bank.smooth_all(angles)

        assert set(result.keys()) == set(angles.keys())
        assert set(result["INDEX"].keys()) == set(angles["INDEX"].keys())
        assert set(result["THUMB"].keys()) == set(angles["THUMB"].keys())

    @pytest.mark.parametrize("mode", [FILTER_MODE_EMA, FILTER_MODE_KALMAN, FILTER_MODE_EMA_KALMAN])
    def test_series_remain_independent_per_finger_joint_in_stateful_modes(self, mode):
        """Nos modos com estado (EMA, KALMAN, EMA_KALMAN), uma série que já
        acumulou histórico não deve influenciar uma série vizinha recebendo
        sua primeira amostra — mesma garantia de independência validada
        para o modo padrão, repetida aqui para os demais modos."""
        bank = GoniometryFilterBank(mode=mode)
        bank.update("INDEX", "MCP", 10.0)
        bank.update("INDEX", "MCP", 90.0)

        first = bank.update("MIDDLE", "MCP", 10.0)
        second = bank.update("MIDDLE", "MCP", 10.0)

        assert first == pytest.approx(10.0)
        assert second == pytest.approx(10.0)


# =============================================================================
# Robustez de None / NaN / infinito
# =============================================================================
#
# Estes testes descrevem como update() trata entradas inválidas: smoothing.py
# valida a entrada e rejeita None, NaN e ±infinito (_is_valid_measurement).
#
# Política verificada:
#   - None/NaN/+inf/-inf nunca atualizam _ema_value, _x, _p ou _k_gain;
#   - em EMA/KALMAN/EMA_KALMAN, com histórico válido: retorna o último valor
#     válido; sem histórico: retorna None;
#   - em RAW: sempre retorna None para entrada inválida, nunca "lembra" nada;
#   - valores inválidos nunca são convertidos para 0.0 (0.0 é uma medida
#     clínica real de extensão/abertura, não um marcador de ausência de dado).

INVALID_VALUES = [None, float("nan"), float("inf"), float("-inf")]
STATEFUL_MODES = [FILTER_MODE_EMA, FILTER_MODE_KALMAN, FILTER_MODE_EMA_KALMAN]
ALL_MODES = [FILTER_MODE_RAW, FILTER_MODE_EMA, FILTER_MODE_KALMAN, FILTER_MODE_EMA_KALMAN]


class TestInvalidValueRejection:
    @pytest.mark.parametrize("invalid", INVALID_VALUES)
    @pytest.mark.parametrize("mode", ALL_MODES)
    def test_first_sample_invalid_returns_none_without_raising(self, mode, invalid):
        """Uma série sem nenhum histórico válido, recebendo um valor
        inválido como primeira amostra, deve devolver None — nunca inventar
        um ângulo (0.0 seria uma medida clínica falsa) e nunca levantar
        exceção não tratada."""
        f = SeriesFilter(mode=mode)

        result = f.update(invalid)

        assert result is None

    @pytest.mark.parametrize("invalid", INVALID_VALUES)
    @pytest.mark.parametrize("mode", STATEFUL_MODES)
    def test_valid_then_invalid_returns_last_valid_value(self, mode, invalid):
        """Nos modos com estado (EMA, KALMAN, EMA_KALMAN), um valor
        inválido depois de uma amostra válida deve devolver o último valor
        filtrado válido — não None, não o valor inválido."""
        f = SeriesFilter(mode=mode)
        first_valid = f.update(20.0)

        result = f.update(invalid)

        assert result == pytest.approx(first_valid, abs=1e-9)

    @pytest.mark.parametrize("invalid", INVALID_VALUES)
    def test_raw_never_remembers_a_previous_value(self, invalid):
        """RAW é definido por não ter memória: mesmo depois de uma amostra
        válida, um valor inválido deve devolver None, nunca o valor
        anterior — reaproveitar um valor aqui contradiria a própria
        definição do modo."""
        f = SeriesFilter(mode=FILTER_MODE_RAW)
        f.update(20.0)

        result = f.update(invalid)

        assert result is None

    @pytest.mark.parametrize("mode", STATEFUL_MODES)
    def test_invalid_value_does_not_touch_internal_state(self, mode):
        """Nenhum dos quatro campos de estado interno pode ser alterado por
        um valor inválido — a contaminação (o problema original que esta
        tratamento de entrada inválida evita) significa exatamente algum
        desses campos mudando."""
        f = SeriesFilter(mode=mode)
        f.update(20.0)
        f.update(50.0)

        ema_before = f._ema_value
        x_before = f._x
        p_before = f._p
        gain_before = f._k_gain

        f.update(float("nan"))

        assert f._ema_value == ema_before
        assert f._x == x_before
        assert f._p == p_before
        assert f._k_gain == gain_before

    @pytest.mark.parametrize("mode", STATEFUL_MODES)
    def test_recovers_normally_after_an_invalid_value(self, mode):
        """Depois de um valor inválido, a série deve continuar exatamente
        como se aquele valor nunca tivesse existido — comparado com uma
        série de referência sem nenhum valor inválido no meio."""
        reference = SeriesFilter(mode=mode)
        reference.update(20.0)
        reference_next = reference.update(80.0)

        f = SeriesFilter(mode=mode)
        f.update(20.0)
        f.update(float("nan"))  # deve ser completamente ignorado
        recovered = f.update(80.0)

        assert recovered == pytest.approx(reference_next, abs=1e-9)

    @pytest.mark.parametrize("mode", ALL_MODES)
    def test_reset_after_invalid_value_behaves_like_a_fresh_series(self, mode):
        """reset() continua funcionando normalmente mesmo depois de um
        valor inválido ter sido rejeitado."""
        f = SeriesFilter(mode=mode)
        f.update(20.0)
        f.update(float("nan"))

        f.reset()

        assert f.is_initialized in (False, True)  # RAW é sempre True; os demais, False
        if mode != FILTER_MODE_RAW:
            assert f.is_initialized is False
        assert f.update(99.0) == pytest.approx(99.0)


class TestGoniometryFilterBankInvalidValues:
    @pytest.mark.parametrize("mode", STATEFUL_MODES)
    def test_invalid_value_in_one_series_does_not_affect_sibling_series(self, mode):
        """Um valor inválido em INDEX_MCP não pode influenciar MIDDLE_MCP —
        mesma garantia de independência validada para entradas válidas,
        aqui sob entrada inválida."""
        bank = GoniometryFilterBank(mode=mode)
        bank.update("INDEX", "MCP", 20.0)
        bank.update("INDEX", "MCP", float("nan"))

        first = bank.update("MIDDLE", "MCP", 10.0)
        second = bank.update("MIDDLE", "MCP", 10.0)

        assert first == pytest.approx(10.0)
        assert second == pytest.approx(10.0)

    @pytest.mark.parametrize("mode", STATEFUL_MODES)
    def test_smooth_all_keeps_last_valid_value_for_joint_with_history(self, mode):
        """Com histórico válido prévio, smooth_all() preserva o último
        valor válido daquela articulação quando a entrada for inválida —
        nunca 0.0, nunca a chave removida."""
        bank = GoniometryFilterBank(mode=mode)
        bank.update("INDEX", "MCP", 20.0)

        result = bank.smooth_all({"INDEX": {"MCP": float("nan")}})

        assert "MCP" in result["INDEX"]
        assert result["INDEX"]["MCP"] == pytest.approx(20.0, abs=1e-9)

    @pytest.mark.parametrize("mode", ALL_MODES)
    def test_smooth_all_returns_none_for_joint_without_valid_history(self, mode):
        """Sem nenhum histórico válido, smooth_all() deve devolver None
        para a articulação — a chave continua presente (estrutura
        preservada), só o valor é None."""
        bank = GoniometryFilterBank(mode=mode)

        result = bank.smooth_all({"INDEX": {"MCP": float("nan")}})

        assert "MCP" in result["INDEX"]
        assert result["INDEX"]["MCP"] is None


class TestInvalidValueLogging:
    def test_logs_a_single_warning_across_consecutive_invalid_updates(self, caplog):
        """Vários quadros inválidos consecutivos devem gerar UM aviso na
        transição válido -> inválido, não um aviso por quadro (evita spam
        de log a ~30 quadros/segundo)."""
        f = SeriesFilter(mode=FILTER_MODE_EMA_KALMAN)
        f.update(20.0)

        with caplog.at_level(logging.WARNING):
            for _ in range(5):
                f.update(float("nan"))

        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warnings) == 1

    def test_logs_recovery_when_value_becomes_valid_again(self, caplog):
        """Quando a série volta a receber um valor válido depois de um
        período inválido, isso deve ser registrado de forma limitada
        (uma vez), não silenciosamente."""
        f = SeriesFilter(mode=FILTER_MODE_EMA_KALMAN)
        f.update(20.0)

        with caplog.at_level(logging.INFO):
            f.update(float("nan"))
            caplog.clear()
            f.update(80.0)

        assert len(caplog.records) >= 1


# =============================================================================
# Semântica do indicador de estabilidade por modo
# =============================================================================
#
# O QUE ESTES TESTES DESCREVEM:
#
# `SeriesFilter.stability` classifica a série a partir de `self._k_gain`, o
# ganho do filtro de Kalman. RAW e EMA nunca executam a etapa Kalman, então
# nesses dois modos o ganho permanece no valor de __init__ (1.0) para
# sempre. Como o limiar de "instavel" é >= 0.40, classificar RAW e EMA pelo
# ganho os faria reportar "instavel" durante a sessão inteira, mesmo com a
# mão parada e os dados perfeitos.
#
# Isso não é falha de RAW nem de EMA: seria o indicador visual usando uma
# métrica que não existe nesses modos, e quem vê a tela concluiria que a
# medição está ruim.
#
# A semântica é APENAS de status. Cada modo reporta o que é verdade sobre ele:
#
#     RAW         -> "sem_filtro"        (não há filtragem a avaliar)
#     EMA         -> "suavizacao_ema"    (há suavização, mas não há Kalman)
#     KALMAN      -> lógica de ganho (limiares do ganho de Kalman)
#     EMA_KALMAN  -> lógica de ganho (limiares do ganho de Kalman)
#
# `stability` é uma property somente de leitura, sem
# efeito sobre o valor filtrado, EMA, Kalman, TAM, ASSH, CSV, PDF ou servos.
#
# Os testes comparam contra as strings literais ("sem_filtro" etc.) e não
# contra constantes importadas, porque a string É o contrato: ela atravessa
# processing_worker.stability_map até goniometry_overlay._stability_color().
#
# NOTA SOBRE O ESTADO VERDE: o limiar de "estavel" (< 0.15) é inalcançável com
# Q=0.01 e R=0.10 (o ganho converge para ~0.2702). Isso está documentado no
# teste de caracterização ao final desta seção. Não há correção neste
# arquivo: recalibrar o limiar é uma decisão científica que exige validação
# experimental.


class TestStabilityInRawMode:
    """RAW não executa nenhuma etapa de filtragem — não há estabilidade de
    filtro a reportar, e fingir que há é o que gera a tela enganosa."""

    def test_raw_reports_sem_filtro(self):
        f = SeriesFilter(mode=FILTER_MODE_RAW)
        f.update(45.0)

        assert f.stability == "sem_filtro"

    @pytest.mark.parametrize("n_amostras", [1, 10, 1000])
    def test_raw_reports_sem_filtro_regardless_of_sample_count(self, n_amostras):
        """O status não depende de quantas amostras passaram: em RAW ele
        descreve o modo, não um estado de convergência que não existe."""
        f = SeriesFilter(mode=FILTER_MODE_RAW)
        for _ in range(n_amostras):
            f.update(45.0)

        assert f.stability == "sem_filtro"

    def test_raw_never_reports_instavel(self):
        """Caso central: um 'instavel' permanente pintaria todas as
        articulações de vermelho no overlay durante uma sessão RAW inteira."""
        f = SeriesFilter(mode=FILTER_MODE_RAW)

        estados = set()
        for i in range(500):
            f.update(30.0 + (i % 11) * 4.0)
            estados.add(f.stability)

        assert "instavel" not in estados

    def test_raw_stability_is_stable_even_with_oscillating_input(self):
        """Entrada oscilando muito não deve mudar o status em RAW: o valor
        descreve o modo de operação, não a qualidade do sinal."""
        f = SeriesFilter(mode=FILTER_MODE_RAW)
        for valor in (0.0, 180.0, 5.0, 200.0, 1.0):
            f.update(valor)

        assert f.stability == "sem_filtro"


class TestStabilityInEmaMode:
    """EMA suaviza, mas não roda Kalman — então tem estabilidade real, só
    não uma que o ganho de Kalman consiga medir."""

    def test_ema_reports_suavizacao_ema(self):
        f = SeriesFilter(mode=FILTER_MODE_EMA)
        f.update(45.0)

        assert f.stability == "suavizacao_ema"

    @pytest.mark.parametrize("n_amostras", [1, 10, 1000])
    def test_ema_reports_suavizacao_ema_regardless_of_sample_count(self, n_amostras):
        f = SeriesFilter(mode=FILTER_MODE_EMA)
        for _ in range(n_amostras):
            f.update(45.0)

        assert f.stability == "suavizacao_ema"

    def test_ema_never_reports_instavel(self):
        f = SeriesFilter(mode=FILTER_MODE_EMA)

        estados = set()
        for i in range(500):
            f.update(30.0 + (i % 11) * 4.0)
            estados.add(f.stability)

        assert "instavel" not in estados


class TestStabilityInKalmanModesUnchanged:
    """
    KALMAN e EMA_KALMAN usam a lógica de ganho de Kalman, sem o status
    específico de RAW e EMA.

    O status semântico é restrito a RAW e EMA; se algum destes testes
    falhar, a mudança vazou para os modos com Kalman — que são os únicos
    onde o ganho realmente significa alguma coisa.
    """

    @pytest.mark.parametrize("mode", [FILTER_MODE_KALMAN, FILTER_MODE_EMA_KALMAN])
    def test_first_sample_is_instavel(self, mode):
        """O ganho só é calculado a partir da segunda amostra; a primeira
        apenas inicializa o estado, e o ganho continua no 1.0 de __init__."""
        f = SeriesFilter(mode=mode)
        f.update(10.0)

        assert f.kalman_gain == pytest.approx(1.0)
        assert f.stability == "instavel"

    @pytest.mark.parametrize("mode", [FILTER_MODE_KALMAN, FILTER_MODE_EMA_KALMAN])
    def test_converged_series_reports_convergindo(self, mode):
        f = SeriesFilter(mode=mode)
        for _ in range(500):
            f.update(45.0)

        assert f.stability == "convergindo"

    @pytest.mark.parametrize("mode", [FILTER_MODE_KALMAN, FILTER_MODE_EMA_KALMAN])
    def test_kalman_gain_converges_to_the_current_steady_state(self, mode):
        """Fotografia do regime permanente (Q=0.01, R=0.10). Se este
        número mudar, algum parâmetro do filtro foi alterado — o que não deve
        acontecer por causa da lógica de estabilidade."""
        f = SeriesFilter(mode=mode)
        for _ in range(500):
            f.update(45.0)

        assert f.kalman_gain == pytest.approx(0.27015621, abs=1e-8)

    @pytest.mark.parametrize("mode", [FILTER_MODE_KALMAN, FILTER_MODE_EMA_KALMAN])
    def test_reset_returns_to_instavel(self, mode):
        f = SeriesFilter(mode=mode)
        for _ in range(500):
            f.update(45.0)

        f.reset()

        assert f.kalman_gain == pytest.approx(1.0)
        assert f.stability == "instavel"


class TestStabilityDoesNotAffectFilterMath:
    """
    O status é somente leitura. Consultá-lo não pode mover o filtro.

    Esta é a garantia que separa "correção visual" de "alteração científica":
    se ler `stability` alterasse qualquer estado interno, o indicador
    deixaria de ser apenas visual.
    """

    @pytest.mark.parametrize(
        "mode",
        [FILTER_MODE_RAW, FILTER_MODE_EMA, FILTER_MODE_KALMAN, FILTER_MODE_EMA_KALMAN],
    )
    def test_reading_stability_does_not_change_the_filtered_output(self, mode):
        entrada = [10.0, 25.0, 18.0, 40.0, 33.0, 51.0, 47.0]

        sem_leitura = SeriesFilter(mode=mode)
        saida_sem_leitura = [sem_leitura.update(v) for v in entrada]

        com_leitura = SeriesFilter(mode=mode)
        saida_com_leitura = []
        for v in entrada:
            com_leitura.stability          # leitura antes
            saida_com_leitura.append(com_leitura.update(v))
            com_leitura.stability          # leitura depois

        assert saida_com_leitura == saida_sem_leitura

    @pytest.mark.parametrize(
        "mode",
        [FILTER_MODE_RAW, FILTER_MODE_EMA, FILTER_MODE_KALMAN, FILTER_MODE_EMA_KALMAN],
    )
    def test_reading_stability_does_not_change_internal_state(self, mode):
        f = SeriesFilter(mode=mode)
        f.update(45.0)
        f.update(60.0)
        antes = (f._ema_value, f._x, f._p, f._k_gain, f._n_updates)

        for _ in range(10):
            f.stability

        assert (f._ema_value, f._x, f._p, f._k_gain, f._n_updates) == antes

    def test_filter_parameters_still_come_from_config(self):
        """Trava os parâmetros do filtro, que vêm de config.py e não podem
        ser alterados pela lógica de estabilidade."""
        f = SeriesFilter()

        assert f.ema_alpha == pytest.approx(config.EMA_ALPHA)
        assert f.q == pytest.approx(config.KALMAN_Q)
        assert f.r == pytest.approx(config.KALMAN_R)

    @pytest.mark.parametrize(
        "mode,esperado",
        [
            (FILTER_MODE_RAW, [10.0, 25.0, 18.0]),
            (FILTER_MODE_EMA, [10.0, 14.5, 15.55]),
        ],
    )
    def test_numeric_output_snapshot_for_stateless_and_ema_modes(self, mode, esperado):
        """Fotografia numérica: a saída dos filtros RAW e EMA não depende
        da lógica de estabilidade."""
        f = SeriesFilter(mode=mode)
        saida = [f.update(v) for v in (10.0, 25.0, 18.0)]

        assert saida == pytest.approx(esperado)


class TestStabilityInvalidValuesUnchanged:
    """
    Valores inválidos são tratados como em update(): o estado interno não
    é tocado, nada vira 0.0, e o status de estabilidade também não pode ser
    corrompido por eles.
    """

    @pytest.mark.parametrize(
        "invalido", [None, float("nan"), float("inf"), float("-inf"), "abc"]
    )
    def test_raw_keeps_sem_filtro_after_invalid_values(self, invalido):
        f = SeriesFilter(mode=FILTER_MODE_RAW)
        f.update(45.0)

        assert f.update(invalido) is None
        assert f.stability == "sem_filtro"

    @pytest.mark.parametrize(
        "invalido", [None, float("nan"), float("inf"), float("-inf"), "abc"]
    )
    def test_ema_keeps_suavizacao_ema_after_invalid_values(self, invalido):
        f = SeriesFilter(mode=FILTER_MODE_EMA)
        f.update(45.0)

        assert f.update(invalido) == pytest.approx(45.0)
        assert f.stability == "suavizacao_ema"

    @pytest.mark.parametrize("mode", [FILTER_MODE_KALMAN, FILTER_MODE_EMA_KALMAN])
    def test_kalman_modes_keep_their_status_after_invalid_values(self, mode):
        f = SeriesFilter(mode=mode)
        for _ in range(500):
            f.update(45.0)
        status_antes = f.stability

        f.update(float("nan"))

        assert f.stability == status_antes

    @pytest.mark.parametrize(
        "mode",
        [FILTER_MODE_RAW, FILTER_MODE_EMA, FILTER_MODE_KALMAN, FILTER_MODE_EMA_KALMAN],
    )
    def test_invalid_value_never_becomes_zero_in_any_mode(self, mode):
        f = SeriesFilter(mode=mode)
        f.update(45.0)

        assert f.update(None) != 0.0


class TestFilterBankStabilityPerMode:
    """
    O worker não lê SeriesFilter diretamente: ele monta `stability_map` a
    partir de GoniometryFilterBank.get_stability(). É por esse caminho que o
    status chega ao overlay, então ele também precisa estar correto.
    """

    @pytest.mark.parametrize(
        "mode,esperado",
        [
            (FILTER_MODE_RAW, "sem_filtro"),
            (FILTER_MODE_EMA, "suavizacao_ema"),
        ],
    )
    def test_bank_reports_the_mode_status_for_stateless_modes(self, mode, esperado):
        bank = GoniometryFilterBank(mode=mode)
        bank.update("INDEX", "MCP", 45.0)

        assert bank.get_stability("INDEX", "MCP") == esperado

    @pytest.mark.parametrize(
        "mode",
        [FILTER_MODE_RAW, FILTER_MODE_EMA, FILTER_MODE_KALMAN, FILTER_MODE_EMA_KALMAN],
    )
    def test_unknown_series_is_still_nao_inicializado(self, mode):
        """Série que nunca recebeu amostra continua distinguível de uma que
        recebeu — isso não muda em nenhum modo."""
        bank = GoniometryFilterBank(mode=mode)

        assert bank.get_stability("INDEX", "MCP") == "nao_inicializado"

    @pytest.mark.parametrize(
        "mode",
        [FILTER_MODE_RAW, FILTER_MODE_EMA, FILTER_MODE_KALMAN, FILTER_MODE_EMA_KALMAN],
    )
    def test_every_mode_reports_a_non_empty_status(self, mode):
        """Nenhum modo pode devolver string vazia ou None: o overlay usa
        esse valor como chave de cor."""
        bank = GoniometryFilterBank(mode=mode)
        bank.update("INDEX", "MCP", 45.0)
        status = bank.get_stability("INDEX", "MCP")

        assert isinstance(status, str) and status.strip()


class TestStableStateReachability:
    """
    Teste de CARACTERIZAÇÃO, não de requisito.

    Documenta que o estado "estavel" (ganho < 0.15) é inalcançável com os
    parâmetros atuais: o ganho de Kalman converge monotonicamente para
    ~0.27016 e nunca desce abaixo disso. Esta é a evidência que sustenta uma
    eventual recalibração do limiar.

    Este arquivo não corrige isso — mexer em limiar, Q ou R exige validação
    experimental. O teste existe para que o fato fique registrado e para
    detectar se alguém alterar Q/R sem perceber a consequência.
    """

    @pytest.mark.parametrize("mode", [FILTER_MODE_KALMAN, FILTER_MODE_EMA_KALMAN])
    def test_gain_never_drops_below_the_stable_threshold(self, mode):
        f = SeriesFilter(mode=mode)

        menor_ganho = f.kalman_gain
        for _ in range(2000):
            f.update(45.0)
            menor_ganho = min(menor_ganho, f.kalman_gain)

        assert menor_ganho > 0.15
        assert menor_ganho == pytest.approx(0.27015621, abs=1e-8)

    @pytest.mark.parametrize("mode", [FILTER_MODE_KALMAN, FILTER_MODE_EMA_KALMAN])
    def test_estavel_is_never_reported_in_practice(self, mode):
        f = SeriesFilter(mode=mode)

        estados = set()
        for _ in range(2000):
            f.update(45.0)
            estados.add(f.stability)

        assert "estavel" not in estados
