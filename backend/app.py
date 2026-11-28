"""Ala Eh! File Backup: a local backup tool. No database; everything lives on disk.

State (settings, file index, history, logs) is stored as JSON files in BACKUP_DATA_DIR
(default: ~/.ala-eh-backup). Backups are plain copies (or .gz) on the destination drives.

Environment variables (all optional):
  BACKUP_DATA_DIR   where the tool keeps its own state          [~/.ala-eh-backup]
  BACKUP_PASSWORD   if set, the web UI asks for this password
  BACKUP_HOST       bind address                                [127.0.0.1]
  BACKUP_PORT       port                                        [5001]
  BACKUP_SHARE_HOST address 'Share this PC' listens on          [0.0.0.0, the local network only]
"""
import socket
from types import SimpleNamespace
import atexit, csv, fnmatch, gzip, hashlib, hmac, heapq, io, json, os, platform, re, secrets, shutil, string, sys, threading, time, urllib.request, uuid
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from pathlib import Path

import agent as agent_mod
import pki
import remote
import smartsearch
import drivecopies
import preview
import updater
from flask import Flask, Response, jsonify, request, send_file, send_from_directory

ON_VERCEL = bool(os.environ.get("VERCEL"))      # serverless: only /tmp is writable, and it is not persistent
DATA = Path(os.environ.get("BACKUP_DATA_DIR") or (Path("/tmp") / ".ala-eh-backup" if ON_VERCEL else Path.home() / ".ala-eh-backup"))
DATA.mkdir(parents=True, exist_ok=True)
if getattr(sys, "frozen", False):                # packaged desktop build: PyInstaller unpacks the UI next to the exe
    DIST = Path(sys._MEIPASS) / "frontend_dist"
else:
    DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
PASSWORD = os.environ.get("BACKUP_PASSWORD", "")
BIND_HOST = os.environ.get("BACKUP_HOST", "127.0.0.1")
FLUSH_LOCK = threading.Lock()
LOCK = threading.RLock()
app = Flask(__name__, static_folder=str(DIST), static_url_path="")

# ---------------------------------------------------------------- storage

def read_json(name, default):
    for n in (name, name + ".bak"):          # a torn or missing file falls back to the last good copy
        try:
            return json.loads((DATA / n).read_text("utf8"))
        except (OSError, ValueError):
            continue
    return default


def write_json(name, obj):
    with FLUSH_LOCK:
        tmp = DATA / (name + ".tmp")
        tmp.write_text(json.dumps(obj, separators=(",", ":")), "utf8")
        os.replace(tmp, DATA / name)


DEFAULTS = {
    "sources": [str(Path.home() / "Documents")],
    "destinations": [str(Path.home() / "Backups")],
    "excludes": [],
    "whole_pc": True,
    "skip_junk": True,
    "new_files": "review",
    "max_size_mb": 0,
    "versions": 0,          # no older copies: a changed file simply replaces its backup
    "keep_versions": 0,     # older copies of a changed file to keep on the drive (0 = the new copy replaces the old one)
    "alert_low_space_pct": 10,   # warn when a backup drive has less than this percent free (0 = off)
    "alert_stale_days": 7,       # warn when nothing was backed up for this many days (0 = off)
    "compress": False,
    "schedule": {"enabled": False, "time": "22:00", "days": [0, 1, 2, 3, 4, 5, 6]},
    "auto_scan_minutes": 0,
    "webhook": "",
    "remote_sources": [],   # folders of other paired PCs to back up: [{"pc": id, "root": label}]
    "deep_check": False,    # also compare contents of files whose size and date did not change (slower)
    "update_check": True,   # installed app: look for a newer release on GitHub
    "reuse_drive_copies": True,   # a file another PC already stored on the shared drive is linked, not written again
}
SETTINGS = {**DEFAULTS, **read_json("settings.json", {})}
SETTINGS["versions"] = 0           # an older setting of 3 is ignored: the new copy replaces the old one
INDEX = read_json("index.json", {})
GONE = read_json("gone.json", {})        # files deleted from the PC that still have a backup copy, so they can be restored       # id -> file record
META = read_json("meta.json", {})
HISTORY = read_json("history.json", [])
_dirty = False

# Built-in rules for system and junk files. A leading "/" anchors a rule to the top of a scanned folder or
# drive (so "/Windows" skips the Windows folder of a drive but not Documents/Windows); other rules match a
# file or folder name anywhere.
JUNK = [
    "/Windows", "/Windows.old", "/Program Files", "/Program Files (x86)", "/ProgramData", "/Recovery",
    "/$Recycle.Bin", "/System Volume Information", "/$WinREAgent", "/MSOCache", "/PerfLogs", "/Config.Msi",
    "/Users/Default", "/Users/All Users", "/Users/Public", "/Users/Default User", "/Documents and Settings",
    "node_modules", ".git", ".svn", "__pycache__", ".venv", "venv", ".cache", ".gradle", ".m2", ".npm",
    ".nuget", "AppData", "Temp", "tmp", "Cache", "Caches", "$RECYCLE.BIN",
    "*.tmp", "*.temp", "*.part", "*.crdownload", "~$*", "Thumbs.db", "desktop.ini", ".DS_Store",
    "pagefile.sys", "hiberfil.sys", "swapfile.sys", "ntuser.dat*", "*.pyc",
]


def _load_pc():
    pc = read_json("pc.json", {})
    fresh = not pc.get("id")
    if fresh:
        pc = {"id": uuid.uuid4().hex}
    pc["name"] = pc.get("name") or platform.node() or "PC"
    if "named" not in pc:
        pc["named"] = not fresh            # a PC that was in use before the app asked for a name keeps its name and is not asked
    write_json("pc.json", pc)
    return pc


PC = _load_pc()
PC_NAME = re.sub(r'[<>:"/\\|?*\s]+', "_", PC["name"]).strip("._") or "PC"
_PCF = {}


VER = [0]                  # bumped on every change to the file list; cached answers are tied to it
_first_dirty = [0.0]
_last_mark = [0.0]


def mark():
    global _dirty
    if not _dirty:
        _first_dirty[0] = time.time()
    _dirty = True
    _last_mark[0] = time.time()
    VER[0] += 1


def flush():
    """Write the file list to disk. The lock is held only to take a copy, never while writing."""
    global _dirty
    with LOCK:
        if not _dirty:
            return
        _dirty = False
        items = list(INDEX.items())
    try:
        snap = json.dumps(dict(items), separators=(",", ":"))
        with FLUSH_LOCK:
            tmp = DATA / "index.json.tmp"
            tmp.write_text(snap, "utf8")
            cur = DATA / "index.json"
            if cur.exists():
                os.replace(cur, DATA / "index.json.bak")
            os.replace(tmp, cur)
    except RuntimeError:       # a record changed while it was being written; try again on the next round
        _dirty = True
    except OSError:            # disk full or a file held by another program: keep the flag so it is retried
        _dirty = True
        raise


def saver():
    while True:
        time.sleep(1)
        now = time.time()
        # wait until changes calm down (a burst of clicks or a running backup is saved once), but never too long
        if _dirty and (now - _last_mark[0] >= 3 or now - _first_dirty[0] >= 30):
            try:
                flush()
            except OSError:
                pass


_MEMO = {"ver": -1, "d": {}}


def memo(key, fn):
    """Cache an answer that only depends on the file list, until the next change to it."""
    with LOCK:
        if _MEMO["ver"] != VER[0] or len(_MEMO["d"]) > 300:
            _MEMO["ver"], _MEMO["d"] = VER[0], {}
        ver, hit = VER[0], _MEMO["d"].get(key)
    if hit is not None:
        return hit
    val = fn()
    with LOCK:
        if _MEMO["ver"] == ver:
            _MEMO["d"][key] = val
    return val


atexit.register(flush)


def log(level, action, message):
    line = json.dumps({"at": datetime.now().isoformat(sep=" ", timespec="seconds"),
                       "level": level, "action": action, "message": message})
    with LOCK:
        f = DATA / "logs.jsonl"
        if f.exists() and f.stat().st_size > 5_000_000:
            os.replace(f, DATA / "logs.1.jsonl")
        with open(f, "a", encoding="utf8") as fh:
            fh.write(line + "\n")


def read_logs(level="", q="", limit=300):
    out = []
    try:
        lines = (DATA / "logs.jsonl").read_text("utf8").splitlines()
    except OSError:
        return out
    sq = smartsearch.Query(q)
    for fuzzy in (False, True):                            # a second pass forgives typos, only if the first found nothing
        if fuzzy and (out or not sq.can_fuzzy):
            break
        for ln in reversed(lines):
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if level and r["level"] != level:
                continue
            if sq.fields.get("level") and r["level"] != sq.fields["level"].replace("warning", "warn"):
                continue
            if sq.fields.get("action") and sq.fields["action"] not in r["action"].lower():
                continue
            if not sq.empty and not sq.match(r["action"] + " " + r["message"], fuzzy=fuzzy):
                continue
            out.append(r)
            if len(out) >= limit:
                break
    return out


def fmt(n):
    n = float(n or 0)
    for unit, size in (("GB", 1e9), ("MB", 1e6), ("KB", 1e3)):
        if n >= size:
            return f"{n / size:.2f} {unit}"
    return f"{int(n)} B"


# ---------------------------------------------------------------- helpers

def fid_of(path):
    return hashlib.sha1(path.encode("utf8", "surrogatepass")).hexdigest()[:12]


def sources():
    """Folders to scan: every internal drive in whole-PC mode, otherwise the folders chosen in Settings."""
    return fixed_drives() if SETTINGS.get("whole_pc", True) else SETTINGS["sources"]


# ---------------------------------------------------------------- backup drive identity

def volume_info(path):
    """(name, serial) of the drive that holds `path`, or None. The serial stays the same if Windows changes the letter."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        root = os.path.splitdrive(os.path.abspath(path))[0] + "\\"
        name, serial = ctypes.create_unicode_buffer(261), ctypes.c_uint32()
        ok = ctypes.windll.kernel32.GetVolumeInformationW(root, name, 261, ctypes.byref(serial), None, None, None, 0)
        return (name.value, f"{serial.value:08X}") if ok else None
    except Exception:
        return None


_RESOLVED = [0.0]


def refresh_destinations(force=False):
    """Follow a backup drive that Windows gave another letter. A different drive on the old letter is never used."""
    if os.name != "nt" or (not force and time.time() - _RESOLVED[0] < 5):
        return
    _RESOLVED[0] = time.time()
    vols = SETTINGS.setdefault("dest_vols", {})
    changed, moved = False, {}
    for d in list(SETTINGS["destinations"]):
        info, saved = volume_info(d), vols.get(d)
        if saved is None:
            if info:
                vols[d], changed = info[1], True      # first time seen: remember which drive this is
            continue
        if info and info[1] == saved:
            continue
        for c in string.ascii_uppercase:              # gone, or another drive on that letter: look for the saved one
            r = f"{c}:\\"
            i2 = volume_info(r) if os.path.exists(r) else None
            if i2 and i2[1] == saved:
                moved[d] = os.path.normpath(r + os.path.splitdrive(d)[1].lstrip("\\/"))
                break
    if moved:
        with LOCK:
            SETTINGS["destinations"] = [moved.get(d, d) for d in SETTINGS["destinations"]]
            for old, new in moved.items():
                vols[new] = vols.pop(old)
                for f in list(INDEX.values()) + list(GONE.values()):
                    if old in f.get("backed", {}):
                        f["backed"][new] = f["backed"].pop(old)
            _PCF.clear()
            mark()
        for old, new in moved.items():
            log("info", "drive", f"The backup drive {old} is now {new}. Using {new}.")
        changed = True
    if changed:
        write_json("settings.json", SETTINGS)


# ---------------------------------------------------------------- file types and presets

CATEGORIES = {
    "documents": ("Documents", "doc docx txt rtf odt md pdf pages wpd"),
    "spreadsheets": ("Spreadsheets", "xls xlsx xlsm xlsb csv ods numbers"),
    "presentations": ("Presentations", "ppt pptx pps ppsx odp key"),
    "email": ("Email", "pst eml msg mbox"),
    "pictures": ("Pictures", "jpg jpeg png gif bmp tif tiff webp heic heif raw cr2 nef arw svg"),
    "design": ("Design and CAD", "psd ai indd dwg dxf sketch fig xd"),
    "videos": ("Videos", "mp4 mov avi mkv wmv flv webm m4v mpg mpeg"),
    "music": ("Music", "mp3 wav flac aac m4a ogg wma"),
    "databases": ("Databases and backups", "mdb accdb sql sqlite db bak mdf"),
    "archives": ("Archives", "zip rar 7z tar gz bz2 xz"),
    "installers": ("Installers and disk images", "exe msi msix iso dmg apk"),
    "other": ("Other", ""),
}
TYPE_EXT = {"." + e: k for k, (_, exts) in CATEGORIES.items() for e in exts.split()}
OFFICE_CATS = {"documents", "spreadsheets", "presentations", "email"}
PRESETS = {
    "office": {"label": "Office PC",
               "desc": "Desktop, Documents and Pictures folders, plus Word, Excel, PowerPoint, PDF and email files anywhere.",
               "folders": {"desktop", "documents", "pictures", "my documents", "my pictures"}, "cats": OFFICE_CATS},
    "documents": {"label": "Documents only",
                  "desc": "Only Word, Excel, PowerPoint, PDF and email files, and the Desktop and Documents folders.",
                  "folders": {"desktop", "documents", "my documents"}, "cats": OFFICE_CATS},
    "everything": {"label": "Everything",
                   "desc": "Every file that is not system or junk.", "all": True},
}


def cat_of(path):
    return TYPE_EXT.get(os.path.splitext(path)[1].lower(), "other")


# How much a file probably matters to its owner, worked out from what the PC already knows about it. It decides which new
# files are suggested first and which are copied first. Nothing here reads a file's content.
_KIND_POINTS = {"documents": 25, "spreadsheets": 25, "presentations": 22, "design": 22, "email": 20, "databases": 18,
                "pictures": 15, "videos": 8, "music": 5, "archives": 3, "installers": -10, "other": 0}
_PLACES = (("documents", 15, "In Documents"), ("desktop", 15, "On the Desktop"), ("pictures", 10, "In Pictures"),
           ("onedrive", 10, "In OneDrive"), ("downloads", 3, ""))


def importance(f, now=None):
    """(score, reason): recently used files of the kinds people keep, in the places people keep them, score highest."""
    now = now or time.time()
    mt, at = f.get("mtime") or 0, f.get("atime") or 0
    used = max(mt, at) if at - mt > 3600 else mt                    # an open that is later than the last edit counts too
    days = max(0.0, (now - used) / 86400)
    pts = 50 if days < 1 else 42 if days < 7 else 32 if days < 30 else 20 if days < 90 else 8 if days < 365 else 0
    verb = "Opened" if used != mt else "Edited"
    when = ("today" if days < 1 else "this week" if days < 7 else "this month" if days < 30 else "in the last 3 months" if days < 90
            else "this year" if days < 365 else "")
    kind = cat_of(f["path"])
    pts += _KIND_POINTS.get(kind, 0)
    low = f["path"].lower().replace("\\", "/")
    place = ""
    for key, p_, text in _PLACES:
        if f"/{key}/" in low:
            pts += p_
            place = text
            break
    size = f.get("size") or 0
    if size > 2e9:
        pts -= 10
    elif size < 1024:
        pts -= 5
    bits = [f"{verb} {when}" if when else "", CATEGORIES[kind][0] if kind != "other" else "", place]
    return pts, ", ".join(b for b in bits if b)


def preset_wants(preset, f):
    if preset.get("all"):
        return True
    if cat_of(f["path"]) in preset["cats"]:
        return True
    parts = {x.lower() for x in Path(f["path"]).parts[:-1]}
    return bool(parts & preset["folders"])


RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}


def labels(srcs=None):
    """A folder name on the backup drive for each scanned folder. Never '.', '..' or a Windows device name."""
    out, used = {}, set()
    for s in (srcs if srcs is not None else sources()):
        base = Path(s).name or s.replace(":", "").strip("\\/") or "root"
        base = re.sub(r'[<>:"/\\|?*]', "_", base).strip(" .") or "root"
        if base.upper() in RESERVED:
            base = "_" + base
        name, n = base, 2
        while name.lower() in used:
            name, n = f"{base}_{n}", n + 1
        used.add(name.lower())
        out[s] = name
    return out


def status(f, ds):
    b = f.get("backed") or {}
    if not any(d in b for d in ds):
        return "new"
    ok = all(d in b and b[d]["size"] == f["size"] and b[d]["mtime"] == f["mtime"] for d in ds)
    return "backed_up" if ok else "modified"


def is_pending(f, ds):
    return bool(f["selected"]) and not f.get("stale") and status(f, ds) != "backed_up"


def hash_stream(fh):
    h = hashlib.sha256()
    for chunk in iter(lambda: fh.read(1 << 20), b""):
        h.update(chunk)
    return h.hexdigest()


def hash_file(path, gz=False):
    with (gzip.open(path, "rb") if gz else open(path, "rb")) as fh:
        return hash_stream(fh)


def existing_ancestor(p):
    p = Path(p)
    while not p.exists():
        if p.parent == p:
            return None
        p = p.parent
    return p


def disk(path):
    a = existing_ancestor(path)
    if a is None:
        return None
    try:
        u = shutil.disk_usage(a)
        return {"free": u.free, "total": u.total}
    except OSError:
        return None


def read_json_at(path):
    try:
        return json.loads(Path(path).read_text("utf8"))
    except (OSError, ValueError):
        return None


def _folder_name(name):
    base = re.sub(r'[<>:"/\\|?*\s]+', "_", str(name)).strip("._") or "PC"
    return "_" + base if base.split(".")[0].upper() in RESERVED else base


def write_json_at(path, obj):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1), "utf8")
    os.replace(tmp, path)


def folder_for(dest, pid, name, user="", create=False):
    """The folder on `dest` that belongs to the PC with this id. One PC has exactly one folder on a drive, whichever PC
    wrote into it: the pc-id.json inside says whose it is, so a PC is found again even if it was renamed, and two PCs
    with the same name never share a folder."""
    pid = str(pid)
    key = dest if pid == PC["id"] else (dest, pid)
    hit = _PCF.get(key)
    if isinstance(hit, str):
        return hit
    if isinstance(hit, tuple) and not create:
        return hit[0]                                 # a folder that does not exist yet: remembered so a scan does not look again
    try:
        kids = [e for e in os.scandir(dest) if not e.name.startswith(".")]
    except OSError:
        kids = []
    for e in kids:
        try:
            if not e.is_dir(follow_symlinks=False):
                continue
        except OSError:
            continue
        idf = Path(e.path) / "pc-id.json"
        data = read_json_at(idf)
        if isinstance(data, dict) and data.get("id") == pid:
            if create and (data.get("name") != str(name) or (user and data.get("user") != user)):
                data["name"] = str(name)
                if user:
                    data["user"] = user
                try:
                    write_json_at(idf, data)           # keep the name current if the PC was renamed
                except OSError:
                    pass
            _PCF[key] = e.name
            return e.name
    base = _folder_name(name)
    for cand in (base, f"{base}-{pid[:6]}"):
        idf = Path(dest) / cand / "pc-id.json"
        if idf.exists():
            continue                                  # another PC's folder
        if not create:
            _PCF[key] = (cand,)
            return cand
        idf.parent.mkdir(parents=True, exist_ok=True)
        write_json_at(idf, {"id": pid, "name": str(name), "user": user,
                            "first_backup": datetime.now().isoformat(timespec="seconds")})
        _PCF[key] = cand
        return cand
    raise RuntimeError(f"Folder name clash for {name} on {dest}")


def pc_folder(dest, create=False):
    """Folder name for this PC on `dest`."""
    return folder_for(dest, PC["id"], PC["name"], os.environ.get("USERNAME", ""), create)


MAX_PC_NAME = 40


def clean_pc_name(raw):
    """The name the person typed, tidied (one space between words), or a ValueError that says what to fix."""
    name = re.sub(r"\s+", " ", str(raw or "")).strip()
    if not name:
        raise ValueError("Type a name for this PC.")
    if len(name) > MAX_PC_NAME:
        raise ValueError(f"Use {MAX_PC_NAME} characters or fewer.")
    if any(ord(c) < 32 for c in name) or not re.search(r"\w", name):
        raise ValueError("Use letters or numbers in the name.")
    return name


def existing_folder(dest, pid):
    """The name of the folder on `dest` that belongs to the PC with this id, or None when it has none there yet."""
    try:
        kids = [e for e in os.scandir(dest) if not e.name.startswith(".")]
    except OSError:
        return None
    for e in kids:
        try:
            if e.is_dir(follow_symlinks=False):
                data = read_json_at(Path(e.path) / "pc-id.json")
                if isinstance(data, dict) and data.get("id") == pid:
                    return e.name
        except OSError:
            continue
    return None


def folder_taken(dest, name):
    """True when a folder for `name` already exists on `dest` and it is not this PC's own."""
    own = existing_folder(dest, PC["id"])
    want = _folder_name(name).lower()
    try:                                               # compared without case: Windows drives treat Sales and sales as one folder
        names = {e.name.lower() for e in os.scandir(dest)}
    except OSError:
        return False
    return want in names and (own is None or want != own.lower())


def sync_folder_names(ds=None):
    """Make this PC's folder on each connected drive carry the PC's current name. A drive that is not plugged in, or a
    folder Windows has open, is left as it is and tried again at the start of the next backup: the folder is found by
    the id inside it, so a backup never depends on the name. Another PC's folder is never touched.
    Returns (renamed, pending): the drives that now match, and the drives still using the old folder name."""
    renamed, pending = [], []
    for d in (SETTINGS["destinations"] if ds is None else ds):
        if not os.path.isdir(d):
            pending.append(d)
            continue
        cur = existing_folder(d, PC["id"])
        if cur is None:
            continue                                   # nothing of this PC there yet: its folder starts with the new name
        want = _folder_name(PC["name"])
        picked = next((c for c in (want, f"{want}-{PC['id'][:6]}")
                       if c.lower() == cur.lower() or not (Path(d) / c).exists()), None)
        try:
            if picked is None:
                raise OSError("a folder with that name is already on the drive")
            if picked != cur:
                os.rename(Path(d) / cur, Path(d) / picked)
                old_v, new_v = Path(d) / ".versions" / cur, Path(d) / ".versions" / picked
                if old_v.is_dir() and not new_v.exists():
                    os.rename(old_v, new_v)
            idf = Path(d) / picked / "pc-id.json"
            data = read_json_at(idf)
            if isinstance(data, dict) and data.get("name") != PC["name"]:
                data["name"] = PC["name"]
                write_json_at(idf, data)
            renamed.append(d)
        except OSError as e:
            log("warn", "settings", f"Could not rename this PC's folder on {d} to {picked or want}: {e}. It keeps working under its old name.")
            pending.append(d)
    _PCF.clear()
    return renamed, pending


def peer_folder(dest, r, create=False):
    """Folder on `dest` for another PC that this PC backs up over the network (`r` is the file's `remote` record). It is
    that PC's own folder, the same one it uses when it backs itself up, so its files are one backup however it is made."""
    pid = str(r["pc"])
    return folder_for(dest, pid, (PEERS.get(pid) or {}).get("name") or r.get("name") or pid[:6], "", create)


def is_legacy_remote(f):
    """Versions 1.3 to 1.5 filed another PC's files under this PC's folder: Remote PCs / name (id) / folder."""
    return bool(f.get("remote")) and len(Path(f["label"]).parts) >= 3 and Path(f["label"]).parts[0] == "Remote PCs"


def folder_of(dest, f, create=False):
    """The PC folder a file is stored in: its own PC's folder, wherever the backup is made from."""
    r = f.get("remote")
    if r and not is_legacy_remote(f):
        return peer_folder(dest, r, create)
    return pc_folder(dest, create)


def target_of(dest, f, gz, create=False):
    p = Path(dest) / folder_of(dest, f, create) / f["label"] / f["rel"]
    return p.with_name(p.name + ".gz") if gz else p


def foreign_folder(dest, f):
    """True when the file belongs to another PC, so this PC is writing into that PC's folder."""
    return bool(f.get("remote")) and not is_legacy_remote(f)


_TOUCHED = {}


def stamp_folder(dest, f):
    """Record on the drive that this PC backed up another PC's folder: when, and by whom. The first time in a run it
    also marks the folder as written by someone else, which makes that PC look at it when it checks for stored copies."""
    if not foreign_folder(dest, f):
        return
    folder = folder_of(dest, f)
    key = (dest, folder)
    if key in _TOUCHED:
        return
    _TOUCHED[key] = True
    idf = Path(dest) / folder / "pc-id.json"
    data = read_json_at(idf)
    if not isinstance(data, dict):
        return
    by = [x for x in data.get("backed_up_by", []) if isinstance(x, str)]
    if PC["name"] not in by:
        by.append(PC["name"])
    data["backed_up_by"] = by
    data["last_backup"] = datetime.now().isoformat(sep=" ", timespec="seconds")
    try:
        write_json_at(idf, data)
    except OSError:
        pass


def written_by_others(dest):
    """True when another PC has also been writing into this PC's folder on `dest`."""
    try:
        data = read_json_at(Path(dest) / pc_folder(dest) / "pc-id.json")
    except RuntimeError:
        return False
    return bool(isinstance(data, dict) and data.get("backed_up_by"))


def make_catalog(dest):
    """What other PCs stored on `dest`. This PC's own folder counts too once another PC has written into it."""
    return drivecopies.Catalog(dest, pc_folder(dest), check_cancel, include_own=written_by_others(dest))


def already_stored(dest, f, h):
    """The copy that is already at this file's place on `dest` has exactly this content: it was put there earlier,
    by this PC or by another PC that backed this PC up. Nothing needs writing; the app just records it."""
    p, gz = find_backup(dest, f)
    if p is None:
        return False
    try:
        if (drivecopies._gz_size(str(p)) if gz else p.stat().st_size) != (f["size"] & 0xFFFFFFFF if gz else f["size"]):
            return False
    except OSError:
        return False
    return drivecopies._hash(str(p), gz) == h


def find_backup(dest, f):
    """Return (path, is_gz) of the copy on `dest`, or (None, False)."""
    for gz in (SETTINGS["compress"], not SETTINGS["compress"]):
        p = target_of(dest, f, gz)
        if p.exists():
            return p, gz
    return None, False


TS = re.compile(r"\d{8}-\d{6}")


def vdir(dest, f):
    return Path(dest) / ".versions" / folder_of(dest, f) / f["label"] / Path(f["rel"]).parent


def version_files(dest, f):
    vd = vdir(dest, f)
    base = Path(f["rel"]).name
    out = []
    if vd.is_dir():
        for e in vd.iterdir():
            for name in (base, base + ".gz"):
                if e.name.startswith(name + ".") and TS.fullmatch(e.name[len(name) + 1:]):
                    out.append((e, e.name[len(name) + 1:], name != base))
    return sorted(out, key=lambda x: x[1], reverse=True)


def archive_version(dest, f, tgt, keep):
    vd = vdir(dest, f)
    vd.mkdir(parents=True, exist_ok=True)
    ts = datetime.fromtimestamp(tgt.stat().st_mtime).strftime("%Y%m%d-%H%M%S")
    os.replace(tgt, vd / f"{tgt.name}.{ts}")
    mine = sorted((e for e in vd.iterdir()
                   if e.name.startswith(tgt.name + ".") and TS.fullmatch(e.name[len(tgt.name) + 1:])),
                  key=lambda e: e.name, reverse=True)
    for e in mine[keep:]:
        e.unlink(missing_ok=True)


def excluded(name, rel, pats):
    rel = rel.replace(os.sep, "/").lower()
    name = name.lower()
    for p in pats:
        p = p.lower()
        if p.startswith("/"):
            a = p[1:]
            if rel == a or rel.startswith(a + "/"):
                return True
        elif fnmatch.fnmatchcase(name, p) or fnmatch.fnmatchcase(rel, p):
            return True
    return False


def compile_rules(pats):
    """Turn the skip rules into fast lookups, so checking a file costs a few set and regex tests."""
    names, rel_exact, anchored, wild, rel_wild = set(), set(), set(), [], []
    for p in pats:
        p = p.strip().lower()
        if not p:
            continue
        if p.startswith("/"):
            anchored.add(p[1:].rstrip("/"))
            continue
        w = any(c in p for c in "*?[")
        if "/" in p:
            if w:
                rel_wild.append(fnmatch.translate(p))
            else:
                rel_exact.add(p)
        elif w:
            wild.append(fnmatch.translate(p))
        else:
            names.add(p)
    wre = re.compile("|".join(wild)) if wild else None
    rre = re.compile("|".join(rel_wild)) if rel_wild else None

    def match(name_l, rel_l):
        return (name_l in names or rel_l in anchored or rel_l in rel_exact
                or (wre is not None and wre.match(name_l) is not None)
                or (rre is not None and rre.match(rel_l) is not None))
    return match


def rules():
    return list(SETTINGS["excludes"]) + (JUNK if SETTINGS.get("skip_junk", True) else [])


# ---------------------------------------------------------------- other PCs (wireless backup)

AGENT = agent_mod.Agent(lambda: DATA / "agent", lambda: PC["name"], lambda: PC["id"], compile_rules)     # this PC as a shared PC (off by default)
PEERS = remote.PeerStore(lambda: DATA / "agent" / "peers.json")                                          # the PCs this PC can back up


def safe_name(s):
    return re.sub(r'[<>:"/\\|?*]', "_", str(s)).strip(" .") or "PC"


def clean_remote_rel(rel):
    """A file path sent by another PC, checked before it is ever used to build a path on this PC's drive. Returns the
    path or None. A PC that is paired but misbehaving must not be able to write outside its own backup folder."""
    if not isinstance(rel, str) or not rel or len(rel) > 1000 or "\\" in rel or "\x00" in rel:
        return None
    for part in rel.split("/"):
        if (part in ("", ".", "..") or ":" in part or part != part.strip(" ") or part.endswith(".") or any(ord(c) < 32 for c in part)
                or part.split(".")[0].upper() in RESERVED):
            return None
    return rel


def peer_tag(peer):
    """A PC's name plus a short piece of its unique id, so two PCs that share a name can never share a folder or a file id."""
    return f"{safe_name(peer['name'])} ({safe_name(str(peer['id']))[:6]})"


def remote_key(peer, root):
    """How a folder of another PC is shown in the file list: Other PCs / name (id) / folder. A plain relative path, so every
    path function treats it like any other (a share-style \\\\name\\folder is mangled by Windows' own path code)."""
    return os.path.join("Other PCs", peer_tag(peer), safe_name(root))


def remote_label(root):
    """The folder name for a shared folder of another PC inside that PC's own folder on the drive. It follows the same
    rule as a local folder's name, so a folder backed up from either PC lands in the same place."""
    name = safe_name(root)
    return "_" + name if name.upper() in RESERVED else name


def old_remote_key(peer, root):
    """The share-style form versions 1.3.0 and 1.3.1 wrote, kept only to carry their lists over."""
    return os.sep * 2 + peer_tag(peer) + os.sep + safe_name(root)


def remote_keys():
    out = []
    for rs in SETTINGS.get("remote_sources", []):
        peer = PEERS.get(rs.get("pc", ""))
        if peer:
            out.append(remote_key(peer, rs["root"]))
    return out


def all_sources():
    return list(sources()) + remote_keys()


def rclient(pc_id):
    peer = PEERS.get(pc_id)
    if not peer:
        raise RuntimeError("That PC is no longer paired with this one.")
    return remote.RemoteClient(peer, AGENT.identity(), PEERS)


def src_stat(f):
    r = f.get("remote")
    if r:
        size, mtime = rclient(r["pc"]).stat(r["root"], r["rel"])
        return SimpleNamespace(st_size=size, st_mtime=mtime)
    return os.stat(f["path"])


def src_open(f):
    r = f.get("remote")
    return rclient(r["pc"]).open(r["root"], r["rel"]) if r else open(f["path"], "rb")


def src_hash(f):
    r = f.get("remote")           # the other PC reads its own disk: nothing is sent just to be hashed
    return rclient(r["pc"]).hash(r["root"], r["rel"]) if r else hash_file(f["path"])


# ---------------------------------------------------------------- jobs

class Cancelled(Exception):
    pass


JOB = {"state": "idle", "type": "", "message": "", "done": 0, "total": 0, "started": None, "finished": None}
CANCEL = threading.Event()


def job_set(**kw):
    with LOCK:
        JOB.update(kw)


def check_cancel():
    if CANCEL.is_set():
        raise Cancelled()


def notify(text):
    url = SETTINGS.get("webhook", "")
    if not url:
        return True, ""
    try:
        req = urllib.request.Request(url, data=json.dumps({"text": text, "content": text}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=10).read()
        return True, ""
    except Exception as e:
        log("warn", "notify", f"Notification failed: {e}")
        return False, str(e)


def start_job(kind, fn, *args):
    with LOCK:
        if JOB["state"] == "running":
            return False
        CANCEL.clear()
        JOB.update(state="running", type=kind, message="Starting...", done=0, total=0,
                   started=time.time(), finished=None)

    def run():
        res, state = None, "done"
        try:
            res = fn(*args)
        except Cancelled:
            state, res = "cancelled", "Cancelled"
            log("warn", kind, f"{kind.capitalize()} cancelled")
        except Exception as e:
            state, res = "error", str(e)
            log("error", kind, f"{kind.capitalize()} failed: {e}")
            if kind == "backup":
                notify(f"Backup failed: {e}")
        try:
            flush()
        except OSError as e:
            log("warn", "save", f"Could not save the file list yet: {e}")
        job_set(state=state, message=res or JOB["message"], finished=time.time())

    threading.Thread(target=run, daemon=True).start()
    return True


def scan_summary():
    """One sentence on where things stand after a scan, so it is clear whether anything is left to do."""
    ds = SETTINGS["destinations"]
    with LOCK:
        fl = list(INDEX.values())
    pend = [f for f in fl if is_pending(f, ds)]
    away = sum(1 for f in fl if f.get("stale") and f["selected"] and status(f, ds) != "backed_up")
    review = sum(1 for f in fl if not f.get("reviewed", True))
    chosen = sum(1 for f in fl if f["selected"])
    more = f" {review:,} new files are waiting for your review." if review else ""
    gone = f" {away:,} chosen files are on a PC that cannot be reached right now." if away else ""
    if pend:
        return f"{len(pend):,} files ({fmt(sum(f['size'] for f in pend))}) are waiting to back up." + gone + more
    if chosen:
        if away:
            return (gone + more).strip()
        return ("Everything chosen is backed up." + more) if review else "Everything is backed up. Nothing new or changed."
    return more.strip() or "Nothing is chosen for backup yet."


def _dir_key(path):
    return os.path.normcase(str(path).rstrip("\\/")) + os.sep


def skipped_dirs():
    """Folders the user skipped as a whole. Files that appear inside them later stay skipped."""
    return tuple(_dir_key(p) for p in META.get("skipped_dirs", []))


def in_skipped(path, rules_):
    return bool(rules_) and os.path.normcase(path).startswith(rules_)


def set_dir_rule(prefix, skip):
    """Remember a whole-folder choice. Backing a folder up again lifts the rule for it and every folder inside it."""
    key = _dir_key(prefix)
    cur = [p for p in META.get("skipped_dirs", []) if not _dir_key(p).startswith(key)]
    if skip and not any(key.startswith(_dir_key(p)) for p in cur):
        cur.append(str(prefix).rstrip("\\/"))
    META["skipped_dirs"] = cur
    write_json("meta.json", META)


def scan_job():
    match = compile_rules(rules())
    skip_rules = skipped_dirs()
    maxb = int(SETTINGS["max_size_mb"]) * 1048576
    skipdirs = {os.path.normcase(os.path.abspath(d)) for d in SETTINGS["destinations"]}
    srcs = sources()
    if not srcs and not SETTINGS.get("remote_sources"):
        raise RuntimeError("No folders are set to be scanned. Turn on 'Scan the whole PC' or add a folder in Settings.")
    lab = labels(srcs)
    auto = SETTINGS.get("new_files") == "include"
    expected = int(META.get("last_scan_count") or len(INDEX) or 0)   # the last scan's size drives the progress estimate
    job_set(total=expected, done=0, message="Scanning...")
    new, keep_src, count, failed = {}, set(), 0, []
    sep = os.sep
    for src in srcs:
        root = Path(src)
        nsrc = os.path.normcase(os.path.abspath(src))
        if any(nsrc == d or nsrc.startswith(d.rstrip(os.sep) + os.sep) for d in skipdirs):
            log("warn", "scan", f"Skipped {src}: it is the backup drive or a folder inside it. Choose a folder outside the backup location.")
            continue                      # the backup drive, or a folder inside it, is never scanned
        if not root.is_dir():
            log("warn", "scan", f"Source not found, keeping its old list: {src}")
            keep_src.add(src)
            continue
        label = lab.get(src) or "root"
        stack = [(str(root), "")]
        while stack:
            check_cancel()
            dp, reld = stack.pop()
            try:
                it = os.scandir(dp)
            except OSError:
                failed.append(os.path.normcase(dp))     # could not be listed: its old records are kept below
                continue
            with it:
                for e in it:
                    name = e.name
                    rel = reld + sep + name if reld else name
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if getattr(e, "is_junction", lambda: False)() or match(name.lower(), rel.replace(sep, "/").lower()):
                                continue
                            if skipdirs and os.path.normcase(os.path.abspath(e.path)) in skipdirs:
                                continue
                            stack.append((e.path, rel))
                            continue
                        if match(name.lower(), rel.replace(sep, "/").lower()):
                            continue
                        if e.is_symlink():
                            continue                   # a link could pull another file's content into the backup
                        st = e.stat()          # on Windows the size and date come with the folder listing: no extra call
                    except OSError:
                        continue
                    if maxb and st.st_size > maxb:
                        continue
                    p = e.path
                    i = fid_of(p)
                    while i in new and new[i]["path"] != p:        # two paths with the same short id
                        i = hashlib.sha1((i + p).encode("utf8", "surrogatepass")).hexdigest()[:12]
                    if i in new:
                        continue                       # the same file under two overlapping folders: the first one wins
                    old = INDEX.get(i)
                    keep = bool(old and old.get("backed"))      # its copy is filed under the old label and path: keep them
                    barred = not old and in_skipped(p, skip_rules)     # new inside a folder the user skipped: stays skipped
                    new[i] = {"id": i, "path": p, "src": src, "label": old["label"] if keep else label,
                              "rel": old["rel"] if keep else rel,
                              "size": st.st_size, "mtime": st.st_mtime, "atime": st.st_atime,
                              "selected": old["selected"] if old else int(auto and not barred),
                              "reviewed": old.get("reviewed", True) if old else (auto or barred),
                              "backed": old.get("backed", {}) if old else {}}
                    count += 1
                    if count % 2000 == 0:
                        job_set(done=count, total=max(expected, count), message=f"Scanned {count:,} files...")
    scanned = set(srcs)
    moved_all = set()
    for rs in SETTINGS.get("remote_sources", []):          # folders of other paired PCs, read over the network
        peer = PEERS.get(rs.get("pc", ""))
        if not peer:
            continue
        rroot = rs["root"]
        key = remote_key(peer, rroot)
        rlabel = remote_label(rroot)
        rnew, rfailed, refused, moved = {}, [], 0, set()
        old_key = old_remote_key(peer, rroot)
        job_set(message=f"Scanning {peer['name']} ({rroot})...")
        try:
            for item in rclient(peer["id"]).walk(rroot, rules(), maxb):
                check_cancel()
                if item[0] == "!":
                    rfailed.append(os.path.normcase(key + sep + item[1].replace("/", sep)))
                    continue
                rel_s, size, mtime = item
                if clean_remote_rel(rel_s) is None or not isinstance(size, int) or not isinstance(mtime, (int, float)) or size < 0:
                    refused += 1                               # not a file name this PC will ever write to
                    continue
                rel = rel_s.replace("/", sep)
                p = key + sep + rel
                i = fid_of(p)
                if i in rnew:
                    continue
                old = INDEX.get(i)
                if old is None:                                    # a list written by 1.3.0 or 1.3.1 moves to the new form
                    oid = fid_of(old_key + sep + rel)
                    old = INDEX.get(oid)
                    if old is not None:
                        moved.add(oid)
                keep = bool(old and old.get("backed"))
                barred = not old and in_skipped(p, skip_rules)
                rnew[i] = {"id": i, "path": p, "src": key, "label": old["label"] if keep else rlabel,
                           "rel": old["rel"] if keep else rel, "size": size, "mtime": mtime,
                           "selected": old["selected"] if old else int(auto and not barred),
                           "reviewed": old.get("reviewed", True) if old else (auto or barred),
                           "backed": old.get("backed", {}) if old else {},
                           "remote": {"pc": peer["id"], "root": rroot, "rel": rel_s, "name": peer["name"]}}
                count += 1
                if count % 2000 == 0:
                    job_set(done=count, total=max(expected, count), message=f"Scanned {count:,} files...")
        except remote.RemoteError as e:
            state = set_peer_state(peer["id"], kind_state(e.kind))
            why = STATE_TEXT[state].rstrip(".")
            log("warn", "scan", f"Could not scan {peer['name']} ({rroot}): {why}. Its list is kept from the last scan.")
            keep_src.add(key)
            continue
        set_peer_state(peer["id"], "online")
        META.setdefault("remote_scans", {})[f"{peer['id']}/{rroot}"] = {"at": time.time(), "files": len(rnew), "bytes": sum(f["size"] for f in rnew.values())}
        moved_all.update(moved)
        if refused:
            log("warn", "scan", f"{peer['name']} ({rroot}) sent {refused} file names that were refused as unsafe.")
        new.update(rnew)
        failed.extend(rfailed)
        scanned.add(key)
    adopted = adopt_known(new)
    with LOCK:
        for i, f in INDEX.items():
            if i in moved_all:
                continue                                   # carried over to its new form above
            if i in new:                                   # keep any choice made while the scan was running
                cur = new[i]
                cur["selected"], cur["reviewed"], cur["backed"] = f["selected"], f.get("reviewed", True), f.get("backed", {})
            elif f["src"] in keep_src or any(os.path.normcase(f["path"]).startswith(p + os.sep) for p in failed):
                if f.get("remote") and f["src"] in keep_src:
                    f["stale"] = True                      # from the last scan of a PC that cannot be reached now
                new[i] = f                                 # could not be read this time: keep it as it was
            elif f.get("backed") and (f["src"] in scanned or f.get("remote")):
                GONE[i] = f                                # deleted from the PC, but the backup copy stays restorable
        for i in new:
            GONE.pop(i, None)
        INDEX.clear()
        INDEX.update(new)
        mark()
    write_json("gone.json", GONE)
    META["last_scan"] = time.time()
    META["last_scan_count"] = count
    write_json("meta.json", META)
    total = sum(f["size"] for f in new.values() if not f.get("stale"))     # files of a PC that was not reached are not counted as scanned
    msg = f"Scanned {count:,} files, {fmt(total)} in total. " + scan_summary()
    if adopted:
        msg += (f" {adopted:,} of the new files are already on the backup drive from another PC: they were added to your backup "
                "list, and the next backup links to those copies without writing them again.")
    log("info", "scan", msg)
    return msg


def adopt_known(new):
    """New files whose copy another PC already put on the backup drive are added to the backup list, so they are not
    shown as new. Nothing is written here: the next backup confirms the content and links to the copy."""
    if not SETTINGS.get("reuse_drive_copies", True):
        return 0
    cats, dests = [], []
    for d in SETTINGS["destinations"]:
        if not os.path.isdir(d):
            continue
        dests.append(d)
        try:
            c = make_catalog(d)
        except (RuntimeError, OSError):
            continue
        if c.usable:
            cats.append(c)
    if not dests:
        return 0
    job_set(message="Looking for copies already on the backup drive...")
    n = 0
    with LOCK:
        for i, f in new.items():
            if i in INDEX or f.get("stale") or f["selected"] or f.get("reviewed", True) or f["backed"]:
                continue                                   # only files waiting in New files, never one the user decided on
            if at_its_place(dests, f) or any(c.seen(Path(f["rel"]).name, f["size"], f["mtime"]) for c in cats):
                f["selected"], f["reviewed"] = 1, True
                n += 1
    return n


def at_its_place(dests, f):
    """A copy with this file's size and date is already where this PC would put it: backed up earlier (this PC's list was
    lost or reset), or by another PC that backed this PC up over the network. The next backup confirms the content."""
    for d in dests:
        try:
            p, gz = find_backup(d, f)
            if p is None:
                continue
            size = drivecopies._gz_size(str(p)) if gz else p.stat().st_size
            if size == (f["size"] & 0xFFFFFFFF if gz else f["size"]) and abs(p.stat().st_mtime - f["mtime"]) <= 2:
                return True
        except (OSError, RuntimeError):
            continue
    return False


def copy_hashed(f, part, gz):
    """Copy the source to `part` and return the SHA-256 of the bytes actually copied. A file that changed while it was
    read is refused, so a half-edited copy is never recorded as backed up."""
    before = src_stat(f)
    sha = hashlib.sha256()
    with src_open(f) as s, (gzip.open(part, "wb", compresslevel=6) if gz else open(part, "wb")) as o:
        for chunk in iter(lambda: s.read(1 << 20), b""):
            sha.update(chunk)
            o.write(chunk)
    after = src_stat(f)
    if (after.st_size, after.st_mtime) != (before.st_size, before.st_mtime) or (before.st_size, before.st_mtime) != (f["size"], f["mtime"]):
        raise RuntimeError("the file changed while it was being backed up; it will be tried again on the next backup")
    if gz or f.get("remote"):
        os.utime(part, (time.time(), f["mtime"]))
    else:
        shutil.copystat(f["path"], part)
    return sha.hexdigest()


def copy_to(dest, f, h):
    gz = SETTINGS["compress"]
    tgt = target_of(dest, f, gz, create=True)
    stamp_folder(dest, f)
    tgt.parent.mkdir(parents=True, exist_ok=True)
    keep = max(0, int(SETTINGS.get("keep_versions") or 0))
    if tgt.exists() and not f["backed"].get(dest):
        keep = max(keep, 1)                   # a copy this PC did not write (another PC's, or a file of the same name): never lose it
    if tgt.exists() and keep > 0:
        archive_version(dest, f, tgt, keep)
    part = tgt.with_name(tgt.name + ".part")
    try:
        h = copy_hashed(f, part, gz)          # the hash of what was really written, not of an earlier read
        os.replace(part, tgt)
    finally:
        part.unlink(missing_ok=True)
    other = target_of(dest, f, not gz)
    if other.exists():
        if keep > 0:
            archive_version(dest, f, other, keep)
        else:
            other.unlink(missing_ok=True)
    record(f, dest, h)


def reuse_copy(dest, f, h, cat):
    """Another PC already stored this exact content on `dest`: link to it instead of writing it again.
    The link is a second name for the same data (NTFS), so it costs no space and the original is never touched.
    Returns False (and changes nothing) when there is no such copy, or the drive cannot link."""
    gz = SETTINGS["compress"]
    src = cat.find(h, f["size"], Path(f["rel"]).name, gz)
    tgt = target_of(dest, f, gz, create=True)
    if not src or os.path.normcase(src) == os.path.normcase(str(tgt)):
        return False
    stamp_folder(dest, f)
    tgt.parent.mkdir(parents=True, exist_ok=True)
    tmp = tgt.with_name(tgt.name + ".part")
    try:
        tmp.unlink(missing_ok=True)
        os.link(src, tmp)                          # nothing is changed yet if the drive cannot link (FAT, exFAT, network)
    except OSError:
        return False
    try:
        st = src_stat(f)
        if (st.st_size, st.st_mtime) != (f["size"], f["mtime"]):
            raise RuntimeError("the file changed while it was being backed up; it will be tried again on the next backup")
        keep = max(0, int(SETTINGS.get("keep_versions") or 0))
        if tgt.exists() and not f["backed"].get(dest):
            keep = max(keep, 1)
        if tgt.exists() and keep > 0:
            archive_version(dest, f, tgt, keep)
        os.replace(tmp, tgt)
    finally:
        tmp.unlink(missing_ok=True)
    other = target_of(dest, f, not gz)
    if other.exists():
        if int(SETTINGS.get("keep_versions") or 0) > 0:
            archive_version(dest, f, other, int(SETTINGS["keep_versions"]))
        else:
            other.unlink(missing_ok=True)
    record(f, dest, h)
    return True


def migrate_legacy_remote(ds):
    """Move what versions 1.3 to 1.5 stored under this PC's folder (Remote PCs / name (id) / folder) into the folder of
    the PC it came from. The copies are renamed, never rewritten, and a file is only switched over when every copy
    of it moved; otherwise it stays where it was and keeps working."""
    with LOCK:
        items = [f for f in list(INDEX.values()) + list(GONE.values()) if is_legacy_remote(f)]
    n = 0
    for f in items:
        check_cancel()
        nf = {**f, "label": remote_label(f["remote"]["root"])}
        done, ok, empty = [], True, []
        try:
            for d in ds:
                pairs = []
                for gz in (False, True):
                    old = target_of(d, f, gz)
                    if old.exists():
                        pairs.append((old, target_of(d, nf, gz, create=True)))
                for e, _, _ in version_files(d, f):
                    pairs.append((e, vdir(d, nf) / e.name))
                for old, new in pairs:
                    if new.exists():
                        ok = False                      # something is already there: leave the old copy alone
                        break
                    new.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(old, new)
                    done.append((old, new))
                    empty.append((d, old.parent))
                if pairs and ok:
                    stamp_folder(d, nf)
                if not ok:
                    break
        except (OSError, RuntimeError) as e:
            ok = False
            log("warn", "backup", f"Could not move {f['path']} into its own PC folder: {e}")
        if ok:
            for d, p in empty:                          # the legacy folders that are now empty go away
                stop = Path(d) / ".versions" if ".versions" in p.parts else Path(d) / pc_folder(d)
                while stop in p.parents and p.is_dir() and not any(p.iterdir()):
                    p.rmdir()
                    p = p.parent
            with LOCK:
                f["label"] = nf["label"]
            n += 1
        else:
            for old, new in reversed(done):             # put back what moved, so the file is found in one place only
                try:
                    os.replace(new, old)
                except OSError:
                    pass
    if n:
        with LOCK:
            mark()
        write_json("gone.json", GONE)
        log("info", "backup", f"Moved {n:,} files of other PCs into those PCs' own folders on the backup drive.")
    return n


def record(f, dest, h):
    with LOCK:
        f["backed"][dest] = {"hash": h, "size": f["size"], "mtime": f["mtime"],
                             "at": datetime.now().isoformat(sep=" ", timespec="seconds")}
        mark()


def deep_changed(ds, already):
    """Chosen files that look unchanged (same size and date) but whose content no longer matches what was backed up."""
    with LOCK:
        cand = [f for f in INDEX.values() if f["selected"] and f["id"] not in already and status(f, ds) == "backed_up"]
    job_set(total=len(cand), done=0, message="Comparing file contents...")
    out = []
    for n, f in enumerate(cand, 1):
        check_cancel()
        try:
            h = src_hash(f)
        except (OSError, remote.RemoteError, RuntimeError):
            continue
        if any(f["backed"][d].get("hash") != h for d in ds):
            out.append(f)
        job_set(done=n, message=f"Comparing contents: {n} of {len(cand)} files")
    return out


def backup_job(trigger="manual", scan_first=False):
    _PCF.clear()                       # re-check which folder on the drive belongs to this PC
    _TOUCHED.clear()
    refresh_destinations(True)
    sync_folder_names()                # a rename made while the drive was away or a job was running catches up here
    if scan_first:
        scan_job()
    ds = list(SETTINGS["destinations"])
    if not ds:
        raise RuntimeError("No backup destination is set. Add one in Settings.")
    for d in ds:
        saved, info = SETTINGS.get("dest_vols", {}).get(d), volume_info(d)
        if saved and (not info or info[1] != saved):
            raise RuntimeError(f"The backup drive is not connected: {d} is missing or is a different drive.")
    for d in ds:
        try:
            os.makedirs(d, exist_ok=True)
        except OSError as e:
            raise RuntimeError(f"Cannot use destination {d}: {e}")
        pc_folder(d, create=True)
    migrate_legacy_remote(ds)
    with LOCK:
        todo = [f for f in INDEX.values() if is_pending(f, ds)]
    waiting = sorted({f["remote"]["pc"] for f in todo if f.get("remote")})
    away = 0
    if waiting:                                            # the other PC may have gone since the last scan: ask before copying
        probe_peers(set(waiting))
        gone_pcs = {pid for pid in waiting if PEER_STATE.get(pid, {}).get("state") != "online"}
        for f in list(todo):
            if f.get("remote") and f["remote"]["pc"] in gone_pcs:
                f["stale"] = True
                todo.remove(f)
                away += 1
        for pid in gone_pcs:
            peer = PEERS.get(pid)
            log("warn", "backup", f"Skipped the files of {peer['name'] if peer else 'a PC'}: {PEER_STATE[pid]['text'].rstrip('.')}.")
    if SETTINGS.get("deep_check"):
        todo += deep_changed(ds, {f["id"] for f in todo})
    now = time.time()
    todo.sort(key=lambda f: -importance(f, now)[0])        # the files that matter most are copied first
    unreachable = sum(1 for f in INDEX.values() if f.get("stale") and f["selected"] and status(f, ds) != "backed_up")
    if not todo:
        msg = ("Everything is already backed up. Nothing new or changed to copy." if not unreachable
               else f"Nothing could be copied: {unreachable:,} chosen files are on a PC that cannot be reached right now.")
        log("info", "backup", msg)
        return msg
    need = {d: 0 for d in ds}
    for f in todo:
        for d in ds:
            b = f["backed"].get(d)
            if not (b and b["size"] == f["size"] and b["mtime"] == f["mtime"]):
                have = 0
                try:
                    p, _ = find_backup(d, f)
                    have = p.stat().st_size if p else 0     # the new copy replaces this one
                except OSError:
                    pass
                need[d] += max(f["size"] - have, 0)
    for d in ds:
        u = disk(d)
        if u and need[d] > u["free"]:
            raise RuntimeError(f"Not enough space on {d}: needs {fmt(need[d])}, only {fmt(u['free'])} free")
    total_b = sum(f["size"] for f in todo)
    job_set(total=total_b, done=0, message=f"Backing up {len(todo)} files ({fmt(total_b)})...")
    copied = skipped = failed = cbytes = done_b = reused = rbytes = present = 0
    errors = []
    cats = {d: make_catalog(d) for d in ds}     # copies other PCs (or an earlier backup of this PC's files by another PC) already put on the drive
    t0 = time.time()
    for n, f in enumerate(todo, 1):
        check_cancel()
        try:
            st = src_stat(f)
            with LOCK:
                f["size"], f["mtime"] = st.st_size, st.st_mtime
                mark()
            h = src_hash(f)
            did = bad = linked = False
            for d in ds:
                b = f["backed"].get(d)
                if b and b["hash"] == h:
                    record(f, d, h)  # content unchanged, only the timestamp moved
                    continue
                try:
                    if already_stored(d, f, h):
                        stamp_folder(d, f)
                        record(f, d, h)                    # the same copy is already at its place on the drive: nothing to write
                        linked = True
                        present += 1
                        continue
                    if SETTINGS.get("reuse_drive_copies", True) and cats[d].usable and reuse_copy(d, f, h, cats[d]):
                        linked = True
                        reused += 1
                        rbytes += f["size"]
                        continue
                    copy_to(d, f, h)
                    did = True
                    cbytes += f["size"]
                except Exception as e:
                    bad = True
                    errors.append(f"{f['path']} -> {d}: {e}")
            if bad:
                failed += 1
            elif did:
                copied += 1
            elif not linked:
                skipped += 1
        except Exception as e:
            failed += 1
            errors.append(f"{f['path']}: {e}")
        done_b += f["size"]
        job_set(done=done_b, message=f"{n} of {len(todo)} files")
    for e in errors[:50]:
        log("error", "backup", e)
    secs = round(time.time() - t0, 1)
    for d, folder in list(_TOUCHED):                       # when each other PC's folder was last backed up from here
        idf = Path(d) / folder / "pc-id.json"
        data = read_json_at(idf)
        if isinstance(data, dict):
            data["last_backup"] = datetime.now().isoformat(sep=" ", timespec="seconds")
            try:
                write_json_at(idf, data)
            except OSError:
                pass
    msg = (f"Backup ({trigger}): {copied} copied ({fmt(cbytes)}), {skipped} unchanged, "
           + (f"{present} already on the drive at their place (backed up earlier, by this PC or another), " if present else "")
           + (f"{reused} already on the drive from another PC and reused ({fmt(rbytes)} not written again), " if reused else "")
           + f"{failed} failed in {secs}s" + (f". {unreachable:,} files on a PC that cannot be reached were skipped." if unreachable else ""))
    log("warn" if failed else "info", "backup", msg)
    HISTORY.append({"at": datetime.now().isoformat(sep=" ", timespec="seconds"), "trigger": trigger,
                    "copied": copied, "skipped": skipped, "failed": failed,
                    "copied_bytes": cbytes, "seconds": secs})
    del HISTORY[:-500]
    write_json("history.json", HISTORY)
    META["last_backup"] = HISTORY[-1]["at"]
    write_json("meta.json", META)
    save_state_copy(ds)
    notify(msg)
    return msg


def save_state_copy(ds):
    """Keep this PC's skip/backup choices on the backup drive too, so a reinstalled PC does not lose them."""
    with LOCK:
        snap = {i: [f["path"], f["selected"], int(f.get("reviewed", True))] for i, f in INDEX.items()}
    for d in ds:
        try:
            with gzip.open(Path(d) / pc_folder(d) / "choices.json.gz", "wt", encoding="utf8") as o:
                json.dump({"pc": PC["name"], "saved": datetime.now().isoformat(timespec="seconds"),
                           "files": snap, "excludes": SETTINGS["excludes"],
                           "skipped_dirs": META.get("skipped_dirs", [])}, o, separators=(",", ":"))
        except OSError as e:
            log("warn", "backup", f"Could not save choices on {d}: {e}")


def verify_job():
    refresh_destinations(True)
    ds = list(SETTINGS["destinations"])
    with LOCK:
        items = [(f, d) for f in INDEX.values() for d in ds if d in f["backed"]]
    job_set(total=len(items), done=0, message="Verifying backups...")
    ok = bad = 0
    for n, (f, d) in enumerate(items, 1):
        check_cancel()
        p, gz = find_backup(d, f)
        problem = None
        if p is None:
            problem = "copy is missing"
        else:
            try:
                if hash_file(p, gz) != f["backed"][d]["hash"]:
                    problem = "copy is corrupt (hash mismatch)"
            except Exception as e:
                problem = f"cannot read copy: {e}"
        if problem:
            bad += 1
            log("error", "verify", f"{f['path']} on {d}: {problem}. It will be backed up again.")
            with LOCK:
                f["backed"].pop(d, None)
                mark()
        else:
            ok += 1
        job_set(done=n, message=f"{n} of {len(items)} copies checked")
    msg = f"Verified {ok} copies OK, {bad} problems"
    log("warn" if bad else "info", "verify", msg)
    META["last_verify"] = {"at": datetime.now().isoformat(sep=" ", timespec="seconds"), "ok": ok, "bad": bad}
    write_json("meta.json", META)
    if bad:
        notify(msg)
    return msg


def restore_job(items, target, overwrite):
    refresh_destinations(True)
    done = skipped = failed = 0
    job_set(total=len(items), done=0, message="Restoring...")
    for n, it in enumerate(items, 1):
        check_cancel()
        f = None
        try:
            if not isinstance(it, dict):
                raise RuntimeError("bad item")
            f = INDEX.get(it.get("id")) or GONE.get(it.get("id"))
            d = it.get("dest")
            if not f or d not in SETTINGS["destinations"]:
                raise RuntimeError("unknown file or destination")
            ver = str(it.get("version") or "")
            if ver:
                hit = next(((e, ts, g) for e, ts, g in version_files(d, f) if e.name == ver), None)
                if not hit:
                    raise RuntimeError("that older version is no longer on the drive")
                src, gz = hit[0], hit[2]
            else:
                src, gz = find_backup(d, f)
            if not src or not src.exists():
                raise RuntimeError("backup copy not found")
            if f.get("remote") and not target:
                raise RuntimeError("Choose a folder to restore into: this file came from another PC.")
            if target:                                     # another PC's files go under that PC's name, so two PCs never mix
                out = Path(target) / (folder_of(d, f) if foreign_folder(d, f) else "") / f["label"] / f["rel"]
            else:
                out = Path(f["path"])
            if ver:                                        # an older version is put beside the file, never over it
                out = out.with_name(f"{out.stem} (version {hit[1]}){out.suffix}")
            if out.exists() and not overwrite:
                skipped += 1
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            part = out.with_name(out.name + ".restoring")
            try:
                if gz:
                    with gzip.open(src, "rb") as s_, open(part, "wb") as o:
                        shutil.copyfileobj(s_, o, 1 << 20)
                    os.utime(part, (time.time(), f["mtime"]))
                else:
                    shutil.copy2(src, part)
                os.replace(part, out)
            finally:
                part.unlink(missing_ok=True)
            done += 1
        except Exception as e:
            failed += 1
            log("error", "restore", f"{f['path'] if f else (it.get('id') if isinstance(it, dict) else it)}: {e}")
        job_set(done=n, message=f"{n} of {len(items)} files")
    msg = f"Restored {done} files to {target or 'their original place'}, {skipped} skipped (already exist), {failed} failed"
    log("warn" if failed else "info", "restore", msg)
    return msg


# ---------------------------------------------------------------- organize my PC

CATS = {
    "Documents": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".rtf", ".odt", ".ods", ".csv", ".md", ".epub"},
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".tif", ".tiff", ".svg", ".raw", ".cr2", ".nef"},
    "Videos": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".3gp"},
    "Music": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".iso"},
    "Code": {".py", ".js", ".ts", ".tsx", ".html", ".css", ".json", ".sql", ".php", ".java", ".cs", ".cpp", ".c", ".sh", ".bat"},
}
EXT_CAT = {e: c for c, es in CATS.items() for e in es}
SKIP_DIRS = {"windows", "program files", "program files (x86)", "programdata", "appdata", "$recycle.bin",
             "system volume information", "node_modules", "site-packages", "__pycache__", "recovery", "msocache"}


def drive_roots():
    if os.name == "nt":
        return [f"{c}:\\" for c in string.ascii_uppercase if os.path.exists(f"{c}:\\")]
    return ["/"]


def organize_roots(scope):
    if scope == "pc":
        return drive_roots()
    h = Path.home()
    return [str(h / n) for n in ("Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music") if (h / n).is_dir()]


def default_org_target():
    best, free = None, -1
    for r in drive_roots():
        u = disk(r)
        if u and u["free"] > free:
            best, free = r, u["free"]
    return str(Path(best or Path.home()) / "Ala Eh Organized")


def organize_job(scope, target):
    if scope not in ("personal", "pc"):
        raise RuntimeError("Unknown scope")
    if not target.strip():
        raise RuntimeError("Choose a folder to organize into")
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    tnorm = os.path.normcase(os.path.abspath(target))
    allowed = {e: c for e, c in EXT_CAT.items() if not (scope == "pc" and c == "Code")}
    todo, ignored = [], 0
    mf = DATA / "organized-index.json"
    try:
        manifest = json.loads(mf.read_text("utf8"))
    except (OSError, ValueError):
        manifest = {}
    made = {os.path.normcase(os.path.abspath(k)) for k in manifest}
    for root in organize_roots(scope):
        rnorm = os.path.normcase(os.path.abspath(root))
        if rnorm == tnorm:
            continue                      # the target is itself a scanned folder: its own output is not new input
        for dp, dirs, names in os.walk(root):
            check_cancel()
            dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS and not d.startswith(("$", "."))
                       and os.path.normcase(os.path.abspath(os.path.join(dp, d))) != tnorm]
            for n in names:
                c = allowed.get(os.path.splitext(n)[1].lower())
                if not c:
                    ignored += 1
                    continue
                p = os.path.join(dp, n)
                if os.path.normcase(os.path.abspath(p)) in made:
                    continue                  # a file this tool created in an earlier run: output, not input
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                todo.append((p, st.st_size, st.st_mtime, c))
            job_set(done=len(todo), message=f"Found {len(todo)} files... {dp[:60]}")
    total = sum(t[1] for t in todo)
    u = disk(target)
    if u and total > u["free"]:
        raise RuntimeError(f"Not enough space in {target}: needs up to {fmt(total)}, only {fmt(u['free'])} free")
    job_set(total=total, done=0, message=f"Organizing {len(todo)} files ({fmt(total)})...")
    copied = same = failed = done_b = 0
    try:
        for n, (p, size, mt, c) in enumerate(todo, 1):
            check_cancel()
            try:
                d = target / c / datetime.fromtimestamp(mt).strftime("%Y")
                base = Path(p)
                dest, k = d / base.name, 2
                skip = False
                while dest.exists():
                    if manifest.get(str(dest)) == p and dest.stat().st_size == size:
                        skip = True
                        break
                    dest = d / f"{base.stem} ({k}){base.suffix}"
                    k += 1
                if skip:
                    same += 1
                else:
                    d.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(p, dest)
                    manifest[str(dest)] = p
                    copied += 1
            except Exception as e:
                failed += 1
                if failed <= 50:
                    log("error", "organize", f"{p}: {e}")
            done_b += size
            job_set(done=done_b, message=f"{n} of {len(todo)} files")
    finally:
        mf.write_text(json.dumps(manifest), "utf8")
        try:
            (target / "organized-index.json").write_text(json.dumps(manifest, indent=1), "utf8")
        except OSError:
            pass
    msg = (f"Organized into {target}: {copied} copied, {same} already there, {failed} failed, "
           f"{ignored} other files ignored (programs, system files)")
    log("warn" if failed else "info", "organize", msg)
    return msg


@app.get("/api/organize/info")
def organize_info():
    return jsonify(target=default_org_target(), personal=organize_roots("personal"), pc=drive_roots())


def is_unc(p):
    return str(p).strip().startswith(("\\\\", "//"))


@app.post("/api/organize")
def organize():
    b = request.json or {}
    if is_unc(b.get("target") or ""):
        return jsonify(error="Network paths are not allowed. Use a drive letter."), 400
    return started(start_job("organize", organize_job, b.get("scope", "personal"), b.get("target") or default_org_target()))


# ---------------------------------------------------------------- scheduler

def next_run():
    s = SETTINGS["schedule"]
    if not s["enabled"] or not s["days"]:
        return None
    now = datetime.now()
    hh, mm = map(int, s["time"].split(":"))
    for add in range(8):
        d = (now + timedelta(days=add)).replace(hour=hh, minute=mm, second=0, microsecond=0)
        if d.weekday() in s["days"] and (d > now or (add == 0 and META.get("last_scheduled") != now.date().isoformat())):
            return d.isoformat(sep=" ", timespec="minutes")
    return None


def scheduled_scan():
    """The scheduled job: scan only. Nothing is copied, so a backup drive on an internal disk never fills up on its own."""
    out = "Scheduled scan: " + scan_job()
    log("info", "schedule", out)
    notify(out)
    return out


def scheduler():
    while True:
        time.sleep(20)
        try:
            with LOCK:
                busy = JOB["state"] == "running"
            if busy:
                continue
            alert_check()
            s, now = SETTINGS["schedule"], datetime.now()
            if (s["enabled"] and now.weekday() in s["days"] and now.strftime("%H:%M") >= s["time"]
                    and META.get("last_scheduled") != now.date().isoformat()):
                if start_job("scan", scheduled_scan):
                    META["last_scheduled"] = now.date().isoformat()
                    write_json("meta.json", META)
                    log("info", "schedule", "Scheduled scan started")
                continue
            m = int(SETTINGS["auto_scan_minutes"])
            if m and time.time() - max(META.get("last_scan", 0), META.get("last_scan_try", 0)) >= m * 60:
                META["last_scan_try"] = time.time()
                start_job("scan", scan_job)
        except Exception as e:
            log("error", "schedule", str(e))


# ---------------------------------------------------------------- auth

TOKENS = set()


UPDATE_LOCK = threading.Lock()
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
FRONTEND_PORT = int(os.environ.get("FRONTEND_PORT", "5174"))
FAILS = {}


@app.before_request
def origin_guard():
    """Only this PC's own pages may use the API: stops other web sites (DNS rebinding, cross-site forms)."""
    if ON_VERCEL and not PASSWORD and request.path.startswith("/api/"):
        return jsonify(error="This deployment only serves the download page. Run the app on your own PC."), 403
    if BIND_HOST not in ("0.0.0.0", "::") and not ON_VERCEL:
        host = (urlsplit("//" + (request.host or "")).hostname or "").lower()
        if host not in LOOPBACK_HOSTS and host != BIND_HOST.lower():
            return jsonify(error="Blocked: unknown host"), 403
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("Origin")
        if origin:
            o = urlsplit(origin)
            host_port = urlsplit("//" + (request.host or "")).port
            # the page itself, or this tool's own dev page on the same PC (Vite forwards /api with its own Origin)
            ok = o.netloc.lower() == (request.host or "").lower() or (
                (o.hostname or "").lower() in LOOPBACK_HOSTS and o.port in (host_port, FRONTEND_PORT))
            if not ok:
                return jsonify(error="Blocked: the request came from another site"), 403


@app.before_request
def guard():
    if PASSWORD and request.path.startswith("/api/") and request.path not in ("/api/auth/status", "/api/auth/login"):
        if request.cookies.get("abt") not in TOKENS:
            return jsonify(error="Login required"), 401


@app.get("/api/auth/status")
def auth_status():
    return jsonify(required=bool(PASSWORD), authed=(not PASSWORD) or request.cookies.get("abt") in TOKENS,
                   version=updater.current_version())      # the desktop launcher uses this to tell copies apart


@app.post("/api/auth/login")
def login():
    pw = (request.get_json(silent=True) or {}).get("password", "")
    ip, now = request.remote_addr or "", time.time()
    recent = [t for t in FAILS.get(ip, []) if now - t < 60]
    if len(recent) >= 5:
        return jsonify(error="Too many wrong passwords. Wait a minute."), 429
    if not PASSWORD or (isinstance(pw, str) and hmac.compare_digest(pw.encode("utf8"), PASSWORD.encode("utf8"))):
        t = secrets.token_hex(24)
        TOKENS.add(t)
        r = jsonify(ok=True)
        r.set_cookie("abt", t, httponly=True, samesite="Strict")
        return r
    FAILS[ip] = recent + [now]
    log("warn", "auth", "Wrong password attempt")
    return jsonify(error="Wrong password"), 401


@app.post("/api/auth/logout")
def logout():
    TOKENS.discard(request.cookies.get("abt"))
    r = jsonify(ok=True)
    r.delete_cookie("abt")
    return r


# ---------------------------------------------------------------- settings and disks

def clean_settings(b):
    s = {}
    def clean_path(x):
        x = str(x).strip()
        if not x:
            return ""
        if is_unc(x):
            raise ValueError("Network paths (\\\\server\\share) are not allowed. Use a drive letter.")
        return os.path.normpath(x)
    paths = lambda k: list(dict.fromkeys(p for p in (clean_path(x) for x in b.get(k, [])) if p))
    s["sources"], s["destinations"] = paths("sources"), paths("destinations")
    for src in s["sources"]:
        ns = os.path.normcase(os.path.abspath(src))
        for d in s["destinations"]:
            nd = os.path.normcase(os.path.abspath(d))
            if ns == nd or ns.startswith(nd.rstrip(os.sep) + os.sep):
                raise ValueError(f"The folder to scan {src} is the backup location {d} or inside it. Choose a folder outside it.")
    s["excludes"] = [str(x).strip() for x in b.get("excludes", []) if str(x).strip()]
    s["whole_pc"] = bool(b.get("whole_pc", True))
    s["skip_junk"] = bool(b.get("skip_junk", True))
    s["new_files"] = "include" if b.get("new_files") == "include" else "review"
    s["max_size_mb"] = max(0, int(b.get("max_size_mb") or 0))
    s["versions"] = 0
    s["keep_versions"] = min(20, max(0, int(b.get("keep_versions") or 0)))
    s["alert_low_space_pct"] = min(90, max(0, int(b.get("alert_low_space_pct") or 0)))
    s["alert_stale_days"] = min(365, max(0, int(b.get("alert_stale_days") or 0)))
    s["compress"] = bool(b.get("compress"))
    sc = b.get("schedule") or {}
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(sc.get("time", ""))):
        raise ValueError("Schedule time must look like 22:00")
    s["schedule"] = {"enabled": bool(sc.get("enabled")), "time": sc["time"],
                     "days": sorted({int(x) for x in sc.get("days", []) if 0 <= int(x) <= 6})}
    s["auto_scan_minutes"] = max(0, int(b.get("auto_scan_minutes") or 0))
    w = str(b.get("webhook") or "").strip()
    if w and not w.lower().startswith(("http://", "https://")):
        raise ValueError("Webhook must start with http:// or https://")
    s["webhook"] = w
    s["update_check"] = bool(b.get("update_check", True))
    s["deep_check"] = bool(b.get("deep_check"))
    s["reuse_drive_copies"] = bool(b.get("reuse_drive_copies", True))
    return s


@app.get("/api/settings")
def get_settings():
    return jsonify({**SETTINGS, "data_dir": str(DATA), "auth_required": bool(PASSWORD), "junk_list": JUNK, "scan_roots": sources(),
                    "pc_name": PC["name"]})


@app.post("/api/settings")
def set_settings():
    try:
        s = clean_settings(request.json or {})
    except (ValueError, TypeError) as e:
        return jsonify(error=str(e)), 400
    with LOCK:
        SETTINGS.update(s)
        mark()                                  # the answers that depend on the settings are rebuilt
    write_json("settings.json", SETTINGS)
    log("info", "settings", "Settings saved")
    return get_settings()


@app.get("/api/pc/preview")
def pc_name_preview():
    """What a name would become on the drive, while it is being typed: the tidied name, the folder, and whether another PC
    already has a folder with that name."""
    try:
        name = clean_pc_name(request.args.get("name", ""))
    except ValueError as e:
        return jsonify(ok=False, error=str(e))
    taken = any(folder_taken(d, name) for d in SETTINGS["destinations"] if os.path.isdir(d))
    return jsonify(ok=True, name=name, folder=_folder_name(name), taken=taken)


@app.post("/api/pc/name")
def set_pc_name():
    """Name this PC (the first time) or rename it. The name is what the app and other PCs show, and the folder this PC
    gets on the backup drive follows it."""
    try:
        name = clean_pc_name((request.json or {}).get("name"))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    old = PC["name"]
    with LOCK:
        PC["name"], PC["named"] = name, True
        mark()
    write_json("pc.json", PC)
    if JOB["state"] == "running":
        renamed, pending = [], list(SETTINGS["destinations"])          # a backup is writing into the folder: it is renamed at the next one
    else:
        renamed, pending = sync_folder_names()
    log("info", "settings", f"This PC is now called {name}" + (f" (was {old})" if old != name else ""))
    return jsonify(name=name, folder=_folder_name(name), renamed=renamed, pending=pending)


EXIT_HOOK = None          # set by backend/desktop.py: closes the native window so the whole exe exits normally


def close_app():
    try:
        if EXIT_HOOK:
            EXIT_HOOK()
    finally:
        threading.Timer(4, lambda: os._exit(0)).start()      # if the window did not close in time, stop anyway


UPDATE = {"at": 0.0, "release": None, "error": ""}


def update_status(force=False):
    """What the UI shows about updates. GitHub is asked at most once every 6 hours (or when forced)."""
    cur = updater.current_version()
    out = {"enabled": bool(SETTINGS.get("update_check", True)), "current": cur, "latest": cur, "available": False,
           "can_install": updater.can_install(), "page": updater.PAGE, "notes": "", "error": ""}
    if not out["enabled"]:
        return out
    with UPDATE_LOCK:
        if force or time.time() - UPDATE["at"] > 6 * 3600:
            try:
                UPDATE["release"], UPDATE["error"] = updater.fetch_latest(), ""
            except Exception as e:                  # offline, rate limited, no release yet: never get in the way
                UPDATE["release"], UPDATE["error"] = None, f"Could not check for updates ({type(e).__name__})."
            UPDATE["at"] = time.time() if UPDATE["release"] else time.time() - 6 * 3600 + 300     # retry a failure in 5 min
        rel, out["error"] = UPDATE["release"], UPDATE["error"]
    if rel and rel["version"]:
        out.update(latest=rel["version"], page=rel["page"], notes=rel["notes"],
                   available=updater.parse(rel["version"]) > updater.parse(cur))
    return out


@app.get("/api/update")
def update_get():
    return jsonify(update_status(force=request.args.get("force") == "1"))


@app.post("/api/update/install")
def update_install():
    st = update_status(force=True)
    if not st["can_install"]:
        return jsonify(error="Updating from here only works in the installed Windows app."), 400
    if not st["available"]:
        return jsonify(error="You already have the latest version."), 400
    try:
        path = updater.download(UPDATE["release"])
    except Exception as e:
        log("error", "update", f"Update to {st['latest']} failed: {e}")
        return jsonify(error=str(e)), 502
    log("info", "update", f"Updating {st['current']} -> {st['latest']}")
    updater.run_installer(path)
    threading.Timer(1.5, close_app).start()      # the installer helper (started above) finishes the job and reopens the app
    return jsonify(ok=True, version=st["latest"])


@app.post("/api/webhook/test")
def webhook_test():
    if not SETTINGS["webhook"]:
        return jsonify(error="Save a webhook URL first"), 400
    ok, err = notify("Test message from Ala Eh! File Backup")
    return (jsonify(ok=True) if ok else (jsonify(error=err), 400))


@app.get("/api/drives")
def drives():
    out = []
    if os.name == "nt":
        for c in string.ascii_uppercase:
            r = f"{c}:\\"
            if os.path.exists(r):
                out.append({"path": r, **(disk(r) or {"free": 0, "total": 0})})
    else:
        out = [{"path": "/", **(disk("/") or {"free": 0, "total": 0})}, {"path": str(Path.home())}]
    return jsonify(out)


def fixed_drives():
    if os.name != "nt":
        return ["/"]
    import ctypes
    return [f"{c}:\\" for c in string.ascii_uppercase
            if os.path.exists(f"{c}:\\") and ctypes.windll.kernel32.GetDriveTypeW(f"{c}:\\") == 3]


@app.post("/api/sources/whole-pc")
def whole_pc():
    """Scan every internal drive. A destination folder inside a drive is skipped by the scan itself."""
    src = fixed_drives()
    SETTINGS["sources"] = src
    write_json("settings.json", SETTINGS)
    log("info", "settings", f"Scan set to the whole PC: {', '.join(src)}")
    return get_settings()


@app.get("/api/browse")
def browse():
    if is_unc(request.args.get("path") or ""):
        return jsonify(error="Network paths are not allowed. Use a drive letter."), 400
    p = Path(request.args.get("path") or Path.home())
    if not p.is_dir():
        return jsonify(error=f"Not a folder: {p}"), 400
    dirs = []
    try:
        dirs = sorted((e.name for e in p.iterdir() if e.is_dir()), key=str.lower)[:500]
    except OSError:
        pass
    return jsonify(path=str(p), parent=str(p.parent) if p.parent != p else None, dirs=dirs)


# ---------------------------------------------------------------- actions

@app.get("/api/job")
def get_job():
    with LOCK:
        return jsonify(JOB)


@app.post("/api/job/cancel")
def cancel_job():
    CANCEL.set()
    return "", 204


def started(ok):
    return (jsonify(ok=True), 202) if ok else (jsonify(error="Another task is already running"), 409)


@app.post("/api/scan")
def scan():
    return started(start_job("scan", scan_job))


@app.post("/api/backup")
def backup():
    return started(start_job("backup", backup_job, "manual", True))


@app.post("/api/verify")
def verify():
    return started(start_job("verify", verify_job))


@app.post("/api/restore")
def restore():
    b = request.json or {}
    items = b.get("items") or []
    if not items:
        return jsonify(error="Nothing selected to restore"), 400
    if is_unc(b.get("target") or ""):
        return jsonify(error="Network paths are not allowed. Use a drive letter."), 400
    return started(start_job("restore", restore_job, items, (b.get("target") or "").strip(), bool(b.get("overwrite"))))


# ---------------------------------------------------------------- data views

def filtered(a):
    sq = smartsearch.Query(a.get("q") or "")
    out = _filtered(a, sq, False)
    if not out and sq.can_fuzzy:                           # nothing matched: forgive a typo or two
        out = _filtered(a, sq, True)
    return out


def _filtered(a, sq, fuzzy):
    ds = SETTINGS["destinations"]
    st, ext = a.get("status") or "all", (a.get("ext") or "").lower()
    cat = a.get("cat") or ""
    a_sel = bool(a.get("sel"))
    dest = a.get("dest") or ""
    out = []
    with LOCK:
        files = list(INDEX.values())
        if st == "has_backup":
            files += list(GONE.values())      # deleted from the PC, still restorable from the backup
    for f in files:
        if not sq.empty and not sq.match(f["path"], f["size"], os.path.splitext(f["rel"])[1], fuzzy):
            continue
        if ext and (os.path.splitext(f["rel"])[1].lower() or "(none)") != ext:
            continue
        if cat and cat_of(f["path"]) != cat:
            continue
        if a_sel and not f["selected"]:
            continue
        s = status(f, ds)
        rv = not f.get("reviewed", True)
        if st == "review":
            if not rv:
                continue
        elif st == "skipped":
            if f["selected"] or rv:
                continue
        elif st == "has_backup":
            if not f["backed"] or (dest and dest not in f["backed"]):
                continue
        elif st != "all" and s != st:
            continue
        out.append((f, s))
    return out


@app.get("/api/files")
def files():
    a = request.args
    rows = filtered(a)
    now = time.time()
    key = {"size": lambda r: r[0]["size"], "mtime": lambda r: r[0]["mtime"], "score": lambda r: importance(r[0], now)[0],
           "status": lambda r: r[1]}.get(a.get("sort"), lambda r: r[0]["path"].lower())
    rows.sort(key=key, reverse=a.get("dir") == "desc")
    off, lim = max(0, int(a.get("offset", 0))), min(500, max(1, int(a.get("limit", 200))))
    exts = {}
    if off == 0:
        with LOCK:
            for f in INDEX.values():
                e = os.path.splitext(f["rel"])[1].lower() or "(none)"
                exts[e] = exts.get(e, 0) + 1
    return jsonify(
        total=len(rows), total_bytes=sum(r[0]["size"] for r in rows),
        rows=[{"id": f["id"], "path": f["path"], "size": f["size"], "mtime": f["mtime"],
               "selected": f["selected"], "review": not f.get("reviewed", True), "status": s} for f, s in rows[off:off + lim]],
        exts=sorted(exts.items(), key=lambda x: -x[1])[:40] if off == 0 else [])


@app.post("/api/files/select")
def select():
    b = request.json or {}
    sel = int(bool(b.get("selected")))
    with LOCK:
        if "ids" in b:
            targets = [INDEX[i] for i in (b["ids"] or []) if i in INDEX]
        elif "prefix" in b:
            if not str(b["prefix"]).strip("\\/ "):
                return jsonify(error="No folder given"), 400
            pre = b["prefix"].rstrip("\\/") + os.sep
            targets = [f for f in INDEX.values() if f["path"].startswith(pre)]
            set_dir_rule(b["prefix"], not sel)      # skipping a whole folder also covers files added to it later
        elif "dir" in b:
            if not str(b["dir"]).strip():
                return jsonify(error="No folder given"), 400
            d = os.path.normcase(b["dir"])
            targets = [f for f in INDEX.values() if os.path.normcase(os.path.dirname(f["path"])) == d]
        elif "filter" in b:
            targets = [f for f, _ in filtered(b.get("filter") or {})]
        else:
            return jsonify(error="Nothing to change"), 400
        for f in targets:
            f["selected"] = sel
            f["reviewed"] = True
        mark()
    return jsonify(changed=len(targets))


@app.get("/api/files/<i>/versions")
def versions(i):
    f = INDEX.get(i)
    if not f:
        return jsonify(error="Unknown file"), 404
    out = []
    for d in SETTINGS["destinations"]:
        for e, ts, _ in version_files(d, f):
            try:
                out.append({"dest": d, "version": e.name, "size": e.stat().st_size,
                            "at": datetime.strptime(ts, "%Y%m%d-%H%M%S").isoformat(sep=" ")})
            except OSError:
                pass
    return jsonify(out)


# ---------------------------------------------------------------- preview

PREVIEW_CAP = 64 * 1024 * 1024         # the most of one file that is held in memory to look inside it
REMOTE_RAW_CAP = 300 * 1024 * 1024     # the biggest file streamed live from another PC just to be looked at


def preview_source(f):
    """Where to read a file from, best first: the file itself on this PC, a copy on a connected backup drive, or the
    other PC it came from (live). None when it can be read from none of them."""
    if not f.get("remote"):
        try:
            if os.path.isfile(f["path"]):
                return {"kind": "pc", "path": f["path"], "gz": False, "label": "This PC"}
        except OSError:
            pass
    for d in SETTINGS["destinations"]:
        if not os.path.isdir(d):
            continue
        try:
            p, gz = find_backup(d, f)
        except RuntimeError:
            continue
        if p:
            return {"kind": "drive", "path": str(p), "gz": gz, "dest": d, "label": f"Backup copy on {d}"}
    r = f.get("remote")
    if r and not f.get("stale"):
        peer = PEERS.get(r["pc"]) or {}
        return {"kind": "remote", "gz": False, "label": f"Live from {peer.get('name') or r.get('name') or 'the other PC'}"}
    return None


def preview_open(src, f):
    """(a seekable binary file, whether it holds the whole file). A real file is opened as it is; a compressed copy or a
    file on another PC is read into memory, up to PREVIEW_CAP."""
    if src["kind"] != "remote" and not src["gz"]:
        return open(src["path"], "rb"), True
    if src["gz"]:
        with gzip.open(src["path"], "rb") as g:
            data = g.read(PREVIEW_CAP + 1)
    else:
        with src_open(f) as r:
            data = r.read(PREVIEW_CAP + 1)
    return io.BytesIO(data[:PREVIEW_CAP]), len(data) <= PREVIEW_CAP


def preview_none(base, reason):
    return jsonify({**base, "mode": "none", "reason": reason})


@app.get("/api/preview/<i>")
def preview_info(i):
    """What the Preview window shows for one file: how to show it, and the content for the kinds that are read here."""
    f = INDEX.get(i) or GONE.get(i)
    if not f:
        return jsonify(error="Unknown file"), 404
    ds = SETTINGS["destinations"]
    name = os.path.basename(f["path"])
    base = {"id": i, "name": name, "path": f["path"], "size": f["size"], "mtime": f["mtime"], "gone": i in GONE and i not in INDEX,
            "status": status(f, ds), "selected": int(f.get("selected") or 0), "reviewed": bool(f.get("reviewed", True)), "backed": [{"dest": d, "at": b.get("at", "")} for d, b in (f.get("backed") or {}).items()],
            "from_pc": (PEERS.get(f["remote"]["pc"]) or {}).get("name") or f["remote"].get("name") if f.get("remote") else None}
    src = preview_source(f)
    if not src:
        why = ("That PC cannot be reached right now, and no connected backup drive has a copy." if f.get("remote")
               else "The file is no longer on this PC, and no connected backup drive has a copy. Connect the backup drive to look at it.")
        return preview_none(base, why)
    base["source"] = src["label"]
    mode = preview.mode_for(name)
    try:
        if src["kind"] == "remote" and f["size"] > REMOTE_RAW_CAP:
            return preview_none(base, "This file is large and is on another PC. Back it up first, then it can be previewed from the drive.")
        if preview.raw_mode(name):
            extra = {}
            if mode == "audio" and preview.ext_of(name) == "mp3" and src["kind"] != "remote":
                try:
                    with (gzip.open(src["path"], "rb") if src["gz"] else open(src["path"], "rb")) as fh:
                        extra["tags"] = preview.id3_tags(fh.read(1_000_000))
                except (OSError, EOFError):
                    pass
            return jsonify({**base, "mode": mode, "raw": f"/api/preview/{i}/raw", **extra})
        fh, whole = preview_open(src, f)
        with fh:
            try:
                out = preview.build(name, fh, f["size"])
            except (preview.zipfile.BadZipFile, preview.tarfile.TarError, preview.ET.ParseError, EOFError, ValueError, KeyError, OSError) as e:
                fh.seek(0)
                out = {**preview.hex_preview(fh), "note": f"This looks like a {mode} file but it could not be read as one ({e.__class__.__name__}), so the start of its bytes is shown instead."}
            if not whole and out.get("mode") != "text":
                out["note"] = f"This file is bigger than {fmt(PREVIEW_CAP)}, so only its start could be read."
    except remote.RemoteError as e:
        return preview_none(base, f"Could not read it from the other PC: {e}")
    except OSError as e:
        return preview_none(base, f"Could not read the file: {e}")
    return jsonify({**base, **out})


PART_NAME = re.compile(r"(?:word|ppt|xl)/media/[A-Za-z0-9_ .()\-]{1,120}\.(png|jpe?g|gif|webp|bmp)", re.I)
PART_MAX = 25 * 1024 * 1024
_PART_CACHE = {}                       # the last compressed or remote document opened for its pictures: one entry, so memory stays bounded


@app.get("/api/preview/<i>/part")
def preview_part(i):
    """One picture from inside a Word, PowerPoint or Excel file, for the preview to draw in the page. Only pictures under the
    document's media folder, only picture types, size-limited, and served in a sandbox."""
    f = INDEX.get(i) or GONE.get(i)
    if not f:
        return jsonify(error="Unknown file"), 404
    name = request.args.get("name", "")
    m = PART_NAME.fullmatch(name)
    if not m or ".." in name or preview.ext_of(f["path"]) not in ("docx", "docm", "pptx", "pptm", "xlsx", "xlsm"):
        return jsonify(error="Not a picture inside this file"), 400
    src = preview_source(f)
    if not src:
        return jsonify(error="No copy of this file can be read right now"), 404
    try:
        if src["kind"] != "remote" and not src["gz"]:
            zf = preview.zipfile.ZipFile(src["path"])
        else:
            key = (i, f["size"], f["mtime"], src["kind"])
            if _PART_CACHE.get("key") != key:
                fh, whole = preview_open(src, f)
                _PART_CACHE.clear()
                _PART_CACHE.update(key=key, data=fh.getvalue() if whole else b"")
            zf = preview.zipfile.ZipFile(io.BytesIO(_PART_CACHE["data"]))
        with zf:
            info = zf.getinfo(name)
            if info.file_size > PART_MAX:
                return jsonify(error="That picture is too large to show"), 413
            data = zf.read(info)
    except KeyError:
        return jsonify(error="No such picture in this file"), 404
    except (OSError, preview.zipfile.BadZipFile, remote.RemoteError) as e:
        return jsonify(error=f"Could not read it: {e}"), 404
    mime = {"png": "image/png", "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp"}.get(m.group(1).lower(), "image/jpeg")
    resp = Response(data, mimetype=mime)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Content-Security-Policy"] = "sandbox; default-src 'none'; img-src 'self' data:"
    resp.headers["Cache-Control"] = "private, max-age=300"
    return resp


@app.get("/api/preview/<i>/raw")
def preview_raw(i):
    """The file's own bytes, for the browser to show (images, PDF, video, audio only). Never an HTML or script type, and
    everything but a PDF is served in a sandbox, so even an SVG with a script in it cannot run."""
    f = INDEX.get(i) or GONE.get(i)
    if not f:
        return jsonify(error="Unknown file"), 404
    mime = preview.raw_type(f["path"])
    if not mime:
        return jsonify(error="This kind of file cannot be shown directly"), 415
    src = preview_source(f)
    if not src:
        return jsonify(error="No copy of this file can be read right now"), 404
    if src["kind"] == "remote" and f["size"] > REMOTE_RAW_CAP:
        return jsonify(error="Too large to show live from another PC"), 413
    try:
        if src["kind"] != "remote" and not src["gz"]:
            resp = send_file(src["path"], mimetype=mime, conditional=True, max_age=0)
        else:
            def chunks():
                try:
                    with (gzip.open(src["path"], "rb") if src["gz"] else src_open(f)) as fh:
                        for c in iter(lambda: fh.read(1 << 20), b""):
                            yield c
                except (OSError, remote.RemoteError):
                    return
            resp = Response(chunks(), mimetype=mime)
    except OSError as e:
        return jsonify(error=str(e)), 404
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Cache-Control"] = "private, no-cache"
    if mime != "application/pdf":
        resp.headers["Content-Security-Policy"] = "sandbox; default-src 'none'; img-src 'self' data:; media-src 'self'; style-src 'unsafe-inline'"
    return resp


def _explore(path):
    """One level of the scanned tree: the subfolders (with totals) and the files directly in `path`."""
    ds = SETTINGS["destinations"]
    nt = os.name == "nt"
    pre = path.rstrip("\\/") + os.sep if path else ""
    folders_, files_ = {}, []
    with LOCK:
        items = list(INDEX.values())
    for f in items:
        p = f["path"]
        if path:
            if not (p.startswith(pre) or (nt and p.lower().startswith(pre.lower()))):
                continue
            rest = p[len(pre):]
            if os.sep in rest:
                name = rest.split(os.sep)[0]
                fp = pre + name
            else:
                files_.append(f)
                continue
        else:
            name = fp = f["src"]
        a = folders_.setdefault(fp, {"name": name, "path": fp, "files": 0, "bytes": 0, "selected": 0, "review": 0})
        a["files"] += 1
        a["bytes"] += f["size"]
        a["selected"] += 1 if f["selected"] else 0
        a["review"] += 0 if f.get("reviewed", True) else 1
    parent = None
    if path:
        src = next((x for x in all_sources() if path.lower().startswith(x.lower().rstrip("\\/"))), "")
        parent = str(Path(path).parent) if os.path.normcase(path.rstrip("\\/")) != os.path.normcase(src.rstrip("\\/")) else ""
        if parent == path:
            parent = ""
    rows = sorted(files_, key=lambda f: f["path"].lower())[:500]
    return dict(
        path=path, parent=parent, total_files=len(files_),
        folders=sorted(folders_.values(), key=lambda x: -x["bytes"]),
        files=[{"id": f["id"], "path": f["path"], "size": f["size"], "mtime": f["mtime"], "selected": f["selected"],
                "review": not f.get("reviewed", True), "status": status(f, ds)} for f in rows])


@app.get("/api/explore")
def explore():
    path = (request.args.get("path") or "").strip()
    return jsonify(memo(("explore", path, tuple(SETTINGS["destinations"])), lambda: _explore(path)))


def _collapsed(pred):
    """The files matching `pred`, collapsed: a folder where every file matches is one item (open it to look
    inside); matching files that sit in a mixed folder are listed one by one."""
    with LOCK:
        items = list(INDEX.values())
    dtot, direct = {}, {}
    for f in items:                                   # one cheap pass per file, by its own folder
        d = os.path.dirname(f["path"])
        a = dtot.get(d)
        if a is None:
            a = dtot[d] = [0, 0, 0, f["src"]]
        a[0] += 1
        if pred(f):
            a[1] += 1
            a[2] += f["size"]
            direct.setdefault(d, []).append(f)
    tot, kids = {}, {}
    for d, (c, n, b, src) in dtot.items():            # then roll the totals up through the (far fewer) folders
        stop = os.path.normcase(src.rstrip("\\/"))
        while True:
            a = tot.setdefault(d, [0, 0, 0])
            a[0] += c
            a[1] += n
            a[2] += b
            up = os.path.dirname(d)
            if os.path.normcase(d.rstrip("\\/")) == stop or up == d:
                break
            kids.setdefault(up, set()).add(d)
            d = up
    ds = SETTINGS["destinations"]
    out = []

    def visit(d, root):
        t, n, b = tot.get(d, [0, 0, 0])
        if not n:
            return
        if not root and n == t:
            out.append({"kind": "folder", "path": d, "name": os.path.basename(d.rstrip("\\/")) or d,
                        "files": n, "bytes": b})
            return
        for c in kids.get(d, ()):
            visit(c, False)
        for f in direct.get(d, ()):
            out.append({"kind": "file", "path": f["path"], "name": os.path.basename(f["path"]), "id": f["id"],
                        "files": 1, "bytes": f["size"], "parent": d})

    for src in all_sources():
        visit(src, True)
    out.sort(key=lambda x: -x["bytes"])
    return dict(items=out[:1000], count=len(out), files=sum(i["files"] for i in out),
                   bytes=sum(i["bytes"] for i in out))


@app.get("/api/review")
def review():
    """New files waiting for a decision."""
    return jsonify(memo(("review", tuple(sources())), lambda: _collapsed(lambda f: not f.get("reviewed", True))))


def _suggested(limit=20):
    """The new files most worth backing up, best first, each with the reason it was picked."""
    with LOCK:
        cand = [f for f in INDEX.values() if not f.get("reviewed", True) and not f.get("stale")]
    now = time.time()
    scored = sorted(((importance(f, now), f) for f in cand), key=lambda x: -x[0][0])
    top = [x for x in scored if x[0][0] >= 50][:limit]
    return dict(total=len(cand), items=[{"id": f["id"], "path": f["path"], "name": os.path.basename(f["path"]),
                                         "parent": os.path.dirname(f["path"]), "bytes": f["size"], "score": sc, "reason": why}
                                        for (sc, why), f in top])


@app.get("/api/suggested")
def suggested():
    """New files to start with: recently used, of the kinds people keep, in the places they keep them."""
    return jsonify(memo(("suggested", tuple(sources())), _suggested))


@app.get("/api/selected")
def selected():
    """Files chosen for backup."""
    return jsonify(memo(("selected", tuple(sources())), lambda: _collapsed(lambda f: bool(f["selected"]))))


def _types():
    agg = {k: {"key": k, "name": v[0], "files": 0, "bytes": 0, "selected": 0, "review": 0} for k, v in CATEGORIES.items()}
    with LOCK:
        items = list(INDEX.values())
    for f in items:
        a = agg[cat_of(f["path"])]
        a["files"] += 1
        a["bytes"] += f["size"]
        a["selected"] += 1 if f["selected"] else 0
        a["review"] += 0 if f.get("reviewed", True) else 1
    return [a for a in sorted(agg.values(), key=lambda x: -x["bytes"]) if a["files"]]


@app.get("/api/types")
def types():
    return jsonify(memo(("types",), _types))


def _biggest():
    """The folders holding the most data (counting the files directly inside) and the largest single files."""
    ds = SETTINGS["destinations"]
    with LOCK:
        items = list(INDEX.values())
    dirs = {}
    for f in items:
        d = os.path.dirname(f["path"])
        a = dirs.setdefault(d, {"dir": d, "files": 0, "bytes": 0, "selected": 0, "review": 0})
        a["files"] += 1
        a["bytes"] += f["size"]
        a["selected"] += 1 if f["selected"] else 0
        a["review"] += 0 if f.get("reviewed", True) else 1
    top = heapq.nlargest(30, items, key=lambda f: f["size"])
    return dict(
        folders=heapq.nlargest(30, dirs.values(), key=lambda x: x["bytes"]),
        files=[{"id": f["id"], "path": f["path"], "size": f["size"], "mtime": f["mtime"], "selected": f["selected"],
                "review": not f.get("reviewed", True), "status": status(f, ds)} for f in top])


@app.get("/api/biggest")
def biggest():
    return jsonify(memo(("biggest", tuple(SETTINGS["destinations"])), _biggest))


@app.get("/api/presets")
def presets():
    return jsonify([{"key": k, "label": v["label"], "desc": v["desc"]} for k, v in PRESETS.items()])


@app.post("/api/presets/apply")
def apply_preset():
    """Decide every file still waiting for review (or, with replace_all, every file) using a preset."""
    b = request.json or {}
    pr = PRESETS.get(b.get("preset"))
    if not pr:
        return jsonify(error="Unknown preset"), 400
    on = off = on_b = 0
    dry = bool(b.get("dry"))
    with LOCK:
        for f in INDEX.values():
            if f.get("reviewed", True) and not b.get("replace_all"):
                continue
            want = preset_wants(pr, f)
            if want:
                on, on_b = on + 1, on_b + f["size"]
            else:
                off += 1
            if not dry:
                f["selected"] = int(want)
                f["reviewed"] = True
        if not dry:
            mark()
    msg = f"{pr['label']}: {on:,} files ({fmt(on_b)}) will be backed up, {off:,} skipped."
    if not dry:
        log("info", "preset", msg)
    return jsonify(message=msg, backed=on, skipped=off, bytes=on_b)


@app.get("/api/devices")
def devices():
    """Every PC that has a folder on a backup drive, found by the pc-id.json file each PC leaves there."""
    refresh_destinations()
    out = []
    for d in SETTINGS["destinations"]:
        entry = {"dest": d, "reachable": os.path.isdir(d), "label": (volume_info(d) or ("", ""))[0], "devices": []}
        if entry["reachable"]:
            try:
                kids = list(os.scandir(d))
            except OSError:
                kids = []
            for e in kids:
                try:
                    if e.name.startswith(".") or not e.is_dir(follow_symlinks=False):
                        continue
                    meta = read_json_at(Path(e.path) / "pc-id.json")
                    if not isinstance(meta, dict):
                        continue
                    ch = Path(e.path) / "choices.json.gz"
                    last = datetime.fromtimestamp(ch.stat().st_mtime).isoformat(sep=" ", timespec="seconds") if ch.exists() else None
                    other = str(meta.get("last_backup") or "").replace("T", " ") or None       # set when another PC backed this one up
                    by = [str(x) for x in meta.get("backed_up_by", []) if isinstance(x, str)] if isinstance(meta.get("backed_up_by"), list) else []
                    entry["devices"].append({"folder": e.name, "name": str(meta.get("name") or e.name), "user": str(meta.get("user") or ""),
                                             "first_backup": meta.get("first_backup"), "last_backup": max(filter(None, (last, other)), default=None),
                                             "backed_up_by": by, "this_pc": meta.get("id") == PC["id"]})
                except OSError:
                    continue
            entry["devices"].sort(key=lambda x: (not x["this_pc"], x["name"].lower()))
        out.append(entry)
    return jsonify(out)


@app.get("/api/devices/size")
def device_size():
    """Size of one PC's folder on a backup drive. Walking a big drive takes a while, so it runs when asked and stops after 60 s."""
    d, folder = request.args.get("dest", ""), request.args.get("folder", "")
    if d not in SETTINGS["destinations"] or not folder or folder != os.path.basename(folder) or folder.startswith("."):
        return jsonify(error="Unknown backup folder"), 400
    root = Path(d) / folder
    total = files = 0
    stack, t0, complete = [str(root)], time.time(), True
    while stack:
        if time.time() - t0 > 60:
            complete = False
            break
        try:
            with os.scandir(stack.pop()) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        elif e.is_file(follow_symlinks=False):
                            total += e.stat(follow_symlinks=False).st_size
                            files += 1
                    except OSError:
                        pass
        except OSError:
            pass
    return jsonify(bytes=total, files=files, complete=complete)


@app.get("/api/folders")
def folders():
    ds = SETTINGS["destinations"]
    agg = {}
    with LOCK:
        for f in INDEX.values():
            parts = Path(f["rel"]).parts
            if len(parts) < 2:
                continue
            prefix = os.path.join(f["src"], parts[0])
            a = agg.setdefault(prefix, {"prefix": prefix, "name": f"{f['label']}/{parts[0]}",
                                        "files": 0, "bytes": 0, "selected": 0})
            a["files"] += 1
            a["bytes"] += f["size"]
            a["selected"] += f["selected"]
    return jsonify(sorted(agg.values(), key=lambda x: -x["bytes"])[:200])


def _stats_core():
    ds = SETTINGS["destinations"]
    with LOCK:
        fl = list(INDEX.values())
    r = dict(files=len(fl), total_bytes=0, selected_files=0, selected_bytes=0, pending_files=0,
             pending_bytes=0, backed_files=0, backed_bytes=0, new_files=0, review_files=0, review_bytes=0,
             skipped_files=0, skipped_bytes=0, pc_name=PC["name"], pc_named=bool(PC.get("named")))
    folders_ = {}
    for f in fl:
        s, sz = status(f, ds), f["size"]
        r["total_bytes"] += sz
        if not f.get("reviewed", True):
            r["review_files"] += 1
            r["review_bytes"] += sz
        elif not f["selected"]:
            r["skipped_files"] += 1
            r["skipped_bytes"] += sz
        if f["selected"]:
            r["selected_files"] += 1
            r["selected_bytes"] += sz
            if s != "backed_up" and not f.get("stale"):
                r["pending_files"] += 1
                r["pending_bytes"] += sz
        if s == "backed_up":
            r["backed_files"] += 1
            r["backed_bytes"] += sz
        if s == "new":
            r["new_files"] += 1
        top = f["rel"].replace("/", os.sep).split(os.sep)
        k = f"{f['label']}/{top[0]}" if len(top) > 1 else f["label"]
        folders_[k] = folders_.get(k, 0) + sz
    days = {}
    today = datetime.now().date()
    for h in HISTORY:
        days[h["at"][:10]] = days.get(h["at"][:10], 0) + h["copied_bytes"]
    r["offline_pcs"] = offline_pcs(fl)
    r["history"] = [{"day": (today - timedelta(days=i)).strftime("%m-%d"),
                     "bytes": days.get((today - timedelta(days=i)).isoformat(), 0)} for i in range(13, -1, -1)]
    r["largest_files"] = [{"id": f["id"], "path": f["path"], "size": f["size"]} for f in heapq.nlargest(10, fl, key=lambda f: f["size"])]
    r["largest_folders"] = [{"name": k, "size": v} for k, v in sorted(folders_.items(), key=lambda x: -x[1])[:10]]
    return r


def compute_alerts(core):
    """What needs the owner's attention: a missing or full drive, no recent backup, a failed check or backup."""
    ds, out = SETTINGS["destinations"], []
    for d in ds:
        info, saved = volume_info(d), SETTINGS.get("dest_vols", {}).get(d)
        if (saved and (not info or info[1] != saved)) or existing_ancestor(d) is None:
            out.append(dict(key="drive:" + d, level="error", title="Backup drive not connected",
                            text=f"{d} cannot be found. Plug the drive in so the next backup can run.", go="settings"))
            continue
        u = disk(d)
        if not u or not u["total"]:
            continue
        pct, lim = u["free"] / u["total"] * 100, int(SETTINGS.get("alert_low_space_pct") or 0)
        if core["pending_bytes"] > u["free"]:
            out.append(dict(key="space:" + d, level="error", title="Not enough room for the next backup",
                            text=f"{fmt(core['pending_bytes'])} is waiting but {d} has only {fmt(u['free'])} free.", go="settings"))
        elif lim and pct < lim:
            out.append(dict(key="low:" + d, level="warn", title="Backup drive is almost full",
                            text=f"{d} has {fmt(u['free'])} free ({pct:.0f}% of {fmt(u['total'])}).", go="settings"))
    days = int(SETTINGS.get("alert_stale_days") or 0)
    if days and core["selected_files"]:
        last = META.get("last_backup")
        try:
            age = (datetime.now() - datetime.fromisoformat(last)).days if last else None
        except ValueError:
            age = None
        if age is None or age >= days:
            out.append(dict(key="stale", level="warn", title="No recent backup",
                            text=("Nothing has been backed up yet." if age is None else f"The last backup was {age} days ago.") + " Click Back up now.", go="dashboard"))
    if HISTORY and HISTORY[-1].get("failed"):
        out.append(dict(key="failed:" + HISTORY[-1]["at"], level="warn", title="Some files failed to back up",
                        text=f"{HISTORY[-1]['failed']} files could not be copied on {HISTORY[-1]['at']}. See the Logs for why.", go="logs"))
    lv = META.get("last_verify")
    if lv and lv.get("bad"):
        out.append(dict(key="verify:" + lv["at"], level="warn", title="The last check found problems",
                        text=f"{lv['bad']} backup copies were missing or damaged on {lv['at']}. They will be copied again on the next backup.", go="logs"))
    return out


ALERT_EVERY = [0.0]


def alert_check():
    """Send each new warning to the webhook once a day, so a full or missing drive is not noticed too late."""
    if time.time() - ALERT_EVERY[0] < 600 or not SETTINGS.get("webhook"):
        return
    ALERT_EVERY[0] = time.time()
    refresh_destinations()
    core = memo(("stats", tuple(SETTINGS["destinations"])), _stats_core)
    today = datetime.now().date().isoformat()
    sent = {k: v for k, v in META.get("alerted", {}).items() if v == today}      # yesterday's are forgotten, so they can come back
    fresh = [a for a in compute_alerts(core) if a["key"] not in sent]
    for a in fresh:
        sent[a["key"]] = today
        notify(f"{a['title']}: {a['text']}")
    if fresh or sent != META.get("alerted"):
        META["alerted"] = sent
        write_json("meta.json", META)


@app.get("/api/stats")
def stats():
    refresh_destinations()
    ds = SETTINGS["destinations"]
    r = dict(memo(("stats", tuple(ds)), _stats_core))
    r["destinations"] = [{"path": d, "pc_folder": pc_folder(d), "label": (volume_info(d) or ("", ""))[0],
                          **(disk(d) or {"free": None, "total": None})} for d in ds]
    r["last_backup"] = META.get("last_backup")
    r["next_run"] = next_run()
    r["alerts"] = compute_alerts(r)
    r["last_verify"] = META.get("last_verify")
    r["sharing"] = bool(AGENT.server)
    r["sharing_connected"] = len(AGENT.status()["connected"]) if AGENT.server else 0
    return jsonify(r)


# ---------------------------------------------------------------- other PCs: API

def bad(msg, code=400):
    return jsonify(error=str(msg)), code


@app.get("/api/agent")
def agent_status():
    return jsonify(AGENT.status())


@app.post("/api/agent/start")
def agent_start():
    try:
        st = AGENT.start(host=os.environ.get("BACKUP_SHARE_HOST") or "0.0.0.0")      # BACKUP_SHARE_HOST: bind to one address only
    except Exception as e:
        return bad(e)
    log("info", "wireless", f"Sharing turned on (port {st['port']})")
    return jsonify(st)


@app.post("/api/agent/stop")
def agent_stop():
    st = AGENT.stop()
    log("info", "wireless", "Sharing turned off")
    return jsonify(st)


@app.post("/api/agent/roots")
def agent_roots():
    try:
        AGENT.set_roots((request.json or {}).get("roots") or [])
    except (ValueError, TypeError) as e:
        return bad(e)
    return jsonify(AGENT.status())


@app.post("/api/agent/settings")
def agent_settings():
    try:
        AGENT.set_auto_off((request.json or {}).get("auto_off_hours", 8))
    except (ValueError, TypeError) as e:
        return bad(e)
    return jsonify(AGENT.status())


@app.post("/api/agent/pairing")
def agent_pairing():
    try:
        AGENT.new_pairing()
    except RuntimeError as e:
        return bad(e)
    return jsonify(AGENT.status())


@app.post("/api/agent/revoke")
def agent_revoke():
    AGENT.revoke(str((request.json or {}).get("id") or ""))
    log("info", "wireless", "A paired PC was removed from this PC's list")
    return jsonify(AGENT.status())


STATE_TEXT = {
    "online": "Online.",
    "off": "Sharing is off, or the app is closed, on that PC.",
    "offline": "That PC cannot be reached: it is off, asleep or on another network.",
    "removed": "That PC no longer accepts this PC. Pair again.",
    "changed": "That PC's identity changed. Forget it and pair again.",
    "error": "That PC could not be checked.",
    "unknown": "Not checked yet.",
}
PEER_STATE = {}                                            # pc id -> {"state", "text", "at"}


def kind_state(kind):
    return {"refused": "off", "unreachable": "offline", "rejected": "removed", "identity": "changed"}.get(kind, "error")


def set_peer_state(pid, state):
    PEER_STATE[pid] = {"state": state, "text": STATE_TEXT[state], "at": time.time()}
    return state


def probe_peers(ids=None, timeout=3):
    """Ask each paired PC (in parallel) whether it is there and sharing. Fast: a few seconds at most."""
    peers = [p for p in PEERS.all() if ids is None or p["id"] in ids]

    def one(p):
        try:
            remote.RemoteClient(p, AGENT.identity(), PEERS, timeout=timeout).hello()
            set_peer_state(p["id"], "online")
        except remote.RemoteError as e:
            set_peer_state(p["id"], kind_state(e.kind))
        except Exception:
            set_peer_state(p["id"], "error")
    threads = [threading.Thread(target=one, args=(p,), daemon=True) for p in peers]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout * 3 + 3)


def offline_pcs(files):
    """Paired PCs whose files are only known from an earlier scan, because they cannot be reached now."""
    out = {}
    for f in files:
        if f.get("stale") and f.get("remote"):
            pid = f["remote"]["pc"]
            peer = PEERS.get(pid)
            if peer:
                st = PEER_STATE.get(pid) or {"state": "offline", "text": STATE_TEXT["offline"]}
                e = out.setdefault(pid, {"id": pid, "name": peer["name"], "state": st["state"], "text": st["text"], "files": 0, "bytes": 0})
                e["files"] += 1
                e["bytes"] += f["size"]
    return list(out.values())


def peer_view(p):
    chosen = [rs["root"] for rs in SETTINGS.get("remote_sources", []) if rs.get("pc") == p["id"]]
    st = PEER_STATE.get(p["id"]) or {"state": "unknown", "text": STATE_TEXT["unknown"], "at": None}
    scans = {k.split("/", 1)[1]: v for k, v in META.get("remote_scans", {}).items() if k.startswith(p["id"] + "/")}
    return {"id": p["id"], "name": p["name"], "host": p["host"], "port": p["port"], "fingerprint": p["fp"][:16],
            "added": p.get("added", ""), "last_seen": p.get("last_seen", ""), "roots": chosen,
            "state": st["state"], "state_text": st["text"], "checked_at": st["at"], "scans": scans}


@app.get("/api/peers")
def peers_list():
    if request.args.get("check") == "1":
        probe_peers()                                      # is each PC there, and is it sharing?
    return jsonify([peer_view(p) for p in PEERS.all()])


@app.post("/api/peers/discover")
def peers_discover():
    paired = {p["id"] for p in PEERS.all()}
    return jsonify([{**f, "paired": f["id"] in paired} for f in remote.discover(2.0) if f["id"] != PC["id"]])


@app.post("/api/peers/pair")
def peers_pair():
    b = request.json or {}
    host, code = str(b.get("host") or "").strip(), b.get("code")
    try:
        port = int(b.get("port") or agent_mod.BASE_PORT)
        ip = socket.gethostbyname(host)
    except (ValueError, OSError):
        return bad("Cannot find that address. Type the PC's IP address, for example 192.168.1.40.")
    if not agent_mod.is_lan(ip):
        return bad("Only PCs on your own network can be paired.")
    try:
        peer = remote.pair(ip, port, code, PC["name"], AGENT.identity())
    except remote.RemoteError as e:
        return bad(e, 403)
    except Exception as e:
        return bad(f"Pairing failed ({e.__class__.__name__}).", 502)
    if peer["id"] == PC["id"]:
        return bad("That is this PC.")
    known = PEERS.get(peer["id"])
    if known and known["fp"] != peer["fp"]:
        return bad("A PC with that id is already paired under a different identity. Forget it first if it was reinstalled.", 409)
    PEERS.add(peer)
    log("info", "wireless", f"Paired with {peer['name']}")
    return jsonify(peer_view(peer))


@app.post("/api/peers/<pid>/forget")
def peers_forget(pid):
    PEERS.remove(pid)
    SETTINGS["remote_sources"] = [rs for rs in SETTINGS.get("remote_sources", []) if rs.get("pc") != pid]
    write_json("settings.json", SETTINGS)
    with LOCK:
        mark()
    log("info", "wireless", "A PC was forgotten")
    return jsonify(ok=True)


@app.get("/api/peers/<pid>/roots")
def peers_roots(pid):
    if not PEERS.get(pid):
        return bad("Unknown PC", 404)
    try:
        hello = rclient(pid).hello()
    except remote.RemoteError as e:
        return bad(STATE_TEXT[set_peer_state(pid, kind_state(e.kind))], 502)
    set_peer_state(pid, "online")
    chosen = [rs["root"] for rs in SETTINGS.get("remote_sources", []) if rs.get("pc") == pid]
    return jsonify(online=True, name=hello.get("name"), roots=[{"label": r, "chosen": r in chosen} for r in hello.get("roots", [])])


@app.post("/api/peers/<pid>/sources")
def peers_sources(pid):
    if not PEERS.get(pid):
        return bad("Unknown PC", 404)
    roots = [str(r) for r in (request.json or {}).get("roots", [])]
    keep = [rs for rs in SETTINGS.get("remote_sources", []) if rs.get("pc") != pid]
    SETTINGS["remote_sources"] = keep + [{"pc": pid, "root": r} for r in dict.fromkeys(roots)]
    write_json("settings.json", SETTINGS)
    with LOCK:
        mark()
    log("info", "wireless", f"Folders to back up from {PEERS.get(pid)['name']}: {', '.join(roots) or 'none'}")
    return jsonify(peer_view(PEERS.get(pid)))


@app.get("/api/logs")
def logs():
    return jsonify(read_logs(request.args.get("level", ""), request.args.get("q", "")))


@app.get("/api/logs.csv")
def logs_csv():
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["time", "level", "action", "message"])
    for r in reversed(read_logs(request.args.get("level", ""), request.args.get("q", ""), 5000)):
        w.writerow([r["at"], r["level"], r["action"], r["message"]])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=backup-log.csv"})


@app.get("/")
def home():
    if (DIST / "index.html").exists():
        return send_from_directory(DIST, "index.html")
    return "Frontend not built. Run: cd frontend && npm install && npm run build", 404


if __name__ == "__main__":
    if BIND_HOST not in ("127.0.0.1", "localhost", "::1") and not PASSWORD:
        raise SystemExit("BACKUP_HOST opens the tool to the network. Set BACKUP_PASSWORD first.")
    threading.Thread(target=saver, daemon=True).start()
    threading.Thread(target=scheduler, daemon=True).start()
    app.run(host=BIND_HOST, port=int(os.environ.get("BACKUP_PORT", "5001")), threaded=True)
