"""Smart search shared by the file list, Restore and the log.

What a person can type:
  report 2025        every word must match, in any order, anywhere in the path (case and accents are ignored)
  "tax return"       a quoted phrase must match exactly
  -backup            leave out anything that has this word
  .pdf  or ext:pdf   only that file type (ext:pdf,docx allows several)
  type:spreadsheet   a kind of file: documents, spreadsheets, presentations, images, videos, audio, archives, code,
                     programs and more (type:images,pdf mixes kinds and extensions)
  >10mb  <1gb  size>500kb   only files bigger or smaller than that
  level:error        for the log: info, warn or error
When nothing matches, the search is run again forgiving one or two typos (reprot finds report).
"""
import re
import unicodedata

_TOKEN = re.compile(r'-?"[^"]*"|\S+')
_SIZE = re.compile(r"^(?:size)?([<>]=?)(\d+(?:\.\d+)?)\s*(b|kb|mb|gb|tb|k|m|g|t)?$", re.I)
_UNIT = {"": 1, "b": 1, "k": 1e3, "kb": 1e3, "m": 1e6, "mb": 1e6, "g": 1e9, "gb": 1e9, "t": 1e12, "tb": 1e12}
_WORD = re.compile(r"[a-z0-9]+")

# Kinds of file and the words that name them. The icons in the app use the same lists (frontend/src/kinds.json; a test keeps
# the two copies identical), so a file that shows a blue "docx" icon is a "document" here.
KINDS = {
    "pdf": "pdf",
    "doc": "doc docx dot dotx odt rtf pages wps",
    "xls": "xls xlsx xlsm xlsb ods csv tsv numbers",
    "ppt": "ppt pptx pps ppsx odp key",
    "zip": "zip rar 7z tar gz tgz bz2 xz iso cab",
    "img": "jpg jpeg png gif bmp webp heic heif tif tiff svg raw cr2 nef arw dng ico psd ai",
    "vid": "mp4 mkv avi mov wmv flv webm m4v 3gp mpg mpeg",
    "aud": "mp3 wav flac aac ogg m4a wma opus mid",
    "code": "py js ts tsx jsx html htm css json xml sql php java cs cpp c h go rs rb sh bat ps1 yml yaml ini toml",
    "txt": "txt md log nfo",
    "exe": "exe msi dll apk",
    "ebook": "epub mobi azw3 djvu",
    "email": "pst eml msg mbox ics vcf",
    "design": "dwg dxf sketch fig xd indd odg",
    "db": "db sqlite mdb accdb mdf",
    "font": "ttf otf woff woff2",
}
KINDS = {k: v.split() for k, v in KINDS.items()}
# A word names one or more kinds. A bare extension (pdf, zip, doc, txt, exe) is never a word: it still means just that extension.
WORDS = {}
for _kinds, _words in (
    ("doc pdf txt", "document documents docs"), ("doc", "word"), ("xls", "spreadsheet spreadsheets sheet sheets excel"),
    ("ppt", "presentation presentations slide slides slideshow slideshows powerpoint"), ("zip", "archive archives compressed"),
    ("img", "image images picture pictures photo photos pic pics graphic graphics"), ("vid", "video videos movie movies film films"),
    ("aud", "audio music song songs sound sounds"), ("code", "code script scripts source"), ("txt", "text note notes"),
    ("exe", "program programs installer installers app apps executable executables"), ("ebook", "ebook ebooks book books"),
    ("email", "email emails mail"), ("design", "cad design designs"), ("db", "database databases"), ("font", "font fonts"),
):
    for _w in _words.split():
        WORDS[_w] = _kinds.split()


def expand_types(value):
    """The extensions a type: or ext: value stands for. Kind words (spreadsheet, images) expand to every extension of
    that kind; anything else is taken as an extension. Comma-separated values mix both."""
    out = set()
    for item in norm(value).split(","):
        item = item.strip(" .")
        if not item:
            continue
        for kind in WORDS.get(item, ()):
            out |= {"." + e for e in KINDS[kind]}
        if item not in WORDS:
            out.add("." + item)
    return out


def norm(s):
    """Lower case, no accents."""
    s = unicodedata.normalize("NFKD", str(s).lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _within(a, b, limit):
    """True if the edit distance between a and b is at most `limit` (small limits only, so this stays cheap)."""
    if abs(len(a) - len(b)) > limit:
        return False
    prev2, prev = None, list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            if prev2 is not None and i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                v = min(v, prev2[j - 2] + 1)                # two neighbouring letters swapped counts as one typo
            cur.append(v)
        if min(cur) > limit and (prev2 is None or min(prev) > limit):
            return False
        prev2, prev = prev, cur
    return prev[-1] <= limit


class Query:
    def __init__(self, text):
        self.terms, self.phrases, self.exclude, self.exts, self.fields = [], [], [], set(), {}
        self.min_size = self.max_size = None
        for tok in _TOKEN.findall(text or ""):
            neg = tok.startswith("-") and len(tok) > 1
            body = tok[1:] if neg else tok
            if body.startswith('"'):
                body = norm(body.strip('"')).strip()
                if body:
                    (self.exclude if neg else self.phrases).append(body)
                continue
            m = _SIZE.match(tok)
            if m:
                n = float(m.group(2)) * _UNIT[(m.group(3) or "").lower()]
                if m.group(1).startswith(">"):
                    self.min_size = n if self.min_size is None else max(self.min_size, n)
                else:
                    self.max_size = n if self.max_size is None else min(self.max_size, n)
                continue
            if ":" in body and not neg:
                k, _, v = body.partition(":")
                if k.lower() in ("ext", "type", "kind") and v:
                    self.exts |= expand_types(v)
                    continue
                if k.lower() in ("level", "action") and v:
                    self.fields[k.lower()] = norm(v)
                    continue
            if re.fullmatch(r"\.[a-z0-9]{1,8}", norm(body)) and not neg:
                self.exts.add(norm(body))
                continue
            w = norm(body)
            if w:
                (self.exclude if neg else self.terms).append(w)

    @property
    def empty(self):
        return not (self.terms or self.phrases or self.exclude or self.exts or self.fields or self.min_size is not None or self.max_size is not None)

    @property
    def can_fuzzy(self):
        return any(len(t) >= 4 for t in self.terms)

    def match(self, text, size=None, ext=None, fuzzy=False):
        """Does this text (and size and extension, for a file) fit the query?"""
        t = norm(text)
        if self.exts and (ext or "").lower() not in self.exts:
            return False
        if size is not None:
            if self.min_size is not None and size < self.min_size:
                return False
            if self.max_size is not None and size > self.max_size:
                return False
        if any(p not in t for p in self.phrases) or any(x in t for x in self.exclude):
            return False
        squashed = None
        words = None
        for w in self.terms:
            if w in t:
                continue
            if squashed is None:
                squashed = "".join(_WORD.findall(t))
            if w in squashed:                              # "taxreturn" finds "tax_return"
                continue
            if not (fuzzy and len(w) >= 4):
                return False
            if words is None:
                words = _WORD.findall(t)
            limit = 1 if len(w) <= 6 else 2
            if not any(_within(w, x, limit) or _within(w, x[:len(w)], limit) for x in words):
                return False
        return True
