"""A table style's ``a:tblBg``: one fill under the whole table, and effects on the table.

PowerPoint's built-in "Themed Style 1" and "2" draw their tables on a theme fill style (a
gradient in Office's own themes) with an effect style (a shadow) under it, and leave most
cells unfilled over it.  Measured on PowerPoint 16's PDF export (pptx2svg, gaps round): the
gradient runs once across the table, not once per cell, and the shadow falls under the
table's outline.
"""

from __future__ import annotations

import re

from ooxml_common.drawingml import scene as m
from ooxml_common.drawingml.context import RenderContext
from ooxml_common.drawingml.rules import POWERPOINT
from ooxml_common.drawingml.shape import render_table
from ooxml_common.text.measure import DefaultTextMeasurer

EMU_PER_PX = 9525


def _table(**data) -> str:
    cells = [m.TableCell(), m.TableCell(fill=m.SolidFill(m.ResolvedColor("#ff0000", 0.2)))]
    table = m.TableElement(
        transform=m.Transform(extent_width=200 * EMU_PER_PX, extent_height=40 * EMU_PER_PX),
        table=m.TableData(rows=[m.TableRow(height=20 * EMU_PER_PX, cells=list(cells)),
                                m.TableRow(height=20 * EMU_PER_PX, cells=list(cells))],
                          columns=[m.TableColumn(width=100 * EMU_PER_PX)] * 2, **data),
    )
    context = RenderContext(measurer=DefaultTextMeasurer(kerning=POWERPOINT.kerning),
                            rules=POWERPOINT)
    return render_table(table, context)


GRADIENT = m.GradientFill(stops=[m.GradientStop(0.0, m.ResolvedColor("#3f80cd")),
                                 m.GradientStop(1.0, m.ResolvedColor("#9bc1ff"))], angle=270)
SHADOW = m.EffectList(outer_shadow=m.OuterShadow(blur_radius=40000, distance=23000,
                                                 direction=90, color=m.ResolvedColor("#000000", 0.35)))


def test_the_background_is_one_rect_over_the_whole_table_under_the_cells():
    svg = _table(background=GRADIENT)
    rects = re.findall(r"<rect [^>]*>", svg)
    assert 'width="200" height="40"' in rects[0] and "url(#" in rects[0]
    assert len(rects) == 3  # the background, then the two cells with a fill of their own
    assert svg.index(rects[0]) < svg.index(rects[1])


def test_the_effects_apply_to_the_table_as_a_whole():
    svg = _table(background=GRADIENT, effects=SHADOW)
    assert re.match(r'<g transform="[^"]*" filter="url\(#[^)]+\)">', svg)


def test_a_table_without_a_background_is_drawn_as_before():
    svg = _table()
    assert re.match(r'<g transform="[^"]*">', svg)
    assert 'width="200"' not in svg
