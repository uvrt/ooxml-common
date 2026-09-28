"""Word's measured DrawingML rules, and the reader that moved here from pptx2svg.

Every expected value below was read off Word 16's PDF export of docx2svg's
``tools/make_dml_probe.py`` (docx2svg ROADMAP.md, "DrawingML drawn by the shared
renderers"); :data:`~ooxml_common.drawingml.rules.POWERPOINT` is held to pptx2svg's output
by pptx2svg's own suite.
"""

from __future__ import annotations

import re
from xml.etree.ElementTree import fromstring

import pytest

from ooxml_common.drawingml import color, fill, geometry, read, rules
from ooxml_common.drawingml import model as m
from ooxml_common.drawingml.svg import Defs

A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'


def _t(*pairs):
    return [m.ColorTransform(kind, value) for kind, value in pairs]


# (base, transforms, Word's level) -- a selection of the probe's 54 swatches.
WORD_SWATCHES = [
    ("4472C4", _t(("tint", 40000)), "CFD5EA"),
    ("FFC000", _t(("shade", 20000)), "7C5B00"),
    ("4472C4", _t(("satMod", 25000)), "747F94"),
    ("4472C4", _t(("satMod", 200000)), "0460FF"),
    ("4472C4", _t(("satMod", 300000)), "004EFF"),
    ("ED7D31", _t(("satOff", 20000)), "FF791B"),
    ("ED7D31", _t(("satOff", -20000)), "D78147"),
    ("4472C4", _t(("hueMod", 50000)), "5BC444"),
    ("4472C4", _t(("hueOff", 3600000)), "9644C4"),
    ("4472C4", _t(("lumMod", 60000), ("lumOff", 40000)), "8FAADC"),
    ("4472C4", _t(("lumOff", 40000), ("lumMod", 60000)), "517CC8"),
    ("ED7D31", _t(("tint", 50000), ("satMod", 300000)), "FFAF86"),
    ("ED7D31", _t(("satMod", 300000), ("tint", 50000)), "FFC4BC"),
    ("4472C4", _t(("lumMod", 105000), ("satMod", 103000), ("tint", 73000)), "9AABD9"),
    ("4472C4", _t(("lumMod", 99000), ("satMod", 120000), ("shade", 78000)), "2E61BA"),
    ("4472C4", _t(("gray", 0)), "6E6E6E"),
    ("4472C4", _t(("inv", 0)), "F8EBB3"),
    ("4472C4", _t(("comp", 0)), "C49644"),
    ("000000", _t(("lumMod", 50000), ("lumOff", 50000)), "7F7F7F"),
]


@pytest.mark.parametrize("base, transforms, expected", WORD_SWATCHES)
def test_word_composes_transforms_as_measured(base, transforms, expected):
    assert color.apply_transforms(base, transforms, color.WORD).hex == "#" + expected.lower()


def test_powerpoint_composition_is_untouched():
    # pptx2svg's pairing and per-step rounding, and its saturation clamp.
    assert color.apply_transforms("4472C4", _t(("lumOff", 40000), ("lumMod", 60000))).hex == "#8faadc"
    assert color.apply_transforms("4472C4", _t(("satMod", 200000))).hex == "#0961ff"
    assert color.apply_transforms("4472C4", _t(("hueMod", 50000))).hex == "#4472c4"


def test_scrgb_is_linear_light_for_word():
    node = fromstring(f'<a:solidFill {A}><a:scrgbClr r="50000" g="20000" b="0"/></a:solidFill>')
    parsed = read.parse_color(node)
    assert parsed.hex == "803300"  # the reader's reading, which pptx2svg keeps
    context = color.ColorContext(None, color.build_effective_color_map(), rules=color.WORD)
    assert color.resolve_color(context, parsed).hex == "#bc7c00"


def test_the_reader_reads_every_transform_and_preset_name():
    node = fromstring(f'<a:solidFill {A}><a:srgbClr val="4472C4"><a:gray/><a:hueOff val="60"/>'
                      "</a:srgbClr></a:solidFill>")
    assert [(t.kind, t.value) for t in read.parse_color(node).transforms] == [("gray", 0), ("hueOff", 60)]
    for name, expected in (("darkSeaGreen", "8FBC8F"), ("dkSeaGreen", "8FBC8F"), ("ltGray", "D3D3D3"),
                           ("medAquamarine", "66CDAA"), ("red", "FF0000")):
        assert read.preset_color_hex(name) == expected
    assert read.preset_color_hex("notAColour") is None


def test_the_reader_keeps_a_custom_geometry_in_the_table_form():
    sp_pr = fromstring(
        f'<wps:spPr xmlns:wps="w" {A}><a:custGeom><a:avLst/><a:gdLst><a:gd name="g" fmla="*/ w 1 2"/></a:gdLst>'
        '<a:pathLst><a:path w="100" h="50" fill="none" stroke="0"><a:moveTo><a:pt x="0" y="0"/></a:moveTo>'
        '<a:lnTo><a:pt x="g" y="50"/></a:lnTo></a:path></a:pathLst></a:custGeom></wps:spPr>')
    kind, spec = read.parse_geometry_spec(sp_pr)
    assert kind == "custom"
    (path,) = geometry.spec_path_data(spec, 200, 100)
    assert (path.fill, path.stroke) == ("none", False)
    assert path.d == "M 0 0 L 200 100"  # g is half the box's width, scaled from 100 wide
    assert read.parse_geometry_spec(fromstring(
        f'<s {A}><a:prstGeom prst="roundRect"><a:avLst><a:gd name="adj" fmla="val 30000"/></a:avLst>'
        "</a:prstGeom></s>")) == ("preset", "roundRect", {"adj": "val 30000"})


# -- gradients ---------------------------------------------------------------------------

#: The probe's 2:1 box, in thousands of EMU (Word's shading coordinates are EMU).
BOX = (0.0, 0.0, 1799.59, 899.795)
TWO = [m.GradientStop(0, m.ResolvedColor("#c00000")), m.GradientStop(1, m.ResolvedColor("#0070c0"))]


def _linear(fill_, frame=None):
    defs = Defs()
    fill.office_gradient_ref(fill_, defs, BOX, frame)
    found = re.search(r'x1="([^"]+)" y1="([^"]+)" x2="([^"]+)" y2="([^"]+)"', defs.defs[0])
    return [float(v) for v in found.groups()], defs.defs[0]


@pytest.mark.parametrize("angle, scaled, word", [
    (0, False, (0, 449897.5, 1799590, 449897.5)),
    (90, False, (899795, 0, 899795, 899795)),
    (45, False, (224948.8, -224948.8, 1574641, 1124744)),
    (45, True, (539877, -269938.5, 1259713, 1169734)),
    (30, False, (30137.42, -52199.54, 1769453, 951994.6)),
    (30, True, (291527.1, -252469.8, 1508063, 1152265)),
    (135, False, (1574641, -224948.8, 224948.8, 1124744)),
])
def test_a_linear_gradient_spans_the_box_as_word_draws_it(angle, scaled, word):
    coords, _ = _linear(m.GradientFill(TWO, angle=angle, scaled=scaled))
    assert coords == pytest.approx([v / 1000 for v in word], abs=0.01)


def test_a_gradient_held_to_the_page_turns_back_against_the_shape():
    # rotWithShape="0" on a shape turned 30 degrees: Word's coordinates in the shape's space.
    coords, _ = _linear(m.GradientFill(TWO, angle=0, rotate_with_shape=False), fill.ShapeFrame(rotation=30))
    assert coords == pytest.approx((30.13744, 951.9945, 1769.453, -52.19952), abs=0.01)
    flipped, _ = _linear(m.GradientFill(TWO, angle=0, rotate_with_shape=False), fill.ShapeFrame(flip_h=True))
    assert flipped == pytest.approx((1799.59, 449.8975, 0, 449.8975), abs=0.01)


def test_two_stops_blend_in_linear_light():
    _, markup = _linear(m.GradientFill(TWO, angle=0))
    stops = re.findall(r'offset="([^"]+)%" stop-color="#(\w+)"', markup)
    assert len(stops) == fill.LINEAR_LIGHT_STOPS + 1
    assert stops[0][1] == "c00000" and stops[-1][1] == "0070c0"
    # In the linear profile: 441544 half way (Word: 441544) and 750614 a quarter (730614).
    assert dict(stops)["50"] == "8c528c" and dict(stops)["25"] == "b32f50"
    three = TWO[:1] + [m.GradientStop(0.3, m.ResolvedColor("#ffd966"))] + TWO[1:]
    _, markup = _linear(m.GradientFill(three, angle=0))
    assert len(re.findall("<stop", markup)) == 3


def test_a_circle_path_gradient_runs_from_its_point_to_the_corners():
    defs = Defs()
    fill.office_gradient_ref(m.GradientFill(TWO, gradient_type="radial", path="circle",
                                            focus=(0.5, 0.5, 0.5, 0.5)), defs, BOX)
    values = [float(v) for v in re.search(r'cx="([^"]+)" cy="([^"]+)" r="([^"]+)" fx="([^"]+)" fy="([^"]+)"',
                                           defs.defs[0]).groups()]
    assert values == pytest.approx((899.795, 449.8975, 1006.001, 899.795, 449.8975), abs=0.01)
    defs = Defs()
    fill.office_gradient_ref(m.GradientFill(TWO, gradient_type="radial", path="circle",
                                            focus=(0, 0, 1, 1)), defs, BOX)
    radius = float(re.search(r' r="([^"]+)"', defs.defs[0]).group(1))
    assert radius == pytest.approx(1023.056, abs=0.01)


def test_a_rect_path_gradient_is_four_trapezoids():
    defs = Defs()
    ref = fill.office_gradient_ref(m.GradientFill(TWO, gradient_type="radial", path="rect",
                                                  focus=(0.5, 0.5, 0.5, 0.5)), defs, (10, 20, 100, 50))
    assert ref == "url(#grad-1)"
    assert defs.defs[0].startswith('<pattern id="grad-1" patternUnits="userSpaceOnUse" x="10" y="20"')
    assert defs.defs[0].count("<polygon") == 4


def test_rules_without_a_box_draw_as_pptx2svg():
    defs = Defs()
    gradient = m.GradientFill(TWO, angle=45)
    assert fill.render_fill_attrs(gradient, defs, rules=rules.WORD) == 'fill="url(#grad-1)"'
    reference = Defs()
    fill.render_fill_attrs(gradient, reference)
    assert defs.defs == reference.defs


# -- outlines ----------------------------------------------------------------------------

def _outline(**kwargs):
    return m.Outline(width=38100, fill=m.SolidFill(m.ResolvedColor("#0070c0")), **kwargs)


def _dasharray(attrs):
    found = re.search(r'stroke-dasharray="([^"]+)"', attrs)
    return found.group(1) if found else None


def test_word_dashes_and_caps():
    at = dict(dpi=72, rules=rules.WORD)  # 1 px = 1 pt: Word's PDF units
    assert _dasharray(fill.render_outline_attrs(_outline(dash_style="dash"), Defs(), **at)) == "12 9"
    assert _dasharray(fill.render_outline_attrs(_outline(dash_style="sysDashDot"), Defs(), **at)) == "9 3 3 3"
    rounded = fill.render_outline_attrs(_outline(dash_style="sysDot", line_cap="round"), Defs(), **at)
    assert _dasharray(rounded) == "0 6" and 'stroke-linecap="round"' in rounded
    custom = fill.render_outline_attrs(_outline(custom_dash=[3, 1, 1, 1], line_cap="round"), Defs(), **at)
    assert _dasharray(custom) == "6 6 0 6"
    square = fill.render_outline_attrs(_outline(dash_style="dot", line_cap="square"), Defs(), **at)
    assert _dasharray(square) == "3 9" and "stroke-linecap" not in square
    assert 'stroke-linejoin="round"' in fill.render_outline_attrs(_outline(), Defs(), **at)
    assert "stroke-linejoin" not in fill.render_outline_attrs(_outline(), Defs(), dpi=72)


def test_word_arrowheads_are_sized_by_the_width_with_a_floor():
    tail = m.ArrowEndpoint("triangle", "lg", "lg")
    ends = ((0.0, 0.0, -1.0, 0.0), (63.0, 0.0, 1.0, 0.0))
    elements, start, end = fill.render_arrowheads(_outline(tail_end=tail), ends, dpi=72)
    assert start == 0 and end == pytest.approx(15 - 1.5)  # 5 x 3 pt, cut half a unit short
    assert elements[0].startswith('<path d="M 63 0 L 48 7.5 L 48 -7.5 Z"')
    thin = m.Outline(width=12700, fill=m.SolidFill(m.ResolvedColor("#000000")),
                     tail_end=m.ArrowEndpoint("triangle", "sm", "sm"))
    elements, _, end = fill.render_arrowheads(thin, ends, dpi=72)
    assert elements[0].startswith('<path d="M 63 0 L 59 2 L 59 -2 Z"') and end == pytest.approx(3)


def test_path_ends_and_trimming():
    ends = geometry.path_ends("M 0 0 L 30 40 L 100 40")
    assert ends[0] == pytest.approx((0, 0, -0.6, -0.8)) and ends[1] == pytest.approx((100, 40, 1, 0))
    assert geometry.trim_path("M 0 0 L 30 40 L 100 40", 5, 10) == "M 3 4 L 30 40 L 90 40"
    assert geometry.path_ends("M 0 0 L 10 0 L 10 10 Z") is None


def test_a_word_pattern_is_registered_to_the_page():
    patt = m.PatternFill("pct50", m.ResolvedColor("#c00000"), m.ResolvedColor("#ffffff"))
    defs = Defs()
    fill.render_fill_attrs(patt, defs, rules=rules.WORD, dpi=300,
                           frame=fill.ShapeFrame(page_transform="rotate(-30 5 5)"))
    assert 'width="33.333" height="33.333" patternTransform="rotate(-30 5 5)"' in defs.defs[0]


# (geometry, the text rectangle's insets from the box's left, top, right and bottom, EMU)
# on a 2,000,000 x 700,000 box; Word 16.106 laid a text box's first glyph out this far in
# (docx2svg's tools/make_text_box_probe.py: 11, 5, 96 / 34, 34, 164 / 115 and 55 / 134 px
# at 300 dpi, where these are 11.2, 5.2, 96.1 / 33.6, 33.6, 164.0 / 114.8 and 54.7 / 134.0).
TEXT_RECTS = [
    (("preset", "rect", {}), (0, 0, 0, 0)),
    (("preset", "roundRect", {}), (34171, 34171, 34171, 34171)),
    (("preset", "roundRect", {"adj": "val 7705"}), (15797, 15797, 15797, 15797)),
    (("preset", "ellipse", {}), (292893, 102513, 292893, 102513)),
    (("preset", "octagon", {}), (102512, 102512, 102512, 102512)),
    (("preset", "triangle", {}), (500000, 350000, 500000, 0)),
    (None, (0, 0, 0, 0)),
    (("preset", "no such preset", {}), (0, 0, 0, 0)),
]


@pytest.mark.parametrize("shape, insets", TEXT_RECTS)
def test_a_preset_lays_its_text_out_in_its_text_rectangle(shape, insets):
    left, top, right, bottom = geometry.text_rect(shape, 2000000, 700000)
    got = (left, top, 2000000 - right, 700000 - bottom)
    assert got == pytest.approx(insets, abs=1)


def test_a_custom_geometry_lays_its_text_out_in_its_own_rectangle():
    sp_pr = fromstring(
        f'<wps:spPr xmlns:wps="urn:x" {A}><a:custGeom><a:avLst/><a:gdLst><a:gd name="q" fmla="*/ w 1 4"/>'
        '<a:gd name="v" fmla="*/ h 1 4"/></a:gdLst><a:rect l="q" t="v" r="r" b="b"/><a:pathLst/></a:custGeom>'
        "</wps:spPr>")
    assert read.parse_text_rect(sp_pr) == ("q", "v", "r", "b")
    assert geometry.text_rect(read.parse_geometry_spec(sp_pr), 2000000, 700000, x=10, y=20,
                              rect=read.parse_text_rect(sp_pr)) == (500010, 175020, 2000010, 700020)
    no_rect = fromstring(f'<wps:spPr xmlns:wps="urn:x" {A}><a:prstGeom prst="rect"/></wps:spPr>')
    assert read.parse_text_rect(no_rect) is None


def test_every_preset_has_a_text_rectangle():
    from ooxml_common.drawingml.preset_text_rects import PRESET_TEXT_RECTS
    from ooxml_common.drawingml.presets import PRESETS

    assert set(PRESET_TEXT_RECTS) == set(PRESETS)


def test_word_draws_its_text_area_in_by_half_the_outline_and_powerpoint_does_not():
    """Word lays text out half the outline's width inside the text rectangle (docx2svg's
    F.13); PowerPoint does not move it at all (pptx2svg's ``tools/make_exposed_probe.py``:
    1 to 8 pt outlines, drawn or ``a:noFill``, on a rect, a roundRect and an ellipse, every
    run where the unoutlined shape starts it, to 0.1 pt)."""
    shape = ("preset", "roundRect", {})
    box = geometry.text_rect(shape, 2000000, 700000)
    assert geometry.text_area(shape, 2000000, 700000, outline_width=101600) == box
    assert geometry.text_area(shape, 2000000, 700000, outline_width=101600, rules=rules.POWERPOINT) == box
    left, top, right, bottom = geometry.text_area(shape, 2000000, 700000, outline_width=101600,
                                                  rules=rules.WORD)
    assert (left - box[0], top - box[1], box[2] - right, box[3] - bottom) == (50800,) * 4
    assert rules.POWERPOINT.text_outline_inset == 0.0
    assert rules.WORD.text_outline_inset == 0.5
