"""Desktop launcher for the packaged app (PyInstaller): runs the API on this PC and shows the UI in a native window."""
import json, os, socket, sys, threading, urllib.request
from pathlib import Path

if sys.stdout is None or sys.stderr is None:      # windowed build has no console: keep print/logging from crashing
    sys.stdout = sys.stderr = open(os.devnull, "w")

if "--selftest" in sys.argv:
    # `AlaEhBackup.exe --selftest <result file>`: load every part of the packaged app (the crypto library, the sharing code,
    # the window) and exit, so a build that is missing a piece is caught when it is built, not on a user's PC.
    import traceback
    _out = sys.argv[sys.argv.index("--selftest") + 1]
    try:
        import tempfile
        _tmp = tempfile.mkdtemp(prefix="aeb-selftest-")
        os.environ["BACKUP_DATA_DIR"] = _tmp
        import webview, app as _app, agent, remote, pki, updater          # noqa: F401
        from spake2 import SPAKE2_A, SPAKE2_B
        _ident = pki.Identity(os.path.join(_tmp, "agent"))
        pki.server_context(_ident, "")
        pki.client_context(_ident)
        _a, _b = SPAKE2_A(b"123456"), SPAKE2_B(b"123456")
        _ma, _mb = _a.start(), _b.start()
        assert _a.finish(_mb) == _b.finish(_ma)
        _msg = "ok"
    except BaseException:
        _msg = traceback.format_exc()
    with open(_out, "w", encoding="utf8") as _f:
        _f.write(_msg)
    os._exit(0 if _msg == "ok" else 1)

import webview
from werkzeug.serving import make_server

import app as core
import updater

# Its own default port, so the installed app never collides with a dev copy (dev backend: 5001).
PORT = int(os.environ.get("BACKUP_PORT", "5100"))
TITLE = "Ala Eh! File Backup"
ICON = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent / "installer")) / "app.ico"


def busy(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def version_on(port):
    """The version of the Ala Eh backup server answering on this port, or None if it is something else."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/auth/status", timeout=1.5) as r:
            return json.loads(r.read().decode("utf8")).get("version")
    except Exception:
        return None


def choose_port():
    """(port, start_server). Reuse a running copy only if it is this exact version; an older leftover copy is
    never reused (its window would show the old app), so a free port is taken instead."""
    port = PORT
    for _ in range(30):
        if not busy(port):
            return port, True
        if version_on(port) == updater.current_version():
            return port, False
        port += 1
    raise SystemExit("No free port found.")


def main():
    port, start = choose_port()
    server = None
    if start:
        threading.Thread(target=core.saver, daemon=True).start()
        threading.Thread(target=core.scheduler, daemon=True).start()
        server = make_server("127.0.0.1", port, core.app, threaded=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
    window = webview.create_window(TITLE, f"http://127.0.0.1:{port}", width=1280, height=820, min_size=(420, 600), confirm_close=False)

    def pick_folder():                           # the normal Windows folder window
        kind = webview.FileDialog.FOLDER if hasattr(webview, "FileDialog") else webview.FOLDER_DIALOG
        r = window.create_file_dialog(kind)
        return r[0] if r else None

    core.PICKER["fn"] = pick_folder
    # an update closes the window cleanly (so the exe's wrapper process exits too) before the installer runs
    core.EXIT_HOOK = lambda: [w.destroy() for w in list(webview.windows)]
    webview.start(icon=str(ICON) if ICON.exists() else None)       # blocks until the window is closed
    if server:
        server.shutdown()


if __name__ == "__main__":
    main()
