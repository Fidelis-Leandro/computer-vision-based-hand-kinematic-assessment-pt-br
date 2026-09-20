"""
tests/test_session_report.py — Regressão para filter_mode no CSV/PDF (Fase 5)
===============================================================================

Este arquivo é novo porque não existe, em nenhum lugar do projeto, nenhum
teste automatizado para session_report.py (confirmado por busca antes de
criar este arquivo). Misturar esses testes em test_kinematic_assessment.py
(foco em cálculo goniométrico/CSV) ou test_processing_worker.py (foco no
worker) seria um encaixe forçado para um módulo com responsabilidade própria
(carregamento de CSV e geração de relatório).

Testa o comportamento da Fase 5b (implementada):
  - load_session_csv() reconhece a presença/ausência da coluna
    filter_mode em CSVs de sessão, sem exigi-la;
  - o rodapé técnico do relatório menciona o modo real usado, ou deixa
    explícito quando o modo foi apenas assumido (CSV antigo).

Nenhum PDF é renderizado ou lido para testar o texto do rodapé — isso é
testado através de uma função pura (build_footer_method_text). Isso evita
introduzir qualquer dependência nova de leitura de PDF só para este teste.

CSVs de teste são sempre criados em tmp_path (diretório temporário do
pytest) — nenhum dado é gravado no repositório.
"""

import csv
import os

import pytest

from goniometry_csv import CSV_FIELDS
from session_report import load_session_csv


def _synthetic_angles(tam_index: float = 180.0) -> dict:
    """
    Ângulos sintéticos simples e válidos, no formato esperado por
    GoniometryCSVLogger.log() / DigitalGoniometer.compute_all(). Não usa
    MediaPipe nem landmarks reais — os testes aqui não avaliam o cálculo
    científico, só o transporte do dado através do CSV/relatório.
    """
    return {
        "INDEX":  {"MCP": 80.0, "PIP": 90.0, "DIP": 10.0, "ABD": 5.0, "TAM": tam_index},
        "MIDDLE": {"MCP": 80.0, "PIP": 90.0, "DIP": 10.0, "ABD": 0.0, "TAM": 180.0},
        "RING":   {"MCP": 80.0, "PIP": 90.0, "DIP": 10.0, "ABD": 5.0, "TAM": 180.0},
        "PINKY":  {"MCP": 80.0, "PIP": 90.0, "DIP": 10.0, "ABD": 5.0, "TAM": 180.0},
        "THUMB":  {"MCP": 40.0, "IP": 50.0, "TAM": 90.0},
    }


def _write_new_format_csv(path, filter_mode: str, tam_index: float = 200.0) -> None:
    """
    Constrói um CSV no formato atual (filter_mode como última coluna),
    escrevendo diretamente com csv.DictWriter em vez de usar
    GoniometryCSVLogger — mantém este teste independente de qual valor
    default o logger usa, focando só no schema do arquivo.

    CSV_FIELDS já inclui "filter_mode" como última entrada (Fase 5b).
    """
    angles = _synthetic_angles(tam_index=tam_index)

    row = {"timestamp": 1700000000.0, "frame_id": 1}
    for finger in ("INDEX", "MIDDLE", "RING", "PINKY"):
        for joint in ("MCP", "PIP", "DIP", "ABD", "TAM"):
            row[f"{finger}_{joint}"] = angles[finger][joint]
    row["THUMB_MCP"] = angles["THUMB"]["MCP"]
    row["THUMB_IP"] = angles["THUMB"]["IP"]
    row["THUMB_TAM"] = angles["THUMB"]["TAM"]
    row["filter_mode"] = filter_mode

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerow(row)


def _write_old_format_csv(path, tam_index: float = 180.0) -> None:
    """
    Constrói um CSV no formato ANTERIOR à Fase 5: só as 24 colunas
    originais, sem filter_mode.

    GoniometryCSVLogger não serve mais para simular isso — desde a
    Fase 5b ele sempre grava filter_mode (com default "EMA_KALMAN" quando
    não informado, ver test_csv_logger_without_filter_mode_defaults_to_
    ema_kalman em test_kinematic_assessment.py). Por isso, para obter um
    CSV genuinamente sem essa coluna, escrevemos o arquivo diretamente com
    o schema antigo.
    """
    old_fieldnames = [name for name in CSV_FIELDS if name != "filter_mode"]
    angles = _synthetic_angles(tam_index=tam_index)

    row = {"timestamp": 1600000000.0, "frame_id": 1}
    for finger in ("INDEX", "MIDDLE", "RING", "PINKY"):
        for joint in ("MCP", "PIP", "DIP", "ABD", "TAM"):
            row[f"{finger}_{joint}"] = angles[finger][joint]
    row["THUMB_MCP"] = angles["THUMB"]["MCP"]
    row["THUMB_IP"] = angles["THUMB"]["IP"]
    row["THUMB_TAM"] = angles["THUMB"]["TAM"]

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=old_fieldnames)
        writer.writeheader()
        writer.writerow(row)


# =============================================================================
# D. CSV antigo, sem a coluna filter_mode
# =============================================================================


class TestLoadSessionCsvOldFormatWithoutFilterMode:
    def test_old_format_csv_has_no_filter_mode_column(self, tmp_path):
        """Confirma o formato 'antigo' (schema anterior à Fase 5), não uma
        suposição sobre como ele deveria ser.

        Não usa GoniometryCSVLogger: desde a Fase 5b ele sempre grava
        filter_mode (com default "EMA_KALMAN"), então não é mais capaz de
        produzir um CSV sem essa coluna — por isso o arquivo é escrito
        diretamente com o schema antigo (_write_old_format_csv)."""
        csv_path = tmp_path / "old_session.csv"
        _write_old_format_csv(csv_path)

        with open(csv_path, newline="", encoding="utf-8") as f:
            assert "filter_mode" not in csv.DictReader(f).fieldnames

    def test_load_session_csv_reads_clinical_data_from_old_format_without_error(self, tmp_path):
        csv_path = tmp_path / "old_session.csv"
        _write_old_format_csv(csv_path, tam_index=180.0)

        data = load_session_csv(str(csv_path))

        assert data["n_frames"] == 1
        assert data["fingers"]["INDEX"]["TAM"] == [180.0]

    def test_load_session_csv_reports_filter_mode_absent_for_old_csv(self, tmp_path):
        """Comportamento da Fase 5b: identificar explicitamente a ausência
        de registro de modo, em vez de assumir algo silenciosamente."""
        csv_path = tmp_path / "old_session.csv"
        _write_old_format_csv(csv_path)

        data = load_session_csv(str(csv_path))

        assert data["filter_mode"] is None
        assert data["filter_mode_assumed"] is True


# =============================================================================
# E. CSV novo, com a coluna filter_mode
# =============================================================================


class TestLoadSessionCsvNewFormatWithFilterMode:
    @pytest.mark.parametrize("mode", ["RAW", "EMA", "KALMAN", "EMA_KALMAN"])
    def test_load_session_csv_reads_filter_mode_from_new_format(self, tmp_path, mode):
        csv_path = tmp_path / "new_session.csv"
        _write_new_format_csv(csv_path, filter_mode=mode, tam_index=210.0)

        data = load_session_csv(str(csv_path))

        assert data["filter_mode"] == mode
        assert data["filter_mode_assumed"] is False
        # Dado clínico continua sendo lido normalmente, sem interferência
        # da coluna nova.
        assert data["fingers"]["INDEX"]["TAM"] == [210.0]


# =============================================================================
# F. Rodapé técnico do PDF (função pura)
# =============================================================================


class TestFooterMethodText:
    """
    build_footer_method_text() (session_report.py) monta o texto do rodapé
    sem renderizar nem ler nenhum PDF. Import feito dentro de cada teste
    (não no topo do arquivo) por consistência com o restante da suíte —
    isola qualquer problema de import a só estes testes, não à coleta dos
    testes D/E acima.
    """

    @pytest.mark.parametrize(
        "mode,expected_fragment",
        [
            ("RAW", "RAW"),
            ("EMA", "EMA"),
            ("KALMAN", "Kalman"),
            ("EMA_KALMAN", "EMA + Kalman"),
        ],
    )
    def test_footer_mentions_the_real_filter_mode(self, mode, expected_fragment):
        from session_report import build_footer_method_text

        text = build_footer_method_text(filter_mode=mode, assumed=False)

        assert expected_fragment in text

    def test_footer_marks_assumed_mode_explicitly_for_old_csv(self):
        from session_report import build_footer_method_text

        text = build_footer_method_text(filter_mode="EMA_KALMAN", assumed=True)

        assert "assumido" in text.lower()
        assert "EMA" in text and "Kalman" in text

    def test_footer_assumed_text_differs_from_confirmed_text(self):
        """O texto para um modo assumido nunca pode ser idêntico ao texto
        de um modo confirmado — essa diferença é exatamente o que evita
        uma afirmação técnica incorreta sobre uma sessão antiga."""
        from session_report import build_footer_method_text

        assumed_text = build_footer_method_text(filter_mode="EMA_KALMAN", assumed=True)
        confirmed_text = build_footer_method_text(filter_mode="EMA_KALMAN", assumed=False)

        assert assumed_text != confirmed_text


# =============================================================================
# Guarda de regressão (já verdadeiro hoje, não uma falha esperada)
# =============================================================================


class TestGeneratePdfReportToleratesFutureCsvFormat:
    def test_generate_pdf_report_does_not_crash_on_csv_with_extra_filter_mode_column(self, tmp_path):
        """
        Este teste já passa HOJE, sem nenhuma mudança de produção — é uma
        garantia de retrocompatibilidade para frente: como
        load_session_csv() lê por nome de coluna (csv.DictReader), uma
        coluna futura desconhecida (filter_mode) não quebra a geração do
        PDF mesmo antes da Fase 5b existir.
        """
        from session_report import generate_pdf_report

        csv_path = tmp_path / "new_session.csv"
        _write_new_format_csv(csv_path, filter_mode="RAW", tam_index=200.0)

        output_path = generate_pdf_report(
            str(csv_path), patient_name="Paciente Teste", side="Direita"
        )

        assert os.path.isfile(output_path)


# =============================================================================
# Fase 7E-a — coluna demo_mode e aviso de demonstração no PDF (subfase de testes)
# =============================================================================
#
# demo_mode NÃO tem um estado "assumido" como filter_mode: um CSV antigo sem
# essa coluna nunca foi uma sessão de demonstração de verdade (o perfil
# Evento não existia), então False é sempre a leitura correta para CSVs
# antigos — não uma suposição que precise ser marcada à parte.
#
# O helper abaixo escreve o CSV diretamente com csv.DictWriter, montando o
# cabeçalho como CSV_FIELDS + ["demo_mode"]. Esse helper nasceu na 7E-a,
# quando "demo_mode" ainda não fazia parte de CSV_FIELDS; hoje CSV_FIELDS já
# a inclui (7E-e), então o cabeçalho gerado repete a coluna. O csv tolera
# isso e load_session_csv() lê por nome, por isso os testes seguem válidos.
# Mesma técnica de _write_old_format_csv() (acima), que subtrai uma coluna.


def _write_csv_with_demo_mode_column(path, demo_mode: str, tam_index: float = 200.0) -> None:
    future_fieldnames = CSV_FIELDS + ["demo_mode"]
    angles = _synthetic_angles(tam_index=tam_index)

    row = {"timestamp": 1700000000.0, "frame_id": 1}
    for finger in ("INDEX", "MIDDLE", "RING", "PINKY"):
        for joint in ("MCP", "PIP", "DIP", "ABD", "TAM"):
            row[f"{finger}_{joint}"] = angles[finger][joint]
    row["THUMB_MCP"] = angles["THUMB"]["MCP"]
    row["THUMB_IP"] = angles["THUMB"]["IP"]
    row["THUMB_TAM"] = angles["THUMB"]["TAM"]
    row["filter_mode"] = "EMA"
    row["demo_mode"] = demo_mode

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=future_fieldnames)
        writer.writeheader()
        writer.writerow(row)


class TestLoadSessionCsvWillReadDemoModeColumn:
    def test_demo_mode_true_is_read_as_bool(self, tmp_path):
        """Guarda de regressão permanente (não é mais uma transição).

        load_session_csv() devolve a chave "demo_mode" no dicionário,
        lida da coluna do CSV como bool."""
        csv_path = tmp_path / "evento_session.csv"
        _write_csv_with_demo_mode_column(csv_path, demo_mode="True")

        data = load_session_csv(str(csv_path))

        assert data["demo_mode"] is True

    def test_demo_mode_false_is_read_as_bool(self, tmp_path):
        """Guarda de regressão permanente (não é mais uma transição)."""
        csv_path = tmp_path / "clinical_session.csv"
        _write_csv_with_demo_mode_column(csv_path, demo_mode="False")

        data = load_session_csv(str(csv_path))

        assert data["demo_mode"] is False

    def test_old_csv_without_the_column_reads_as_false_not_assumed(self, tmp_path):
        """Guarda de regressão permanente (não é mais uma transição).

        Diferente de filter_mode_assumed: não existe um "demo_mode_assumed"
        proposto, porque não há ambiguidade a marcar — todo CSV gravado
        antes do perfil Evento existir é, por definição, uma sessão
        clínica. False é fato, não suposição."""
        csv_path = tmp_path / "old_session.csv"
        _write_old_format_csv(csv_path)  # formato sem filter_mode NEM demo_mode

        data = load_session_csv(str(csv_path))

        assert data["demo_mode"] is False


class TestFooterDemoModeWarning:
    """
    build_demo_mode_warning_text() (session_report.py) monta o aviso de
    demonstração do rodapé, no mesmo espírito de build_footer_method_text():
    função pura, sem renderizar nem ler PDF. Estes testes fixam o contrato:
    texto de alerta quando demo_mode=True, string vazia quando False.
    """

    def test_warning_text_exists_and_mentions_demonstration_when_true(self):
        """Guarda de regressão permanente (não é mais uma transição)."""
        from session_report import build_demo_mode_warning_text

        texto = build_demo_mode_warning_text(demo_mode=True)

        assert texto.strip() != ""
        assert "demonstra" in texto.lower() or "evento" in texto.lower()

    def test_warning_text_is_empty_when_not_demo(self):
        """Guarda de regressão permanente (não é mais uma transição).

        Uma sessão clínica normal não deve ganhar nenhuma linha extra no
        rodapé — o aviso é exclusivo do perfil Evento."""
        from session_report import build_demo_mode_warning_text

        assert build_demo_mode_warning_text(demo_mode=False) == ""
