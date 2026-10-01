"""Word's chart rules (``chart.rules.WORD``) and the scene renderers' Word fields
(``drawingml.rules.WORD``), each against the PowerPoint default it departs from.

The measurements are docx2svg's (``tools/make_chart_probe.py``, ``make_smartart_probe.py``),
recorded and scored in its suite; what this file holds is that each rule does what its
field says, and that ``POWERPOINT`` -- what pptx2svg draws -- does not move.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

from ooxml_common.chart import rules as chart_rules
from ooxml_common.chart.layout import (
    EMU_PER_POINT,
    LEGEND_SWATCH_EM,
    TITLE_BAND_LINES,
    WORD_LEGEND_LEAD_PT,
    WORD_LEGEND_LEFT_PT,
    WORD_LEGEND_TRAIL_PT,
    WORD_TITLE_PAD_PT,
    ChartBuilder,
    ChartStyle,
    default_font_size,
    drawable_plots,
    font_box,
    text_width,
)
from ooxml_common.chart.read import parse_chart_space
from ooxml_common.drawingml import rules as drawing_rules
from ooxml_common.drawingml import scene as m
from ooxml_common.drawingml import source_tree as s
from ooxml_common.drawingml.context import RenderContext
from ooxml_common.drawingml.geometry import render_geometry, scaled_path_data
from ooxml_common.drawingml.textbody import render_text_body

C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
WIDTH, HEIGHT = 432.0, 252.0


def _series(index: int, name: str, values, extra: str = "") -> str:
    points = "".join(f"<c:pt idx='{k}'><c:v>{v}</c:v></c:pt>" for k, v in enumerate(values))
    cats = "".join(f"<c:pt idx='{k}'><c:v>{c}</c:v></c:pt>" for k, c in enumerate("NSEW"))
    return (f"<c:ser><c:idx val='{index}'/><c:order val='{index}'/><c:tx><c:strRef><c:strCache>"
            f"<c:ptCount val='1'/><c:pt idx='0'><c:v>{name}</c:v></c:pt></c:strCache></c:strRef></c:tx>{extra}"
            f"<c:cat><c:strRef><c:strCache><c:ptCount val='4'/>{cats}</c:strCache></c:strRef></c:cat>"
            f"<c:val><c:numRef><c:numCache><c:formatCode>General</c:formatCode><c:ptCount val='4'/>{points}"
            "</c:numCache></c:numRef></c:val></c:ser>")


def chart(*, direction="col", grouping="clustered", legend="r", title=True, space="", plot="",
          kind="barChart", series_extra="") -> str:
    groups = (f"<c:{kind}>" + (f"<c:barDir val='{direction}'/>" if kind == "barChart" else "")
              + f"<c:grouping val='{grouping}'/>"
              + _series(0, "Plan", (4, 2, 3, 5), series_extra) + _series(1, "Actual", (2, 4, 1, 3), series_extra)
              + ("<c:overlap val='100'/>" if grouping != "clustered" and kind == "barChart" else "")
              + f"<c:axId val='1'/><c:axId val='2'/></c:{kind}>")
    cat_pos, val_pos = ("l", "b") if direction == "bar" else ("b", "l")
    axes = (f"<c:catAx><c:axId val='1'/><c:delete val='0'/><c:axPos val='{cat_pos}'/><c:crossAx val='2'/></c:catAx>"
            f"<c:valAx><c:axId val='2'/><c:delete val='0'/><c:axPos val='{val_pos}'/><c:majorGridlines/>"
            "<c:crossAx val='1'/></c:valAx>")
    head = ("<c:title><c:tx><c:rich><a:bodyPr/><a:p><a:r><a:t>Sales</a:t></a:r></a:p></c:rich></c:tx></c:title>"
            "<c:autoTitleDeleted val='0'/>" if title else "<c:autoTitleDeleted val='1'/>")
    legend_xml = f"<c:legend><c:legendPos val='{legend}'/></c:legend>" if legend else ""
    return (f"<c:chartSpace xmlns:c='{C}' xmlns:a='{A}'><c:chart>{head}<c:plotArea><c:layout/>{groups}{axes}{plot}"
            f"</c:plotArea>{legend_xml}</c:chart>{space}</c:chartSpace>")


def _fill(source):
    if isinstance(source, s.SourceNoFill):
        return m.NoFill()
    if isinstance(source, s.SourceSolidFill) and isinstance(source.color, s.SrgbColor):
        return m.SolidFill(m.ResolvedColor(hex="#" + source.color.hex.upper()))
    return None


def _outline(source):
    if source is None:
        return None
    paint = _fill(source.fill) if source.fill is not None else None
    if isinstance(paint, m.NoFill):
        return None
    return m.Outline(width=source.width or 9525, fill=paint)


def _title(rich, text, size, align):
    return m.TextBody(paragraphs=[m.Paragraph(
        runs=[m.TextRun(text, m.RunProperties(font_size=size, font_family="Arial"))],
        properties=m.ParagraphProperties(alignment=align))])


def build(xml: str, rules=chart_rules.POWERPOINT):
    source = parse_chart_space(ET.fromstring(xml))
    plots = drawable_plots(source)
    builder = ChartBuilder(
        source, plots[0], width_pt=WIDTH, height_pt=HEIGHT,
        style=ChartStyle(font_family="Aptos", font_size=default_font_size(source),
                         color=m.ResolvedColor(hex="#000000"),
                         accents=[m.ResolvedColor(hex="#4472C4"), m.ResolvedColor(hex="#ED7D31")]),
        resolve_fill=_fill, resolve_outline=_outline, resolve_text=_title, plots=plots, rules=rules,
    )
    children, _data = builder.build()
    return builder, children


def boxes(children):
    """``(fill hex or None, outline (hex, width) or None, left, top, right, bottom)`` pt,
    of every shape without text."""
    out = []
    for child in children:
        if not isinstance(child, m.ShapeElement) or child.text_body is not None:
            continue
        t = child.transform
        fill = child.fill.color.hex if isinstance(child.fill, m.SolidFill) else None
        line = ((child.outline.fill.color.hex, child.outline.width)
                if child.outline is not None and isinstance(child.outline.fill, m.SolidFill) else None)
        out.append((fill, line, t.offset_x / EMU_PER_POINT, t.offset_y / EMU_PER_POINT,
                    (t.offset_x + t.extent_width) / EMU_PER_POINT, (t.offset_y + t.extent_height) / EMU_PER_POINT))
    return out


def texts(children):
    """``{text: (left, top)}`` pt of every one-run label."""
    out = {}
    for child in children:
        if isinstance(child, m.ShapeElement) and child.text_body is not None:
            run = child.text_body.paragraphs[0].runs[0]
            out.setdefault(run.text, (child.transform.offset_x / EMU_PER_POINT,
                                      child.transform.offset_y / EMU_PER_POINT))
    return out


def test_word_is_a_set_of_fields_and_powerpoint_is_still_the_default():
    assert chart_rules.WORD.drawing is drawing_rules.WORD
    defaults = chart_rules.ChartRules("x", drawing_rules.POWERPOINT)
    for name in ("chart_fill", "chart_line", "plot_fill", "plot_line", "title", "side_legend",
                 "legend_under_title", "top_right_legend", "legend_order", "bars_upward",
                 "stated_line_width", "legend_key_outlines"):
        assert getattr(chart_rules.POWERPOINT, name) == getattr(defaults, name), name
    for name in ("custom_path_strokes", "text_size_grid", "first_baseline"):
        assert getattr(drawing_rules.POWERPOINT, name) == getattr(drawing_rules.DrawingRules(
            "x", drawing_rules.POWERPOINT.color), name), name


def test_word_paints_an_unstated_chart_space_and_plot_area():
    _builder, children = build(chart())
    assert not any(box[:2] == ("#FFFFFF", None) for box in boxes(children))
    _builder, children = build(chart(), chart_rules.WORD)
    frame = [box for box in boxes(children) if box[2:] == (0.0, 0.0, WIDTH, HEIGHT)]
    assert frame == [("#FFFFFF", ("#898989", 6350.0), 0.0, 0.0, WIDTH, HEIGHT)]
    assert sum(1 for box in boxes(children) if box[:2] == ("#FFFFFF", None)) == 1


@pytest.mark.parametrize("space,fill,line", [
    ("<c:spPr><a:solidFill><a:srgbClr val='F2F2F2'/></a:solidFill></c:spPr>", "#F2F2F2", ("#898989", 6350.0)),
    ("<c:spPr><a:ln w='12700'><a:solidFill><a:srgbClr val='4472C4'/></a:solidFill></a:ln></c:spPr>", "#FFFFFF",
     ("#4472C4", 12700)),
    ("<c:spPr><a:noFill/><a:ln><a:noFill/></a:ln></c:spPr>", None, None),
])
def test_word_defaults_a_chart_space_fill_and_line_each_on_its_own(space, fill, line):
    _builder, children = build(chart(space=space), chart_rules.WORD)
    frame = [box for box in boxes(children) if box[2:] == (0.0, 0.0, WIDTH, HEIGHT)]
    assert frame == ([] if fill is None and line is None else [(fill, line, 0.0, 0.0, WIDTH, HEIGHT)])


def test_word_draws_the_plot_area_s_own_line():
    plot = "<c:spPr><a:ln w='12700'><a:solidFill><a:srgbClr val='C00000'/></a:solidFill></a:ln></c:spPr>"
    _builder, children = build(chart(plot=plot))
    assert not any(box[1] == ("#C00000", 12700) for box in boxes(children))
    _builder, children = build(chart(plot=plot), chart_rules.WORD)
    assert [box[:2] for box in boxes(children) if box[1] == ("#C00000", 12700)] == [("#FFFFFF", ("#C00000", 12700))]


def test_word_s_title_band_is_its_pitch_and_nine_points():
    _builder, children = build(chart(), chart_rules.WORD)
    title = font_box("Arial", 18.0)
    top = min(box[3] for box in boxes(children) if box[0] == "#FFFFFF" and box[2] > 0)
    untitled = min(box[3] for box in boxes(build(chart(title=False), chart_rules.WORD)[1])
                   if box[0] == "#FFFFFF" and box[2] > 0)
    assert top - untitled == pytest.approx(title.pitch + WORD_TITLE_PAD_PT)
    # PowerPoint's ratio, measured on this one face and size, is the same band to 0.002 pt.
    assert TITLE_BAND_LINES * title.line_height == pytest.approx(title.pitch + WORD_TITLE_PAD_PT, abs=0.002)


@pytest.mark.parametrize("size", [600, 1000, 1800])
def test_word_s_side_legend_stands_against_the_frame(size):
    space = f"<c:txPr><a:bodyPr/><a:p><a:pPr><a:defRPr sz='{size}'/></a:pPr></a:p></c:txPr>"
    _builder, children = build(chart(space=space), chart_rules.WORD)
    em = size / 100
    widest = text_width("Actual", "Aptos", em)
    keys = [box for box in boxes(children) if box[0] in ("#4472C4", "#ED7D31") and box[4] - box[2] < 12
            and abs((box[4] - box[2]) - LEGEND_SWATCH_EM * em) < 1e-6]
    label = texts(children)["Actual"][0]
    assert label + widest == pytest.approx(WIDTH - WORD_LEGEND_TRAIL_PT, abs=0.01)
    plot_right = max(box[4] for box in boxes(children) if box[0] == "#FFFFFF" and box[2] > 0 and box[4] < WIDTH)
    assert keys[0][2] - plot_right == pytest.approx(WORD_LEGEND_LEAD_PT + LEGEND_SWATCH_EM * em / 2, abs=0.01)


def test_word_s_left_legend_key_is_a_fixed_pad_and_half_a_key_in():
    _builder, children = build(chart(legend="l"), chart_rules.WORD)
    keys = [box for box in boxes(children) if box[0] == "#4472C4" and box[4] - box[2] < 6]
    assert keys[0][2] == pytest.approx(WORD_LEGEND_LEFT_PT + LEGEND_SWATCH_EM * 10 / 2)


def _legend_order(children):
    found = {name: xy for name, xy in texts(children).items() if name in ("Plan", "Actual")}
    return sorted(found, key=lambda name: (found[name][1], found[name][0]))


@pytest.mark.parametrize("direction,grouping,legend,reversed_", [
    ("col", "clustered", "r", False),
    ("col", "stacked", "r", True),
    ("col", "stacked", "b", False),
    ("bar", "clustered", "r", True),
    ("bar", "clustered", "b", True),
    ("bar", "stacked", "r", False),
])
def test_word_lists_the_legend_in_the_order_the_plot_stacks_it(direction, grouping, legend, reversed_):
    xml = chart(direction=direction, grouping=grouping, legend=legend)
    assert _legend_order(build(xml)[1]) == ["Plan", "Actual"]
    assert _legend_order(build(xml, chart_rules.WORD)[1]) == (["Actual", "Plan"] if reversed_ else ["Plan", "Actual"])


def test_word_s_clustered_bars_put_the_first_series_lowest():
    def first_bar(rules):
        bars = [box for box in boxes(build(chart(direction="bar"), rules)[1]) if box[0] in ("#4472C4", "#ED7D31")
                and box[4] - box[2] > 20]
        lowest = max(bars, key=lambda box: box[5])
        return lowest[0]

    assert first_bar(chart_rules.POWERPOINT) == "#ED7D31"
    assert first_bar(chart_rules.WORD) == "#4472C4"


def test_word_puts_a_top_legend_under_the_title():
    def key_top(rules, title):
        return min(box[3] for box in boxes(build(chart(legend="t", title=title), rules)[1]) if box[0] == "#4472C4"
                   and box[4] - box[2] < 6)

    assert key_top(chart_rules.POWERPOINT, True) == pytest.approx(key_top(chart_rules.POWERPOINT, False))
    band = font_box("Arial", 18.0).pitch + WORD_TITLE_PAD_PT
    assert key_top(chart_rules.WORD, True) - key_top(chart_rules.WORD, False) == pytest.approx(band)


def test_word_s_top_right_legend_is_a_column_at_the_right():
    _builder, children = build(chart(legend="tr"), chart_rules.WORD)
    plan, actual = texts(children)["Plan"], texts(children)["Actual"]
    assert plan[0] == pytest.approx(actual[0]) and actual[1] > plan[1]
    assert plan[0] > WIDTH * 0.8


def test_word_keeps_a_line_series_stated_width():
    xml = chart(kind="lineChart", grouping="standard", series_extra="<c:spPr><a:ln w='28575'/></c:spPr>")

    def widths(rules):
        return {child.outline.width for child in build(xml, rules)[1]
                if isinstance(child, m.ShapeElement) and isinstance(child.geometry, m.CustomGeometry)
                and child.outline is not None}

    assert widths(chart_rules.POWERPOINT) == {19050.0}
    assert widths(chart_rules.WORD) == {28575}


def test_word_outlines_a_legend_key_with_its_series_line():
    line = "<c:spPr><a:solidFill><a:srgbClr val='70AD47'/></a:solidFill><a:ln><a:solidFill><a:srgbClr val='000000'/>" \
           "</a:solidFill></a:ln></c:spPr>"

    def outlined_keys(rules):
        return [box for box in boxes(build(chart(series_extra=line), rules)[1])
                if box[0] == "#70AD47" and box[4] - box[2] < 6 and box[1] is not None]

    assert outlined_keys(chart_rules.POWERPOINT) == []
    assert len(outlined_keys(chart_rules.WORD)) == 2


def test_a_custom_path_s_coordinates_scale_and_its_stroke_does_not():
    assert scaled_path_data("M 0 0 L 10 20 C 1 2 3 4 5 6 Z", 2.0, 0.5) == "M 0 0 L 20 10 C 2 1 6 2 10 3 Z"
    assert scaled_path_data("M 0 0 A 10 20 30 0 1 40 50", 2.0, 0.5) == "M 0 0 A 20 10 30 0 1 80 25"
    geometry = m.CustomGeometry(paths=[m.CustomGeometryPath(width=100, height=50, commands="M 0 0 L 100 50")])
    assert 'transform="scale(2, 2)"' in render_geometry(geometry, 200, 100)
    assert render_geometry(geometry, 200, 100, scale_paths=True) == '<path d="M 0 0 L 200 100"/>'


def _body(size: float, spacing: int | None = None, text: str = "Text") -> m.TextBody:
    props = m.ParagraphProperties(line_spacing=m.PercentSpacing(spacing) if spacing else None)
    return m.TextBody(
        paragraphs=[m.Paragraph(runs=[m.TextRun(text, m.RunProperties(font_size=size, font_family="Aptos"))],
                                properties=props)],
        body_properties=m.BodyProperties(margin_left=0, margin_right=0, margin_top=0, margin_bottom=0),
    )


def test_word_draws_a_run_at_its_size_on_the_device_pixel():
    frame = m.Transform(extent_width=2000000, extent_height=600000)
    powerpoint = render_text_body(_body(10.0), frame, RenderContext())
    word = render_text_body(_body(10.0), frame, RenderContext(rules=drawing_rules.WORD))
    assert 'font-size="13.333"' in powerpoint
    assert 'font-size="13.44"' in word  # 42 device px at 300 dpi: 10.08 pt


def test_word_s_first_baseline_is_the_spaced_box_less_the_descent():
    class Measurer(type(RenderContext().measurer)):
        def line_height_ratio(self, font_family=None, font_family_ea=None):
            return 1.25

        def ascender_ratio(self, font_family=None, font_family_ea=None):
            return 1.0

    frame = m.Transform(extent_width=2000000, extent_height=600000)

    def baseline(rules):
        svg = render_text_body(_body(20.0, 90000), frame, RenderContext(rules=rules, measurer=Measurer()))
        return float(re.search(r'<text x="0" y="([^"]+)"', svg).group(1))

    px = 96 / 72
    # The box is 25 pt and the descent 5 pt: at 90% spacing the box is 22.5 pt.
    assert baseline(drawing_rules.WORD) == pytest.approx((22.5 - 5) * px, abs=0.001)
    assert baseline(drawing_rules.POWERPOINT) == pytest.approx(20 * 0.9 * px, abs=0.001)
