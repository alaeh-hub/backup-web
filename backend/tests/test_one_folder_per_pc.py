"""One folder per PC on the shared drive, whichever PC does the backing up.

PC A backs up itself and PC B over the network. Later PC B backs itself up from the same drive. B's files must be found
where A put them (B's own folder), so nothing is stored twice and the Devices list shows one backup per PC."""
import json
import os
import shutil

import app as backup
from test_wireless import TAG, pr, wired  # noqa: F401  (fixtures)

B_ID = "b-id-1234567890"


def _become_b(monkeypatch, sources):
    """Run the app as PC B from now on: B's id and name, B's own folders as sources, no other PC to back up."""
    monkeypatch.setitem(backup.PC, "id", B_ID)
    monkeypatch.setitem(backup.PC, "name", "OFFICE-PC")
    monkeypatch.setitem(backup.SETTINGS, "sources", [str(s) for s in sources])
    monkeypatch.setitem(backup.SETTINGS, "remote_sources", [])
    backup._PCF.clear()
    backup.INDEX.clear()
    backup.GONE.clear()


def _a_backs_up_b(rig, wired):
    wired.write("Reports/q1.txt", "quarterly")
    wired.write("notes.txt", "notes")
    backup.scan_job()
    rig.choose_all()
    backup.backup_job()
    return rig.dest / "OFFICE-PC"


def test_the_other_pcs_files_go_in_its_own_folder_not_under_the_pc_that_backed_it_up(rig, wired):
    folder = _a_backs_up_b(rig, wired)
    assert (folder / "docs" / "Reports" / "q1.txt").read_text() == "quarterly"
    meta = json.loads((folder / "pc-id.json").read_text())
    assert meta["id"] == B_ID and meta["backed_up_by"] == [backup.PC["name"]] and meta["last_backup"]
    assert not (rig.dest / backup.pc_folder(str(rig.dest)) / "Remote PCs").exists()
    st = rig.get("/api/devices").json[0]["devices"]
    other = next(d for d in st if d["folder"] == "OFFICE-PC")
    assert other["this_pc"] is False and other["last_backup"] and other["backed_up_by"] == [backup.PC["name"]]


def test_when_that_pc_backs_itself_up_later_it_finds_its_files_where_the_other_pc_put_them(rig, wired, monkeypatch):
    folder = _a_backs_up_b(rig, wired)
    q1 = folder / "docs" / "Reports" / "q1.txt"
    before = q1.stat()
    a_folder = backup.pc_folder(str(rig.dest))
    _become_b(monkeypatch, [wired.docs])
    wired.write("new.txt", "made on B after the first backup")
    backup.scan_job()
    by = {os.path.basename(f["path"]): f for f in backup.INDEX.values()}
    assert by["q1.txt"]["selected"] == 1 and by["q1.txt"]["reviewed"] is True        # recognised, not shown as new
    assert by["notes.txt"]["reviewed"] is True
    assert by["new.txt"]["selected"] == 0 and by["new.txt"]["reviewed"] is False     # the only new file
    rig.choose_all()
    msg = backup.backup_job()
    assert backup.pc_folder(str(rig.dest)) == "OFFICE-PC"                               # B's own folder is the one A made
    assert "2 already on the drive at their place" in msg and "1 copied" in msg
    assert q1.stat().st_mtime_ns == before.st_mtime_ns                                  # not rewritten
    assert (folder / "docs" / "new.txt").read_text() == "made on B after the first backup"
    assert sorted(p.name for p in rig.dest.iterdir() if p.is_dir() and (p / "pc-id.json").exists()) == sorted(["OFFICE-PC", a_folder])   # one folder per PC
    assert all(backup.status(f, [str(rig.dest)]) == "backed_up" for f in backup.INDEX.values())
    assert "Everything is already backed up" in backup.backup_job()


def test_a_change_on_the_pc_is_the_only_thing_the_second_backup_copies(rig, wired, monkeypatch):
    folder = _a_backs_up_b(rig, wired)
    _become_b(monkeypatch, [wired.docs])
    backup.scan_job()
    rig.choose_all()
    backup.backup_job()
    p = wired.docs / "notes.txt"
    p.write_text("notes, edited on B")
    os.utime(p, (p.stat().st_atime, p.stat().st_mtime + 30))
    backup.scan_job()
    msg = backup.backup_job()
    assert "1 copied" in msg and (folder / "docs" / "notes.txt").read_text() == "notes, edited on B"
    assert (folder / "docs" / "Reports" / "q1.txt").read_text() == "quarterly"


def test_the_same_files_under_a_different_folder_name_are_linked_not_copied_again(rig, wired, monkeypatch, tmp_path):
    folder = _a_backs_up_b(rig, wired)
    mine = tmp_path / "my documents"                                   # B backs the same documents up from another folder name
    (mine / "Reports").mkdir(parents=True)
    copy = mine / "Reports" / "q1.txt"
    copy.write_text("quarterly")
    shutil.copystat(wired.docs / "Reports" / "q1.txt", copy)
    _become_b(monkeypatch, [mine])
    backup.scan_job()
    assert next(iter(backup.INDEX.values()))["reviewed"] is True
    rig.choose_all()
    msg = backup.backup_job()
    assert "reused" in msg
    assert os.path.samefile(folder / "my documents" / "Reports" / "q1.txt", folder / "docs" / "Reports" / "q1.txt")


def test_backups_made_by_versions_1_3_to_1_5_move_into_the_pc_folder(rig, wired, monkeypatch, tmp_path):
    real_label = backup.remote_label
    legacy = os.path.join("Remote PCs", TAG, "docs")
    monkeypatch.setattr(backup, "remote_label", lambda root: legacy)    # what the old versions wrote
    wired.write("Reports/q1.txt", "quarterly")
    backup.scan_job()
    rig.choose_all()
    backup.backup_job()
    own = rig.dest / backup.pc_folder(str(rig.dest))
    assert (own / "Remote PCs" / TAG / "docs" / "Reports" / "q1.txt").read_text() == "quarterly"
    assert backup.is_legacy_remote(next(iter(backup.INDEX.values())))
    monkeypatch.setattr(backup, "remote_label", real_label)
    assert "Everything is already backed up" in backup.backup_job()      # the next backup tidies up
    f = next(iter(backup.INDEX.values()))
    assert f["label"] == "docs" and not backup.is_legacy_remote(f)
    assert (rig.dest / "OFFICE-PC" / "docs" / "Reports" / "q1.txt").read_text() == "quarterly"
    assert not (own / "Remote PCs").exists()                             # nothing is left behind
    assert backup.status(f, [str(rig.dest)]) == "backed_up"
    out = tmp_path / "back"
    assert "Restored 1 files" in backup.restore_job([{"id": f["id"], "dest": str(rig.dest)}], str(out), False)
    assert (out / "OFFICE-PC" / "docs" / "Reports" / "q1.txt").read_text() == "quarterly"


def test_a_copy_this_pc_did_not_write_is_kept_as_a_version_when_it_is_replaced(rig):
    rig.write("Docs/a.txt", "my own words")
    other = rig.drive_copy("Docs", "a.txt")
    other.parent.mkdir(parents=True)
    other.write_text("somebody else's")
    backup.scan_job()
    rig.choose_all()
    backup.backup_job()
    assert other.read_text() == "my own words"
    kept = [p for p in (rig.dest / ".versions").rglob("*") if p.is_file()]
    assert len(kept) == 1 and kept[0].read_text() == "somebody else's"


def test_a_drive_with_one_pc_does_not_look_through_its_own_folder_for_copies(rig):
    rig.write("Docs/a.txt", "alpha")
    backup.scan_job()
    rig.choose_all()
    backup.backup_job()
    assert backup.written_by_others(str(rig.dest)) is False
    assert backup.make_catalog(str(rig.dest)).usable is False
