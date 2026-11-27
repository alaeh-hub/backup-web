import zipfile

import app as backup
import preview
from test_wireless import pr, wired  # noqa: F401  (fixtures)

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
S = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
A = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'


def make_zip(path, parts):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in parts.items():
            z.writestr(name, data)
    return path


def docx(path, *paras):
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paras)
    return make_zip(path, {"word/document.xml": f"<w:document {W}><w:body>{body}</w:body></w:document>"})


def xlsx(path):
    return make_zip(path, {
        "xl/workbook.xml": f'<workbook {S}><sheets><sheet name="April" sheetId="1"/></sheets></workbook>',
        "xl/sharedStrings.xml": f"<sst {S}><si><t>Item</t></si><si><t>Rice</t></si></sst>",
        "xl/worksheets/sheet1.xml": f'<worksheet {S}><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1"><v>Qty</v></c></row>'
                                    f'<row r="2"><c r="A2" t="s"><v>1</v></c><c r="B2"><v>12</v></c></row></sheetData></worksheet>',
    })


def pptx(path):
    def slide(t):
        return f"<p:sld {A}><a:p><a:r><a:t>{t}</a:t></a:r></a:p></p:sld>"
    return make_zip(path, {"ppt/slides/slide1.xml": slide("Quarterly review"), "ppt/slides/slide2.xml": slide("Next steps")})


def info(rig, name):
    backup.scan_job()
    fid = rig.ids()[name]
    return rig.get(f"/api/preview/{fid}").json, fid


def test_text_is_shown_and_html_is_only_ever_text(rig):
    rig.write("notes.txt", "hello\nworld")
    rig.write("page.html", "<script>alert(1)</script><p>hi</p>")
    d, _ = info(rig, "notes.txt")
    assert d["mode"] == "text" and d["text"] == "hello\nworld" and d["source"] == "This PC"
    h, _ = info(rig, "page.html")
    assert h["mode"] == "text" and "<script>" in h["text"]                        # source, never rendered


def test_csv_and_spreadsheets_become_tables(rig):
    rig.write("a.csv", "name;qty\nrice;12\n")
    xlsx(rig.src / "april.xlsx")
    d, _ = info(rig, "a.csv")
    assert d["mode"] == "table" and d["sheets"][0]["rows"] == [["name", "qty"], ["rice", "12"]]
    x, _ = info(rig, "april.xlsx")
    assert x["sheets"][0]["name"] == "April" and x["sheets"][0]["rows"] == [["Item", "Qty"], ["Rice", "12"]]


def test_documents_and_slides_show_their_text(rig):
    docx(rig.src / "letter.docx", "Dear Ana", "See you soon")
    pptx(rig.src / "deck.pptx")
    d, _ = info(rig, "letter.docx")
    assert d["mode"] == "doc" and [b["runs"][0]["x"] for b in d["blocks"]] == ["Dear Ana", "See you soon"]
    p, _ = info(rig, "deck.pptx")
    assert [x["title"] for x in p["pages"]] == ["Slide 1", "Slide 2"] and p["pages"][1]["lines"] == ["Next steps"]


def test_an_archive_is_listed_not_unpacked(rig):
    make_zip(rig.src / "bundle.zip", {"a/one.txt": "1", "two.txt": "22"})
    d, _ = info(rig, "bundle.zip")
    assert d["mode"] == "archive" and sorted(e["name"] for e in d["entries"]) == ["a/one.txt", "two.txt"]


def test_every_other_file_still_shows_something(rig):
    (rig.src / "blob.bin").write_bytes(bytes(range(256)))
    (rig.src / "old.doc").write_bytes(b"\xd0\xcf\x11\xe0" + b"\x00" * 40 + b"Readable sentence in an old file" + b"\x00" * 30)
    (rig.src / "broken.docx").write_bytes(b"PK\x03\x04" + bytes(range(1, 200)))               # starts like a zip, is not one
    b, _ = info(rig, "blob.bin")
    assert b["mode"] == "hex" and b["hex"].startswith("000000  00 01 02")
    o, _ = info(rig, "old.doc")
    assert any("Readable sentence" in line for line in o["pages"][0]["lines"])
    r, _ = info(rig, "broken.docx")
    assert r["mode"] == "hex" and "could not be read" in r["note"]


def test_an_unknown_extension_that_is_text_is_shown_as_text(rig):
    rig.write("thing.zzz", "plain words inside")
    d, _ = info(rig, "thing.zzz")
    assert d["mode"] == "text" and d["text"] == "plain words inside"


def test_images_are_streamed_with_safe_headers_and_support_ranges(rig):
    (rig.src / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0123456789" * 50)
    d, fid = info(rig, "pic.png")
    assert d["mode"] == "image" and d["raw"] == f"/api/preview/{fid}/raw"
    r = rig.get(d["raw"])
    assert r.status_code == 200 and r.mimetype == "image/png" and r.headers["X-Content-Type-Options"] == "nosniff"
    assert "sandbox" in r.headers["Content-Security-Policy"]
    part = rig.get(d["raw"], headers={"Range": "bytes=0-9"})
    assert part.status_code == 206 and part.data == b"\x89PNG\r\n\x1a\n01"


def test_an_svg_with_a_script_is_served_in_a_sandbox(rig):
    rig.write("evil.svg", "<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>")
    _, fid = info(rig, "evil.svg")
    r = rig.get(f"/api/preview/{fid}/raw")
    assert r.mimetype == "image/svg+xml" and r.headers["Content-Security-Policy"].startswith("sandbox")


def test_a_pdf_is_served_inline_for_the_browsers_viewer(rig):
    (rig.src / "r.pdf").write_bytes(b"%PDF-1.4 fake")
    d, _ = info(rig, "r.pdf")
    assert d["mode"] == "pdf"
    r = rig.get(d["raw"])
    assert r.mimetype == "application/pdf" and "Content-Security-Policy" not in r.headers


def test_only_media_can_be_fetched_raw_and_unknown_ids_are_refused(rig):
    rig.write("notes.txt", "x")
    _, fid = info(rig, "notes.txt")
    assert rig.get(f"/api/preview/{fid}/raw").status_code == 415
    assert rig.get("/api/preview/nope").status_code == 404 and rig.get("/api/preview/nope/raw").status_code == 404


def test_a_file_deleted_from_the_pc_is_previewed_from_the_backup_drive(rig):
    p = rig.write("notes.txt", "kept on the drive")
    backup.scan_job()
    rig.choose_all()
    backup.backup_job()
    fid = rig.ids()["notes.txt"]
    p.unlink()
    d = rig.get(f"/api/preview/{fid}").json
    assert d["mode"] == "text" and d["text"] == "kept on the drive" and d["source"].startswith("Backup copy on")


def test_a_compressed_backup_copy_is_unpacked_to_preview(rig, monkeypatch):
    monkeypatch.setitem(backup.SETTINGS, "compress", True)
    docx(rig.src / "letter.docx", "Dear Ana")
    backup.scan_job()
    rig.choose_all()
    backup.backup_job()
    fid = rig.ids()["letter.docx"]
    (rig.src / "letter.docx").unlink()
    d = rig.get(f"/api/preview/{fid}").json
    assert d["mode"] == "doc" and d["blocks"][0]["runs"][0]["x"] == "Dear Ana" and d["source"].startswith("Backup copy")


def test_a_file_with_no_copy_anywhere_says_so(rig):
    p = rig.write("notes.txt", "x")
    backup.scan_job()
    fid = rig.ids()["notes.txt"]
    p.unlink()
    d = rig.get(f"/api/preview/{fid}").json
    assert d["mode"] == "none" and "no connected backup drive has a copy" in d["reason"]


def test_a_document_that_declares_entities_is_refused_not_expanded(rig):
    bomb = '<?xml version="1.0"?><!DOCTYPE lol [<!ENTITY a "aaaa">]><w:document ' + W + '><w:body><w:p><w:r><w:t>&a;</w:t></w:r></w:p></w:body></w:document>'
    make_zip(rig.src / "bomb.docx", {"word/document.xml": bomb})
    d, _ = info(rig, "bomb.docx")
    assert d["mode"] == "pages" and d["pages"][0]["lines"] == []


def test_a_big_text_file_is_cut_off(rig):
    rig.write("big.log", "line\n" * 100_000)
    d, _ = info(rig, "big.log")
    assert d["truncated"] is True and 0 < len(d["text"]) <= preview.MAX_TEXT


def test_another_pcs_file_is_previewed_live_and_then_from_the_drive(rig, wired):
    wired.write("Reports/q1.txt", "quarterly figures")
    backup.scan_job()
    fid = next(iter(backup.INDEX))
    d = rig.get(f"/api/preview/{fid}").json
    assert d["mode"] == "text" and d["text"] == "quarterly figures" and d["source"].startswith("Live from") and d["from_pc"] == "OFFICE-PC"
    rig.choose_all()
    backup.backup_job()
    d = rig.get(f"/api/preview/{fid}").json
    assert d["text"] == "quarterly figures" and d["source"].startswith("Backup copy")


def test_excel_dates_and_numbers_are_written_the_way_a_person_reads_them(rig):
    styles = (f'<styleSheet {S}><numFmts count="1"><numFmt numFmtId="164" formatCode="yyyy-mm-dd hh:mm"/></numFmts>'
              '<cellXfs count="3"><xf numFmtId="0"/><xf numFmtId="14"/><xf numFmtId="164"/></cellXfs></styleSheet>')
    sheet = (f'<worksheet {S}><sheetData><row r="1">'
             '<c r="A1" s="1"><v>46113</v></c><c r="B1" s="2"><v>46113.5</v></c><c r="C1"><v>3.5000000000000004</v></c>'
             '<c r="D1"><v>12</v></c><c r="E1" t="b"><v>1</v></c></row></sheetData></worksheet>')
    make_zip(rig.src / "dates.xlsx", {"xl/styles.xml": styles, "xl/worksheets/sheet1.xml": sheet})
    d, _ = info(rig, "dates.xlsx")
    assert d["sheets"][0]["rows"] == [["2026-04-01", "2026-04-01 12:00", "3.5", "12", "TRUE"]]


def _mp3(tag_frames):
    import struct
    tag = b"".join(fid + struct.pack(">I", len(body)) + b"\0\0" + body for fid, body in tag_frames)
    size = len(tag)
    syn = bytes([(size >> 21) & 127, (size >> 14) & 127, (size >> 7) & 127, size & 127])
    return b"ID3\x03\x00\x00" + syn + tag + (b"\xff\xfb\x90\x00" + b"\x00" * 413) * 4


def test_an_mp3_shows_its_title_artist_and_cover_from_the_tags(rig):
    jpeg = b"\xff\xd8\xff\xe0" + b"jpegdata" * 4
    (rig.src / "song.mp3").write_bytes(_mp3([(b"TIT2", b"\x00Silent song"), (b"TPE1", b"\x00The Quiet Band"), (b"TALB", b"\x00Nothing"),
                                             (b"TYER", b"\x002026"), (b"APIC", b"\x00image/jpeg\x00\x03\x00" + jpeg)]))
    (rig.src / "plain.mp3").write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 413)
    d, _ = info(rig, "song.mp3")
    assert d["mode"] == "audio" and d["raw"].endswith("/raw")
    assert {k: d["tags"][k] for k in ("title", "artist", "album", "year")} == {"title": "Silent song", "artist": "The Quiet Band", "album": "Nothing", "year": "2026"}
    assert d["tags"]["cover"].startswith("data:image/jpeg;base64,")
    p, _ = info(rig, "plain.mp3")
    assert p["tags"] == {}                                                         # no tag: the player falls back to the file name


def test_a_cover_that_is_not_really_an_image_is_ignored(rig):
    (rig.src / "odd.mp3").write_bytes(_mp3([(b"TIT2", b"\x00Odd"), (b"APIC", b"\x00image/png\x00\x03\x00" + b"<html><script>alert(1)</script>")]))
    d, _ = info(rig, "odd.mp3")
    assert d["tags"] == {"title": "Odd"}
