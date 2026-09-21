"""
tests/test_session_report.py — Regressão para filter_mode no CSV/PDF
===============================================================================

Este arquivo reúne os testes de session_report.py. Misturá-los em
test_kinematic_assessment.py (foco em cálculo goniométrico/CSV) ou
test_processing_worker.py (foco no worker) seria um encaixe forçado para um
módulo com responsabilidade própria (carregamento de CSV e geração de
relatório).

Testa o comportamento do módulo quanto ao filter_mode:
  - load_session_csv() reconhece a presença/ausência da coluna
    filter_mode em CSVs de sessão, sem exigi-la;
  - o rodapé técnico do relatório menciona o modo real usado, ou deixa
    explícito quando o modo foi apenas assumido (CSV sem a coluna).

Nenhum PDF é renderizado ou lido para testar o texto do rodapé — isso é
testado através de uma função pura (build_footer_method_text). Isso evita
introduzir qualquer dependência nova de leitura de PDF só para este teste.

CSVs de teste são sempre criados em tmp_path (diretório temporário do
pytest) — nenhum dado é gravado no repositório.
"""

import csv
import os
import re
import warnings
import zlib

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
    Constrói um CSV no formato atual (com a coluna filter_mode),
    escrevendo diretamente com csv.DictWriter em vez de usar
    GoniometryCSVLogger — mantém este teste independente de qual valor
    default o logger usa, focando só no schema do arquivo.

    CSV_FIELDS inclui "filter_mode" imediatamente antes de "demo_mode".
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
    Constrói um CSV sem as colunas filter_mode e demo_mode: o cabeçalho é
    CSV_FIELDS sem essas duas colunas.

    GoniometryCSVLogger não serve para simular isso — ele grava as duas
    colunas em toda linha, com defaults próprios quando o chamador não as
    informa ("EMA_KALMAN" para filter_mode e False para demo_mode, ver
    test_csv_logger_without_filter_mode_defaults_to_ema_kalman e
    test_csv_logger_without_demo_mode_defaults_to_false em
    test_kinematic_assessment.py). Por isso o arquivo é escrito diretamente
    com csv.DictWriter.
    """
    old_fieldnames = [
        name for name in CSV_FIELDS if name not in ("filter_mode", "demo_mode")
    ]
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
# D. CSV antigo, sem as colunas filter_mode e demo_mode
# =============================================================================


class TestLoadSessionCsvOldFormatWithoutFilterMode:
    def test_old_format_csv_has_neither_filter_mode_nor_demo_mode_column(
        self, tmp_path
    ):
        """Confirma que o CSV gerado pelo helper não tem as colunas
        filter_mode e demo_mode, em vez de supor que não tem.

        Não usa GoniometryCSVLogger: ele grava as duas colunas em toda
        linha, então não produz um CSV sem elas — por isso o arquivo é
        escrito diretamente (_write_old_format_csv)."""
        csv_path = tmp_path / "old_session.csv"
        _write_old_format_csv(csv_path)

        with open(csv_path, newline="", encoding="utf-8") as f:
            fieldnames = csv.DictReader(f).fieldnames

        assert "filter_mode" not in fieldnames
        assert "demo_mode" not in fieldnames

    def test_load_session_csv_reads_clinical_data_from_old_format_without_error(self, tmp_path):
        csv_path = tmp_path / "old_session.csv"
        _write_old_format_csv(csv_path, tam_index=180.0)

        data = load_session_csv(str(csv_path))

        assert data["n_frames"] == 1
        assert data["fingers"]["INDEX"]["TAM"] == [180.0]

    def test_load_session_csv_reports_filter_mode_absent_for_old_csv(self, tmp_path):
        """Identifica explicitamente a ausência de registro de modo, em vez
        de assumir algo silenciosamente."""
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
# Tolerância a colunas extras no CSV
# =============================================================================


class TestGeneratePdfReportWithFilterModeColumn:
    def test_generate_pdf_report_does_not_crash_on_csv_with_extra_filter_mode_column(self, tmp_path):
        """
        Como load_session_csv() lê por nome de coluna (csv.DictReader), uma
        coluna adicional como filter_mode não quebra a geração do PDF.
        """
        from session_report import generate_pdf_report

        csv_path = tmp_path / "new_session.csv"
        _write_new_format_csv(csv_path, filter_mode="RAW", tam_index=200.0)

        output_path = generate_pdf_report(
            str(csv_path), patient_name="Paciente Teste", side="Direita"
        )

        assert os.path.isfile(output_path)


# =============================================================================
# Coluna demo_mode e aviso de demonstração no PDF
# =============================================================================
#
# demo_mode NÃO tem um estado "assumido" como filter_mode: um CSV sem a
# coluna demo_mode não é uma sessão de demonstração, então False é sempre a
# leitura correta — não uma suposição que precise ser marcada à parte.
#
# O helper abaixo escreve o CSV diretamente com csv.DictWriter, usando
# CSV_FIELDS como cabeçalho: a lista canônica inclui "demo_mode" como última
# coluna, então o arquivo de teste tem exatamente o schema real, sem coluna
# repetida. Mesma técnica de _write_old_format_csv() (acima), que subtrai
# as colunas filter_mode e demo_mode do cabeçalho.


def _write_csv_with_demo_mode_column(path, demo_mode: str, tam_index: float = 200.0) -> None:
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
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerow(row)


class TestLoadSessionCsvReadsDemoModeColumn:
    def test_demo_mode_true_is_read_as_bool(self, tmp_path):
        """load_session_csv() devolve a chave "demo_mode" no dicionário,
        lida da coluna do CSV como bool."""
        csv_path = tmp_path / "evento_session.csv"
        _write_csv_with_demo_mode_column(csv_path, demo_mode="True")

        data = load_session_csv(str(csv_path))

        assert data["demo_mode"] is True

    def test_demo_mode_false_is_read_as_bool(self, tmp_path):
        """O valor "False" da coluna demo_mode é lido como o bool False."""
        csv_path = tmp_path / "clinical_session.csv"
        _write_csv_with_demo_mode_column(csv_path, demo_mode="False")

        data = load_session_csv(str(csv_path))

        assert data["demo_mode"] is False

    def test_old_csv_without_the_column_reads_as_false_not_assumed(self, tmp_path):
        """Diferente de filter_mode_assumed: não existe um
        "demo_mode_assumed", porque não há ambiguidade a marcar — um CSV sem
        a coluna demo_mode é, por definição, uma sessão clínica. False é
        fato, não suposição."""
        csv_path = tmp_path / "old_session.csv"
        _write_old_format_csv(csv_path)  # sem as colunas filter_mode e demo_mode

        with open(csv_path, newline="", encoding="utf-8") as f:
            assert "demo_mode" not in csv.DictReader(f).fieldnames

        data = load_session_csv(str(csv_path))

        assert data["demo_mode"] is False
        assert "demo_mode_assumed" not in data


class TestFooterDemoModeWarning:
    """
    build_demo_mode_warning_text() (session_report.py) monta o aviso de
    demonstração do rodapé, no mesmo espírito de build_footer_method_text():
    função pura, sem renderizar nem ler PDF. Estes testes fixam o contrato:
    texto de alerta quando demo_mode=True, string vazia quando False.
    """

    def test_warning_text_exists_and_mentions_demonstration_when_true(self):
        """O aviso de demonstração existe e menciona demonstração ou evento."""
        from session_report import build_demo_mode_warning_text

        texto = build_demo_mode_warning_text(demo_mode=True)

        assert texto.strip() != ""
        assert "demonstra" in texto.lower() or "evento" in texto.lower()

    def test_warning_text_is_empty_when_not_demo(self):
        """Uma sessão clínica normal não deve ganhar nenhuma linha extra no
        rodapé — o aviso é exclusivo do perfil Evento."""
        from session_report import build_demo_mode_warning_text

        assert build_demo_mode_warning_text(demo_mode=False) == ""


# =============================================================================
# Unidades ° e °/s no PDF e sanitização do texto
# =============================================================================
#
# O relatório deve imprimir "54°" e "75°/s", e não "54 deg" e "75 deg/s". O
# código-fonte escreve "°" em todas as tabelas, na legenda e na interpretação
# clínica, e todo texto do PDF passa por sanitize_for_pdf(), via
# _cell/_multi_cell. O sanitizador não pode converter "°" em " deg".
#
# POR QUE "°" NÃO PRECISA DE CONVERSÃO: as fontes core do FPDF2 (Helvetica,
# usada em todo o relatório) codificam em Latin-1, e "°" é U+00B0, dentro do
# Latin-1. Não é preciso registrar fonte TTF nem mudar encoding. Já "—", "…",
# "≤", "≥" e as aspas curvas estão FORA do Latin-1 e quebrariam a geração com
# FPDFUnicodeEncodingException — por isso essas conversões continuam sendo
# necessárias, e os testes abaixo as protegem explicitamente.
#
# O aviso do perfil Evento começa com "⚠" (U+26A0), também fora do Latin-1;
# o sanitizador precisa convertê-lo para que o relatório de uma sessão do
# perfil Evento seja gerado. Os testes da classe TestEventProfileReportGenerates
# fixam esse contrato.
#
# Todos os CSVs e PDFs vivem em tmp_path. Os helpers de CSV são os que já
# existem neste arquivo (_write_new_format_csv e _write_csv_with_demo_mode_
# column) — nada de CSV_FIELDS nem de dados sintéticos duplicados aqui.


def _extract_pdf_text(pdf_path: str) -> str:
    """
    Extrai o texto de um PDF usando apenas a biblioteca padrão.

    Não há biblioteca de leitura de PDF no projeto (pypdf, pdfminer e fitz
    estão todos ausentes), e acrescentar uma dependência só para conferir
    duas unidades seria caro demais. O formato permite ler o texto sem isso:
    os streams são comprimidos com zlib e os textos aparecem como literais
    entre parênteses dentro dos operadores de desenho.

    Só os streams de TEXTO são lidos. Os gráficos Matplotlib embutidos também
    são streams comprimidos, e seus bytes de imagem — megabytes de pixels —
    contêm qualquer sequência de três letras por acaso, inclusive "deg". Ler
    tudo faria a asserção "não contém deg" falhar por ruído de imagem em vez
    de por unidade errada, então streams sem os operadores BT/Tj são
    descartados.

    O texto é decodificado como Latin-1 porque é exatamente assim que o FPDF2
    grava com as fontes core: "°" chega ao arquivo como o byte 0xB0. As
    sequências de escape do PDF (\\( e \\)) não são desfeitas — nenhuma
    asserção daqui depende disso.
    """
    with open(pdf_path, "rb") as f:
        raw = f.read()

    partes = []
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.S):
        try:
            conteudo = zlib.decompress(match.group(1))
        except zlib.error:
            continue  # stream não comprimido ou com filtro diferente
        if b"BT" not in conteudo or b"Tj" not in conteudo:
            continue  # stream de imagem, não de texto
        for literal in re.findall(rb"\((?:\\.|[^\\()])*\)", conteudo):
            partes.append(literal[1:-1])

    return b"".join(partes).decode("latin-1")


class TestDegreeSymbolSurvivesSanitization:
    """
    O contrato mais direto: o símbolo de grau precisa chegar ao PDF
    como "°", não como " deg". Testado na função pura, que é o único ponto
    onde a conversão acontece.
    """

    def test_degree_symbol_is_preserved(self):
        """1. "54°" não pode virar "54 deg"."""
        from session_report import sanitize_for_pdf

        assert sanitize_for_pdf("54°") == "54°"

    def test_degrees_per_second_is_preserved(self):
        """2. "75°/s" não pode virar "75 deg/s"."""
        from session_report import sanitize_for_pdf

        assert sanitize_for_pdf("75°/s") == "75°/s"


class TestUnsupportedCharactersAreConverted:
    """
    Proteção contra o excesso de zelo na direção oposta: remover a entrada
    do grau não pode virar "remover o sanitizador". Estes caracteres estão
    fora do Latin-1 e, sem conversão, quebram a geração inteira do relatório
    com FPDFUnicodeEncodingException.
    """

    @pytest.mark.parametrize(
        "original, esperado",
        [
            ("a — b", "a - b"),      # travessão (U+2014)
            ("a – b", "a - b"),      # traço en (U+2013)
            ("a…", "a..."),          # reticências (U+2026)
            ("≤ 30", "<= 30"),       # menor ou igual (U+2264)
            ("≥ 30", ">= 30"),       # maior ou igual (U+2265)
            ("'x'", "'x'"),          # aspas simples curvas (U+2018/U+2019)
            ("“x”", '"x"'),          # aspas duplas curvas (U+201C/U+201D)
        ],
    )
    def test_character_outside_latin1_is_converted(self, original, esperado):
        """3. Cada caractere fora do Latin-1 é convertido para o equivalente
        ASCII esperado."""
        from session_report import sanitize_for_pdf

        assert sanitize_for_pdf(original) == esperado

    @pytest.mark.parametrize(
        "original",
        ["a — b", "a – b", "a…", "≤ 30", "≥ 30", "'x'", "“x”", "54°", "75°/s"],
    )
    def test_sanitized_output_is_encodable_in_latin1(self, original):
        """
        4. O que sai do sanitizador precisa ser codificável em Latin-1.

        Esta é a condição real que o FPDF2 impõe com fontes core, e é o que
        um teste sobre o dicionário de substituições estaria tentando
        aproximar. O dicionário é uma variável local de sanitize_for_pdf(),
        não um atributo de módulo, então não há como percorrê-lo de fora —
        mas verificar a SAÍDA é mais forte de qualquer forma: é o texto que
        chega ao PDF, não a tabela que o produziu.
        """
        from session_report import sanitize_for_pdf

        sanitize_for_pdf(original).encode("latin-1")  # não deve levantar


class TestGeneratedPdfUsesDegreeSymbol:
    def test_pdf_text_has_degree_symbol_and_no_deg_abbreviation(self, tmp_path):
        """
        5. Verificação ponta a ponta no arquivo gerado.

        Os testes de sanitize_for_pdf() acima provam a função; este prova o
        trajeto inteiro até o PDF em disco — tabela principal, tabela
        suplementar, legenda e interpretação clínica, todas passando pelo
        mesmo sanitizador.
        """
        from session_report import generate_pdf_report

        csv_path = tmp_path / "sessao_unidades.csv"
        _write_new_format_csv(csv_path, filter_mode="EMA_KALMAN", tam_index=200.0)

        output_path = generate_pdf_report(
            str(csv_path), patient_name="Paciente Teste", side="Direita"
        )
        texto = _extract_pdf_text(output_path)

        assert "°" in texto, "o relatório deve imprimir o símbolo de grau"
        assert "°/s" in texto, "as velocidades angulares devem usar °/s"
        assert "deg" not in texto, (
            "nenhuma unidade pode aparecer abreviada como 'deg' — "
            f"encontradas {texto.count('deg')} ocorrências"
        )


class TestEventProfileReportGenerates:
    """
    Guarda contra uma falha de geração: build_demo_mode_warning_text() começa
    com "⚠" (U+26A0), fora do Latin-1, e o sanitizador precisa convertê-lo.
    Sem isso, qualquer sessão do perfil Evento falharia ao gerar o relatório.

    O teste ponta a ponta com _write_new_format_csv() não cobre esse caso,
    porque não escreve demo_mode=True, e os testes de demonstração verificam
    o aviso como string pura, sem passar pelo FPDF. Por isso esta classe gera
    o relatório de uma sessão Evento.
    """

    def test_demo_warning_text_is_encodable_in_latin1(self):
        """
        6a. Localiza o problema na função, antes do PDF.

        Separado do teste ponta a ponta porque um relatório que falha inteiro
        não diz QUAL caractere o derrubou; este diz.
        """
        from session_report import build_demo_mode_warning_text, sanitize_for_pdf

        texto = sanitize_for_pdf(build_demo_mode_warning_text(demo_mode=True))

        texto.encode("latin-1")  # não deve levantar

    def test_generate_pdf_report_succeeds_for_an_event_profile_session(self, tmp_path):
        """
        6b. O relatório de uma sessão Evento precisa ser gerado como o de
        qualquer outra: sem exceção, com arquivo real e não vazio.
        """
        from session_report import generate_pdf_report

        csv_path = tmp_path / "sessao_evento.csv"
        _write_csv_with_demo_mode_column(csv_path, demo_mode="True")

        output_path = generate_pdf_report(
            str(csv_path), patient_name="Paciente Teste", side="Direita"
        )

        assert os.path.isfile(output_path)
        assert os.path.getsize(output_path) > 0


# =============================================================================
# API de células do FPDF2: ausência de depreciação e estrutura do relatório
# =============================================================================
#
# O parâmetro ln= de cell()/multi_cell() está obsoleto no FPDF2 desde a versão
# 2.5.2. O equivalente atual de ln=True é o par new_x=XPos.LMARGIN,
# new_y=YPos.NEXT, que produz o mesmo avanço de linha: cursor para a margem
# esquerda, uma linha abaixo. Enquanto o fpdf2 ainda aceita ln=, cada chamada
# apenas emite um DeprecationWarning; quando o suporte for removido, a geração
# do relatório passa a falhar de uma vez.
#
# Um aviso de depreciação some da vista assim que alguém se acostuma a ele.
# Por isso a ausência dele é contrato verificado aqui: reintroduzir ln= em
# qualquer chamada quebra a suíte na hora, em vez de acrescentar em silêncio
# mais um item a uma contagem que ninguém lê.
#
# Não confundir com o MÉTODO pdf.ln(...), usado dezenas de vezes em
# session_report.py: ele não é obsoleto e é o que controla todo o espaçamento
# vertical do documento. Só o PARÂMETRO ln= foi descontinuado. O segundo teste
# desta seção protege exatamente essa confusão — mexer no método por engano
# desloca o conteúdo e altera a paginação, que é o que ele verifica.


def _pdf_page_footers(texto: str) -> list:
    """
    Devolve os rodapés "Página N/T" encontrados no texto extraído.

    Contar páginas sem biblioteca de PDF é possível porque _ReportPDF.footer()
    escreve esse rodapé em toda página. O número de rodapés é o número de
    páginas, e cada um traz o total — os dois têm de bater.
    """
    return re.findall(r"P.gina *(\d+)/(\d+)", texto)


class TestNoFpdfDeprecationWarnings:
    def test_report_generation_emits_no_deprecated_ln_warning(self, tmp_path):
        """
        Nenhum DeprecationWarning sobre o parâmetro ln durante a geração.

        O filtro é específico: só avisos que citam "ln" ou "new_x". Um teste
        que falhasse em QUALQUER DeprecationWarning ficaria refém de
        depreciações de matplotlib, numpy ou do próprio Python — ruído de
        terceiros que não temos como corrigir aqui e que tornaria este teste
        instável a cada atualização de ambiente.
        """
        from session_report import generate_pdf_report

        csv_path = tmp_path / "sessao_sem_avisos.csv"
        _write_new_format_csv(csv_path, filter_mode="EMA_KALMAN", tam_index=200.0)

        with warnings.catch_warnings(record=True) as capturados:
            warnings.simplefilter("always")
            output_path = generate_pdf_report(
                str(csv_path), patient_name="Paciente Teste", side="Direita"
            )

        relevantes = [
            w
            for w in capturados
            if issubclass(w.category, DeprecationWarning)
            and ("ln" in str(w.message) or "new_x" in str(w.message))
        ]

        assert os.path.isfile(output_path)
        assert os.path.getsize(output_path) > 0
        assert not relevantes, (
            f"{len(relevantes)} aviso(s) de depreciação do FPDF2 durante a "
            f"geração; primeiro: {relevantes[0].message}"
        )


class TestReportStructureSurvivesMigration:
    def test_report_keeps_its_essential_sections_and_pagination(self, tmp_path):
        """
        As seções e a paginação do relatório não mudam.

        Não compara com um PDF de referência: um relatório binário guardado
        no repositório ninguém saberia regenerar, e ele falharia por qualquer
        diferença irrelevante (data de geração, ordem interna de objetos). O
        que precisa continuar verdadeiro são as seções do documento e a
        paginação — qualquer erro no posicionamento do cursor entre células
        desloca o conteúdo e derruba justamente isso.
        """
        from session_report import generate_pdf_report

        csv_path = tmp_path / "sessao_estrutura.csv"
        _write_new_format_csv(csv_path, filter_mode="EMA_KALMAN", tam_index=200.0)

        output_path = generate_pdf_report(
            str(csv_path), patient_name="Paciente Teste", side="Direita"
        )
        texto = _extract_pdf_text(output_path)

        assert texto.strip(), "o PDF não pode sair sem nenhum texto"

        for trecho in (
            "Tabela Principal",
            "Avaliação Funcional",
            "Interpretação Clínica",
            "Tabela Suplementar",
            "Legenda Clínica",
        ):
            assert trecho in texto, f"seção ausente do relatório: {trecho!r}"

        rodapes = _pdf_page_footers(texto)
        assert len(rodapes) >= 2, (
            f"relatório com paginação inesperada: {len(rodapes)} página(s)"
        )
        total_declarado = {total for _, total in rodapes}
        assert total_declarado == {str(len(rodapes))}, (
            "o total de páginas do rodapé não bate com o número de páginas: "
            f"rodapés={rodapes}"
        )
