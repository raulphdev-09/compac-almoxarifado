"""Bounded, passive spreadsheet imports and explicitly selected report exports.

Importers return text, including the exact decimal representation stored in XLSX.
They never ask an office engine to calculate, follow a link, or open a document.
Only the report columns supplied by the caller are exported; row dictionaries
must already have been selected through the application's authorization layer.
"""
from __future__ import annotations

import csv
from datetime import date, datetime, timezone
from decimal import Decimal
from io import BytesIO, StringIO
from pathlib import Path, PurePosixPath
import re
import unicodedata
from xml.sax.saxutils import escape
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile

from defusedxml import ElementTree as SafeXML
from defusedxml.common import DefusedXmlException


MAX_IMPORT_BYTES = 2 * 1024 * 1024
MAX_IMPORT_COLUMNS = 100
MAX_CELL_CHARS = 32767
MAX_ZIP_ENTRIES = 200
MAX_ZIP_EXPANDED = 20 * 1024 * 1024
MAX_ZIP_MEMBER = 8 * 1024 * 1024
MIME_TYPES = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
MAX_EXPORT_ROWS = {"pdf": 2_000, "docx": 3_000, "xlsx": 10_000, "csv": 50_000}
_SHEET = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_CELL_REFERENCE = re.compile(r"([A-Z]{1,3})([1-9][0-9]{0,6})\Z")
_NUMERIC = re.compile(r"[-+]?\d+\.\d+\Z")
_FORBIDDEN_FIELDS = {
    "password", "senha", "token", "secret", "segredo", "cookie", "session",
    "biometria", "biometric", "biometrics", "embedding", "descriptor",
    "face", "facial", "photo", "foto", "image", "username", "usuario",
    "usuarios", "user", "users", "email", "salt", "credential", "credentials",
}


class TableRow(dict):
    """Ordinary row mapping with its physical upload row for validation/audit."""

    def __init__(self, values=(), *, source_row: int):
        super().__init__(values)
        self.source_row = source_row


class _RowValues(list):
    def __init__(self, values, *, source_row: int):
        super().__init__(values)
        self.source_row = source_row


def _field_is_sensitive(key: object) -> bool:
    normalized = unicodedata.normalize("NFKD", str(key)).encode("ascii", "ignore").decode()
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", normalized).lower()
    return bool(set(re.split(r"[^a-z0-9]+", normalized)) & _FORBIDDEN_FIELDS)


def _text(value: object, *, key: str = "", template: bool = False) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        result = "Sim" if value else "Não"
    elif isinstance(value, datetime):
        result = value.strftime("%d/%m/%Y %H:%M:%S")
    elif isinstance(value, date):
        result = value.strftime("%d/%m/%Y")
    elif isinstance(value, Decimal):
        result = format(value, "f")
    elif isinstance(value, (dict, list, tuple, bytes)):
        raise ValueError("O relatório contém um valor incompatível com a exportação.")
    else:
        result = str(value)
    # Keep identifiers such as material codes unchanged and never round a decimal.
    if not template and _NUMERIC.fullmatch(result) and key not in {"code", "codigo", "id", "document", "documento"}:
        result = result.replace(".", ",")
    result = "".join(char for char in result if char in "\t\n\r" or ord(char) >= 32)
    if len(result) > MAX_CELL_CHARS:
        raise ValueError("Uma célula excede o limite de caracteres da exportação.")
    return result


def _spreadsheet_risk(value: str) -> bool:
    # Excel may discard leading whitespace or normalize full-width characters.
    # Include invisible format characters so they cannot hide a formula prefix.
    candidate = unicodedata.normalize("NFKC", value)
    while candidate:
        stripped = candidate.lstrip().lstrip("\ufeff\u200b\u200c\u200d")
        if stripped == candidate:
            break
        candidate = stripped
    return value.startswith(("\t", "\r", "\n")) or candidate.startswith(("=", "+", "-", "@"))


def _csv_cell(value: str) -> str:
    return "'" + value if _spreadsheet_risk(value) else value


def _metadata_lines(metadata: dict) -> list[list[str]]:
    generated = metadata.get("generated_at") or datetime.now(timezone.utc)
    if isinstance(generated, str):
        try:
            generated = datetime.fromisoformat(generated.replace("Z", "+00:00"))
        except ValueError:
            pass
    lines = [["Gerado em", _text(generated)]]
    for key, value in (metadata.get("filters") or {}).items():
        if _field_is_sensitive(key):
            raise ValueError("Campos sensíveis não são permitidos em relatórios.")
        if value is not None and value != "":
            lines.append(["Filtro — " + _text(key), _text(value, key=str(key))])
    return lines


def render_document(format: str, title: str, columns: list[tuple[str, str]],
                    rows: list[dict], metadata: dict | None = None) -> tuple[bytes, str, str]:
    """Render passive CSV/XLSX/PDF/DOCX. ``template=True`` keeps header first.

    Metadata accepts ``generated_at``, ``filters`` and ``totals`` dictionaries.
    A template is intentionally header-only when ``rows=[]`` is supplied.
    Numeric values are rendered as text without binary floating point coercion.
    """
    format = str(format).lower().lstrip(".")
    if format not in MIME_TYPES:
        raise ValueError("Formato inválido. Use CSV, XLSX, PDF ou DOCX.")
    if len(rows) > MAX_EXPORT_ROWS[format]:
        raise ValueError(
            f"O formato {format.upper()} permite no máximo {MAX_EXPORT_ROWS[format]} linhas. "
            "Refine os filtros e exporte novamente."
        )
    if not columns or len(columns) > MAX_IMPORT_COLUMNS:
        raise ValueError("A exportação deve conter entre 1 e 100 colunas.")
    if any(_field_is_sensitive(key) or _field_is_sensitive(label) for key, label in columns):
        raise ValueError("Campos sensíveis não são permitidos em relatórios.")
    metadata = metadata or {}
    template = metadata.get("template") is True
    title = _text(title)
    headers = [_text(label, template=True) for _, label in columns]
    table_rows = [[_text(row.get(key), key=key, template=template) for key, _ in columns] for row in rows]
    information = [] if template else _metadata_lines(metadata)
    totals = []
    if not template:
        for key, value in (metadata.get("totals") or {}).items():
            if _field_is_sensitive(key):
                raise ValueError("Campos sensíveis não são permitidos em relatórios.")
            totals.append([_text(key), _text(value, key=str(key))])
    if format == "csv":
        output = StringIO(newline="")
        writer = csv.writer(output, delimiter=";", lineterminator="\r\n")
        if not template:
            for row in [[title], *information, []]:
                writer.writerow([_csv_cell(cell) for cell in row])
        for row in [headers, *table_rows]:
            writer.writerow([_csv_cell(cell) for cell in row])
        if totals:
            writer.writerow([])
            writer.writerow(["Totais"])
            for row in totals:
                writer.writerow([_csv_cell(cell) for cell in row])
        data = output.getvalue().encode("utf-8-sig")
    elif format == "xlsx":
        data = _render_xlsx(title, headers, table_rows, information, totals, template)
    elif format == "pdf":
        data = _render_pdf(title, headers, table_rows, information, totals)
    else:
        data = _render_docx(title, headers, table_rows, information, totals)
    return data, MIME_TYPES[format], format


def _render_xlsx(title, headers, rows, information, totals, template):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    workbook.properties.creator = "COMPAC"
    sheet = workbook.active
    sheet.title = "Modelo" if template else "Relatório"

    def append(values):
        sheet.append(values)
        for cell in sheet[sheet.max_row]:
            # Explicit inline strings prevent Excel from interpreting formulas,
            # URLs, dates or high-precision decimal quantities on opening.
            cell.data_type = "s"
            cell.number_format = "@"
            cell.quotePrefix = bool(cell.value and _spreadsheet_risk(str(cell.value)))
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    if not template:
        append([title])
        sheet.cell(1, 1).font = Font(size=16, bold=True, color="173D3B")
        for line in information:
            append(line)
        append([])
    append(headers)
    header_row = sheet.max_row
    for cell in sheet[header_row]:
        cell.fill = PatternFill("solid", fgColor="173D3B")
        cell.font = Font(bold=True, color="FFFFFF")
    for row in rows:
        append(row)
    if not template:
        sheet.auto_filter.ref = f"A{header_row}:{get_column_letter(len(headers))}{max(header_row, sheet.max_row)}"
    sheet.freeze_panes = f"A{header_row + 1}"
    if totals:
        append([])
        append(["Totais"])
        sheet.cell(sheet.max_row, 1).font = Font(bold=True)
        for row in totals:
            append(row)
    for index, label in enumerate(headers, 1):
        width = max([len(label)] + [min(60, len(row[index - 1])) for row in rows[:200]])
        sheet.column_dimensions[get_column_letter(index)].width = max(14, min(48, width + 3))
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    if not template:
        sheet.print_title_rows = f"{header_row}:{header_row}"
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _render_pdf(title, headers, rows, information, totals):
    import reportlab
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle

    # ReportLab ships these fonts, so accented Portuguese does not depend on
    # operating-system font packages or downloading any resource at runtime.
    fonts = Path(reportlab.__file__).parent / "fonts"
    for name, filename in (("CompacVera", "Vera.ttf"), ("CompacVeraBold", "VeraBd.ttf")):
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(fonts / filename)))
    body = ParagraphStyle("body", fontName="CompacVera", fontSize=8, leading=11, wordWrap="CJK")
    heading = ParagraphStyle("heading", parent=body, fontName="CompacVeraBold", fontSize=17, leading=22, spaceAfter=10)
    header = ParagraphStyle("header", parent=body, fontName="CompacVeraBold", textColor=colors.white)
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=11, spaceAfter=4)

    def paragraph(text, style=body):
        return Paragraph(escape(text).replace("\n", "<br/>"), style)

    output = BytesIO()
    page_size = landscape(A4) if len(headers) > 5 else A4
    document = SimpleDocTemplate(output, pagesize=page_size, leftMargin=28, rightMargin=28,
                                 topMargin=30, bottomMargin=32, title=title, author="COMPAC")
    story = [paragraph(title, heading)]
    story += [paragraph(": ".join(line), small) for line in information]
    story.append(Spacer(1, 10))
    weights = [max(8, min(35, max([len(label)] + [len(row[i]) for row in rows[:50]])))
               for i, label in enumerate(headers)]
    widths = [(page_size[0] - 56) * weight / sum(weights) for weight in weights]
    data = [[paragraph(value, header) for value in headers]]
    data += [[paragraph(value) for value in row] for row in rows]
    table = LongTable(data, colWidths=widths, repeatRows=1, splitByRow=1, splitInRow=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#173D3B")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F1F5F4")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CBD5D1")),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(table)
    if totals:
        story.extend([Spacer(1, 12), paragraph("Totais", heading)])
        story += [paragraph(": ".join(line), small) for line in totals]
    footer = ParagraphStyle("footer", parent=small, alignment=TA_CENTER)

    def page_footer(canvas, doc):
        canvas.saveState()
        label = paragraph(f"COMPAC · Página {doc.page}", footer)
        label.wrap(page_size[0] - 56, 15)
        label.drawOn(canvas, 28, 14)
        canvas.restoreState()

    document.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
    return output.getvalue()


def _render_docx(title, headers, rows, information, totals):
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.oxml import OxmlElement
    from docx.shared import Cm, Pt, RGBColor

    document = Document()
    section = document.sections[0]
    if len(headers) > 5:
        section.orientation = WD_ORIENT.LANDSCAPE
        section.page_width, section.page_height = section.page_height, section.page_width
    section.top_margin = section.bottom_margin = Cm(1.5)
    section.left_margin = section.right_margin = Cm(1.4)
    style = document.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(9)
    style.paragraph_format.space_after = Pt(4)
    document.core_properties.title = title
    document.core_properties.author = "COMPAC"
    document.add_heading(title, 0)
    for line in information:
        document.add_paragraph(": ".join(line))
    table = document.add_table(rows=1, cols=len(headers))
    table.style = "Light Shading Accent 1"
    for cell, label in zip(table.rows[0].cells, headers):
        cell.text = label
        for run in cell.paragraphs[0].runs:
            run.bold = True
            run.font.color.rgb = RGBColor.from_string("173D3B")
    repeat_header = OxmlElement("w:tblHeader")
    table.rows[0]._tr.get_or_add_trPr().append(repeat_header)
    for row in rows:
        for cell, value in zip(table.add_row().cells, row):
            cell.text = value
    if totals:
        document.add_heading("Totais", 1)
        for line in totals:
            document.add_paragraph(": ".join(line))
    section.footer.paragraphs[0].text = "COMPAC — Relatório"
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def parse_table(data: bytes, filename: str, max_rows: int = 500,
                max_bytes: int = MAX_IMPORT_BYTES) -> tuple[list[str], list[dict[str, str]]]:
    """Read a UTF-8 CSV or passive XLSX template with bounded resource use.

    Errors are deliberately generic: uploaded cell content is never included.
    Empty rows are ignored; duplicate/empty headers and excess cells are errors.
    """
    if not isinstance(data, bytes) or not data:
        raise ValueError("Envie um arquivo CSV ou XLSX não vazio.")
    if max_rows < 1 or max_bytes < 1:
        raise ValueError("Os limites de importação devem ser positivos.")
    if len(data) > max_bytes:
        raise ValueError("O arquivo excede o limite de tamanho da importação.")
    extension = Path(str(filename)).suffix.lower()
    if extension not in {".csv", ".xlsx"}:
        raise ValueError("Importação disponível somente para CSV e XLSX.")
    try:
        if extension == ".xlsx":
            if not data.startswith(b"PK\x03\x04"):
                raise ValueError("O conteúdo do arquivo não corresponde a uma planilha XLSX.")
            return _parse_xlsx(data, max_rows)
        if data.startswith((b"PK", b"%PDF", b"\xd0\xcf\x11\xe0")) or b"\x00" in data:
            raise ValueError("O conteúdo do arquivo não corresponde a um CSV UTF-8.")
        text = data.decode("utf-8-sig")
        if any(ord(char) < 32 and char not in "\t\r\n" for char in text):
            raise ValueError("O CSV contém caracteres de controle inválidos.")
        first_line = text.splitlines()[0] if text.splitlines() else ""
        delimiter = "," if "," in first_line and ";" not in first_line else ";"
        reader = csv.reader(StringIO(text, newline=""), delimiter=delimiter, strict=True)

        def csv_rows():
            while True:
                source_row = reader.line_num + 1
                try:
                    values = next(reader)
                except StopIteration:
                    return
                yield _RowValues(values, source_row=source_row)

        return _table_records(csv_rows(), max_rows)
    except UnicodeDecodeError:
        raise ValueError("O CSV deve estar codificado em UTF-8.") from None
    except (BadZipFile, KeyError, IndexError, csv.Error, SafeXML.ParseError,
            DefusedXmlException, OverflowError, RuntimeError, NotImplementedError):
        raise ValueError("Arquivo inválido ou incompatível com o modelo de importação.") from None


def _table_records(rows, max_rows):
    headers = None
    records = []
    for position, values in enumerate(rows, 1):
        source_row = getattr(values, "source_row", position)
        values = ["" if value is None else str(value).strip() for value in values]
        if not any(values):
            continue
        if len(values) > MAX_IMPORT_COLUMNS or any(len(value) > MAX_CELL_CHARS for value in values):
            raise ValueError("A planilha excede o limite de colunas ou caracteres por célula.")
        if headers is None:
            headers = values
            normalized = [unicodedata.normalize("NFKC", value).casefold() for value in headers]
            if any(not value for value in headers) or len(set(normalized)) != len(headers):
                raise ValueError("A planilha contém cabeçalhos vazios ou duplicados.")
            continue
        if len(values) > len(headers):
            raise ValueError("Uma linha contém mais células do que o cabeçalho.")
        if len(records) >= max_rows:
            raise ValueError("A planilha excede o limite de linhas da importação.")
        records.append(TableRow(zip(headers, values + [""] * (len(headers) - len(values))), source_row=source_row))
    if headers is None:
        raise ValueError("A planilha não contém um cabeçalho válido.")
    return headers, records


def _parse_xlsx(data, max_rows):
    with ZipFile(BytesIO(data)) as archive:
        entries = archive.infolist()
        names = {entry.filename for entry in entries}
        if len(entries) > MAX_ZIP_ENTRIES or len(names) != len(entries):
            raise ValueError("A planilha contém entradas ZIP duplicadas ou em excesso.")
        if sum(entry.file_size for entry in entries) > MAX_ZIP_EXPANDED:
            raise ValueError("O conteúdo descompactado da planilha excede o limite permitido.")
        for entry in entries:
            name = entry.filename
            path = PurePosixPath(name)
            if (entry.flag_bits & 1 or entry.compress_type not in {ZIP_STORED, ZIP_DEFLATED}
                    or entry.file_size > MAX_ZIP_MEMBER
                    or entry.file_size > max(1, entry.compress_size) * 200
                    or path.is_absolute() or ".." in path.parts or "\\" in name):
                raise ValueError("A planilha contém uma entrada ZIP insegura ou excessiva.")
            lowered = name.lower()
            if any(marker in lowered for marker in ("vbaproject", "externallinks/", "activex/", "embeddings/")):
                raise ValueError("Macros, objetos incorporados e referências externas não são permitidos.")
        if not {"[Content_Types].xml", "xl/workbook.xml", "xl/_rels/workbook.xml.rels"}.issubset(names):
            raise ValueError("O conteúdo do arquivo não corresponde a uma planilha XLSX.")

        def xml(name):
            return SafeXML.fromstring(archive.read(name), forbid_dtd=True, forbid_entities=True, forbid_external=True)

        types = xml("[Content_Types].xml")
        if any(any(marker in element.attrib.get("ContentType", "").lower()
                   for marker in ("macroenabled", "vbaproject", "activex", "oleobject", "externallink"))
               for element in types):
            raise ValueError("Macros, objetos incorporados e referências externas não são permitidos.")
        if not any(element.attrib.get("ContentType") == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
                   and element.attrib.get("PartName") == "/xl/workbook.xml" for element in types):
            raise ValueError("Somente planilhas XLSX sem macros são permitidas.")
        for name in sorted(names):
            if name.lower().endswith(".rels"):
                for relationship in xml(name):
                    target = relationship.attrib.get("Target", "")
                    if (relationship.attrib.get("TargetMode", "").lower() == "external"
                            or ":" in target or target.startswith(("//", "\\\\"))):
                        raise ValueError("Links e referências externas não são permitidos na importação.")
            if name.lower().startswith("xl/worksheets/") and name.lower().endswith(".xml"):
                sheet = xml(name)
                if (sheet.find(f".//{{{_SHEET}}}f") is not None
                        or sheet.find(f".//{{{_SHEET}}}hyperlink") is not None):
                    raise ValueError("Fórmulas e links não são permitidos na importação.")
        workbook = xml("xl/workbook.xml")
        if workbook.find(f".//{{{_SHEET}}}definedName") is not None:
            raise ValueError("Intervalos nomeados e fórmulas não são permitidos na importação.")
        sheets = workbook.find(f"{{{_SHEET}}}sheets")
        if sheets is None or not len(sheets):
            raise ValueError("A planilha não contém abas válidas.")
        first_id = sheets[0].attrib.get(f"{{{_OFFICE_REL}}}id")
        relationships = xml("xl/_rels/workbook.xml.rels")
        relationship = next((item for item in relationships if item.attrib.get("Id") == first_id), None)
        if relationship is None or relationship.attrib.get("Type") != _OFFICE_REL + "/worksheet":
            raise ValueError("A primeira aba deve ser uma tabela XLSX válida.")
        target = relationship.attrib.get("Target", "")
        target_path = PurePosixPath(target.lstrip("/")) if target.startswith("/") else PurePosixPath("xl") / target
        if ".." in target_path.parts or not str(target_path).startswith("xl/worksheets/"):
            raise ValueError("A planilha contém uma referência de aba inválida.")
        shared = []
        if "xl/sharedStrings.xml" in names:
            for item in xml("xl/sharedStrings.xml").findall(f"{{{_SHEET}}}si"):
                shared.append("".join(node.text or "" for node in item.iter(f"{{{_SHEET}}}t")))
        sheet = xml(str(target_path))
        if (sheet.find(f".//{{{_SHEET}}}f") is not None
                or sheet.find(f".//{{{_SHEET}}}hyperlink") is not None):
            raise ValueError("Fórmulas e links não são permitidos na importação.")
        sheet_rows = sheet.find(f"{{{_SHEET}}}sheetData")
        if sheet_rows is None:
            raise ValueError("A planilha não contém linhas válidas.")

        def rows():
            seen_rows = set()
            for row in sheet_rows:
                row_number = row.attrib.get("r")
                if (not row_number or not row_number.isascii() or not row_number.isdigit()
                        or len(row_number) > 7 or not 1 <= int(row_number) <= 1048576):
                    raise ValueError("A planilha contém uma referência de linha inválida.")
                if row_number in seen_rows:
                    raise ValueError("A planilha contém linhas duplicadas.")
                seen_rows.add(row_number)
                values = {}
                for cell in row:
                    reference = _CELL_REFERENCE.fullmatch(cell.attrib.get("r", ""))
                    if reference is None or reference[2] != row_number:
                        raise ValueError("A planilha contém uma referência de célula inválida.")
                    column = 0
                    for letter in reference[1]:
                        column = column * 26 + ord(letter) - 64
                    if column > MAX_IMPORT_COLUMNS or column in values:
                        raise ValueError("A planilha contém células duplicadas ou colunas em excesso.")
                    cell_type = cell.attrib.get("t", "n")
                    value = cell.find(f"{{{_SHEET}}}v")
                    raw = "" if value is None else value.text or ""
                    if cell_type == "s":
                        if not raw.isascii() or not raw.isdigit() or len(raw) > 9 or int(raw) >= len(shared):
                            raise ValueError("A planilha contém uma referência de texto inválida.")
                        raw = shared[int(raw)]
                    elif cell_type == "inlineStr":
                        raw = "".join(node.text or "" for node in cell.iter(f"{{{_SHEET}}}t"))
                    elif cell_type not in {"n", "str", "b", "d"}:
                        raise ValueError("A planilha contém um tipo de célula não permitido.")
                    values[column] = raw
                yield _RowValues([values.get(column, "") for column in range(1, max(values, default=0) + 1)],
                                 source_row=int(row_number))

        return _table_records(rows(), max_rows)
