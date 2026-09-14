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

from unittest.mock import MagicMock

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


class TestUpdateBuffersInvalidValues:
    """
    Fase 4b: _update_buffers() deve ignorar TAM inválido (None/NaN/inf) sem
    levantar exceção, sem inserir 0.0 no lugar, e sem apagar o histórico
    válido já acumulado no buffer.
    """

    def test_valid_tam_is_appended_to_the_buffer(self):
        worker = ProcessingWorker()
        worker._update_buffers({"INDEX": {"TAM": 45.0}}, timestamp=1.0)

        assert list(worker._tam_buffers["INDEX"]) == [45.0]
        assert list(worker._time_buffers["INDEX"]) == [1.0]

    @pytest.mark.parametrize("invalid", [None, float("nan"), float("inf"), float("-inf")])
    def test_invalid_tam_does_not_raise_and_is_not_appended(self, invalid):
        worker = ProcessingWorker()

        worker._update_buffers({"INDEX": {"TAM": invalid}}, timestamp=1.0)

        assert list(worker._tam_buffers["INDEX"]) == []
        assert list(worker._time_buffers["INDEX"]) == []

    def test_none_tam_is_never_recorded_as_zero(self):
        worker = ProcessingWorker()
        worker._update_buffers({"INDEX": {"TAM": None}}, timestamp=1.0)

        assert 0.0 not in worker._tam_buffers["INDEX"]

    def test_invalid_value_preserves_existing_valid_history(self):
        worker = ProcessingWorker()
        worker._update_buffers({"INDEX": {"TAM": 45.0}}, timestamp=1.0)
        worker._update_buffers({"INDEX": {"TAM": 50.0}}, timestamp=2.0)

        worker._update_buffers({"INDEX": {"TAM": float("nan")}}, timestamp=3.0)

        assert list(worker._tam_buffers["INDEX"]) == [45.0, 50.0]
        assert list(worker._time_buffers["INDEX"]) == [1.0, 2.0]

    def test_valid_samples_continue_being_processed_after_an_invalid_one(self):
        worker = ProcessingWorker()
        worker._update_buffers({"INDEX": {"TAM": 45.0}}, timestamp=1.0)
        worker._update_buffers({"INDEX": {"TAM": None}}, timestamp=2.0)
        worker._update_buffers({"INDEX": {"TAM": 60.0}}, timestamp=3.0)

        assert list(worker._tam_buffers["INDEX"]) == [45.0, 60.0]
        assert list(worker._time_buffers["INDEX"]) == [1.0, 3.0]


class TestProcessingWorkerForwardsFilterModeToCsvLogger:
    """
    Fase 5: ProcessingWorker encaminha self._filter_bank.mode ao
    GoniometryCSVLogger em cada linha registrada. Usa um logger fake
    (MagicMock) — nenhum arquivo CSV real é criado, nenhuma
    câmera/Arduino/interface é usada.
    """

    def _worker_with_fake_logger(self) -> tuple:
        worker = ProcessingWorker()
        fake_logger = MagicMock()
        worker._csv_logger = fake_logger
        worker._session_active = True
        worker._frame_id = 7
        return worker, fake_logger

    def test_try_log_csv_forwards_current_filter_bank_mode(self):
        worker, fake_logger = self._worker_with_fake_logger()

        worker._try_log_csv({"INDEX": {"MCP": 10.0}})

        fake_logger.log.assert_called_once()
        _, kwargs = fake_logger.log.call_args
        assert kwargs.get("filter_mode") == worker._filter_bank.mode

    def test_try_log_csv_forwards_ema_kalman_when_that_is_the_configured_default(self):
        assert config.FILTER_MODE_DEFAULT == FILTER_MODE_EMA_KALMAN
        worker, fake_logger = self._worker_with_fake_logger()

        worker._try_log_csv({"INDEX": {"MCP": 10.0}})

        _, kwargs = fake_logger.log.call_args
        assert kwargs.get("filter_mode") == FILTER_MODE_EMA_KALMAN

    def test_try_log_csv_forwards_a_non_default_mode_too(self, monkeypatch):
        # monkeypatch restaura config.FILTER_MODE_DEFAULT automaticamente
        # ao final do teste — nenhuma limpeza manual necessária.
        monkeypatch.setattr(config, "FILTER_MODE_DEFAULT", FILTER_MODE_RAW)

        worker = ProcessingWorker()  # criado DEPOIS do monkeypatch: usa RAW
        fake_logger = MagicMock()
        worker._csv_logger = fake_logger
        worker._session_active = True
        worker._frame_id = 1

        worker._try_log_csv({"INDEX": {"MCP": 10.0}})

        _, kwargs = fake_logger.log.call_args
        assert kwargs.get("filter_mode") == FILTER_MODE_RAW


# =============================================================================
# Fase 7D-a — transição para a remoção de reset_state()
# =============================================================================


class TestResetStateRemovedInPhase7Db:
    """
    reset_state() foi escrito para reaproveitar o worker entre sessões, mas o
    sistema seguiu outro caminho: MainWindow._new_session() destrói e recria
    os workers do zero, porque um QThread não reinicia depois que run()
    retorna. O worker recriado já nasce com fila vazia, banco de filtros novo,
    buffers zerados e contadores em zero — tudo o que reset_state() faria, e
    ainda com um MediaPipe novo.

    Resultado: o método nunca chegou a ser chamado. Uma busca no repositório
    inteiro encontra uma única ocorrência, a própria linha `def`. A docstring
    dele afirma "Chamado quando uma nova sessão é iniciada", o que nunca foi
    verdade.

    O método foi removido na Fase 7D-b. O teste abaixo permanece como guarda
    permanente contra sua reintrodução acidental.

    Não instancia ProcessingWorker — hasattr na classe basta, e assim nenhum
    MediaPipe é carregado neste teste.
    """

    def test_reset_state_no_longer_exists(self):
        """Método removido. Este teste impede sua reintrodução acidental."""
        assert not hasattr(ProcessingWorker, "reset_state")

    def test_reset_for_hand_change_still_exists(self):
        """Guarda contra remoção excessiva: _reset_for_hand_change() tem nome
        parecido, mas é chamado de verdade quando a mão avaliada muda."""
        assert hasattr(ProcessingWorker, "_reset_for_hand_change")
