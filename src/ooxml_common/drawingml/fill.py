"""Fill, stroke and arrow-marker attributes.

Renderers here return *attribute strings* rather than elements, because the caller
splices them into whichever geometry element the shape produced.  Anything that needs a
``<defs>`` entry (gradients, image patterns, hatch patterns, markers) registers it on the
:class:`~ooxml_common.drawingml.svg.SvgDefs` it is given -- pptx2svg's ``RenderContext`` is
one -- and returns a ``url(#id)`` reference.

SVG output uses inline attributes only -- no CSS classes.  librsvg and resvg, the usual
rasterisation backends, do not apply CSS selectors reliably.
"""

from __future__ import annotations

import base64
import math
from dataclasses import dataclass

from . import model as m
from ..imagemeta import natural_size_pt
from ..units import DEFAULT_DPI, PX_PER_PT, emu_to_px
from .rules import POWERPOINT, DrawingRules
from .svg import SvgDefs, num
from .pattern import PATTERN_CELL_BITS, PATTERN_CELL_PT, cell_rectangles

#: Dash patterns as multiples of the stroke width (ECMA-376 §20.1.10.49).
DASH_PATTERNS: dict[str, list[float]] = {
    "dash": [4, 3],
    "dot": [1, 3],
    "dashDot": [4, 3, 1, 3],
    "lgDash": [8, 3],
    "lgDashDot": [8, 3, 1, 3],
    "lgDashDotDot": [8, 3, 1, 3, 1, 3],
    "sysDash": [3, 1],
    "sysDot": [1, 1],
    # Measured on Word (rules.py); pptx2svg's reader never produced these names before
    # the reader moved here, and draws them as it draws any preset.
    "sysDashDot": [3, 1, 1, 1],
    "sysDashDotDot": [3, 1, 1, 1, 1, 1],
}


@dataclass(frozen=True)
class ShapeFrame:
    """How the element a fill is referenced from is placed on its page, for the rules
    that measured a fill against the page rather than the shape (:mod:`.rules`):
    its rotation in degrees and flips (a gradient with ``rotWithShape="0"`` keeps its
    angle to the page), and ``page_transform``, an SVG transform from the page's
    coordinates into the element's user space (a pattern registered to the page)."""

    rotation: float = 0.0
    flip_h: bool = False
    flip_v: bool = False
    page_transform: str | None = None
    #: Whether the shape's outline is its box: a ``shape`` path gradient draws rings of
    #: the outline, rectangles on a rectangle and ellipses on an ellipse (measured).
    rectangular: bool = True

ARROW_SIZE_PX: dict[str, float] = {"sm": 5, "med": 8, "lg": 12}


def render_fill_attrs(
    fill: m.Fill | None,
    context: SvgDefs,
    box: tuple[float, float, float, float] | None = None,
    *,
    rules: DrawingRules = POWERPOINT,
    dpi: float = DEFAULT_DPI,
    frame: ShapeFrame | None = None,
) -> str:
    """``fill="..."`` (plus ``fill-opacity``) for a shape.

    ``box`` is the filled rectangle -- ``(x, y, width, height)`` in the user space the
    fill is referenced from, all in pixels.  A tiled image fill needs it, for a reason no
    other fill does under pptx2svg's rules: ``a:tile@algn`` registers the tile grid
    against one of the box's nine corners and edges, so without the box there is no
    right answer, only a guess that it is the top-left one.  Under rules whose gradients
    are measured (:mod:`.rules`) a gradient needs it too; without it, it is drawn as
    pptx2svg draws one.

    ``dpi`` is the pixels per inch of the caller's user space (96, pptx2svg's; docx2svg
    draws on Word's 300 dpi device grid): the pattern cell and a picture tile are sized in
    it.  ``frame`` is where the element sits on its page (:class:`ShapeFrame`).
    """
    if fill is None or isinstance(fill, m.NoFill):
        return 'fill="none"'

    if isinstance(fill, m.SolidFill):
        opacity = f' fill-opacity="{num(fill.color.alpha)}"' if fill.color.alpha < 1 else ""
        return f'fill="{fill.color.hex}"{opacity}'

    if isinstance(fill, m.GradientFill):
        if rules.gradients == "office" and box is not None:
            return f'fill="{office_gradient_ref(fill, context, box, frame)}"'
        return f'fill="{_gradient_ref(fill, context)}"'

    if isinstance(fill, m.ImageFill):
        return f'fill="{_image_fill_ref(fill, context, box, dpi)}"'

    if isinstance(fill, m.PatternFill):
        return _pattern_fill_attrs(fill, context, dpi=dpi,
                                   page=frame if rules.pattern_phase == "page" else None,
                                   on_page=rules.pattern_phase == "page")

    return 'fill="none"'


def _gradient_ref(fill: m.GradientFill, context: SvgDefs) -> str:
    gradient_id = context.new_id("grad")

    stops = "".join(
        f'<stop offset="{num(stop.position * 100)}%" stop-color="{stop.color.hex}"'
        + (f' stop-opacity="{num(stop.color.alpha)}"' if stop.color.alpha < 1 else "")
        + "/>"
        for stop in fill.stops
    )

    if fill.gradient_type == "radial":
        cx = (fill.center_x if fill.center_x is not None else 0.5) * 100
        cy = (fill.center_y if fill.center_y is not None else 0.5) * 100
        # Radius reaches the farthest corner from the focus point.
        dx = max(cx, 100 - cx)
        dy = max(cy, 100 - cy)
        r = math.hypot(dx, dy)
        context.add_def(
            f'<radialGradient id="{gradient_id}" cx="{num(cx)}%" cy="{num(cy)}%" '
            f'r="{num(r)}%">{stops}</radialGradient>'
        )
        return f"url(#{gradient_id})"

    radians = math.radians(fill.angle)
    x1 = 50 - math.cos(radians) * 50
    y1 = 50 - math.sin(radians) * 50
    x2 = 50 + math.cos(radians) * 50
    y2 = 50 + math.sin(radians) * 50
    context.add_def(
        f'<linearGradient id="{gradient_id}" x1="{num(x1)}%" y1="{num(y1)}%" '
        f'x2="{num(x2)}%" y2="{num(y2)}%">{stops}</linearGradient>'
    )
    return f"url(#{gradient_id})"


def _image_fill_ref(
    fill: m.ImageFill,
    context: SvgDefs,
    box: tuple[float, float, float, float] | None = None,
    dpi: float = DEFAULT_DPI,
) -> str:
    pattern_id = context.new_id("imgfill")
    href = f"data:{fill.mime_type};base64,{fill.image_data}"

    if fill.tile is not None:
        tile = tile_pattern(pattern_id, href, fill.image_data, fill.tile, box, dpi=dpi)
        if tile is not None:
            context.add_def(tile)
            return f"url(#{pattern_id})"
        # The picture's natural size is what a tile is measured in, and a format
        # `imagemeta` cannot read has none to measure.  Stretching one copy over the
        # shape is wrong, but it is the same wrong as an untiled fill rather than a
        # tiling at an invented pitch.

    context.add_def(
        f'<pattern id="{pattern_id}" patternContentUnits="objectBoundingBox" '
        f'width="1" height="1">'
        f'<image href="{href}" width="1" height="1" preserveAspectRatio="none"/>'
        "</pattern>"
    )
    return f"url(#{pattern_id})"


#: ``@flip`` -> whether the cell carries a copy mirrored across x, and across y.
_TILE_FLIPS: dict[str, tuple[bool, bool]] = {
    "none": (False, False),
    "x": (True, False),
    "y": (False, True),
    "xy": (True, True),
}


def tile_pattern(
    pattern_id: str,
    href: str,
    image_data: str,
    tile: m.ImageFillTile | m.TileInfo,
    box: tuple[float, float, float, float] | None,
    image_attrs: str = "",
    *,
    dpi: float = DEFAULT_DPI,
) -> str | None:
    """One ``<pattern>`` for ``a:tile``, sized and registered the way PowerPoint does.

    **The tile is the picture's own size scaled by ``sx``/``sy``.**  It has nothing to do
    with the shape.  This file used to say "a tiled fill repeats at sx/sy of the shape's
    bounding box", and the measurement refutes it: deck ``fill-tile`` drew the same 32 px
    picture at ``sx=100%`` on boxes of 68x48, 136x96, 272x192 and 400x96 pt and got a
    16.0000 pt cell on all four.  Scaling the picture's natural size instead (see
    :mod:`ooxml_common.imagemeta`) reproduces every row of that deck: 25, 50, 60, 150 and 200%
    of a 16 pt picture drew 4, 8, 9.6, 24 and 32 pt, and ``sx != sy`` moved the two axes
    independently.  ``feature-sweep`` slide 10 is the same arithmetic -- a 32 px untagged
    PNG at ``sx=60%`` is 16 x 0.6 = 9.6 pt, which is what PowerPoint drew there, against
    the 82.08 pt this drew from the box.

    Shared with pptx2svg's ``p:pic`` path (``pptx2svg.render.shape``), which carries the
    identical ``a:tile`` and used to size it from the frame for the stated reason that the
    two paths agreeing mattered more than either being right.  They agree here too, on the
    measurement.

    ``@algn`` registers the grid against the box and ``@tx``/``@ty`` then translate it;
    see :func:`_tile_origin`.  ``@flip`` mirrors alternate copies, which an SVG
    ``<pattern>`` cannot do by repeating one tile -- so the cell is doubled and holds the
    mirrored copies itself, which is exactly what PowerPoint's own export does (a
    ``flip="xy"`` tile of a 32 px picture exports as a **64 x 64** image on a doubled
    cell).  Measured: from the registration point the order is original then mirror in
    both axes, and ``flip="x"`` mirrors **horizontally**.
    """
    try:
        data = base64.b64decode(image_data, validate=True)
    except (ValueError, TypeError):
        return None
    natural = natural_size_pt(data)
    if natural is None:
        return None

    px_per_pt = PX_PER_PT if dpi == DEFAULT_DPI else dpi / 72
    width = natural[0] * px_per_pt * tile.sx
    height = natural[1] * px_per_pt * tile.sy
    if width <= 0 or height <= 0:
        return None

    mirror_x, mirror_y = _TILE_FLIPS.get(tile.flip, (False, False))
    cell_width = width * (2 if mirror_x else 1)
    cell_height = height * (2 if mirror_y else 1)

    x, y = _tile_origin(tile.align, box, width, height)
    x += emu_to_px(tile.tx, dpi)
    y += emu_to_px(tile.ty, dpi)

    copies = [(0.0, 0.0, 1, 1)]
    if mirror_x:
        copies.append((2 * width, 0.0, -1, 1))
    if mirror_y:
        copies.append((0.0, 2 * height, 1, -1))
    if mirror_x and mirror_y:
        copies.append((2 * width, 2 * height, -1, -1))

    images = "".join(
        f'<image href="{href}" width="{num(width)}" height="{num(height)}" '
        f'preserveAspectRatio="none"'
        + (f" {image_attrs}" if image_attrs else "")
        + (
            ""
            if (scale_x, scale_y) == (1, 1)
            else f' transform="translate({num(offset_x)}, {num(offset_y)}) '
            f'scale({scale_x}, {scale_y})"'
        )
        + "/>"
        for offset_x, offset_y, scale_x, scale_y in copies
    )
    return (
        f'<pattern id="{pattern_id}" patternUnits="userSpaceOnUse" '
        f'x="{num(x)}" y="{num(y)}" '
        f'width="{num(cell_width)}" height="{num(cell_height)}">{images}</pattern>'
    )


def _tile_origin(
    align: str,
    box: tuple[float, float, float, float] | None,
    width: float,
    height: float,
) -> tuple[float, float]:
    """Where ``@algn`` puts the grid, in the same space as ``box``.

    Measured on deck ``fill-algn``, which had to be built twice.  The first sweep put all
    nine alignments on a 136 x 96 pt box with an 8 pt tile, and 136 and 96 are 17 and 12
    whole tiles -- so left-, centre- and right-registration all landed on the same lattice
    and the sweep said nothing at all.  Re-run on a 130 x 90 box with an 8 pt tile and a
    137 x 83 box with a 12 pt one -- indivisible in both axes both times -- the three rules
    separate cleanly:

    * leading (``tl``/``l``/``bl`` in x, ``tl``/``t``/``tr`` in y) puts the tile's leading
      edge on the box's, so the origin is the box's own left or top;
    * trailing puts the tile's trailing edge on the box's, so the origin is the box's end
      minus one tile -- read as -6 on 130 pt / 8 pt and -7 on 137 pt / 12 pt, which is
      that value modulo the cell;
    * centred puts **one tile's centre on the box's centre** -- read as -3 and -9.5 for the
      same two, which is ``(box - tile) / 2`` modulo the cell.

    The two axes are chosen independently by the two halves of the name, so the nine
    values are one product of three rules with three rather than nine separate cases.
    """
    if box is None:
        return 0.0, 0.0
    left, top, box_width, box_height = box
    if align in ("tr", "r", "br"):
        x = left + box_width - width
    elif align in ("t", "ctr", "b"):
        x = left + (box_width - width) / 2
    else:
        x = left
    if align in ("bl", "b", "br"):
        y = top + box_height - height
    elif align in ("l", "ctr", "r"):
        y = top + (box_height - height) / 2
    else:
        y = top
    return x, y


def _pattern_fill_attrs(
    fill: m.PatternFill,
    context: SvgDefs,
    *,
    dpi: float = DEFAULT_DPI,
    page: ShapeFrame | None = None,
    on_page: bool = False,
) -> str:
    """``a:pattFill`` as a ``<pattern>`` of the preset's measured 8 x 8 cell.

    The cell is **8.0 pt**, which is ``PATTERN_CELL_PT * PX_PER_PT`` pixels here, and one
    bit of the preset's bitmap is one point.  The old code used 8 *pixels*, which is 6 pt,
    so every pattern in the library tiled a third too finely; see
    :mod:`ooxml_common.drawingml.pattern` for how the cell and all 54 bitmaps were measured.

    **The lattice's phase is measured but not reproduced.**  PowerPoint registers the grid
    to the slide's own top-left corner: deck ``fill-pitch`` put a shape's left edge at
    36.0, 36.5, 38.0, 41.0, 100.3, 173.75, 260.125 and 411.0 pt and the exported pattern
    origin snapped every one down to the 8 pt lattice -- 32, 32, 32, 40, 96, 168, 256, 408
    -- so two shapes whose left edges differ by 4 pt get patterns half a cell out of step
    with each other.  This registers to each shape's own top-left instead, which is the
    phase PowerPoint gives a shape that happens to sit on an 8 pt boundary.  The cost is
    exactly that offset and never the pitch, and it is visible: rendered at 5760 px,
    ``feature-sweep`` slide 13's ``cross`` box (at 452, 52 pt, both 4 past a lattice point)
    puts its first rule 3.938 pt into the box for PowerPoint and 0.188 pt for us, on an
    identical 8.0000 pt period -- while the ``horz`` box at 244, 168 pt, which *is* on the
    lattice, matches rule for rule.

    It is left alone because reproducing it needs a concept this renderer does not have --
    the shape's position on the *slide* -- and because that concept immediately raises two
    further questions no probe here answers.  A shape inside a group knows only its offset
    within the group, and a group may also rotate, flip and scale; and a *rotated* shape
    would need to know whether PowerPoint turns the hatch with it or leaves it square to
    the page, which is a device-space brush's usual behaviour and would make the phase a
    property of the drawing surface rather than of the document.  Landing one corner of
    that -- the ungrouped, unrotated case -- would be fitting the fixture rather than the
    law.  Measure those two first; the instrument is ``tools/make_fill_probe.py``.

    **Word answers both, and rules that reproduce it take them** (``on_page``, from
    :attr:`.rules.DrawingRules.pattern_phase`): docx2svg's ``tools/make_dml_probe.py`` found
    Word's cell registered to the page's own top-left corner -- a shape at 95.7 pt drawn
    with its tile origin at 88 -- and a rotated shape's pattern square to the page, not
    turned with it.  So the pattern is laid in the page's coordinates, carried into the
    element's by ``page.page_transform``.
    """
    rectangles = cell_rectangles(fill.preset)
    if rectangles is None:
        # Not a value ST_PresetPatternVal allows at all.  A flat foreground is a poor
        # picture, but every value the schema does allow is measured.
        opacity = (
            f' fill-opacity="{num(fill.foreground_color.alpha)}"'
            if fill.foreground_color.alpha < 1
            else ""
        )
        return f'fill="{fill.foreground_color.hex}"{opacity}'

    cell = PATTERN_CELL_PT * (PX_PER_PT if dpi == DEFAULT_DPI else dpi / 72)
    unit = cell / PATTERN_CELL_BITS
    pattern_id = context.new_id("patt")

    foreground = fill.foreground_color
    fg_opacity = f' fill-opacity="{num(foreground.alpha)}"' if foreground.alpha < 1 else ""
    bg_opacity = (
        f' fill-opacity="{num(fill.background_color.alpha)}"'
        if fill.background_color.alpha < 1
        else ""
    )
    marks = "".join(
        f'<rect x="{num(x * unit)}" y="{num(y * unit)}" '
        f'width="{num(width * unit)}" height="{num(height * unit)}" '
        f'fill="{foreground.hex}"{fg_opacity}/>'
        for x, y, width, height in rectangles
    )
    placement = ""
    if on_page and page is not None and page.page_transform:
        placement = f' patternTransform="{page.page_transform}"'
    context.add_def(
        f'<pattern id="{pattern_id}" patternUnits="userSpaceOnUse" '
        f'width="{num(cell)}" height="{num(cell)}"{placement}>'
        f'<rect width="{num(cell)}" height="{num(cell)}" '
        f'fill="{fill.background_color.hex}"{bg_opacity}/>{marks}</pattern>'
    )
    return f'fill="url(#{pattern_id})"'


def render_outline_attrs(
    outline: m.Outline | None,
    context: SvgDefs,
    *,
    rules: DrawingRules = POWERPOINT,
    dpi: float = DEFAULT_DPI,
    box: tuple[float, float, float, float] | None = None,
    frame: ShapeFrame | None = None,
) -> str:
    """``stroke``/``stroke-width``/``stroke-dasharray`` etc. for a shape.

    ``box`` is the outlined path's box, as for :func:`render_fill_attrs`: a gradient
    outline under measured rules spans it widened by half the width (Word's).
    """
    if outline is None:
        return 'stroke="none"'

    width_px = emu_to_px(outline.width, dpi)
    parts = [f'stroke-width="{num(width_px)}"']

    if outline.fill is None:
        parts.append('stroke="none"')
    elif isinstance(outline.fill, m.SolidFill):
        parts.append(f'stroke="{outline.fill.color.hex}"')
        if outline.fill.color.alpha < 1:
            parts.append(f'stroke-opacity="{num(outline.fill.color.alpha)}"')
    elif isinstance(outline.fill, m.GradientFill):
        if rules.gradients == "office" and box is not None:
            half = width_px / 2
            widened = (box[0] - half, box[1] - half, box[2] + width_px, box[3] + width_px)
            parts.append(f'stroke="{office_gradient_ref(outline.fill, context, widened, frame)}"')
        else:
            parts.append(f'stroke="{_gradient_ref(outline.fill, context)}"')

    cap = outline.line_cap
    dashes = _dash_lengths(outline, width_px, rules)
    if dashes is not None:
        parts.append('stroke-dasharray="' + " ".join(num(value) for value in dashes) + '"')
        if rules.dashes == "office" and cap == "square" and not outline.custom_dash:
            # Word draws a preset dash's own ends butt and squares only the line's ends.
            cap = None

    if cap:
        parts.append(f'stroke-linecap="{cap}"')
    join = outline.line_join or rules.default_join
    if join:
        parts.append(f'stroke-linejoin="{join}"')

    return " ".join(parts)


def _dash_lengths(outline: m.Outline, width_px: float, rules: DrawingRules) -> list[float] | None:
    """The dash array in pixels, or ``None`` for a solid line (:mod:`.rules`, ``dashes``)."""
    if outline.custom_dash:
        pattern = list(outline.custom_dash)
    elif outline.dash_style != "solid":
        pattern = DASH_PATTERNS.get(outline.dash_style)
        if not pattern:
            return None
    else:
        return None
    lengths = [value * width_px for value in pattern]
    if rules.dashes == "office" and outline.line_cap == "round":
        # Each rounded dash reaches half a width past both its ends, so Word draws it a
        # width shorter and the gap a width longer (measured: 3 1 1 1 at 3 pt is 6 6 0 6).
        lengths = [
            max(0.0, value - width_px) if index % 2 == 0 else value + width_px
            for index, value in enumerate(lengths)
        ]
    return lengths


def render_markers(outline: m.Outline | None, context: SvgDefs) -> str:
    """``marker-start``/``marker-end`` attributes for a connector's arrowheads."""
    if outline is None or (outline.head_end is None and outline.tail_end is None):
        return ""

    color, alpha = "#000000", 1.0
    if isinstance(outline.fill, m.SolidFill):
        color, alpha = outline.fill.color.hex, outline.fill.color.alpha
    elif isinstance(outline.fill, m.GradientFill) and outline.fill.stops:
        color, alpha = outline.fill.stops[0].color.hex, outline.fill.stops[0].color.alpha

    attrs: list[str] = []
    if outline.head_end is not None:
        marker_id = context.new_id("marker")
        definition = _marker_def(marker_id, outline.head_end, color, alpha)
        if definition:
            context.add_def(definition)
            attrs.append(f'marker-start="url(#{marker_id})"')
    if outline.tail_end is not None:
        marker_id = context.new_id("marker")
        definition = _marker_def(marker_id, outline.tail_end, color, alpha)
        if definition:
            context.add_def(definition)
            attrs.append(f'marker-end="url(#{marker_id})"')

    return " ".join(attrs)


def _marker_def(
    marker_id: str, endpoint: m.ArrowEndpoint, color: str, alpha: float
) -> str | None:
    mw = ARROW_SIZE_PX[endpoint.length]
    mh = ARROW_SIZE_PX[endpoint.width]
    opacity = f' opacity="{num(alpha)}"' if alpha < 1 else ""

    if endpoint.type == "none":
        return None

    if endpoint.type == "oval":
        return (
            f'<marker id="{marker_id}" markerWidth="{num(mw)}" markerHeight="{num(mh)}" '
            f'refX="{num(mw/2)}" refY="{num(mh/2)}" orient="auto" markerUnits="userSpaceOnUse">'
            f'<ellipse cx="{num(mw/2)}" cy="{num(mh/2)}" rx="{num(mw/2)}" ry="{num(mh/2)}" '
            f'fill="{color}"{opacity}/></marker>'
        )

    if endpoint.type == "triangle":
        path = f"M 0 0 L {num(mw)} {num(mh/2)} L 0 {num(mh)} Z"
        fill_attr = f'fill="{color}"'
    elif endpoint.type == "stealth":
        path = f"M 0 0 L {num(mw)} {num(mh/2)} L 0 {num(mh)} L {num(mw*0.3)} {num(mh/2)} Z"
        fill_attr = f'fill="{color}"'
    elif endpoint.type == "diamond":
        path = (
            f"M 0 {num(mh/2)} L {num(mw/2)} 0 L {num(mw)} {num(mh/2)} L {num(mw/2)} {num(mh)} Z"
        )
        fill_attr = f'fill="{color}"'
    elif endpoint.type == "arrow":
        path = f"M 0 0 L {num(mw)} {num(mh/2)} L 0 {num(mh)}"
        fill_attr = f'fill="none" stroke="{color}" stroke-width="1"'
    else:
        return None

    return (
        f'<marker id="{marker_id}" markerWidth="{num(mw)}" markerHeight="{num(mh)}" '
        f'refX="{num(mw)}" refY="{num(mh/2)}" orient="auto" markerUnits="userSpaceOnUse">'
        f'<path d="{path}" {fill_attr}{opacity}/></marker>'
    )


# --------------------------------------------------------------------------------------
# Gradients as Word draws them (rules.py, ``gradients="office"``)
# --------------------------------------------------------------------------------------

#: Word writes a gradient of exactly two stops, at 0 and 100%, in a linear ("Generic
#: HDR") profile and eases between them: ``C00000`` to ``0070C0`` is ``890000`` to
#: ``002A89`` in that profile (gamma 2.2 of the sRGB levels, to the level), and at a
#: quarter of the way ``730614`` -- not the straight blend's ``671E3A`` but the cosine
#: ease's, ``(1 - cos(pi t)) / 2`` of the way (``142373`` at three quarters; every
#: channel of every probe gradient so).  Any other gradient is written in sRGB and blends
#: straight.  SVG blends straight in sRGB, so the eased blend is written out as this many
#: stops, each converted back.
LINEAR_LIGHT_STOPS = 16
LINEAR_LIGHT_GAMMA = 2.2

#: A ``circle`` path gradient's outer circle is centred on the box and passes through
#: its corners -- unless the ``fillToRect`` point is as far out as a corner, when Word
#: widens it by this factor (measured: 1,023,056 EMU against the 1,006,001 of a
#: 1,799,590 x 899,795 box's half-diagonal, the point on its corner).
CIRCLE_CLEARANCE = 1023056 / 1006001


def office_gradient_ref(
    fill: m.GradientFill,
    context: SvgDefs,
    box: tuple[float, float, float, float],
    frame: ShapeFrame | None = None,
) -> str:
    """A gradient's paint server under Word's measured geometry (:mod:`.rules`), for a
    shape whose box is ``box`` in the element's user space; ``url(#id)``."""
    stops = _office_stops(fill.stops)
    x, y, width, height = box
    path = (fill.path or "circle") if fill.gradient_type == "radial" else None
    if path == "shape" and frame is not None and not frame.rectangular:
        # Rings of the outline: on an ellipse (measured) the box's inscribed ellipses, a
        # radial gradient over the box; any other outline is drawn so too.
        gradient_id = context.new_id("grad")
        left, top, right, bottom = fill.focus or (0.5, 0.5, 0.5, 0.5)
        context.add_def(
            f'<radialGradient id="{gradient_id}" cx="0.5" cy="0.5" r="0.5" '
            f'fx="{num((left + 1 - right) / 2)}" fy="{num((top + 1 - bottom) / 2)}">'
            + "".join(_stop_markup(position, color) for position, color in stops) + "</radialGradient>"
        )
        return f"url(#{gradient_id})"
    if path in ("rect", "shape"):
        return _rectangular_gradient_ref(fill, stops, context, box)
    gradient_id = context.new_id("grad")
    markup = "".join(_stop_markup(position, color) for position, color in stops)
    if fill.gradient_type == "radial":
        left, top, right, bottom = fill.focus or (0.5, 0.5, 0.5, 0.5)
        fx = x + width * (left + (1 - right)) / 2
        fy = y + height * (top + (1 - bottom)) / 2
        cx, cy = x + width / 2, y + height / 2
        radius = math.hypot(width / 2, height / 2)
        radius = max(radius, math.hypot(fx - cx, fy - cy) * CIRCLE_CLEARANCE)
        context.add_def(
            f'<radialGradient id="{gradient_id}" gradientUnits="userSpaceOnUse" cx="{num(cx)}" '
            f'cy="{num(cy)}" r="{num(radius)}" fx="{num(fx)}" fy="{num(fy)}">{markup}</radialGradient>'
        )
        return f"url(#{gradient_id})"

    angle = fill.angle
    if fill.rotate_with_shape is False and frame is not None:
        # Held to the page: undo the rotation, then the flips (the element's transform
        # rotates after flipping, so its inverse flips after unrotating).
        angle -= frame.rotation
        if frame.flip_h:
            angle = 180 - angle
        if frame.flip_v:
            angle = -angle
    radians = math.radians(angle)
    if fill.scaled:
        # The unit square's gradient stretched onto the box: its lines of equal colour
        # stretch with it, and the direction across them is theirs turned square.
        dx, dy = height * math.cos(radians), width * math.sin(radians)
    else:
        dx, dy = math.cos(radians), math.sin(radians)
    length = math.hypot(dx, dy) or 1.0
    dx, dy = dx / length, dy / length
    half = (width * abs(dx) + height * abs(dy)) / 2
    cx, cy = x + width / 2, y + height / 2
    context.add_def(
        f'<linearGradient id="{gradient_id}" gradientUnits="userSpaceOnUse" '
        f'x1="{num(cx - dx * half)}" y1="{num(cy - dy * half)}" '
        f'x2="{num(cx + dx * half)}" y2="{num(cy + dy * half)}">{markup}</linearGradient>'
    )
    return f"url(#{gradient_id})"


def _stop_markup(position: float, color: m.ResolvedColor) -> str:
    return (
        f'<stop offset="{num(position * 100)}%" stop-color="{color.hex}"'
        + (f' stop-opacity="{num(color.alpha)}"' if color.alpha < 1 else "")
        + "/>"
    )


def _office_stops(stops: list[m.GradientStop]) -> list[tuple[float, m.ResolvedColor]]:
    """The stops in position order (Word sorts them), opaque (Word's export draws a stop's
    ``alpha`` as nothing: the probe's 20% stop is solid ``0070C0``), and a two-stop 0-100%
    gradient written out as Word eases it (:data:`LINEAR_LIGHT_STOPS`)."""
    ordered = sorted(((stop.position, m.ResolvedColor(stop.color.hex)) for stop in stops), key=lambda item: item[0])
    if len(ordered) != 2 or ordered[0][0] != 0 or ordered[1][0] != 1:
        return ordered
    (_, first), (_, last) = ordered
    start = [(int(first.hex[k:k + 2], 16) / 255) ** LINEAR_LIGHT_GAMMA for k in (1, 3, 5)]
    end = [(int(last.hex[k:k + 2], 16) / 255) ** LINEAR_LIGHT_GAMMA for k in (1, 3, 5)]
    out = []
    for index in range(LINEAR_LIGHT_STOPS + 1):
        t = index / LINEAR_LIGHT_STOPS
        eased = (1 - math.cos(math.pi * t)) / 2
        channels = [(a + (b - a) * eased) ** (1 / LINEAR_LIGHT_GAMMA) for a, b in zip(start, end)]
        out.append((t, m.ResolvedColor("#" + "".join(f"{max(0, min(255, round(c * 255))):02x}" for c in channels))))
    return out


def _rectangular_gradient_ref(
    fill: m.GradientFill,
    stops: list[tuple[float, m.ResolvedColor]],
    context: SvgDefs,
    box: tuple[float, float, float, float],
) -> str:
    """A ``rect`` path gradient -- rectangular rings from the ``fillToRect`` rectangle
    (the first stop) out to the box's edges (the last) -- as a pattern the size of the
    box holding four trapezoids, each a linear gradient from its edge in to the
    rectangle.  Their seams run from the box's corners to the rectangle's, where the rings
    turn.  Word draws this as a picture; this is its geometry.  ``shape`` is drawn the
    same, which is Word's on a rectangle (the caller may give another shape a ``circle``)."""
    x, y, width, height = box
    left, top, right, bottom = fill.focus or (0.5, 0.5, 0.5, 0.5)
    fl, ft = width * left, height * top
    fr, fb = width * (1 - right), height * (1 - bottom)
    if fr < fl:
        fl = fr = (fl + fr) / 2
    if fb < ft:
        ft = fb = (ft + fb) / 2
    pattern_id = context.new_id("grad")
    markup = "".join(_stop_markup(position, color) for position, color in stops)
    parts = []
    middle = (fl + fr) / 2
    # The left and right halves first, whole, then the top and bottom trapezoids over
    # them: every seam is then an anti-aliased edge over a colour it matches, where four
    # trapezoids side by side leave a hairline of what is under them.
    for name, polygon, (x1, y1, x2, y2) in (
        ("l", ((0, 0), (middle, 0), (middle, height), (0, height)), (fl, 0, 0, 0)),
        ("r", ((middle, 0), (width, 0), (width, height), (middle, height)), (fr, 0, width, 0)),
        ("t", ((0, 0), (width, 0), (fr, ft), (fl, ft)), (0, ft, 0, 0)),
        ("b", ((0, height), (width, height), (fr, fb), (fl, fb)), (0, fb, 0, height)),
    ):
        if (x1, y1) == (x2, y2):
            continue
        gradient_id = f"{pattern_id}-{name}"
        parts.append(
            f'<linearGradient id="{gradient_id}" gradientUnits="userSpaceOnUse" x1="{num(x1)}" '
            f'y1="{num(y1)}" x2="{num(x2)}" y2="{num(y2)}">{markup}</linearGradient>'
            f'<polygon points="{" ".join(f"{num(px)},{num(py)}" for px, py in polygon)}" '
            f'fill="url(#{gradient_id})"/>'
        )
    first = stops[0][1]
    if fr > fl and fb > ft:
        parts.append(
            f'<rect x="{num(fl)}" y="{num(ft)}" width="{num(fr - fl)}" height="{num(fb - ft)}" '
            f'fill="{first.hex}"' + (f' fill-opacity="{num(first.alpha)}"' if first.alpha < 1 else "") + "/>"
        )
    context.add_def(
        f'<pattern id="{pattern_id}" patternUnits="userSpaceOnUse" x="{num(x)}" y="{num(y)}" '
        f'width="{num(width)}" height="{num(height)}">{"".join(parts)}</pattern>'
    )
    return f"url(#{pattern_id})"


# --------------------------------------------------------------------------------------
# Arrowheads as Word draws them (rules.py, ``arrowheads="office"``)
# --------------------------------------------------------------------------------------

#: ``a:headEnd`` / ``a:tailEnd`` ``@w`` and ``@len`` as multiples of the line's width.
ARROW_SIZE_FACTORS = {"sm": 2.0, "med": 3.0, "lg": 5.0}
#: The width a thinner line's arrowhead is sized by (measured at 1 pt: an ``sm`` head
#: 4 pt long, ``lg`` 10).
ARROW_MINIMUM_UNIT_PT = 2.0
#: Where a stealth head's notch is, as a fraction of its length from the tip.
STEALTH_NOTCH = 0.6


def render_arrowheads(
    outline: m.Outline | None,
    ends: tuple,
    *,
    dpi: float = DEFAULT_DPI,
) -> tuple[list[str], float, float]:
    """Word's arrowheads for an open path: ``ends`` is ``((x, y, dx, dy), (x, y, dx, dy))``,
    the path's first and last points with the unit direction pointing *out* of the path
    there (backwards along the first segment, forwards along the last).

    Returns the heads as SVG elements (their paint given, in the outline's colour), and how
    far to cut the path back at its start and its end so the line stops under the head
    rather than poking through its tip -- Word's shaft stops half a unit behind a
    triangle's base and at a stealth's middle; under a diamond or an oval it runs to the
    point, their centre.  Measured on Word (:mod:`.rules`); an ``arrow`` head, an open
    chevron stroked at the line's width, is drawn with its outer tip on the point.
    """
    if outline is None or (outline.head_end is None and outline.tail_end is None):
        return [], 0.0, 0.0
    color, alpha = "#000000", 1.0
    if isinstance(outline.fill, m.SolidFill):
        color, alpha = outline.fill.color.hex, outline.fill.color.alpha
    elif isinstance(outline.fill, m.GradientFill) and outline.fill.stops:
        color, alpha = outline.fill.stops[0].color.hex, outline.fill.stops[0].color.alpha
    opacity = f' fill-opacity="{num(alpha)}"' if alpha < 1 else ""
    width = emu_to_px(outline.width, dpi)
    unit = max(width, ARROW_MINIMUM_UNIT_PT * dpi / 72)
    elements: list[str] = []
    setbacks = []
    for endpoint, (px, py, dx, dy) in ((outline.head_end, ends[0]), (outline.tail_end, ends[1])):
        if endpoint is None or endpoint.type == "none":
            setbacks.append(0.0)
            continue
        length = ARROW_SIZE_FACTORS.get(endpoint.length, 3.0) * unit
        half = ARROW_SIZE_FACTORS.get(endpoint.width, 3.0) * unit / 2
        nx, ny = -dy, dx  # across the line

        def at(along: float, across: float) -> str:
            return f"{num(px + dx * along + nx * across)} {num(py + dy * along + ny * across)}"

        if endpoint.type == "triangle":
            elements.append(f'<path d="M {at(0, 0)} L {at(-length, half)} L {at(-length, -half)} Z" '
                            f'fill="{color}"{opacity}/>')
            setbacks.append(max(0.0, length - unit / 2))
        elif endpoint.type == "stealth":
            elements.append(f'<path d="M {at(0, 0)} L {at(-length, half)} L {at(-length * STEALTH_NOTCH, 0)} '
                            f'L {at(-length, -half)} Z" fill="{color}"{opacity}/>')
            setbacks.append(length / 2)
        elif endpoint.type == "diamond":
            elements.append(f'<path d="M {at(length / 2, 0)} L {at(0, half)} L {at(-length / 2, 0)} '
                            f'L {at(0, -half)} Z" fill="{color}"{opacity}/>')
            setbacks.append(0.0)
        elif endpoint.type == "oval":
            angle = math.degrees(math.atan2(dy, dx))
            elements.append(f'<ellipse cx="{num(px)}" cy="{num(py)}" rx="{num(length / 2)}" '
                            f'ry="{num(half)}" transform="rotate({num(angle)} {num(px)} {num(py)})" '
                            f'fill="{color}"{opacity}/>')
            setbacks.append(0.0)
        elif endpoint.type == "arrow":
            spread = math.atan2(half, length) or 1e-9
            inset = (width / 2) / math.sin(spread)
            stroke_opacity = f' stroke-opacity="{num(alpha)}"' if alpha < 1 else ""
            elements.append(
                f'<path d="M {at(-inset - length, half)} L {at(-inset, 0)} L {at(-inset - length, -half)}" '
                f'fill="none" stroke="{color}" stroke-width="{num(width)}" stroke-linecap="round" '
                f'stroke-linejoin="miter"{stroke_opacity}/>'
            )
            setbacks.append(inset + width / 2)
        else:
            setbacks.append(0.0)
    return elements, setbacks[0], setbacks[1]
