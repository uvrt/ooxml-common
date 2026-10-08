"""Chart text as Office draws it: its colour from the ``c:txPr`` cascade, and its number
format from the labels' own ``c:numFmt``.

The facts are PowerPoint's and Word's (16 for Mac) PDF exports of charts made as Office
makes them -- axis and legend text ``tx1`` at ``lumMod`` 65% / ``lumOff`` 35%, data labels
at 75% / 25% -- varied one element at a time under a theme whose ``dk1`` is ``203864``,
so that ``tx1`` cannot be mistaken for black.  Both applications drew every case alike:

=========================================  ==========================================
chart                                      drawn
=========================================  ==========================================
Office's ``c:txPr`` on axes, legend, dLbls  labels and legend ``4572C3``, data labels
                                           ``3760AC``
no ``c:txPr`` anywhere (chart style or     every label ``203864``: plain ``tx1``
not)
only the chart space's, at 65%             every label ``4572C3``
chart space red, value axis ``accent2``,   value labels ``accent2``; category labels,
category axis no fill, no legend or        legend, data labels, chart title and axis
dLbls ``c:txPr``, titles with no fill      titles red
=========================================  ==========================================

Data labels in ``"€"#,##0.0"m"`` read ``€12,4m`` (a Dutch Mac's separators); the same
code source-linked read the cache's ``#,##0.0``; and a value axis source-linked over a
series cached in ``"$"#,##0.00`` read ``$0,00`` up.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from ooxml_common.chart import rules as chart_rules
from ooxml_common.chart.layout import (
    ChartBuilder,
    ChartStyle,
    default_font_size,
    drawable_plots,
    format_number,
)
from ooxml_common.chart.read import parse_chart_space
from ooxml_common.drawingml import scene as m
from ooxml_common.drawingml import source_tree as s
from ooxml_common.drawingml.color import ColorContext, build_effective_color_map, resolve_color

C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"


class _Theme:
    color_scheme = {
        "dk1": s.SrgbColor(hex="203864"),
        "lt1": s.SrgbColor(hex="FFFFFF"),
        "accent1": s.SrgbColor(hex="1F4E79"),
        "accent2": s.SrgbColor(hex="2E8B57"),
    }


COLORS = ColorContext(_Theme(), build_effective_color_map())


def _fill(source):
    if isinstance(source, s.SourceSolidFill):
        return m.SolidFill(resolve_color(COLORS, source.color))
    return None


def _outline(source):
    return None if source is None else m.Outline(width=source.width or 9525, fill=_fill(source.fill))


def _title(rich, text, size, align):
    # As a renderer does: the title's own colour where it states one, else the default.
    color = None
    if rich is not None:
        for paragraph in rich.paragraphs:
            for run in paragraph.runs:
                if run.properties is not None and run.properties.color is not None:
                    color = resolve_color(COLORS, run.properties.color)
    run = m.TextRun(text, m.RunProperties(font_size=size, color=color or TX1))
    return m.TextBody(paragraphs=[m.Paragraph(runs=[run])])


TX1 = m.ResolvedColor(hex="#203864")


def _fill_xml(inner: str) -> str:
    return f"<a:solidFill>{inner}</a:solidFill>"


TX65 = _fill_xml('<a:schemeClr val="tx1"><a:lumMod val="65000"/><a:lumOff val="35000"/></a:schemeClr>')
TX75 = _fill_xml('<a:schemeClr val="tx1"><a:lumMod val="75000"/><a:lumOff val="25000"/></a:schemeClr>')


def _tx_pr(fill: str | None, size: int = 1197) -> str:
    return (f'<c:txPr><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="{size}">{fill or ""}</a:defRPr>'
            '</a:pPr><a:endParaRPr lang="en-US"/></a:p></c:txPr>')


def _chart(*, axis: str | None = TX65, value_axis: str | None = None, legend: str | None = TX65,
           labels: str | None = TX75, space: str | None = "", title: str = "",
           label_format: str = '<c:numFmt formatCode="&quot;€&quot;#,##0.0&quot;m&quot;" sourceLinked="0"/>',
           cache_format: str = "#,##0.0", value_format: str = "") -> str:
    """A clustered column chart in add_chart's shape; ``None`` leaves an element's
    ``c:txPr`` out, ``""`` writes one stating no fill."""
    tx = lambda fill: "" if fill is None else _tx_pr(fill)  # noqa: E731
    space_tx = "" if space is None else _tx_pr(space).replace(' sz="1197"', "")
    return f"""<c:chartSpace xmlns:c="{C}" xmlns:a="{A}">
  <c:chart>{title}<c:autoTitleDeleted val="{0 if title else 1}"/>
    <c:plotArea>
      <c:barChart>
        <c:barDir val="col"/><c:grouping val="clustered"/><c:varyColors val="0"/>
        <c:ser>
          <c:idx val="0"/><c:order val="0"/>
          <c:tx><c:strRef><c:strCache><c:ptCount val="1"/><c:pt idx="0"><c:v>North</c:v></c:pt></c:strCache></c:strRef></c:tx>
          <c:spPr><a:solidFill><a:schemeClr val="accent1"/></a:solidFill></c:spPr>
          <c:dLbls>{label_format}{tx(labels)}<c:showLegendKey val="0"/><c:showVal val="1"/>
            <c:showCatName val="0"/><c:showSerName val="0"/><c:showPercent val="0"/><c:showBubbleSize val="0"/></c:dLbls>
          <c:cat><c:strRef><c:strCache><c:ptCount val="2"/>
            <c:pt idx="0"><c:v>Q1</c:v></c:pt><c:pt idx="1"><c:v>Q2</c:v></c:pt></c:strCache></c:strRef></c:cat>
          <c:val><c:numRef><c:numCache><c:formatCode>{cache_format}</c:formatCode><c:ptCount val="2"/>
            <c:pt idx="0"><c:v>12.4</c:v></c:pt><c:pt idx="1"><c:v>14.9</c:v></c:pt></c:numCache></c:numRef></c:val>
        </c:ser>
        <c:gapWidth val="50"/><c:axId val="1"/><c:axId val="2"/>
      </c:barChart>
      <c:catAx><c:axId val="1"/><c:delete val="0"/><c:axPos val="b"/>
        <c:majorTickMark val="none"/><c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/>
        {tx(axis)}<c:crossAx val="2"/></c:catAx>
      <c:valAx><c:axId val="2"/><c:delete val="0"/><c:axPos val="l"/>{value_format}
        <c:majorTickMark val="none"/><c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/>
        {tx(axis if value_axis is None else value_axis)}<c:crossAx val="1"/></c:valAx>
    </c:plotArea>
    <c:legend><c:legendPos val="b"/>{tx(legend)}</c:legend>
  </c:chart>
  {space_tx}
</c:chartSpace>"""


def _texts(xml: str, rules=chart_rules.POWERPOINT) -> dict[str, str]:
    """Every piece of chart text drawn, mapped to the colour it is drawn in."""
    source = parse_chart_space(ET.fromstring(xml))
    plots = drawable_plots(source)
    builder = ChartBuilder(
        source, plots[0], width_pt=480, height_pt=300,
        style=ChartStyle(font_family="Arial", font_size=default_font_size(source), color=TX1,
                         accents=[m.ResolvedColor(hex="#1F4E79")]),
        resolve_fill=_fill, resolve_outline=_outline, resolve_text=_title, plots=plots, rules=rules,
    )
    children, _ = builder.build()
    return {
        run.text: run.properties.color.hex.upper()
        for child in children
        if isinstance(child, m.ShapeElement) and child.text_body
        for paragraph in child.text_body.paragraphs
        for run in paragraph.runs
    }


RULES = [chart_rules.POWERPOINT, chart_rules.WORD]


@pytest.mark.parametrize("rules", RULES, ids=lambda rules: rules.name)
def test_office_chart_text_is_tx1_at_65_percent_and_its_data_labels_at_75(rules):
    texts = _texts(_chart(), rules)
    assert texts["Q1"] == texts["North"] == "#4572C3"   # category label, legend entry
    assert texts["14.0"] == "#4572C3"                    # a value-axis label
    assert texts["€12.4m"] == "#3760AC"                  # a data label


@pytest.mark.parametrize("rules", RULES, ids=lambda rules: rules.name)
def test_a_chart_that_states_no_text_properties_draws_in_plain_tx1(rules):
    texts = _texts(_chart(axis=None, legend=None, labels=None, space=None), rules)
    assert set(texts.values()) == {"#203864"}


@pytest.mark.parametrize("rules", RULES, ids=lambda rules: rules.name)
def test_the_chart_space_fill_reaches_every_element_that_states_none(rules):
    texts = _texts(_chart(axis=None, legend=None, labels=None, space=TX65), rules)
    assert set(texts.values()) == {"#4572C3"}


@pytest.mark.parametrize("rules", RULES, ids=lambda rules: rules.name)
def test_an_elements_own_fill_wins_over_the_chart_spaces(rules):
    red = _fill_xml('<a:srgbClr val="FF0000"/>')
    texts = _texts(_chart(axis="", value_axis=_fill_xml('<a:schemeClr val="accent2"/>'), legend=None,
                          labels=None, space=red), rules)
    assert texts["14.0"] == "#2E8B57"                    # the value axis' accent2
    assert texts["Q1"] == texts["North"] == texts["€12.4m"] == "#FF0000"


@pytest.mark.parametrize("rules", RULES, ids=lambda rules: rules.name)
def test_a_title_stating_no_colour_takes_the_chart_spaces_not_its_axis(rules):
    title = ('<c:title><c:tx><c:rich><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="1800"/></a:pPr>'
             '<a:r><a:rPr lang="en-US"/><a:t>Revenue</a:t></a:r></a:p></c:rich></c:tx>'
             '<c:overlay val="0"/></c:title>')
    red = _fill_xml('<a:srgbClr val="FF0000"/>')
    assert _texts(_chart(title=title, space=red), rules)["Revenue"] == "#FF0000"
    # With nothing in the chart space, the renderer's own colour stands.
    assert _texts(_chart(title=title), rules)["Revenue"] == "#203864"


def test_data_labels_draw_their_own_number_format_unless_source_linked():
    assert "€12.4m" in _texts(_chart())
    linked = _chart(label_format='<c:numFmt formatCode="&quot;€&quot;#,##0.0&quot;m&quot;" sourceLinked="1"/>',
                    cache_format="#,##0.00")
    assert "12.40" in _texts(linked) and "€12.4m" not in _texts(linked)
    assert "$12.40" in _texts(_chart(label_format="", cache_format='"$"#,##0.00'))


def test_a_source_linked_value_axis_takes_the_series_format_over_its_own():
    linked = '<c:numFmt formatCode="#,##0.0" sourceLinked="1"/>'
    texts = _texts(_chart(label_format="", cache_format='"$"#,##0.00', value_format=linked))
    assert "$0.00" in texts and "0.0" not in texts
    chosen = '<c:numFmt formatCode="&quot;€&quot;0&quot;m&quot;" sourceLinked="0"/>'
    assert "€0m" in _texts(_chart(value_format=chosen))


@pytest.mark.parametrize(
    "value,code,expected",
    [
        # Measured (the separators are the renderer's; Office's are the system's).
        (12.4, '"€"#,##0.0"m"', "€12.4m"),
        (7.1, "#,##0.00_);(#,##0.00)", "7.10 "),
        (5.2, "[$€-413] #,##0.0", "€ 5.2"),
        (0.0, '"€"0"m"', "€0m"),
        (20.0, '"€"0"m"', "€20m"),
        (12.4, '"$"#,##0.00', "$12.40"),
        # The rest of the language the same code reads.
        (12.4, "$#,##0.00", "$12.40"),
        (-12.4, '"€"#,##0.0"m"', "-€12.4m"),
        (0.0, '#,##0;-#,##0;"-"', "-"),
        (1234567.0, '#,##0.0,,"M"', "1.2M"),
        (1500.0, '0,"k"', "2k"),
        (1.5, "0.0#", "1.5"),
        (1.25, "0.0#", "1.25"),
        (12345.0, "0.00E+00", "1.23E+04"),
        (3.0, 'General" units"', "3 units"),
        (43000.0, "m/d/yyyy", "43000"),
        (-1234.0, "#,##0;(#,##0)", "(1,234)"),
    ],
)
def test_a_number_format_keeps_the_text_round_the_number(value, code, expected):
    assert format_number(value, code) == expected


# -- Radar category labels ---------------------------------------------------------------

#: Each label's centre and baseline from its vertex, in points, as Word and PowerPoint
#: drew them: the radars of 5 categories in Aptos 9 pt (Word, radius 94.99 pt) and of 8 in
#: Arial 12 pt (PowerPoint's 1197, radius 148.11 pt).
RADAR_MEASURED = {
    ("Aptos", 9.0, 94.99): [
        ("Quality", -0.01, -7.77),
        ("Price", 13.58, 0.99),
        ("Delivery", 17.85, 5.19),
        ("Sustainability", -28.59, 5.19),
        ("Service", -17.90, 0.99),
    ],
    ("Arial", 11.97, 148.11): [
        ("Quality", -0.13, -9.40),
        ("Price", 18.06, -0.46),
        ("Delivery", 27.47, 3.77),
        ("Sustainability", 39.72, 8.00),
        ("Service", -0.12, 16.94),
        ("Innovation", -31.61, 8.00),
        ("Risk", -17.74, 3.77),
        ("Support", -24.96, -0.46),
    ],
}


def _radar(face: str, size: float, names: list[str]) -> str:
    cats = "".join(f'<c:pt idx="{i}"><c:v>{name}</c:v></c:pt>' for i, name in enumerate(names))
    vals = "".join(f'<c:pt idx="{i}"><c:v>3</c:v></c:pt>' for i in range(len(names)))
    return f"""<c:chartSpace xmlns:c="{C}" xmlns:a="{A}"><c:chart><c:plotArea>
  <c:radarChart><c:radarStyle val="marker"/><c:varyColors val="0"/>
    <c:ser><c:idx val="0"/><c:order val="0"/>
      <c:cat><c:strRef><c:strCache><c:ptCount val="{len(names)}"/>{cats}</c:strCache></c:strRef></c:cat>
      <c:val><c:numRef><c:numCache><c:ptCount val="{len(names)}"/>{vals}</c:numCache></c:numRef></c:val>
    </c:ser><c:axId val="1"/><c:axId val="2"/></c:radarChart>
  <c:catAx><c:axId val="1"/><c:delete val="0"/><c:axPos val="b"/>
    <c:txPr><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="{round(size * 100)}"><a:latin typeface="{face}"/>
    </a:defRPr></a:pPr></a:p></c:txPr><c:crossAx val="2"/></c:catAx>
  <c:valAx><c:axId val="2"/><c:delete val="0"/><c:axPos val="l"/><c:crossAx val="1"/></c:valAx>
</c:plotArea></c:chart></c:chartSpace>"""


@pytest.mark.parametrize("face,size,radius", list(RADAR_MEASURED), ids=lambda value: str(value))
def test_radar_category_labels_stand_off_their_vertex_by_four_percent_of_the_radius(face, size, radius):
    """Every label within 0.3 pt across and 0.7 pt down of Office's, on spokes at every
    angle -- where a fixed 2.85 pt gap and a box hung from the anchor by its corner were
    up to 3.1 pt across and 9.7 pt down out on the sloping ones."""
    import math

    measured = RADAR_MEASURED[(face, size, radius)]
    names = [name for name, _, _ in measured]
    source = parse_chart_space(ET.fromstring(_radar(face, size, names)))
    plots = drawable_plots(source)
    builder = ChartBuilder(
        source, plots[0], width_pt=480, height_pt=360,
        style=ChartStyle(font_family=face, font_size=size, color=TX1, accents=[TX1]),
        resolve_fill=_fill, resolve_outline=_outline, resolve_text=_title, plots=plots,
    )
    font = builder._label_font(next(axis for axis in source.axes if axis.kind == "catAx"))
    assert font.size == pytest.approx(size)
    centre = (240.0, 180.0)
    builder._draw_radar_category_labels(centre, radius, [[name] for name in names], font)
    drawn = {}
    for element in builder.elements:
        run = element.text_body.paragraphs[0].runs[0]
        left = element.transform.offset_x / 12700
        width = element.transform.extent_width / 12700
        baseline = element.transform.offset_y / 12700 + builder._first_baseline(font.box)
        drawn[run.text] = (left + width / 2, baseline)
    for index, (name, across, down) in enumerate(measured):
        angle = 2 * math.pi * index / len(names)
        vertex = (centre[0] + radius * math.sin(angle), centre[1] - radius * math.cos(angle))
        x, y = drawn[name]
        assert x - vertex[0] == pytest.approx(across, abs=0.3), name
        assert y - vertex[1] == pytest.approx(down, abs=0.7), name
