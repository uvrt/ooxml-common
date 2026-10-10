"""Symbol-face text drawn as the Unicode it stands for (``text/symbol_fonts.py``).

The expected characters are what PowerPoint 16 drew for the same codes, compared by eye
on its export of pptx2svg's ``tools/make_symbol_probe.py``: the bullets and marks of the
Office bullet libraries in each face, written as the code and as its private-use alias.
"""

from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

import pytest

from ooxml_common.drawingml import scene as m
from ooxml_common.drawingml.context import RenderContext
from ooxml_common.drawingml.textbody import render_text_body
from ooxml_common.text.measure import DefaultTextMeasurer
from ooxml_common.text.recorded_symbol_faces import ADVANCES
from ooxml_common.text.symbol_fonts import (
    FALLBACK_FAMILIES,
    recorded_font_metrics,
    symbol_face,
    to_unicode,
    translate,
)
from ooxml_common.text.symbol_maps import MAPS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from derive_symbol_maps import proposal_entries  # noqa: E402

#: (face, code, the character drawn for PowerPoint's glyph).
DRAWN = [
    ("wingdings", 0x71, "❑"),  # q: the shadowed box bullet
    ("wingdings", 0x6C, "●"),  # l: the round bullet
    ("wingdings", 0x6E, "■"),  # n: the square bullet
    ("wingdings", 0xA7, "▪"),  # §: the small square bullet
    ("wingdings", 0xD8, "➢"),  # Ø: the arrowhead bullet
    ("wingdings", 0xFC, "✓"),  # ü: a light check, as PowerPoint draws it
    ("wingdings", 0xFE, "☑"),  # þ: the checked box
    ("wingdings", 0x76, "❖"),  # v: the four-diamond bullet
    ("symbol", 0xB7, "•"),  # ·: the bullet
    ("wingdings 2", 0x50, "\U0001f5f8"),  # P: LIGHT CHECK MARK
    ("wingdings 3", 0x7D, "\U0001f782"),  # }: the right-pointing triangle
    ("webdings", 0x34, "⏵"),  # 4: the play triangle
]


@pytest.mark.parametrize("face,code,drawn", DRAWN)
def test_a_code_and_its_private_use_alias_are_the_same_character(face, code, drawn):
    assert to_unicode(face, chr(code)) == drawn
    assert to_unicode(face, chr(0xF000 + code)) == drawn


def test_every_face_is_covered_and_every_value_is_a_named_character():
    for face, table in MAPS.items():
        assert len(table) >= 150, face
        for code, point in table.items():
            assert 0x20 <= code <= 0xFF
            assert unicodedata.name(chr(point), ""), (face, hex(code))


def test_symbol_follows_adobes_table():
    assert to_unicode("symbol", "a") == "α"  # GREEK SMALL LETTER ALPHA
    assert to_unicode("symbol", "") == "Δ"  # GREEK CAPITAL LETTER DELTA
    assert to_unicode("symbol", "-") == "−"  # MINUS SIGN


def test_faces_are_named_as_decks_spell_them():
    assert symbol_face("Wingdings") == "wingdings"
    assert symbol_face("Wingdings 2") == "wingdings 2"
    assert symbol_face("WINGDINGS3") == "wingdings 3"
    assert symbol_face("Webdings") == "webdings"
    assert symbol_face("Symbol") == "symbol"
    assert symbol_face("Calibri") is None
    assert symbol_face(None) is None


def test_translate_reports_codes_without_an_equivalent():
    text, unmapped = translate("wingdings", "q ü")
    assert text == "❑ ✓"
    assert unmapped == ""
    unknown = next(code for code in range(0x21, 0x100) if code not in MAPS["webdings"])
    assert translate("webdings", chr(unknown))[1] == chr(unknown)


def test_recorded_metrics_measure_both_spellings_at_the_faces_advance():
    table = recorded_font_metrics("wingdings")
    assert table is not None and table.units_per_em == 2048
    assert table.widths["q"] == table.widths[""] == ADVANCES["wingdings"][0xF071]
    measurer = DefaultTextMeasurer({"wingdings": table})
    assert measurer.measure_text_width("q", 20, font_family="Wingdings") == pytest.approx(
        ADVANCES["wingdings"][0xF071] / 2048 * 20 * 96 / 72
    )
    assert recorded_font_metrics("webdings") is None


def _body(family: str, text: str, bullet: str | None = None) -> m.TextBody:
    properties = m.ParagraphProperties()
    if bullet is not None:
        properties = m.ParagraphProperties(
            bullet=m.CharBullet(char=bullet), bullet_font=family, margin_left=342900,
            indent=-342900,
        )
    return m.TextBody(paragraphs=[m.Paragraph(
        runs=[
            m.TextRun("Item ", m.RunProperties(font_size=18, font_family="Calibri")),
            m.TextRun(text, m.RunProperties(font_size=18, font_family=family)),
        ],
        properties=properties,
    )])


FRAME = m.Transform(extent_width=6000000, extent_height=800000)


def test_an_absent_symbol_face_is_drawn_as_unicode_in_faces_that_have_it():
    context = RenderContext(mapped_symbol_faces=frozenset({"wingdings"}))
    svg = render_text_body(_body("Wingdings", "ü", bullet="q"), FRAME, context)
    assert "❑" in svg and "✓" in svg
    assert ">q<" not in svg and "ü" not in svg
    assert FALLBACK_FAMILIES[0] in svg
    assert not re.search(r'font-family="Wingdings', svg)


def test_a_face_the_drawing_has_is_drawn_as_itself():
    svg = render_text_body(_body("Wingdings", "ü", bullet="q"), FRAME, RenderContext())
    assert ">q<" in svg and "ü" in svg
    assert "❑" not in svg


def test_the_mapped_run_keeps_the_faces_advance_for_what_follows():
    """The text after a mapped symbol starts where the face's own advance puts it."""
    table = recorded_font_metrics("wingdings")
    measurer = DefaultTextMeasurer({"wingdings": table})
    body = _body("Wingdings", "ü")
    body.paragraphs[0].runs.append(
        m.TextRun(" done", m.RunProperties(font_size=18, font_family="Calibri"))
    )
    mapped = render_text_body(
        body, FRAME, RenderContext(measurer=measurer, mapped_symbol_faces=frozenset({"wingdings"}))
    )
    plain = render_text_body(body, FRAME, RenderContext(measurer=measurer))
    xs = re.findall(r'<tspan x="([0-9.]+)"[^>]*> done<', mapped)
    width = measurer.measure_text_width("Item ", 18, font_family="Calibri") + measurer.measure_text_width(
        "ü", 18, font_family="Wingdings"
    )
    assert xs, mapped
    left = float(re.search(r'<tspan x="([0-9.]+)"', plain).group(1))
    assert float(xs[0]) == pytest.approx(left + width, abs=0.05)


def test_the_proposal_reader_takes_an_entry_over_several_lines():
    lines = [
        "1252 ", "2713", "✓", "CHECK MARK", "= heavy check", "",
        "3125 ", "1F782", "BLACK RIGHT-POINTING ISOCELES", "RIGHT TRIANGLE", "",
        "1129 ", "2780", "➀", "DINGBAT CIRCLED SANS-", "SERIF DIGIT ONE",
    ]
    assert proposal_entries(lines) == {
        "1252": (["2713"], "CHECK MARK"),
        "3125": (["1F782"], "BLACK RIGHT-POINTING ISOCELES RIGHT TRIANGLE"),
        "1129": (["2780"], "DINGBAT CIRCLED SANS-SERIF DIGIT ONE"),
    }
