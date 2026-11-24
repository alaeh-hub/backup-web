"""Self-update for the installed Windows app: asks GitHub for the latest release and can run its installer."""
import hashlib, json, os, re, shutil, subprocess, sys, tempfile, urllib.request
from pathlib import Path
from urllib.parse import urlsplit

REPO = "alaeh-hub/backup-web"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET = "AlaEhBackup-Setup.exe"
PAGE = f"https://github.com/{REPO}/releases/latest"
TRUSTED = ("github.com", "githubusercontent.com")          # the installer may only come from GitHub


def current_version():
    """The version baked into the exe at build time, else frontend/package.json (running from source)."""
    try:
        from _version import VERSION                      # written by installer/build.ps1, not committed
        return VERSION
    except ImportError:
        pass
    try:
        pkg = Path(__file__).resolve().parent.parent / "frontend" / "package.json"
        return str(json.loads(pkg.read_text("utf8")).get("version", "0.0.0"))
    except (OSError, ValueError):
        return "0.0.0"


def parse(v):
    nums = re.findall(r"\d+", str(v).split("-")[0])[:3]
    return tuple(int(n) for n in nums) + (0,) * (3 - len(nums))


def can_install():
    return bool(getattr(sys, "frozen", False)) and os.name == "nt"


def trusted(url):
    p = urlsplit(url)
    host = (p.hostname or "").lower()
    return p.scheme == "https" and any(host == h or host.endswith("." + h) for h in TRUSTED)


def fetch_latest(opener=urllib.request.urlopen):
    """The newest published release: {version, page, notes, url, size, sha256} (url is None without the installer)."""
    req = urllib.request.Request(API, headers={"Accept": "application/vnd.github+json", "User-Agent": "ala-eh-backup-updater"})
    with opener(req, timeout=8) as r:
        data = json.loads(r.read().decode("utf8"))
    asset = next((a for a in data.get("assets", []) if a.get("name") == ASSET), None)
    digest = str((asset or {}).get("digest") or "")
    return {
        "version": str(data.get("tag_name", "")).lstrip("vV"),
        "page": data.get("html_url") if trusted(str(data.get("html_url", ""))) else PAGE,
        "notes": str(data.get("body") or "")[:2000],
        "url": asset.get("browser_download_url") if asset and trusted(str(asset.get("browser_download_url", ""))) else None,
        "size": int((asset or {}).get("size") or 0),
        "sha256": digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else "",
    }


def download(release, opener=urllib.request.urlopen):
    """Save the installer to a temp folder and check it is the file GitHub announced. Returns its path."""
    if not release.get("url"):
        raise RuntimeError("This release has no installer attached.")
    for old in Path(tempfile.gettempdir()).glob("ala-eh-update-*"):       # leftovers of earlier updates
        shutil.rmtree(old, ignore_errors=True)
    folder = Path(tempfile.mkdtemp(prefix="ala-eh-update-"))
    path = folder / ASSET
    req = urllib.request.Request(release["url"], headers={"User-Agent": "ala-eh-backup-updater"})
    sha, size = hashlib.sha256(), 0
    with opener(req, timeout=60) as r, open(path, "wb") as f:
        if not trusted(r.geturl()):
            raise RuntimeError("The download was redirected to an untrusted site.")
        while chunk := r.read(1 << 20):
            f.write(chunk)
            sha.update(chunk)
            size += len(chunk)
    if release.get("size") and size != release["size"]:
        raise RuntimeError("The download is incomplete. Try again.")
    if release.get("sha256") and sha.hexdigest() != release["sha256"]:
        raise RuntimeError("The download failed its integrity check, so it was not installed.")
    return path


def run_installer(path):
    """Hand over to a detached helper: it waits for this app to answer the browser, kills every AlaEhBackup.exe
    (the PyInstaller exe is a wrapper plus the app, and a leftover wrapper would lock the file the installer
    replaces), then runs the installer silently. The installer reopens the app when it is done."""
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    exe = Path(sys.executable).name if getattr(sys, "frozen", False) else "AlaEhBackup.exe"
    steps = (f'ping -n 4 127.0.0.1 >nul & taskkill /F /T /IM "{exe}" >nul 2>&1 & ping -n 3 127.0.0.1 >nul & '
             f'"{path}" /SILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS')
    subprocess.Popen(f'cmd.exe /d /s /c "{steps}"', creationflags=flags, close_fds=True)
