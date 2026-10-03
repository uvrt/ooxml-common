"""DrawingML's value types and renderers, held to what each consumer relies on.

pptx2svg's own suite holds these renderers to its output byte for byte (every VRT
snapshot and fidelity baseline), so the tests here are about the *shared* surface: the
package works with no consumer behind it, the complete preset table is complete, path data
agrees with the renderer it shares an evaluator with, and where Word and PowerPoint differ
the difference is a parameter rather than a choice made for both.
"""

from __future__ import annotations

import re

import pytest

from ooxml_common.drawingml import color, effect, fill, geometry
from ooxml_common.drawingml import model as m
from ooxml_common.drawingml.preset_specs import PRESET_SPECS
from ooxml_common.drawingml.presets import OTHER_PRESET_SPECS, PRESETS
from ooxml_common.drawingml.svg import Defs, SvgDefs, num

# -- the SVG document seam -------------------------------------------------------------


def test_defs_is_the_minimal_document_the_renderers_need():
    defs = Defs()
    assert isinstance(defs, SvgDefs)
    attrs = fill.render_fill_attrs(
        m.GradientFill([m.GradientStop(0, m.ResolvedColor("#ff0000")),
                        m.GradientStop(1, m.ResolvedColor("#0000ff", 0.5))]),
        defs,
    )
    assert attrs == 'fill="url(#grad-1)"'
    assert defs.defs[0].startswith('<linearGradient id="grad-1"')
    assert 'stop-opacity="0.5"' in defs.defs[0]


def test_num_is_compact():
    assert num(12.0) == "12"
    assert num(12.3456) == "12.346"
    assert num(-0.0001) == "0"


# -- fills, outlines, effects without a consumer --------------------------------------


def test_solid_fill_and_dashed_outline():
    defs = Defs()
    assert fill.render_fill_attrs(m.SolidFill(m.ResolvedColor("#123456", 0.25)), defs) == (
        'fill="#123456" fill-opacity="0.25"'
    )
    outline = m.Outline(width=12700, fill=m.SolidFill(m.ResolvedColor("#000000")),
                        dash_style="sysDot", line_cap="round")
    attrs = fill.render_outline_attrs(outline, defs)
    # 1 pt is 4/3 px; sysDot is 1-on 1-off in stroke widths.
    assert 'stroke-width="1.333"' in attrs
    assert 'stroke-dasharray="1.333 1.333"' in attrs
    assert 'stroke-linecap="round"' in attrs


def test_pattern_fill_draws_the_measured_cell():
    defs = Defs()
    attrs = fill.render_fill_attrs(
        m.PatternFill("cross", m.ResolvedColor("#000000"), m.ResolvedColor("#ffffff")), defs
    )
    assert attrs == 'fill="url(#patt-1)"'
    # 8 pt is 10.667 px.
    assert 'width="10.667" height="10.667"' in defs.defs[0]


def test_markers_and_effects_register_their_definitions():
    defs = Defs()
    outline = m.Outline(fill=m.SolidFill(m.ResolvedColor("#ff0000")),
                        tail_end=m.ArrowEndpoint("triangle"))
    assert fill.render_markers(outline, defs) == 'marker-end="url(#marker-1)"'
    attrs = effect.render_effects(
        m.EffectList(outer_shadow=m.OuterShadow(50800, 38100, 45, m.ResolvedColor("#000000", 0.4))),
        defs,
    )
    assert attrs.startswith('filter="url(#')
    assert len(defs.defs) == 2


# -- colour: one resolver, each application's measured rule ----------------------------


def _theme(**slots):
    return type("Theme", (), {"color_scheme": {k: m.SrgbColor(v) for k, v in slots.items()}})()


BLACK_HALF = [m.ColorTransform("lumMod", 50000), m.ColorTransform("lumOff", 50000)]


def test_powerpoint_is_the_default_and_keeps_its_levels_in_scrgb():
    """PowerPoint draws black at lumMod 50000 lumOff 50000 as 7F7F7F too, but because the
    127.5 it computes is kept as 21404/100000 of linear light -- 127.4997 levels -- not by
    rounding a half down (pptx2svg's tools/make_color_probe.py)."""
    assert color.apply_transforms("000000", BLACK_HALF).hex == "#7f7f7f"
    context = color.ColorContext(_theme(dk1="000000"), color.build_effective_color_map())
    assert context.rules is color.POWERPOINT
    assert color.resolve_color(context, m.SchemeColor("tx1", BLACK_HALF)).hex == "#7f7f7f"


def test_word_rounds_a_half_down():
    """docx2svg's measurement (its ROADMAP.md, F.3): Word draws black at lumMod 50000
    lumOff 50000 -- 127.5 levels -- as 7F7F7F."""
    assert color.apply_transforms("000000", BLACK_HALF, color.WORD).hex == "#7f7f7f"
    context = color.ColorContext(
        _theme(dk1="000000"), color.build_effective_color_map(), rules=color.WORD
    )
    assert color.resolve_color(context, m.SchemeColor("tx1", BLACK_HALF)).hex == "#7f7f7f"


def test_the_rules_agree_away_from_a_half_level():
    transforms = [m.ColorTransform("lumMod", 75000)]
    assert (color.apply_transforms("4472C4", transforms).hex
            == color.apply_transforms("4472c4", transforms, color.WORD).hex)


def test_rounding_helpers():
    assert [color.round_half_even(v) for v in (126.5, 127.5, 127.49, 127.51)] == [126, 128, 127, 128]
    assert [color.round_half_down(v) for v in (126.5, 127.5, 127.49, 127.51)] == [126, 127, 127, 128]
    # A half computed through floating point is still a half.
    assert color.round_half_down(127.50000000001) == 127


def test_scheme_resolution_through_the_colour_map_and_fallback():
    context = color.ColorContext(_theme(accent1="4472C4"), color.build_effective_color_map())
    assert color.resolve_color(context, m.SchemeColor("accent1")).hex == "#4472c4"
    # A slot the theme does not state falls back to the Office theme.
    assert color.resolve_color(context, m.SchemeColor("accent2")).hex == "#ed7d31"
    tint = color.resolve_color(context, m.SchemeColor("accent1", [m.ColorTransform("tint", 40000),
                                                                  m.ColorTransform("alpha", 30000)]))
    assert tint.alpha == 0.3


# -- style references ------------------------------------------------------------------

_A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'


def test_a_font_reference_keeps_the_collection_it_names():
    from xml.etree.ElementTree import fromstring

    from ooxml_common.drawingml import read

    style = read.parse_shape_style(fromstring(
        f'<p:style {_A} xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        '<a:lnRef idx="2"><a:schemeClr val="accent1"><a:shade val="15000"/></a:schemeClr>'
        '</a:lnRef><a:fillRef idx="1"><a:schemeClr val="accent1"/></a:fillRef>'
        '<a:effectRef idx="0"><a:schemeClr val="accent1"/></a:effectRef>'
        '<a:fontRef idx="major"><a:schemeClr val="lt1"/></a:fontRef></p:style>'
    ))
    assert style.font_ref.collection == "major"
    assert style.font_ref.idx == 0
    assert style.font_ref.color.scheme == "lt1"
    # A numbered reference names no collection.
    assert (style.fill_ref.idx, style.fill_ref.collection) == (1, None)
    assert (style.line_ref.idx, style.line_ref.collection) == (2, None)
    for value, expected in (("minor", "minor"), ("none", "none"), ("bogus", None)):
        ref = read.parse_style_reference(fromstring(f'<a:fontRef {_A} idx="{value}"/>'))
        assert ref.collection == expected


# -- the complete preset table ---------------------------------------------------------

#: ST_ShapeType in ECMA-376 Part 1, 5th edition, dml-main.xsd: 187 names.
ST_SHAPE_TYPE_COUNT = 187


def test_the_table_is_complete_and_the_two_halves_share_no_name():
    assert not set(PRESET_SPECS) & set(OTHER_PRESET_SPECS)
    assert len(PRESETS) == ST_SHAPE_TYPE_COUNT
    for name in ("rect", "roundRect", "ellipse", "line", "rtTriangle", "straightConnector1",
                 "flowChartProcess", "wedgeEllipseCallout", "upArrow"):
        assert name in PRESETS


def _points(d: str) -> list[tuple[float, float]]:
    """The end point of every command, which is what two spellings of a shape share."""
    out = []
    for command in re.findall(r"[MLQCAZ][^MLQCAZ]*", d):
        numbers = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?(?:e-?\d+)?", command[1:])]
        if len(numbers) >= 2:
            out.append((numbers[-2], numbers[-1]))
    return out


def test_up_arrow_is_down_arrow_upside_down():
    """``upArrow`` is not in the specification's definitions file; the table writes it as
    ``downArrow`` mirrored, and this holds it to that at a non-default adjustment."""
    adjust = {"adj1": 30000, "adj2": 70000}
    up = geometry.preset_path_data("upArrow", 120, 90, adjust)[0].d
    down = geometry.preset_path_data("downArrow", 120, 90, adjust)[0].d
    assert sorted((x, round(90 - y, 3)) for x, y in _points(up)) == sorted(
        (x, y) for x, y in _points(down)
    )


#: The five presets docx2svg had to write itself (``docx2svg.drawing.EXTRA_PRESETS``),
#: copied here as it wrote them from ECMA-376, to hold the generated table to the same
#: shapes: the table must be able to replace them.
DOCX2SVG_EXTRA_PRESETS = {
    "rect": ((), (), (("norm", True, None, (("M", "l", "t"), ("L", "r", "t"), ("L", "r", "b"),
                                              ("L", "l", "b"), ("Z",))),)),
    "roundRect": (
        (("adj", 16667),),
        (("a", "pin 0 adj 50000"), ("dx1", "*/ ss a 100000"), ("x2", "+- r 0 dx1"), ("y2", "+- b 0 dx1")),
        (("norm", True, None, (
            ("M", "l", "dx1"), ("A", "dx1", "dx1", "cd2", "cd4"), ("L", "x2", "t"),
            ("A", "dx1", "dx1", "3cd4", "cd4"), ("L", "r", "y2"), ("A", "dx1", "dx1", "0", "cd4"),
            ("L", "dx1", "b"), ("A", "dx1", "dx1", "cd4", "cd4"), ("Z",))),),
    ),
    "ellipse": ((), (), (("norm", True, None, (
        ("M", "l", "vc"), ("A", "wd2", "hd2", "cd2", "cd4"), ("A", "wd2", "hd2", "3cd4", "cd4"),
        ("A", "wd2", "hd2", "0", "cd4"), ("A", "wd2", "hd2", "cd4", "cd4"), ("Z",))),)),
    "line": ((), (), (("none", True, None, (("M", "l", "t"), ("L", "r", "b"))),)),
    "rtTriangle": ((), (), (("norm", True, None, (("M", "l", "b"), ("L", "l", "t"), ("L", "r", "b"),
                                                    ("Z",))),)),
}


@pytest.mark.parametrize("name", sorted(DOCX2SVG_EXTRA_PRESETS))
@pytest.mark.parametrize("adjust", [{}, {"adj": 40000}])
def test_the_table_draws_what_docx2svg_wrote_by_hand(name, adjust):
    ours = geometry.preset_path_data(name, 173.4, 61.2, adjust, x=12.5, y=7)
    theirs = geometry.spec_path_data(DOCX2SVG_EXTRA_PRESETS[name], 173.4, 61.2, adjust, x=12.5, y=7)
    if name == "line":
        # The one difference, and it is docx2svg's: the specification's ``line`` path has
        # no ``@fill`` and so fills ``norm`` -- an open two-point path, whose fill has no
        # area -- where docx2svg wrote ``none``.
        assert [p.fill for p in ours] == ["norm"] and [p.fill for p in theirs] == ["none"]
    else:
        assert [p.fill for p in ours] == [p.fill for p in theirs]
    assert [p.stroke for p in ours] == [p.stroke for p in theirs]
    for a, b in zip(ours, theirs):
        assert _points(a.d) == pytest.approx(_points(b.d), abs=1e-3)


# -- path data -------------------------------------------------------------------------


def test_path_data_is_placed_in_the_box():
    (path,) = geometry.preset_path_data("rect", 100, 50, x=10, y=5)
    assert path == geometry.GeometryPath("M 10 5 L 110 5 L 110 55 L 10 55 Z", "norm", True)


def test_path_data_keeps_each_paths_fill_mode_and_stroke():
    paths = geometry.preset_path_data("can", 80, 120)
    assert [(p.fill, p.stroke) for p in paths] == [("norm", False), ("lighten", False), ("none", True)]
    (connector,) = geometry.preset_path_data("straightConnector1", 10, 10)
    assert (connector.fill, connector.stroke) == ("none", True)


@pytest.mark.parametrize("name", ["star5", "can", "cloud", "circularArrow", "chartX"])
def test_path_data_agrees_with_the_element_renderer(name):
    """Same evaluator, same path builder: a preset pptx2svg draws from the specification
    comes out as the same path data both ways."""
    element = geometry.preset_geometry_svg(name, 140, 90, {})
    drawn = re.findall(r'<path d="([^"]*)"', element)
    ours = [p.d for p in geometry.preset_path_data(name, 140, 90)]
    # The element renderer draws a shaded path twice (the shape's colour, then the overlay).
    assert list(dict.fromkeys(drawn)) == list(dict.fromkeys(ours))


def test_adjustments_as_numbers_or_as_formulas():
    by_number = geometry.preset_path_data("roundRect", 100, 60, {"adj": 30000})
    by_formula = geometry.preset_path_data("roundRect", 100, 60, {"adj": "val 30000"})
    assert by_number == by_formula


def test_an_alias_and_an_unknown_name():
    assert geometry.preset_path_data("bendUpArrow", 50, 50) == geometry.preset_path_data("bentUpArrow", 50, 50)
    assert geometry.preset_path_data("noSuchShape", 50, 50) is None


def test_a_model_geometry():
    preset = geometry.geometry_path_data(m.PresetGeometry("rect"), 20, 10)
    assert preset[0].d == "M 0 0 L 20 0 L 20 10 L 0 10 Z"
    custom = geometry.geometry_path_data(
        m.CustomGeometry([m.CustomGeometryPath(200, 100, "M 0 0 L 200 100 A 50 25 0 0 1 100 50 "
                                                         "C 10 20, 30 40, 50 60 Q 1 2, 3 4 Z")]),
        100, 50, x=1, y=2,
    )
    assert custom == [geometry.GeometryPath(
        "M 1 2 L 101 52 A 25 12.5 0 0 1 51 27 C 6 12 16 22 26 32 Q 1.5 3 2.5 4 Z"
    )]
