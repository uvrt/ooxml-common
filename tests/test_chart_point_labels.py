"""A data label with text of its own: ``c:dLbl/c:tx``, and "Value From Cells".

The facts are PowerPoint 16's export of pptx2svg's ``tools/make_point_label_probe.py``:

* a ``c:dLbl`` whose ``c:tx`` is rich text prints that text, with its runs' formatting --
  a bold red ``Bold`` beside a plain ``plain``, an 18 pt ``Big`` -- and prints it even with
  every ``c:show*`` flag off; on a scatter and a bubble chart alike;
* its fields are the point's: ``CELLRANGE`` the series' ``c15:datalabelsRange`` text,
  ``CATEGORYNAME``, ``SERIESNAME`` and ``VALUE`` (``alpha | North | Sales | 3``);
* a ``c:tx`` that is a ``c:strRef`` prints its cached string;
* ``c15:showDataLabelsRange`` with ``c:showCatName`` and ``c:showVal`` prints
  ``alpha; North; 3`` on one line.

Word reads the same chart part through the same code.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from ooxml_common.chart import rules as chart_rules
from ooxml_common.chart.layout import ChartBuilder, ChartStyle, default_font_size, drawable_plots
from ooxml_common.chart.read import parse_chart_space
from ooxml_common.drawingml import scene as m
from ooxml_common.drawingml import source_tree as s
from ooxml_common.drawingml.color import ColorContext, build_effective_color_map, resolve_color

C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
C15 = "http://schemas.microsoft.com/office/drawing/2012/chart"
FLAGS = ("LegendKey", "Val", "CatName", "SerName", "Percent", "BubbleSize")
TX1 = m.ResolvedColor(hex="#203864")


class _Theme:
    color_scheme = {"dk1": s.SrgbColor(hex="203864"), "lt1": s.SrgbColor(hex="FFFFFF"),
                    "accent1": s.SrgbColor(hex="1F4E79")}


COLORS = ColorContext(_Theme(), build_effective_color_map())


def _fill(source):
    if isinstance(source, s.SourceSolidFill):
        return m.SolidFill(resolve_color(COLORS, source.color))
    return None


def _title(rich, text, size, align):
    return m.TextBody(paragraphs=[m.Paragraph(runs=[m.TextRun(text, m.RunProperties(font_size=size))])])


def flags(**on: bool) -> str:
    return "".join(f'<c:show{name} val="{int(on.get(name, False))}"/>' for name in FLAGS)


def rich(*runs: str) -> str:
    return f"<c:tx><c:rich><a:bodyPr/><a:lstStyle/><a:p>{''.join(runs)}</a:p></c:rich></c:tx>"


def run(text: str, props: str = "", inner: str = "") -> str:
    return f'<a:r><a:rPr lang="en-US" {props}>{inner}</a:rPr><a:t>{text}</a:t></a:r>'


def fld(kind: str, cached: str) -> str:
    return f'<a:fld id="{{0F0E0D0C-0000-4000-8000-000000000001}}" type="{kind}"><a:t>{cached}</a:t></a:fld>'


def d_lbl(index: int, tx: str, **shown: bool) -> str:
    return f'<c:dLbl><c:idx val="{index}"/>{tx}<c:dLblPos val="r"/>{flags(**(shown or {"Val": True}))}</c:dLbl>'


RANGE = (
    f'<c:extLst><c:ext uri="{{02D57815-91ED-43cb-92C2-25804820EDAC}}" xmlns:c15="{C15}">'
    "<c15:datalabelsRange><c15:f>Sheet1!$D$2:$D$4</c15:f><c15:dlblRangeCache><c:ptCount val=\"3\"/>"
    '<c:pt idx="0"><c:v>alpha</c:v></c:pt><c:pt idx="1"><c:v>beta</c:v></c:pt>'
    '<c:pt idx="2"><c:v>gamma</c:v></c:pt></c15:dlblRangeCache></c15:datalabelsRange></c:ext></c:extLst>'
)
SHOW_RANGE = (
    f'<c:extLst><c:ext uri="{{CE6537A1-D6FC-4f65-9D91-7224C49458BB}}" xmlns:c15="{C15}">'
    '<c15:showDataLabelsRange val="1"/></c:ext></c:extLst>'
)


def _num(values) -> str:
    points = "".join(f'<c:pt idx="{i}"><c:v>{v}</c:v></c:pt>' for i, v in enumerate(values))
    return (f"<c:numRef><c:numCache><c:formatCode>General</c:formatCode>"
            f'<c:ptCount val="{len(values)}"/>{points}</c:numCache></c:numRef>')


def _axes() -> str:
    return "".join(
        f'<c:valAx><c:axId val="{own}"/><c:delete val="0"/><c:axPos val="{pos}"/>'
        f'<c:tickLblPos val="nextTo"/><c:crossAx val="{other}"/></c:valAx>'
        for own, other, pos in ((1, 2, "b"), (2, 1, "l"))
    )


def _scatter(labels: str, bubble: bool = False, shown: str = flags(Val=True)) -> str:
    kind = "bubbleChart" if bubble else "scatterChart"
    series = (
        '<c:ser><c:idx val="0"/><c:order val="0"/>'
        '<c:tx><c:strRef><c:strCache><c:ptCount val="1"/><c:pt idx="0"><c:v>Ideas</c:v></c:pt>'
        "</c:strCache></c:strRef></c:tx>"
        f'<c:dLbls>{labels}<c:dLblPos val="r"/>{shown}</c:dLbls>'
        f"<c:xVal>{_num((1, 2, 3, 4))}</c:xVal><c:yVal>{_num((2, 4, 3, 1))}</c:yVal>"
        + (f"<c:bubbleSize>{_num((3, 2, 3, 1))}</c:bubbleSize>" if bubble else "")
        + "</c:ser>"
    )
    style = "" if bubble else '<c:scatterStyle val="lineMarker"/>'
    return (f"<c:{kind}>{style}{series}"
            f'<c:axId val="1"/><c:axId val="2"/></c:{kind}>{_axes()}')


def _column(labels: str, series_ext: str = "") -> str:
    cats = "".join(f'<c:pt idx="{i}"><c:v>{v}</c:v></c:pt>' for i, v in enumerate(("North", "South", "East")))
    return (
        '<c:barChart><c:barDir val="col"/><c:grouping val="clustered"/>'
        '<c:ser><c:idx val="0"/><c:order val="0"/>'
        '<c:tx><c:strRef><c:strCache><c:ptCount val="1"/><c:pt idx="0"><c:v>Sales</c:v></c:pt>'
        "</c:strCache></c:strRef></c:tx>"
        f"<c:dLbls>{labels}</c:dLbls>"
        f'<c:cat><c:strRef><c:strCache><c:ptCount val="3"/>{cats}</c:strCache></c:strRef></c:cat>'
        f"<c:val>{_num((3, 5, 4))}</c:val>{series_ext}</c:ser>"
        '<c:axId val="1"/><c:axId val="2"/></c:barChart>'
        '<c:catAx><c:axId val="1"/><c:delete val="0"/><c:axPos val="b"/><c:crossAx val="2"/></c:catAx>'
        '<c:valAx><c:axId val="2"/><c:delete val="0"/><c:axPos val="l"/><c:crossAx val="1"/></c:valAx>'
    )


def _runs(plot: str, rules=chart_rules.POWERPOINT) -> list[list[m.TextRun]]:
    """Every chart text box drawn, as its runs."""
    xml = (f'<c:chartSpace xmlns:c="{C}" xmlns:a="{A}"><c:chart><c:autoTitleDeleted val="1"/>'
           f"<c:plotArea>{plot}</c:plotArea></c:chart></c:chartSpace>")
    source = parse_chart_space(ET.fromstring(xml))
    plots = drawable_plots(source)
    builder = ChartBuilder(
        source, plots[0], width_pt=480, height_pt=300,
        style=ChartStyle(font_family="Arial", font_size=default_font_size(source), color=TX1,
                         accents=[m.ResolvedColor(hex="#1F4E79")]),
        resolve_fill=_fill, resolve_outline=lambda outline: None, resolve_text=_title, plots=plots,
        rules=rules,
    )
    children, _ = builder.build()
    return [
        list(paragraph.runs)
        for child in children
        if isinstance(child, m.ShapeElement) and child.text_body
        for paragraph in child.text_body.paragraphs
    ]


def _texts(plot: str, rules=chart_rules.POWERPOINT) -> list[str]:
    return ["".join(r.text for r in runs) for runs in _runs(plot, rules)]


def _labels(plot: str, bare: str, rules=chart_rules.POWERPOINT) -> list[str]:
    """The texts ``plot`` draws that the same chart with no labels (``bare``) does not:
    its data labels, with the axes' tick labels taken away."""
    from collections import Counter

    return sorted((Counter(_texts(plot, rules)) - Counter(_texts(bare, rules))).elements())


RICH = (
    d_lbl(0, rich(run("R1")))
    + d_lbl(1, rich(run("Bold", 'b="1"', '<a:solidFill><a:srgbClr val="C00000"/></a:solidFill>'),
                    run(" plain")))
    + d_lbl(2, rich(run("Big", 'sz="1800"')))
    + f'<c:dLbl><c:idx val="3"/>{rich(run("Hidden"))}<c:dLblPos val="r"/>{flags()}</c:dLbl>'
)


@pytest.mark.parametrize("rules", [chart_rules.POWERPOINT, chart_rules.WORD], ids=lambda r: r.name)
@pytest.mark.parametrize("bubble", [False, True], ids=["scatter", "bubble"])
def test_a_points_rich_text_is_printed_instead_of_its_value(bubble, rules):
    labels = _labels(_scatter(RICH, bubble), _scatter("", bubble, flags()), rules)
    assert labels == ["Big", "Bold plain", "Hidden", "R1"]


def test_the_runs_keep_their_formatting():
    runs = {r.text: r.properties for line in _runs(_scatter(RICH)) for r in line}
    assert runs["Bold"].bold and runs["Bold"].color.hex.upper() == "#C00000"
    assert not runs[" plain"].bold and runs[" plain"].color.hex.upper() == "#203864"
    assert runs["Big"].font_size == 18
    assert runs["R1"].font_size == runs[" plain"].font_size == 10


def test_a_label_typed_with_every_show_flag_off_is_still_printed():
    assert "Hidden" in _texts(_scatter(RICH))


def test_fields_are_the_points_own():
    labels = "".join(
        d_lbl(i, rich(fld("CELLRANGE", "[CELLRANGE]"), run(" | "), fld("CATEGORYNAME", "[CATEGORY NAME]"),
                      run(" | "), fld("SERIESNAME", "[SERIES NAME]"), run(" | "), fld("VALUE", "[VALUE]")))
        for i in range(3)
    )
    texts = _texts(_column(labels + flags(Val=True), RANGE))
    assert "alpha | North | Sales | 3" in texts
    assert "beta | South | Sales | 5" in texts
    assert "gamma | East | Sales | 4" in texts


def test_a_cell_reference_prints_its_cached_string():
    label = d_lbl(1, '<c:tx><c:strRef><c:f>Sheet1!$E$3</c:f><c:strCache><c:ptCount val="1"/>'
                     '<c:pt idx="0"><c:v>From a cell</c:v></c:pt></c:strCache></c:strRef></c:tx>')
    labels = _labels(_column(label + flags(Val=True)), _column(flags()))
    assert labels == ["3", "4", "From a cell"]


def test_value_from_cells_comes_first_on_one_line():
    texts = _texts(_column(flags(Val=True, CatName=True) + SHOW_RANGE, RANGE))
    assert {"alpha; North; 3", "beta; South; 5", "gamma; East; 4"} <= set(texts)


def test_a_range_is_read_by_point_index():
    source = parse_chart_space(ET.fromstring(
        f'<c:chartSpace xmlns:c="{C}" xmlns:a="{A}"><c:chart><c:plotArea>'
        f"{_column(flags(Val=True) + SHOW_RANGE, RANGE)}</c:plotArea></c:chart></c:chartSpace>"))
    series = source.plots[0].series[0]
    assert series.label_range == ["alpha", "beta", "gamma"]
    assert series.data_labels.show_range is True
