"""Read and write .xlsx workbooks with the standard library only (zipfile + xml), so Excel files work offline
without installing anything.

read_xlsx(bytes)  -> {sheet name: [[cell, ...], ...]}   cells are str, int, float, bool, datetime.date or None
write_xlsx(sheets) -> bytes                                sheets = [Sheet(name, rows, widths, formats)]
"""
import io
import posixpath
import re
import zipfile
from datetime import date, datetime, timedelta
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from ..errors import ApiError

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "pr": "http://schemas.openxmlformats.org/package/2006/relationships"}
MAX_UNPACKED = 200 * 1024 * 1024
BUILTIN_DATE_FORMATS = set(range(14, 23)) | set(range(27, 37)) | set(range(45, 48)) | set(range(50, 59))
EPOCH = date(1899, 12, 30)


def _q(tag):
    ns, name = tag.split(":")
    return "{%s}%s" % (NS[ns], name)


def _parse(zf, name):
    """Parse an XML part, refusing entity declarations (protects against 'billion laughs' files)."""
    data = zf.read(name)
    if b"<!ENTITY" in data or b"<!DOCTYPE" in data:
        raise ApiError("That Excel file contains unsafe content and was not read.")
    return ET.fromstring(data)


def _col_index(ref):
    letters = re.match(r"[A-Z]+", ref).group(0)
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


def _is_date_format(code):
    code = re.sub(r'"[^"]*"|\\.|\[[^\]]*\]', "", code or "").lower()
    return bool(re.search(r"[dmyhs]", code)) and not re.search(r"0\.0|#", code)


def read_xlsx(raw):
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise ApiError("That doesn't look like an Excel (.xlsx) file.")
    if sum(i.file_size for i in zf.infolist()) > MAX_UNPACKED:
        raise ApiError("That Excel file is too large to read.")
    names = set(zf.namelist())
    if "xl/workbook.xml" not in names:
        raise ApiError("That doesn't look like an Excel (.xlsx) file. (Old .xls files: save as .xlsx or CSV first.)")

    shared = []
    if "xl/sharedStrings.xml" in names:
        for si in _parse(zf, "xl/sharedStrings.xml").findall(_q("m:si")):
            shared.append("".join(t.text or "" for t in si.iter(_q("m:t"))))

    date_styles = set()
    if "xl/styles.xml" in names:
        st = _parse(zf, "xl/styles.xml")
        custom = {int(n.get("numFmtId")): n.get("formatCode") for n in st.iter(_q("m:numFmt"))}
        xfs = st.find(_q("m:cellXfs"))
        for idx, xf in enumerate(xfs.findall(_q("m:xf")) if xfs is not None else []):
            fid = int(xf.get("numFmtId", "0"))
            if fid in BUILTIN_DATE_FORMATS or (fid in custom and _is_date_format(custom[fid])):
                date_styles.add(idx)

    rels = {}
    if "xl/_rels/workbook.xml.rels" in names:
        for rel in _parse(zf, "xl/_rels/workbook.xml.rels").findall(_q("pr:Relationship")):
            rels[rel.get("Id")] = rel.get("Target")
    wb = _parse(zf, "xl/workbook.xml")
    out = {}
    for sh in wb.iter(_q("m:sheet")):
        target = rels.get(sh.get(_q("r:id")))
        if not target:
            continue
        path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
        if path not in names:
            continue
        out[sh.get("name")] = _read_sheet(_parse(zf, path), shared, date_styles)
    return out


def _read_sheet(root, shared, date_styles):
    table = []
    for row in root.iter(_q("m:row")):
        r_index = int(row.get("r", len(table) + 1)) - 1
        while len(table) < r_index:
            table.append([])
        cells = []
        for c in row.findall(_q("m:c")):
            idx = _col_index(c.get("r", "A1"))
            while len(cells) < idx:
                cells.append(None)
            cells.append(_cell_value(c, shared, date_styles))
        table.append(cells)
        if len(table) > 500_000:
            raise ApiError("That sheet has too many rows.")
    return table


def _cell_value(c, shared, date_styles):
    t = c.get("t", "n")
    v = c.find(_q("m:v"))
    if t == "inlineStr":
        return "".join(x.text or "" for x in c.iter(_q("m:t")))
    if v is None or v.text is None:
        return None
    text = v.text
    if t == "s":
        return shared[int(text)] if int(text) < len(shared) else None
    if t in ("str", "e"):
        return text
    if t == "b":
        return text == "1"
    if t == "d":
        try:
            return datetime.fromisoformat(text).date()
        except ValueError:
            return text
    try:
        num = float(text)
    except ValueError:
        return text
    if int(c.get("s", "0")) in date_styles and 1 <= num < 2_958_466:
        return EPOCH + timedelta(days=int(num))
    return int(num) if num == int(num) and abs(num) < 1e15 else num


# ---------------------------------------------------------------- writing

class Sheet:
    """rows: list of lists. A cell is str / int / float / date / None. `header` rows are styled bold.
    widths: column widths in characters."""

    def __init__(self, name, rows, widths=None, header_rows=1):
        self.name, self.rows, self.widths, self.header_rows = name[:31], rows, widths or [], header_rows


S_DEFAULT, S_HEADER, S_DATE, S_INT, S_DEC = 0, 1, 2, 3, 4

STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="1"><numFmt numFmtId="164" formatCode="mmm\\ d\\,\\ yyyy"/></numFmts>
<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>
<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFE8E8E8"/></patternFill></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="5">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>
<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="3" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="4" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""

_BAD_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


def _col_name(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _cell_xml(ref, value, header):
    if value is None or value == "":
        return ""
    if header:
        return f'<c r="{ref}" s="{S_HEADER}" t="inlineStr"><is><t>{escape(_BAD_XML.sub("", str(value)))}</t></is></c>'
    if isinstance(value, bool):
        return f'<c r="{ref}" t="b"><v>{int(value)}</v></c>'
    if isinstance(value, (datetime, date)):
        d = value.date() if isinstance(value, datetime) else value
        return f'<c r="{ref}" s="{S_DATE}"><v>{(d - EPOCH).days}</v></c>'
    if isinstance(value, int):
        return f'<c r="{ref}" s="{S_INT}"><v>{value}</v></c>'
    if isinstance(value, float):
        style = S_INT if value == int(value) else S_DEC
        return f'<c r="{ref}" s="{style}"><v>{repr(value)}</v></c>'
    text = _BAD_XML.sub("", str(value))
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(text)}</t></is></c>'


def _sheet_xml(sheet):
    cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(sheet.widths))
    body = []
    for r, row in enumerate(sheet.rows, start=1):
        cells = "".join(_cell_xml(f"{_col_name(c)}{r}", v, r <= sheet.header_rows) for c, v in enumerate(row))
        body.append(f'<row r="{r}">{cells}</row>')
    ncols = max((len(r) for r in sheet.rows), default=1)
    last = f"{_col_name(max(ncols, 1) - 1)}{max(len(sheet.rows), 1)}"
    freeze = ('<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
              '</sheetView></sheetViews>') if sheet.header_rows else ""
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'{freeze}<cols>{cols}</cols><sheetData>{"".join(body)}</sheetData>'
            f'<autoFilter ref="A1:{last}"/></worksheet>' if cols else
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'{freeze}<sheetData>{"".join(body)}</sheetData><autoFilter ref="A1:{last}"/></worksheet>')


def write_xlsx(sheets):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                             for i in range(1, len(sheets) + 1)) + "</Types>")
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   '</Relationships>')
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{escape(s.name)}" sheetId="{i}" r:id="rId{i}"/>' for i, s in enumerate(sheets, 1))
                   + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
                             for i in range(1, len(sheets) + 1))
                   + f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                   "</Relationships>")
        z.writestr("xl/styles.xml", STYLES)
        for i, s in enumerate(sheets, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", _sheet_xml(s))
    return buf.getvalue()
