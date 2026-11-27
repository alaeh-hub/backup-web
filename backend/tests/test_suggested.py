import os
import time

import app as backup


def rec(path, age_days, size=5000, atime=None):
    now = time.time()
    return {"path": path, "mtime": now - age_days * 86400, "atime": atime or 0, "size": size}


def test_recent_documents_in_the_usual_places_outrank_old_installers():
    a, why = backup.importance(rec(r"C:\Users\me\Documents\budget.xlsx", 0.1))
    b, _ = backup.importance(rec(r"C:\Users\me\Downloads\setup.exe", 400, size=9e8))
    assert a > b + 60 and "Edited today" in why and "Spreadsheets" in why and "In Documents" in why


def test_opening_a_file_counts_as_using_it():
    now = time.time()
    s, why = backup.importance(rec(r"C:\Users\me\Pictures\trip.jpg", 200, atime=now - 3600 * 5))
    assert "Opened today" in why


def test_suggested_lists_the_best_new_files_first_and_the_backup_copies_them_first(rig):
    old = rig.write("Documents/old.txt", "a" * 3000)
    new = rig.write("Documents/new.docx", "b" * 3000)
    t = time.time()
    os.utime(old, (t - 500 * 86400, t - 500 * 86400))
    backup.scan_job()
    got = rig.get("/api/suggested").json
    assert got["total"] == 2 and [i["name"] for i in got["items"]] == ["new.docx"]
    assert got["items"][0]["reason"].startswith("Edited today")
    rig.choose_all()
    order = []
    real = backup.copy_to
    backup.copy_to = lambda d, f, h: (order.append(os.path.basename(f["path"])), real(d, f, h))[1]
    try:
        backup.backup_job()
    finally:
        backup.copy_to = real
    assert order == ["new.docx", "old.txt"]


def test_files_can_be_sorted_by_importance(rig):
    a = rig.write("Documents/a.txt", "a" * 3000)
    rig.write("Documents/b.docx", "b" * 3000)
    t = time.time()
    os.utime(a, (t - 400 * 86400, t - 400 * 86400))
    backup.scan_job()
    rows = rig.get("/api/files?sort=score&dir=desc").json["rows"]
    assert [os.path.basename(r["path"]) for r in rows] == ["b.docx", "a.txt"]
