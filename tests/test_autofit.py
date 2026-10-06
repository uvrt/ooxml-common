"""What a text body's autofit draws, held to PowerPoint on open.

PowerPoint does not re-fit a file's text when it opens it: ``a:normAutofit`` applies the
``fontScale`` and ``lnSpcReduction`` it stores and nothing else, and ``a:spAutoFit`` keeps
the shape's stored extent -- measured on PowerPoint 16's PDF export of pptx2svg's
``tools/make_autofit_probe.py`` (pptx2svg ROADMAP.md, "5.8 Autofit is what the file
stores").  Word's rules keep the re-fitting the renderers did before.
"""

from __future__ import annotations

import re

from ooxml_common.drawingml import rules as drawing_rules
from ooxml_common.drawingml import scene as m
from ooxml_common.drawingml.context import RenderContext
from ooxml_common.drawingml.shape import render_shape
from ooxml_common.drawingml.textbody import render_text_body
from ooxml_common.units import PX_PER_PT

#: 400 x 150 pt, the probe's box.
FRAME = m.Transform(extent_width=400 * 12700, extent_height=150 * 12700)


def _body(lines: int, size: float | None = 18, fit: str = "normAutofit", scale: float = 1.0,
          reduction: float = 0.0, spacing: m.SpacingValue | None = None) -> m.TextBody:
    return m.TextBody(
        paragraphs=[
            m.Paragraph(
                runs=[m.TextRun(f"Line {n:02d}", m.RunProperties(font_size=size))],
                properties=m.ParagraphProperties(line_spacing=spacing),
            )
            for n in range(lines)
        ],
        body_properties=m.BodyProperties(auto_fit=fit, font_scale=scale,
                                         ln_spc_reduction=reduction),
    )


def _sizes(svg: str) -> set[float]:
    return {round(float(size) / PX_PER_PT, 3) for size in re.findall(r'font-size="([^"]+)"', svg)}


def _pitch(svg: str) -> float:
    """The baseline step between lines, pt."""
    steps = [float(dy) for dy in re.findall(r' dy="([^"]+)"', svg) if float(dy)]
    return round(steps[0] / PX_PER_PT, 3)


def test_overflowing_text_with_nothing_stored_is_drawn_at_full_size():
    """Twelve 18 pt lines in a 150 pt box: PowerPoint draws 18 pt, 297.6 pt deep."""
    svg = render_text_body(_body(12), FRAME, RenderContext())
    assert _sizes(svg) == {18.0}


def test_word_still_shrinks_overflowing_text_to_fit():
    svg = render_text_body(_body(12), FRAME, RenderContext(rules=drawing_rules.WORD))
    assert max(_sizes(svg)) < 18


def test_a_stored_font_scale_rounds_each_size_to_a_whole_point_half_up():
    cases = {(25, 0.5): 13, (21, 0.5): 11, (18, 0.625): 11, (18, 0.7): 13,
             (18, 0.925): 17, (10, 0.85): 9, (10.5, 0.5): 5, (18, 0.55): 10}
    for (size, scale), drawn in cases.items():
        svg = render_text_body(_body(3, size, scale=scale), FRAME, RenderContext())
        assert _sizes(svg) == {drawn}, (size, scale)


def test_a_stated_half_point_is_kept_at_full_scale():
    svg = render_text_body(_body(3, 10.5), FRAME, RenderContext())
    assert _sizes(svg) == {10.5}


def test_a_stored_font_scale_reaches_the_default_size():
    svg = render_text_body(_body(3, None, scale=0.625), FRAME, RenderContext())
    assert _sizes(svg) == {11}


def test_overflow_at_the_stored_scale_is_not_shrunk_further():
    svg = render_text_body(_body(30, scale=0.5), FRAME, RenderContext())
    assert _sizes(svg) == {9}


def test_a_line_spacing_reduction_comes_off_the_percentage():
    """150 % less 20 draws as 130 %, and 90 % less 10 as 80 %."""
    context = RenderContext()

    def pitch(percent: float, reduction: float) -> float:
        spacing = m.PercentSpacing(percent * 1000)
        return _pitch(render_text_body(
            _body(3, spacing=spacing, reduction=reduction), FRAME, context))

    assert pitch(150, 0.2) == pitch(130, 0.0)
    assert pitch(90, 0.1) == pitch(80, 0.0)
    assert pitch(100, 0.2) == pitch(80, 0.0)


def test_a_line_spacing_reduction_leaves_exact_spacing_alone():
    spacing = m.PointsSpacing(3000)
    svg = render_text_body(_body(3, spacing=spacing, reduction=0.2), FRAME, RenderContext())
    assert _pitch(svg) == 30.0


def _shape(rules: drawing_rules.DrawingRules) -> str:
    shape = m.ShapeElement(
        transform=FRAME,
        geometry=m.PresetGeometry("rect"),
        fill=m.SolidFill(m.ResolvedColor("#d9d9d9")),
        text_body=_body(12, fit="spAutofit"),
    )
    svg = render_shape(shape, RenderContext(rules=rules))
    return re.search(r'<rect[^>]* height="([^"]+)"', svg).group(1)


def test_a_shape_that_fits_its_text_keeps_its_stored_extent_in_powerpoint():
    assert float(_shape(drawing_rules.POWERPOINT)) == 200.0


def test_a_shape_that_fits_its_text_still_grows_under_word():
    assert float(_shape(drawing_rules.WORD)) > 200.0
