import json
from pathlib import Path

import smartsearch as ss


def test_a_kind_word_stands_for_every_extension_of_that_kind():
    q = ss.Query("type:spreadsheets")
    assert {".xls", ".xlsx", ".csv", ".ods"} <= q.exts and ".pdf" not in q.exts
    assert q.match("Docs/april.xlsx", ext=".xlsx") and not q.match("Docs/april.pdf", ext=".pdf")


def test_kinds_and_plain_extensions_mix_and_a_bare_extension_stays_exact():
    assert {".pdf", ".docx", ".jpg"} <= ss.Query("ext:pdf,docx,images").exts
    assert ss.Query("type:zip").exts == {".zip"}                 # an extension, not the whole archive kind
    assert ss.Query("type:xyz").exts == {".xyz"}                 # anything unknown is still just an extension
    assert ss.Query("kind:video").exts >= {".mp4", ".mkv"}


def test_document_covers_the_usual_document_files():
    assert {".docx", ".pdf", ".txt"} <= ss.Query("type:documents").exts


def test_words_alone_are_still_ordinary_search_words():
    q = ss.Query("spreadsheets april")
    assert not q.exts and q.terms == ["spreadsheets", "april"]


def test_the_app_and_the_server_use_the_same_kind_lists():
    shared = json.loads((Path(__file__).resolve().parents[2] / "frontend" / "src" / "kinds.json").read_text("utf8"))
    assert shared == {"kinds": ss.KINDS, "words": ss.WORDS}      # regenerate frontend/src/kinds.json from smartsearch.py if this fails
