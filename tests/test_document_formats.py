"""Real document round-trips and hostile upload cases, without office engines."""
import csv
from contextlib import nullcontext
from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO, StringIO
import shutil
import subprocess
from zipfile import ZIP_DEFLATED, ZipFile

from docx import Document
from openpyxl import Workbook, load_workbook
import pytest

from app.document_formats import MAX_CELL_CHARS, MAX_EXPORT_ROWS, parse_table, render_document


COLUMNS = [("code", "Código"), ("description", "Descrição"), ("quantity", "Quantidade")]
ROWS = [{"code": "MAT-01", "description": "Aço de São João <ensaio>",
         "quantity": Decimal("9007199254740993.001"), "password_hash": "DO-NOT-EXPORT"}]
METADATA = {"generated_at": datetime(2026, 11, 17, 12, 34, tzinfo=timezone.utc),
            "filters": {"Obra": "São João"}, "totals": {"Quantidade": "9007199254740993.001"}}


def workbook_data(rows, configure=None):
    book = Workbook()
    for row in rows:
        book.active.append(row)
    if configure:
        configure(book)
    output = BytesIO()
    book.save(output)
    return output.getvalue()


def rewrite_zip(data, replacements=None, additions=None):
    output = BytesIO()
    replacements = replacements or {}
    with ZipFile(BytesIO(data)) as original, ZipFile(output, "w", ZIP_DEFLATED) as changed:
        for entry in original.infolist():
            value = original.read(entry.filename)
            if entry.filename in replacements:
                value = replacements[entry.filename](value)
            changed.writestr(entry.filename, value)
        for name, value in (additions or {}).items():
            changed.writestr(name, value)
    return output.getvalue()


def test_csv_report_has_portuguese_metadata_exact_decimals_and_only_selected_fields():
    data, media, extension = render_document("csv", "Estoque — São João", COLUMNS, ROWS, METADATA)
    assert data.startswith(b"\xef\xbb\xbf")
    assert media == "text/csv; charset=utf-8" and extension == "csv"
    records = list(csv.reader(StringIO(data.decode("utf-8-sig")), delimiter=";"))
    assert ["Estoque — São João"] in records
    assert ["Gerado em", "17/11/2026 12:34:00"] in records
    assert ["Filtro — Obra", "São João"] in records
    assert ["MAT-01", "Aço de São João <ensaio>", "9007199254740993,001"] in records
    assert ["Quantidade", "9007199254740993,001"] in records
    assert b"DO-NOT-EXPORT" not in data


@pytest.mark.parametrize("format,limit", [("pdf", 2000), ("docx", 3000), ("xlsx", 10000), ("csv", 50000)])
def test_export_row_limits_reject_before_reading_cells_or_building_documents(format, limit, monkeypatch):
    assert MAX_EXPORT_ROWS[format] == limit

    def unexpected_render(*args, **kwargs):
        pytest.fail("Document construction must not start above the row limit")

    for name in ("_render_pdf", "_render_docx", "_render_xlsx"):
        monkeypatch.setattr("app.document_formats." + name, unexpected_render)
    # Invalid row objects also prove the guard runs before table conversion.
    with pytest.raises(ValueError, match=rf"{format.upper()}.*{limit}.*Refine os filtros"):
        render_document(format, "Relatório", COLUMNS, [object()] * (limit + 1), {})


@pytest.mark.parametrize("value", ["=1+1", "+1+1", "-1+1", "@SUM(A1)", "\t=1+1", "\r=1+1", "\n=1+1", "   =1+1",
                                 "\u00a0=1+1", "\ufeff =1+1", "\u200b=1+1", "＝1+1", "＠SUM(A1)"])
def test_csv_neutralizes_formula_injection_and_xlsx_keeps_passive_text(value):
    csv_data, _, _ = render_document("csv", "Modelo", [("description", "descricao")],
                                     [{"description": value}], {"template": True})
    parsed_csv = list(csv.reader(StringIO(csv_data.decode("utf-8-sig")), delimiter=";"))
    assert parsed_csv[1] == ["'" + value]
    data, _, _ = render_document("xlsx", "Modelo", [("description", "descricao")],
                                 [{"description": value}], {"template": True})
    book = load_workbook(BytesIO(data), data_only=False)
    assert book.active["A2"].value == value
    assert book.active["A2"].data_type == "s"
    assert book.active["A2"].quotePrefix
    assert book.active["A2"].hyperlink is None
    with ZipFile(BytesIO(data)) as archive:
        assert b"<f>" not in archive.read("xl/worksheets/sheet1.xml")


@pytest.mark.parametrize("format", ["csv", "xlsx"])
def test_empty_import_templates_round_trip_with_first_row_headers(format):
    data, _, _ = render_document(format, "Modelo", [("codigo", "codigo"), ("descricao", "descricao")],
                                 [], {"template": True})
    assert parse_table(data, "modelo." + format) == (["codigo", "descricao"], [])


def test_xlsx_report_metadata_table_repeat_header_and_exact_text():
    data, media, extension = render_document("xlsx", "Estoque — São João", COLUMNS, ROWS, METADATA)
    assert "spreadsheetml" in media and extension == "xlsx"
    book = load_workbook(BytesIO(data), data_only=False)
    records = list(book.active.values)
    assert ("Código", "Descrição", "Quantidade") in records
    assert ("MAT-01", "Aço de São João <ensaio>", "9007199254740993,001") in records
    assert all(cell.data_type != "f" for row in book.active for cell in row)
    assert all(cell.hyperlink is None for row in book.active for cell in row)
    assert book.active.print_title_rows
    assert book.active.freeze_panes


def test_docx_semantics_unicode_escaping_table_and_repeated_header():
    data, media, extension = render_document("docx", "Estoque — São João", COLUMNS, ROWS, METADATA)
    assert extension == "docx" and "wordprocessingml" in media
    document = Document(BytesIO(data))
    paragraphs = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "Estoque — São João" in paragraphs
    assert "17/11/2026 12:34:00" in paragraphs
    assert "Filtro — Obra: São João" in paragraphs
    assert "Totais" in paragraphs and "9007199254740993,001" in paragraphs
    assert [cell.text for cell in document.tables[0].rows[1].cells] == [
        "MAT-01", "Aço de São João <ensaio>", "9007199254740993,001"]
    with ZipFile(BytesIO(data)) as archive:
        assert b"w:tblHeader" in archive.read("word/document.xml")
        assert b"DO-NOT-EXPORT" not in archive.read("word/document.xml")
        assert b"TargetMode=\"External\"" not in archive.read("word/_rels/document.xml.rels")


def test_pdf_semantic_extraction_page_breaks_unicode_and_repeated_table_header(tmp_path):
    extractor = shutil.which("pdftotext")
    if not extractor:
        pytest.skip("pdftotext is available in the document validation environment")
    rows = [dict(ROWS[0], code=f"MAT-{number:04d}") for number in range(160)]
    data, media, extension = render_document("pdf", "Estoque — São João", COLUMNS, rows, METADATA)
    assert data.startswith(b"%PDF-") and media == "application/pdf" and extension == "pdf"
    path = tmp_path / "report.pdf"
    path.write_bytes(data)
    extracted = subprocess.run([extractor, "-layout", str(path), "-"], check=True,
                               capture_output=True, text=True, timeout=20).stdout
    assert "Estoque — São João" in extracted and "São João" in extracted
    assert "Aço de São João <ensaio>" in extracted
    assert "9007199254740993,001" in extracted
    assert "MAT-0000" in extracted and "MAT-0159" in extracted
    assert extracted.count("Código") >= 2
    assert "Página 2" in extracted and "Totais" in extracted
    assert "DO-NOT-EXPORT" not in extracted


@pytest.mark.parametrize("key", ["password_hash", "senha", "access_token", "face_embedding", "biometria", "username",
                               "passwordHash", "accessToken", "faceEmbedding"])
def test_sensitive_fields_are_blocked_in_columns_and_metadata(key):
    with pytest.raises(ValueError, match="sensíveis"):
        render_document("csv", "Exportação", [(key, "Campo")], [{key: "SECRET"}], {})
    with pytest.raises(ValueError, match="sensíveis"):
        render_document("csv", "Exportação", COLUMNS, [], {"filters": {key: "SECRET"}})


def test_csv_parses_bom_semicolon_quoted_newline_and_exact_decimal_text():
    data = '\ufeffcodigo;descricao;quantidade\r\nMAT-01;"Aço; com\nquebra";123456789012345678,001\r\n\r\n'.encode()
    assert parse_table(data, "modelo.csv") == (["codigo", "descricao", "quantidade"], [
        {"codigo": "MAT-01", "descricao": "Aço; com\nquebra", "quantidade": "123456789012345678,001"}])
    assert parse_table(b"codigo,descricao\nA,Parafuso\n", "modelo.CSV")[1][0]["codigo"] == "A"


def test_parser_preserves_physical_csv_and_xlsx_row_numbers_for_audit():
    _, rows = parse_table(b'codigo;descricao\n\nA;"first\nsecond"\n\nB;last\n', "model.csv")
    assert rows == [{"codigo": "A", "descricao": "first\nsecond"}, {"codigo": "B", "descricao": "last"}]
    assert [row.source_row for row in rows] == [3, 6]
    data = workbook_data([["codigo"], [], [], ["A"], [], ["B"]])
    assert [row.source_row for row in parse_table(data, "model.xlsx")[1]] == [4, 6]


def test_xlsx_parses_inline_text_shared_text_sparse_cells_and_raw_exact_decimals():
    data = workbook_data([["codigo", "descricao", "quantidade"], ["001.001", "Aço", 1], ["MAT-2", None, 0]])
    data = rewrite_zip(data, {"xl/worksheets/sheet1.xml": lambda xml: xml.replace(
        b'<c r="C2" t="n"><v>1</v></c>', b'<c r="C2" t="n"><v>9007199254740993.001</v></c>')})
    headers, rows = parse_table(data, "modelo.xlsx")
    assert headers == ["codigo", "descricao", "quantidade"]
    assert rows == [{"codigo": "001.001", "descricao": "Aço", "quantidade": "9007199254740993.001"},
                    {"codigo": "MAT-2", "descricao": "", "quantidade": "0"}]
    shared = b'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>Texto compartilhado</t></si></sst>'
    data = rewrite_zip(data, {"xl/worksheets/sheet1.xml": lambda xml: xml.replace(
        b'<c r="B2" t="inlineStr"><is><t>A&#231;o</t></is></c>', b'<c r="B2" t="s"><v>0</v></c>')},
        {"xl/sharedStrings.xml": shared})
    assert parse_table(data, "modelo.xlsx")[1][0]["descricao"] == "Texto compartilhado"


@pytest.mark.parametrize("data,filename,match", [
    (b"", "empty.csv", "não vazio"),
    (b"codigo;Codigo\nA;B", "repeat.csv", "duplicados"),
    (b"codigo;\nA;B", "empty-header.csv", "vazios"),
    (b"codigo\nA;B", "excess.csv", "mais células"),
    (b'codigo;descricao\nA;"unterminated', "invalid.csv", "inválido"),
    (b"codigo\n\xff", "latin.csv", "UTF-8"),
    (b"codigo\x00", "binary.csv", "CSV UTF-8"),
    (b"%PDF-1.4", "document.csv", "CSV UTF-8"),
    (b"PK\x03\x04", "wrong.csv", "CSV UTF-8"),
    (b"codigo\nA", "wrong.xlsx", "XLSX"),
    (b"anything", "old.xls", "somente"),
    (b"anything", "report.pdf", "somente"),
    (b"anything", "report.docx", "somente"),
])
def test_parser_rejects_invalid_content_and_extensions(data, filename, match):
    with pytest.raises(ValueError, match=match):
        parse_table(data, filename)


@pytest.mark.parametrize("format", ["csv", "xlsx"])
def test_import_size_rows_columns_and_cell_limits(format):
    data = b"codigo\nA\nB" if format == "csv" else workbook_data([["codigo"], ["A"], ["B"]])
    with pytest.raises(ValueError, match="tamanho"):
        parse_table(data, "model." + format, max_bytes=1)
    with pytest.raises(ValueError, match="linhas"):
        parse_table(data, "model." + format, max_rows=1)
    excessive = (";".join("col" + str(i) for i in range(101))).encode() if format == "csv" else workbook_data([list(range(101))])
    with pytest.raises(ValueError, match="colunas"):
        parse_table(excessive, "model." + format)
    if format == "csv":
        with pytest.raises(ValueError, match="caracteres"):
            parse_table(("codigo\n" + "X" * (MAX_CELL_CHARS + 1)).encode(), "model.csv")


@pytest.mark.parametrize("configure", [
    lambda book: setattr(book.active["A2"], "value", '=HYPERLINK("https://example.invalid/SECRET")'),
    lambda book: setattr(book.active["A2"], "hyperlink", "https://example.invalid/SECRET"),
    lambda book: book.create_sheet("Hidden").append(["=1+1"]),
])
def test_xlsx_rejects_formulas_or_links_on_any_sheet_without_exposing_content(configure):
    data = workbook_data([["codigo"], ["MAT-01"]], configure)
    with pytest.raises(ValueError) as error:
        parse_table(data, "model.xlsx")
    assert "SECRET" not in str(error.value)
    assert any(word in str(error.value).lower() for word in ("fórmula", "links", "externas"))


def test_xlsx_rejects_duplicate_cells_and_headers():
    duplicate_header = workbook_data([["codigo", "CODIGO"], ["A", "B"]])
    with pytest.raises(ValueError, match="duplicados"):
        parse_table(duplicate_header, "model.xlsx")
    data = workbook_data([["codigo"], ["A"]])
    duplicate_cell = rewrite_zip(data, {"xl/worksheets/sheet1.xml": lambda xml: xml.replace(
        b'<row r="2">', b'<row r="2"><c r="A2" t="n"><v>1</v></c>')})
    with pytest.raises(ValueError, match="duplicadas"):
        parse_table(duplicate_cell, "model.xlsx")


def test_xlsx_rejects_formula_when_worksheet_has_unusual_part_extension():
    original = workbook_data([["codigo"], ["=1+1"]])
    output = BytesIO()
    with ZipFile(BytesIO(original)) as source, ZipFile(output, "w", ZIP_DEFLATED) as changed:
        for item in source.infolist():
            value = source.read(item.filename)
            name = item.filename
            if name == "xl/worksheets/sheet1.xml":
                name = "xl/worksheets/sheet1.XML"
            if name == "xl/_rels/workbook.xml.rels":
                value = value.replace(b"sheet1.xml", b"sheet1.XML")
            changed.writestr(name, value)
    with pytest.raises(ValueError, match="Fórmulas"):
        parse_table(output.getvalue(), "model.xlsx")


def test_xlsx_rejects_macro_objects_entities_and_non_xlsx_zip():
    data = workbook_data([["codigo"], ["A"]])
    for addition in ({"xl/vbaProject.bin": b"macro"}, {"xl/embeddings/object.bin": b"ole"}):
        with pytest.raises(ValueError, match="Macros"):
            parse_table(rewrite_zip(data, additions=addition), "model.xlsx")
    entity = rewrite_zip(data, {"xl/worksheets/sheet1.xml": lambda xml:
        b'<!DOCTYPE worksheet [<!ENTITY private SYSTEM "file:///etc/passwd">]>' + xml})
    with pytest.raises(ValueError, match="inválido"):
        parse_table(entity, "model.xlsx")
    macro_type = rewrite_zip(data, {"[Content_Types].xml": lambda xml: xml.replace(
        b"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
        b"application/vnd.ms-excel.sheet.macroEnabled.main+xml")})
    with pytest.raises(ValueError, match="Macros"):
        parse_table(macro_type, "model.xlsx")
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("random.txt", "not an Excel workbook")
    with pytest.raises(ValueError, match="XLSX"):
        parse_table(output.getvalue(), "model.xlsx")


def test_xlsx_rejects_zip_bombs_many_entries_traversal_and_duplicate_members():
    original = workbook_data([["codigo"], ["A"]])
    additions = [{"bomb.xml": b"0" * (9 * 1024 * 1024)},
                 {"ratio-bomb.xml": b"0" * (1024 * 1024)},
                 {f"expanded-bomb-{i}.xml": b"0" * (7 * 1024 * 1024) for i in range(3)},
                 {f"entry-{i}.txt": b"x" for i in range(201)},
                 {"../outside.xml": b"x"}, {"xl/workbook.xml": b"duplicate"}]
    for addition in additions:
        with pytest.warns(UserWarning) if "xl/workbook.xml" in addition else nullcontext():
            data = rewrite_zip(original, additions=addition)
        with pytest.raises(ValueError):
            parse_table(data, "model.xlsx")


def test_errors_do_not_include_uploaded_values():
    with pytest.raises(ValueError) as error:
        parse_table(b"codigo\nSECRET-A;SECRET-B", "model.csv")
    assert "SECRET" not in str(error.value)
