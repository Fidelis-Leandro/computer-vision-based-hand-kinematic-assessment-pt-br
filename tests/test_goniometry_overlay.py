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

import inspect
import logging
import os
import sys

import cv2
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


# =============================================================================
# Texto fixo com acentos e legenda proporcional
# =============================================================================
#
# O título, a legenda e o aviso de espera são desenhados pelo Pillow com a
# fonte DejaVu Sans do matplotlib; sem ela, o painel usa Hershey com a versão
# ASCII de cada texto. Os testes de fallback alteram o estado do módulo só
# por meio do monkeypatch, que o restaura ao fim de cada teste.

RESOLUTIONS = [(640, 480), (1280, 720), (1920, 1080)]


def _render_at(pw, ph, landmarks=True, frozen=False):
    return _build_skeleton(
        frame=np.zeros((ph, pw, 3), dtype=np.uint8),
        landmarks=_synthetic_landmarks() if landmarks else [],
        angles=_synthetic_angles(tam=180.0),
        pw=pw,
        ph=ph,
        frozen=frozen,
        stability_map=_stability_map("convergindo"),
    )


@pytest.fixture
def text_state(monkeypatch):
    """Estado de texto do módulo isolado: caches vazios e fonte a resolver."""
    monkeypatch.setattr(
        goniometry_overlay, "_unicode_font_path_cache", goniometry_overlay._FONT_UNRESOLVED
    )
    monkeypatch.setattr(goniometry_overlay, "_unicode_fallback_logged", False)
    monkeypatch.setattr(goniometry_overlay, "_font_cache", {})
    monkeypatch.setattr(goniometry_overlay, "_text_cache", {})
    return monkeypatch


def _require_unicode_font():
    if goniometry_overlay._unicode_font_path() is None:
        pytest.skip("Pillow, matplotlib ou DejaVuSans.ttf indisponível neste ambiente")


def _spy_text(monkeypatch, name):
    """Troca um helper de desenho por um espião que registra o texto recebido."""
    original = getattr(goniometry_overlay, name)
    calls = []

    def spy(canvas, text, *args, **kwargs):
        calls.append(text)
        return original(canvas, text, *args, **kwargs)

    monkeypatch.setattr(goniometry_overlay, name, spy)
    return calls


def _spy_legend_labels(monkeypatch):
    """Registra (texto, x, y, px) de cada rótulo da legenda desenhado."""
    original = goniometry_overlay._draw_text
    labels = {
        goniometry_overlay.LEGEND_FIXED,
        goniometry_overlay.LEGEND_MOBILE,
        goniometry_overlay.LEGEND_AXIS,
    }
    calls = []

    def spy(canvas, text, x, y, px, color):
        if text in labels:
            calls.append((text, x, y, px))
        return original(canvas, text, x, y, px, color)

    monkeypatch.setattr(goniometry_overlay, "_draw_text", spy)
    return calls


class TestBuildSkeletonContract:
    def test_signature_is_unchanged(self):
        """A assinatura é o contrato com processing_worker.py."""
        params = list(inspect.signature(_build_skeleton).parameters)
        assert params == ["frame", "landmarks", "angles", "pw", "ph", "frozen", "stability_map"]

    @pytest.mark.parametrize("frozen", [False, True])
    @pytest.mark.parametrize("with_landmarks", [True, False])
    @pytest.mark.parametrize("pw, ph", RESOLUTIONS)
    def test_renders_valid_canvas(self, pw, ph, with_landmarks, frozen):
        canvas = _render_at(pw, ph, landmarks=with_landmarks, frozen=frozen)

        assert isinstance(canvas, np.ndarray)
        assert canvas.shape == (ph, pw, 3)
        assert canvas.dtype == np.uint8


class TestUnicodeText:
    def test_title_constant_is_the_accented_name(self):
        assert goniometry_overlay.OVERLAY_TITLE[0] == "AVALIAÇÃO CINEMÁTICA DA MÃO"

    def test_declared_unicode_text_dependencies_are_installed(self, text_state):
        """Pillow e a DejaVu Sans do matplotlib são dependências declaradas em
        requirements.txt: numa instalação feita a partir dele, o texto com
        acentos está sempre disponível. Este teste falha, e não pula, quando
        falta alguma delas. O fallback ASCII continua coberto à parte, como
        comportamento de execução."""
        from PIL import Image, ImageDraw, ImageFont  # noqa: F401

        path = goniometry_overlay._unicode_font_path()

        assert path is not None, "Pillow, matplotlib ou DejaVuSans.ttf indisponível"
        assert os.path.basename(path) == "DejaVuSans.ttf"
        assert os.path.isfile(path)
        assert goniometry_overlay._unicode_fallback_logged is False

    def test_title_and_mobile_label_go_through_the_unicode_helper(self, text_state):
        _require_unicode_font()
        calls = _spy_text(text_state, "_blit_unicode_text")

        _render_at(1280, 720)

        assert "AVALIAÇÃO CINEMÁTICA DA MÃO" in calls
        assert "Móvel" in calls

    def test_waiting_message_goes_through_the_unicode_helper(self, text_state):
        _require_unicode_font()
        calls = _spy_text(text_state, "_blit_unicode_text")

        _render_at(1280, 720, landmarks=False)

        assert "Aguardando detecção da mão..." in calls

    def test_font_and_text_masks_are_reused_between_frames(self, text_state):
        """A fonte é carregada uma vez por tamanho e cada texto é rasterizado
        uma vez: o segundo quadro reaproveita exatamente os mesmos objetos."""
        _require_unicode_font()
        _render_at(1280, 720)
        fonts = dict(goniometry_overlay._font_cache)
        masks = dict(goniometry_overlay._text_cache)

        _render_at(1280, 720)

        assert goniometry_overlay._font_cache.keys() == fonts.keys()
        assert goniometry_overlay._text_cache.keys() == masks.keys()
        assert all(goniometry_overlay._font_cache[k] is v for k, v in fonts.items())
        assert all(goniometry_overlay._text_cache[k] is v for k, v in masks.items())

    @pytest.mark.parametrize("x, y", [(-30, -10), (70, 40), (500, 500), (-500, -500)])
    def test_unicode_blit_is_clipped_to_the_canvas(self, text_state, x, y):
        _require_unicode_font()
        canvas = np.zeros((50, 80, 3), dtype=np.uint8)

        goniometry_overlay._blit_unicode_text(canvas, "Móvel", x, y, 20, (255, 255, 255))

        assert canvas.shape == (50, 80, 3)

    def test_partially_visible_text_is_still_drawn(self, text_state):
        _require_unicode_font()
        canvas = np.zeros((50, 80, 3), dtype=np.uint8)

        goniometry_overlay._blit_unicode_text(canvas, "Móvel", -10, -5, 20, (255, 255, 255))

        assert canvas.any()


class TestTextFallback:
    def _assert_ascii_texts(self, puts):
        assert "AVALIACAO CINEMATICA DA MAO" in puts
        assert "Movel" in puts
        assert "Aguardando deteccao da mao..." in puts

    def _render_all(self):
        for pw, ph in RESOLUTIONS:
            assert _render_at(pw, ph).shape == (ph, pw, 3)
        assert _render_at(1280, 720, landmarks=False).shape == (720, 1280, 3)

    def test_missing_font_file_falls_back_to_ascii(self, text_state, tmp_path):
        import matplotlib

        text_state.setattr(matplotlib, "get_data_path", lambda: str(tmp_path))
        blits = _spy_text(text_state, "_blit_unicode_text")
        puts = _spy_text(text_state, "_put")

        self._render_all()

        assert blits == []
        self._assert_ascii_texts(puts)

    def test_missing_pillow_falls_back_to_ascii(self, text_state):
        text_state.setitem(sys.modules, "PIL", None)
        blits = _spy_text(text_state, "_blit_unicode_text")
        puts = _spy_text(text_state, "_put")

        self._render_all()

        assert blits == []
        self._assert_ascii_texts(puts)

    def test_rendering_error_falls_back_without_raising(self, text_state):
        _require_unicode_font()

        def broken(*args, **kwargs):
            raise RuntimeError("falha simulada de rasterização")

        text_state.setattr(goniometry_overlay, "_unicode_text_sprite", broken)
        puts = _spy_text(text_state, "_put")

        self._render_all()

        self._assert_ascii_texts(puts)
        assert goniometry_overlay._unicode_font_path() is None

    def test_fallback_is_logged_only_once(self, text_state, tmp_path, caplog):
        import matplotlib

        text_state.setattr(matplotlib, "get_data_path", lambda: str(tmp_path))

        with caplog.at_level(logging.WARNING, logger="goniometry_overlay"):
            self._render_all()
            self._render_all()

        avisos = [r for r in caplog.records if "fallback ASCII" in r.getMessage()]
        assert len(avisos) == 1


class TestResponsiveLegend:
    @pytest.mark.parametrize("pw, ph", RESOLUTIONS)
    def test_legend_band_has_the_three_marker_colors(self, pw, ph):
        """A faixa inferior esquerda contém as três cores semânticas da
        legenda. Com os landmarks sintéticos, nenhum braço do goniômetro
        alcança essa faixa, então as cores só podem vir da legenda."""
        canvas = _render_at(pw, ph)
        band = canvas[ph - ph // 12:, : pw // 2]

        for color in (
            goniometry_overlay.COLOR_STAT,
            goniometry_overlay.COLOR_MOB,
            goniometry_overlay.COLOR_AXIS,
        ):
            assert np.all(band == color, axis=2).any(), f"cor {color} ausente da legenda"

    @pytest.mark.parametrize("pw, ph", RESOLUTIONS)
    def test_legend_keeps_clear_of_the_panel_edges(self, pw, ph):
        canvas = _render_at(pw, ph)
        background = np.array(goniometry_overlay.BG_DARK, dtype=np.uint8)

        assert np.all(canvas[:, :4] == background), "legenda encostada na borda esquerda"
        assert np.all(canvas[-4:, :] == background), "legenda encostada na borda inferior"

    @pytest.mark.parametrize("pw, ph", RESOLUTIONS + [(320, 240)])
    def test_legend_labels_do_not_overlap_and_fit_the_panel(self, monkeypatch, pw, ph):
        calls = _spy_legend_labels(monkeypatch)

        _render_at(pw, ph)

        assert [c[0] for c in calls] == [
            goniometry_overlay.LEGEND_FIXED,
            goniometry_overlay.LEGEND_MOBILE,
            goniometry_overlay.LEGEND_AXIS,
        ]
        right_edges = []
        for text, x, y, px in calls:
            w, h = goniometry_overlay._text_extent(text, px, goniometry_overlay.GRAY_LIGHT)
            assert 0 <= x and x + w <= pw, f"rótulo {text[0]!r} fora da largura do painel"
            assert 0 <= y and y + h <= ph, f"rótulo {text[0]!r} fora da altura do painel"
            right_edges.append(x + w)
        for (_, next_x, _, _), right in zip(calls[1:], right_edges):
            assert right < next_x, "rótulos da legenda sobrepostos"

    def test_legend_font_grows_with_the_panel(self, monkeypatch):
        sizes = []
        for pw, ph in RESOLUTIONS:
            calls = _spy_legend_labels(monkeypatch)
            _render_at(pw, ph)
            sizes.append(calls[0][3])
            monkeypatch.undo()

        assert sizes == sorted(sizes) and sizes[0] < sizes[-1]

    def test_frozen_legend_sits_above_the_frozen_banner(self, monkeypatch):
        pw, ph = 640, 480
        calls = _spy_legend_labels(monkeypatch)

        _render_at(pw, ph, frozen=True)

        (_, banner_h), _ = cv2.getTextSize(
            goniometry_overlay.FROZEN_TEXT,
            cv2.FONT_HERSHEY_DUPLEX,
            goniometry_overlay.FROZEN_SCALE,
            1,
        )
        banner_top = ph - goniometry_overlay.FROZEN_BASELINE_OFFSET - banner_h
        for text, x, y, px in calls:
            _, h = goniometry_overlay._text_extent(text, px, goniometry_overlay.GRAY_LIGHT)
            assert y + h <= banner_top, f"rótulo {text[0]!r} sobre o aviso de quadro congelado"
