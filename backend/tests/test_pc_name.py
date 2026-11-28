"""Naming this PC: asked once on a new install, kept on the drive as the PC's folder, and renamable later."""
import json
import os

import pytest

import app as backup


@pytest.fixture
def named(rig, monkeypatch):
    monkeypatch.setitem(backup.PC, "name", "OFFICE-PC")
    monkeypatch.setitem(backup.PC, "named", True)
    backup._PCF.clear()
    return rig


def _backup(rig, rel="Docs/report.docx", text="v1"):
    rig.write(rel, text)
    backup.scan_job()
    rig.choose_all()
    backup.backup_job()


def _folders(rig):
    return sorted(p.name for p in rig.dest.iterdir() if p.is_dir() and not p.name.startswith("."))


def test_a_new_install_is_asked_and_an_existing_one_is_not(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "DATA", tmp_path / "fresh")
    (tmp_path / "fresh").mkdir()
    pc = backup._load_pc()
    assert pc["named"] is False and pc["name"] and pc["id"]
    again = backup._load_pc()                                   # it stays unnamed until the person answers
    assert again["named"] is False and again["id"] == pc["id"]
    old = tmp_path / "old"
    old.mkdir()
    (old / "pc.json").write_text(json.dumps({"id": "abc", "name": "SHOP-PC"}))   # written by a version that never asked
    monkeypatch.setattr(backup, "DATA", old)
    assert backup._load_pc()["named"] is True


def test_the_page_is_told_whether_this_pc_still_needs_a_name(named, monkeypatch):
    assert named.get("/api/stats").json["pc_named"] is True
    monkeypatch.setitem(backup.PC, "named", False)
    backup.mark()                                              # the page's numbers are rebuilt after a change
    assert named.get("/api/stats").json["pc_named"] is False


def test_naming_the_pc_saves_it_and_marks_it_named(named, monkeypatch):
    monkeypatch.setitem(backup.PC, "named", False)
    r = named.post("/api/pc/name", {"name": "  Front   desk laptop "})
    assert r.status_code == 200 and r.json["name"] == "Front desk laptop" and r.json["folder"] == "Front_desk_laptop"
    assert backup.PC["name"] == "Front desk laptop" and backup.PC["named"] is True
    assert json.loads((backup.DATA / "pc.json").read_text())["name"] == "Front desk laptop"
    assert named.get("/api/stats").json["pc_name"] == "Front desk laptop"


@pytest.mark.parametrize("bad", ["", "   ", "x" * 41, "!!!", "tab\there\x01"])
def test_a_bad_name_is_refused_with_a_reason(named, bad):
    r = named.post("/api/pc/name", {"name": bad})
    assert r.status_code == 400 and r.json["error"]
    assert backup.PC["name"] == "OFFICE-PC"
    p = named.get("/api/pc/preview", query_string={"name": bad}).json
    assert p["ok"] is False and p["error"]


def test_the_preview_shows_the_folder_and_warns_about_a_name_another_pc_has(named):
    other = named.dest / "Accounting"
    other.mkdir()
    (other / "pc-id.json").write_text(json.dumps({"id": "zzz", "name": "Accounting"}))
    p = named.get("/api/pc/preview", query_string={"name": "Sales / North"}).json
    assert p == {"ok": True, "name": "Sales / North", "folder": "Sales_North", "taken": False}
    assert named.get("/api/pc/preview", query_string={"name": "accounting"}).json["taken"] is True


def test_renaming_renames_the_folder_on_the_drive_and_everything_still_works(named, monkeypatch):
    monkeypatch.setitem(backup.SETTINGS, "keep_versions", 2)
    _backup(named, text="first")
    assert _folders(named) == ["OFFICE-PC"]
    p = named.src / "Docs" / "report.docx"
    p.write_text("second version")
    os.utime(p, (p.stat().st_atime, p.stat().st_mtime + 30))
    backup.backup_job(scan_first=True)
    assert (named.dest / ".versions" / "OFFICE-PC").is_dir()
    r = named.post("/api/pc/name", {"name": "Reception PC"}).json
    assert r["renamed"] == [str(named.dest)] and r["pending"] == []
    assert _folders(named) == ["Reception_PC"] and (named.dest / ".versions" / "Reception_PC").is_dir()
    assert not (named.dest / ".versions" / "OFFICE-PC").exists()
    meta = json.loads((named.dest / "Reception_PC" / "pc-id.json").read_text())
    assert meta["id"] == backup.PC["id"] and meta["name"] == "Reception PC"
    assert named.get("/api/stats").json["pending_files"] == 0                     # nothing is backed up again
    assert [(d["name"], d["this_pc"]) for d in named.get("/api/devices").json[0]["devices"]] == [("Reception PC", True)]
    backup.verify_job()
    assert backup.META["last_verify"]["bad"] == 0
    fid = named.ids()["report.docx"]
    assert len(named.get(f"/api/files/{fid}/versions").json) == 1                # the older version is still found
    p.write_text("third")
    os.utime(p, (p.stat().st_atime, p.stat().st_mtime + 60))
    backup.backup_job(scan_first=True)
    assert _folders(named) == ["Reception_PC"]                                    # new files go into the renamed folder


def test_a_rename_never_touches_another_pcs_folder(named):
    _backup(named)
    other = named.dest / "Reception_PC"
    other.mkdir()
    (other / "pc-id.json").write_text(json.dumps({"id": "zzz", "name": "Reception PC"}))
    r = named.post("/api/pc/name", {"name": "Reception PC"}).json
    assert r["renamed"] == [str(named.dest)]
    assert json.loads((other / "pc-id.json").read_text())["id"] == "zzz"
    mine = [f for f in _folders(named) if f != "Reception_PC"]
    assert len(mine) == 1 and mine[0].startswith("Reception_PC-")                 # the app added a short suffix instead
    assert backup.pc_folder(str(named.dest)) == mine[0]


def test_a_rename_waits_when_the_drive_is_away_and_catches_up_at_the_next_backup(named, monkeypatch):
    _backup(named)
    real = backup.os.path.isdir
    away = {"on": True}
    monkeypatch.setattr(backup.os.path, "isdir", lambda p: False if away["on"] and str(p) == str(named.dest) else real(p))
    r = named.post("/api/pc/name", {"name": "Reception PC"}).json
    assert r["renamed"] == [] and r["pending"] == [str(named.dest)]
    away["on"] = False
    assert _folders(named) == ["OFFICE-PC"]                                       # still the old name on the drive
    assert backup.pc_folder(str(named.dest)) == "OFFICE-PC"                        # and still found by the id
    named.write("Docs/more.txt", "new file")
    backup.scan_job()
    named.choose_all()
    backup.backup_job()
    assert _folders(named) == ["Reception_PC"]


def test_a_rename_during_a_backup_is_left_for_the_next_one(named):
    _backup(named)
    backup.JOB["state"] = "running"
    try:
        r = named.post("/api/pc/name", {"name": "Reception PC"}).json
    finally:
        backup.JOB["state"] = "idle"
    assert r["renamed"] == [] and r["pending"] == [str(named.dest)] and _folders(named) == ["OFFICE-PC"]
    backup.backup_job()
    assert _folders(named) == ["Reception_PC"]


def test_a_folder_that_cannot_be_renamed_keeps_working_under_the_old_name(named, monkeypatch):
    _backup(named)
    real = os.rename

    def locked(a, b, *args, **kw):
        if os.path.basename(str(a)) == "OFFICE-PC":
            raise PermissionError("in use by another process")
        return real(a, b, *args, **kw)
    monkeypatch.setattr(backup.os, "rename", locked)
    r = named.post("/api/pc/name", {"name": "Reception PC"})
    assert r.status_code == 200 and r.json["pending"] == [str(named.dest)] and r.json["name"] == "Reception PC"
    assert _folders(named) == ["OFFICE-PC"] and backup.pc_folder(str(named.dest)) == "OFFICE-PC"
    named.write("Docs/more.txt", "x")
    backup.scan_job()
    named.choose_all()
    assert "failed" in backup.backup_job() and backup.META["last_backup"]
    assert named.get("/api/stats").json["pending_files"] == 0
