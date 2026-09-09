"""
tests/test_processing_worker.py — Integração mínima ProcessingWorker <-> filtros
===================================================================================

Confirma que ProcessingWorker conecta explicitamente o banco de filtros
(GoniometryFilterBank) ao modo definido em config.FILTER_MODE_DEFAULT (Fase 3
da evolução dos modos de filtro), sem alterar o comportamento padrão
histórico (EMA_KALMAN).

Nenhum teste aqui usa câmera, Arduino, porta serial ou uma janela real do
PyQt6. Instanciar ProcessingWorker carrega o MediaPipe real em memória (é
inevitável — o construtor cria um mp.solutions.hands.Hands), mas nenhuma
câmera é aberta e nenhuma thread é iniciada (nunca chamamos .start()).
"""

import pytest

import config
from smoothing import FILTER_MODE_EMA_KALMAN, FILTER_MODE_KALMAN, FILTER_MODE_RAW, GoniometryFilterBank
from workers.processing_worker import ProcessingWorker


class TestProcessingWorkerFilterMode:
    def test_processing_worker_uses_filter_mode_default_from_config(self):
        """O banco de filtros do worker deve usar exatamente o modo
        configurado em config.FILTER_MODE_DEFAULT — não um valor hardcoded
        separado dentro de processing_worker.py."""
        worker = ProcessingWorker()

        assert worker._filter_bank.mode == config.FILTER_MODE_DEFAULT

    def test_processing_worker_default_config_reproduces_ema_kalman_flow(self):
        """Trava o valor atual de config.FILTER_MODE_DEFAULT como
        "EMA_KALMAN" — se esta constante mudar um dia sem intenção, este
        teste é o primeiro a falhar, antes de qualquer impacto em produção."""
        assert config.FILTER_MODE_DEFAULT == FILTER_MODE_EMA_KALMAN

        worker = ProcessingWorker()

        assert worker._filter_bank.mode == FILTER_MODE_EMA_KALMAN

    def test_processing_worker_can_use_raw_ema_kalman_via_direct_bank_construction(self):
        """Os modos alternativos (RAW, EMA, KALMAN) continuam existindo e
        funcionais em GoniometryFilterBank, independentemente do que
        ProcessingWorker usa por padrão. Este teste não toca config.py nem
        ProcessingWorker — apenas confirma, na fronteira entre as duas
        fases, que a "ponte" para modos alternativos continua disponível
        para quando uma fase futura decidir conectá-la de fato."""
        for mode in (FILTER_MODE_RAW, FILTER_MODE_KALMAN, FILTER_MODE_EMA_KALMAN):
            bank = GoniometryFilterBank(mode=mode)
            assert bank.mode == mode
            # Uma atualização simples confirma que o banco está operante
            # nesse modo, sem depender de nenhum estado do ProcessingWorker.
            assert bank.update("INDEX", "MCP", 10.0) == pytest.approx(10.0)

    def test_processing_worker_angles_smooth_structure_unchanged(self):
        """A saída de smooth_all() usada pelo worker preserva a mesma
        estrutura (mesmos dedos e articulações) da entrada — nenhuma chave
        criada ou perdida pela conexão explícita do modo."""
        worker = ProcessingWorker()
        angles_raw = {
            "INDEX": {"MCP": 10.0, "PIP": 20.0, "DIP": 5.0, "ABD": 2.0, "TAM": 35.0},
            "THUMB": {"MCP": 8.0, "IP": 4.0, "TAM": 12.0},
        }

        angles_smooth = worker._filter_bank.smooth_all(angles_raw)

        assert set(angles_smooth.keys()) == set(angles_raw.keys())
        assert set(angles_smooth["INDEX"].keys()) == set(angles_raw["INDEX"].keys())
        assert set(angles_smooth["THUMB"].keys()) == set(angles_raw["THUMB"].keys())
