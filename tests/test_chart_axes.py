"""Axes in reverse order, minor and category gridlines, and axis titles on every
cartesian chart -- PowerPoint's and Word's alike.

The facts are PowerPoint 16 for Mac's PDF exports of charts ooxml-edit writes
(``set_axis_scale(reverse=True)``, ``set_gridlines``, ``set_axis_title``), measured off the
PDF's own vector lines and text:

* ``c:scaling/c:orientation val="maxMin"`` on a category axis lists the first category at
  the **top** of a bar chart and at the **right** of a column chart; on a value axis it
  puts the minimum at the top (or the right).  The axis crossing it stays where its own
  ``c:crosses`` puts it, ``max`` being the far end of the reversed axis -- the plot's near
  edge -- and a bar grows from where the category axis crosses: the bottom edge of a
  column chart whose reversed value axis is crossed at its maximum.  A clustered bar
  chart's group turns round with its axis (first series on top) and its legend comes back
  into series order.
* A scatter's x and y axes reverse the same way.
* ``c:minorGridlines``: under the major ones, at the minor unit, none at a major value or
  at the crossing; the y axis' before the x axis' on a scatter.
* A category axis' ``c:majorGridlines``: one line at every band edge, both plot edges
  included.
* Axis titles: drawn by PowerPoint where Word draws them (to the half-point raster), on a
  scatter and a bubble chart too, the x axis' at the bottom and the y axis' at the left.
* Clustered horizontal bars: first series at the bottom of its group, legend reversed
  (``C B A``), as in Word.
"""

from __future__ import annotations

import pytest

from ooxml_common.chart import rules as chart_rules
from ooxml_common.chart.layout import EMU_PER_POINT, WORD_TITLE_PAD_PT, font_box
from ooxml_common.drawingml import scene as m
from test_word_chart import A, C, boxes, build, chart, texts

BLUE, ORANGE = "#4472C4", "#ED7D31"
RULES = [chart_rules.POWERPOINT, chart_rules.WORD]


def _scaled(xml: str, axis: str, inner: str) -> str:
    """``inner`` into the ``c:scaling`` of the ``axis`` element (``catAx``/``valAx``)."""
    tag = f"<c:{axis}><c:axId"
    head, _, tail = xml.partition(tag)
    ident, _, rest = tail.partition("/>")
    return f"{head}{tag}{ident}/><c:scaling>{inner}</c:scaling>{rest}"


def _crossing(xml: str, axis: str, where: str) -> str:
    tag = f"<c:{axis}>"
    head, _, tail = xml.partition(tag)
    body, _, rest = tail.partition(f"</c:{axis}>")
    return f"{head}{tag}{body}<c:crosses val='{where}'/></c:{axis}>{rest}"


def bars(children, direction="col"):
    """The bars, by fill, as ``(left, top, right, bottom)`` in drawing order."""
    return [box for box in boxes(children) if box[0] in (BLUE, ORANGE)
            and (box[5] - box[3] > 6 and box[4] - box[2] > 6)]


def lines(children):
    """``(x0, y0, x1, y1, hex)`` of every straight line drawn, pt."""
    out = []
    for child in children:
        if isinstance(child, m.ConnectorElement):
            t = child.transform
            x0, y0 = t.offset_x / EMU_PER_POINT, t.offset_y / EMU_PER_POINT
            x1, y1 = x0 + t.extent_width / EMU_PER_POINT, y0 + t.extent_height / EMU_PER_POINT
            colour = (child.outline.fill.color.hex if child.outline is not None
                      and isinstance(child.outline.fill, m.SolidFill) else None)
            out.append((round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3), colour))
    return out


def _labels_top_down(children, names):
    found = texts(children)
    return [name for name in sorted(names, key=lambda n: found[n][1])]


@pytest.mark.parametrize("rules", RULES)
def test_a_reversed_category_axis_lists_a_bar_chart_top_down(rules):
    plain = chart(direction="bar", legend=None, title=False)
    reversed_ = _crossing(_scaled(plain, "catAx", "<c:orientation val='maxMin'/>"), "valAx", "max")
    assert _labels_top_down(build(plain, rules)[1], "NSEW") == ["W", "E", "S", "N"]
    assert _labels_top_down(build(reversed_, rules)[1], "NSEW") == ["N", "S", "E", "W"]
    # The bar for N (Plan 4 of a longest 5) is now the top group's, and Plan stands above
    # Actual in it: the group turns round with its axis.
    drawn = bars(build(reversed_, rules)[1])
    plan = [box for box in drawn if box[0] == BLUE]
    actual = [box for box in drawn if box[0] == ORANGE]
    top_plan = min(plan, key=lambda box: box[3])
    assert top_plan[4] - top_plan[2] == pytest.approx(0.8 * max(b[4] - b[2] for b in plan))
    assert min(b[3] for b in plan) < min(b[3] for b in actual)
    # The value axis stays at the bottom: its labels are under the plot.
    assert texts(build(reversed_, rules)[1])["0"][1] == pytest.approx(
        texts(build(plain, rules)[1])["0"][1])


def test_a_reversed_category_axis_runs_a_column_chart_right_to_left():
    plain = chart(legend=None, title=False)
    reversed_ = _crossing(_scaled(plain, "catAx", "<c:orientation val='maxMin'/>"), "valAx", "max")
    found = texts(build(reversed_)[1])
    assert sorted("NSEW", key=lambda n: found[n][0]) == ["W", "E", "S", "N"]


def test_a_reversed_value_axis_hangs_nothing_when_the_category_axis_crosses_at_its_maximum():
    """PowerPoint, measured: 0 at the top, the categories under the plot, the columns rising
    from the bottom edge (the axis' maximum) to their values."""
    plain = chart(legend=None, title=False)
    flipped = _crossing(_scaled(plain, "valAx", "<c:orientation val='maxMin'/>"), "catAx", "max")
    _, children = build(flipped)
    found = texts(children)
    assert found["0"][1] < found["5"][1]          # the minimum at the top
    drawn = bars(children)
    bottom = max(box[5] for box in drawn)
    assert all(box[5] == pytest.approx(bottom) for box in drawn)
    assert found["N"][1] > bottom                 # the category labels under the plot


def test_a_reversed_value_axis_puts_an_outside_label_beyond_the_hanging_end():
    plain = chart(legend=None, title=False,
                  series_extra="<c:dLbls><c:dLblPos val='outEnd'/><c:showVal val='1'/></c:dLbls>")
    flipped = _scaled(plain, "valAx", "<c:orientation val='maxMin'/>")
    _, children = build(flipped)
    drawn = bars(children)
    lowest_end = max(box[5] for box in drawn)     # Plan's 5 hangs furthest
    labels = [(child.transform.offset_y / EMU_PER_POINT) for child in children
              if isinstance(child, m.ShapeElement) and child.text_body is not None
              and child.text_body.paragraphs[0].runs[0].text == "5"]
    assert any(top >= lowest_end for top in labels)


def test_a_scatter_reverses_its_x_axis():
    from test_chart_point_labels import _scatter, flags

    wrap = (f"<c:chartSpace xmlns:c='{C}' xmlns:a='{A}'><c:chart><c:autoTitleDeleted val='1'/>"
            f"<c:plotArea>{{}}</c:plotArea></c:chart></c:chartSpace>")
    plain = _scatter("", shown=flags())
    reversed_ = plain.replace('<c:valAx><c:axId val="1"/>', '<c:valAx><c:axId val="1"/><c:scaling>'
                              '<c:orientation val="maxMin"/></c:scaling>', 1)
    def x_labels(xml):
        placed = [(child.text_body.paragraphs[0].runs[0].text, child.transform.offset_x,
                   child.transform.offset_y) for child in build(wrap.format(xml))[1]
                  if isinstance(child, m.ShapeElement) and child.text_body is not None]
        bottom = max(y for _, _, y in placed)
        return {text: x for text, x, y in placed if y == bottom}

    before, after = x_labels(plain), x_labels(reversed_)
    assert before["1"] < before["4"]
    assert after["4"] < after["1"]             # x runs right to left


@pytest.mark.parametrize("rules", RULES)
def test_clustered_bars_stand_upwards_and_legend_from_the_top(rules):
    xml = chart(direction="bar", title=False)
    drawn = bars(build(xml, rules)[1])
    lowest = max(drawn, key=lambda box: box[5])
    assert lowest[0] == BLUE
    names = texts(build(xml, rules)[1])
    assert names["Actual"][1] < names["Plan"][1]
    reversed_ = _scaled(xml, "catAx", "<c:orientation val='maxMin'/>")
    names = texts(build(reversed_, rules)[1])
    assert names["Plan"][1] < names["Actual"][1]


def test_minor_gridlines_go_under_the_major_ones_between_them():
    xml = chart(legend=None, title=False).replace(
        "<c:majorGridlines/>",
        "<c:majorGridlines/><c:minorGridlines><c:spPr><a:ln w='9525'><a:solidFill>"
        "<a:srgbClr val='F2F2F2'/></a:solidFill></a:ln></c:spPr></c:minorGridlines>")
    xml = xml.replace("<c:crossAx val='1'/></c:valAx>",
                      "<c:crossAx val='1'/><c:majorUnit val='1'/><c:minorUnit val='0.5'/></c:valAx>")
    xml = _scaled(xml, "valAx", "<c:orientation val='minMax'/><c:max val='5'/><c:min val='0'/>")
    drawn = [line for line in lines(build(xml)[1]) if abs(line[2] - line[0]) > 50]
    minor = [line for line in drawn if line[4] == "#F2F2F2"]
    major_ys = {line[1] for line in drawn if line[4] != "#F2F2F2" and line[1] == line[3]}
    assert len(minor) == 5                         # 0.5, 1.5, 2.5, 3.5, 4.5
    assert not {line[1] for line in minor} & major_ys
    first_major = next(k for k, line in enumerate(drawn) if line[4] != "#F2F2F2")
    assert all(drawn.index(line) < first_major for line in minor)


def test_a_category_axis_gridline_at_every_band_edge():
    xml = chart(legend=None, title=False).replace(
        "<c:axPos val='b'/><c:crossAx val='2'/>",
        "<c:axPos val='b'/><c:majorGridlines><c:spPr><a:ln><a:solidFill><a:srgbClr val='D9D9D9'/>"
        "</a:solidFill></a:ln></c:spPr></c:majorGridlines><c:crossAx val='2'/>")
    vertical = [line for line in lines(build(xml)[1]) if line[4] == "#D9D9D9"
                and line[0] == line[2]]
    assert len(vertical) == 5                      # four categories, five edges
    xs = sorted(line[0] for line in vertical)
    steps = [b - a for a, b in zip(xs, xs[1:])]
    assert max(steps) - min(steps) < 0.01


@pytest.mark.parametrize("bubble", [False, True])
def test_a_scatter_draws_its_axis_titles_and_gives_them_room(bubble):
    from test_chart_point_labels import _scatter, flags

    def titled(xml):
        title = ("<c:title><c:tx><c:rich><a:bodyPr rot='-5400000' vert='horz'/><a:p><a:r>"
                 "<a:t>{}</a:t></a:r></a:p></c:rich></c:tx><c:overlay val='0'/></c:title>")
        xml = xml.replace('<c:axPos val="b"/>', '<c:axPos val="b"/>'
                          + title.replace(" rot='-5400000' vert='horz'", "").format("Effort"), 1)
        return xml.replace('<c:axPos val="l"/>', '<c:axPos val="l"/>' + title.format("Impact"), 1)

    body = _scatter("", bubble=bubble, shown=flags())
    wrap = (f"<c:chartSpace xmlns:c='{C}' xmlns:a='{A}'><c:chart><c:autoTitleDeleted val='1'/>"
            f"<c:plotArea>{{}}</c:plotArea></c:chart></c:chartSpace>")
    builder, children = build(wrap.format(titled(body)))
    assert {"Effort", "Impact"} <= set(texts(children))
    assert not builder.axis_titles_not_drawn
    if not bubble:
        plain_axis = [line for line in lines(build(wrap.format(body))[1]) if line[0] == line[2]]
        titled_axis = [line for line in lines(children) if line[0] == line[2]]
        pitch = font_box("Arial", 18.0).pitch + WORD_TITLE_PAD_PT
        assert min(l[0] for l in titled_axis) - min(l[0] for l in plain_axis) == pytest.approx(
            pitch, abs=0.5)
