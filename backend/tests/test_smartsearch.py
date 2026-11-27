import smartsearch as ss


def hit(q, text, **kw):
    return ss.Query(q).match(text, **kw)


def test_words_in_any_order_ignoring_case_and_accents():
    assert hit("2025 REPORT", r"C:\Docs\report_final_2025.docx")
    assert hit("cafe", r"C:\menu\Café.txt")
    assert not hit("report 2024", r"C:\Docs\report_final_2025.docx")


def test_phrase_exclude_and_joined_words():
    assert hit('"tax return"', r"C:\a\tax return.pdf") and not hit('"tax return"', r"C:\a\return tax.pdf")
    assert hit("tax -draft", r"C:\a\tax.pdf") and not hit("tax -draft", r"C:\a\tax draft.pdf")
    assert hit("taxreturn", r"C:\a\tax_return.pdf")


def test_extension_and_size_filters():
    assert hit(".pdf", "a.pdf", ext=".pdf", size=1) and not hit("ext:pdf", "a.doc", ext=".doc", size=1)
    assert hit("ext:pdf,docx", "a.docx", ext=".docx", size=1)
    assert hit(">10mb", "a", size=11e6) and not hit(">10mb", "a", size=9e6) and hit("size<1gb", "a", size=5)


def test_typos_only_when_asked():
    q = ss.Query("reprot")
    assert not q.match("quarterly report.xlsx") and q.match("quarterly report.xlsx", fuzzy=True)
    assert not ss.Query("zzzz").match("quarterly report.xlsx", fuzzy=True)
    assert not ss.Query("cat").can_fuzzy


def test_log_fields():
    assert ss.Query("level:error disk").fields == {"level": "error"}
