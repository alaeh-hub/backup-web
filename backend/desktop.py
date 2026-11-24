"""Desktop launcher for the packaged app (PyInstaller): serves the UI + API on this PC and opens the browser."""
import socket, sys, threading, webbrowser

import app as core
from werkzeug.serving import make_server

PORT = int(core.os.environ.get("BACKUP_PORT", "5000"))
URL = f"http://127.0.0.1:{PORT}"


def already_running():
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def main():
    if already_running():                       # a second click just reopens the page
        webbrowser.open(URL)
        return
    threading.Thread(target=core.saver, daemon=True).start()
    threading.Thread(target=core.scheduler, daemon=True).start()
    server = make_server("127.0.0.1", PORT, core.app, threaded=True)
    print(f"Ala Eh! File Backup is running at {URL}")
    print("Keep this window open while you use it. Close it to stop the app.")
    threading.Timer(1.0, webbrowser.open, args=(URL,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
