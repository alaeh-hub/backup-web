"""Ala Eh! File Backup launcher: `py app.py` starts the Flask backend AND the React/TypeScript
frontend (Vite dev server, hot reload) together, opens the browser, and stops both on Ctrl+C.

Env: FRONTEND_PORT [5174], BACKUP_PORT [5001], NO_BROWSER=1 to skip opening the browser.
"""
import os, shutil, subprocess, sys, time, webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
FRONT_PORT = os.environ.get("FRONTEND_PORT", "5174")
BACK_PORT = os.environ.get("BACKUP_PORT", "5001")


def run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd).returncode == 0


def stop(proc):
    if proc.poll() is not None:
        return
    if os.name == "nt":  # kill the whole tree (npm -> node -> vite)
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        proc.terminate()


def main():
    npm = shutil.which("npm")
    if not npm:
        sys.exit("npm not found. Install Node.js from https://nodejs.org and try again.")

    print("[setup] checking Python packages...")
    if not run([sys.executable, "-m", "pip", "install", "-q", "-r", str(BACKEND / "requirements.txt")], ROOT):
        sys.exit("pip install failed.")
    if not (FRONTEND / "node_modules").exists():
        print("[setup] installing frontend packages (first run only)...")
        if not run([npm, "install"], FRONTEND):
            sys.exit("npm install failed.")

    procs = []
    try:
        print(f"[start] backend  -> http://127.0.0.1:{BACK_PORT}")
        procs.append(subprocess.Popen([sys.executable, str(BACKEND / "app.py")], cwd=BACKEND))
        print(f"[start] frontend -> http://127.0.0.1:{FRONT_PORT}")
        procs.append(subprocess.Popen(
            [npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", FRONT_PORT, "--strictPort"], cwd=FRONTEND))

        if not os.environ.get("NO_BROWSER"):
            time.sleep(3)
            webbrowser.open(f"http://127.0.0.1:{FRONT_PORT}")
        print("[ready] press Ctrl+C to stop both.")

        while all(p.poll() is None for p in procs):
            time.sleep(0.5)
        print("[exit] a process stopped; shutting down.")
    except KeyboardInterrupt:
        print("\n[exit] stopping...")
    finally:
        for p in procs:
            stop(p)


if __name__ == "__main__":
    main()
