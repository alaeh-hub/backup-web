"""A Word document as a plain model of blocks (paragraphs, lists, tables, pictures) that the app draws like a page.

Read-only and bounded. Only the document's own text, formatting and the names of pictures inside it are read; nothing in it is
run, no link is followed, and the XML is refused if it declares entities. Pictures are not sent here: the model names them
(`word/media/image1.png`) and the app asks for each one separately, from the same file.
"""
from __future__ import annotations

import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile

MAX_BLOCKS = 2500
MAX_CHARS = 500_000
MAX_IMAGES = 400
MAX_XML = 24 * 1024 * 1024
IMG_EXT = {"png", "jpg", "jpeg", "gif", "webp", "bmp"}
EMU_PX = 9525
HEX = re.compile(r"[0-9A-Fa-f]{6}")
HIGHLIGHT = {"yellow": "FFF200", "green": "00FF00", "cyan": "00FFFF", "magenta": "FF00FF", "blue": "5B9BFF", "red": "FF6B6B",
             "lightGray": "D9D9D9", "darkYellow": "BFA600", "darkGreen": "2E8B57", "darkCyan": "2CA0A8"}


class _Stop(Exception):
    pass


def ln(el) -> str:
    return el.tag.rsplit("}", 1)[-1] if isinstance(el.tag, str) else ""


def at(el, name, default=None):
    if el is None:
        return default
    for k, v in el.attrib.items():
        if k.rsplit("}", 1)[-1] == name:
            return v
    return default


def child(el, name):
    if el is None:
        return None
    for c in el:
        if ln(c) == name:
            return c
    return None


def children(el, name):
    return [c for c in el if ln(c) == name] if el is not None else []


def load(zf: zipfile.ZipFile, part: str):
    """One XML part, parsed; None if it is missing, too big, broken or declares entities."""
    try:
        info = zf.getinfo(part)
    except KeyError:
        return None
    if info.file_size > MAX_XML:
        return None
    with zf.open(info) as f:
        data = f.read(MAX_XML + 1)
    low = data[:65536].lower()
    if b"<!entity" in low or b"<!doctype" in low:
        return None
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        return None


def _on(el) -> bool:
    """A toggle like <w:b/> is on unless it says val=0, false or off."""
    return el is not None and str(at(el, "val", "1")).lower() not in ("0", "false", "off", "none")


def run_props(rpr) -> dict:
    out = {}
    if rpr is None:
        return out
    for name, key in (("b", "b"), ("i", "i"), ("strike", "s"), ("dstrike", "s"), ("caps", "caps"), ("smallCaps", "caps")):
        el = child(rpr, name)
        if el is not None:
            out[key] = 1 if _on(el) else 0
    u = child(rpr, "u")
    if u is not None:
        out["u"] = 0 if str(at(u, "val", "single")).lower() == "none" else 1
    c = at(child(rpr, "color"), "val")
    if c and HEX.fullmatch(c):
        out["c"] = c.upper()
    sz = at(child(rpr, "sz"), "val")
    if sz and sz.isdigit():
        out["sz"] = max(8, min(96, int(sz))) / 2          # half-points -> points
    hl = at(child(rpr, "highlight"), "val")
    if hl in HIGHLIGHT:
        out["hl"] = HIGHLIGHT[hl]
    va = at(child(rpr, "vertAlign"), "val")
    if va in ("superscript", "subscript"):
        out["va"] = va
    fonts = child(rpr, "rFonts")
    name = (at(fonts, "ascii") or at(fonts, "hAnsi") or "").lower()
    if name:
        out["f"] = "mono" if re.search(r"courier|consolas|mono|menlo", name) else "serif" if re.search(r"times|georgia|garamond|cambria|serif|palatino|book", name) else "sans"
    return out


def para_props(ppr) -> dict:
    out = {}
    if ppr is None:
        return out
    jc = at(child(ppr, "jc"), "val")
    if jc in ("center", "right", "both", "left", "start", "end"):
        out["al"] = {"both": "justify", "start": "left", "end": "right"}.get(jc, jc)
    ind = child(ppr, "ind")
    for key, names in (("left", ("left", "start")), ("hang", ("hanging",)), ("first", ("firstLine",))):
        for n in names:
            v = at(ind, n)
            if v and v.lstrip("-").isdigit():
                out[key] = int(v) / 20                          # twips -> points
    sp = child(ppr, "spacing")
    for key, n in (("before", "before"), ("after", "after")):
        v = at(sp, n)
        if v and v.isdigit():
            out[key] = min(int(v) / 20, 72)
    num = child(ppr, "numPr")
    if num is not None:
        out["num"] = (at(child(num, "numId"), "val"), int(at(child(num, "ilvl"), "val", "0") or 0))
    out["style"] = at(child(ppr, "pStyle"), "val")
    return out


class Styles:
    def __init__(self, zf):
        self.by_id, self.base_r = {}, {}
        root = load(zf, "word/styles.xml")
        if root is None:
            return
        dd = child(root, "docDefaults")
        self.base_r = run_props(child(child(dd, "rPrDefault"), "rPr")) if dd is not None else {}
        for s in children(root, "style"):
            sid = at(s, "styleId")
            if sid:
                self.by_id[sid] = {"name": (at(child(s, "name"), "val") or "").lower(), "based": at(child(s, "basedOn"), "val"),
                                   "r": run_props(child(s, "rPr")), "p": para_props(child(s, "pPr")), "type": at(s, "type")}

    def chain(self, sid):
        out, seen = [], set()
        while sid and sid in self.by_id and sid not in seen and len(out) < 8:
            seen.add(sid)
            out.append(self.by_id[sid])
            sid = self.by_id[sid]["based"]
        return list(reversed(out))                                   # base first

    def merged(self, sid, key):
        out = {}
        for s in self.chain(sid):
            out.update(s[key])
        return out

    def level(self, sid):
        """title, h1 to h6, or '' for an ordinary paragraph."""
        for s in reversed(self.chain(sid)):
            m = re.fullmatch(r"(?:heading|titre|kop)\s*([1-6])", s["name"])
            if m:
                return "h" + m.group(1)
            if s["name"] in ("title", "subtitle"):
                return s["name"]
        return ""


class Numbering:
    def __init__(self, zf):
        self.abstract, self.nums, self.count = {}, {}, {}
        root = load(zf, "word/numbering.xml")
        if root is None:
            return
        for a in children(root, "abstractNum"):
            lv = {}
            for l in children(a, "lvl"):
                lv[int(at(l, "ilvl", "0") or 0)] = {"fmt": at(child(l, "numFmt"), "val", "decimal"), "text": at(child(l, "lvlText"), "val", ""),
                                                   "start": int(at(child(l, "start"), "val", "1") or 1)}
            self.abstract[at(a, "abstractNumId")] = lv
        for n in children(root, "num"):
            self.nums[at(n, "numId")] = at(child(n, "abstractNumId"), "val")

    @staticmethod
    def _fmt(n: int, fmt: str) -> str:
        if fmt == "lowerLetter":
            return chr(96 + (n - 1) % 26 + 1) if n > 0 else str(n)
        if fmt == "upperLetter":
            return chr(64 + (n - 1) % 26 + 1) if n > 0 else str(n)
        if fmt in ("lowerRoman", "upperRoman"):
            vals = [(1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"), (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]
            out, k = "", max(1, n)
            for v, s in vals:
                while k >= v:
                    out, k = out + s, k - v
            return out.upper() if fmt == "upperRoman" else out
        return str(n)

    def label(self, num_id, lvl):
        """The marker for the next paragraph of this list at this level: a bullet or '1.', 'a)', '1.2'."""
        levels = self.abstract.get(self.nums.get(num_id), {})
        info = levels.get(lvl)
        if info is None:
            return "•"
        if info["fmt"] == "bullet" or info["fmt"] == "none":
            return ("•", "◦", "▪")[min(lvl, 2)] if info["fmt"] == "bullet" else ""
        counts = self.count.setdefault(num_id, {})
        counts[lvl] = counts.get(lvl, info["start"] - 1) + 1
        for deeper in [k for k in counts if k > lvl]:
            del counts[deeper]
        def rep(m):
            k = int(m.group(1)) - 1
            lv = levels.get(k, info)
            return self._fmt(counts.get(k, lv["start"]), lv["fmt"])
        return re.sub(r"%([1-9])", rep, info["text"] or "%1.")


class Ctx:
    def __init__(self, zf):
        self.zf = zf
        self.styles, self.numbering = Styles(zf), Numbering(zf)
        self.chars = 0
        self.images = []
        self.rels = {}
        rels = load(zf, "word/_rels/document.xml.rels")
        for r in children(rels, "Relationship") if rels is not None else []:
            if str(at(r, "Type", "")).endswith("/image") and at(r, "TargetMode") != "External":
                t = at(r, "Target", "")
                part = t[1:] if t.startswith("/") else posixpath.normpath("word/" + t)
                if part.startswith("word/media/") and part.rsplit(".", 1)[-1].lower() in IMG_EXT:
                    self.rels[at(r, "Id")] = part


def _picture(ctx: Ctx, el):
    """An image inside a run (a drawing or an old-style picture): the part name and its size on the page, or None."""
    rid = None
    for d in el.iter():
        n = ln(d)
        if n == "blip":
            rid = at(d, "embed")
            break
        if n == "imagedata":
            rid = at(d, "id")
            break
    part = ctx.rels.get(rid)
    if not part or len(ctx.images) >= MAX_IMAGES:
        return None
    ext = next((d for d in el.iter() if ln(d) == "extent"), None)
    w = h = None
    if ext is not None and str(at(ext, "cx", "")).isdigit() and str(at(ext, "cy", "")).isdigit():
        w, h = round(int(at(ext, "cx")) / EMU_PX), round(int(at(ext, "cy")) / EMU_PX)
    doc = next((d for d in el.iter() if ln(d) == "docPr"), None)
    ctx.images.append(part)
    out = {"img": part}
    if w and h:
        out["w"], out["h"] = min(w, 4000), min(h, 4000)
    if at(doc, "descr"):
        out["alt"] = at(doc, "descr")[:200]
    return out


def _runs(ctx: Ctx, p, base_r: dict, boxes: list):
    runs = []

    def add(piece):
        runs.append(piece)

    def run(r, inherited):
        props = dict(inherited)
        rpr = child(r, "rPr")
        rs = at(child(rpr, "rStyle"), "val")
        if rs:
            props.update(ctx.styles.merged(rs, "r"))
        props.update(run_props(rpr))
        for c in r:
            n = ln(c)
            if n == "t" and c.text:
                ctx.chars += len(c.text)
                add({**props, "x": c.text})
            elif n == "tab":
                add({**props, "x": "\t"})
            elif n == "br":
                add({"br": "page" if at(c, "type") == "page" else "line"})
            elif n in ("noBreakHyphen",):
                add({**props, "x": "-"})
            elif n in ("drawing", "pict", "object"):
                walk_graphic(c, props)
            elif n == "AlternateContent":
                choice = child(c, "Choice")
                if choice is not None:
                    for g in choice:
                        walk_graphic(g, props)
        if ctx.chars > MAX_CHARS:
            raise _Stop()

    def walk_graphic(g, props):
        for box in (d for d in g.iter() if ln(d) == "txbxContent"):      # text in a text box becomes its own block after this paragraph
            blocks = []
            _body(ctx, box, blocks, boxes_flag=True)
            boxes.extend(blocks)
        pic = _picture(ctx, g)
        if pic:
            add(pic)

    def walk(el, inherited):
        for c in el:
            n = ln(c)
            if n == "r":
                run(c, inherited)
            elif n in ("hyperlink", "smartTag", "sdt", "sdtContent", "ins", "fldSimple", "customXml", "bdo", "dir"):
                walk(c, inherited)
            elif n == "AlternateContent":
                choice = child(c, "Choice")
                if choice is not None:
                    walk(choice, inherited)

    walk(p, base_r)
    merged = []
    for r in runs:                                             # neighbours with the same look become one run
        if merged and "x" in r and "x" in merged[-1] and {k: v for k, v in r.items() if k != "x"} == {k: v for k, v in merged[-1].items() if k != "x"}:
            merged[-1] = {**merged[-1], "x": merged[-1]["x"] + r["x"]}
        else:
            merged.append(r)
    return merged


def _paragraph(ctx: Ctx, p, out: list, boxes_flag=False):
    pp = para_props(child(p, "pPr"))
    sid = pp.get("style")
    base_p = ctx.styles.merged(sid, "p")
    props = {**base_p, **{k: v for k, v in pp.items() if k != "style"}}
    base_r = {**ctx.styles.base_r, **ctx.styles.merged(sid, "r")}
    boxes = []
    runs = _runs(ctx, p, base_r, boxes)
    level = ctx.styles.level(sid)
    block = {"t": "p", "runs": runs}
    if level:
        block["h"] = level
    for k in ("al", "left", "hang", "first", "before", "after"):
        if k in props:
            block[k] = props[k]
    if props.get("num") and props["num"][0] not in (None, "0"):
        block["label"] = ctx.numbering.label(props["num"][0], props["num"][1])
        block["lvl"] = props["num"][1]
    if boxes_flag:
        block["box"] = 1
    page_break = any(r.get("br") == "page" for r in runs)
    runs[:] = [r for r in runs if r.get("br") != "page"]
    if runs or block.get("label") is not None or not page_break:
        out.append(block)
    if page_break:
        out.append({"t": "pagebreak"})
    out.extend(boxes)
    if len(out) > MAX_BLOCKS:
        raise _Stop()


def _table(ctx: Ctx, tbl, out: list):
    pr = child(tbl, "tblPr")
    borders = child(pr, "tblBorders")
    grid = borders is not None and any(at(b, "val", "none") not in ("none", "nil") for b in borders) or "grid" in (at(child(pr, "tblStyle"), "val") or "").lower()
    rows = []
    for tr in children(tbl, "tr"):
        cells = []
        for tc in children(tr, "tc"):
            tcpr = child(tc, "tcPr")
            span = at(child(tcpr, "gridSpan"), "val", "1")
            vm = child(tcpr, "vMerge")
            fill = at(child(tcpr, "shd"), "fill")
            blocks = []
            _body(ctx, tc, blocks)
            cells.append({"blocks": blocks, "span": int(span) if str(span).isdigit() else 1, "fill": fill.upper() if fill and HEX.fullmatch(fill) else None,
                          "cont": 1 if vm is not None and at(vm, "val") != "restart" else 0})
        rows.append(cells)
    out.append({"t": "table", "rows": rows, "grid": 1 if grid else 0})


def _body(ctx: Ctx, container, out: list, boxes_flag=False):
    for c in container:
        n = ln(c)
        if n == "p":
            _paragraph(ctx, c, out, boxes_flag)
        elif n == "tbl":
            _table(ctx, c, out)
        elif n == "sdt":
            content = child(c, "sdtContent")
            if content is not None:
                _body(ctx, content, out, boxes_flag)
        elif n in ("sdtContent", "customXml", "ins"):
            _body(ctx, c, out, boxes_flag)
        elif n == "AlternateContent":
            choice = child(c, "Choice")
            if choice is not None:
                _body(ctx, choice, out, boxes_flag)
        if len(out) > MAX_BLOCKS:
            raise _Stop()


def render(zf: zipfile.ZipFile) -> dict | None:
    """The document's blocks, or None when it cannot be read as a Word file."""
    rels = load(zf, "_rels/.rels")
    part = "word/document.xml"
    for r in children(rels, "Relationship") if rels is not None else []:
        if str(at(r, "Type", "")).endswith("/officeDocument"):
            t = at(r, "Target", "")
            part = t[1:] if t.startswith("/") else t
    root = load(zf, part)
    if root is None:
        return None
    body = child(root, "body")
    if body is None:
        return None
    ctx = Ctx(zf)
    blocks, cut = [], False
    try:
        _body(ctx, body, blocks)
    except _Stop:
        cut = True
    return {"mode": "doc", "blocks": blocks, "images": len(ctx.images), "truncated": cut}
