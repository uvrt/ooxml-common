"""Blank chart points as Office draws them (round 29): a chart that does not state
``c:dispBlanksAs``, or states it without ``val``, draws a blank as zero, and an area chart
draws ``span`` as zero.  Measured 2026-11-03 in PowerPoint 16 for Mac on screen and in Word
16 for Mac as a PDF export, on line, radar, scatter and area charts; made-up numbers."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

import goldens
from ooxml_common.chart.layout import _blanks_as

C = "http://schemas.openxmlformats.org/drawingml/2006/chart"


@pytest.mark.parametrize("stated, area, expected", [
    (None, False, "zero"), ("", False, "zero"), ("other", False, "zero"),
    ("gap", False, "gap"), ("zero", False, "zero"), ("span", False, "span"),
    ("span", True, "zero"), ("gap", True, "gap"), (None, True, "zero")])
def test_blanks_as_is_what_office_draws(stated, area, expected):
    assert _blanks_as(stated, area=area) == expected


def _chart(plot: str, blanks: str) -> str:
    points = "".join(f'<c:pt idx="{i}"><c:v>{v}</c:v></c:pt>'
                     for i, v in enumerate([4, 6, None, 5, 7]) if v is not None)
    cats = "".join(f'<c:pt idx="{i}"><c:v>{c}</c:v></c:pt>' for i, c in enumerate("ABCDE"))
    return (f'<c:chartSpace xmlns:c="{C}"><c:chart><c:plotArea><c:{plot}>'
            '<c:grouping val="standard"/><c:ser><c:idx val="0"/><c:order val="0"/>'
            f'<c:cat><c:strRef><c:strCache><c:ptCount val="5"/>{cats}</c:strCache></c:strRef></c:cat>'
            f'<c:val><c:numRef><c:numCache><c:ptCount val="5"/>{points}</c:numCache></c:numRef>'
            f'</c:val></c:ser><c:axId val="1"/><c:axId val="2"/></c:{plot}>'
            '<c:catAx><c:axId val="1"/><c:crossAx val="2"/></c:catAx>'
            '<c:valAx><c:axId val="2"/><c:crossAx val="1"/></c:valAx>'
            f'</c:plotArea>{blanks}</c:chart></c:chartSpace>')


def _svg(plot: str, blanks: str) -> str:
    element, _ = goldens.chart_element(ET.fromstring(_chart(plot, blanks)), 400, 250)
    assert element is not None
    return goldens.svg_document([element], element.transform.extent_width,
                                element.transform.extent_height, "powerpoint", [])


@pytest.mark.parametrize("plot", ["lineChart", "areaChart", "radarChart"])
@pytest.mark.parametrize("blanks", ["", '<c:dispBlanksAs/>'])
def test_a_chart_that_does_not_say_draws_its_blanks_as_zero(plot, blanks):
    zero = _svg(plot, '<c:dispBlanksAs val="zero"/>')
    assert _svg(plot, blanks) == zero
    assert _svg(plot, '<c:dispBlanksAs val="gap"/>') != zero


def test_an_area_chart_draws_span_as_zero_and_a_line_spans():
    assert _svg("areaChart", '<c:dispBlanksAs val="span"/>') == \
        _svg("areaChart", '<c:dispBlanksAs val="zero"/>')
    assert _svg("lineChart", '<c:dispBlanksAs val="span"/>') != \
        _svg("lineChart", '<c:dispBlanksAs val="zero"/>')
