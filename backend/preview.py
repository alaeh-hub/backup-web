"""Turn a file into something a person can look at, for the Preview window.

Everything here only reads. Nothing is run, nothing is rendered as a web page (HTML is shown as text), and every read is
bounded, so a huge or hostile file costs a little time, never the whole PC:

  images, PDF, video, audio     streamed as they are (see RAW_TYPES) and shown by the browser itself
  text and code                 the start of the file
  csv, xlsx, ods                the first rows of each sheet, as a table
  docx, odt, rtf, pptx, odp     the text of the pages or slides
  doc, xls, ppt (old Office)    the readable text found inside
  zip, tar and friends          the list of what is inside, never unpacked
  anything else                 a hex dump of the first bytes, so every file shows something
"""
from __future__ import annotations

import base64
import csv
import datetime
import io
import re
import tarfile
import zipfile
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

import docxrender

MAX_TEXT = 200_000              # bytes of a text file shown
MAX_MEMBER = 8 * 1024 * 1024    # bytes read from one part of an Office or zip file
MAX_ROWS, MAX_COLS, MAX_CELL = 150, 26, 160
MAX_PARAS, MAX_SLIDES, MAX_ENTRIES = 600, 80, 500
HEX_BYTES = 768

RAW_TYPES = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp",
    "svg": "image/svg+xml", "ico": "image/x-icon", "avif": "image/avif",
    "pdf": "application/pdf",
    "mp4": "video/mp4", "m4v": "video/mp4", "webm": "video/webm", "ogv": "video/ogg", "mov": "video/quicktime",
    "mp3": "audio/mpeg", "wav": "audio/wav", "ogg": "audio/ogg", "oga": "audio/ogg", "m4a": "audio/mp4", "aac": "audio/aac",
    "flac": "audio/flac", "opus": "audio/ogg",
}
RAW_MODE = {}
for _e, _m in RAW_TYPES.items():
    RAW_MODE[_e] = "pdf" if _m == "application/pdf" else _m.split("/")[0]

TEXT_EXTS = set("""txt md markdown log nfo json jsonl xml html htm xhtml css scss js mjs ts tsx jsx vue py rb php java kt cs cpp cc c h hpp go rs
swift sql sh bat cmd ps1 psm1 yml yaml ini toml cfg conf properties env gitignore gitattributes editorconfig tex bib srt vtt sub
lrc rst adoc csv tsv diff patch reg inf url lnk-text""".split())
TABLE_EXTS = {"csv", "tsv", "xlsx", "xlsm", "ods"}
PAGE_EXTS = {"docx", "docm", "odt", "rtf", "pptx", "pptm", "odp"}
LEGACY_EXTS = {"doc", "xls", "ppt", "wps", "pub", "vsd"}
ZIP_EXTS = {"zip", "jar", "apk", "epub", "xpi", "cbz"}
TAR_EXTS = {"tar", "tgz", "tbz2", "txz"}

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
TXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
TBL = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"


def ext_of(name: str) -> str:
    m = re.search(r"\.([A-Za-z0-9]{1,10})$", name or "")
    return m.group(1).lower() if m else ""


def is_tar(name: str) -> bool:
    n = (name or "").lower()
    return ext_of(n) in TAR_EXTS or n.endswith((".tar.gz", ".tar.bz2", ".tar.xz"))


def raw_mode(name: str) -> str | None:
    """image, pdf, video or audio when the browser can show the file as it is; otherwise None."""
    return RAW_MODE.get(ext_of(name))


def raw_type(name: str) -> str | None:
    return RAW_TYPES.get(ext_of(name))


def mode_for(name: str) -> str:
    """How a file is previewed: image, pdf, video, audio (streamed), or text, table, pages, legacy, archive, hex (read here)."""
    e = ext_of(name)
    if e in RAW_MODE:
        return RAW_MODE[e]
    if e in TABLE_EXTS:
        return "table"
    if e in PAGE_EXTS:
        return "pages"
    if e in LEGACY_EXTS:
        return "legacy"
    if e in ZIP_EXTS or is_tar(name):
        return "archive"
    if e in TEXT_EXTS:
        return "text"
    return "sniff"                      # unknown kind: text if it looks like text, otherwise a hex dump


def decode(data: bytes) -> str:
    if data[:3] == b"\xef\xbb\xbf":
        return data[3:].decode("utf-8", "replace")
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", "replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", "replace")


def looks_like_text(head: bytes) -> bool:
    if not head:
        return True
    if head[:2] in (b"\xff\xfe", b"\xfe\xff") or head[:3] == b"\xef\xbb\xbf":
        return True
    if b"\x00" in head:
        return False
    bad = sum(1 for b in head if b < 9 or 13 < b < 32)
    return bad / len(head) < 0.05


def _clip(s: str) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= MAX_CELL else s[:MAX_CELL - 1] + "…"


# ---------------------------------------------------------------- text and tables

def text_preview(fh, size=None) -> dict:
    data = fh.read(MAX_TEXT + 1)
    cut = len(data) > MAX_TEXT
    text = decode(data[:MAX_TEXT]).replace("\r\n", "\n")
    return {"mode": "text", "text": text, "truncated": cut or (size is not None and size > MAX_TEXT), "lines": text.count("\n") + 1}


def delimited_preview(fh, ext: str) -> dict:
    text = decode(fh.read(MAX_TEXT + 1)[:MAX_TEXT])
    lines = text.splitlines()
    sample = "\n".join(lines[:20])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|") if ext != "tsv" else csv.excel_tab
    except csv.Error:
        dialect = csv.excel_tab if ext == "tsv" else csv.excel
    rows, cut = [], False
    for r in csv.reader(io.StringIO(text), dialect):
        if len(rows) >= MAX_ROWS:
            cut = True
            break
        rows.append([_clip(c) for c in r[:MAX_COLS]])
    return {"mode": "table", "sheets": [{"name": "", "rows": rows, "truncated": cut}]}


def _safe_xml(zf: zipfile.ZipFile, name: str):
    """Parse one part of an Office file, bounded in size, refusing anything that declares entities (the XML bomb trick)."""
    try:
        info = zf.getinfo(name)
    except KeyError:
        return None
    with zf.open(info) as f:
        data = f.read(MAX_MEMBER + 1)
    low = data[:65536].lower()
    if len(data) > MAX_MEMBER or b"<!entity" in low or b"<!doctype" in low:
        return None
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        return None


def _col(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref or "A").group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def _is_date_format(fid: int, custom: dict) -> bool:
    if fid in (14, 15, 16, 17, 18, 19, 20, 21, 22, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 45, 46, 47, 50, 51, 52, 53, 54, 55, 56, 57, 58):
        return True
    code = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.', "", custom.get(fid, "")).lower()
    return bool(code) and code != "general" and re.search(r"[ymdhs]", code) is not None and "0" not in code.replace("0.0", "")


def _date_styles(zf) -> set:
    """The cell styles (by position) whose number format is a date or a time."""
    st = _safe_xml(zf, "xl/styles.xml")
    if st is None:
        return set()
    custom = {}
    for nf in st.iter(S + "numFmt"):
        try:
            custom[int(nf.get("numFmtId", "0"))] = nf.get("formatCode", "")
        except ValueError:
            pass
    out = set()
    xfs = st.find(S + "cellXfs")
    for i, xf in enumerate(xfs.findall(S + "xf") if xfs is not None else []):
        try:
            if _is_date_format(int(xf.get("numFmtId", "0")), custom):
                out.add(i)
        except ValueError:
            pass
    return out


def _serial_text(v: str) -> str:
    """An Excel date serial (days since 1899-12-30) written as a date and, when it has one, a time."""
    try:
        x = float(v)
        d = datetime.datetime(1899, 12, 30) + datetime.timedelta(days=x)
    except (ValueError, OverflowError):
        return v
    if x < 1:
        return d.strftime("%H:%M")
    return d.strftime("%Y-%m-%d") if x == int(x) else d.strftime("%Y-%m-%d %H:%M")


def _number_text(v: str) -> str:
    try:
        x = float(v)
    except ValueError:
        return v
    return str(int(x)) if x == int(x) and abs(x) < 1e15 else f"{x:.10g}"


def xlsx_preview(fh) -> dict:
    zf = zipfile.ZipFile(fh)
    date_xf = _date_styles(zf)
    shared = []
    ss = _safe_xml(zf, "xl/sharedStrings.xml")
    if ss is not None:
        for si in ss.iter(S + "si"):
            shared.append("".join(t.text or "" for t in si.iter(S + "t")))
    names = []
    wb = _safe_xml(zf, "xl/workbook.xml")
    if wb is not None:
        names = [s.get("name", "") for s in wb.iter(S + "sheet")]
    parts = sorted((n for n in zf.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)), key=lambda n: int(re.findall(r"\d+", n)[0]))
    sheets = []
    for i, part in enumerate(parts[:3]):
        root = _safe_xml(zf, part)
        if root is None:
            continue
        rows, cut = [], False
        for row in root.iter(S + "row"):
            if len(rows) >= MAX_ROWS:
                cut = True
                break
            cells = {}
            for c in row.iter(S + "c"):
                col = _col(c.get("r", ""))
                if col >= MAX_COLS:
                    continue
                v = c.find(S + "v")
                t = c.get("t")
                if t == "s" and v is not None and (v.text or "").isdigit() and int(v.text) < len(shared):
                    val = shared[int(v.text)]
                elif t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter(S + "t"))
                elif t == "b":
                    val = "TRUE" if v is not None and v.text == "1" else "FALSE"
                elif v is None or v.text is None:
                    val = ""
                elif t in (None, "n") and c.get("s", "").isdigit() and int(c.get("s")) in date_xf:
                    val = _serial_text(v.text)
                elif t in (None, "n"):
                    val = _number_text(v.text)
                else:
                    val = v.text
                cells[col] = _clip(val)
            if cells:
                rows.append([cells.get(k, "") for k in range(max(cells) + 1)])
        sheets.append({"name": names[i] if i < len(names) else f"Sheet {i + 1}", "rows": rows, "truncated": cut})
    if len(parts) > 3:
        sheets.append({"name": f"{len(parts) - 3} more sheets not shown", "rows": [], "truncated": False})
    return {"mode": "table", "sheets": sheets}


def _ods_cells(row):
    out = []
    for c in row:
        if c.tag not in (TBL + "table-cell", TBL + "covered-table-cell"):
            continue
        txt = " ".join("".join(p.itertext()) for p in c.iter(TXT + "p"))
        rep = c.get(TBL + "number-columns-repeated")
        n = int(rep) if rep and rep.isdigit() and txt else 1
        out.extend([_clip(txt)] * min(n, 8))
        if len(out) >= MAX_COLS:
            break
    while out and not out[-1]:
        out.pop()
    return out[:MAX_COLS]


def ods_preview(fh) -> dict:
    zf = zipfile.ZipFile(fh)
    root = _safe_xml(zf, "content.xml")
    sheets = []
    if root is not None:
        for t in list(root.iter(TBL + "table"))[:3]:
            rows, cut = [], False
            for row in t.iter(TBL + "table-row"):
                cells = _ods_cells(row)
                if not cells:
                    continue
                if len(rows) >= MAX_ROWS:
                    cut = True
                    break
                rows.append(cells)
            sheets.append({"name": t.get(TBL + "name", ""), "rows": rows, "truncated": cut})
    return {"mode": "table", "sheets": sheets}


# ---------------------------------------------------------------- documents and slides

def docx_preview(fh) -> dict:
    zf = zipfile.ZipFile(fh)
    root = _safe_xml(zf, "word/document.xml")
    paras, cut = [], False
    if root is not None:
        for p in root.iter(W + "p"):
            if len(paras) >= MAX_PARAS:
                cut = True
                break
            parts = []
            for el in p.iter():
                if el.tag == W + "t" and el.text:
                    parts.append(el.text)
                elif el.tag in (W + "tab", W + "br"):
                    parts.append(" ")
            line = "".join(parts).strip()
            if line:
                paras.append(line)
    return {"mode": "pages", "pages": [{"title": "", "lines": paras}], "truncated": cut}


def docx_rendered(fh) -> dict:
    """A Word file drawn as a page (formatting, lists, tables, pictures); if that cannot be done, its plain text."""
    try:
        out = docxrender.render(zipfile.ZipFile(fh))
    except (zipfile.BadZipFile, ET.ParseError, KeyError, ValueError, RecursionError):
        out = None
    if out is not None and (out["blocks"] or out["images"]):
        return out
    fh.seek(0)
    return docx_preview(fh)


def pptx_preview(fh) -> dict:
    zf = zipfile.ZipFile(fh)
    parts = sorted((n for n in zf.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)), key=lambda n: int(re.findall(r"\d+", n)[0]))
    pages = []
    for i, part in enumerate(parts[:MAX_SLIDES], 1):
        root = _safe_xml(zf, part)
        lines = []
        if root is not None:
            for p in root.iter(A + "p"):
                line = "".join(t.text or "" for t in p.iter(A + "t")).strip()
                if line:
                    lines.append(line)
        pages.append({"title": f"Slide {i}", "lines": lines})
    return {"mode": "pages", "pages": pages, "truncated": len(parts) > MAX_SLIDES}


def odf_preview(fh, slides: bool) -> dict:
    zf = zipfile.ZipFile(fh)
    root = _safe_xml(zf, "content.xml")
    pages, cut = [], False
    if root is not None:
        if slides:
            pg = "{urn:oasis:names:tc:opendocument:xmlns:drawing:1.0}page"
            for i, page in enumerate(list(root.iter(pg))[:MAX_SLIDES], 1):
                pages.append({"title": f"Slide {i}", "lines": [t for t in ("".join(p.itertext()).strip() for p in page.iter(TXT + "p")) if t]})
        else:
            lines = []
            for el in root.iter():
                if el.tag in (TXT + "p", TXT + "h"):
                    t = "".join(el.itertext()).strip()
                    if t:
                        lines.append(t)
                    if len(lines) >= MAX_PARAS:
                        cut = True
                        break
            pages.append({"title": "", "lines": lines})
    return {"mode": "pages", "pages": pages, "truncated": cut}


def rtf_preview(fh) -> dict:
    raw = fh.read(MAX_TEXT * 2).decode("latin-1")
    raw = re.sub(r"\{\\\*[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", "", raw)              # groups the text does not live in
    raw = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: bytes.fromhex(m.group(1)).decode("cp1252", "replace"), raw)
    raw = re.sub(r"\\(par|line|row)\b ?", "\n", raw)
    raw = re.sub(r"\\tab\b ?", "\t", raw)
    raw = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", raw)
    raw = re.sub(r"[{}]", "", raw).replace("\\\\", "\\")
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    return {"mode": "pages", "pages": [{"title": "", "lines": lines[:MAX_PARAS]}], "truncated": len(lines) > MAX_PARAS}


def legacy_preview(fh) -> dict:
    """Old Word, Excel and PowerPoint files keep their text among binary: pull out the readable runs, ASCII and UTF-16."""
    data = fh.read(4 * 1024 * 1024)
    runs = re.findall(rb"[\x20-\x7e\xa0-\xff]{8,}", data)
    runs += [r.decode("utf-16le", "ignore").encode("utf-8") for r in re.findall(rb"(?:[\x20-\x7e]\x00){8,}", data)]
    seen, lines = set(), []
    for r in runs:
        t = r.decode("utf-8", "ignore").strip()
        if t and t not in seen and not re.fullmatch(r"[\W_]+", t):
            seen.add(t)
            lines.append(t)
        if len(lines) >= MAX_PARAS:
            break
    return {"mode": "pages", "pages": [{"title": "Readable text found in this file", "lines": lines}], "truncated": False, "approximate": True}


# ---------------------------------------------------------------- archives and the rest

def zip_preview(fh) -> dict:
    zf = zipfile.ZipFile(fh)
    infos = zf.infolist()
    ents = [{"name": i.filename, "size": i.file_size} for i in infos[:MAX_ENTRIES] if not i.filename.endswith("/")]
    return {"mode": "archive", "entries": ents, "total": len(infos), "truncated": len(infos) > MAX_ENTRIES}


def tar_preview(fh) -> dict:
    tf = tarfile.open(fileobj=fh, mode="r:*")
    ents, total = [], 0
    for m in tf:
        total += 1
        if len(ents) < MAX_ENTRIES and m.isfile():
            ents.append({"name": m.name, "size": m.size})
        if total > 20000:
            break
    return {"mode": "archive", "entries": ents, "total": total, "truncated": total > MAX_ENTRIES}


def _id3_text(data: bytes) -> str:
    if not data:
        return ""
    enc, body = data[0], data[1:]
    try:
        if enc == 0:
            t = body.decode("latin-1")
        elif enc == 1:
            t = body.decode("utf-16")
        elif enc == 2:
            t = body.decode("utf-16-be")
        else:
            t = body.decode("utf-8")
    except UnicodeDecodeError:
        t = body.decode("latin-1", "replace")
    return t.split("\x00")[0].strip()


def id3_tags(head: bytes) -> dict:
    """Title, artist, album, year and cover picture from the ID3v2 tag at the start of an mp3 (the first bytes of the file)."""
    if head[:3] != b"ID3" or len(head) < 10:
        return {}
    ver = head[3]
    if ver not in (2, 3, 4):
        return {}
    flags = head[5]
    size = (head[6] << 21) | (head[7] << 14) | (head[8] << 7) | head[9]
    end = min(10 + size, len(head))
    pos = 10
    if ver >= 3 and flags & 0x40 and pos + 4 <= end:                      # an extended header to skip
        pos += (int.from_bytes(head[pos:pos + 4], "big") if ver == 3 else ((head[pos] << 21) | (head[pos + 1] << 14) | (head[pos + 2] << 7) | head[pos + 3]))
    names = {"TIT2": "title", "TT2": "title", "TPE1": "artist", "TP1": "artist", "TALB": "album", "TAL": "album",
             "TYER": "year", "TYE": "year", "TDRC": "year", "TRCK": "track", "TRK": "track", "TCON": "genre", "TCO": "genre"}
    out = {}
    idlen, hdr = (3, 6) if ver == 2 else (4, 10)
    while pos + hdr <= end:
        fid = head[pos:pos + idlen].decode("latin-1")
        if not fid.strip("\x00"):
            break
        raw = head[pos + idlen:pos + hdr]
        if ver == 2:
            n = int.from_bytes(raw, "big")
        elif ver == 3:
            n = int.from_bytes(raw[:4], "big")
        else:
            n = (raw[0] << 21) | (raw[1] << 14) | (raw[2] << 7) | raw[3]
        body = head[pos + hdr:pos + hdr + n]
        pos += hdr + n
        if fid in names and names[fid] not in out:
            t = _id3_text(body)
            if t:
                out[names[fid]] = t[:4] if names[fid] == "year" else t[:200]
        elif fid in ("APIC", "PIC") and "cover" not in out and len(body) > 8:
            enc, rest = body[0], body[1:]
            if fid == "APIC":
                z = rest.find(b"\x00")
                mime = rest[:z].decode("latin-1") if z >= 0 else ""
                rest = rest[z + 2:] if z >= 0 else b""                       # past the type byte
            else:
                mime = "image/" + ("png" if rest[:3] == b"PNG" else "jpeg")
                rest = rest[4:]
            term = b"\x00\x00" if enc in (1, 2) else b"\x00"
            z = rest.find(term)
            pic = rest[z + len(term):] if z >= 0 else rest
            jpeg, png = pic[:2] == b"\xff\xd8", pic[:4] == b"\x89PNG"
            if mime in ("image/jpeg", "image/jpg", "image/png") and 0 < len(pic) <= 700_000 and (jpeg or png):
                out["cover"] = f"data:{'image/png' if png else 'image/jpeg'};base64," + base64.b64encode(pic).decode()
    return out


def hex_preview(fh) -> dict:
    data = fh.read(HEX_BYTES)
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        hx = " ".join(f"{b:02x}" for b in chunk).ljust(47)
        lines.append(f"{i:06x}  {hx}  " + "".join(chr(b) if 32 <= b < 127 else "." for b in chunk))
    return {"mode": "hex", "hex": "\n".join(lines), "shown": len(data)}


class _HtmlTables(HTMLParser):
    """The tables, and the plain text, of an HTML page. Nothing in the page is run or followed; scripts and styles are skipped."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.text = [], []
        self._depth, self._rows, self._row, self._cell, self._skip = 0, None, None, None, 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head", "title"):
            self._skip += 1
        elif tag == "table":
            self._depth += 1
            if self._depth == 1:
                self._rows = []
        elif self._depth == 1 and tag == "tr":
            self._row = []
        elif self._depth == 1 and tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag in ("br", "p", "div", "li", "h1", "h2", "h3", "h4", "tr"):
            self.text.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head", "title"):
            self._skip = max(0, self._skip - 1)
        elif tag in ("td", "th") and self._depth == 1 and self._cell is not None and self._row is not None:
            self._row.append(_clip("".join(self._cell)))
            self._cell = None
        elif tag == "tr" and self._depth == 1 and self._row is not None:
            if any(self._row):
                self._rows.append(self._row[:MAX_COLS])
            self._row = None
        elif tag == "table" and self._depth:
            self._depth -= 1
            if self._depth == 0 and self._rows is not None:
                if self._rows:
                    self.tables.append(self._rows)
                self._rows = None

    def handle_data(self, data):
        if self._skip:
            return
        if self._cell is not None:
            self._cell.append(data)
        self.text.append(data)


def html_preview(fh) -> dict:
    """An HTML page saved with an Office name (a common export, .xls or .doc that Excel and Word open as a page): its tables
    as a table, or, without tables, its text."""
    data = fh.read(MAX_MEMBER)
    parser = _HtmlTables()
    try:
        parser.feed(decode(data))
        parser.close()
    except Exception:                                      # a broken page still shows what was read so far
        pass
    if parser.tables:
        sheets = []
        for i, rows in enumerate(parser.tables[:3], 1):
            sheets.append({"name": f"Table {i}" if len(parser.tables) > 1 else "", "rows": rows[:MAX_ROWS], "truncated": len(rows) > MAX_ROWS})
        return {"mode": "table", "sheets": sheets, "note": "This file is really an HTML table saved with an Excel or Word name, so it is shown as a table."}
    lines = [" ".join(x.split()) for x in "".join(parser.text).split("\n")]
    lines = [x for x in lines if x][:MAX_PARAS]
    return {"mode": "pages", "pages": [{"title": "", "lines": lines}], "truncated": False,
            "note": "This file is really a web page saved with an Office name, so its text is shown."}


def spreadsheetml_preview(fh) -> dict:
    """Excel 2003's XML spreadsheet (also saved as .xls)."""
    data = fh.read(MAX_MEMBER + 1)
    low = data[:65536].lower()
    if len(data) > MAX_MEMBER or b"<!entity" in low or b"<!doctype" in low:
        return {"mode": "table", "sheets": []}
    ns = "{urn:schemas-microsoft-com:office:spreadsheet}"
    root = ET.fromstring(data)
    sheets = []
    for i, ws in enumerate(list(root.iter(ns + "Worksheet"))[:3], 1):
        rows, cut = [], False
        for row in ws.iter(ns + "Row"):
            if len(rows) >= MAX_ROWS:
                cut = True
                break
            cells = []
            for c in row.iter(ns + "Cell"):
                d = c.find(ns + "Data")
                cells.append(_clip("".join(d.itertext())) if d is not None else "")
            cells = cells[:MAX_COLS]
            if any(cells):
                rows.append(cells)
        sheets.append({"name": ws.get("{urn:schemas-microsoft-com:office:spreadsheet}Name", f"Sheet {i}"), "rows": rows, "truncated": cut})
    return {"mode": "table", "sheets": sheets}


OFFICE_EXTS = {"xls", "xlsx", "xlsm", "xlsb", "ods", "csv", "tsv", "doc", "docx", "docm", "dot", "dotx", "odt", "rtf", "ppt", "pptx", "odp", "wps"}


def disguised(name: str, fh) -> dict | None:
    """What a file really is, when it is not what its extension says: an HTML table saved as .xls, an XML spreadsheet, RTF
    saved as .doc, a modern file under an old name or the other way round, plain text saved as .xls. None when the extension is honest."""
    e = ext_of(name)
    if e not in OFFICE_EXTS:
        return None
    head = fh.read(4096)
    fh.seek(0)
    h = head.lstrip(b"\xef\xbb\xbf \t\r\n")[:3000].lower()
    ole = head[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    if head[:4] == b"PK\x03\x04":
        zf = zipfile.ZipFile(fh)
        names = set(zf.namelist())
        fh.seek(0)
        if "word/document.xml" in names and e not in ("docx", "docm", "dotx"):
            return docx_rendered(fh)
        if "xl/workbook.xml" in names and e not in ("xlsx", "xlsm"):
            return xlsx_preview(fh)
        if any(n.startswith("ppt/slides/") for n in names) and e not in ("pptx",):
            return pptx_preview(fh)
        if "content.xml" in names and e not in ("ods", "odt", "odp"):
            return None
        return None
    if ole and e in ("docx", "xlsx", "pptx", "xlsm", "docm"):
        return legacy_preview(fh)
    if head[:5] == b"{\\rtf" and e != "rtf":
        return rtf_preview(fh)
    if b"urn:schemas-microsoft-com:office:spreadsheet" in head and b"<workbook" in h:
        return spreadsheetml_preview(fh)
    if not ole and (h.startswith((b"<html", b"<!doctype html", b"<table", b"<head", b"<body", b"<meta")) or (b"<html" in h) or (b"<table" in h)):
        return html_preview(fh)
    if not ole and e in ("xls", "xlsx", "xlsm", "xlsb") and looks_like_text(head):
        out = delimited_preview(fh, "tsv" if b"\t" in head else "csv")
        out["note"] = "This file is really plain text saved with an Excel name, so it is shown as a table."
        return out
    if not ole and e in ("doc", "docx", "docm", "wps", "odt") and looks_like_text(head) and head[:2] != b"PK":
        out = text_preview(fh)
        out["note"] = "This file is really plain text saved with a Word name."
        return out
    return None


def build(name: str, fh, size: int | None = None) -> dict:
    """The preview of one file, read from `fh` (a seekable binary file). Raises only for a damaged file; the caller falls back."""
    e = ext_of(name)
    mode = mode_for(name)
    other = disguised(name, fh)
    if other is not None:
        return other
    if mode == "text":
        return delimited_preview(fh, e) if e in ("csv", "tsv") else text_preview(fh, size)
    if mode == "table":
        if e in ("csv", "tsv"):
            return delimited_preview(fh, e)
        return ods_preview(fh) if e == "ods" else xlsx_preview(fh)
    if mode == "pages":
        if e in ("docx", "docm"):
            return docx_rendered(fh)
        if e in ("pptx", "pptm"):
            return pptx_preview(fh)
        if e == "rtf":
            return rtf_preview(fh)
        return odf_preview(fh, slides=(e == "odp"))
    if mode == "legacy":
        return legacy_preview(fh)
    if mode == "archive":
        return tar_preview(fh) if is_tar(name) else zip_preview(fh)
    head = fh.read(4096)
    fh.seek(0)
    if mode == "sniff" and looks_like_text(head):
        return text_preview(fh, size)
    return hex_preview(fh)
