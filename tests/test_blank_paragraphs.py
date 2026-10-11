"""A paragraph that holds only whitespace, and one that holds nothing, held to PowerPoint.

Measured on PowerPoint 16's PDF export of placeholder and text-box paragraphs (bullets
from the layout and from ``a:buChar``, wrapped and ``wrap="none"``): a paragraph whose
runs hold only whitespace -- a space, a tab, a no-break space, several, in one run or two
-- draws its bullet, first paragraph or later, in its run's size and colour, on a line as
tall as that run.  An auto-number numbers it and counts it.  A paragraph that holds
nothing (no run, or only an empty one) draws no bullet and no number and is not counted:
``a``, whitespace, ``b``, empty, ``c`` is numbered 1, 2, 3, -, 4.  ``a:buNone`` draws
nothing either way, and only the first line of a paragraph carries its bullet, so a break
before the text (``<a:br/>Text``) leaves the bullet alone on the first line.

Word is not measured, so :data:`~ooxml_common.drawingml.rules.WORD` keeps what was drawn
before (:attr:`~ooxml_common.drawingml.rules.DrawingRules.blank_paragraphs`).
"""

from __future__ import annotations

import re

from ooxml_common.drawingml import scene as m
from ooxml_common.drawingml.context import RenderContext
from ooxml_common.drawingml.rules import POWERPOINT, WORD
from ooxml_common.drawingml.textbody import render_text_body

FRAME = m.Transform(extent_width=6000000, extent_height=4000000)
BULLET = m.ParagraphProperties(bullet=m.CharBullet("•"), margin_left=342900,
                               indent=-342900)
NUMBER = m.ParagraphProperties(bullet=m.AutoNumBullet("arabicPeriod"), margin_left=457200,
                               indent=-457200)
RED = m.ResolvedColor("#FF0000")


def _paragraph(*texts: str, properties=BULLET, size=18.0, color=None) -> m.Paragraph:
    return m.Paragraph(
        runs=[m.TextRun(text, m.RunProperties(font_size=size, color=color)) for text in texts],
        properties=properties,
        end_para_run_properties=m.RunProperties(font_size=18),
    )


def _lines(paragraphs, *, wrap="square", rules=POWERPOINT):
    """(dy, marker, marker attributes, text) per line, in order."""
    body = m.TextBody(paragraphs=list(paragraphs),
                      body_properties=m.BodyProperties(wrap=wrap))
    svg = render_text_body(body, FRAME, RenderContext(rules=rules))
    lines = []
    for attrs, text in re.findall(r"<tspan([^>]*)>([^<]*)</tspan>", svg):
        dy = re.search(r' dy="([-\d.]+)"', attrs)
        if dy is not None:
            lines.append([float(dy.group(1)), "", "", ""])
        x = re.search(r' x="([-\d.]+)"', attrs)
        if x is not None and float(x.group(1)) < 20 and text.strip():
            lines[-1][1], lines[-1][2] = text, attrs
        else:
            lines[-1][3] += text
    return lines


def _markers(paragraphs, **kwargs) -> list[str]:
    return [marker for _dy, marker, _attrs, _text in _lines(paragraphs, **kwargs)]


def test_a_whitespace_paragraph_draws_its_bullet():
    for wrap in ("square", "none"):
        for blank in (" ", "\t", " ", "   "):
            assert _markers([_paragraph("Alpha"), _paragraph(blank), _paragraph("Bravo")],
                            wrap=wrap) == ["•"] * 3, (wrap, repr(blank))
        assert _markers([_paragraph(" ", " ")], wrap=wrap) == ["•"]
        assert _markers([_paragraph(" "), _paragraph("Delta")], wrap=wrap) == ["•"] * 2


def test_an_empty_paragraph_draws_none():
    empty = m.Paragraph(properties=BULLET, end_para_run_properties=m.RunProperties(font_size=18))
    assert _markers([_paragraph("Alpha"), empty, _paragraph(""), _paragraph("Bravo")]) == [
        "•", "", "", "•"]


def test_no_bullet_stays_no_bullet():
    none = m.ParagraphProperties(bullet=m.NoBullet())
    assert _markers([_paragraph("Lima"), _paragraph(" ", properties=none)]) == ["•", ""]


def test_the_bullet_takes_the_whitespace_runs_size_and_colour_and_so_does_the_line():
    """PowerPoint: a 40 pt red space under a 10 pt blue end mark draws a 40 pt red bullet,
    its baseline as far down as a 40 pt line's; a 10 pt one steps like a 10 pt "x"."""
    lines = _lines([_paragraph(" ", size=40, color=RED), _paragraph("Echo"),
                    _paragraph(" ", size=10), _paragraph("Fox"), _paragraph("x", size=10)])
    assert 'font-size="53.333"' in lines[0][2] and 'fill="#FF0000"' in lines[0][2]
    assert 'font-size="13.333"' in lines[2][2]
    assert lines[2][0] == lines[4][0]


def test_a_whitespace_first_line_is_as_tall_as_its_run():
    def first_baseline(size):
        body = m.TextBody(paragraphs=[_paragraph(" ", size=size), _paragraph("Echo")])
        svg = render_text_body(body, FRAME, RenderContext())
        return float(re.search(r'<text x="0" y="([\d.]+)"', svg).group(1))

    assert first_baseline(40) > first_baseline(18) > first_baseline(10)


def test_only_the_first_line_carries_the_bullet():
    lines = _lines([_paragraph("\nBravo"), _paragraph(" \nIndia")])
    assert [(marker, text.strip()) for _dy, marker, _attrs, text in lines] == [
        ("•", ""), ("", "Bravo"), ("•", ""), ("", "India")]


def test_an_auto_number_counts_whitespace_but_not_an_empty_paragraph():
    empty = m.Paragraph(properties=NUMBER, end_para_run_properties=m.RunProperties(font_size=18))
    texts = ["a", " ", "b", None, "c", "\t", "d", " ", "e"]
    paragraphs = [empty if text is None else _paragraph(text, properties=NUMBER) for text in texts]
    assert _markers(paragraphs) == ["1.", "2.", "3.", "", "4.", "5.", "6.", "7.", "8."]
    assert _markers([empty, _paragraph("a", properties=NUMBER),
                     _paragraph(" ", properties=NUMBER)]) == ["", "1.", "2."]


def test_word_keeps_what_was_drawn():
    empty = m.Paragraph(properties=NUMBER, end_para_run_properties=m.RunProperties(font_size=18))
    assert _markers([_paragraph("a"), _paragraph(" "), _paragraph("b")], rules=WORD) == [
        "•", "", "•"]
    assert _markers([_paragraph("a", properties=NUMBER), empty,
                     _paragraph("b", properties=NUMBER)], rules=WORD) == ["1.", "", "3."]
