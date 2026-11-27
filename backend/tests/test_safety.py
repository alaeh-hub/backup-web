import os

import app as backup
from test_backup import bump


def _backed_up(rig, text="v1"):
    p = rig.write("Docs/report.docx", text)
    backup.scan_job()
    rig.choose_all()
    backup.backup_job()
    return p


def test_verify_remembers_its_result_and_alerts_on_damage(rig, monkeypatch):
    monkeypatch.setitem(backup.META, "last_verify", None)
    _backed_up(rig)
    backup.verify_job()
    assert backup.META["last_verify"]["bad"] == 0 and rig.get("/api/stats").json["last_verify"]["ok"] == 1
    rig.drive_copy("Docs", "report.docx").write_text("damaged")
    backup.verify_job()
    st = rig.get("/api/stats").json
    assert st["last_verify"]["bad"] == 1 and any(a["key"].startswith("verify:") for a in st["alerts"])
    monkeypatch.setitem(backup.META, "last_verify", None)


def test_older_versions_are_kept_and_restored_beside_the_file(rig, monkeypatch):
    monkeypatch.setitem(backup.SETTINGS, "keep_versions", 2)
    p = _backed_up(rig, "first")
    p.write_text("second version")
    bump(p)
    backup.backup_job(scan_first=True)
    assert any(".versions" in f for f in rig.on_drive())
    fid = rig.ids()["report.docx"]
    vs = rig.get(f"/api/files/{fid}/versions").json
    assert len(vs) == 1
    out = rig.root / "restored"
    rig.post("/api/restore", {"items": [{"id": fid, "dest": str(rig.dest), "version": vs[0]["version"]}], "target": str(out)})
    for _ in range(100):
        if backup.JOB["state"] != "running":
            break
        import time; time.sleep(0.05)
    got = [f for f in out.rglob("*") if f.is_file()]
    assert len(got) == 1 and "(version " in got[0].name and got[0].read_text() == "first"


def test_alerts_for_a_full_drive_a_stale_backup_and_a_failed_run(rig, monkeypatch):
    _backed_up(rig)
    monkeypatch.setitem(backup.META, "last_backup", "2020-01-01 10:00:00")
    monkeypatch.setitem(backup.SETTINGS, "alert_stale_days", 7)
    keys = [a["key"] for a in rig.get("/api/stats").json["alerts"]]
    assert "stale" in keys
    monkeypatch.setitem(backup.SETTINGS, "alert_stale_days", 0)
    assert "stale" not in [a["key"] for a in rig.get("/api/stats").json["alerts"]]
    monkeypatch.setitem(backup.SETTINGS, "alert_low_space_pct", 100)
    assert any(a["key"].startswith("low:") for a in rig.get("/api/stats").json["alerts"])
    monkeypatch.setitem(backup.SETTINGS, "alert_low_space_pct", 0)
    backup.HISTORY.append({"at": "2026-01-01 00:00:00", "failed": 2, "copied": 0, "skipped": 0, "copied_bytes": 0, "seconds": 0, "trigger": "manual"})
    assert any(a["key"].startswith("failed:") for a in rig.get("/api/stats").json["alerts"])


def test_a_missing_drive_is_an_alert(rig, monkeypatch):
    _backed_up(rig)
    monkeypatch.setitem(backup.SETTINGS, "dest_vols", {str(rig.dest): "DEADBEEF"})
    monkeypatch.setattr(backup, "volume_info", lambda p: ("X", "00000001"))
    a = rig.get("/api/stats").json["alerts"]
    assert any(x["key"].startswith("drive:") and x["level"] == "error" for x in a)


def test_alerts_reach_the_webhook_once_a_day(rig, monkeypatch):
    _backed_up(rig)
    sent = []
    monkeypatch.setattr(backup, "notify", lambda t: sent.append(t) or (True, ""))
    monkeypatch.setitem(backup.SETTINGS, "webhook", "http://example.invalid/hook")
    monkeypatch.setitem(backup.SETTINGS, "alert_low_space_pct", 100)
    monkeypatch.setitem(backup.META, "alerted", {})
    backup.ALERT_EVERY[0] = 0
    backup.alert_check()
    n = len(sent)
    assert n >= 1
    backup.ALERT_EVERY[0] = 0
    backup.alert_check()
    assert len(sent) == n


def test_the_new_settings_are_saved_and_clamped(rig):
    s = rig.get("/api/settings").json
    s.update(keep_versions=99, alert_low_space_pct=5, alert_stale_days=-3)
    out = rig.post("/api/settings", s).json
    assert out["keep_versions"] == 20 and out["alert_low_space_pct"] == 5 and out["alert_stale_days"] == 0
    s.update(keep_versions=0, alert_low_space_pct=10, alert_stale_days=7)
    rig.post("/api/settings", s)
