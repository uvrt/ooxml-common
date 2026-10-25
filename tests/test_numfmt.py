"""ooxml_common.numfmt: one reading of a number format code, held to Excel's answers.

The table is :data:`ooxml_common.numfmt.MEASURED` (Excel for Mac 16.106, 2026-10-25);
xlsx-agent runs the same table through its own ``classify_format``.  ooxml-edit reads codes
with this module (``ooxml_edit.dates.is_date_code`` is :func:`~ooxml_common.numfmt.is_date_code`,
from ooxml-edit 0.64.0); with it installed, the test below checks that it agrees on every
code, so a copy creeping back in fails here.
"""

from __future__ import annotations

import pytest

from ooxml_common import dates, numfmt
from ooxml_common.numfmt import Token, classify, is_date_code, sections, tokens


@pytest.mark.parametrize("code, kind, shown", numfmt.MEASURED)
def test_every_measured_code_is_classified_as_excel_showed_it(code, kind, shown):
    assert classify(code).kind == kind, shown
    assert is_date_code(code) is (kind in numfmt.DATE_KINDS)
    assert dates.is_date_code is is_date_code


def test_the_table_covers_every_kind_but_none():
    assert {kind for _, kind, _ in numfmt.MEASURED} == set(numfmt.KINDS)
    assert len(numfmt.MEASURED) >= 50


# ooxml-edit's cases (its tests/test_dates.py), with Excel's answer: the same as its own.
EDIT_CASES = [
    (r"[$-413]d\ mmmm\ yyyy", True), ("m/d/yyyy", True), ("dd/mm/yy;@", True), ("h:mm", True),
    ("[h]:mm", True), ("General", False), ("@", False), ("#,##0.0", False), ('"days" 0', False),
    (r"\d0", False), ("[Red]0.0", False), ("[$€-413] #,##0.0", False), ("", False), (None, False),
]


@pytest.mark.parametrize("code, is_date", EDIT_CASES)
def test_ooxml_edits_cases(code, is_date):
    assert is_date_code(code) is is_date


def test_ooxml_edit_reads_every_code_as_excel_showed_it():
    edit = pytest.importorskip("ooxml_edit.dates")
    differs = {code for code, kind, _ in numfmt.MEASURED
               if edit.is_date_code(code) is not (kind in numfmt.DATE_KINDS)}
    assert differs == set()
    for code, is_date in EDIT_CASES:
        assert edit.is_date_code(code) is is_date
    assert edit.is_date_code("0;[Red]d", 1)


def test_a_section_is_asked_by_its_index():
    # A negative serial in 0;[Red]d showed ####: its section is a date.
    assert not is_date_code("0;[Red]d") and is_date_code("0;[Red]d", 1)
    assert is_date_code("0;0;d", 2) and not is_date_code("0;0;d", 1)
    assert classify("AM/PM;0", 1).kind == "number"
    with pytest.raises(IndexError, match="1 section"):
        classify("0", 1)
    # The system's date is read in the first section only.
    assert not is_date_code("0;[$-F800]", 1)


def test_sections_are_cut_where_excel_cuts_them():
    assert sections("0;-0;;@") == ["0", "-0", "", "@"]
    assert sections(r"0\;0") == [r"0\;0"]
    assert sections("0_;0") == ["0_;0"] and sections("0*;0") == ["0*;0"]
    assert sections('"a;b"0;0') == ['"a;b"0', "0"]
    assert sections("") == [""]


def test_tokens():
    assert tokens('[$-413]d\\ mmmm "x"_)*-') == [
        Token("locale", "-413"), Token("date", "d"), Token("escaped", " "),
        Token("date", "mmmm"), Token("literal", " "), Token("quoted", "x"),
        Token("pad", ")"), Token("fill", "-")]
    assert [t.kind for t in tokens("[Red][<100]#,##0.0E+0%")] == [
        "color", "condition", "digit", "literal", "digit", "digit", "digit", "literal",
        "digit", "exponent", "digit", "percent"]
    assert [t.kind for t in tokens("[h]:mm:ss AM/PM")] == [
        "elapsed", "literal", "time", "literal", "time", "literal", "ampm"]
    assert [(t.kind, t.text) for t in tokens("General @ [DBNum1] x")] == [
        ("general", "General"), ("literal", " "), ("text", "@"), ("literal", " "),
        ("bracket", "DBNum1"), ("literal", " "), ("letter", "x")]
    # An unclosed quote or bracket runs to the end.
    assert tokens('"ab') == [Token("quoted", "ab")]
    assert tokens("[Red") == [Token("color", "Red")]


@pytest.mark.parametrize("code, kinds", [
    ("mm", ["date"]), ("h:mm", ["time", "time"]), ("mm:ss", ["time", "time"]),
    ('h "x" m', ["time", "time"]), ("yyyy m", ["date", "date"]), ("m s", ["time", "time"]),
    ("[h] m", ["elapsed", "time"]), ("d m h", ["date", "date", "time"]),
    ("m/d h:mm", ["date", "date", "time", "time"]),
])
def test_m_is_minutes_after_an_hour_or_before_a_second(code, kinds):
    assert [t.kind for t in tokens(code) if t.kind in ("date", "time", "elapsed")] == kinds


def test_elapsed_and_locale_ids():
    assert classify("[h]:mm:ss") == numfmt.Classification("time", True, None)
    assert classify("h:mm:ss") == numfmt.Classification("time", False, None)
    assert classify("[$-409]h:mm").lcid == 0x409
    assert classify("[$-F800]dddd").lcid == 0xF800
    assert classify("[$€-407] #,##0.00").lcid == 0x407
    assert classify("[$-x-sysdate]").lcid is None and classify("[Red]0").lcid is None
    assert classify("[ช]:นน").elapsed and classify("dd/mm/yyyy [h]").kind == "datetime"


def test_is_date_code_takes_anything():
    for code in (None, "", 0, "General", "@"):
        assert not is_date_code(code)
