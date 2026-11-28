"""A different drive on the backup location: told clearly, and accepted with one choice instead of a workaround."""
import pytest

import app as backup


@pytest.fixture
def usb(rig, monkeypatch):
    """The backup drive is remembered as the USB stick (serial AAAA0000), and files are backed up to it."""
    now = {"v": ("USB stick", "AAAA0000")}
    monkeypatch.setattr(backup, "volume_info", lambda p: now["v"])
    monkeypatch.setattr(backup, "refresh_destinations", lambda force=False: None)
    monkeypatch.setitem(backup.SETTINGS, "dest_vols", {str(rig.dest): "AAAA0000"})
    rig.write("Docs/a.txt", "first file")
    rig.write("Docs/b.txt", "second file")
    backup.scan_job()
    rig.choose_all()
    backup.backup_job()
    assert rig.get("/api/stats").json["backed_files"] == 2
    rig.now = now
    return rig


def _swap(rig, name="Seagate HDD", serial="BBBB0000"):
    rig.now["v"] = (name, serial)


def test_the_same_drive_is_not_a_change(usb):
    assert backup.drive_change(str(usb.dest)) is None
    assert usb.get("/api/settings").json["new_drives"] == []
    assert usb.post("/api/destinations/use-new", {"path": str(usb.dest)}).status_code == 400


def test_a_different_drive_is_refused_with_a_clear_message_and_offered(usb):
    _swap(usb)
    with pytest.raises(RuntimeError, match="Use this drive"):
        backup.backup_job()
    st = usb.get("/api/stats").json
    assert st["destinations"][0]["new_drive"] == {"name": "Seagate HDD"}
    alert = next(a for a in st["alerts"] if a["key"].startswith("drive:"))
    assert alert["level"] == "error" and "Seagate HDD" in alert["text"] and "Use this drive" in alert["text"]
    assert usb.get("/api/settings").json["new_drives"] == [{"path": str(usb.dest), "name": "Seagate HDD"}]


def test_using_the_new_drive_remembers_it_and_copies_everything_to_it(usb):
    _swap(usb)
    r = usb.post("/api/destinations/use-new", {"path": str(usb.dest)})
    assert r.status_code == 200 and r.json["files"] == 2
    assert backup.SETTINGS["dest_vols"][str(usb.dest)] == "BBBB0000"
    st = usb.get("/api/stats").json
    assert st["backed_files"] == 0 and st["pending_files"] == 2                 # nothing counts as backed up on the new drive
    assert st["destinations"][0]["new_drive"] is None and not any(a["key"].startswith("drive:") for a in st["alerts"])
    backup.backup_job()                                                          # no longer refused
    assert usb.get("/api/stats").json["backed_files"] == 2
    assert usb.drive_copy("Docs", "a.txt").read_text() == "first file"


def test_it_is_protected_again_afterwards(usb):
    _swap(usb)
    usb.post("/api/destinations/use-new", {"path": str(usb.dest)})
    _swap(usb, "Another disk", "CCCC0000")                                       # a third drive takes the letter
    with pytest.raises(RuntimeError, match="different drive"):
        backup.backup_job()


def test_files_already_on_the_new_drive_are_kept_not_written_again(usb):
    _swap(usb)
    usb.post("/api/destinations/use-new", {"path": str(usb.dest)})               # the files are still in place on disk
    msg = backup.backup_job()
    assert "already on the drive" in msg and "0 copied" in msg


def test_it_cannot_be_used_for_the_wrong_things(usb):
    _swap(usb)
    assert usb.post("/api/destinations/use-new", {"path": "Z:\nowhere"}).status_code == 400   # not a backup drive
    backup.JOB["state"] = "running"
    try:
        assert usb.post("/api/destinations/use-new", {"path": str(usb.dest)}).status_code == 409
    finally:
        backup.JOB["state"] = "idle"
    usb.now["v"] = None                                                            # unplugged: nothing to switch to
    assert backup.drive_change(str(usb.dest)) is None
    assert usb.post("/api/destinations/use-new", {"path": str(usb.dest)}).status_code == 400
    assert backup.SETTINGS["dest_vols"][str(usb.dest)] == "AAAA0000"
