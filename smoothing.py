"""
smoothing.py — Pipeline obrigatório de suavização EMA -> Kalman
===============================================================

Este módulo implementa a camada de suavização do sistema.

Pipeline por série temporal:
    raw_angle -> EMA -> Kalman -> smoothed_angle

As classes aqui presentes são independentes de OpenCV e MediaPipe.
Operam exclusivamente sobre valores numéricos, o que simplifica testes e reutilização.

Onde este módulo se encaixa no pipeline (estado real do código, não uma
proposta futura):
    workers/processing_worker.py::_process_frame() calcula `angles_raw`
    chamando DigitalGoniometer.compute_all() (goniometry.py). `angles_raw` é
    uma VARIÁVEL LOCAL e TRANSITÓRIA dentro desse método — existe apenas
    entre a linha em que é calculada e a linha seguinte, em que é passada
    para GoniometryFilterBank.smooth_all() (implementado abaixo). Ela nunca é
    armazenada em ProcessingResult, nunca chega à UI, nunca é gravada no CSV
    (goniometry_csv.py), nunca alimenta o PDF (session_report.py, que só lê
    o CSV) e nunca é enviada à mão robótica (outputs/tam_to_servo.py).

    O único resultado deste módulo que é persistido e efetivamente consumido
    em todo o resto do sistema é a saída de smooth_all(): `angles_smooth`,
    armazenada em ProcessingResult.angles_smooth. É esse valor — e somente
    ele — que chega ao overlay de vídeo, aos gráficos, aos cards da UI, ao
    CSV, ao PDF (via CSV) e à mão robótica.

    Em outras palavras: apesar do nome da etapa 1 (EMA) e da etapa 2 (Kalman)
    sugerirem estágios independentes, o código atual não oferece nenhuma
    forma de obter "só EMA" ou "só Kalman" — SeriesFilter.update() sempre
    executa as duas etapas em sequência, incondicionalmente. O modo de
    operação efetivo do sistema hoje é sempre "EMA seguido de Kalman"
    (equivalente ao que uma futura seleção de modo chamaria de EMA_KALMAN),
    ainda que esse nome não exista formalmente como enum ou constante no
    código atual.

Modos de filtro (introduzidos nesta fase, ainda não conectados à produção):
    RAW, EMA, KALMAN e EMA_KALMAN existem agora como opção explícita em
    SeriesFilter e GoniometryFilterBank, mas workers/processing_worker.py
    continua instanciando essas classes sem informar o modo — o que significa
    que o pipeline de produção continua usando EMA_KALMAN, exatamente como
    antes desta fase. Nenhum outro arquivo (config.py à parte, que só define
    a constante de modo padrão) foi alterado para conectar esses modos a
    qualquer fluxo real.
"""

import logging
import math
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# =============================================================================
# MODOS DE FILTRO
# =============================================================================

# Constantes de string simples (não Enum) para manter o mesmo padrão já usado
# em todo o projeto (ex.: FINGERS/JOINTS em dashboard_utils.py, comparações
# como side == "Direita" em processing_worker.py) — sem introduzir um
# conceito de linguagem novo para algo que só precisa de 4 rótulos fixos.
FILTER_MODE_RAW = "RAW"
FILTER_MODE_EMA = "EMA"
FILTER_MODE_KALMAN = "KALMAN"
FILTER_MODE_EMA_KALMAN = "EMA_KALMAN"

VALID_FILTER_MODES = (
    FILTER_MODE_RAW,
    FILTER_MODE_EMA,
    FILTER_MODE_KALMAN,
    FILTER_MODE_EMA_KALMAN,
)


def _is_valid_measurement(value: object) -> bool:
    """
    True se `value` for um número finito usável pelo filtro.

    None, NaN, +inf e -inf são inválidos. Uma medida inválida nunca deve
    virar 0.0 — 0.0 é uma extensão/abertura real da articulação, não um
    marcador de "sem dado". Quem chama update() com um valor inválido
    recebe o último valor filtrado válido (ou None, se nunca houve um).
    """
    if value is None:
        return False
    try:
        value = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(value)


# =============================================================================
# FILTRO DE SÉRIE ESCALAR
# =============================================================================


class SeriesFilter:
    """
    Filtro escalar para uma única série temporal angular.

    Cada articulação de cada dedo recebe uma instância independente
    para manter seu próprio histórico e estado de Kalman.

    O parâmetro `mode` decide quais etapas update() executa (ver constantes
    FILTER_MODE_* no topo do módulo). O default (FILTER_MODE_EMA_KALMAN)
    preserva exatamente o comportamento histórico deste arquivo — qualquer
    código que já cria SeriesFilter() sem informar `mode` continua se
    comportando de forma idêntica a antes desta classe ganhar o parâmetro.
    """

    def __init__(
        self,
        ema_alpha: float = 0.30,
        kalman_q: float = 0.01,
        kalman_r: float = 0.10,
        mode: str = FILTER_MODE_EMA_KALMAN,
    ):
        if mode not in VALID_FILTER_MODES:
            raise ValueError(
                f"Modo de filtro inválido: {mode!r}. "
                f"Use um de {VALID_FILTER_MODES}."
            )

        # Parâmetros do EMA.
        self.ema_alpha = ema_alpha

        # Parâmetros do filtro escalar de Kalman.
        self.q = kalman_q
        self.r = kalman_r

        self.mode = mode

        # Estado interno.
        self._ema_value: Optional[float] = None
        self._x: Optional[float] = None
        self._p: float = 1.0
        self._k_gain: float = 1.0
        self._n_updates: int = 0

        # True enquanto a série estiver recebendo valores inválidos em
        # sequência. Usado só para limitar o logging por transição
        # (um aviso ao entrar, um registro ao sair) — nunca um por quadro.
        self._last_invalid: bool = False

    def update(self, raw: float) -> Optional[float]:
        """
        Processa um novo valor bruto e retorna o valor suavizado de acordo
        com self.mode.

        Valor inválido (None, NaN, +inf ou -inf):
            Nenhum estado interno é tocado (nem EMA, nem Kalman) — a
            entrada é descartada sem contaminar nada. Nos modos com estado
            (EMA, KALMAN, EMA_KALMAN), devolve o último valor filtrado
            válido, se houver, ou None se a série ainda não tiver nenhum
            histórico válido. Em RAW, devolve sempre None — o modo é
            definido por não ter memória, então "lembrar" um valor aqui
            contradiria sua própria definição. Nunca inventa 0.0: 0.0 é uma
            extensão real de articulação, não um marcador de ausência de dado.

        FILTER_MODE_RAW (entrada válida):
            Devolve o valor bruto convertido para float, sem tocar em nenhum
            estado interno (nem EMA, nem Kalman) e sem nenhum atraso.

        FILTER_MODE_EMA (entrada válida):
            Aplica somente a etapa EMA (reduz jitter entre quadros) e
            atualiza somente o estado de EMA. O estado de Kalman nunca é
            tocado neste modo.

        FILTER_MODE_KALMAN (entrada válida):
            Aplica o filtro de Kalman diretamente sobre o valor bruto (sem
            passar por EMA antes) e atualiza somente o estado de Kalman.

        FILTER_MODE_EMA_KALMAN (default, entrada válida, comportamento histórico):
            Etapa 1 — EMA:
                Reduz oscilações rápidas (jitter) entre quadros.
            Etapa 2 — Kalman:
                Modela a estimativa recursiva do valor real a partir da
                saída do EMA (não do valor bruto) e sua incerteza residual.
            Este ramo reproduz literalmente o código original deste método,
            antes da introdução dos demais modos — nenhuma conta foi
            reescrita, só isolada dentro do `elif` correspondente.
        """
        self._n_updates += 1

        if not _is_valid_measurement(raw):
            if not self._last_invalid:
                logger.warning(
                    "SeriesFilter (mode=%s): valor inválido recebido (None/NaN/"
                    "inf) — estado preservado, devolvendo último valor válido "
                    "(ou None).",
                    self.mode,
                )
                self._last_invalid = True

            if self.mode == FILTER_MODE_RAW:
                return None
            if self.mode == FILTER_MODE_EMA:
                return self._ema_value
            # KALMAN e EMA_KALMAN: o último valor filtrado válido é _x.
            return self._x

        if self._last_invalid:
            logger.info(
                "SeriesFilter (mode=%s): valor válido recebido novamente — "
                "retomando atualização normal.",
                self.mode,
            )
            self._last_invalid = False

        raw = float(raw)

        if self.mode == FILTER_MODE_RAW:
            return float(raw)

        if self.mode == FILTER_MODE_EMA:
            if self._ema_value is None:
                self._ema_value = raw
            else:
                self._ema_value = (
                    self.ema_alpha * raw
                    + (1.0 - self.ema_alpha) * self._ema_value
                )
            return float(self._ema_value)

        if self.mode == FILTER_MODE_KALMAN:
            if self._x is None:
                self._x = raw
                return float(self._x)

            p_minus = self._p + self.q
            self._k_gain = p_minus / (p_minus + self.r)
            self._x = self._x + self._k_gain * (raw - self._x)
            self._p = (1.0 - self._k_gain) * p_minus

            return float(self._x)

        # FILTER_MODE_EMA_KALMAN — comportamento original, inalterado.

        # EMA
        if self._ema_value is None:
            self._ema_value = raw
        else:
            self._ema_value = (
                self.ema_alpha * raw
                + (1.0 - self.ema_alpha) * self._ema_value
            )

        ema_output = self._ema_value

        # Kalman
        if self._x is None:
            self._x = ema_output
            return float(self._x)

        p_minus = self._p + self.q
        self._k_gain = p_minus / (p_minus + self.r)
        self._x = self._x + self._k_gain * (ema_output - self._x)
        self._p = (1.0 - self._k_gain) * p_minus

        return float(self._x)

    @property
    def kalman_gain(self) -> float:
        """
        Retorna o último ganho de Kalman calculado.

        Só é atualizado nos modos que executam a etapa Kalman (KALMAN e
        EMA_KALMAN). Em RAW e EMA, permanece no valor padrão de __init__.
        """
        return self._k_gain

    @property
    def stability(self) -> str:
        """
        Classifica a estabilidade atual do filtro com base no ganho de Kalman.

        Só é significativo nos modos KALMAN e EMA_KALMAN — em RAW e EMA, o
        ganho de Kalman nunca é atualizado, então este valor não reflete a
        estabilidade real da série nesses dois modos.
        """
        if self._k_gain < 0.15:
            return "estavel"
        elif self._k_gain < 0.40:
            return "convergindo"
        else:
            return "instavel"

    @property
    def is_initialized(self) -> bool:
        """
        Retorna se a série já foi inicializada com pelo menos uma amostra.

        A verificação depende de self.mode porque cada modo usa um campo de
        estado diferente:
            RAW          -> não há estado a inicializar; sempre True.
            EMA          -> depende de self._ema_value.
            KALMAN       -> depende de self._x.
            EMA_KALMAN   -> depende de self._x (comportamento original,
                             inalterado: só fica True depois que a etapa
                             Kalman roda pela primeira vez).
        """
        if self.mode == FILTER_MODE_RAW:
            return True
        if self.mode == FILTER_MODE_EMA:
            return self._ema_value is not None
        return self._x is not None

    def reset(self, seed_value: Optional[float] = None) -> None:
        """
        Reinicializa o estado interno do filtro.

        Reinicia os campos de EMA e de Kalman juntos, independentemente do
        modo atual — o campo que o modo ativo não usa simplesmente fica sem
        efeito (ex.: em modo EMA, resetar `_x` não muda nada observável,
        porque update() nesse modo nunca lê `_x`). Isso mantém reset() simples
        e válido para os quatro modos sem precisar de um caminho por modo.
        """
        self._ema_value = seed_value
        self._x = seed_value
        self._p = 1.0
        self._k_gain = 1.0 if seed_value is None else 0.5
        self._n_updates = 0
        # reset() é um recomeço legítimo, não uma "recuperação" de valor
        # inválido — evita um log de recuperação espúrio na próxima amostra.
        self._last_invalid = False


# =============================================================================
# BANCO DE FILTROS
# =============================================================================

class GoniometryFilterBank:
    """
    Banco de filtros indexado por pares (dedo, articulação).

    Esta classe coordena todas as séries temporais do sistema
    e fornece uma API unificada para suavizar o dicionário completo de ângulos.

    O parâmetro `mode` (ver constantes FILTER_MODE_* no topo do módulo) é
    repassado a cada SeriesFilter criado pelo banco. O default
    (FILTER_MODE_EMA_KALMAN) preserva o comportamento histórico — código
    existente que cria GoniometryFilterBank() sem informar `mode` (como
    workers/processing_worker.py faz hoje) continua funcionando de forma
    idêntica a antes desta fase.
    """

    def __init__(
        self,
        ema_alpha: float = 0.30,
        kalman_q: float = 0.01,
        kalman_r: float = 0.10,
        mode: str = FILTER_MODE_EMA_KALMAN,
    ):
        if mode not in VALID_FILTER_MODES:
            raise ValueError(
                f"Modo de filtro inválido: {mode!r}. "
                f"Use um de {VALID_FILTER_MODES}."
            )

        self._ema_alpha = ema_alpha
        self._kalman_q = kalman_q
        self._kalman_r = kalman_r
        self._mode = mode
        self._filters: Dict[str, SeriesFilter] = {}

    @property
    def mode(self) -> str:
        """
        Modo de filtro atualmente em uso por todas as séries deste banco.
        """
        return self._mode

    def update(self, finger: str, joint: str, raw_angle: float) -> float:
        """
        Atualiza uma série específica no banco.
        """
        key = f"{finger}_{joint}"

        if key not in self._filters:
            self._filters[key] = SeriesFilter(
                ema_alpha=self._ema_alpha,
                kalman_q=self._kalman_q,
                kalman_r=self._kalman_r,
                mode=self._mode,
            )

        return self._filters[key].update(raw_angle)

    def smooth_all(self, angles: Dict[str, Dict[str, float]]) -> Dict[str, Dict[str, float]]:
        """
        Suaviza todo o dicionário de ângulos de uma só vez.

        O formato de entrada e saída é preservado para facilitar a integração.

        Este é o único ponto do pipeline cuja saída é persistida além do
        próprio quadro processado: workers/processing_worker.py armazena o
        retorno desta função em ProcessingResult.angles_smooth, que é a
        única fonte de ângulos usada pela UI, pelo CSV, pelo PDF (via CSV) e
        pela mão robótica. O dicionário de entrada (`angles_raw`, calculado
        por DigitalGoniometer.compute_all()) não é persistido em nenhum lugar.
        """
        filtered: Dict[str, Dict[str, float]] = {}

        for finger, metrics in angles.items():
            filtered[finger] = {}
            for joint, raw in metrics.items():
                value = self.update(finger, joint, raw)
                # value é None quando a série não tem nenhum histórico
                # válido ainda (ou está em modo RAW e a amostra é inválida).
                # round(None, 2) levantaria TypeError — preserva None.
                filtered[finger][joint] = round(value, 2) if value is not None else None

        return filtered

    def get_stability(self, finger: str, joint: str) -> str:
        """
        Retorna o estado qualitativo do filtro para uma dada série.
        """
        key = f"{finger}_{joint}"
        if key not in self._filters:
            return "nao_inicializado"
        return self._filters[key].stability

    def get_all_gains(self) -> Dict[str, float]:
        """
        Retorna o ganho de Kalman de todas as séries ativas.
        """
        return {k: f.kalman_gain for k, f in self._filters.items()}

    def reset_finger(self, finger: str) -> None:
        """
        Reinicializa todas as séries associadas a um determinado dedo.
        """
        for key, filt in self._filters.items():
            if key.startswith(finger):
                filt.reset()

    def reset_all(self, seed_angles: Optional[Dict] = None) -> None:
        """
        Reinicializa todas as séries no banco.
        """
        if seed_angles is None:
            for filt in self._filters.values():
                filt.reset()
        else:
            for finger, metrics in seed_angles.items():
                for joint, val in metrics.items():
                    key = f"{finger}_{joint}"
                    if key in self._filters:
                        self._filters[key].reset(seed_value=val)

    def configure(
        self,
        ema_alpha: float = None,
        kalman_q: float = None,
        kalman_r: float = None,
    ) -> None:
        """
        Reconfigura os parâmetros globais do banco.

        A alteração de parâmetros limpa todos os filtros existentes para que novas
        séries sejam criadas com a configuração atualizada.
        """
        if ema_alpha is not None:
            self._ema_alpha = ema_alpha
        if kalman_q is not None:
            self._kalman_q = kalman_q
        if kalman_r is not None:
            self._kalman_r = kalman_r

        self._filters.clear()

    @property
    def active_series_count(self) -> int:
        """
        Número de séries atualmente ativas.
        """
        return len(self._filters)

    def __repr__(self) -> str:
        return (
            f"GoniometryFilterBank("
            f"mode={self._mode}, "
            f"alpha={self._ema_alpha}, "
            f"Q={self._kalman_q}, "
            f"R={self._kalman_r}, "
            f"series={self.active_series_count})"
        )