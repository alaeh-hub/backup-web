import os
import sys
import tempfile
from pathlib import Path

import pytest

# The app reads its state folder when it is imported, so point it at a throwaway folder first.
_STATE = tempfile.mkdtemp(prefix="ala-eh-test-state-")
os.environ["BACKUP_DATA_DIR"] = _STATE
os.environ.pop("BACKUP_PASSWORD", None)
os.environ.pop("BACKUP_HOST", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as backup  # noqa: E402

HOST = {"Host": "127.0.0.1:5000"}


class Rig:
    """A fake PC (a source folder) and a fake backup drive, both inside a temp folder."""

    def __init__(self, root: Path):
        self.root = root
        self.src = root / "src"
        self.dest = root / "dest"
        self.src.mkdir()
        self.dest.mkdir()
        self.client = backup.app.test_client()

    def write(self, rel: str, text: str = "x") -> Path:
        p = self.src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def get(self, path, **kw):
        return self.client.get(path, headers={**HOST, **kw.pop("headers", {})}, **kw)

    def post(self, path, body=None, headers=None):
        return self.client.post(path, json=body if body is not None else {}, headers={**HOST, **(headers or {})})

    def ids(self):
        return {os.path.basename(f["path"]): f["id"] for f in backup.INDEX.values()}

    def choose_all(self):
        self.post("/api/files/select", {"selected": True, "filter": {"status": "all"}})

    def on_drive(self):
        out = []
        for r, _, fs in os.walk(self.dest):
            for f in fs:
                if f not in ("choices.json.gz", "pc-id.json"):
                    out.append(os.path.relpath(os.path.join(r, f), self.dest))
        return sorted(out)

    def drive_copy(self, *parts) -> Path:
        return self.dest / backup.pc_folder(str(self.dest)) / "src" / Path(*parts)


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "DATA", tmp_path / "state")
    (tmp_path / "state").mkdir()
    backup.INDEX.clear()
    backup.GONE.clear()
    backup.HISTORY.clear()
    backup._PCF.clear()
    backup.FAILS.clear()
    backup.CANCEL.clear()
    backup.JOB.update(state="idle", type="", message="", done=0, total=0)
    r = Rig(tmp_path)
    monkeypatch.setitem(backup.SETTINGS, "whole_pc", False)
    monkeypatch.setitem(backup.SETTINGS, "sources", [str(r.src)])
    monkeypatch.setitem(backup.SETTINGS, "destinations", [str(r.dest)])
    monkeypatch.setitem(backup.SETTINGS, "excludes", [])
    monkeypatch.setitem(backup.SETTINGS, "skip_junk", True)
    monkeypatch.setitem(backup.SETTINGS, "compress", False)
    monkeypatch.setitem(backup.SETTINGS, "new_files", "review")
    monkeypatch.setitem(backup.SETTINGS, "max_size_mb", 0)
    return r
