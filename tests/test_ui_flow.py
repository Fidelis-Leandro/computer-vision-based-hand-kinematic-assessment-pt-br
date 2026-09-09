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
from PyQt6.QtWidgets import QMessageBox

# Garante que o diretório raiz do projeto esteja no sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import config
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

    assert hasattr(app_window, "_btn_result_clear")
    assert "Limpar Dados do Paciente" in app_window._btn_result_clear.text()


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

