"""Where a run is drawn after the run before it, held to PowerPoint.

PowerPoint puts a run at the advance of the one before it, its trailing space included,
in that run's own face, and a space opening a run in the run's face -- measured on
PowerPoint 16's PDF export of pptx2svg's ``tools/make_run_probe.py`` (pptx2svg
ROADMAP.md, "5.7 A run after a change of face").
"""

from __future__ import annotations

import re

from ooxml_common.drawingml import scene as m
from ooxml_common.drawingml.context import RenderContext
from ooxml_common.drawingml.textbody import render_text_body
from ooxml_common.text.fontmap import metrics_for
from ooxml_common.text.measure import DefaultTextMeasurer

FRAME = m.Transform(extent_width=6000000, extent_height=800000)


def _line(*runs: tuple[str, dict]) -> list[tuple[str, str]]:
    body = m.TextBody(
        paragraphs=[m.Paragraph(runs=[
            m.TextRun(text, m.RunProperties(font_size=18, **properties))
            for text, properties in runs
        ])],
    )
    svg = render_text_body(body, FRAME, RenderContext())
    return re.findall(r"<tspan([^>]*)>([^<]*)</tspan>", svg)


def test_a_change_of_face_in_latin_text_does_not_open_a_chunk():
    tspans = _line(("Operating margin ", {"font_family": "Calibri"}),
                   ("11.9%", {"font_family": "Consolas"}))
    assert [text for _attrs, text in tspans] == ["Operating margin ", "11.9%"]
    assert 'x="' not in tspans[1][0]


def test_a_run_of_east_asian_text_still_opens_its_own_chunk():
    tspans = _line(("Markdown", {"font_family": "Calibri"}),
                   ("から", {"font_family": "ＭＳ Ｐゴシック"}))
    assert 'x="' in tspans[1][0]


def test_a_latin_italic_is_not_sheared_for_the_east_asian_face_beside_it():
    office = {"font_family": "Aptos", "font_family_ea": "游ゴシック"}
    tspans = _line(("to ", office), ("4,285", {**office, "italic": True}))
    assert 'font-style="italic"' in tspans[-1][0]
    body = m.TextBody(paragraphs=[m.Paragraph(runs=[m.TextRun("編集", m.RunProperties(
        font_size=18, italic=True, font_family="Aptos", font_family_ea="游ゴシック"))])])
    assert "skewX" in render_text_body(body, FRAME, RenderContext())


def test_consolas_is_measured_at_its_own_pitch():
    """1126/2048 em on every character: a run after a Consolas space starts 13.25 pt on
    at 24 pt in PowerPoint's export, where a face with no table was guessed at 7.2."""
    assert metrics_for("Consolas") is not None
    measurer = DefaultTextMeasurer()
    for text in (" ", "i", "W", "11.9%"):
        width_pt = measurer.measure_text_width(text, 24, False, "Consolas") * 72 / 96
        assert abs(width_pt - len(text) * 24 * 1126 / 2048) < 1e-9
