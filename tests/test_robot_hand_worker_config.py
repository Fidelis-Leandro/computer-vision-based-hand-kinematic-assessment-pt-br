"""
tests/test_robot_hand_worker_config.py — Configuração de RobotHandWorker
==========================================================================

Cobre exclusivamente o timeout de segurança configurável
(hand_lost_timeout_s) que o perfil Evento usa para tolerar 1.5s sem
detecção de mão, contra 1.0s no modo clínico padrão.

Este arquivo é separado porque nenhum dos outros arquivos de teste
(test_ui_flow.py, test_processing_worker.py, test_tam_to_servo.py,
test_session_report.py) importa outputs.robot_hand_output, e nenhum deles é
o lugar natural para um teste do CONSTRUTOR de RobotHandWorker.

Só o construtor é exercitado — nunca .start()/.run(). Instanciar
RobotHandWorker(parent=None) não abre porta serial nem conecta a nenhum
Arduino: toda I/O acontece dentro de run(), que só executa depois de
.start() ser chamado pela QThread, e nenhum teste aqui chama isso. Mesmo
padrão de isolamento já usado por ProcessingWorker() em
test_processing_worker.py (instanciado ali sem qtbot/app_window e sem abrir
câmera).
"""

from outputs.robot_hand_output import HAND_LOST_TIMEOUT_S, RobotHandWorker


class TestHandLostTimeoutIsConfigurable:
    def test_default_timeout_matches_the_clinical_constant(self):
        """Sem o argumento, o worker usa exatamente
        HAND_LOST_TIMEOUT_S (1.0s) — o comportamento clínico não muda só
        porque o parâmetro existe. O valor fica guardado no atributo de
        instância _hand_lost_timeout_s, que _send_cycle() lê."""
        worker = RobotHandWorker(parent=None)

        assert worker._hand_lost_timeout_s == HAND_LOST_TIMEOUT_S

    def test_custom_timeout_is_accepted_and_stored(self):
        """O construtor aceita hand_lost_timeout_s e guarda o valor na
        instância, sem nenhuma I/O (nenhuma porta serial é aberta)."""
        worker = RobotHandWorker(parent=None, hand_lost_timeout_s=1.5)

        assert worker._hand_lost_timeout_s == 1.5

    def test_custom_timeout_does_not_mutate_the_module_constant(self):
        """Guarda de sanidade: passar um timeout customizado para uma
        instância nunca pode alterar HAND_LOST_TIMEOUT_S para as demais —
        isso vazaria o timeout do perfil Evento para uma sessão clínica
        seguinte que reutilizasse o mesmo processo."""
        RobotHandWorker(parent=None, hand_lost_timeout_s=1.5)

        assert HAND_LOST_TIMEOUT_S == 1.0
