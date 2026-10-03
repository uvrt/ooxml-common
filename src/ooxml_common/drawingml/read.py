"""DrawingML readers: colours, fills, outlines, effects, transforms and geometry.

Moved from ``pptx2svg.parse.drawing`` (which re-exports this module) so that a Word
document's shapes are read into the same :mod:`~ooxml_common.drawingml.source` types as a
slide's.  Nothing here knows which application wrote the XML: a ``wps:spPr`` and a
``p:spPr`` hold the same ``a:`` children, and a theme's ``a:fmtScheme`` is the same part.

Everything here stays unresolved -- ``a:schemeClr val="tx1"`` becomes a
:class:`SchemeColor`, not a hex string, because the colour map that gives ``tx1`` a
meaning lives with the document (a slide master's ``p:clrMap``, Word's
``w:clrSchemeMapping``), not on the shape.  Likewise ``lumMod``/``tint`` are recorded but
not applied: :mod:`~ooxml_common.drawingml.color` applies them, under the application's
rules.
"""

from __future__ import annotations

from xml.etree.ElementTree import Element

from ..xmlutil import (
    attr,
    child,
    children,
    has_child,
    is_true,
    local_name,
    ns_attr,
    num_attr,
)
from .guides import arc_segments, evaluate_guides, resolve_value
from .model import ArrowEndpoint, CustomGeometryPath
from .source import (
    ColorTransform,
    SchemeColor,
    SourceColor,
    SourceCustomGeometry,
    SourceEffectList,
    SourceFill,
    SourceFormatScheme,
    SourceGeometry,
    SourceGlow,
    SourceGradientFill,
    SourceGradientStop,
    SourceGroupFill,
    SourceImageFill,
    SourceImageFillTile,
    SourceInnerShadow,
    SourceNoFill,
    SourceOuterShadow,
    SourceOutline,
    SourcePatternFill,
    SourcePresetGeometry,
    SourceShapeStyle,
    SourceSoftEdge,
    SourceSolidFill,
    SourceStyleReference,
    SourceBlipEffects,
    SourceTransform,
    SrgbColor,
    SystemColor,
)

COLOR_ELEMENTS = ("srgbClr", "schemeClr", "sysClr", "prstClr", "scrgbClr", "hslClr")
COLOR_TRANSFORM_KINDS = {
    "lumMod", "lumOff", "tint", "shade", "alpha", "satMod", "satOff", "hueMod", "hueOff", "gray", "inv",
    "comp", "gamma", "invGamma", "alphaMod", "alphaOff",
}
#: The transforms that take no value (ECMA-376 20.1.2.3): read as 0.
VALUELESS_TRANSFORMS = {"gray", "inv", "comp", "gamma", "invGamma"}

DASH_STYLES = {
    "solid",
    "dash",
    "dot",
    "dashDot",
    "lgDash",
    "lgDashDot",
    "lgDashDotDot",
    "sysDash",
    "sysDot",
    "sysDashDot",
    "sysDashDotDot",
}
ARROW_TYPES = {"triangle", "stealth", "diamond", "oval", "arrow"}
ARROW_SIZES = {"sm", "med", "lg"}
RECTANGLE_ALIGNMENTS = {"tl", "t", "tr", "l", "ctr", "r", "bl", "b", "br"}
LINE_CAP_MAP = {"flat": "butt", "sq": "square", "rnd": "round"}

#: ``a:ln@cmpd`` -- how many parallel strokes the one outline is drawn as.  ``sng`` is
#: the default and the only one that is a single stroke; the rest lay two or three
#: strokes across the stated width ``w``, which SVG's one centred stroke per path cannot
#: express.  Kept because the *renderer* has to know it is simplifying: a ``dbl`` border
#: drawn as one stroke is the right colour, the right width and the wrong picture, and
#: silence about that is the defect this field exists to stop.
COMPOUND_LINE_TYPES = {"sng", "dbl", "thickThin", "thinThick", "tri"}

#: ``a:prstClr`` (``ST_PresetColorVal``, ECMA-376 20.1.10.48): the CSS named colours, keyed
#: in lower case.  The schema spells them in camel case and abbreviates ``dark``,
#: ``light`` and ``medium`` as ``dk``, ``lt`` and ``med`` in a second spelling of each
#: (``dkSeaGreen``); :func:`preset_color_hex` reads either.  Word draws ``darkSeaGreen``
#: as ``8FBC8F``, the CSS value (docx2svg ``tools/make_dml_probe.py``).
CSS_COLOR_HEX = {
    "aliceblue": "F0F8FF",
    "antiquewhite": "FAEBD7",
    "aqua": "00FFFF",
    "aquamarine": "7FFFD4",
    "azure": "F0FFFF",
    "beige": "F5F5DC",
    "bisque": "FFE4C4",
    "black": "000000",
    "blanchedalmond": "FFEBCD",
    "blue": "0000FF",
    "blueviolet": "8A2BE2",
    "brown": "A52A2A",
    "burlywood": "DEB887",
    "cadetblue": "5F9EA0",
    "chartreuse": "7FFF00",
    "chocolate": "D2691E",
    "coral": "FF7F50",
    "cornflowerblue": "6495ED",
    "cornsilk": "FFF8DC",
    "crimson": "DC143C",
    "cyan": "00FFFF",
    "darkblue": "00008B",
    "darkcyan": "008B8B",
    "darkgoldenrod": "B8860B",
    "darkgray": "A9A9A9",
    "darkgreen": "006400",
    "darkgrey": "A9A9A9",
    "darkkhaki": "BDB76B",
    "darkmagenta": "8B008B",
    "darkolivegreen": "556B2F",
    "darkorange": "FF8C00",
    "darkorchid": "9932CC",
    "darkred": "8B0000",
    "darksalmon": "E9967A",
    "darkseagreen": "8FBC8F",
    "darkslateblue": "483D8B",
    "darkslategray": "2F4F4F",
    "darkslategrey": "2F4F4F",
    "darkturquoise": "00CED1",
    "darkviolet": "9400D3",
    "deeppink": "FF1493",
    "deepskyblue": "00BFFF",
    "dimgray": "696969",
    "dimgrey": "696969",
    "dodgerblue": "1E90FF",
    "firebrick": "B22222",
    "floralwhite": "FFFAF0",
    "forestgreen": "228B22",
    "fuchsia": "FF00FF",
    "gainsboro": "DCDCDC",
    "ghostwhite": "F8F8FF",
    "gold": "FFD700",
    "goldenrod": "DAA520",
    "gray": "808080",
    "green": "008000",
    "greenyellow": "ADFF2F",
    "grey": "808080",
    "honeydew": "F0FFF0",
    "hotpink": "FF69B4",
    "indianred": "CD5C5C",
    "indigo": "4B0082",
    "ivory": "FFFFF0",
    "khaki": "F0E68C",
    "lavender": "E6E6FA",
    "lavenderblush": "FFF0F5",
    "lawngreen": "7CFC00",
    "lemonchiffon": "FFFACD",
    "lightblue": "ADD8E6",
    "lightcoral": "F08080",
    "lightcyan": "E0FFFF",
    "lightgoldenrodyellow": "FAFAD2",
    "lightgray": "D3D3D3",
    "lightgreen": "90EE90",
    "lightgrey": "D3D3D3",
    "lightpink": "FFB6C1",
    "lightsalmon": "FFA07A",
    "lightseagreen": "20B2AA",
    "lightskyblue": "87CEFA",
    "lightslategray": "778899",
    "lightslategrey": "778899",
    "lightsteelblue": "B0C4DE",
    "lightyellow": "FFFFE0",
    "lime": "00FF00",
    "limegreen": "32CD32",
    "linen": "FAF0E6",
    "magenta": "FF00FF",
    "maroon": "800000",
    "mediumaquamarine": "66CDAA",
    "mediumblue": "0000CD",
    "mediumorchid": "BA55D3",
    "mediumpurple": "9370DB",
    "mediumseagreen": "3CB371",
    "mediumslateblue": "7B68EE",
    "mediumspringgreen": "00FA9A",
    "mediumturquoise": "48D1CC",
    "mediumvioletred": "C71585",
    "midnightblue": "191970",
    "mintcream": "F5FFFA",
    "mistyrose": "FFE4E1",
    "moccasin": "FFE4B5",
    "navajowhite": "FFDEAD",
    "navy": "000080",
    "oldlace": "FDF5E6",
    "olive": "808000",
    "olivedrab": "6B8E23",
    "orange": "FFA500",
    "orangered": "FF4500",
    "orchid": "DA70D6",
    "palegoldenrod": "EEE8AA",
    "palegreen": "98FB98",
    "paleturquoise": "AFEEEE",
    "palevioletred": "DB7093",
    "papayawhip": "FFEFD5",
    "peachpuff": "FFDAB9",
    "peru": "CD853F",
    "pink": "FFC0CB",
    "plum": "DDA0DD",
    "powderblue": "B0E0E6",
    "purple": "800080",
    "red": "FF0000",
    "rosybrown": "BC8F8F",
    "royalblue": "4169E1",
    "saddlebrown": "8B4513",
    "salmon": "FA8072",
    "sandybrown": "F4A460",
    "seagreen": "2E8B57",
    "seashell": "FFF5EE",
    "sienna": "A0522D",
    "silver": "C0C0C0",
    "skyblue": "87CEEB",
    "slateblue": "6A5ACD",
    "slategray": "708090",
    "slategrey": "708090",
    "snow": "FFFAFA",
    "springgreen": "00FF7F",
    "steelblue": "4682B4",
    "tan": "D2B48C",
    "teal": "008080",
    "thistle": "D8BFD8",
    "tomato": "FF6347",
    "turquoise": "40E0D0",
    "violet": "EE82EE",
    "wheat": "F5DEB3",
    "white": "FFFFFF",
    "whitesmoke": "F5F5F5",
    "yellow": "FFFF00",
    "yellowgreen": "9ACD32",
}

#: The names this reader mapped before it carried the whole table, kept as the reader's
#: public name for them; every value is the CSS one.
PRESET_COLOR_HEX = {
    name: CSS_COLOR_HEX[name.lower()]
    for name in (
        "black", "white", "red", "green", "lime", "blue", "yellow", "cyan", "aqua", "magenta",
        "fuchsia", "gray", "grey", "darkGray", "lightGray", "silver", "maroon", "olive", "navy",
        "purple", "teal", "orange", "pink", "brown", "gold", "violet", "indigo",
    )
}

_PRESET_PREFIXES = (("dk", "dark"), ("lt", "light"), ("med", "medium"))


def preset_color_hex(name: str) -> str | None:
    """``RRGGBB`` for an ``a:prstClr@val``, in either of the schema's spellings."""
    key = name.lower()
    if key in CSS_COLOR_HEX:
        return CSS_COLOR_HEX[key]
    for short, long in _PRESET_PREFIXES:
        if name.startswith(short) and name[len(short):len(short) + 1].isupper():
            return CSS_COLOR_HEX.get(long + key[len(short):])
    return None


# --------------------------------------------------------------------------------------
# Colour
# --------------------------------------------------------------------------------------


def parse_color(parent: Element | None) -> SourceColor | None:
    """Read the colour child of a colour-holding element (``a:solidFill``, ``a:buClr``...)."""
    if parent is None:
        return None
    for node in parent:
        color = parse_color_node(node)
        if color is not None:
            return color
    return None


def parse_color_node(node: Element) -> SourceColor | None:
    """Read one ``a:srgbClr`` / ``a:schemeClr`` / ``a:sysClr`` / ``a:prstClr`` element."""
    name = local_name(node.tag)
    if name == "srgbClr":
        value = attr(node, "val")
        if value is None:
            return None
        return SrgbColor(hex=value.upper(), transforms=parse_color_transforms(node))
    if name == "schemeClr":
        value = attr(node, "val")
        if value is None:
            return None
        return SchemeColor(scheme=value, transforms=parse_color_transforms(node))
    if name == "sysClr":
        value = attr(node, "val")
        if value is None:
            return None
        last = attr(node, "lastClr")
        return SystemColor(
            value=value,
            last_color=last.upper() if last else None,
            transforms=parse_color_transforms(node),
        )
    if name == "prstClr":
        hex_value = preset_color_hex(attr(node, "val") or "")
        if hex_value is None:
            return None
        return SrgbColor(hex=hex_value, transforms=parse_color_transforms(node))
    if name == "scrgbClr":
        # Linear RGB percentages; approximate by treating them as sRGB percentages.
        components = [
            max(0.0, min(1.0, (num_attr(node, key) or 0) / 100000)) for key in ("r", "g", "b")
        ]
        hex_value = "".join(f"{round(component * 255):02X}" for component in components)
        return SrgbColor(hex=hex_value, transforms=parse_color_transforms(node),
                         linear=(components[0], components[1], components[2]))
    if name == "hslClr":
        hue = (num_attr(node, "hue") or 0) / 60000 / 360
        sat = (num_attr(node, "sat") or 0) / 100000
        lum = (num_attr(node, "lum") or 0) / 100000
        return SrgbColor(hex=_hsl_to_hex(hue, sat, lum), transforms=parse_color_transforms(node))
    return None


def parse_color_transforms(node: Element) -> list[ColorTransform]:
    transforms: list[ColorTransform] = []
    for item in node:
        kind = local_name(item.tag)
        if kind not in COLOR_TRANSFORM_KINDS:
            continue
        value = num_attr(item, "val")
        if value is None and kind in VALUELESS_TRANSFORMS:
            value = 0
        if value is None:
            continue
        transforms.append(ColorTransform(kind=kind, value=value))  # type: ignore[arg-type]
    return transforms


def _hsl_to_hex(hue: float, sat: float, lum: float) -> str:
    if sat == 0:
        level = round(lum * 255)
        return f"{level:02X}{level:02X}{level:02X}"

    def hue_to_rgb(p: float, q: float, t: float) -> float:
        t = t % 1.0
        if t < 1 / 6:
            return p + (q - p) * 6 * t
        if t < 1 / 2:
            return q
        if t < 2 / 3:
            return p + (q - p) * (2 / 3 - t) * 6
        return p

    q = lum * (1 + sat) if lum < 0.5 else lum + sat - lum * sat
    p = 2 * lum - q
    values = (hue_to_rgb(p, q, hue + 1 / 3), hue_to_rgb(p, q, hue), hue_to_rgb(p, q, hue - 1 / 3))
    return "".join(f"{max(0, min(255, round(v * 255))):02X}" for v in values)


# --------------------------------------------------------------------------------------
# Fill
# --------------------------------------------------------------------------------------


def parse_fill(parent: Element | None) -> SourceFill | None:
    """Read the fill child of ``a:spPr`` / ``a:ln`` / ``p:bgPr`` / ``a:tcPr``."""
    if parent is None:
        return None

    solid = child(parent, "solidFill")
    if solid is not None:
        color = parse_color(solid)
        return SourceSolidFill(color=color) if color is not None else None

    if has_child(parent, "noFill"):
        return SourceNoFill()

    gradient = child(parent, "gradFill")
    if gradient is not None:
        parsed = parse_gradient_fill(gradient)
        if parsed is not None:
            return parsed

    blip_fill = child(parent, "blipFill")
    if blip_fill is not None:
        parsed = parse_blip_fill(blip_fill)
        if parsed is not None:
            return parsed

    pattern = child(parent, "pattFill")
    if pattern is not None:
        parsed = parse_pattern_fill(pattern)
        if parsed is not None:
            return parsed

    if has_child(parent, "grpFill"):
        return SourceGroupFill()

    return None


def parse_gradient_fill(gradient: Element) -> SourceFill | None:
    stops: list[SourceGradientStop] = []
    for stop in children(child(gradient, "gsLst"), "gs"):
        color = parse_color(stop)
        if color is None:
            continue
        stops.append(SourceGradientStop(position=(num_attr(stop, "pos") or 0) / 100000, color=color))
    if not stops:
        return None

    path = child(gradient, "path")
    if path is not None:
        # Radial/shape gradient: fillToRect gives the focus rectangle as inset percentages.
        rect = child(path, "fillToRect")
        left = num_attr(rect, "l") or 0
        top = num_attr(rect, "t") or 0
        right = num_attr(rect, "r") or 0
        bottom = num_attr(rect, "b") or 0
        return SourceGradientFill(
            stops=stops,
            gradient_type="radial",
            center_x=(left + (100000 - right)) / 2 / 100000,
            center_y=(top + (100000 - bottom)) / 2 / 100000,
            path=attr(path, "path") or "circle",
            focus=(left / 100000, top / 100000, right / 100000, bottom / 100000),
            rotate_with_shape=_optional_bool(attr(gradient, "rotWithShape")),
        )

    lin = child(gradient, "lin")
    return SourceGradientFill(
        stops=stops,
        gradient_type="linear",
        angle=num_attr(lin, "ang") or 0,
        scaled=_optional_bool(attr(lin, "scaled")),
        rotate_with_shape=_optional_bool(attr(gradient, "rotWithShape")),
    )


def _optional_bool(value: str | None) -> bool | None:
    return None if value is None else is_true(value)


def parse_blip_fill(blip_fill: Element) -> SourceFill | None:
    blip = child(blip_fill, "blip")
    embed = ns_attr(blip, "embed")
    if embed is None:
        return None
    return SourceImageFill(
        blip_relationship_id=embed,
        svg_relationship_id=parse_svg_blip_rel_id(blip),
        tile=parse_image_fill_tile(child(blip_fill, "tile")),
        src_rect=parse_relative_rect(child(blip_fill, "srcRect")),
        stretch=parse_relative_rect(child(child(blip_fill, "stretch"), "fillRect")),
    )


def parse_svg_blip_rel_id(blip: Element | None) -> str | None:
    """``a:blip/a:extLst/a:ext/asvg:svgBlip@r:embed`` -- the vector original of a picture.

    PowerPoint stores an SVG picture *twice*: a rasterised PNG in ``a:blip@r:embed``, so
    that every consumer draws something, and the SVG itself hung off the blip in an
    extension.  Readers that do not know the extension get the raster and are none the
    wiser, which is the point of the design -- and is also why missing it is invisible:
    the picture is simply soft, at whatever size PowerPoint happened to rasterise it.

    We embed SVG directly, so the vector is strictly the better of the two.  The
    extension's ``uri`` is a fixed GUID, but it is matched on the element name instead:
    the name is what identifies it in the schema, and one deck in the wild spelling the
    GUID differently would cost a picture for nothing.
    """
    for ext in children(child(blip, "extLst"), "ext"):
        svg_blip = child(ext, "svgBlip")
        if svg_blip is not None:
            embed = ns_attr(svg_blip, "embed")
            if embed is not None:
                return embed
    return None


def parse_image_fill_tile(tile: Element | None) -> SourceImageFillTile | None:
    if tile is None:
        return None
    flip = attr(tile, "flip") or "none"
    return SourceImageFillTile(
        tx=num_attr(tile, "tx") or 0,
        ty=num_attr(tile, "ty") or 0,
        sx=(num_attr(tile, "sx") or 100000) / 100000,
        sy=(num_attr(tile, "sy") or 100000) / 100000,
        flip=flip if flip in ("x", "y", "xy") else "none",  # type: ignore[arg-type]
        align=parse_rectangle_alignment(attr(tile, "algn"), "tl"),
    )


def parse_relative_rect(rect: Element | None) -> tuple[float, float, float, float] | None:
    """``a:srcRect`` / ``a:fillRect`` inset percentages -> 0..1 ratios (l, t, r, b)."""
    if rect is None:
        return None
    return (
        (num_attr(rect, "l") or 0) / 100000,
        (num_attr(rect, "t") or 0) / 100000,
        (num_attr(rect, "r") or 0) / 100000,
        (num_attr(rect, "b") or 0) / 100000,
    )


def parse_rectangle_alignment(value: str | None, fallback: str) -> str:
    return value if value in RECTANGLE_ALIGNMENTS else fallback


def parse_pattern_fill(pattern: Element) -> SourceFill | None:
    foreground = parse_color(child(pattern, "fgClr"))
    background = parse_color(child(pattern, "bgClr"))
    if foreground is None or background is None:
        return None
    return SourcePatternFill(
        preset=attr(pattern, "prst") or "ltDnDiag",
        foreground_color=foreground,
        background_color=background,
    )


# --------------------------------------------------------------------------------------
# Outline
# --------------------------------------------------------------------------------------


def parse_outline(sp_pr: Element | None) -> SourceOutline | None:
    return parse_line(child(sp_pr, "ln"))


def parse_line(ln: Element | None) -> SourceOutline | None:
    """Read ``a:ln`` / ``a:lnL`` / ``a:lnR`` / ``a:lnT`` / ``a:lnB``."""
    if ln is None:
        return None

    dash = attr(child(ln, "prstDash"), "val")
    cap = attr(ln, "cap")
    compound = attr(ln, "cmpd")
    return SourceOutline(
        width=num_attr(ln, "w"),
        fill=parse_fill(ln),
        dash_style=dash if dash in DASH_STYLES else None,  # type: ignore[arg-type]
        custom_dash=parse_custom_dash(ln),
        line_cap=LINE_CAP_MAP.get(cap) if cap else None,  # type: ignore[arg-type]
        line_join=parse_line_join(ln),
        head_end=parse_arrow_endpoint(child(ln, "headEnd")),
        tail_end=parse_arrow_endpoint(child(ln, "tailEnd")),
        compound=compound if compound in COMPOUND_LINE_TYPES else None,  # type: ignore[arg-type]
    )


def parse_custom_dash(ln: Element) -> list[float] | None:
    segments = children(child(ln, "custDash"), "ds")
    if not segments:
        return None
    dashes: list[float] = []
    for segment in segments:
        dashes.append((num_attr(segment, "d") or 100000) / 100000)
        dashes.append((num_attr(segment, "sp") or 100000) / 100000)
    return dashes


def parse_line_join(ln: Element) -> str | None:
    for name in ("round", "bevel", "miter"):
        if has_child(ln, name):
            return name
    return None


def parse_arrow_endpoint(node: Element | None) -> ArrowEndpoint | None:
    if node is None:
        return None
    arrow_type = attr(node, "type")
    if arrow_type not in ARROW_TYPES:
        return None
    width = attr(node, "w") or "med"
    length = attr(node, "len") or "med"
    return ArrowEndpoint(
        type=arrow_type,  # type: ignore[arg-type]
        width=width if width in ARROW_SIZES else "med",  # type: ignore[arg-type]
        length=length if length in ARROW_SIZES else "med",  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------------------
# Style references (a:style)
# --------------------------------------------------------------------------------------


def parse_style_reference(node: Element | None) -> SourceStyleReference | None:
    if node is None:
        return None
    collection = attr(node, "idx")
    return SourceStyleReference(
        idx=int(num_attr(node, "idx") or 0),
        color=parse_color(node),
        collection=collection if collection in FONT_COLLECTIONS else None,
    )


#: ``ST_FontCollectionIndex``: what ``a:fontRef@idx`` says instead of a number.
FONT_COLLECTIONS = frozenset({"major", "minor", "none"})


def parse_shape_style(style: Element | None) -> SourceShapeStyle | None:
    if style is None:
        return None
    parsed = SourceShapeStyle(
        fill_ref=parse_style_reference(child(style, "fillRef")),
        line_ref=parse_style_reference(child(style, "lnRef")),
        effect_ref=parse_style_reference(child(style, "effectRef")),
        font_ref=parse_style_reference(child(style, "fontRef")),
    )
    if parsed.fill_ref or parsed.line_ref or parsed.effect_ref or parsed.font_ref:
        return parsed
    return None


# --------------------------------------------------------------------------------------
# Effects
# --------------------------------------------------------------------------------------


def parse_effect_list(effect_list: Element | None) -> SourceEffectList | None:
    if effect_list is None:
        return None

    outer = child(effect_list, "outerShdw")
    inner = child(effect_list, "innerShdw")
    glow = child(effect_list, "glow")
    soft = child(effect_list, "softEdge")

    parsed = SourceEffectList(
        outer_shadow=_parse_outer_shadow(outer),
        inner_shadow=_parse_inner_shadow(inner),
        glow=_parse_glow(glow),
        soft_edge=SourceSoftEdge(radius=num_attr(soft, "rad") or 0) if soft is not None else None,
    )
    if parsed.outer_shadow or parsed.inner_shadow or parsed.glow or parsed.soft_edge:
        return parsed
    return None


def _parse_outer_shadow(node: Element | None) -> SourceOuterShadow | None:
    if node is None:
        return None
    color = parse_color(node)
    if color is None:
        return None
    return SourceOuterShadow(
        blur_radius=num_attr(node, "blurRad") or 0,
        distance=num_attr(node, "dist") or 0,
        direction=num_attr(node, "dir") or 0,
        color=color,
        alignment=parse_rectangle_alignment(attr(node, "algn"), "b"),  # type: ignore[arg-type]
        rotate_with_shape=attr(node, "rotWithShape") != "0",
    )


def _parse_inner_shadow(node: Element | None) -> SourceInnerShadow | None:
    if node is None:
        return None
    color = parse_color(node)
    if color is None:
        return None
    return SourceInnerShadow(
        blur_radius=num_attr(node, "blurRad") or 0,
        distance=num_attr(node, "dist") or 0,
        direction=num_attr(node, "dir") or 0,
        color=color,
    )


def _parse_glow(node: Element | None) -> SourceGlow | None:
    if node is None:
        return None
    color = parse_color(node)
    if color is None:
        return None
    return SourceGlow(radius=num_attr(node, "rad") or 0, color=color)


def _alpha_mod_fix(node: Element | None) -> float | None:
    if node is None:
        return None
    amount = (num_attr(node, "amt") or 100000) / 100000
    return amount if amount < 1 else None


def parse_blip_effects(blip: Element | None) -> SourceBlipEffects | None:
    """Read the image adjustment children of ``a:blip`` (grayscale, duotone, ...)."""
    if blip is None:
        return None

    bi_level = child(blip, "biLevel")
    blur = child(blip, "blur")
    lum = child(blip, "lum")
    duotone = child(blip, "duotone")
    clr_change = child(blip, "clrChange")
    alpha_mod_fix = child(blip, "alphaModFix")

    duotone_colors = None
    if duotone is not None:
        colors = [c for c in (parse_color_node(node) for node in duotone) if c is not None]
        if len(colors) >= 2:
            duotone_colors = (colors[0], colors[1])

    change = None
    if clr_change is not None:
        source = parse_color(child(clr_change, "clrFrom"))
        target = parse_color(child(clr_change, "clrTo"))
        if source is not None and target is not None:
            change = (source, target)

    parsed = SourceBlipEffects(
        grayscale=has_child(blip, "grayscl"),
        bi_level=(num_attr(bi_level, "thresh") or 50000) / 100000 if bi_level is not None else None,
        blur=(num_attr(blur, "rad") or 0, attr(blur, "grow") != "0") if blur is not None else None,
        lum=(
            ((num_attr(lum, "bright") or 0) / 100000, (num_attr(lum, "contrast") or 0) / 100000)
            if lum is not None
            else None
        ),
        duotone=duotone_colors,
        clr_change=change,
        # `a:alphaModFix@amt` is a 1/1000 percent and defaults to 100%, so a bare
        # `<a:alphaModFix/>` -- which is what a Google Slides export writes on every
        # picture -- asks for nothing.  Recording it as 1.0 would put a no-op
        # `feFuncA slope="1"` into the filter chain of every such picture, so the no-op
        # is dropped here and only a real reduction survives.
        alpha=_alpha_mod_fix(alpha_mod_fix),
    )
    if (
        parsed.grayscale
        or parsed.bi_level is not None
        or parsed.blur is not None
        or parsed.lum is not None
        or parsed.duotone is not None
        or parsed.clr_change is not None
        or parsed.alpha is not None
    ):
        return parsed
    return None


# --------------------------------------------------------------------------------------
# Transform
# --------------------------------------------------------------------------------------


def parse_transform(sp_pr: Element | None) -> SourceTransform | None:
    """Read ``a:xfrm`` -- offset / extent / rotation / flip."""
    return _transform_from_xfrm(child(sp_pr, "xfrm"))


def parse_group_transforms(
    grp_sp_pr: Element | None,
) -> tuple[SourceTransform | None, SourceTransform | None]:
    """Group ``a:xfrm`` carries both the outer placement and the child coordinate space."""
    xfrm = child(grp_sp_pr, "xfrm")
    if xfrm is None:
        return None, None
    outer = _transform_from_xfrm(xfrm)
    child_off = child(xfrm, "chOff")
    child_ext = child(xfrm, "chExt")
    if child_off is None or child_ext is None:
        return outer, None
    inner = SourceTransform(
        offset_x=num_attr(child_off, "x") or 0,
        offset_y=num_attr(child_off, "y") or 0,
        width=num_attr(child_ext, "cx") or 0,
        height=num_attr(child_ext, "cy") or 0,
    )
    return outer, inner


def parse_text_transform(sp: Element | None) -> SourceTransform | None:
    """``dsp:txXfrm`` -- a diagram shape's text box, placed independently of the shape.

    Only SmartArt's cached drawings use this, and they use it constantly: a Venn ring's
    label belongs in the sliver that ring does not share, a cycle arrow's label beside
    the arrow rather than across it.  Without it every label lands at its shape's own
    origin, which for a circle means the top-left corner of its bounding box.

    The offset is in the same coordinate space as the shape's own ``a:xfrm``, so the
    renderer works with the difference between the two.
    """
    return _transform_from_xfrm(child(sp, "txXfrm"))


def _transform_from_xfrm(xfrm: Element | None) -> SourceTransform | None:
    if xfrm is None:
        return None
    off = child(xfrm, "off")
    ext = child(xfrm, "ext")
    offset_x = num_attr(off, "x")
    offset_y = num_attr(off, "y")
    width = num_attr(ext, "cx")
    height = num_attr(ext, "cy")
    if offset_x is None or offset_y is None or width is None or height is None:
        return None
    return SourceTransform(
        offset_x=offset_x,
        offset_y=offset_y,
        width=width,
        height=height,
        rotation=num_attr(xfrm, "rot") or 0,
        flip_horizontal=is_true(attr(xfrm, "flipH")),
        flip_vertical=is_true(attr(xfrm, "flipV")),
    )


# --------------------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------------------


def parse_geometry(sp_pr: Element | None) -> SourceGeometry | None:
    if sp_pr is None:
        return None

    preset = child(sp_pr, "prstGeom")
    if preset is not None:
        return SourcePresetGeometry(
            preset=attr(preset, "prst") or "rect",
            adjust_values={
                name: value
                for name, value in (
                    (attr(gd, "name"), _adjust_value(attr(gd, "fmla")))
                    for gd in children(child(preset, "avLst"), "gd")
                )
                if name is not None and value is not None
            },
        )

    custom = child(sp_pr, "custGeom")
    if custom is not None:
        paths = parse_custom_geometry(custom)
        if paths:
            return SourceCustomGeometry(paths=paths)

    return None


def _adjust_value(formula: str | None) -> float | None:
    """``avLst`` guides are always ``val N`` for preset adjustments."""
    if formula is None:
        return None
    tokens = formula.split()
    if len(tokens) == 2 and tokens[0] == "val":
        try:
            return float(tokens[1])
        except ValueError:
            return None
    return None


def parse_custom_geometry(cust_geom: Element | None) -> list[CustomGeometryPath]:
    """Convert ``a:custGeom`` into SVG path data, evaluating the guide formulas."""
    path_list = child(cust_geom, "pathLst")
    paths = children(path_list, "path")
    if not paths:
        return []

    av_guides = _parse_guide_list(child(cust_geom, "avLst"))
    gd_guides = _parse_guide_list(child(cust_geom, "gdLst"))

    result: list[CustomGeometryPath] = []
    for path in paths:
        width = num_attr(path, "w") or 0
        height = num_attr(path, "h") or 0
        if width == 0 and height == 0:
            continue
        variables = evaluate_guides([av_guides, gd_guides], width, height)
        commands = _build_path_commands(path, variables)
        if commands:
            result.append(CustomGeometryPath(width=width, height=height, commands=commands))
    return result


#: ``a:pathLst`` commands as the preset table's command letters.
_SPEC_LETTERS = {"moveTo": "M", "lnTo": "L", "quadBezTo": "Q", "cubicBezTo": "C", "arcTo": "A", "close": "Z"}


def parse_geometry_spec(sp_pr: Element | None) -> tuple | None:
    """A shape's geometry for :mod:`~ooxml_common.drawingml.geometry`'s path-data
    functions: ``("preset", name, {adjustment: formula})`` for ``a:prstGeom``, or
    ``("custom", spec)`` for ``a:custGeom`` with ``spec`` in the preset table's form --
    ``(adjustments, guides, paths)``, each path ``(fill, stroke, (w, h), commands)`` and
    each command a letter with its operands as written (guide names or literals) -- which
    :func:`~ooxml_common.drawingml.geometry.spec_path_data` draws at any size, keeping each
    path's ``@fill`` and ``@stroke``.  ``None`` when the shape states neither.

    :func:`parse_geometry` evaluates a custom geometry into path strings at its own size
    and drops the paint flags; a consumer that draws each ``a:path`` itself reads this."""
    preset = child(sp_pr, "prstGeom")
    if preset is not None:
        adjust = {attr(g, "name") or "": attr(g, "fmla") or "" for g in children(child(preset, "avLst"), "gd")}
        return ("preset", attr(preset, "prst") or "rect", adjust)
    custom = child(sp_pr, "custGeom")
    if custom is None:
        return None
    adjustments = tuple(_parse_guide_list(child(custom, "avLst")))
    guides = tuple(_parse_guide_list(child(custom, "gdLst")))
    paths = []
    for path in children(child(custom, "pathLst"), "path"):
        commands = []
        for node in path:
            letter = _SPEC_LETTERS.get(local_name(node.tag))
            if letter is None:
                continue
            if letter == "A":
                commands.append(("A",) + tuple(attr(node, key) or "0" for key in ("wR", "hR", "stAng", "swAng")))
            elif letter == "Z":
                commands.append(("Z",))
            else:
                commands.append((letter,) + tuple(value for point in children(node, "pt")
                                                  for value in (attr(point, "x") or "0", attr(point, "y") or "0")))
        space = (num_attr(path, "w") or 0, num_attr(path, "h") or 0)
        paths.append((attr(path, "fill") or "norm", attr(path, "stroke") not in ("0", "false"),
                      space if any(space) else None, tuple(commands)))
    return ("custom", (adjustments, guides, tuple(paths)))


def parse_text_rect(sp_pr: Element | None) -> tuple[str, str, str, str] | None:
    """A custom geometry's text rectangle (``a:custGeom/a:rect``): its ``l``, ``t``, ``r``
    and ``b``, guide names or literals as written, for
    :func:`~ooxml_common.drawingml.geometry.text_rect`; ``None`` when there is none (a
    preset's comes from the specification)."""
    rect = child(child(sp_pr, "custGeom"), "rect")
    if rect is None:
        return None
    return tuple(attr(rect, key) or default for key, default in (("l", "l"), ("t", "t"), ("r", "r"), ("b", "b")))


def _parse_guide_list(parent: Element | None) -> list[tuple[str, str]]:
    guides: list[tuple[str, str]] = []
    for guide in children(parent, "gd"):
        name = attr(guide, "name")
        formula = attr(guide, "fmla")
        if name and formula:
            guides.append((name, formula))
    return guides


def _build_path_commands(path: Element, variables: dict[str, float]) -> str:
    parts: list[str] = []
    current_x = current_y = start_x = start_y = 0.0

    for node in path:
        command = local_name(node.tag)
        if command == "moveTo":
            point = _first_point(node, variables)
            if point is not None:
                parts.append(f"M {_fmt(point[0])} {_fmt(point[1])}")
                current_x, current_y = point
                start_x, start_y = point
        elif command == "lnTo":
            point = _first_point(node, variables)
            if point is not None:
                parts.append(f"L {_fmt(point[0])} {_fmt(point[1])}")
                current_x, current_y = point
        elif command == "cubicBezTo":
            points = _all_points(node, variables)
            if len(points) >= 3:
                parts.append("C " + ", ".join(f"{_fmt(x)} {_fmt(y)}" for x, y in points))
                current_x, current_y = points[-1]
        elif command == "quadBezTo":
            points = _all_points(node, variables)
            if len(points) >= 2:
                parts.append("Q " + ", ".join(f"{_fmt(x)} {_fmt(y)}" for x, y in points))
                current_x, current_y = points[-1]
        elif command == "arcTo":
            arc = _convert_arc_to(node, current_x, current_y, variables)
            if arc is not None:
                parts.append(arc[0])
                current_x, current_y = arc[1], arc[2]
        elif command == "close":
            parts.append("Z")
            current_x, current_y = start_x, start_y

    return " ".join(parts)


def _first_point(node: Element, variables: dict[str, float]) -> tuple[float, float] | None:
    points = _all_points(node, variables)
    return points[0] if points else None


def _all_points(node: Element, variables: dict[str, float]) -> list[tuple[float, float]]:
    return [
        (
            resolve_value(attr(point, "x") or "0", variables),
            resolve_value(attr(point, "y") or "0", variables),
        )
        for point in children(node, "pt")
    ]


def _convert_arc_to(
    arc: Element, current_x: float, current_y: float, variables: dict[str, float]
) -> tuple[str, float, float] | None:
    width_radius = resolve_value(attr(arc, "wR") or "0", variables)
    height_radius = resolve_value(attr(arc, "hR") or "0", variables)
    start_angle = resolve_value(attr(arc, "stAng") or "0", variables)
    sweep_angle = resolve_value(attr(arc, "swAng") or "0", variables)
    if (width_radius == 0 and height_radius == 0) or sweep_angle == 0:
        return None

    segments = arc_segments(
        current_x, current_y, width_radius, height_radius, start_angle, sweep_angle
    )
    if not segments:
        return None

    command = " ".join(
        f"A {_round(width_radius)} {_round(height_radius)} 0 "
        f"{large_arc} {sweep_flag} {_round(end_x)} {_round(end_y)}"
        for end_x, end_y, large_arc, sweep_flag in segments
    )
    end_x, end_y = segments[-1][0], segments[-1][1]
    return command, end_x, end_y


def _round(value: float) -> str:
    return _fmt(value)


def _fmt(value: float) -> str:
    """Compact coordinate formatting: 0.0 -> "0", 12.3456 -> "12.346"."""
    rounded = round(value, 3)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:g}"


# --------------------------------------------------------------------------------------
# The theme: its colour scheme and format scheme
# --------------------------------------------------------------------------------------

#: ``a:clrScheme``'s slots, in schema order.
COLOR_SCHEME_KEYS = (
    "dk1", "lt1", "dk2", "lt2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6",
    "hlink", "folHlink",
)


def parse_color_scheme(clr_scheme: Element | None) -> dict:
    """``a:clrScheme`` as ``{slot: colour choice}`` (moved from ``pptx2svg.parse.parts``)."""
    if clr_scheme is None:
        return {}
    scheme = {}
    for key in COLOR_SCHEME_KEYS:
        color = parse_color(child(clr_scheme, key))
        if color is not None:
            scheme[key] = color
    return scheme


def parse_format_scheme(fmt_scheme: Element | None) -> SourceFormatScheme:
    """``a:fmtScheme``: the fill, line, effect and background fill styles a shape style's
    ``idx`` selects (moved from ``pptx2svg.parse.parts``)."""
    if fmt_scheme is None:
        return SourceFormatScheme()
    return SourceFormatScheme(
        fill_styles=[
            fill
            for fill in (parse_fill_style(node) for node in children(child(fmt_scheme, "fillStyleLst")))
            if fill is not None
        ],
        line_styles=[
            line
            for line in (parse_line(node) for node in children(child(fmt_scheme, "lnStyleLst"), "ln"))
            if line is not None
        ],
        effect_styles=[
            parse_effect_list(child(node, "effectLst"))
            for node in children(child(fmt_scheme, "effectStyleLst"), "effectStyle")
        ],
        bg_fill_styles=[
            fill
            for fill in (
                parse_fill_style(node) for node in children(child(fmt_scheme, "bgFillStyleLst"))
            )
            if fill is not None
        ],
    )


def parse_fill_style(node: Element | None):
    """A fill style list holds bare fill elements; wrap each so ``parse_fill`` can read it."""
    if node is None:
        return None
    wrapper = Element("wrapper")
    wrapper.append(node)
    return parse_fill(wrapper)
