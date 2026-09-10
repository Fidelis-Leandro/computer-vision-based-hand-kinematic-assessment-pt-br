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

import os
import sys
from typing import Generator

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox

# Garante que o diretório raiz do projeto esteja no sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import config
from themes import COLOR_WARNING
from ui.main_window import MainWindow


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
    """14. O seletor expõe exatamente os quatro modos de smoothing.py, com o
    recomendado em primeiro e RAW por último — a ordem afasta o modo de risco
    do clique acidental de quem abre o combo com pressa."""
    combo = app_window._setup_combo_filter

    assert combo.count() == 4
    assert [combo.itemData(i) for i in range(4)] == ["EMA_KALMAN", "EMA", "KALMAN", "RAW"]


def test_filter_combo_starts_at_the_configured_default(app_window: MainWindow, qtbot):
    """15. A seleção inicial vem de config.FILTER_MODE_DEFAULT — fonte única
    da verdade. Se essa constante mudar, o seletor acompanha sem edição."""
    assert app_window._setup_combo_filter.currentData() == config.FILTER_MODE_DEFAULT
    assert config.FILTER_MODE_DEFAULT == "EMA_KALMAN"


def test_filter_combo_labels_are_readable_for_the_operator(app_window: MainWindow, qtbot):
    """16. Os rótulos visíveis identificam o modo sem exigir conhecimento do
    código, e o recomendado se anuncia como tal."""
    combo = app_window._setup_combo_filter
    labels = {combo.itemData(i): combo.itemText(i) for i in range(combo.count())}

    assert "recomendado" in labels["EMA_KALMAN"].lower()
    assert "EMA" in labels["EMA"]
    assert "Kalman" in labels["KALMAN"]
    assert "RAW" in labels["RAW"]


def test_every_filter_mode_has_its_own_tooltip(app_window: MainWindow, qtbot):
    """17. Cada opção traz explicação própria (ToolTipRole), não um texto
    genérico repetido — quatro tooltips distintos e não vazios."""
    combo = app_window._setup_combo_filter
    tooltips = [
        combo.itemData(i, Qt.ItemDataRole.ToolTipRole) for i in range(combo.count())
    ]

    assert all(tip and tip.strip() for tip in tooltips)
    assert len(set(tooltips)) == 4


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

