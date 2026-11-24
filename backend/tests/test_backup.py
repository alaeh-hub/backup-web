import json
import os
import shutil

import pytest

import app as backup


def bump(path, seconds=5):
    st = os.stat(path)
    os.utime(path, (st.st_atime + seconds, st.st_mtime + seconds))


# ---------------------------------------------------------------- scan

def test_first_scan_holds_every_file_for_review(rig):
    rig.write("Docs/a.docx")
    rig.write("Docs/b.txt")
    msg = backup.scan_job()
    stats = rig.get("/api/stats").json
    assert stats["review_files"] == 2 and stats["backed_files"] == 0 and stats["pending_files"] == 0
    assert "2 new files are waiting for your review" in msg


def test_scan_skips_junk(rig):
    rig.write("Docs/keep.docx")
    rig.write("node_modules/x/lib.js")
    rig.write("Windows/system.dll")
    rig.write("Docs/~$lock.docx")
    rig.write("Docs/cache.tmp")
    backup.scan_job()
    assert sorted(rig.ids()) == ["keep.docx"]


def test_scan_with_nothing_to_scan_keeps_the_list(rig, monkeypatch):
    rig.write("a.txt")
    backup.scan_job()
    assert len(backup.INDEX) == 1
    monkeypatch.setitem(backup.SETTINGS, "sources", [])
    with pytest.raises(RuntimeError):
        backup.scan_job()
    assert len(backup.INDEX) == 1


def test_a_folder_that_cannot_be_read_keeps_its_records(rig, monkeypatch):
    rig.write("Docs/a.txt")
    rig.write("Other/b.txt")
    backup.scan_job()
    real = os.scandir

    def flaky(p):
        if str(p).endswith("Docs"):
            raise PermissionError("locked")
        return real(p)

    monkeypatch.setattr(os, "scandir", flaky)
    backup.scan_job()
    assert sorted(rig.ids()) == ["a.txt", "b.txt"]


def test_the_backup_drive_is_never_scanned(rig, monkeypatch):
    rig.write("a.txt")
    (rig.dest / "somewhere").mkdir()
    (rig.dest / "somewhere" / "old.txt").write_text("x")
    monkeypatch.setitem(backup.SETTINGS, "sources", [str(rig.dest)])
    backup.scan_job()
    assert backup.INDEX == {}


# ---------------------------------------------------------------- choosing and backing up

def test_only_chosen_files_are_copied(rig):
    rig.write("Docs/a.docx", "one")
    rig.write("Docs/b.txt", "two")
    backup.scan_job()
    rig.post("/api/files/select", {"selected": True, "ids": [rig.ids()["a.docx"]]})
    backup.backup_job()
    assert rig.on_drive() == [os.path.join(backup.pc_folder(str(rig.dest)), "src", "Docs", "a.docx")]


def test_quick_pick_previews_before_it_changes_anything(rig):
    rig.write("Documents/report.docx")
    rig.write("Videos/clip.mp4")
    backup.scan_job()
    dry = rig.post("/api/presets/apply", {"preset": "office", "replace_all": True, "dry": True}).json
    assert dry["backed"] == 1 and dry["skipped"] == 1
    assert rig.get("/api/stats").json["review_files"] == 2          # nothing changed yet
    rig.post("/api/presets/apply", {"preset": "office", "replace_all": True})
    stats = rig.get("/api/stats").json
    assert stats["pending_files"] == 1 and stats["skipped_files"] == 1 and stats["review_files"] == 0


def test_a_changed_file_replaces_its_backup_and_keeps_no_versions(rig):
    p = rig.write("Docs/report.docx", "v1")
    backup.scan_job()
    rig.choose_all()
    backup.backup_job()
    p.write_text("v1 and more text")
    bump(p)
    backup.backup_job(scan_first=True)
    assert rig.drive_copy("Docs", "report.docx").read_text() == "v1 and more text"
    assert not any(".versions" in f for f in rig.on_drive())


def test_everything_backed_up_says_so(rig):
    rig.write("a.txt")
    backup.scan_job()
    rig.choose_all()
    assert "waiting to back up" in backup.scan_job()
    backup.backup_job()
    assert "Everything is backed up" in backup.scan_job()
    assert "already backed up" in backup.backup_job()


def test_new_files_are_held_and_skipped_files_stay_skipped(rig):
    a = rig.write("Docs/a.txt")
    s = rig.write("Docs/skip.txt")
    backup.scan_job()
    rig.post("/api/files/select", {"selected": True, "ids": [rig.ids()["a.txt"]]})
    rig.post("/api/files/select", {"selected": False, "ids": [rig.ids()["skip.txt"]]})
    backup.backup_job()
    bump(s)
    rig.write("Docs/new.txt")
    backup.scan_job()
    review = [i["name"] for i in rig.get("/api/review").json["items"]]
    assert review == ["new.txt"]
    assert rig.get("/api/stats").json["skipped_files"] == 1
    assert a.exists()


def test_a_choice_made_during_a_scan_is_kept(rig, monkeypatch):
    rig.write("Docs/a.txt")
    backup.scan_job()
    fid = rig.ids()["a.txt"]
    real = os.scandir

    def scan_then_choose(p):
        rig.post("/api/files/select", {"selected": True, "ids": [fid]})   # the user clicks mid-scan
        monkeypatch.setattr(os, "scandir", real)
        return real(p)

    monkeypatch.setattr(os, "scandir", scan_then_choose)
    backup.scan_job()
    assert backup.INDEX[fid]["selected"] == 1


def test_select_never_treats_an_empty_request_as_everything(rig):
    rig.write("a.txt")
    backup.scan_job()
    assert rig.post("/api/files/select", {"selected": True, "ids": []}).json["changed"] == 0
    assert rig.post("/api/files/select", {"selected": True}).status_code == 400
    assert rig.get("/api/stats").json["review_files"] == 1


# ---------------------------------------------------------------- safety of the copies

def test_an_interrupted_copy_keeps_the_old_backup(rig, monkeypatch):
    p = rig.write("a.txt", "good copy")
    backup.scan_job()
    rig.choose_all()
    backup.backup_job()
    target = rig.drive_copy("a.txt")
    p.write_text("new content")
    bump(p)
    backup.scan_job()

    def boom(src, dst, **kw):
        with open(dst, "w") as f:
            f.write("partial")
        raise OSError("disk full")

    monkeypatch.setattr(shutil, "copy2", boom)
    backup.backup_job()
    monkeypatch.undo()
    assert target.read_text() == "good copy"
    assert not any(f.endswith(".part") for f in rig.on_drive())


def test_a_deleted_file_can_still_be_restored(rig):
    p = rig.write("Docs/a.docx", "important")
    backup.scan_job()
    rig.choose_all()
    backup.backup_job()
    p.unlink()
    backup.scan_job()
    assert any(r["path"] == str(p) for r in rig.get("/api/files?status=has_backup").json["rows"])
    fid = next(iter(backup.GONE))
    backup.restore_job([{"id": fid, "dest": str(rig.dest)}], "", False)
    assert p.read_text() == "important"


def test_restore_does_not_overwrite_unless_asked(rig):
    p = rig.write("a.txt", "backed up")
    backup.scan_job()
    rig.choose_all()
    backup.backup_job()
    p.write_text("changed on the PC")
    fid = rig.ids()["a.txt"]
    backup.restore_job([{"id": fid, "dest": str(rig.dest)}], "", False)
    assert p.read_text() == "changed on the PC"
    backup.restore_job([{"id": fid, "dest": str(rig.dest)}], "", True)
    assert p.read_text() == "backed up"


# ---------------------------------------------------------------- devices

def test_two_pcs_with_one_name_get_separate_folders(rig):
    folder = rig.dest / backup.PC_NAME
    folder.mkdir()
    (folder / "pc-id.json").write_text(json.dumps({"id": "another-pc", "name": backup.PC_NAME}))
    got = backup.pc_folder(str(rig.dest), create=True)
    assert got != backup.PC_NAME and got.startswith(backup.PC_NAME + "-")
    backup._PCF.clear()
    assert backup.pc_folder(str(rig.dest)) == got          # and it is recognised again next time


def test_devices_lists_every_pc_folder_on_the_drive(rig):
    rig.write("a.txt")
    backup.scan_job()
    rig.choose_all()
    backup.backup_job()
    other = rig.dest / "OFFICE-2"
    other.mkdir()
    (other / "pc-id.json").write_text(json.dumps({"id": "zzz", "name": "OFFICE-2", "user": "Ana"}))
    (rig.dest / "not-a-pc").mkdir()
    devices = rig.get("/api/devices").json[0]["devices"]
    assert [(d["name"], d["this_pc"]) for d in devices] == [(backup.PC["name"], True), ("OFFICE-2", False)]
    assert rig.get(f"/api/devices/size?dest={rig.dest}&folder=..").status_code == 400


def test_labels_are_safe_and_unique():
    out = backup.labels(["C:/..", "D:/CON", "E:/Docs", "F:/docs"])
    assert len(set(v.lower() for v in out.values())) == 4
    assert all(v not in ("", ".", "..") and v.upper() != "CON" for v in out.values())


# ---------------------------------------------------------------- who may call the API

def test_other_sites_cannot_use_the_api(rig):
    assert rig.client.get("/api/job", headers={"Host": "evil.example:5001"}).status_code == 403
    assert rig.post("/api/scan", headers={"Origin": "http://evil.example"}).status_code == 403
    assert rig.post("/api/job/cancel", headers={"Origin": "http://127.0.0.1:5174"}).status_code == 204   # the dev page
    assert rig.post("/api/job/cancel", headers={"Origin": "http://127.0.0.1:3000"}).status_code == 403


def test_network_paths_are_refused(rig):
    unc = "\\\\server\\share"
    assert rig.get("/api/browse", query_string={"path": unc}).status_code == 400
    assert rig.post("/api/restore", {"items": [{"id": "x", "dest": "y"}], "target": unc}).status_code == 400
    body = {**rig.get("/api/settings").json, "destinations": [unc]}
    assert rig.post("/api/settings", body).status_code == 400


def test_wrong_passwords_are_throttled(rig, monkeypatch):
    monkeypatch.setattr(backup, "PASSWORD", "right-password")
    codes = [rig.post("/api/auth/login", {"password": "nope"}).status_code for _ in range(6)]
    assert codes[:5] == [401] * 5 and codes[5] == 429
    backup.FAILS.clear()
    assert rig.post("/api/auth/login", {"password": 12345}).status_code == 401      # not a string
    assert rig.post("/api/auth/login", {"password": "right-password"}).status_code == 200
    assert rig.get("/api/job").status_code == 200
    monkeypatch.setattr(backup, "TOKENS", set())
    assert rig.get("/api/job").status_code == 401
