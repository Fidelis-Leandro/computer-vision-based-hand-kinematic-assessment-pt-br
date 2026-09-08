"""
outputs/__init__.py
===================
Módulo de saídas e atuadores externos (mão robótica Arduino, etc.).
"""

import inspect

# Polyfill global de compatibilidade: o pyFirmata (versão 1.1.0, ver
# requirements.txt) chama inspect.getargspec() internamente ao ser importado.
# Essa função foi removida da biblioteca padrão do Python a partir da versão
# 3.11 (substituída por inspect.getfullargspec) — sem este polyfill,
# "import pyfirmata" falha com AttributeError antes de qualquer tentativa de
# conexão com o Arduino.
#
# A mesma correção é repetida em outputs/robot_hand_output.py de forma
# defensiva (ver comentário lá para o motivo da duplicação). Se este arquivo
# for removido ou alterado, o polyfill de robot_hand_output.py continua
# funcionando de forma independente.
#
# Remover quando pyfirmata for substituído por uma alternativa mantida e
# compatível nativamente com Python 3.11+.
if not hasattr(inspect, "getargspec"):
    inspect.getargspec = inspect.getfullargspec  # type: ignore[attr-defined]
