"""The public text measurement, held to the private estimate autofit uses, number for number.

:mod:`ooxml_common.drawingml.textmeasure` promises :func:`textbody._estimate_text_height`'s
height exactly, and the line breaks :func:`wrap.wrap_paragraph` gives; consumers that used to
compose the private helpers themselves (pptx-agent's text fit) rely on that.
"""

from __future__ import annotations

import pytest

from ooxml_common.drawingml import scene as m
from ooxml_common.drawingml import textbody as tb
from ooxml_common.drawingml.context import RenderContext
from ooxml_common.drawingml.rules import WORD
from ooxml_common.drawingml.shape import _outline_width, text_geometry
from ooxml_common.drawingml.textmeasure import measure_shape_text, measure_text, measure_text_body
from ooxml_common.drawingml.wrap import wrap_paragraph
from ooxml_common.units import emu_to_px

FRAME = m.Transform(extent_width=300 * 12700, extent_height=120 * 12700)
LONG = ("The quarter closed with revenue ahead of plan in every region, and the pipeline for "
        "the next two quarters is the strongest it has been since the product launched.")


def _paragraph(text: str, size: float | None = 18, family: str | None = "Arial", **properties):
    run = m.RunProperties(font_size=size, font_family=family)
    return m.Paragraph(runs=[m.TextRun(text, run)] if text else [],
                       properties=m.ParagraphProperties(**properties),
                       end_para_run_properties=run)


def _bodies():
    yield "one line", m.TextBody([_paragraph("Short")])
    yield "wrapped", m.TextBody([_paragraph(LONG)])
    yield "mixed runs", m.TextBody([m.Paragraph(runs=[
        m.TextRun("Bold start ", m.RunProperties(font_size=24, bold=True, font_family="Calibri")),
        m.TextRun(LONG, m.RunProperties(font_size=14, font_family="Calibri"))])])
    yield "spacing", m.TextBody([
        _paragraph(LONG, space_after=m.PointsSpacing(600)),
        _paragraph("", space_before=m.PercentSpacing(20000)),
        _paragraph(LONG, size=12, line_spacing=m.PercentSpacing(150000)),
        _paragraph("Fixed", line_spacing=m.PointsSpacing(3000))])
    yield "breaks", m.TextBody([_paragraph("First line\nsecond line\n\nfourth " + LONG)])
    yield "cjk", m.TextBody([_paragraph("日本語のテキストは、文字ごとに改行できます。" * 3,
                                        family="Yu Gothic")])
    yield "no wrap", m.TextBody([_paragraph(LONG)], m.BodyProperties(wrap="none"))
    yield "stored scale", m.TextBody([_paragraph(LONG), _paragraph(LONG, size=None)],
                                     m.BodyProperties(auto_fit="normAutofit", font_scale=0.625,
                                                      ln_spc_reduction=0.2))
    yield "columns", m.TextBody([_paragraph(LONG)] * 3, m.BodyProperties(num_col=2))
    yield "vertical", m.TextBody([_paragraph(LONG)], m.BodyProperties(vert="vert270"))
    yield "insets", m.TextBody([_paragraph(LONG)], m.BodyProperties(margin_left=360000, margin_top=0))
    yield "empty", m.TextBody([_paragraph("")])


BODIES = list(_bodies())


def _private(body: m.TextBody, frame: m.Transform, context: RenderContext, geometry=None):
    """What a consumer composed from the private helpers before (pptx-agent's text fit)."""
    properties = body.body_properties
    area, _, _ = tb._text_area(frame, geometry, 0.0, context.rules)
    dims = tb._resolve_dimensions(properties, emu_to_px(area.extent_width), emu_to_px(area.extent_height))
    columns = max(1, properties.num_col)
    text_width = (dims.width - dims.margin_left - dims.margin_right) / columns
    scale = properties.font_scale if properties.auto_fit == "normAutofit" else 1.0
    default = tb._default_font_size(body.paragraphs)
    wrap = properties.wrap != "none"
    has_text = any(run.text for p in body.paragraphs for run in p.runs)
    text_px = tb._estimate_text_height(body.paragraphs, default, wrap, text_width,
                                       properties.ln_spc_reduction, scale, context) if has_text else 0.0
    if columns > 1 and properties.vert == "horz":
        text_px /= columns
    lines = [len(wrap_paragraph(p, text_width, default * scale, scale, context.measurer))
             if wrap and any(r.text for r in p.runs) else (1 if any(r.text for r in p.runs) else 0)
             for p in body.paragraphs]
    ratio = tb._default_line_height_ratio(body.paragraphs, context)
    tallest = max((tb._line_height_px(p, tb._paragraph_natural_height(p, default, scale, context, ratio),
                                      properties.ln_spc_reduction)
                   for p in body.paragraphs if any(r.text for r in p.runs)), default=0.0)
    needed = text_px + (dims.margin_top + dims.margin_bottom) if has_text else 0.0
    return text_px, needed, dims.height, text_width, lines, tallest


@pytest.mark.parametrize("name,body", BODIES, ids=[name for name, _ in BODIES])
@pytest.mark.parametrize("rules", ["powerpoint", "word"])
def test_the_measure_is_the_private_estimate_exactly(name, body, rules):
    context = RenderContext() if rules == "powerpoint" else RenderContext(rules=WORD)
    measured = measure_text_body(body, FRAME, context)
    text_px, needed, available, text_width, lines, tallest = _private(body, FRAME, context)
    assert measured.text_height == text_px
    assert measured.needed == needed
    assert measured.available == available
    assert measured.text_width == text_width
    assert [len(p.lines) if p.has_text else 0 for p in measured.paragraphs] == lines
    assert measured.tallest_line == tallest


@pytest.mark.parametrize("name,body", BODIES, ids=[name for name, _ in BODIES])
def test_lines_are_stretches_of_their_paragraph(name, body):
    measured = measure_text_body(body, FRAME)
    for paragraph in measured.paragraphs:
        previous = 0
        for line in paragraph.lines:
            assert paragraph.text[line.start:line.end] == line.text
            assert line.start >= previous
            assert paragraph.text[previous:line.start].strip() == ""
            previous = line.end
            assert line.height == paragraph.line_height
        assert paragraph.text[previous:].strip() == ""


def test_wrapped_lines_fit_the_width_and_break_at_spaces():
    measured = measure_text_body(m.TextBody([_paragraph(LONG)]), FRAME)
    assert len(measured.lines) > 2
    assert all(0 < line.width <= measured.text_width + 1e-6 for line in measured.lines)
    assert " ".join(line.text for line in measured.lines) == LONG


def test_a_shape_is_measured_in_its_text_rectangle_and_group_scale():
    shape = m.ShapeElement(transform=FRAME, geometry=m.PresetGeometry("ellipse"),
                           text_body=m.TextBody([_paragraph(LONG)]))
    context = RenderContext()
    measured = measure_shape_text(shape, context, scale=(2.0, 1.0))
    frame = m.Transform(extent_width=FRAME.extent_width * 2.0, extent_height=FRAME.extent_height)
    text_px, needed, available, text_width, _, _ = _private(shape.text_body, frame, context,
                                                            text_geometry(shape))
    assert (measured.text_height, measured.needed, measured.available, measured.text_width) == \
        (text_px, needed, available, text_width)
    assert _outline_width(shape) == 0.0
    assert measured.width < emu_to_px(frame.extent_width)       # the ellipse's inscribed rectangle
    assert measure_shape_text(m.ShapeElement(transform=FRAME, geometry=m.PresetGeometry("rect"))) is None


def test_a_plain_string():
    one = measure_text("Revenue", "Arial", 18)
    assert len(one.lines) == 1 and one.lines[0].width > 0 and one.insets == (0, 0, 0, 0)
    assert one.needed == one.text_height == one.lines[0].height
    wrapped = measure_text(LONG, "Arial", 18, width=200)
    assert len(wrapped.lines) > 3
    assert abs(wrapped.text_width - 200) < 1e-9
    assert all(line.width <= 200 + 1e-6 for line in wrapped.lines)
    double = measure_text(LONG, "Arial", 18, width=200, line_spacing=2.0)
    assert double.text_height == pytest.approx(2 * wrapped.text_height)
    two = measure_text("one\ntwo", "Arial", 18)
    assert [line.text for line in two.lines] == ["one", "two"] and len(two.paragraphs) == 2
    assert measure_text("", "Arial", 18).needed == 0.0
    assert measure_text("Wide", "Arial", 36).lines[0].width > measure_text("Wide", "Arial", 18).lines[0].width


def test_as_drawn_wraps_inside_the_left_margin_and_breaks_at_line_breaks():
    indented = m.TextBody([_paragraph(LONG, margin_left=914400)])
    estimate = measure_text_body(indented, FRAME)
    drawn = measure_text_body(indented, FRAME, as_drawn=True)
    assert drawn.paragraphs[0].width == estimate.paragraphs[0].width - 96
    assert len(drawn.lines) > len(estimate.lines)
    assert all(line.width <= drawn.paragraphs[0].width + 1e-6 for line in drawn.lines)
    unwrapped = m.TextBody([_paragraph("one  \ntwo\n\nfour")], m.BodyProperties(wrap="none"))
    assert [line.text for line in measure_text_body(unwrapped, FRAME).lines] == ["one  \ntwo\n\nfour"]
    lines = measure_text_body(unwrapped, FRAME, as_drawn=True).lines
    assert [line.text for line in lines] == ["one", "two", "", "four"]
    assert [line.start for line in lines] == [0, 6, 10, 11]
    assert lines[0].width > measure_text("one", "Arial", 18).lines[0].width   # its spaces count
    # Where neither applies the two agree.
    plain = m.TextBody([_paragraph(LONG), _paragraph("Short")])
    assert measure_text_body(plain, FRAME, as_drawn=True) == measure_text_body(plain, FRAME)


def test_a_plain_string_breaks_at_vertical_tabs_and_takes_insets():
    measured = measure_text("one\vtwo", "Arial", 18, width=300, insets=(10, 4, 10, 6))
    assert [line.text for line in measured.lines] == ["one", "two"] and len(measured.paragraphs) == 1
    assert measured.text_width == pytest.approx(280)
    assert measured.needed == pytest.approx(measured.text_height + 10)


def test_a_paragraph_that_starts_with_a_break_starts_with_an_empty_line():
    lines = measure_text_body(m.TextBody([_paragraph("\nabc")]), FRAME).lines
    assert [(line.text, line.start, line.end) for line in lines] == [("", 0, 0), ("abc", 1, 4)]
