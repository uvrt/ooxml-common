"""Round 10's renderer speed-ups that must not change a pixel: the tight filter region of
an effect (``drawingml.effect.effect_region``), the indexed font mapping
(``text.fontmap.mapped_font``).  pptx2svg's suite and the corpus comparison in the
round's notes hold the output; these hold the rules."""

from __future__ import annotations

import re

from ooxml_common.drawingml import effect, shape
from ooxml_common.drawingml import model as m
from ooxml_common.drawingml import scene
from ooxml_common.drawingml.svg import Defs
from ooxml_common.text import fontmap
from ooxml_common.units import emu_to_px

BLACK = m.ResolvedColor("#000000", 0.35)


def _region(defs: Defs) -> dict:
    head = re.match(r"<filter ([^>]*)>", defs.defs[-1]).group(1)
    return dict(re.findall(r'([\w-]+)="([^"]*)"', head))


def test_without_bounds_the_region_is_twice_the_bounding_box():
    defs = Defs()
    effect.render_effects(m.EffectList(outer_shadow=m.OuterShadow(50800, 38100, 90, BLACK)), defs)
    assert _region(defs) == {"id": "effect-1", "x": "-50%", "y": "-50%", "width": "200%", "height": "200%",
                             "color-interpolation-filters": "sRGB"}


def test_a_shadow_reaches_three_deviations_and_its_offset_on_every_side():
    defs = Defs()
    # blurRad 4 pt (5.333 px, deviation 2.667 px) at 3 pt (4 px) straight down: the blur is
    # drawn before it is moved, and resvg moves it along the page's axes, so the offset
    # counts on every side.
    shadow = m.OuterShadow(50800, 38100, 90, BLACK)
    effect.render_effects(m.EffectList(outer_shadow=shadow), defs, bounds=(0, 0, 100, 50))
    region = _region(defs)
    reach = 3 * emu_to_px(50800) / 2 + 4 + 2
    assert region["filterUnits"] == "userSpaceOnUse"
    assert (float(region["x"]), float(region["y"])) == (round(-reach, 3), round(-reach, 3))
    assert (float(region["width"]), float(region["height"])) == (round(100 + 2 * reach, 3), round(50 + 2 * reach, 3))


def test_a_turned_shape_keeps_the_region_of_its_bounding_box():
    from ooxml_common.drawingml.context import RenderContext

    shadow = m.EffectList(outer_shadow=m.OuterShadow(50800, 38100, 90, BLACK))
    box = m.Transform(0, 0, 952500, 476250)
    for transform, turned in ((box, False), (m.Transform(0, 0, 952500, 476250, rotation=30), False), (box, True)):
        context = RenderContext()
        context.turned = turned
        drawn = shape.render_shape(scene.ShapeElement(transform, m.PresetGeometry("rect"), effects=shadow), context)
        assert drawn
        tight = "userSpaceOnUse" in context.defs[-1]
        assert tight == (not turned and not transform.rotation)


def test_glow_and_inner_shadow_reach_every_side():
    glow = m.EffectList(glow=m.Glow(76200, BLACK))           # 6 pt: deviation 8 px
    x, y, width, height = effect.effect_region(glow, (10, 10, 20, 20))
    assert (x, y, width, height) == (10 - 24 - 2, 10 - 24 - 2, 10 + 48 + 4, 10 + 48 + 4)
    inner = m.EffectList(inner_shadow=m.InnerShadow(25400, 38100, 0, BLACK))
    x, _, width, _ = effect.effect_region(inner, (0, 0, 10, 10))
    reach = 4 * emu_to_px(25400) / 2 + emu_to_px(38100)
    assert (round(x, 9), round(width, 9)) == (round(-reach - 2, 9), round(10 + 2 * reach + 4, 9))
    soft = m.EffectList(soft_edge=m.SoftEdge(50800))
    reach = 3 * emu_to_px(50800) + 2
    assert effect.effect_region(soft, (0, 0, 10, 10)) == (-reach, -reach, 10 + 2 * reach, 10 + 2 * reach)


def test_shapes_give_bounds_only_where_all_they_draw_is_in_the_box():
    outline = m.Outline(width=12700, fill=m.SolidFill(m.ResolvedColor("#000000")))
    assert shape._drawn_bounds(m.PresetGeometry("rect"), 100, 50, outline) == (
        -2 * emu_to_px(12700), -2 * emu_to_px(12700), 100 + 2 * emu_to_px(12700), 50 + 2 * emu_to_px(12700))
    assert shape._drawn_bounds(m.PresetGeometry("ellipse"), 100, 50, None) == (0, 0, 100, 50)
    assert shape._drawn_bounds(m.PresetGeometry("wedgeRectCallout"), 100, 50, None) is None
    assert shape._drawn_bounds(m.CustomGeometry([]), 100, 50, None) is None
    body = scene.TextBody([scene.Paragraph([scene.TextRun("")])])
    assert not shape._has_text(body)
    assert shape._has_text(scene.TextBody([scene.Paragraph([scene.TextRun("Hi")])]))


def test_a_stretched_picture_pushed_out_of_its_frame_is_in_its_bounds():
    image = scene.ImageElement(m.Transform(0, 0, 952500, 952500), "", "image/png",
                           stretch=m.StretchFillRect(left=-0.5, top=0, right=0, bottom=-0.25))
    assert shape._image_bounds(image, 100, 100) == (-50, 0, 100, 125)


def test_mapped_font_finds_what_the_scan_found():
    mapping = {"Calibri": "Carlito", "calibri": "Other", "ＭＳ ゴシック": "Noto Sans JP"}
    assert fontmap.mapped_font("CALIBRI ", mapping) == "Carlito"     # the first key wins
    assert fontmap.mapped_font("calibri", mapping) == "Other"        # an exact key first
    mapping["Cambria"] = "Caladea"                                   # changed in place
    assert fontmap.mapped_font("cambria", mapping) == "Caladea"
    assert fontmap.mapped_font("Nothing Like It", {"x": ["unhashable"]}) is None
    assert fontmap.mapped_font("X", {"x": ["unhashable"]}) == ["unhashable"]


# -- the scans a rasterisation runs over a whole SVG ------------------------------------


def test_a_large_svg_picture_not_drawn_here_is_not_decoded_whole(monkeypatch):
    import base64

    from ooxml_common import metafile

    big = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1">' + b"<!-- " + b"x" * 100_000 + b" --></svg>"
    href = "data:image/svg+xml;base64," + base64.b64encode(big).decode()
    page = f'<svg xmlns="http://www.w3.org/2000/svg"><image width="1" height="1" href="{href}"/></svg>'
    decoded = []
    real = base64.b64decode
    monkeypatch.setattr(metafile.base64, "b64decode", lambda data, **k: decoded.append(len(data)) or real(data, **k))
    metafile._INLINE.clear()
    assert metafile.inline_metafile_images(page) == page
    assert decoded == [metafile._HEAD]          # the head only
    assert metafile.inline_metafile_images(page) == page
    assert decoded == [metafile._HEAD]          # and once


def test_one_parse_serves_the_rasterisers_checks(monkeypatch):
    from ooxml_common.fonts import rasterdb

    parses = []
    real = rasterdb.ET.fromstring
    monkeypatch.setattr(rasterdb.ET, "fromstring", lambda text: parses.append(1) or real(text))
    rasterdb.parsed_svg.cache_clear()
    svg = ('<svg xmlns="http://www.w3.org/2000/svg"><text font-family="Nothing Here">Hi</text>'
           f'<!-- {len(parses)} --></svg>')
    assert rasterdb.parsed_svg(svg) is rasterdb.parsed_svg(svg)
    rasterdb.needed_font_files(svg, font_files=[])
    assert len(parses) == 1
