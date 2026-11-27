"""Word files drawn as pages, the pictures inside them, and files that are not what their name says."""
import struct
import zlib

import app as backup
from test_preview import W, docx, info, make_zip

DRAWING = ('<w:r><w:drawing><wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"><wp:extent cx="{cx}" cy="{cy}"/>'
           '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:graphicData><pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
           '<pic:blipFill><a:blip xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:embed="rId5"/></pic:blipFill></pic:pic></a:graphicData></a:graphic>'
           '</wp:inline></w:drawing></w:r>')
RELS = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId5" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image1.png"/></Relationships>')


def png_bytes():
    def chunk(t, data):
        c = struct.pack(">I", len(data)) + t + data
        return c + struct.pack(">I", zlib.crc32(t + data) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b"")


def styled_docx(path):
    styles = f'<w:styles {W}><w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:rPr><w:b/><w:sz w:val="36"/></w:rPr></w:style></w:styles>'
    numbering = (f'<w:numbering {W}><w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl></w:abstractNum>'
                 '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>')
    item = '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t>{}</w:t></w:r></w:p>'
    body = ('<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Title here</w:t></w:r></w:p>'
            '<w:p><w:r><w:rPr><w:b/><w:i/></w:rPr><w:t>bold italic</w:t></w:r><w:r><w:t xml:space="preserve"> plain</w:t></w:r></w:p>'
            + item.format("first") + item.format("second")
            + '<w:tbl><w:tblPr><w:tblBorders><w:top w:val="single"/></w:tblBorders></w:tblPr><w:tr><w:tc><w:tcPr><w:shd w:fill="D9E2F3"/></w:tcPr>'
              '<w:p><w:r><w:t>cell</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
            + "<w:p>" + DRAWING.format(cx=1905000, cy=952500) + "</w:p>")
    return make_zip(path, {"word/document.xml": f"<w:document {W}><w:body>{body}</w:body></w:document>", "word/styles.xml": styles,
                           "word/numbering.xml": numbering, "word/_rels/document.xml.rels": RELS, "word/media/image1.png": png_bytes()})


def test_a_word_file_is_drawn_with_its_formatting_lists_tables_and_pictures(rig):
    styled_docx(rig.src / "styled.docx")
    d, _ = info(rig, "styled.docx")
    assert d["mode"] == "doc" and d["images"] == 1
    paras = [b for b in d["blocks"] if b["t"] == "p"]
    assert paras[0]["h"] == "h1" and paras[0]["runs"][0]["b"] == 1 and paras[0]["runs"][0]["sz"] == 18
    assert paras[1]["runs"][0]["b"] == 1 and paras[1]["runs"][0]["i"] == 1 and paras[1]["runs"][0]["x"] == "bold italic"
    assert [p["label"] for p in paras if "label" in p] == ["1.", "2."]
    table = next(b for b in d["blocks"] if b["t"] == "table")
    assert table["grid"] == 1 and table["rows"][0][0]["fill"] == "D9E2F3" and table["rows"][0][0]["blocks"][0]["runs"][0]["x"] == "cell"
    pic = next(r for b in paras for r in b["runs"] if "img" in r)
    assert pic["img"] == "word/media/image1.png" and pic["w"] == 200


def test_pictures_inside_a_word_file_are_served_safely(rig):
    styled_docx(rig.src / "styled.docx")
    rig.write("plain.txt", "x")
    _, fid = info(rig, "styled.docx")
    ok = rig.get(f"/api/preview/{fid}/part?name=word/media/image1.png")
    assert ok.status_code == 200 and ok.mimetype == "image/png" and ok.data == png_bytes() and ok.headers["X-Content-Type-Options"] == "nosniff"
    assert "sandbox" in ok.headers["Content-Security-Policy"]
    for bad in ("word/document.xml", "word/media/../document.xml", "../x.png", "word/media/image1.svg", "word/media/missing.png"):
        assert rig.get(f"/api/preview/{fid}/part", query_string={"name": bad}).status_code in (400, 404)
    txt = rig.ids()["plain.txt"]
    assert rig.get(f"/api/preview/{txt}/part?name=word/media/image1.png").status_code == 400      # only Office files have parts


def test_a_book_of_page_pictures_with_no_text_shows_the_pictures(rig):
    body = "".join("<w:p>" + DRAWING.format(cx=952500, cy=952500) + "</w:p>" for _ in range(3))
    make_zip(rig.src / "book.docx", {"word/document.xml": f"<w:document {W}><w:body>{body}</w:body></w:document>", "word/_rels/document.xml.rels": RELS,
                                     "word/media/image1.png": png_bytes()})
    d, _ = info(rig, "book.docx")
    assert d["mode"] == "doc" and d["images"] == 3 and all(r.get("img") for b in d["blocks"] for r in b["runs"])


def test_an_html_table_saved_as_xls_is_shown_as_a_table(rig):
    html = ('<html><head><meta charset="UTF-8"/></head><body><table><tr><th colspan="2">TOTAL STOCKS</th></tr><tr><th>SKU</th><th>Qty</th></tr>'
            '<tr><td>AFP001</td><td>247</td></tr></table><script>alert(1)</script></body></html>')
    rig.write("report.xls", html)
    d, _ = info(rig, "report.xls")
    assert d["mode"] == "table" and "really an HTML table" in d["note"]
    assert d["sheets"][0]["rows"] == [["TOTAL STOCKS"], ["SKU", "Qty"], ["AFP001", "247"]]
    assert "alert" not in str(d)                                                  # scripts are skipped, never run or shown


def test_files_that_are_not_what_their_name_says_are_shown_as_what_they_are(rig):
    rig.write("plain.xls", "name\tqty\nrice\t12\n")
    rig.write("page.doc", "<html><body><p>Hello</p><p>World</p></body></html>")
    (rig.src / "rich.doc").write_bytes(b"{\\rtf1\\ansi Hello \\b bold\\b0 text\\par}")
    rig.write("old2003.xls", '<?xml version="1.0"?><Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">'
                             '<Worksheet ss:Name="Stock"><Table><Row><Cell><Data ss:Type="String">SKU</Data></Cell><Cell><Data ss:Type="Number">5</Data></Cell></Row></Table></Worksheet></Workbook>')
    docx(rig.src / "modern.doc", "A modern file under an old name")
    t, _ = info(rig, "plain.xls")
    assert t["mode"] == "table" and t["sheets"][0]["rows"] == [["name", "qty"], ["rice", "12"]]
    h, _ = info(rig, "page.doc")
    assert h["mode"] == "pages" and h["pages"][0]["lines"] == ["Hello", "World"]
    r, _ = info(rig, "rich.doc")
    assert any("Hello" in line for line in r["pages"][0]["lines"])
    x, _ = info(rig, "old2003.xls")
    assert x["sheets"][0]["name"] == "Stock" and x["sheets"][0]["rows"] == [["SKU", "5"]]
    m, _ = info(rig, "modern.doc")
    assert m["mode"] == "doc"
