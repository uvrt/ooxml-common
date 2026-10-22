"""What a live, editable view of a slide asks of the drawing (round 13): table cells and
text bodies marked with ``data-`` attributes only (``RenderContext.edit_marks``), and
hyperlinks left out (``RenderContext.hyperlinks``).  Off, the drawing is what it was;
on, only attributes and attribute-only groups are added, so it draws the same."""

from __future__ import annotations

import re

from ooxml_common.drawingml import scene as m
from ooxml_common.drawingml.context import RenderContext
from ooxml_common.drawingml.elements import render_element
from ooxml_common.drawingml.rules import POWERPOINT
from ooxml_common.drawingml.shape import render_table
from ooxml_common.text.measure import DefaultTextMeasurer

EMU_PER_PX = 9525
LINK = m.Hyperlink(url="https://example.com/a?b=1&c=2")


def _context(**flags) -> RenderContext:
    return RenderContext(measurer=DefaultTextMeasurer(kerning=POWERPOINT.kerning), rules=POWERPOINT,
                         **flags)


def _body(text: str, link: m.Hyperlink | None = None) -> m.TextBody:
    run = m.TextRun(text, m.RunProperties(font_size=18, font_family="Arial", hyperlink=link))
    return m.TextBody(paragraphs=[m.Paragraph(runs=[run])])


def _shape(element_id: str | None = "256.4", link: m.Hyperlink | None = None, text_link=None) -> m.ShapeElement:
    return m.ShapeElement(
        transform=m.Transform(extent_width=200 * EMU_PER_PX, extent_height=50 * EMU_PER_PX),
        geometry=m.PresetGeometry("rect"),
        fill=m.SolidFill(m.ResolvedColor("#4472c4")),
        text_body=_body("Quarterly plan", text_link),
        hyperlink=link,
        element_id=element_id,
    )


def _table(element_id: str | None = "256.7") -> m.TableElement:
    filled = m.SolidFill(m.ResolvedColor("#ff0000"))
    rows = [
        m.TableRow(height=20 * EMU_PER_PX, cells=[m.TableCell(text_body=_body("a"), fill=filled), m.TableCell()]),
        # The second row's first cell spans both columns: the position it hides is not drawn.
        m.TableRow(height=20 * EMU_PER_PX, cells=[m.TableCell(text_body=_body("b"), grid_span=2),
                                                   m.TableCell(h_merge=True)]),
    ]
    return m.TableElement(
        transform=m.Transform(extent_width=200 * EMU_PER_PX, extent_height=40 * EMU_PER_PX),
        table=m.TableData(rows=rows, columns=[m.TableColumn(width=100 * EMU_PER_PX)] * 2),
        element_id=element_id,
    )


def _without_marks(svg: str) -> str:
    """``svg`` with the marks taken out: attribute-only groups unwrapped, ``data-pptx-text``
    and the cells' empty boxes dropped."""
    svg = re.sub(r'<g data-pptx-text="[^"]*">((?:(?!<g data-pptx-text).)*?)</g>(?=</g>$)', r"\1", svg)
    svg = svg.replace(' data-pptx-text="cell"', "")
    svg = re.sub(r'<rect [^>]*fill="none"/>', "", svg)
    return re.sub(r'<g data-pptx-id="[^"]*/cell\d+,\d+">(.*?)</g>(?=<g data-pptx-id|<line|</g>$)',
                  lambda match: match.group(1), svg)


def test_off_by_default():
    assert RenderContext().edit_marks is False and RenderContext().hyperlinks is True
    svg = render_table(_table(), _context())
    assert "data-pptx-text" not in svg and "/cell" not in svg


def test_each_drawn_cell_is_a_group_named_by_its_grid_position():
    svg = render_table(_table(), _context(edit_marks=True))
    cells = re.findall(r'<g data-pptx-id="([^"]*)">', svg)
    assert cells == ["256.7/cell0,0", "256.7/cell0,1", "256.7/cell1,0"]   # 1,1 is hidden by the span
    # A cell with no fill still has its box, drawn as nothing.
    assert re.search(r'data-pptx-id="256.7/cell0,1"><rect x="100" y="0" width="100" height="[\d.]+" fill="none"/></g>', svg)
    # Its text is marked as a cell's.
    assert svg.count('data-pptx-text="cell"') == 2


def test_cell_marks_only_add_groups_and_attributes():
    plain = render_table(_table(), _context())
    marked = render_table(_table(), _context(edit_marks=True))
    assert _without_marks(marked) == plain


def test_a_table_without_an_id_is_not_marked():
    svg = render_table(_table(element_id=None), _context(edit_marks=True))
    assert "data-pptx-id" not in svg and "data-pptx-text" not in svg


def test_a_shapes_text_body_is_marked():
    plain = render_element(_shape(), _context())
    marked = render_element(_shape(), _context(edit_marks=True))
    assert marked.count('<g data-pptx-text="shape">') == 1
    assert marked.replace('<g data-pptx-text="shape">', "", 1)[:-len("</g></g>")] + "</g>" == plain
    # A SmartArt drawing's piece says so; a shape no id owns (a chart's) is not marked.
    assert '<g data-pptx-text="diagram">' in render_element(_shape("256.9/0/3"), _context(edit_marks=True))
    assert "data-pptx-text" not in render_element(_shape(None), _context(edit_marks=True))


def test_hyperlinks_can_be_left_out_keeping_what_they_cover():
    shape = _shape(link=LINK, text_link=LINK)
    linked = render_element(shape, _context())
    assert linked.startswith('<a href="https://example.com/a?b=1&amp;c=2">') and linked.count("<a ") == 2
    bare = render_element(shape, _context(hyperlinks=False))
    assert "<a " not in bare and "</a>" not in bare
    assert re.sub(r"<a [^>]*>|</a>", "", linked) == bare


def test_scoped_ids_count_from_one_in_each_scope():
    context = _context()
    assert context.new_id("grad") == "grad-1"
    context.scope_ids("s256_4-")
    assert [context.new_id("grad"), context.new_id("clip")] == ["grad-s256_4-1", "clip-s256_4-2"]
    context.scope_ids("s256_5-")
    assert context.new_id("grad") == "grad-s256_5-1"


def test_marked_shapes_leave_their_path_out():
    shape = _shape()
    shape.element_path = "3"
    assert 'data-pptx-path="3"' in render_element(shape, _context())
    assert "data-pptx-path" not in render_element(shape, _context(edit_marks=True))
