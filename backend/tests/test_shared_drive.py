import json
import os

import app as backup


def _other_pc(rig, rel, text):
    """Another PC's folder on the shared drive, holding one file."""
    root = rig.dest / "PC-A"
    root.mkdir(exist_ok=True)
    (root / "pc-id.json").write_text(json.dumps({"id": "other-pc-id", "name": "PC-A"}))
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def _run(rig):
    backup.scan_job()
    rig.choose_all()
    return backup.backup_job()


def test_a_file_another_pc_already_stored_is_reused_not_written_again(rig):
    theirs = _other_pc(rig, "Remote PCs/PC-X/Docs/report.docx", "same words")
    rig.write("Docs/report.docx", "same words")
    msg = _run(rig)
    mine = rig.drive_copy("Docs", "report.docx")
    assert mine.read_text() == "same words"
    assert os.path.samefile(mine, theirs)                       # one set of data, two names
    assert "reused" in msg and "1 already on the drive" in msg
    fid = rig.ids()["report.docx"]
    assert backup.status(backup.INDEX[fid], [str(rig.dest)]) == "backed_up"


def test_different_content_with_the_same_name_is_copied(rig):
    theirs = _other_pc(rig, "Docs/report.docx", "their version")
    rig.write("Docs/report.docx", "my version!!")
    msg = _run(rig)
    mine = rig.drive_copy("Docs", "report.docx")
    assert mine.read_text() == "my version!!" and theirs.read_text() == "their version"
    assert not os.path.samefile(mine, theirs) and "reused" not in msg


def test_changing_a_reused_file_later_never_alters_the_other_pcs_copy(rig):
    from test_backup import bump
    theirs = _other_pc(rig, "Docs/report.docx", "same words")
    p = rig.write("Docs/report.docx", "same words")
    _run(rig)
    p.write_text("edited here, longer")
    bump(p)
    backup.backup_job(scan_first=True)
    assert theirs.read_text() == "same words"
    assert rig.drive_copy("Docs", "report.docx").read_text() == "edited here, longer"


def test_a_drive_with_only_this_pc_behaves_as_before(rig):
    rig.write("Docs/a.txt", "alpha")
    msg = _run(rig)
    assert "reused" not in msg and rig.drive_copy("Docs", "a.txt").read_text() == "alpha"


def test_a_drive_that_cannot_link_falls_back_to_a_normal_copy(rig, monkeypatch):
    theirs = _other_pc(rig, "Docs/report.docx", "same words")
    rig.write("Docs/report.docx", "same words")
    monkeypatch.setattr(os, "link", lambda *a, **k: (_ for _ in ()).throw(OSError("no links here")))
    msg = _run(rig)
    mine = rig.drive_copy("Docs", "report.docx")
    assert mine.read_text() == "same words" and not os.path.samefile(mine, theirs) and "reused" not in msg


def test_compressed_copies_from_another_pc_are_found_too(rig, monkeypatch):
    import gzip
    monkeypatch.setitem(backup.SETTINGS, "compress", True)
    root = rig.dest / "PC-A"
    root.mkdir()
    (root / "pc-id.json").write_text(json.dumps({"id": "other-pc-id", "name": "PC-A"}))
    with gzip.open(root / "report.docx.gz", "wb") as o:
        o.write(b"same words")
    rig.write("Docs/report.docx", "same words")
    msg = _run(rig)
    assert "reused" in msg and os.path.samefile(rig.dest / backup.pc_folder(str(rig.dest)) / "src" / "Docs" / "report.docx.gz", root / "report.docx.gz")


def test_the_scan_recognises_files_another_pc_stored_and_does_not_show_them_as_new(rig):
    theirs = _other_pc(rig, "Remote PCs/PC-X/Docs/report.docx", "same words")
    mine = rig.write("Docs/report.docx", "same words")
    os.utime(theirs, (os.stat(mine).st_atime, os.stat(mine).st_mtime))      # a backup keeps the file's date
    rig.write("Docs/other.docx", "not stored anywhere yet")
    msg = backup.scan_job()
    assert "already on the backup drive from another PC" in msg
    by = {os.path.basename(f["path"]): f for f in backup.INDEX.values()}
    assert by["report.docx"]["selected"] == 1 and by["report.docx"]["reviewed"] is True
    assert by["other.docx"]["selected"] == 0 and by["other.docx"]["reviewed"] is False      # stays in New files
    backup.backup_job()
    assert os.path.samefile(rig.drive_copy("Docs", "report.docx"), theirs)


def test_recognition_can_be_turned_off(rig, monkeypatch):
    monkeypatch.setitem(backup.SETTINGS, "reuse_drive_copies", False)
    theirs = _other_pc(rig, "Docs/report.docx", "same words")
    mine = rig.write("Docs/report.docx", "same words")
    os.utime(theirs, (os.stat(mine).st_atime, os.stat(mine).st_mtime))
    backup.scan_job()
    f = next(iter(backup.INDEX.values()))
    assert f["selected"] == 0 and f["reviewed"] is False


def test_a_same_name_and_size_but_different_date_is_not_recognised(rig):
    theirs = _other_pc(rig, "Docs/report.docx", "same words")
    mine = rig.write("Docs/report.docx", "same words")
    os.utime(theirs, (1_000_000_000, 1_000_000_000))
    backup.scan_job()
    assert next(iter(backup.INDEX.values()))["reviewed"] is False
