"""Desktop launcher for the packaged app (PyInstaller): runs the API on this PC and shows the UI in a native window."""
import os, socket, sys, threading

if sys.stdout is None or sys.stderr is None:      # windowed build has no console: keep print/logging from crashing
    sys.stdout = sys.stderr = open(os.devnull, "w")

import webview
from werkzeug.serving import make_server

import app as core

PORT = int(os.environ.get("BACKUP_PORT", "5000"))
URL = f"http://127.0.0.1:{PORT}"
TITLE = "Ala Eh! File Backup"


def already_running():
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def main():
    server = None
    if not already_running():                    # a second launch just opens another window on the running app
        threading.Thread(target=core.saver, daemon=True).start()
        threading.Thread(target=core.scheduler, daemon=True).start()
        server = make_server("127.0.0.1", PORT, core.app, threaded=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
    webview.create_window(TITLE, URL, width=1280, height=820, min_size=(420, 600), confirm_close=False)
    webview.start()                              # blocks until the window is closed
    if server:
        server.shutdown()


if __name__ == "__main__":
    main()
