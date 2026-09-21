"""
tests/test_ui_flow.py — Suíte de testes automatizados para o fluxo multitelas (PyQt6)
===================================================================================

Testa os fluxos clínicos e transições entre telas da interface gráfica gerenciada
pelo QStackedWidget em ui/main_window.py:
  - Tela 1 (Página 1): Configuração da Sessão
  - Tela 2 (Página 0): Avaliação em Andamento (com barra fixa externa)
  - Tela 3 (Página 2): Resultado da Sessão (ações pós-sessão sob demanda)

Diretrizes de isolamento para execução determinística e segura:
  1. Threads de hardware (CameraWorker e ProcessingWorker) são mockadas para evitar
     acesso a webcams reais e dependência de hardware em ambientes de teste/CI.
  2. Diálogos modais (QMessageBox.exec) são interceptados via monkeypatch para simular
     respostas programáticas imediatas, prevenindo travamento do event loop Qt.
  3. A saída de CSV é isolada via diretório temporário (tmp_path do pytest) para não
     poluir o diretório logs/ do projeto.
  4. Transições assíncronas são aguardadas com qtbot.waitUntil() para evitar race conditions.
"""

import logging
import os
import sys
from typing import Generator
from unittest.mock import MagicMock

import numpy as np
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtPdf import QPdfDocument
from PyQt6.QtWidgets import QLabel, QMessageBox

# Garante que o diretório raiz do projeto esteja no sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import config
import ui.main_window as main_window_module
from outputs.tam_to_servo import TAM_MAX_DEMO
from themes import COLOR_DANGER, COLOR_WARNING
from ui.main_window import MainWindow
from workers.processing_worker import ProcessingResult


@pytest.fixture
def app_window(qtbot, monkeypatch, tmp_path) -> Generator[MainWindow, None, None]:
    """
    Fixture que instancia a MainWindow em ambiente isolado e seguro para testes.

    Configurações de segurança:
      - Redireciona config.LOG_DIR para tmp_path (preserva a pasta logs/ do repositório).
      - Impede que CameraWorker e ProcessingWorker iniciem threads concorrentes de hardware.
      - Registra a janela no qtbot para gerenciamento de ciclo de vida e teardown limpo.
    """
    # Isola o diretório de logs para o diretório temporário desta execução de teste
    monkeypatch.setattr(config, "LOG_DIR", str(tmp_path))

    window = MainWindow()
    qtbot.addWidget(window)

    # Mocka a chamada de início dos workers para não abrir webcam nem thread de processamento
    monkeypatch.setattr(window.camera_worker, "start", lambda: None)
    monkeypatch.setattr(window.processing_worker, "start", lambda: None)

    window.show()

    yield window

    # Teardown seguro: encerra workers e fecha a janela
    try:
        window.camera_worker.stop()
        window.processing_worker.stop()
        window.close()
    except Exception:
        pass


def test_initial_state_setup_page(app_window: MainWindow, qtbot):
    """
    1. MainWindow deve iniciar na Página 1 (Configuração), estado IDLE e barra fixa oculta.
    """
    assert app_window._stack.currentIndex() == 1
    assert app_window._state == "IDLE"
    assert app_window._setup_btn_start.isEnabled() is False
    assert app_window._assessment_bar.isVisible() is False


def test_setup_patient_input_enables_start(app_window: MainWindow, qtbot):
    """
    2. Digitação de nome válido no formulário de configuração habilita o botão de início.
    """
    assert app_window._setup_btn_start.isEnabled() is False

    # Inserção de nome de paciente válido
    app_window._setup_input_patient.setText("Maria Silva")
    assert app_window._setup_btn_start.isEnabled() is True

    # Campo apenas com espaços em branco deve desabilitar
    app_window._setup_input_patient.setText("   ")
    assert app_window._setup_btn_start.isEnabled() is False

    # Redigitação de nome válido reabilita
    app_window._setup_input_patient.setText("João Santos")
    assert app_window._setup_btn_start.isEnabled() is True


def test_start_session_transitions_to_page_0(app_window: MainWindow, qtbot):
    """
    3. Clicar em 'Iniciar Avaliação' transita para a Página 0 com estado RUNNING.
    """
    app_window._setup_input_patient.setText("Paciente Teste")
    assert app_window._setup_btn_start.isEnabled() is True

    app_window._setup_btn_start.click()

    # Aguarda transição para a Tela de Avaliação (Página 0)
    qtbot.waitUntil(lambda: app_window._stack.currentIndex() == 0, timeout=3000)
    assert app_window._state == "RUNNING"
    assert app_window.session_header._input_patient.text() == "Paciente Teste"


def test_assessment_bar_visible_during_running(app_window: MainWindow, qtbot):
    """
    4. Na Página 0 durante RUNNING, a barra fixa superior (_assessment_bar) deve estar visível
       e o botão de encerramento (btn_end) habilitado.
    """
    app_window._setup_input_patient.setText("Paciente Teste")
    app_window._setup_btn_start.click()

    qtbot.waitUntil(lambda: app_window._state == "RUNNING", timeout=3000)

    assert app_window._assessment_bar.isVisible() is True
    assert app_window.btn_end.isEnabled() is True
    assert "Avaliação em andamento" in app_window._assessment_bar_label.text()


def test_confirm_end_session_transitions_to_page_2(app_window: MainWindow, qtbot, monkeypatch):
    """
    5. Confirmação de encerramento transita para a Página 2 (Resultado) com estado STOPPED.
    """
    app_window._setup_input_patient.setText("Paciente Teste")
    app_window._setup_btn_start.click()
    qtbot.waitUntil(lambda: app_window._state == "RUNNING", timeout=3000)

    # Mock do QMessageBox para simular clique no botão de confirmação (AcceptRole)
    def mock_exec_accept(msg_self):
        for btn in msg_self.buttons():
            if msg_self.buttonRole(btn) == QMessageBox.ButtonRole.AcceptRole:
                msg_self._test_clicked = btn
                break
        return 0

    monkeypatch.setattr(QMessageBox, "exec", mock_exec_accept)
    monkeypatch.setattr(
        QMessageBox,
        "clickedButton",
        lambda msg_self: getattr(msg_self, "_test_clicked", None),
    )

    app_window.btn_end.click()

    # Aguarda transição para a Tela de Resultado (Página 2)
    qtbot.waitUntil(lambda: app_window._stack.currentIndex() == 2, timeout=3000)
    assert app_window._state == "STOPPED"


def test_assessment_bar_hidden_on_result_page(app_window: MainWindow, qtbot, monkeypatch):
    """
    6. Na Página 2 (Resultado), a barra fixa de avaliação deve permanecer oculta.
    """
    app_window._setup_input_patient.setText("Paciente Teste")
    app_window._setup_btn_start.click()
    qtbot.waitUntil(lambda: app_window._state == "RUNNING", timeout=3000)

    def mock_exec_accept(msg_self):
        for btn in msg_self.buttons():
            if msg_self.buttonRole(btn) == QMessageBox.ButtonRole.AcceptRole:
                msg_self._test_clicked = btn
                break
        return 0

    monkeypatch.setattr(QMessageBox, "exec", mock_exec_accept)
    monkeypatch.setattr(
        QMessageBox,
        "clickedButton",
        lambda msg_self: getattr(msg_self, "_test_clicked", None),
    )

    app_window.btn_end.click()
    qtbot.waitUntil(lambda: app_window._stack.currentIndex() == 2, timeout=3000)

    # A barra de avaliação deve estar oculta na tela de resultado
    assert app_window._assessment_bar.isVisible() is False


def test_result_page_buttons_actions(app_window: MainWindow, qtbot, monkeypatch):
    """
    7. Controles de ação da Tela 3 estão presentes, com identificações corretas e funcionais.
    """
    app_window._setup_input_patient.setText("Paciente Teste")
    app_window._setup_btn_start.click()
    qtbot.waitUntil(lambda: app_window._state == "RUNNING", timeout=3000)

    def mock_exec_accept(msg_self):
        for btn in msg_self.buttons():
            if msg_self.buttonRole(btn) == QMessageBox.ButtonRole.AcceptRole:
                msg_self._test_clicked = btn
                break
        return 0

    monkeypatch.setattr(QMessageBox, "exec", mock_exec_accept)
    monkeypatch.setattr(
        QMessageBox,
        "clickedButton",
        lambda msg_self: getattr(msg_self, "_test_clicked", None),
    )

    app_window.btn_end.click()
    qtbot.waitUntil(lambda: app_window._stack.currentIndex() == 2, timeout=3000)

    # Valida existência e rótulos dos controles dedicados da Tela 3
    assert hasattr(app_window, "_btn_result_pdf")
    assert "Gerar Relatório PDF" in app_window._btn_result_pdf.text()

    assert hasattr(app_window, "_btn_result_csv")
    assert "Exportar CSV" in app_window._btn_result_csv.text()

    assert hasattr(app_window, "_btn_result_history")
    assert "Abrir Pasta de Sessões" in app_window._btn_result_history.text()

    assert hasattr(app_window, "_btn_result_next")
    assert "Nova Avaliação" in app_window._btn_result_next.text()


def test_toggle_logs_drawer(app_window: MainWindow, qtbot):
    """
    8. O botão btn_toggle_logs expande e recolhe a gaveta do LogWidget corretamente.
    """
    # Posiciona na Página 0 onde os componentes de avaliação e a gaveta residem
    app_window._stack.setCurrentIndex(0)
    qtbot.waitUntil(lambda: app_window._stack.currentIndex() == 0)

    # Estado inicial: gaveta recolhida
    assert app_window._logs_visible is False
    assert app_window.log_widget.isVisible() is False
    assert "Exibir Logs" in app_window.btn_toggle_logs.text()

    # Primeiro clique: expande a gaveta
    app_window.btn_toggle_logs.click()
    assert app_window._logs_visible is True
    assert app_window.log_widget.isVisible() is True
    assert "Ocultar Logs" in app_window.btn_toggle_logs.text()

    # Segundo clique: recolhe a gaveta
    app_window.btn_toggle_logs.click()
    assert app_window._logs_visible is False
    assert app_window.log_widget.isVisible() is False
    assert "Exibir Logs" in app_window.btn_toggle_logs.text()


# =============================================================================
# Fase 4b — robustez de None/NaN/infinito nos widgets (plot_widget, finger_card_widget)
# =============================================================================
#
# Reutiliza o mesmo app_window (MainWindow real, com plot_widget e
# finger_cards já instanciados) em vez de criar widgets isolados — mesmo
# padrão de fixture já usado no restante deste arquivo.


@pytest.mark.parametrize("invalid_tam", [None, float("nan"), float("inf"), float("-inf")])
def test_plot_widget_handles_invalid_tam_without_raising(app_window, qtbot, invalid_tam):
    """9. TAM None/NaN/infinito não deve gerar exceção em update_data() nem
    ser inserido no buffer da curva como 0.0."""
    plot = app_window.plot_widget

    plot.update_data({"INDEX": {"TAM": invalid_tam}}, hand_detected=True)

    assert list(plot._buffers["INDEX"]) == []


def test_plot_widget_valid_tam_still_appended_after_invalid_ones(app_window, qtbot):
    """10. Um TAM válido continua sendo desenhado normalmente mesmo depois
    de quadros com valor inválido."""
    plot = app_window.plot_widget

    plot.update_data({"INDEX": {"TAM": float("nan")}}, hand_detected=True)
    plot.update_data({"INDEX": {"TAM": 42.0}}, hand_detected=True)

    assert list(plot._buffers["INDEX"]) == [42.0]


def test_finger_card_widget_shows_dash_for_none_tam(app_window, qtbot):
    """11. TAM None deve exibir "—" no card, nunca um número (nem 0.0) e sem
    lançar exceção."""
    panel = app_window.finger_cards
    finger_states = {
        "INDEX": {"TAM": None, "fechado": False, "rotulo_assh": "Sem dado", "cor_assh": "#94a3b8"},
    }
    metrics = {"rom": 0.0, "vel_media": 0.0, "vel_pico": 0.0, "freq_hz": 0.0, "cv": 0.0, "regularidade": "-", "n_picos": 0}

    panel.update_all(
        finger_states=finger_states,
        metrics_per_finger={"INDEX": metrics},
        tam_buffers_per_finger={"INDEX": []},
    )

    assert panel._cards["INDEX"]._lbl_tam_value.text() == "—"


def test_finger_card_widget_does_not_label_missing_data_as_ruim(app_window, qtbot):
    """12. Ausência de dado (TAM None) deve exibir "Sem dado", nunca
    "Ruim" — dashboard_utils.classify_hand_state() já decide isso, o card
    só precisa exibir o rótulo recebido sem substituí-lo."""
    panel = app_window.finger_cards
    finger_states = {
        "INDEX": {"TAM": None, "fechado": False, "rotulo_assh": "Sem dado", "cor_assh": "#94a3b8"},
    }
    metrics = {"rom": 0.0, "vel_media": 0.0, "vel_pico": 0.0, "freq_hz": 0.0, "cv": 0.0, "regularidade": "-", "n_picos": 0}

    panel.update_all(
        finger_states=finger_states,
        metrics_per_finger={"INDEX": metrics},
        tam_buffers_per_finger={"INDEX": []},
    )

    label = panel._cards["INDEX"]._lbl_assh.text()
    assert label == "Sem dado"
    assert label != "Ruim"


def test_finger_card_widget_valid_data_still_displayed_normally(app_window, qtbot):
    """13. Dados válidos continuam sendo exibidos exatamente como antes —
    nenhuma regressão introduzida pela proteção contra valores inválidos."""
    panel = app_window.finger_cards
    finger_states = {
        "INDEX": {"TAM": 90.5, "fechado": False, "rotulo_assh": "Razoável", "cor_assh": "#f97316"},
    }
    metrics = {"rom": 0.0, "vel_media": 0.0, "vel_pico": 0.0, "freq_hz": 0.0, "cv": 0.0, "regularidade": "-", "n_picos": 0}

    panel.update_all(
        finger_states=finger_states,
        metrics_per_finger={"INDEX": metrics},
        tam_buffers_per_finger={"INDEX": [90.5]},
    )

    assert panel._cards["INDEX"]._lbl_tam_value.text() == "90.5°"
    assert panel._cards["INDEX"]._lbl_assh.text() == "Razoável"


# =============================================================================
# Fase 6 — seletor de modo de filtro e consolidação do botão de reset
# =============================================================================
#
# Cobrem o seletor de modo de filtro da Tela de Configuração e o botão único
# de reset da Tela de Resultado (Fase 6b, implementada).
#
# Dois pontos de desenho, ambos deliberados:
#
#   1. Os testes de estado (IDLE/READY/STOPPED) chamam _set_state() direto,
#      sem passar por _new_session(). Motivo: a fixture app_window mocka
#      processing_worker.start() na instância criada no __init__, mas
#      _new_session() chama _create_workers(), que substitui essa instância
#      por outra NÃO mockada — passar por lá dispararia uma thread MediaPipe
#      real. Só o teste do botão de reset percorre esse caminho, e ele nunca
#      inicia sessão depois do reset.
#
#   2. O modo de filtro é lido de itemData(), não do texto visível. O rótulo
#      é para o operador e pode ser reescrito; o itemData é o contrato com
#      smoothing.py e não pode mudar sem quebrar o CSV.


def _auto_accept_dialogs(monkeypatch) -> None:
    """
    Faz todo QMessageBox subsequente responder afirmativamente.

    Cobre as DUAS formas de diálogo usadas no projeto, porque um patch só da
    primeira deixa a suíte travada num modal real:

      - QMessageBox construído + .exec()/.clickedButton() — usado por
        _confirm_end_session() e _confirm_new_session(). Mesma técnica já
        aplicada nos testes 5, 6 e 7 deste arquivo.
      - QMessageBox.question(), estático — usado por _new_session(confirm=True).
        Por ser estático, não passa pelo .exec() da instância e precisa de
        patch próprio.
    """
    def mock_exec_accept(msg_self):
        for btn in msg_self.buttons():
            if msg_self.buttonRole(btn) == QMessageBox.ButtonRole.AcceptRole:
                msg_self._test_clicked = btn
                break
        return 0

    monkeypatch.setattr(QMessageBox, "exec", mock_exec_accept)
    monkeypatch.setattr(
        QMessageBox,
        "clickedButton",
        lambda msg_self: getattr(msg_self, "_test_clicked", None),
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )


def _run_session_until_result_page(app_window, qtbot, monkeypatch) -> None:
    """Leva a interface até a Tela 3 (Resultado) com uma sessão encerrada."""
    app_window._setup_input_patient.setText("Paciente Teste")
    app_window._setup_btn_start.click()
    qtbot.waitUntil(lambda: app_window._state == "RUNNING", timeout=3000)

    _auto_accept_dialogs(monkeypatch)
    app_window.btn_end.click()
    qtbot.waitUntil(lambda: app_window._stack.currentIndex() == 2, timeout=3000)


# --- Seletor: estrutura e conteúdo ------------------------------------------


def test_filter_combo_has_the_four_modes_recommended_first(app_window: MainWindow, qtbot):
    """14. O seletor expõe os quatro modos de smoothing.py nos primeiros
    quatro índices, com o recomendado em primeiro e RAW por último — a ordem
    afasta o modo de risco do clique acidental de quem abre o combo com
    pressa. Um quinto item (Evento, Fase 7E-d) vem depois, sem modo próprio
    em smoothing.py — por isso o teste verifica os quatro primeiros índices,
    não o total de itens (ver test_filter_combo_will_have_five_items_with_evento_last)."""
    combo = app_window._setup_combo_filter

    assert [combo.itemData(i) for i in range(4)] == ["EMA_KALMAN", "EMA", "KALMAN", "RAW"]


def test_filter_combo_starts_at_the_configured_default(app_window: MainWindow, qtbot):
    """15. A seleção inicial vem de config.FILTER_MODE_DEFAULT — fonte única
    da verdade. Se essa constante mudar, o seletor acompanha sem edição."""
    assert app_window._setup_combo_filter.currentData() == config.FILTER_MODE_DEFAULT
    assert config.FILTER_MODE_DEFAULT == "EMA_KALMAN"


def test_filter_combo_labels_are_readable_for_the_operator(app_window: MainWindow, qtbot):
    """16. Os rótulos visíveis identificam o modo sem exigir conhecimento do
    código, e o recomendado se anuncia como tal.

    Lê por ÍNDICE, não por um dicionário chaveado por itemData(): desde a
    Fase 7E-d, o item Evento também tem itemData() == "EMA" (mesmo filtro
    real do item 2, por design) — um dicionário {mode: label} colapsaria os
    dois no mesmo valor e o rótulo do Evento sobrescreveria o do EMA
    clínico."""
    combo = app_window._setup_combo_filter

    assert "recomendado" in combo.itemText(0).lower()
    assert "EMA" in combo.itemText(1)
    assert "Kalman" in combo.itemText(2)
    assert "RAW" in combo.itemText(3)


def test_every_filter_mode_has_its_own_tooltip(app_window: MainWindow, qtbot):
    """17. Cada opção traz explicação própria (ToolTipRole), não um texto
    genérico repetido. Cinco itens desde a Fase 7E-d (Evento incluído) —
    cinco tooltips distintos e não vazios, nenhum deles reaproveitado."""
    combo = app_window._setup_combo_filter
    tooltips = [
        combo.itemData(i, Qt.ItemDataRole.ToolTipRole) for i in range(combo.count())
    ]

    assert all(tip and tip.strip() for tip in tooltips)
    assert len(set(tooltips)) == len(main_window_module.FILTER_MODE_OPTIONS)


# --- Seletor: linha de ajuda dinâmica ---------------------------------------


def test_filter_help_line_changes_with_the_selected_mode(app_window: MainWindow, qtbot):
    """18. A linha de ajuda descreve o modo atual — é o que dá ao seletor a
    descoberta que um QComboBox normalmente esconde."""
    combo = app_window._setup_combo_filter
    help_label = app_window._setup_lbl_filter_help

    combo.setCurrentIndex(combo.findData("EMA_KALMAN"))
    texto_padrao = help_label.text()

    combo.setCurrentIndex(combo.findData("KALMAN"))
    texto_kalman = help_label.text()

    assert texto_padrao.strip()
    assert texto_kalman.strip()
    assert texto_padrao != texto_kalman


def test_raw_mode_help_line_is_marked_as_a_warning(app_window: MainWindow, qtbot):
    """19. RAW recebe destaque âmbar e o sinal ⚠; os demais modos não. O
    destaque é específico do modo sem suavização — se valesse para todos,
    não comunicaria nada."""
    combo = app_window._setup_combo_filter
    help_label = app_window._setup_lbl_filter_help

    combo.setCurrentIndex(combo.findData("RAW"))
    assert "⚠" in help_label.text()
    assert COLOR_WARNING.lower() in help_label.styleSheet().lower()

    combo.setCurrentIndex(combo.findData("EMA_KALMAN"))
    assert COLOR_WARNING.lower() not in help_label.styleSheet().lower()


# --- Seletor: bloqueio por estado -------------------------------------------


def test_filter_combo_is_locked_during_running(app_window: MainWindow, qtbot):
    """20. Durante a sessão o seletor fica desabilitado — regra 3."""
    app_window._setup_input_patient.setText("Paciente Teste")
    app_window._setup_btn_start.click()
    qtbot.waitUntil(lambda: app_window._state == "RUNNING", timeout=3000)

    assert app_window._setup_combo_filter.isEnabled() is False


@pytest.mark.parametrize("state", ["IDLE", "READY", "STOPPED"])
def test_filter_combo_is_editable_outside_running(app_window: MainWindow, qtbot, state):
    """21. Fora de RUNNING o seletor volta a ser editável — regra 4."""
    app_window._set_state(state)

    assert app_window._setup_combo_filter.isEnabled() is True


# --- Integração: seletor -> ProcessingWorker -> banco de filtros -------------


def test_selected_mode_is_applied_to_the_filter_bank_on_session_start(
    app_window: MainWindow, qtbot
):
    """22. O modo escolhido chega ao banco de filtros ao iniciar a sessão —
    regra 5. É este valor que _try_log_csv() grava em cada linha do CSV."""
    combo = app_window._setup_combo_filter
    combo.setCurrentIndex(combo.findData("RAW"))

    app_window._setup_input_patient.setText("Paciente Teste")
    app_window._setup_btn_start.click()
    qtbot.waitUntil(lambda: app_window._state == "RUNNING", timeout=3000)

    assert app_window.processing_worker._filter_bank.mode == "RAW"


def test_filter_mode_is_applied_before_the_csv_session_opens(
    app_window: MainWindow, qtbot, monkeypatch
):
    """23. set_filter_mode() precisa acontecer ANTES de start_session().

    Na ordem inversa, o CSV abriria com o banco antigo instalado e as
    primeiras linhas da sessão sairiam com o modo errado — um erro silencioso,
    que só apareceria no rodapé de um PDF já entregue."""
    chamadas = []
    worker = app_window.processing_worker

    monkeypatch.setattr(
        worker, "set_filter_mode", lambda *a, **k: chamadas.append("set_filter_mode")
    )
    monkeypatch.setattr(
        worker, "start_session", lambda *a, **k: chamadas.append("start_session")
    )

    app_window._setup_input_patient.setText("Paciente Teste")
    app_window._setup_btn_start.click()
    qtbot.waitUntil(lambda: app_window._state == "RUNNING", timeout=3000)

    assert chamadas == ["set_filter_mode", "start_session"]


def test_untouched_combo_keeps_the_historical_ema_kalman_pipeline(
    app_window: MainWindow, qtbot
):
    """24. Regressão do comportamento invisível: quem nunca tocar no seletor
    continua rodando exatamente o pipeline clínico de sempre."""
    app_window._setup_input_patient.setText("Paciente Teste")
    app_window._setup_btn_start.click()
    qtbot.waitUntil(lambda: app_window._state == "RUNNING", timeout=3000)

    assert app_window.processing_worker._filter_bank.mode == "EMA_KALMAN"


def test_changing_mode_installs_a_bank_without_inherited_state(
    app_window: MainWindow, qtbot
):
    """25. Regra 7: o banco do novo modo começa vazio, sem nenhuma série
    herdada do modo anterior contaminando as primeiras amostras."""
    worker = app_window.processing_worker
    worker._filter_bank.update("INDEX", "MCP", 42.0)
    assert worker._filter_bank.active_series_count > 0

    worker.set_filter_mode("RAW")

    assert worker._filter_bank.mode == "RAW"
    assert worker._filter_bank.active_series_count == 0


def test_invalid_filter_mode_raises_and_keeps_the_previous_bank(
    app_window: MainWindow, qtbot
):
    """26. Um modo inválido é rejeitado sem deixar o worker sem banco: o
    banco anterior continua instalado e operante."""
    worker = app_window.processing_worker
    banco_antes = worker._filter_bank

    with pytest.raises(ValueError):
        worker.set_filter_mode("MODO_INEXISTENTE")

    assert worker._filter_bank is banco_antes
    assert worker._filter_bank.mode == config.FILTER_MODE_DEFAULT


# --- Consolidação do botão de reset -----------------------------------------


def test_result_page_has_a_single_reset_button(app_window: MainWindow, qtbot, monkeypatch):
    """27. A Tela 3 oferece um único caminho de reset. O botão ambíguo
    "Limpar Dados do Paciente" deixou de existir."""
    _run_session_until_result_page(app_window, qtbot, monkeypatch)

    assert "Nova Avaliação" in app_window._btn_result_next.text()
    assert not hasattr(app_window, "_btn_result_clear")
    assert not hasattr(app_window, "_on_result_clear_patient")


def test_new_evaluation_button_resets_everything_including_filter_mode(
    app_window: MainWindow, qtbot, monkeypatch
):
    """28. O botão único apaga identificação do paciente, devolve o modo de
    filtro ao padrão e termina em IDLE na tela de configuração."""
    combo = app_window._setup_combo_filter
    combo.setCurrentIndex(combo.findData("RAW"))

    _run_session_until_result_page(app_window, qtbot, monkeypatch)

    app_window._btn_result_next.click()

    # _on_result_new_session() é síncrono de ponta a ponta (nenhuma thread é
    # iniciada no reset), então o estado final já vale logo após o clique —
    # não há transição assíncrona a aguardar com qtbot.waitUntil().
    assert app_window._state == "IDLE"
    assert app_window._stack.currentIndex() == 1
    assert app_window._setup_input_patient.text() == ""
    assert app_window.session_header._input_patient.text() == ""
    assert app_window._setup_combo_filter.currentData() == config.FILTER_MODE_DEFAULT


def test_new_evaluation_cancelled_changes_nothing(
    app_window: MainWindow, qtbot, monkeypatch
):
    """29. Cancelar o diálogo não reseta nada — a confirmação é a proteção
    real contra clique acidental, já que o botão é sempre destrutivo."""
    _run_session_until_result_page(app_window, qtbot, monkeypatch)

    # Substitui o auto-accept pelo caminho de recusa, nas duas formas de
    # diálogo (construído e estático), pelo mesmo motivo de _auto_accept_dialogs.
    monkeypatch.setattr(QMessageBox, "exec", lambda msg_self: 0)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda msg_self: None)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.No),
    )

    app_window._btn_result_next.click()

    assert app_window._state == "STOPPED"
    assert app_window._stack.currentIndex() == 2
    assert app_window.session_header._input_patient.text() == "Paciente Teste"


# =============================================================================
# Fase 7D-a — rede de segurança para a remoção de código morto
# =============================================================================
#
# A Fase 7D-b vai remover cinco botões que existem em memória mas nunca são
# inseridos em nenhum layout visível: btn_new_session, btn_start, btn_pdf,
# btn_csv e btn_historico (criados em _create_widgets(), conectados em
# _connect_signals(), geridos por _set_state(), e reunidos apenas em
# _build_button_row(), método que ninguém chama).
#
# Todos foram removidos na Fase 7D-b. Os testes ao final desta seção são as
# guardas que impedem a reintrodução acidental deles.
#
# O caso que exige rede de verdade é o btn_pdf. Ele não é código morto puro:
# _gerar_relatorio(), _on_pdf_finished() e _on_pdf_error() escrevem nele
# ("Gerando PDF..." e a restauração). Só que o botão VISÍVEL da Tela de
# Resultado — _btn_result_pdf — já recebe exatamente o mesmo tratamento nas
# linhas seguintes de cada um desses três métodos. Os testes abaixo travam o
# comportamento do botão visível, que é o que o operador enxerga: se a
# remoção do btn_pdf quebrar o feedback de progresso, eles acusam.
#
# Nada aqui gera PDF de verdade: _PdfGeneratorWorker.start é substituído por
# um no-op, então nenhuma thread roda e nenhum arquivo é escrito. Os diálogos
# modais também são interceptados, nas duas formas usadas pelo projeto
# (QMessageBox construído com .exec() e os estáticos .critical/.question).


def _prepare_pdf_session(app_window, tmp_path, monkeypatch) -> None:
    """
    Deixa a janela pronta para _gerar_relatorio() sem gerar PDF de verdade.

    _gerar_relatorio() sai cedo se _csv_path não apontar para um arquivo
    existente, então um CSV mínimo é criado em tmp_path. O conteúdo não
    importa: o worker que o leria nunca chega a rodar.
    """
    csv_path = tmp_path / "sessao_para_pdf.csv"
    csv_path.write_text("timestamp,frame_id\n", encoding="utf-8")
    app_window._csv_path = str(csv_path)

    monkeypatch.setattr(
        main_window_module._PdfGeneratorWorker, "start", lambda self: None
    )
    monkeypatch.setattr(QMessageBox, "exec", lambda msg_self: 0)
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: 0))


# --- Fluxo do PDF: o botão visível é a referência ----------------------------


def test_generating_pdf_disables_the_visible_button(
    app_window: MainWindow, qtbot, tmp_path, monkeypatch
):
    """30. Durante a geração, o botão visível fica desabilitado e anuncia o
    progresso — proteção contra duplo clique e sinal de que algo acontece."""
    _prepare_pdf_session(app_window, tmp_path, monkeypatch)

    app_window._gerar_relatorio()

    assert app_window._btn_result_pdf.isEnabled() is False
    assert "Gerando PDF" in app_window._btn_result_pdf.text()


def test_pdf_success_restores_the_visible_button(
    app_window: MainWindow, qtbot, tmp_path, monkeypatch
):
    """31. Concluída a geração, o botão visível volta ao estado normal."""
    _prepare_pdf_session(app_window, tmp_path, monkeypatch)
    app_window._gerar_relatorio()

    app_window._on_pdf_finished(str(tmp_path / "relatorio.pdf"))

    assert app_window._btn_result_pdf.isEnabled() is True
    assert "Gerar Relatório PDF" in app_window._btn_result_pdf.text()
    assert "Gerando PDF" not in app_window._btn_result_pdf.text()


def test_pdf_error_restores_the_visible_button(
    app_window: MainWindow, qtbot, tmp_path, monkeypatch
):
    """32. Em caso de falha o botão também precisa voltar — senão a interface
    fica travada em "Gerando PDF..." para sempre, sem forma de tentar de novo."""
    _prepare_pdf_session(app_window, tmp_path, monkeypatch)
    app_window._gerar_relatorio()

    app_window._on_pdf_error("falha simulada de geração")

    assert app_window._btn_result_pdf.isEnabled() is True
    assert "Gerar Relatório PDF" in app_window._btn_result_pdf.text()
    assert "Gerando PDF" not in app_window._btn_result_pdf.text()


# --- Máquina de estados e componentes visíveis -------------------------------


@pytest.mark.parametrize("state", ["IDLE", "READY", "RUNNING", "STOPPED"])
def test_set_state_runs_for_every_state_without_error(
    app_window: MainWindow, qtbot, state
):
    """33. _set_state() referencia cada botão que gere. Se a remoção deixar
    uma referência pendurada, isto estoura com AttributeError."""
    app_window._set_state(state)

    assert app_window._state == state


@pytest.mark.parametrize(
    "widget_name",
    [
        "btn_end",
        "btn_toggle_logs",
        "_btn_result_pdf",
        "_btn_result_csv",
        "_btn_result_history",
        "_btn_result_next",
    ],
)
def test_visible_widgets_still_exist(app_window: MainWindow, qtbot, widget_name):
    """34. Guarda contra remoção excessiva: estes seis são os controles que o
    operador realmente vê e usa. Nenhum deles pode sair na Fase 7D-b."""
    assert hasattr(app_window, widget_name)


def test_new_session_recreates_both_workers(app_window: MainWindow, qtbot):
    """35. _new_session() destrói e recria os workers, em vez de reaproveitá-los.

    É essa recriação que torna ProcessingWorker.reset_state() dispensável: o
    worker novo já nasce com fila vazia, banco de filtros novo e buffers
    zerados. Se algum dia o reset passar a reaproveitar o worker, este teste
    falha e o reset_state volta a fazer falta.

    confirm=False evita o diálogo; nenhuma thread é iniciada depois do reset.
    """
    camera_antes = app_window.camera_worker
    processing_antes = app_window.processing_worker

    assert app_window._new_session(confirm=False) is True

    assert app_window.camera_worker is not camera_antes
    assert app_window.processing_worker is not processing_antes


# --- Guardas de limpeza: símbolos removidos na Fase 7D-b --------------------


@pytest.mark.parametrize(
    "legacy_button",
    ["btn_new_session", "btn_start", "btn_pdf", "btn_csv", "btn_historico"],
)
def test_legacy_invisible_button_no_longer_exists(
    app_window: MainWindow, qtbot, legacy_button
):
    """36. Botões removidos. Este teste impede sua reintrodução acidental.

    Nenhum deles aparecia em qualquer layout. Note que `btn_start` era
    distinto de `_setup_btn_start`, que é visível e permanece."""
    assert not hasattr(app_window, legacy_button)


def test_build_button_row_no_longer_exists(app_window: MainWindow, qtbot):
    """37. Método removido. Este teste impede sua reintrodução acidental.

    _build_button_row() montava a linha de botões legados e não era chamado
    por ninguém — a própria docstring admitia que não entrava em nenhum
    layout visível."""
    assert not hasattr(app_window, "_build_button_row")


# =============================================================================
# Fase 7E-a — perfil "Evento" no seletor de filtro (subfase de testes)
# =============================================================================
#
# "Evento" é um QUINTO ITEM do mesmo QComboBox "Modo de Filtro" — não um
# controle novo, não um quinto algoritmo de smoothing.py. Ele usa o filtro
# EMA de sempre (já válido em VALID_FILTER_MODES/CSV_VALID_FILTER_MODES, sem
# nenhuma mudança de validação em smoothing.py ou goniometry_csv.py) e
# acrescenta um PERFIL de operação (CLINICAL vs DEMO), carregado num segundo
# papel de dado do próprio item do combo — Qt.ItemDataRole.UserRole continua
# guardando só o filtro real (como hoje, para os 5 itens), e um papel
# customizado (UserRole + 1) guarda o perfil. Essa separação é o que garante
# que os quatro chamadores já existentes de currentData()/findData() (o
# combo em si, set_filter_mode(), a coluna filter_mode do CSV) não precisem
# mudar uma linha sequer para os 4 modos clínicos, e recebam "EMA" — um modo
# genuinamente válido — mesmo quando o item selecionado é o Evento.
#
# Estes testes nasceram na subfase 7E-a, antes da implementação, e hoje
# passam todos: o quinto item, o papel de perfil e o reset já existem em
# produção (7E-d). Permanecem como guardas de regressão permanentes do
# comportamento do Evento no seletor.

# Espelha o papel customizado definido em ui/main_window.py (_PROFILE_ROLE,
# Fase 7E-d). Definido aqui, e não importado, porque nasceu antes de o
# símbolo existir em produção; foi mantido assim por simplicidade. Qt já está
# importado no topo deste arquivo; nenhum import novo é necessário aqui.
_PROFILE_ROLE = Qt.ItemDataRole(int(Qt.ItemDataRole.UserRole) + 1)


# --- Comportamento dos 4 modos clínicos e do padrão --------------------------


def test_clinical_items_keep_their_mode_in_the_first_four_slots(
    app_window: MainWindow, qtbot
):
    """
    Os 4 modos clínicos devem ocupar os índices 0-3 do combo com o mesmo
    filtro real de sempre, com o Evento como 5º item no fim da lista. Não
    afirma o total de itens (isso é o teste do quinto item, abaixo) — só que
    os 4 primeiros não mudam de lugar nem de valor.
    """
    combo = app_window._setup_combo_filter
    esperado = ["EMA_KALMAN", "EMA", "KALMAN", "RAW"]

    assert [combo.itemData(i) for i in range(4)] == esperado


def test_filter_combo_default_selection_stays_ema_kalman(
    app_window: MainWindow, qtbot
):
    """
    A seleção inicial do combo continua vindo exclusivamente de
    config.FILTER_MODE_DEFAULT — o Evento não pode se tornar o padrão por
    engano."""
    assert app_window._setup_combo_filter.currentData() == config.FILTER_MODE_DEFAULT
    assert config.FILTER_MODE_DEFAULT == "EMA_KALMAN"


# --- Comportamento do item Evento ---------------------------------------------


def test_filter_combo_will_have_five_items_with_evento_last(
    app_window: MainWindow, qtbot
):
    """Guarda de regressão permanente (não é mais uma transição).

    O combo tem 5 itens. "⚡ Evento — resposta rápida da mão robótica" é o
    quinto, por último — mesma lógica de posicionamento já usada
    para RAW: o item de uso não-clínico fica longe do clique apressado."""
    combo = app_window._setup_combo_filter

    assert combo.count() == 5
    assert "Evento" in combo.itemText(4)


def test_evento_item_carries_ema_as_its_real_filter(app_window: MainWindow, qtbot):
    """Guarda de regressão permanente (não é mais uma transição).

    O UserRole do item Evento é "EMA" — o mesmo filtro válido que os
    demais itens usam. Isto é o que permite ao Evento atravessar
    set_filter_mode() e a coluna filter_mode do CSV sem nenhuma mudança de
    validação: para essas duas peças do sistema, Evento simplesmente "é"
    EMA."""
    combo = app_window._setup_combo_filter

    assert combo.itemData(4) == "EMA"


@pytest.mark.parametrize("index", range(4))
def test_clinical_items_have_no_profile_role_yet(
    app_window: MainWindow, qtbot, index
):
    """Guarda de regressão permanente (não é mais uma transição).

    Os 4 itens clínicos (índices 0-3) carregam ("CLINICAL", None) no papel
    customizado de perfil. Testa os itens clínicos, não o Evento: garante
    que o mecanismo do papel cobre todos os itens, e não só o quinto."""
    combo = app_window._setup_combo_filter

    assert combo.itemData(index, _PROFILE_ROLE) == ("CLINICAL", None)


def test_evento_item_profile_is_demo_with_1_5s_timeout(
    app_window: MainWindow, qtbot
):
    """Guarda de regressão permanente (não é mais uma transição).

    O perfil do Evento é ("DEMO", 1.5): perfil de servo DEMO e tolerância de
    1.5s sem detecção de mão antes da reabertura de segurança (contra 1.0s
    do modo clínico) — valor escolhido a partir da investigação de
    amplitude/oclusão já documentada em INTEGRACAO_MAO_ROBOTICA.md."""
    combo = app_window._setup_combo_filter

    assert combo.itemData(4, _PROFILE_ROLE) == ("DEMO", 1.5)


def test_new_evaluation_resets_combo_from_evento_to_clinical_default(
    app_window: MainWindow, qtbot, monkeypatch
):
    """Guarda de regressão permanente (não é mais uma transição).

    Seleciona Evento e aciona diretamente o mesmo reset que o botão "Nova
    Avaliação" usa (_on_result_new_session(), com o diálogo de confirmação
    interceptado) — sem passar por _start_session(), que não é necessário
    para provar o reset. Depois do reset, o combo volta ao índice de
    EMA_KALMAN e o item padrão carrega o perfil ("CLINICAL", None), nunca
    o do Evento."""
    combo = app_window._setup_combo_filter
    combo.setCurrentIndex(4)  # índice do Evento

    _auto_accept_dialogs(monkeypatch)
    app_window._on_result_new_session()

    assert combo.currentData() == config.FILTER_MODE_DEFAULT
    assert combo.itemData(combo.currentIndex(), _PROFILE_ROLE) == ("CLINICAL", None)


# =============================================================================
# Fase 7E-f — ativação real do perfil Evento (congelamento, robô, badge)
# =============================================================================
#
# Estes testes exercitam o comportamento que a Fase 7E-d apenas preparou:
# selecionar Evento agora tem efeito real sobre o worker de processamento
# (set_demo_mode), o mapeamento de servo (tam_max_table) e o timeout de
# segurança do RobotHandWorker — tudo lido do perfil CONGELADO em
# self._session_demo_mode/self._session_hand_lost_timeout_s, nunca de uma
# nova leitura do combo.
#
# RobotHandWorker e robot_hand_map_all são sempre mockados aqui: nenhum
# teste desta seção abre porta serial, conecta a um Arduino real ou inicia
# uma thread de verdade — quando a classe inteira é substituída por um
# MagicMock, chamar .start() na instância apenas registra a chamada, sem
# nenhuma I/O.


def _fake_processing_result(angles_smooth=None) -> ProcessingResult:
    """ProcessingResult mínimo para exercitar _on_result() sem câmera real."""
    return ProcessingResult(
        frame_overlay=np.zeros((4, 4, 3), dtype=np.uint8),
        angles_smooth=angles_smooth or {},
        hand_state={},
        metrics_per_finger={},
        hand_detected=True,
        frame_id=1,
        fps=30.0,
    )


# --- Requisito 1: congelamento do perfil ao iniciar a sessão ----------------


def test_starting_session_with_evento_freezes_demo_profile(
    app_window: MainWindow, qtbot, monkeypatch
):
    """Selecionar Evento e iniciar a sessão deve: instalar EMA como filtro
    real, marcar demo_mode=True no worker, e congelar
    self._session_demo_mode/self._session_hand_lost_timeout_s em True/1.5."""
    combo = app_window._setup_combo_filter
    combo.setCurrentIndex(4)  # Evento

    filter_mode_calls = []
    demo_mode_calls = []
    monkeypatch.setattr(
        app_window.processing_worker,
        "set_filter_mode",
        lambda m: filter_mode_calls.append(m),
    )
    monkeypatch.setattr(
        app_window.processing_worker,
        "set_demo_mode",
        lambda d: demo_mode_calls.append(d),
    )

    app_window._setup_input_patient.setText("Paciente Teste")
    app_window._setup_btn_start.click()
    qtbot.waitUntil(lambda: app_window._state == "RUNNING", timeout=3000)

    assert filter_mode_calls == ["EMA"]
    assert demo_mode_calls == [True]
    assert app_window._session_demo_mode is True
    assert app_window._session_hand_lost_timeout_s == 1.5


@pytest.mark.parametrize(
    "index,expected_mode",
    [(0, "EMA_KALMAN"), (1, "EMA"), (2, "KALMAN"), (3, "RAW")],
)
def test_starting_session_with_clinical_item_keeps_clinical_profile(
    app_window: MainWindow, qtbot, monkeypatch, index, expected_mode
):
    """Qualquer item clínico deve manter demo_mode=False, timeout de sessão
    None, e instalar o filtro real correspondente — sem nenhum efeito do
    mecanismo de perfil sobre o comportamento já validado nas fases
    anteriores."""
    combo = app_window._setup_combo_filter
    combo.setCurrentIndex(index)

    demo_mode_calls = []
    monkeypatch.setattr(
        app_window.processing_worker,
        "set_demo_mode",
        lambda d: demo_mode_calls.append(d),
    )

    app_window._setup_input_patient.setText("Paciente Teste")
    app_window._setup_btn_start.click()
    qtbot.waitUntil(lambda: app_window._state == "RUNNING", timeout=3000)

    assert demo_mode_calls == [False]
    assert app_window._session_demo_mode is False
    assert app_window._session_hand_lost_timeout_s is None
    assert app_window.processing_worker._filter_bank.mode == expected_mode


# --- Requisito 2: mapeamento do robô com a tabela correta --------------------


def test_on_result_uses_demo_tam_max_table_in_evento_profile(
    app_window: MainWindow, qtbot, monkeypatch
):
    """Com o perfil congelado em DEMO, _on_result() deve chamar
    robot_hand_map_all(..., tam_max_table=TAM_MAX_DEMO)."""
    app_window._session_demo_mode = True
    app_window._robot_hand_worker = MagicMock()
    app_window._robot_hand_state = "on"

    fake_map_all = MagicMock(
        return_value={f: 0 for f in ("polegar", "indicador", "medio", "anelar", "minimo")}
    )
    monkeypatch.setattr(main_window_module, "robot_hand_map_all", fake_map_all)

    app_window._on_result(_fake_processing_result())

    fake_map_all.assert_called_once()
    _, kwargs = fake_map_all.call_args
    assert kwargs.get("tam_max_table") is TAM_MAX_DEMO


def test_on_result_uses_clinical_table_outside_evento_profile(
    app_window: MainWindow, qtbot, monkeypatch
):
    """Fora do perfil Evento, tam_max_table deve ser None — preservando
    exatamente o mapeamento clínico de sempre (TAM_MAX interno do módulo,
    não a tabela paralela TAM_MAX_DEMO)."""
    app_window._session_demo_mode = False
    app_window._robot_hand_worker = MagicMock()
    app_window._robot_hand_state = "on"

    fake_map_all = MagicMock(
        return_value={f: 0 for f in ("polegar", "indicador", "medio", "anelar", "minimo")}
    )
    monkeypatch.setattr(main_window_module, "robot_hand_map_all", fake_map_all)

    app_window._on_result(_fake_processing_result())

    _, kwargs = fake_map_all.call_args
    assert kwargs.get("tam_max_table") is None


# --- Requisito 3: timeout do RobotHandWorker ---------------------------------


def test_start_robot_hand_uses_1_5s_timeout_in_evento_profile(
    app_window: MainWindow, qtbot, monkeypatch
):
    """_start_robot_hand() deve passar hand_lost_timeout_s=1.5 quando o
    perfil congelado é Evento. RobotHandWorker é substituído por um
    MagicMock inteiro: instanciá-lo não conecta a nenhum Arduino, e
    chamar .start() na instância apenas registra a chamada."""
    fake_worker_class = MagicMock()
    monkeypatch.setattr(main_window_module, "RobotHandWorker", fake_worker_class)

    app_window._session_hand_lost_timeout_s = 1.5
    app_window._start_robot_hand()

    _, kwargs = fake_worker_class.call_args
    assert kwargs.get("hand_lost_timeout_s") == 1.5
    fake_worker_class.return_value.start.assert_called_once()


def test_start_robot_hand_uses_clinical_default_timeout_outside_evento(
    app_window: MainWindow, qtbot, monkeypatch
):
    """Fora do perfil Evento, _start_robot_hand() não deve passar
    hand_lost_timeout_s — RobotHandWorker usa seu próprio default (1.0s)
    sem esse valor precisar ser duplicado aqui."""
    fake_worker_class = MagicMock()
    monkeypatch.setattr(main_window_module, "RobotHandWorker", fake_worker_class)

    app_window._session_hand_lost_timeout_s = None
    app_window._start_robot_hand()

    _, kwargs = fake_worker_class.call_args
    assert "hand_lost_timeout_s" not in kwargs


# --- Requisito 4: badge visual -----------------------------------------------


def test_demo_badge_exists_as_a_read_only_label(app_window: MainWindow, qtbot):
    assert hasattr(app_window, "_demo_badge")
    assert isinstance(app_window._demo_badge, QLabel)
    assert app_window._demo_badge.isEnabled() is False


def test_demo_badge_hidden_at_startup(app_window: MainWindow, qtbot):
    assert app_window._demo_badge.isVisible() is False


def test_demo_badge_text_and_color(app_window: MainWindow, qtbot):
    text = app_window._demo_badge.text()
    assert "EVENTO" in text
    assert "DEMONSTRAÇÃO" in text
    assert COLOR_DANGER.lower() in app_window._demo_badge.styleSheet().lower()


def test_demo_badge_appears_only_during_running_with_evento(
    app_window: MainWindow, qtbot
):
    combo = app_window._setup_combo_filter
    combo.setCurrentIndex(4)  # Evento

    app_window._setup_input_patient.setText("Paciente Teste")
    app_window._setup_btn_start.click()
    qtbot.waitUntil(lambda: app_window._state == "RUNNING", timeout=3000)

    assert app_window._demo_badge.isVisible() is True


def test_demo_badge_stays_hidden_during_clinical_session(app_window: MainWindow, qtbot):
    app_window._setup_input_patient.setText("Paciente Teste")
    app_window._setup_btn_start.click()  # default EMA_KALMAN
    qtbot.waitUntil(lambda: app_window._state == "RUNNING", timeout=3000)

    assert app_window._demo_badge.isVisible() is False


def test_demo_badge_hides_when_session_stops(
    app_window: MainWindow, qtbot, monkeypatch
):
    combo = app_window._setup_combo_filter
    combo.setCurrentIndex(4)  # Evento

    _run_session_until_result_page(app_window, qtbot, monkeypatch)

    assert app_window._state == "STOPPED"
    assert app_window._demo_badge.isVisible() is False


# --- Requisito 8: reset por Nova Avaliação -----------------------------------


def test_new_evaluation_resets_demo_profile_and_badge(
    app_window: MainWindow, qtbot, monkeypatch
):
    combo = app_window._setup_combo_filter
    combo.setCurrentIndex(4)  # Evento

    _run_session_until_result_page(app_window, qtbot, monkeypatch)
    app_window._btn_result_next.click()
    qtbot.waitUntil(lambda: app_window._state == "IDLE", timeout=3000)

    assert app_window._session_demo_mode is False
    assert app_window._session_hand_lost_timeout_s is None
    assert app_window._demo_badge.isVisible() is False
    assert combo.currentData() == config.FILTER_MODE_DEFAULT
    assert combo.itemData(combo.currentIndex(), _PROFILE_ROLE) == ("CLINICAL", None)


# =============================================================================
# Fase 8a — "Não Salvar Esta Sessão" na Tela de Resultado (subfase de testes)
# =============================================================================
#
# Hoje o CSV da sessão nasce em _start_session() e permanece em logs/ para
# sempre; não existe nenhum caminho na interface para descartá-lo. Esta fase
# acrescenta um botão na Tela 3 que remove do disco o CSV e, se já tiver sido
# gerado, o relatório PDF daquela sessão.
#
# Nomes contratados por estes testes (produção ainda não os tem):
#   _btn_result_do_not_save      botão na Tela de Resultado
#   _confirm_do_not_save_session()  diálogo de confirmação
#   _on_result_do_not_save_session()  handler que remove os arquivos
#   _session_pdf_path            caminho do PDF gerado nesta sessão
#
# Isolamento: a fixture app_window já redireciona config.LOG_DIR para
# tmp_path, então _start_session() cria o CSV real DENTRO do tmp_path do
# pytest. Nenhum teste desta seção toca a pasta logs/ do repositório, e
# nenhum abre câmera, Arduino ou thread real (start() dos workers é no-op
# na fixture).


def _reject_dialogs(monkeypatch) -> None:
    """Faz todo QMessageBox subsequente responder como 'Cancelar'."""
    monkeypatch.setattr(QMessageBox, "exec", lambda msg_self: 0)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda msg_self: None)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.No),
    )


def _derived_pdf_path(csv_path: str) -> str:
    """
    Caminho do PDF que generate_pdf_report() produz para um dado CSV.

    session_report.py monta o nome como <base do csv>_report.pdf, no mesmo
    diretório do CSV. Reproduzido aqui para que os testes criem o arquivo
    exatamente onde a produção o teria criado.
    """
    return os.path.splitext(csv_path)[0] + "_report.pdf"


def _session_with_files(app_window, qtbot, monkeypatch, with_pdf: bool):
    """
    Roda uma sessão até a Tela de Resultado e devolve (csv_path, pdf_path).

    O CSV é real, criado pelo próprio _start_session() em tmp_path. O PDF,
    quando pedido, é um arquivo de conteúdo irrelevante criado no caminho
    derivado e registrado via _on_pdf_finished() — o mesmo caminho que a
    geração real usaria, sem rodar Matplotlib nem FPDF.
    """
    _run_session_until_result_page(app_window, qtbot, monkeypatch)
    csv_path = app_window._csv_path

    pdf_path = None
    if with_pdf:
        pdf_path = _derived_pdf_path(csv_path)
        with open(pdf_path, "w", encoding="utf-8") as f:
            f.write("PDF de teste")
        app_window._on_pdf_finished(pdf_path)

    return csv_path, pdf_path


# --- 1 a 3: remoção dos arquivos ---------------------------------------------


def test_do_not_save_removes_the_session_csv(
    app_window: MainWindow, qtbot, monkeypatch
):
    """1. O CSV da sessão é removido do disco."""
    csv_path, _ = _session_with_files(app_window, qtbot, monkeypatch, with_pdf=False)
    assert os.path.exists(csv_path)

    app_window._on_result_do_not_save_session()

    assert not os.path.exists(csv_path)


def test_do_not_save_removes_the_generated_pdf(
    app_window: MainWindow, qtbot, monkeypatch
):
    """2. Se o PDF já foi gerado nesta sessão, ele também é removido —
    guardar só o CSV deixaria o relatório clínico em disco, que é
    justamente o que o operador pediu para não manter."""
    csv_path, pdf_path = _session_with_files(
        app_window, qtbot, monkeypatch, with_pdf=True
    )
    assert os.path.exists(pdf_path)

    app_window._on_result_do_not_save_session()

    assert not os.path.exists(csv_path)
    assert not os.path.exists(pdf_path)


def test_do_not_save_without_any_pdf_does_not_error(
    app_window: MainWindow, qtbot, monkeypatch
):
    """3. Nenhum PDF gerado é o caso mais comum: a ausência do arquivo não
    pode virar exceção nem impedir a remoção do CSV."""
    csv_path, _ = _session_with_files(app_window, qtbot, monkeypatch, with_pdf=False)
    assert not os.path.exists(_derived_pdf_path(csv_path))

    app_window._on_result_do_not_save_session()

    assert not os.path.exists(csv_path)


# --- 4: idempotência ---------------------------------------------------------


def test_do_not_save_twice_does_not_raise(
    app_window: MainWindow, qtbot, monkeypatch
):
    """4. Uma segunda chamada, com os arquivos já removidos, não pode
    levantar exceção — o botão fica desabilitado, mas o handler precisa ser
    seguro por si só."""
    _session_with_files(app_window, qtbot, monkeypatch, with_pdf=True)

    app_window._on_result_do_not_save_session()
    app_window._on_result_do_not_save_session()  # não deve levantar


# --- 5: estado dos botões depois da ação -------------------------------------


def test_do_not_save_disables_export_buttons_and_itself(
    app_window: MainWindow, qtbot, monkeypatch
):
    """5. Sem arquivo em disco, "Gerar Relatório PDF" e "Exportar CSV" não
    têm sobre o que operar, e o próprio botão não deve permitir uma segunda
    tentativa."""
    _session_with_files(app_window, qtbot, monkeypatch, with_pdf=True)
    assert app_window._btn_result_pdf.isEnabled() is True
    assert app_window._btn_result_csv.isEnabled() is True

    app_window._on_result_do_not_save_session()

    assert app_window._btn_result_pdf.isEnabled() is False
    assert app_window._btn_result_csv.isEnabled() is False
    assert app_window._btn_result_do_not_save.isEnabled() is False


# --- 6: rastreabilidade sem vazar identificação ------------------------------


def test_do_not_save_logs_the_action_without_the_patient_name(
    app_window: MainWindow, qtbot, monkeypatch, caplog
):
    """6. A ação é registrada para rastreabilidade, mas o log não pode
    reintroduzir justamente o dado que o operador pediu para não manter —
    nem o nome do paciente, nem o caminho completo do arquivo."""
    csv_path, _ = _session_with_files(app_window, qtbot, monkeypatch, with_pdf=True)

    # O início/fim da sessão já logaram nome e caminho; só interessa o que
    # a remoção em si registra.
    caplog.clear()
    with caplog.at_level(logging.INFO):
        app_window._on_result_do_not_save_session()

    assert caplog.text.strip() != ""
    assert "Paciente Teste" not in caplog.text
    assert csv_path not in caplog.text


# --- 7: escopo restrito à sessão atual ---------------------------------------


def test_do_not_save_keeps_files_from_other_sessions(
    app_window: MainWindow, qtbot, monkeypatch, tmp_path
):
    """7. Só os arquivos da sessão atual são removidos. Um CSV de outra
    sessão, no mesmo diretório, precisa sobreviver intacto."""
    outra_sessao = tmp_path / "session_Outro_Paciente_20260101_120000_s1.csv"
    outra_sessao.write_text("timestamp,frame_id\n", encoding="utf-8")

    _session_with_files(app_window, qtbot, monkeypatch, with_pdf=True)

    app_window._on_result_do_not_save_session()

    assert outra_sessao.exists()
    assert outra_sessao.read_text(encoding="utf-8") == "timestamp,frame_id\n"


# --- 8: arquivo bloqueado por outro programa ---------------------------------


def test_do_not_save_warns_when_a_file_is_locked(
    app_window: MainWindow, qtbot, monkeypatch
):
    """8. No Windows, um CSV aberto no Excel não pode ser removido. O
    handler deve avisar e seguir sem travar nem estourar exceção — e o
    arquivo que não pôde ser removido continua em disco."""
    csv_path, _ = _session_with_files(app_window, qtbot, monkeypatch, with_pdf=False)

    def remove_bloqueado(path):
        raise PermissionError(f"arquivo em uso: {path}")

    # monkeypatch restaura os.remove ao final do teste automaticamente.
    monkeypatch.setattr(os, "remove", remove_bloqueado)

    app_window._on_result_do_not_save_session()  # não deve levantar

    assert os.path.exists(csv_path)


# --- 9: corrida com a geração de PDF -----------------------------------------


def test_do_not_save_is_blocked_while_the_pdf_is_being_generated(
    app_window: MainWindow, qtbot, tmp_path, monkeypatch
):
    """9. Remover o CSV enquanto _PdfGeneratorWorker o está lendo quebraria
    a geração em curso. Durante a geração o botão fica desabilitado, e volta
    ao normal quando o PDF termina."""
    _prepare_pdf_session(app_window, tmp_path, monkeypatch)

    app_window._gerar_relatorio()
    assert app_window._btn_result_do_not_save.isEnabled() is False

    app_window._on_pdf_finished(str(tmp_path / "relatorio.pdf"))
    assert app_window._btn_result_do_not_save.isEnabled() is True


# --- 10: cancelamento --------------------------------------------------------


def test_do_not_save_cancelled_keeps_every_file(
    app_window: MainWindow, qtbot, monkeypatch
):
    """10. Cancelar no diálogo não remove nada — a confirmação é a única
    proteção contra o clique acidental numa ação irreversível.

    Exercita o fluxo real (clique no botão -> diálogo -> cancelamento), não
    o handler isolado: é o clique que precisa passar pela confirmação antes
    de qualquer remoção."""
    csv_path, pdf_path = _session_with_files(
        app_window, qtbot, monkeypatch, with_pdf=True
    )

    _reject_dialogs(monkeypatch)
    # Sem este assert, um botão desabilitado faria o teste passar sem nunca
    # ter chegado ao diálogo — um falso verde.
    assert app_window._btn_result_do_not_save.isEnabled() is True
    app_window._btn_result_do_not_save.click()

    assert os.path.exists(csv_path)
    assert os.path.exists(pdf_path)
    assert app_window._btn_result_pdf.isEnabled() is True


# --- 11: convivência com o reset ---------------------------------------------


def test_new_evaluation_works_after_do_not_save(
    app_window: MainWindow, qtbot, monkeypatch
):
    """11. Descartar os arquivos não pode deixar a interface num estado que
    impeça o fluxo seguinte: "Nova Avaliação" continua levando a IDLE na
    Tela de Configuração."""
    _session_with_files(app_window, qtbot, monkeypatch, with_pdf=True)
    app_window._on_result_do_not_save_session()

    app_window._btn_result_next.click()
    qtbot.waitUntil(lambda: app_window._state == "IDLE", timeout=3000)

    assert app_window._stack.currentIndex() == 1
    assert app_window._csv_path == ""


# =============================================================================
# Fase 9a — Visualizador de PDF embutido na Tela de Resultado (subfase de testes)
# =============================================================================
#
# Hoje o relatório PDF só pode ser visto fora da aplicação: nada na interface
# o abre. Esta fase acrescenta um botão na Tela 3 que exibe o PDF da sessão
# num QDialog não modal, usando QPdfView/QPdfDocument (já disponíveis no
# PyQt6 6.11 instalado, sem dependência nova).
#
# Nomes contratados por estes testes (produção ainda não os tem):
#   _btn_result_view_pdf     botão "Visualizar Relatório" na Tela 3
#   _on_result_view_pdf()    handler que abre o visualizador
#   _pdf_viewer_dialog       instância aberta, ou None se nenhuma
#   ui/pdf_viewer_dialog.py  módulo novo com a classe PdfViewerDialog
#
# DECISÃO DE DESIGN (caso 4): com o visualizador já aberto, um segundo
# clique NÃO cria outra instância — reaproveita a existente e a traz para
# frente. Duas janelas do mesmo relatório não trariam informação nova e
# dobrariam os handles de arquivo a fechar antes de remover o PDF, que é
# justamente o risco que o caso 5 protege.
#
# Nenhum PDF real é renderizado: QPdfDocument.load é sempre substituído por
# monkeypatch (a classe do PyQt6 aceita, verificado antes de escrever estes
# testes). Todos os arquivos vivem em tmp_path, nunca em logs/.


def _fake_pdf_load(result=None):
    """Substituto de QPdfDocument.load que não toca disco."""
    resultado = QPdfDocument.Error.None_ if result is None else result
    return lambda self, path: resultado


def _open_viewer(app_window, monkeypatch):
    """Abre o visualizador pelo caminho real (clique no botão)."""
    monkeypatch.setattr(QPdfDocument, "load", _fake_pdf_load())
    app_window._btn_result_view_pdf.click()


# --- 1 e 2: habilitação do botão conforme o PDF existir ----------------------


def test_view_pdf_button_disabled_without_pdf(
    app_window: MainWindow, qtbot, monkeypatch
):
    """1. Sem PDF em disco não há o que visualizar — mesmo critério de
    existência de arquivo já usado pelos demais botões da Tela 3."""
    _session_with_files(app_window, qtbot, monkeypatch, with_pdf=False)

    assert app_window._btn_result_view_pdf.isEnabled() is False


def test_view_pdf_button_enabled_when_pdf_exists(
    app_window: MainWindow, qtbot, monkeypatch
):
    """2. Com o PDF gerado, o botão fica disponível. O rótulo é verificado
    só pelo texto essencial: a presença ou não de emoji é decisão de estilo,
    que não deve ficar travada num teste."""
    _session_with_files(app_window, qtbot, monkeypatch, with_pdf=True)

    assert app_window._btn_result_view_pdf.isEnabled() is True
    assert "Visualizar Relatório" in app_window._btn_result_view_pdf.text()


# --- 3 e 4: abertura e reaproveitamento da janela ----------------------------


def test_clicking_view_pdf_opens_the_viewer_dialog(
    app_window: MainWindow, qtbot, monkeypatch
):
    """3. O clique cria a instância de PdfViewerDialog e a exibe."""
    from ui.pdf_viewer_dialog import PdfViewerDialog

    _session_with_files(app_window, qtbot, monkeypatch, with_pdf=True)
    _open_viewer(app_window, monkeypatch)

    assert isinstance(app_window._pdf_viewer_dialog, PdfViewerDialog)
    assert app_window._pdf_viewer_dialog.isVisible() is True


def test_second_click_reuses_the_open_viewer(
    app_window: MainWindow, qtbot, monkeypatch
):
    """4. Segundo clique não abre uma segunda janela: a instância é a mesma
    (ver DECISÃO DE DESIGN no cabeçalho desta seção)."""
    _session_with_files(app_window, qtbot, monkeypatch, with_pdf=True)
    _open_viewer(app_window, monkeypatch)
    primeira = app_window._pdf_viewer_dialog

    app_window._btn_result_view_pdf.click()

    assert app_window._pdf_viewer_dialog is primeira


# --- 5: o teste mais crítico — não regredir a Fase 8 -------------------------


def test_do_not_save_closes_viewer_before_removing_files(
    app_window: MainWindow, qtbot, monkeypatch
):
    """5. "Não Salvar Esta Sessão" precisa fechar o visualizador e liberar o
    handle do QPdfDocument ANTES de remover os arquivos.

    No Windows, um PDF aberto pelo próprio aplicativo pode bloquear
    os.remove() e transformar o descarte num PermissionError — ou seja, o
    visualizador quebraria a funcionalidade da Fase 8. O espião em
    os.remove registra o estado do visualizador no INSTANTE da remoção, que
    é o que prova a ordem correta; conferir depois não provaria nada."""
    csv_path, pdf_path = _session_with_files(
        app_window, qtbot, monkeypatch, with_pdf=True
    )
    _open_viewer(app_window, monkeypatch)
    assert app_window._pdf_viewer_dialog is not None

    estado = {}
    remove_real = os.remove

    def remove_espiao(path):
        estado.setdefault("viewer_no_momento_da_remocao", app_window._pdf_viewer_dialog)
        remove_real(path)

    monkeypatch.setattr(os, "remove", remove_espiao)
    app_window._on_result_do_not_save_session()

    assert estado["viewer_no_momento_da_remocao"] is None
    assert not os.path.exists(csv_path)
    assert not os.path.exists(pdf_path)


# --- 6 e 7: ciclo de vida do visualizador ------------------------------------


def test_new_evaluation_closes_the_viewer(
    app_window: MainWindow, qtbot, monkeypatch
):
    """6. "Nova Avaliação" limpa a tela; deixar aberto um relatório da
    sessão anterior mostraria dados que não correspondem mais ao que está
    na interface."""
    _session_with_files(app_window, qtbot, monkeypatch, with_pdf=True)
    _open_viewer(app_window, monkeypatch)
    assert app_window._pdf_viewer_dialog is not None

    app_window._on_result_new_session()

    assert app_window._pdf_viewer_dialog is None


def test_starting_a_session_closes_a_leftover_viewer(
    app_window: MainWindow, qtbot, monkeypatch
):
    """7. Iniciar uma avaliação nova com o visualizador da anterior ainda
    aberto deixaria na tela um relatório de outro paciente durante a
    captura."""
    _session_with_files(app_window, qtbot, monkeypatch, with_pdf=True)
    _open_viewer(app_window, monkeypatch)
    assert app_window._pdf_viewer_dialog is not None

    app_window._start_session()
    qtbot.waitUntil(lambda: app_window._state == "RUNNING", timeout=3000)

    assert app_window._pdf_viewer_dialog is None


# --- 8: corrida com a geração do PDF -----------------------------------------


def test_view_pdf_is_blocked_while_the_pdf_is_being_generated(
    app_window: MainWindow, qtbot, tmp_path, monkeypatch
):
    """8. Durante a geração, o arquivo está sendo reescrito pelo
    _PdfGeneratorWorker — abri-lo nesse instante mostraria um PDF
    incompleto. Mesmo padrão já aplicado ao "Não Salvar Esta Sessão"."""
    _prepare_pdf_session(app_window, tmp_path, monkeypatch)

    app_window._gerar_relatorio()
    assert app_window._btn_result_view_pdf.isEnabled() is False

    # O PDF precisa existir para o botão voltar: a habilitação depende do
    # arquivo em disco, não apenas do fim da geração.
    pdf_path = _derived_pdf_path(app_window._csv_path)
    with open(pdf_path, "w", encoding="utf-8") as f:
        f.write("PDF de teste")
    app_window._on_pdf_finished(pdf_path)

    assert app_window._btn_result_view_pdf.isEnabled() is True


# --- 9: PDF ilegível ---------------------------------------------------------


def test_view_pdf_warns_when_the_document_fails_to_load(
    app_window: MainWindow, qtbot, monkeypatch
):
    """9. Arquivo corrompido ou inacessível: o operador é avisado e nenhuma
    exceção escapa. Sem visualizador pendurado depois da falha — uma janela
    vazia seria pior que nenhuma."""
    _session_with_files(app_window, qtbot, monkeypatch, with_pdf=True)

    monkeypatch.setattr(
        QPdfDocument, "load", _fake_pdf_load(QPdfDocument.Error.InvalidFileFormat)
    )
    avisos = []
    monkeypatch.setattr(
        QMessageBox, "warning", staticmethod(lambda *a, **k: avisos.append(a))
    )

    app_window._btn_result_view_pdf.click()  # não deve levantar

    assert avisos, "o operador precisa ser avisado da falha de leitura"
    assert app_window._pdf_viewer_dialog is None

