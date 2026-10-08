"""A table's rows as PowerPoint lays them out: ``a:tr@h`` is a minimum, grown by text.

The heights are measured on PowerPoint 16 for Mac (pptx-agent's
``tools/table_rows_probe.py``, its ``tests/fixtures/table-rows-probe.json``): a row of empty
18 pt Aptos cells is drawn 28.8 pt tall -- one 21.6 pt line and the 0.05 in top and bottom
margins -- whether its stored height is 14.4 or 18 pt.
"""

from __future__ import annotations

import pytest

from ooxml_common.drawingml import scene as m
from ooxml_common.drawingml.context import RenderContext
from ooxml_common.drawingml.rules import POWERPOINT
from ooxml_common.drawingml.shape import _row_heights
from ooxml_common.text.measure import DefaultTextMeasurer

PT = 12700
WIDTH = 2286000


def _cell(*texts: str, size: float = 18.0) -> m.TableCell:
    properties = m.RunProperties(font_size=size, font_family="Aptos")
    return m.TableCell(text_body=m.TextBody(paragraphs=[
        m.Paragraph(runs=[m.TextRun(text, properties)] if text else [],
                    end_para_run_properties=properties)
        for text in texts
    ]))


def _heights(*rows: tuple[float, list[m.TableCell]]) -> list[float]:
    data = m.TableData(rows=[m.TableRow(height=height, cells=cells) for height, cells in rows],
                       columns=[m.TableColumn(width=WIDTH)] * len(rows[0][1]))
    context = RenderContext(measurer=DefaultTextMeasurer(kerning=POWERPOINT.kerning),
                            rules=POWERPOINT)
    return _row_heights(data, context)


@pytest.mark.parametrize("stored_pt", [14.4, 18.0])
def test_a_row_of_empty_cells_is_one_line_tall_as_powerpoint_draws_it(stored_pt):
    (height,) = _heights((stored_pt * PT, [_cell(""), _cell(""), _cell("")]))
    assert height == pytest.approx(28.8 * PT, abs=0.1 * PT)


def test_an_empty_cell_takes_its_end_of_paragraph_size_and_every_paragraph():
    """What follows from the rule (not measured beyond one paragraph at 18 pt): each empty
    paragraph is a line at its own size."""
    (small,) = _heights((0.0, [_cell("", size=10.0)]))
    (two,) = _heights((0.0, [_cell("", "", size=18.0)]))
    assert small < 28.8 * PT and two == pytest.approx((2 * 21.6 + 7.2) * PT, abs=0.1 * PT)


def test_a_row_taller_than_its_empty_line_keeps_its_stored_height():
    (height,) = _heights((86.4 * PT, [_cell(""), _cell("")]))
    assert height == 86.4 * PT


def test_text_is_measured_as_before():
    (one, tall) = _heights((14.4 * PT, [_cell("One"), _cell("")]),
                           (57.6 * PT, [_cell("One", "Two", "Three", "Four", size=14.0)]))
    assert one == pytest.approx(28.8 * PT, abs=0.1 * PT)
    assert tall == pytest.approx(74.4 * PT, abs=0.1 * PT)      # measured: the probe's "mixed" row 3
