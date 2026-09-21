"""
tests/test_goniometry_overlay.py — Rede de segurança do overlay de vídeo
=========================================================================

Estes testes cobrem goniometry_overlay.py, que não tinha cobertura própria.
Eles protegem o caminho que a aplicação realmente usa e impedem a volta de
código já removido do módulo.

Por que só `_build_skeleton()` é testado como funcional:
    É o ÚNICO símbolo de goniometry_overlay.py importado em todo o projeto
    (workers/processing_worker.py), e o único que desenha algo que chega à
    tela. O painel de dados e `draw_goniometry_overlay()` foram removidos
    porque ninguém os chamava; testá-los como funcionais daria a impressão
    errada de que fazem parte do produto.

Por que o painel removido não é testado como funcional:
    Ele não tinha chamador e continha um defeito real: usava
    `data.get("TAM", 0.0)`, mas smooth_all() grava a chave com valor None
    quando não há histórico válido — o default nunca entrava em ação e o None
    seguia para classify_tam(None), f"{None:.1f}" e None/270.0, todos
    TypeError. Por isso a ausência dos símbolos é verificada, e não o
    comportamento do painel.

Nenhum teste aqui usa câmera, MediaPipe, Arduino ou interface PyQt6 —
`_build_skeleton()` opera sobre arrays NumPy e objetos simples de landmark.
"""

import os
import sys

import numpy as np
import pytest

# Garante que o diretório raiz do projeto esteja no sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import goniometry_overlay
from goniometry_overlay import _build_skeleton

PANEL_W = 640
PANEL_H = 480

FINGER_JOINTS = {
    "INDEX": ("MCP", "PIP", "DIP"),
    "MIDDLE": ("MCP", "PIP", "DIP"),
    "RING": ("MCP", "PIP", "DIP"),
    "PINKY": ("MCP", "PIP", "DIP"),
    "THUMB": ("MCP", "IP"),
}


class _Landmark:
    """Landmark mínimo no formato que _build_skeleton espera: .x e .y
    normalizados entre 0 e 1, como o MediaPipe entrega."""

    def __init__(self, x: float, y: float) -> None:
        self.x = x
        self.y = y


def _synthetic_landmarks() -> list:
    """
    21 landmarks espalhados de forma determinística.

    Os valores não representam uma mão anatomicamente real — o overlay só
    precisa de 21 pontos distintos para desenhar linhas, arcos e a caixa
    delimitadora. Pontos distintos importam: coordenadas idênticas produziriam
    vetores de norma zero nos cálculos de arco.
    """
    return [_Landmark(0.20 + (i % 5) * 0.13, 0.20 + (i // 5) * 0.15) for i in range(21)]


def _synthetic_angles(tam=None) -> dict:
    """Ângulos válidos para todos os dedos. `tam` opcional para exercitar o
    caminho em que uma métrica vem ausente."""
    angles = {}
    for finger, joints in FINGER_JOINTS.items():
        angles[finger] = {joint: 45.0 for joint in joints}
        angles[finger]["TAM"] = tam
    return angles


def _stability_map(status: str) -> dict:
    return {
        finger: {joint: status for joint in joints}
        for finger, joints in FINGER_JOINTS.items()
    }


def _render(angles=None, stability_map=None, landmarks=None, frozen=False):
    """Chama _build_skeleton com defaults válidos, deixando cada teste
    sobrescrever só o que quer exercitar."""
    return _build_skeleton(
        frame=np.zeros((PANEL_H, PANEL_W, 3), dtype=np.uint8),
        landmarks=_synthetic_landmarks() if landmarks is None else landmarks,
        angles=_synthetic_angles(tam=180.0) if angles is None else angles,
        pw=PANEL_W,
        ph=PANEL_H,
        frozen=frozen,
        stability_map=_stability_map("convergindo") if stability_map is None else stability_map,
    )


def _assert_valid_panel(canvas) -> None:
    assert isinstance(canvas, np.ndarray)
    assert canvas.shape == (PANEL_H, PANEL_W, 3)
    assert canvas.dtype == np.uint8


# =============================================================================
# Caminho ativo — precisa continuar funcionando sem o código removido
# =============================================================================


class TestActiveOverlayPath:
    def test_module_imports_without_error(self):
        """1. O módulo é importável. Se uma remoção deixar um import órfão
        ou uma referência pendurada, isto falha primeiro."""
        assert goniometry_overlay is not None

    def test_build_skeleton_exists(self):
        """2. O único símbolo consumido em produção continua exposto."""
        assert hasattr(goniometry_overlay, "_build_skeleton")
        assert callable(goniometry_overlay._build_skeleton)

    def test_build_skeleton_renders_a_valid_panel(self):
        """3. Entrada válida produz uma imagem válida, sem exceção."""
        _assert_valid_panel(_render())

    def test_build_skeleton_tolerates_none_tam(self):
        """4. TAM ausente não pode derrubar o desenho.

        É o guard `if angle_val is None: continue` que sustenta este teste — e
        é justamente o guard que o painel morto não tem. Em modo RAW, uma
        medição inválida produz None com frequência bem maior."""
        _assert_valid_panel(_render(angles=_synthetic_angles(tam=None)))

    def test_build_skeleton_tolerates_all_angles_none(self):
        """4b. Todas as articulações sem valor: nenhum arco é desenhado, mas o
        painel é produzido."""
        angles = {
            finger: {joint: None for joint in joints}
            for finger, joints in FINGER_JOINTS.items()
        }
        _assert_valid_panel(_render(angles=angles))

    def test_build_skeleton_tolerates_empty_angles(self):
        """5. Dicionário de ângulos vazio — exatamente o que o worker emite
        quando nenhuma mão é detectada (angles_smooth={})."""
        _assert_valid_panel(_render(angles={}))

    def test_build_skeleton_without_landmarks_returns_waiting_panel(self):
        """Sem landmarks o overlay desenha o aviso de espera em vez de
        esqueleto. Não deve estourar por acessar landmarks[i]."""
        _assert_valid_panel(_render(landmarks=[]))

    def test_build_skeleton_tolerates_missing_stability_map(self):
        """stability_map=None é aceito: o overlay cai no status
        'nao_inicializado' para cada articulação."""
        _assert_valid_panel(_render(stability_map=None))

    @pytest.mark.parametrize("status", ["sem_filtro", "suavizacao_ema"])
    def test_build_skeleton_accepts_modes_without_kalman(self, status):
        """6. Os status dos modos RAW e EMA (sem Kalman) são aceitos e
        produzem overlay válido."""
        _assert_valid_panel(_render(stability_map=_stability_map(status)))

    @pytest.mark.parametrize(
        "status", ["estavel", "convergindo", "instavel", "nao_inicializado"]
    )
    def test_build_skeleton_accepts_kalman_states(self, status):
        """7. Os status do filtro de Kalman são aceitos."""
        _assert_valid_panel(_render(stability_map=_stability_map(status)))

    def test_build_skeleton_accepts_unknown_status(self):
        """Status desconhecido não pode quebrar o desenho: _stability_color()
        tem fallback para cinza justamente para isso."""
        _assert_valid_panel(_render(stability_map=_stability_map("status_inexistente")))

    def test_frozen_frame_still_renders(self):
        """O modo 'quadro congelado' é um parâmetro do caminho ativo."""
        _assert_valid_panel(_render(frozen=True))


class TestStabilityColorMapping:
    """_stability_color() é o helper que traduz status em cor e é usado por
    _build_skeleton()."""

    @pytest.mark.parametrize(
        "status",
        [
            "estavel",
            "convergindo",
            "instavel",
            "nao_inicializado",
            "sem_filtro",
            "suavizacao_ema",
            "qualquer_coisa_desconhecida",
        ],
    )
    def test_every_status_maps_to_a_valid_bgr_color(self, status):
        color = goniometry_overlay._stability_color(status)

        assert isinstance(color, tuple) and len(color) == 3
        assert all(isinstance(c, int) and 0 <= c <= 255 for c in color)


# =============================================================================
# Guardas de ausência — símbolos removidos do módulo
# =============================================================================
#
# O painel de dados clínicos lado a lado foi removido: ficou sem nenhum
# chamador quando as métricas por dedo migraram para os widgets PyQt6, e
# presumia TAM sempre numérico, quebrando com o None que smooth_all() produz.
#
# Os testes abaixo impedem a reintrodução acidental desses símbolos. Se algum
# voltar a existir, é sinal de merge malfeito ou de código restaurado sem o
# contexto de por que saiu.


class TestRemovedOverlaySymbolsRemainAbsent:
    @pytest.mark.parametrize(
        "symbol",
        [
            "draw_goniometry_overlay",
            "_build_data_panel",
            "_build_data_template",
            "compose_side_by_side",
            "_data_template_cache",
            "_tam_bar",
        ],
    )
    def test_dead_overlay_symbol_no_longer_exists(self, symbol):
        """Símbolo removido. Este teste impede sua reintrodução acidental.

        `_tam_bar` saiu por arrasto: seu único uso estava dentro de
        `_build_data_panel`."""
        assert not hasattr(goniometry_overlay, symbol)

    @pytest.mark.parametrize("constant", ["GRAY_DARK", "COLOR_SEC"])
    def test_dead_overlay_constant_no_longer_exists(self, constant):
        """Símbolo removido. Este teste impede sua reintrodução acidental.

        Constantes que só o painel removido usava. As demais (_DATA_*) viviam
        dentro do próprio bloco e saíram junto."""
        assert not hasattr(goniometry_overlay, constant)

    def test_digital_goniometer_import_no_longer_needed(self):
        """Import removido. Este teste impede sua reintrodução acidental.

        DigitalGoniometer era importado só para `_build_data_panel` chamar
        classify_tam(). Sem o painel, o import ficou órfão.
        `is_in_normal_range`, do mesmo import, permanece — `_build_skeleton`
        o usa, e a segunda asserção protege isso."""
        assert not hasattr(goniometry_overlay, "DigitalGoniometer")
        assert hasattr(goniometry_overlay, "is_in_normal_range")
