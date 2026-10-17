"""EMF+ records played into SVG ([MS-EMFPLUS]).

An EMF+ file is an EMF whose ``EMR_COMMENT`` records carry GDI+ drawing records.
Windows PowerPoint draws such a file from its EMF+ records only -- a dual file's GDI
records are the fallback for players without EMF+, and an EMF+-only file's GDI records
are not drawn at all -- except the GDI records that follow an ``EmfPlusGetDC``, which
are played until the next EMF+ record.  :mod:`.emf` routes the records; this module
keeps the GDI+ graphics state (world and page transforms, clip, the save stack and
containers, the 64-slot object table) and draws through the same :class:`~.gdi.Player`
as the GDI records, so both write one SVG whose user space is the reference device's
pixels.

**What Windows draws** (PowerPoint for Microsoft 365's PDF export and slide show of 22
made-up EMF+ files, round 7; :mod:`.gdi` lists the GDI measurements), followed here:

* EMF+ device pixels are the EMF's: the frame maps them as it maps GDI's (px 20 at
  19.95 pt, 180 at 179.56 pt of a 400 px frame in a 400 pt box);
* a pen's width is centred on the outline, its world-unit width scaled by the world
  transform (width 5 under scale 2: a 10 px band); a pixel-unit width is not scaled by it;
* caps: flat ends at the end point, square and triangle reach half the width past it,
  round a half-width disc; ``ArrowAnchor`` is a triangle twice the width across and
  ``sqrt(3)`` widths long with its tip on the end point, the line ending one width
  before it;
* joins: ``Miter`` past the miter limit is cut off at the limit (SVG ``miter-clip``),
  ``MiterClipped`` past it is bevelled (SVG ``miter``); the default limit is 10;
* dashes are multiples of the width -- ``Dash`` 3 and 1, ``Dot`` 1 and 1, ``DashDot``
  3 1 1 1, ``DashDotDot`` 3 1 1 1 1 1, a custom array its entries -- shifted by
  ``DashOffset`` widths; a round or triangle ``DashedLineCap`` is inside each dash's
  length;
* ``PenAlignmentInset`` puts a closed figure's whole stroke inside it; a compound
  array draws its bands across the width;
* ``FillPolygon`` and ``FillPath`` fill even-odd, ``FillClosedCurve`` nonzero with its
  winding flag; a cardinal spline's control points are a third of the tension times
  the chord of the neighbouring points (fitted to 0.2 px over three tensions);
* angles turn clockwise from the x axis;
* hatches are 8 x 8 device pixels in the fore colour over the back colour (a fully
  transparent back colour shows the slide through);
* a linear gradient runs along its rectangle's x axis through the brush transform and
  is **not repeated**: past its rectangle it keeps its end colours, whatever its wrap
  mode (Windows' PDF, ``Tile`` and ``TileFlipX`` alike), and its colours are the record's
  ``Reserved1`` and ``Reserved2`` (which GDI+ writes as the start and end colours again;
  Windows drew nothing where they were 0); blend factors and preset colours are stops
  (Windows' PDF ramps a ``[0 1 0]`` blend later than its factors, and drew preset
  colours green-yellow-green where its slide show drew red-yellow-green: the factors
  and the slide show are followed);
* a path gradient blends from its centre colour at the centre point to the surrounding
  colours on the boundary, triangle by triangle (each triangle of the centre and one
  boundary edge shaded between its corners) -- drawn here as a bitmap of the same
  shading, clipped to the shape, as Windows' PDF export draws it too;
* texture tiles start at the brush space's origin and are drawn sharp; every wrap mode
  but ``Clamp`` is a plain tile (``TileFlipXY`` drew as ``Tile``); ``Clamp`` draws the
  image once;
* the page transform's scale is honoured; its unit is read from the high byte of the
  record's flags, which is ``UnitWorld`` (no conversion) in every measured file: units
  written in the low byte were not converted by Windows (a rectangle drawn in inches
  came out in pixels);
* a ``BeginContainer`` maps its source rectangle onto its destination only with a page
  unit (the flags' high byte); with none -- as measured -- it saves the state as
  ``BeginContainerNoParams`` does;
* ``Save``/``Restore`` and containers restore transform and clip; ``SetClipRect`` is in
  world coordinates, through the transform in force; ``Replace``, ``Intersect`` and
  ``Exclude`` combine as the spec says;
* bitmaps' rows are top-down; ``DrawImagePoints`` maps the source rectangle's upper-left,
  upper-right and lower-left corners onto its three points.

Also measured (Windows' PDF of slides 23 to 29 but 26): the GDI records after an
``EmfPlusGetDC`` drawn until the next EMF+ record, and none after it; translucent colours
as opacity; ``SourceCopy`` blended like ``SourceOver``; bitmaps with alpha (ARGB, PARGB,
PNG) alike; ``DrawString`` -- the layout box moved a sixth of an em left and padded a
sixth of an em on either side (``Near`` text at the box's x, ``Center`` a sixth of an em
left of its centre, ``Far`` a third of an em in), clipped to the moved box, lines the
ascent and descent apart, the first baseline 0.97 of the ascent below the top, an aligned
block 0.12 em taller than its lines, ``NoWrap`` one line clipped; a gradient brush on text.
On screen (slides 23 and 26): a bitmap's source pixel i is centred on i, not i + 1/2,
and past the image transparency is sampled -- a nearest-neighbour image starts with a
half block and ends half a block early, a smoothed one (every other mode) fades out at
its right and bottom (the PDF draws every mode sharp and exact; the screen is followed);
``DrawDriverString`` with characters places each at its origin on the baseline, or from
the first with natural advances (its PDF export fails).  Antialiasing and text hints
are ignored.

Never raises: each record is played inside a guard, and what cannot be drawn is named in
:attr:`.gdi.Player.skipped`.
"""

from __future__ import annotations

import base64
import math
import struct
from dataclasses import dataclass, replace
from xml.sax.saxutils import escape

from . import dib, gdi
from .gdi import IDENTITY, Figure, Matrix, Player, Stop, apply, invert, mul, num, path_data, scale_of

#: Caps on the work a hostile EMF+ stream can force.
MAX_OBJECT_BYTES = 4 * 1024 * 1024
MAX_SAVES = 1_024
#: Pixels shaded for path gradients over one metafile (each is a few float operations
#: in Python), and the most for one gradient.
MAX_GRADIENT_PIXELS = 1_000_000
MAX_GRADIENT_IMAGE = 250_000
#: How deep a metafile drawn as an EMF+ image may nest further metafiles.
MAX_NESTING = 2

EMF_PLUS_HEADER = 0x4001
GET_DC = 0x4004

NAMES = {
    0x4001: "Header", 0x4002: "EndOfFile", 0x4003: "Comment", 0x4004: "GetDC", 0x4005: "MultiFormatStart",
    0x4006: "MultiFormatSection", 0x4007: "MultiFormatEnd", 0x4008: "Object", 0x4009: "Clear",
    0x400A: "FillRects", 0x400B: "DrawRects", 0x400C: "FillPolygon", 0x400D: "DrawLines",
    0x400E: "FillEllipse", 0x400F: "DrawEllipse", 0x4010: "FillPie", 0x4011: "DrawPie", 0x4012: "DrawArc",
    0x4013: "FillRegion", 0x4014: "FillPath", 0x4015: "DrawPath", 0x4016: "FillClosedCurve",
    0x4017: "DrawClosedCurve", 0x4018: "DrawCurve", 0x4019: "DrawBeziers", 0x401A: "DrawImage",
    0x401B: "DrawImagePoints", 0x401C: "DrawString", 0x401D: "SetRenderingOrigin", 0x401E: "SetAntiAliasMode",
    0x401F: "SetTextRenderingHint", 0x4020: "SetTextContrast", 0x4021: "SetInterpolationMode",
    0x4022: "SetPixelOffsetMode", 0x4023: "SetCompositingMode", 0x4024: "SetCompositingQuality",
    0x4025: "Save", 0x4026: "Restore", 0x4027: "BeginContainer", 0x4028: "BeginContainerNoParams",
    0x4029: "EndContainer", 0x402A: "SetWorldTransform", 0x402B: "ResetWorldTransform",
    0x402C: "MultiplyWorldTransform", 0x402D: "TranslateWorldTransform", 0x402E: "ScaleWorldTransform",
    0x402F: "RotateWorldTransform", 0x4030: "SetPageTransform", 0x4031: "ResetClip", 0x4032: "SetClipRect",
    0x4033: "SetClipPath", 0x4034: "SetClipRegion", 0x4035: "OffsetClip", 0x4036: "DrawDriverString",
    0x4037: "StrokeFillPath", 0x4038: "SerializableObject", 0x4039: "SetTSGraphics", 0x403A: "SetTSClip",
}

#: Records with nothing for an SVG to change: hints and qualities (Windows' slide show
#: antialiases whatever they say), and the comment.
_EVENODD_FILL = ' fill-rule="evenodd"'
_EVENODD_CLIP = ' clip-rule="evenodd"'

_NO_OP = {0x4003, 0x401E, 0x401F, 0x4020, 0x4022, 0x4024}

# UnitType
U_WORLD, U_DISPLAY, U_PIXEL, U_POINT, U_INCH, U_DOCUMENT, U_MM = range(7)

# Line caps and joins
CAP_FLAT, CAP_SQUARE, CAP_ROUND, CAP_TRIANGLE = 0, 1, 2, 3
CAP_NO_ANCHOR, CAP_SQUARE_ANCHOR, CAP_ROUND_ANCHOR, CAP_DIAMOND_ANCHOR, CAP_ARROW_ANCHOR = 0x10, 0x11, 0x12, 0x13, 0x14
CAP_CUSTOM = 0xFF
JOIN_MITER, JOIN_BEVEL, JOIN_ROUND, JOIN_MITER_CLIPPED = 0, 1, 2, 3
#: Dash patterns in pen widths (DashStyle 1..4), measured on Windows.
_DASHES = {1: (3, 1), 2: (1, 1), 3: (3, 1, 1, 1), 4: (3, 1, 1, 1, 1, 1)}

# Combine modes
C_REPLACE, C_INTERSECT, C_UNION, C_XOR, C_EXCLUDE, C_COMPLEMENT = range(6)

# Wrap modes
W_TILE, W_FLIP_X, W_FLIP_Y, W_FLIP_XY, W_CLAMP = range(5)

#: Hatch styles drawn exactly: their 8 x 8 tiles, one device pixel wide.
_H_HORIZONTAL = "M0 0h8v1h-8z"
_H_VERTICAL = "M0 0h1v8h-1z"
_H_DOWN = "".join(f"M{i} {i}h1v1h-1z" for i in range(8))
_H_UP = "".join(f"M{7 - i} {i}h1v1h-1z" for i in range(8))
_HATCHES = {0: _H_HORIZONTAL, 1: _H_VERTICAL, 2: _H_DOWN, 3: _H_UP, 4: _H_HORIZONTAL + _H_VERTICAL,
            5: _H_DOWN + _H_UP}
#: HatchStylePercent05 .. Percent90: the fore colour's share of each tile.
_PERCENT = {6: 0.05, 7: 0.10, 8: 0.20, 9: 0.25, 10: 0.30, 11: 0.40, 12: 0.50, 13: 0.60, 14: 0.70, 15: 0.75,
            16: 0.80, 17: 0.90}
#: Named hatches drawn as the plain hatch of their direction (approximately).
_LIKE = {18: 2, 19: 3, 20: 2, 21: 3, 22: 2, 23: 3, 24: 1, 25: 0, 26: 1, 27: 0, 28: 1, 29: 0, 30: 2, 31: 3,
         32: 0, 33: 1, 43: 4, 44: 5, 46: 5, 48: 4, 51: 5}


# --------------------------------------------------------------------------------------
# Colours
# --------------------------------------------------------------------------------------


def argb(value: int) -> tuple[str, float]:
    """An ARGB colour as ``#rrggbb`` and its opacity."""
    return "#%02X%02X%02X" % ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF), ((value >> 24) & 0xFF) / 255


def _channels(value: int) -> tuple[int, int, int, int]:
    return (value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF, (value >> 24) & 0xFF


def _lerp_argb(c0: int, c1: int, t: float) -> int:
    t = min(max(t, 0.0), 1.0)
    a, b = _channels(c0), _channels(c1)
    r, g, bl, al = (round(x + (y - x) * t) for x, y in zip(a, b))
    return (al << 24) | (r << 16) | (g << 8) | bl


def _stop(value: int) -> str:
    hexa, alpha = argb(value)
    return f' stop-color="{hexa}"' + (f' stop-opacity="{num(alpha)}"' if alpha < 1 else "")


def _fill(value: int, prop: str = "fill") -> str:
    hexa, alpha = argb(value)
    out = f' {prop}="{hexa}"'
    if alpha < 1:
        out += f' {prop}-opacity="{num(alpha)}"'
    return out


# --------------------------------------------------------------------------------------
# Objects
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Solid:
    color: int


@dataclass(frozen=True)
class Hatch:
    style: int
    fore: int
    back: int


@dataclass(frozen=True)
class Linear:
    rect: tuple
    start: int
    end: int
    matrix: Matrix
    #: ``(position, ARGB)`` stops along the rectangle's width.
    stops: tuple


@dataclass(frozen=True)
class PathGradient:
    center_color: int
    center: tuple
    surround: tuple
    #: The boundary, in brush space: a list of point lists (closed polygons).
    boundary: tuple
    matrix: Matrix
    #: ``(position, factor)`` from the boundary (0) to the centre (1), or ``None``.
    blend: tuple | None = None
    #: ``(position, ARGB)`` likewise, replacing both colours, or ``None``.
    preset: tuple | None = None
    focus: float = 0.0


@dataclass(frozen=True)
class Texture:
    image: "Image"
    wrap: int
    matrix: Matrix


@dataclass(frozen=True)
class Image:
    #: ``"bitmap"`` (``data`` is PNG, JPEG or GIF bytes of ``mime``) or ``"svg"`` (``data``
    #: is a drawn metafile's SVG document).
    kind: str
    data: bytes
    mime: str
    width: float
    height: float
    #: The bitmap with a transparent column and row after its last: what Windows samples
    #: past the image (PNG), or ``None`` where it could not be made.
    padded: bytes | None = None


@dataclass(frozen=True)
class Pen:
    width: float = 1.0
    unit: int = U_WORLD
    brush: object = Solid(0xFF000000)
    start_cap: int = CAP_FLAT
    end_cap: int = CAP_FLAT
    join: int = JOIN_MITER
    miter: float = 10.0
    dash: int = 0
    dash_cap: int = CAP_FLAT
    dash_offset: float = 0.0
    dash_array: tuple = ()
    align: int = 0
    compound: tuple = ()
    matrix: Matrix = IDENTITY


@dataclass(frozen=True)
class Path:
    #: Subpaths in world coordinates.
    figures: tuple


@dataclass(frozen=True)
class Region:
    node: tuple


@dataclass(frozen=True)
class FontObj:
    em: float
    unit: int
    style: int
    family: str


@dataclass(frozen=True)
class StringFormat:
    flags: int = 0
    align: int = 0
    line_align: int = 0
    leading: float = 0.0
    trailing: float = 0.0


@dataclass(frozen=True)
class Other:
    """An object the player keeps a slot for and never draws with (image attributes,
    custom line caps), or one it could not read."""

    what: str


# --------------------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Clip:
    """A clip in device coordinates: the SVG ``clipPath`` that draws it, and -- when it
    is one plain union of figures -- those figures, for a later combination."""

    cid: str
    parts: tuple | None = None  # ((figures, evenodd), ...)


@dataclass(frozen=True)
class State:
    world: Matrix = IDENTITY
    page_scale: float = 1.0
    page_unit: int = U_PIXEL
    #: The container's frame: world-and-page space to device space.
    base: Matrix = IDENTITY
    clip: Clip | None = None
    base_clip: Clip | None = None
    interpolation: int = 0
    compositing: int = 0
    origin: tuple = (0.0, 0.0)


# --------------------------------------------------------------------------------------
# Reading helpers
# --------------------------------------------------------------------------------------


class _Data:
    """A bounds-checked little-endian reader over one record's data."""

    __slots__ = ("b", "at")

    def __init__(self, data: bytes, at: int = 0):
        self.b = data
        self.at = at

    def take(self, fmt: str):
        values = struct.unpack_from("<" + fmt, self.b, self.at)
        self.at += struct.calcsize("<" + fmt)
        return values

    def u32(self) -> int:
        return self.take("I")[0]

    def i32(self) -> int:
        return self.take("i")[0]

    def f32(self) -> float:
        value = self.take("f")[0]
        if not math.isfinite(value):
            raise ValueError("not a finite number")
        return value

    def floats(self, n: int) -> list[float]:
        if n < 0 or self.at + 4 * n > len(self.b):
            raise ValueError("past the record")
        values = list(struct.unpack_from(f"<{n}f", self.b, self.at))
        self.at += 4 * n
        if not all(math.isfinite(v) for v in values):
            raise ValueError("not a finite number")
        return values

    def bytes(self, n: int) -> bytes:
        if n < 0 or self.at + n > len(self.b):
            raise ValueError("past the record")
        out = self.b[self.at : self.at + n]
        self.at += n
        return out

    def left(self) -> int:
        return len(self.b) - self.at


def _matrix(d: _Data) -> Matrix:
    return tuple(d.floats(6))


def _count(d: _Data, size: int) -> int:
    n = d.u32()
    if n * size > d.left():
        raise ValueError("count runs past the record")
    return n


def _points(d: _Data, count: int, *, compressed: bool, relative: bool = False) -> list[tuple[float, float]]:
    """``count`` points: floats, 16-bit integers (``C``), or relative ``EmfPlusPointR``s."""
    if relative:
        out, x, y = [], 0.0, 0.0
        for _ in range(count):
            x += _int_r(d)
            y += _int_r(d)
            out.append((x, y))
        return out
    if compressed:
        if count * 4 > d.left():
            raise ValueError("past the record")
        flat = d.take(f"{2 * count}h")
    else:
        flat = d.floats(2 * count)
    return list(zip(flat[0::2], flat[1::2]))


def _int_r(d: _Data) -> int:
    """``EmfPlusInteger7`` or ``EmfPlusInteger15``."""
    first = d.take("B")[0]
    if first & 0x80:
        second = d.take("B")[0]
        value = ((first & 0x7F) << 8) | second
        return value - 0x8000 if value & 0x4000 else value
    return first - 0x80 if first & 0x40 else first


def _rects(d: _Data, count: int, compressed: bool) -> list[tuple[float, float, float, float]]:
    if compressed:
        if count * 8 > d.left():
            raise ValueError("past the record")
        flat = d.take(f"{4 * count}h")
    else:
        flat = d.floats(4 * count)
    return [tuple(flat[i : i + 4]) for i in range(0, len(flat), 4)]


def _rect_figure(x, y, w, h) -> Figure:
    return gdi.rect_figure(x, y, x + w, y + h)


def _param(angle: float, rx: float, ry: float) -> float:
    """The ellipse's parametric angle for a geometric one (GDI+ measures arcs as the
    angle of the ray from the centre)."""
    if not rx or not ry:
        return angle
    return math.atan2(math.sin(angle) * rx, math.cos(angle) * ry)


def _arc(x, y, w, h, start_deg, sweep_deg) -> tuple[tuple, list[tuple]]:
    """The start point and Béziers of an arc of the ellipse in ``(x, y, w, h)``."""
    rx, ry = w / 2, h / 2
    cx, cy = x + rx, y + ry
    sweep_deg = max(min(sweep_deg, 360.0), -360.0)
    a0 = math.radians(start_deg)
    a1 = math.radians(start_deg + sweep_deg)
    t0 = _param(a0, abs(rx), abs(ry))
    t1 = _param(a1, abs(rx), abs(ry))
    sweep = t1 - t0
    full = math.radians(sweep_deg)
    # Keep the parametric sweep on the side and the number of turns the geometric one has.
    while full > 0 and sweep < 0:
        sweep += 2 * math.pi
    while full < 0 and sweep > 0:
        sweep -= 2 * math.pi
    if abs(sweep_deg) >= 360:
        sweep = math.copysign(2 * math.pi, sweep_deg)
    start = (cx + rx * math.cos(t0), cy + ry * math.sin(t0))
    return start, gdi.arc_segments(cx, cy, rx, ry, t0, sweep)


def _cardinal(points, tension: float, closed: bool) -> list[tuple]:
    """Béziers through ``points`` (a cardinal spline): each control point a third of the
    tension times the chord of its neighbours from its point (fitted to Windows)."""
    n = len(points)
    k = tension / 3
    out = []
    last = n if closed else n - 1
    for i in range(last):
        p0, p1 = points[i], points[(i + 1) % n]
        if closed:
            pm, p2 = points[(i - 1) % n], points[(i + 2) % n]
        else:
            pm, p2 = points[max(i - 1, 0)], points[min(i + 2, n - 1)]
        c1 = (p0[0] + k * (p1[0] - pm[0]), p0[1] + k * (p1[1] - pm[1]))
        c2 = (p1[0] - k * (p2[0] - p0[0]), p1[1] - k * (p2[1] - p0[1]))
        out.append((*c1, *c2, *p1))
    return out


def _flatten(fig: Figure, steps: int = 8) -> list[tuple[float, float]]:
    pts = [fig.start]
    for seg in fig.segments:
        if len(seg) == 2:
            pts.append(seg)
        else:
            x0, y0 = pts[-1]
            for j in range(1, steps + 1):
                t = j / steps
                u = 1 - t
                pts.append((u * u * u * x0 + 3 * u * u * t * seg[0] + 3 * u * t * t * seg[2] + t * t * t * seg[4],
                            u * u * u * y0 + 3 * u * u * t * seg[1] + 3 * u * t * t * seg[3] + t * t * t * seg[5]))
    return pts


def _translate(x, y) -> Matrix:
    return (1.0, 0.0, 0.0, 1.0, x, y)


# --------------------------------------------------------------------------------------
# The EMF+ player
# --------------------------------------------------------------------------------------


class PlusPlayer:
    """The GDI+ graphics state, drawing into a :class:`~.gdi.Player`."""

    def __init__(self, player: Player, *, nesting: int = 0):
        self.p = player
        self.state = State()
        self.objects: dict[int, object] = {}
        self.saves: dict[int, tuple] = {}  # stack index -> (order, state)
        self.containers: list[tuple[int, State]] = []
        self.order = 0
        self.partial: dict[int, tuple[int, int, bytearray]] = {}  # id -> (type, total, data)
        self.dpi = (96.0, 96.0)
        self.get_dc = False
        self.drawn_before = player.drawn
        self.nesting = nesting
        self.gradient_pixels = 0
        self._everything_cache: str | None = None

    @property
    def drew(self) -> bool:
        return self.p.drawn > self.drawn_before

    # ---- records ------------------------------------------------------------------------

    def play(self, data: bytes) -> None:
        """The EMF+ records of one ``EMR_COMMENT``'s data (after its identifier)."""
        offset = 0
        p = self.p
        while offset + 12 <= len(data):
            kind, flags, size, data_size = struct.unpack_from("<HHII", data, offset)
            if size < 12 or offset + size > len(data):
                p.skip("an EMF+ record whose size runs past its comment")
                return
            body = data[offset + 12 : offset + 12 + min(data_size, size - 12)]
            offset += size
            self.get_dc = kind == GET_DC
            self.record(kind, flags, body)

    def record(self, kind: int, flags: int, data: bytes) -> None:
        name = "EmfPlus" + NAMES.get(kind, f"Record 0x{kind:04X}")
        if kind in _NO_OP or kind in (EMF_PLUS_HEADER, 0x4002, GET_DC):
            if kind == EMF_PLUS_HEADER and len(data) >= 16:
                _version, _flags, dx, dy = struct.unpack_from("<IIII", data, 0)
                if 0 < dx < 100_000 and 0 < dy < 100_000:
                    self.dpi = (float(dx), float(dy))
            return
        handler = _HANDLERS.get(kind)
        if handler is None:
            self.p.skip(name)
            return
        try:
            self.p.flush()
            if handler(self, flags, _Data(data)) is False:
                self.p.skip(name)
        except Stop:
            raise
        except Exception:  # a record that cannot be read is named, never fatal
            self.p.skip(name + " (unreadable)")

    # ---- transforms ---------------------------------------------------------------------

    def matrix(self) -> Matrix:
        """World to device: the world transform, the page scale, the container's frame."""
        s = self.state
        page = (s.page_scale * self._unit(s.page_unit, 0), 0.0, 0.0, s.page_scale * self._unit(s.page_unit, 1), 0.0, 0.0)
        return mul(mul(s.world, page), s.base)

    def _unit(self, unit: int, axis: int = 0) -> float:
        """Device pixels per unit (``UnitWorld`` and ``UnitDisplay`` as pixels)."""
        dpi = self.dpi[axis]
        return {U_POINT: dpi / 72, U_INCH: dpi, U_DOCUMENT: dpi / 300, U_MM: dpi / 25.4}.get(unit, 1.0)

    def set(self, **changes) -> None:
        self.state = replace(self.state, **changes)

    # ---- painting -----------------------------------------------------------------------

    def _brush(self, flags: int, value: int):
        """The brush a record names: an ARGB colour with the ``S`` flag, else an object."""
        if flags & 0x8000:
            return Solid(value)
        brush = self.objects.get(value & 0xFF) if value < 64 else None
        return brush if isinstance(brush, (Solid, Hatch, Linear, PathGradient, Texture)) else None

    def _pen(self, index: int) -> Pen | None:
        pen = self.objects.get(index & 0xFF)
        return pen if isinstance(pen, Pen) else None

    def _write(self, text: str) -> None:
        clip = self.state.clip
        self.p._write(text, clip=clip.cid if clip else None)

    def _note_compositing(self, brush) -> None:
        """``SourceCopy`` is drawn as ``SourceOver``, as Windows draws it (slide 27: a
        50 % red over stripes blended alike in both modes)."""

    def paint_layers(self, brush, m: Matrix, prop: str = "fill") -> list[str] | None:
        """The ``fill`` (or ``stroke``) attributes of ``brush`` for a shape in the space of
        ``m``, one per painted layer; ``None`` for a path gradient, which is drawn as a
        bitmap."""
        if isinstance(brush, Solid):
            return [_fill(brush.color, prop)] if argb(brush.color)[1] > 0 else []
        if isinstance(brush, Hatch):
            layers = []
            if argb(brush.back)[1] > 0:
                layers.append(_fill(brush.back, prop))
            style = brush.style
            if style in _HATCHES or style in _LIKE:
                if style in _LIKE:
                    self.p.skip(f"EmfPlus hatch style {style} (drawn as the plain hatch of its direction)")
                layers.append(f' {prop}="url(#{self._hatch(brush, m)})"')
            else:
                # A percentage (or another named pattern): the fore colour over the back
                # at its share of the tile.
                if style not in _PERCENT:
                    self.p.skip(f"EmfPlus hatch style {style} (drawn as its mean colour)")
                hexa, alpha = argb(brush.fore)
                layers.append(f' {prop}="{hexa}" {prop}-opacity="{num(alpha * _PERCENT.get(style, 0.5))}"')
            return layers
        if isinstance(brush, Linear):
            return [f' {prop}="url(#{self._linear(brush)})"']
        if isinstance(brush, Texture):
            if brush.wrap == W_CLAMP and prop == "fill":
                return None  # one image, clipped to the shape
            if brush.wrap == W_CLAMP:
                self.p.skip("EmfPlus Clamp texture pens (drawn tiled)")
            return [f' {prop}="url(#{self._texture(brush)})"']
        if isinstance(brush, PathGradient):
            if prop == "stroke":
                self.p.skip("EmfPlus path gradient pens (drawn in their centre colour)")
                return [_fill(brush.center_color, prop)]
            return None
        return []

    def _hatch(self, brush: Hatch, m: Matrix) -> str:
        """An 8 x 8 device-pixel tile, from the rendering origin."""
        style = brush.style
        d = _HATCHES.get(style) or _HATCHES[_LIKE.get(style, 0)]
        ox, oy = self.state.origin
        key = ("H", d, brush.fore, m, ox, oy)
        cached = self.p._patterns.get(key)
        if cached:
            return cached
        pid = self.p._id("h")
        inverse = invert(m) or IDENTITY
        transform = mul(_translate(ox, oy), inverse)
        self.p._def(f'<pattern id="{pid}" patternUnits="userSpaceOnUse" width="8" height="8" '
                    f'patternTransform="matrix({" ".join(num(v) for v in transform)})">'
                    f'<path d="{d}"{_fill(brush.fore)}/></pattern>')
        self.p._patterns[key] = pid
        return pid

    def _linear(self, brush: Linear) -> str:
        key = ("L", brush)
        cached = self.p._patterns.get(key)
        if cached:
            return cached
        gid = self.p._id("g")
        x, y, w, _h = brush.rect
        stops = "".join(f'<stop offset="{num(min(max(pos, 0.0), 1.0))}"{_stop(c)}/>' for pos, c in brush.stops)
        transform = "" if brush.matrix == IDENTITY else f' gradientTransform="matrix({" ".join(num(v) for v in brush.matrix)})"'
        self.p._def(f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="{num(x)}" y1="{num(y)}" '
                    f'x2="{num(x + w)}" y2="{num(y)}"{transform}>{stops}</linearGradient>')
        self.p._patterns[key] = gid
        return gid

    def _texture(self, brush: Texture) -> str:
        key = ("T", id(brush.image), brush.wrap, brush.matrix)
        cached = self.p._patterns.get(key)
        if cached:
            return cached
        pid = self.p._id("p")
        img = brush.image
        w, h = img.width, img.height
        # Windows tiles every wrap mode but Clamp alike (TileFlipXY drew as Tile) and
        # draws the tiles' pixels sharp.
        pw, ph = w, h
        content = _image_markup(img, 0, 0, w, h, 5)
        transform = "" if brush.matrix == IDENTITY else f' patternTransform="matrix({" ".join(num(v) for v in brush.matrix)})"'
        self.p._def(f'<pattern id="{pid}" patternUnits="userSpaceOnUse" width="{num(pw)}" height="{num(ph)}"'
                    f'{transform}>{content}</pattern>')
        self.p._patterns[key] = pid
        return pid

    def fill(self, figures: list[Figure], brush, *, evenodd: bool = False) -> None:
        """Fill world-space figures with a brush, in the current transform and clip."""
        figures = [f for f in figures if f is not None]
        if not figures or brush is None:
            return
        self._note_compositing(brush)
        m = self.matrix()
        d = path_data(figures)
        transform = Player._transform(m)
        rule = ' fill-rule="evenodd"' if evenodd else ""
        layers = self.paint_layers(brush, m)
        if layers is None and isinstance(brush, Texture):
            self._clamped(brush, figures, m, evenodd)
            return
        if layers is None:
            self._path_gradient(brush, figures, m, evenodd)
            return
        for layer in layers:
            self._write(f'<path d="{d}"{transform}{layer}{rule}/>')

    # ---- pens ---------------------------------------------------------------------------

    def _pen_width(self, pen: Pen, m: Matrix) -> float:
        """The pen's width in the shape's units (the space of ``m``), at least one device
        pixel."""
        scale = scale_of(m) or 1.0
        width = pen.width * scale_of(pen.matrix) if pen.matrix != IDENTITY else pen.width
        if pen.unit != U_WORLD:
            width = width * self._unit(pen.unit) / scale
        return max(width, 1 / scale)

    def stroke(self, figures: list[Figure], pen: Pen | None) -> None:
        """Stroke world-space figures with a pen, in the current transform and clip."""
        figures = [f for f in figures if f is not None]
        if not figures or pen is None:
            return
        self._note_compositing(pen.brush)
        m = self.matrix()
        width = self._pen_width(pen, m)
        layers = self.paint_layers(pen.brush, m, "stroke")
        if not layers:
            return
        paint = layers[-1]
        inset = pen.align == 1 and all(f.closed for f in figures)
        drawn_width = 2 * width if inset else width
        attrs = paint + f' stroke-width="{num(drawn_width)}"'
        open_figures = [f for f in figures if not f.closed]
        decorate = pen.start_cap != pen.end_cap or pen.start_cap not in (CAP_FLAT, CAP_SQUARE, CAP_ROUND)
        cap = {CAP_SQUARE: "square", CAP_ROUND: "round"}.get(pen.start_cap, "butt") if not decorate else "butt"
        if pen.start_cap == CAP_CUSTOM or pen.end_cap == CAP_CUSTOM:
            self.p.skip("EmfPlus custom line caps (drawn flat)")
        original = figures
        if pen.start_cap == CAP_ARROW_ANCHOR or pen.end_cap == CAP_ARROW_ANCHOR:
            figures = [_shortened(f, width if pen.start_cap == CAP_ARROW_ANCHOR else 0.0,
                                  width if pen.end_cap == CAP_ARROW_ANCHOR else 0.0) if not f.closed else f
                       for f in figures]
        dashes = None
        if pen.dash in _DASHES:
            dashes = [v * width for v in _DASHES[pen.dash]]
        elif pen.dash == 5 and pen.dash_array:
            dashes = [max(v, 0.0) * width for v in pen.dash_array]
        flat_ends = False
        if dashes and sum(dashes) > 0:
            flat_ends = pen.dash_cap in (CAP_ROUND, CAP_TRIANGLE) and bool(open_figures)
            if pen.dash_cap == CAP_ROUND:
                cap = "round"
                dashes = [max(v - width, 0.0) if i % 2 == 0 else v + width for i, v in enumerate(dashes)]
            elif pen.dash_cap == CAP_TRIANGLE:
                # A triangle dash cap, drawn as a flat end half as long (the same area).
                self.p.skip("EmfPlus triangle dash caps (drawn flat, half as long)")
                cap = "butt"
                dashes = [max(v - width / 2, 0.0) if i % 2 == 0 else v + width / 2 for i, v in enumerate(dashes)]
            else:
                cap = "butt"
            if len(dashes) % 2:
                dashes = dashes * 2
            attrs += f' stroke-dasharray="{" ".join(num(v) for v in dashes)}"'
            if pen.dash_offset:
                attrs += f' stroke-dashoffset="{num(pen.dash_offset * width)}"'
        if cap != "butt":
            attrs += f' stroke-linecap="{cap}"'
        if pen.join == JOIN_ROUND:
            attrs += ' stroke-linejoin="round"'
        elif pen.join == JOIN_BEVEL:
            attrs += ' stroke-linejoin="bevel"'
        else:
            if pen.join == JOIN_MITER:
                attrs += ' stroke-linejoin="miter-clip"'
            attrs += f' stroke-miterlimit="{num(max(pen.miter, 1.0))}"'
        d = path_data(figures)
        transform = Player._transform(m)
        compound = _bands(pen.compound)
        if pen.compound and compound is None:
            self.p.skip("EmfPlus compound pens that are not symmetric (drawn as one stroke)")
        if inset:
            cid = self.p._id("c")
            self.p._def(f'<clipPath id="{cid}" clipPathUnits="userSpaceOnUse"><path d="{d}"/></clipPath>')
            body = f'<path d="{d}" fill="none"{attrs} clip-path="url(#{cid})"/>'
        else:
            body = f'<path d="{d}" fill="none"{attrs}/>'
        if compound:
            body = self._compound(body, d, attrs, drawn_width, compound, figures)
        if flat_ends:
            body = self._flat_ends(body, d, attrs, drawn_width, figures)
        self._write(f"<g{transform}>{body}</g>" if transform else body)
        if decorate and open_figures:
            self._caps(original, pen, width, m, layers)

    def _flat_ends(self, body: str, d: str, attrs: str, width: float, figures) -> str:
        """Round dash caps end flat at the line's own ends (measured): the dashes masked
        by the undashed line with flat ends."""
        mid = self.p._id("k")
        joins = "".join(" " + a for a in attrs.split(" ") if a.startswith(("stroke-linejoin", "stroke-miterlimit")))
        self.p._def(f'<mask id="{mid}" maskUnits="userSpaceOnUse" {_region(figures, width)}><path d="{d}" '
                    f'fill="none" stroke="#FFFFFF" stroke-width="{num(width)}"{joins}/></mask>')
        return f'<g mask="url(#{mid})">{body}</g>'

    def _compound(self, body: str, d: str, attrs: str, width: float, bands: list[float], figures) -> str:
        """A compound pen: the stroke masked by nested centred strokes, white and black in
        turn, one for each edge of its bands (exact for a symmetric array)."""
        mid = self.p._id("k")
        region = _region(figures, width)
        base = attrs.split(' stroke-width="', 1)
        rest = base[1].split('"', 1)[1] if len(base) > 1 else ""
        rest = rest.replace(' stroke-dasharray', ' data-d').replace(' stroke-dashoffset', ' data-o')
        strokes = []
        for i, edge in enumerate(bands):
            colour = "#FFFFFF" if i % 2 == 0 else "#000000"
            strokes.append(f'<path d="{d}" fill="none" stroke="{colour}" stroke-width="{num((1 - 2 * edge) * width)}"{rest}/>')
        self.p._def(f'<mask id="{mid}" maskUnits="userSpaceOnUse" {region}>{"".join(strokes)}</mask>')
        return f'<g mask="url(#{mid})">{body}</g>'

    def _caps(self, figures, pen: Pen, width: float, m: Matrix, layers) -> None:
        """Line caps SVG has no ``stroke-linecap`` for (and differing start and end caps),
        as filled shapes at the ends of the open figures."""
        shapes = []
        for fig in figures:
            if fig.closed:
                continue
            ends = _ends(fig)
            if ends is None:
                continue
            (p0, d0), (p1, d1) = ends
            for cap, point, direction in ((pen.start_cap, p0, d0), (pen.end_cap, p1, d1)):
                shape = _cap_shape(cap, point, direction, width)
                if shape is not None:
                    shapes.append(shape)
        if not shapes:
            return
        transform = Player._transform(m)
        paint = layers[-1].replace(' stroke="', ' fill="').replace(' stroke-opacity="', ' fill-opacity="')
        self._write(f'<path d="{path_data(shapes)}"{transform}{paint}/>')

    def _clamped(self, brush: Texture, figures, m: Matrix, evenodd: bool) -> None:
        """A ``Clamp`` texture: the image once, through the brush transform, clipped to
        the shape."""
        cid = self.p._id("c")
        rule = ' clip-rule="evenodd"' if evenodd else ""
        self.p._def(f'<clipPath id="{cid}" clipPathUnits="userSpaceOnUse"><path d="{path_data(figures)}"{rule}/>'
                    f'</clipPath>')
        image = _image_markup(brush.image, 0, 0, brush.image.width, brush.image.height, 5)
        inner = f'<g clip-path="url(#{cid})"><g{Player._transform(brush.matrix)}>{image}</g></g>'
        transform = Player._transform(m)
        self._write(f"<g{transform}>{inner}</g>" if transform else inner)

    # ---- path gradients -------------------------------------------------------------------

    def _path_gradient(self, brush: PathGradient, figures, m: Matrix, evenodd: bool) -> None:
        """A path gradient, shaded triangle by triangle into a bitmap in device pixels and
        clipped to the shape (a faithful approximation: Windows' PDF export does the same)."""
        bm = mul(brush.matrix, m)
        polygons = [[apply(bm, *pt) for pt in poly] for poly in brush.boundary if len(poly) >= 3]
        if not polygons:
            return
        centre = apply(bm, *brush.center)
        shape = [f.mapped(m) for f in figures]
        sx = [x for f in shape for x, _ in _flatten(f, 4)]
        sy = [y for f in shape for _, y in _flatten(f, 4)]
        bx = [x for poly in polygons for x, _ in poly]
        by = [y for poly in polygons for _, y in poly]
        cx, cy, cw, ch = self.p.canvas
        x0 = max(math.floor(max(min(sx), min(bx), cx)), -1_000_000)
        y0 = max(math.floor(max(min(sy), min(by), cy)), -1_000_000)
        x1 = min(math.ceil(min(max(sx), max(bx), cx + cw)), 1_000_000)
        y1 = min(math.ceil(min(max(sy), max(by), cy + ch)), 1_000_000)
        if x1 <= x0 or y1 <= y0:
            return
        area = (x1 - x0) * (y1 - y0)
        # One sample a device pixel, as Windows' own bitmap of it; fewer for a big one.
        k = 1.0 if area <= MAX_GRADIENT_IMAGE else math.sqrt(MAX_GRADIENT_IMAGE / area)
        pw, ph = max(1, int((x1 - x0) * k)), max(1, int((y1 - y0) * k))
        if self.gradient_pixels + pw * ph > MAX_GRADIENT_PIXELS:
            self.p.skip("EmfPlus path gradients beyond the shading cap (drawn in their centre colour)")
            self._write(f'<path d="{path_data(figures)}"{Player._transform(m)}{_fill(brush.center_color)}'
                        f'{_EVENODD_FILL if evenodd else ""}/>')
            return
        self.gradient_pixels += pw * ph
        rgba = _shade(brush, polygons, centre, x0, y0, pw, ph, (x1 - x0) / pw, (y1 - y0) / ph)
        png = dib.encode_png(pw, ph, bytes(rgba), has_alpha=True)
        cid = self.p._id("c")
        rule = ' clip-rule="evenodd"' if evenodd else ""
        self.p._def(f'<clipPath id="{cid}" clipPathUnits="userSpaceOnUse"><path d="{path_data(figures)}"'
                    f'{Player._transform(m)}{rule}/></clipPath>')
        href = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        self._write(f'<g clip-path="url(#{cid})"><image x="{num(x0)}" y="{num(y0)}" width="{num(x1 - x0)}" '
                    f'height="{num(y1 - y0)}" preserveAspectRatio="none" href="{href}"/></g>')

    # ---- clipping ---------------------------------------------------------------------------

    def _everything(self) -> list[Figure]:
        x, y, w, h = self.p.canvas
        margin = 4 * max(w, h, 1.0) + 100000
        return [gdi.rect_figure(x - margin, y - margin, x + w + margin, y + h + margin)]

    def _clip_of(self, parts, parent: Clip | None) -> Clip:
        """A clipPath of the union of ``parts`` (device figures and their rule), inside
        ``parent``."""
        cid = self.p._id("c")
        chained = f' clip-path="url(#{parent.cid})"' if parent else ""
        children = "".join(f'<path d="{path_data(list(figs)) or "M0 0Z"}"{_EVENODD_CLIP if eo else ""}/>'
                           for figs, eo in parts) or '<path d="M0 0Z"/>'
        self.p._def(f'<clipPath id="{cid}" clipPathUnits="userSpaceOnUse"{chained}>{children}</clipPath>')
        return Clip(cid, None if parent else tuple(parts))

    def combine(self, figures: list[Figure] | None, mode: int, *, evenodd: bool = True) -> bool:
        """Combine the clip with device-space figures (``None``: the infinite region)."""
        current = self.state.clip
        base = self.state.base_clip
        if figures is None:  # infinite
            if mode in (C_REPLACE, C_UNION):
                self.set(clip=base)
            elif mode == C_EXCLUDE:
                self.set(clip=self._clip_of([((), False)], None))
            elif mode == C_XOR or mode == C_COMPLEMENT:
                return self.combine_inverse(current, mode)
            return True
        new = (tuple(figures), evenodd)
        if mode == C_REPLACE:
            self.set(clip=self._clip_of([new], base))
            return True
        if mode == C_INTERSECT:
            self.set(clip=self._clip_of([new], current))
            return True
        if mode == C_EXCLUDE:
            self.set(clip=self._clip_of([(tuple(self._everything()) + tuple(figures), True)], current))
            return True
        if mode == C_UNION:
            if current is None:
                return True
            if current.parts is not None:
                self.set(clip=self._clip_of(list(current.parts) + [new], None))
                return True
            return False
        if mode == C_XOR:
            if current is None:
                self.set(clip=self._clip_of([(tuple(self._everything()) + tuple(figures), True)], None))
                return True
            if current.parts is not None and len(current.parts) == 1:
                figs, _ = current.parts[0]
                self.set(clip=self._clip_of([(tuple(figs) + tuple(figures), True)], None))
                return True
            return False
        if mode == C_COMPLEMENT:
            if current is None:
                self.set(clip=self._clip_of([((), False)], None))
                return True
            if current.parts is not None and len(current.parts) == 1:
                figs, _ = current.parts[0]
                outside = self._clip_of([(tuple(self._everything()) + tuple(figs), True)], None)
                self.set(clip=self._clip_of([new], outside))
                return True
            return False
        return False

    def combine_inverse(self, current, mode) -> bool:
        if current is None:
            self.set(clip=self._clip_of([((), False)], None))
            return True
        if current.parts is not None and len(current.parts) == 1:
            figs, _ = current.parts[0]
            self.set(clip=self._clip_of([(tuple(self._everything()) + tuple(figs), True)], None))
            return True
        return False

    def region_figures(self, node, m: Matrix):
        """A region node as ``("paths", [(figures, evenodd)])`` (a union), ``("inf",)`` or
        ``None`` where it is not one plain union."""
        kind = node[0]
        if kind == "rect":
            x, y, w, h = node[1]
            return ("paths", [((_rect_figure(x, y, w, h).mapped(m),), False)])
        if kind == "path":
            return ("paths", [(tuple(f.mapped(m) for f in node[1]), True)])
        if kind == "empty":
            return ("paths", [])
        if kind == "inf":
            return ("inf",)
        if kind == "or":
            a, b = self.region_figures(node[1], m), self.region_figures(node[2], m)
            if a is None or b is None:
                return None
            if a[0] == "inf" or b[0] == "inf":
                return ("inf",)
            return ("paths", a[1] + b[1])
        return None

    def set_clip_region(self, node, mode: int, m: Matrix) -> bool:
        """Combine the clip with a region: built node by node into chained clipPaths."""
        plain = self.region_figures(node, m)
        if plain is not None:
            if plain[0] == "inf":
                return self.combine(None, mode)
            parts = plain[1]
            if mode == C_INTERSECT or mode == C_REPLACE:
                parent = self.state.clip if mode == C_INTERSECT else self.state.base_clip
                self.set(clip=self._clip_of(parts or [((), False)], parent))
                return True
            if len(parts) == 1:
                return self.combine(list(parts[0][0]), mode, evenodd=parts[0][1])
            if not parts:
                return self.combine([gdi.rect_figure(0, 0, 0, 0)], mode)
            return False
        if node[0] == "and" and mode in (C_REPLACE, C_INTERSECT):
            if mode == C_REPLACE:
                self.set(clip=self.state.base_clip)
            return self.set_clip_region(node[1], C_INTERSECT, m) and self.set_clip_region(node[2], C_INTERSECT, m)
        if node[0] == "exclude" and mode in (C_REPLACE, C_INTERSECT):
            if mode == C_REPLACE:
                self.set(clip=self.state.base_clip)
            if not self.set_clip_region(node[1], C_INTERSECT, m):
                return False
            right = self.region_figures(node[2], m)
            if right is None or right[0] == "inf":
                return right is not None and self.combine(None, C_EXCLUDE)
            for figs, eo in right[1]:
                self.combine(list(figs), C_EXCLUDE, evenodd=eo)
            return True
        return False

    # ---- images ---------------------------------------------------------------------------

    def draw_image(self, image: Image, src, local: Matrix) -> None:
        """``image``'s source rectangle (pixels) drawn through ``local`` (the unit square of
        the source onto world space) and the current transform."""
        sx, sy, sw, sh = src
        if not sw or not sh:
            return
        m = mul(local, self.matrix())
        # The source rectangle onto the unit square, then the destination.
        to_unit = (1 / sw, 0.0, 0.0, 1 / sh, -sx / sw, -sy / sh)
        whole = mul(to_unit, m)
        if image.kind == "bitmap":
            # Windows' slide show (slide 23) centres source pixel i on i, not i + 1/2, and
            # samples transparency past the image: a nearest-neighbour image starts with a
            # half block and ends half a block early; a smoothed one fades out at its right
            # and bottom.  The bitmap drawn half a pixel up and left, padded, clipped.
            inner = _image_markup(image, -0.5, -0.5, image.width + (1 if image.padded else 0),
                                  image.height + (1 if image.padded else 0), self.state.interpolation,
                                  padded=True)
        else:
            inner = _image_markup(image, 0, 0, image.width, image.height, self.state.interpolation)
        if image.kind == "bitmap" or (sx, sy, sw, sh) != (0, 0, image.width, image.height):
            cid = self.p._id("c")
            self.p._def(f'<clipPath id="{cid}" clipPathUnits="userSpaceOnUse"><path d="'
                        f'{path_data([_rect_figure(sx, sy, sw, sh)])}"/></clipPath>')
            inner = f'<g clip-path="url(#{cid})">{inner}</g>'
        self._write(f"<g{Player._transform(whole)}>{inner}</g>")

    # ---- text -----------------------------------------------------------------------------

    def _font_size(self, font: FontObj) -> float:
        """The em in world units: a ``UnitWorld`` size as it is, any other unit in pixels
        at the header's resolution."""
        return font.em * self._unit(font.unit, 1)

    def _text_paint(self, brush) -> str | None:
        m = self.matrix()
        layers = self.paint_layers(brush, m)
        if layers is None:
            self.p.skip("EmfPlus path gradient text (drawn in its centre colour)")
            return _fill(brush.center_color)
        return layers[-1] if layers else None

    def draw_string(self, font: FontObj, brush, fmt: StringFormat, rect, text: str) -> None:
        paint = self._text_paint(brush)
        if paint is None:
            return
        text = text[: gdi.MAX_TEXT_CHARS]
        size = self._font_size(font)
        if size <= 0 or not math.isfinite(size):
            return
        bold, italic = bool(font.style & 1), bool(font.style & 2)
        if fmt.flags & 0x0003:
            self.p.skip("EmfPlusDrawString right-to-left or vertical (drawn left to right)")
        x, y, w, h = rect
        ascent, descent, _gap = gdi.line_metrics(font.family)
        # Measured (Windows slides 24, 25; Arial 16 to 28 px): the layout box is moved a
        # sixth of an em left and padded a sixth of an em on either side; lines are the
        # ascent and descent apart; the first baseline is 0.97 of the ascent below the top;
        # a block is 0.12 em taller than its lines when it is aligned.
        pad_em = size / 6
        x -= pad_em
        line_height = (ascent + descent) * size
        wrap = w > 0 and not fmt.flags & 0x1000
        inner = w - 2 * pad_em - (fmt.leading + fmt.trailing) * size
        lines = _lines(text, size, bold, font.family, inner if wrap else None)
        if not lines:
            return
        total = len(lines) * line_height + 0.12 * size
        if h > 0 and fmt.line_align == 1:
            top = y + (h - total) / 2
        elif h > 0 and fmt.line_align == 2:
            top = y + h - total
        elif h <= 0 and fmt.line_align == 1:
            top = y - total / 2
        elif h <= 0 and fmt.line_align == 2:
            top = y - total
        else:
            top = y
        if fmt.align == 1:
            tx, anchor = x + w / 2, ' text-anchor="middle"'
        elif fmt.align == 2:
            tx, anchor = x + w - pad_em - fmt.trailing * size, ' text-anchor="end"'
        else:
            tx, anchor = x + pad_em + fmt.leading * size, ""
        attrs = " ".join(gdi.font_attributes(font.family, size, bold=bold, italic=italic,
                                             underline=bool(font.style & 4), strike=bool(font.style & 8),
                                             font_mapping=self.p.font_mapping))
        parts = []
        for k, line in enumerate(lines):
            if not line.strip():
                continue
            baseline = top + k * line_height + 0.97 * ascent * size
            parts.append(f'<text x="{num(tx)}" y="{num(baseline)}"{paint} {attrs}{anchor} '
                         f'xml:space="preserve">{escape(line)}</text>')
        if not parts:
            return
        body = "".join(parts)
        if w > 0 and h > 0 and not fmt.flags & 0x4000:
            cid = self.p._id("c")
            self.p._def(f'<clipPath id="{cid}" clipPathUnits="userSpaceOnUse"><path d="'
                        f'{path_data([_rect_figure(x, y, w, h)])}"/></clipPath>')
            body = f'<g clip-path="url(#{cid})">{body}</g>'
        transform = Player._transform(self.matrix())
        self._write(f"<g{transform}>{body}</g>" if transform else body)

    def draw_driver_string(self, font: FontObj, brush, options: int, glyphs: list[int], positions, matrix) -> bool:
        if not options & 0x1:
            self.p.skip("EmfPlusDrawDriverString by glyph index (not drawn)")
            return True
        if options & 0x2:
            self.p.skip("EmfPlusDrawDriverString vertical (drawn horizontally)")
        paint = self._text_paint(brush)
        if paint is None or not glyphs:
            return True
        text = "".join(chr(g) if 0x20 <= g < 0xD800 or 0xE000 <= g <= 0xFFFD else " " for g in glyphs)
        size = self._font_size(font)
        attrs = " ".join(gdi.font_attributes(font.family, size, bold=bool(font.style & 1),
                                             italic=bool(font.style & 2), underline=bool(font.style & 4),
                                             strike=bool(font.style & 8), font_mapping=self.p.font_mapping))
        if options & 0x4:
            xs, ys = num(positions[0][0]), num(positions[0][1])
        else:
            xs = " ".join(num(px) for px, _ in positions)
            ys = " ".join(num(py) for _, py in positions)
        m = self.matrix()
        if matrix is not None:
            m = mul(matrix, m)
        self._write(f'<text x="{xs}" y="{ys}"{Player._transform(m)}{paint} {attrs} '
                    f'xml:space="preserve">{escape(text)}</text>')
        return True


# --------------------------------------------------------------------------------------
# Geometry helpers
# --------------------------------------------------------------------------------------


def _bands(compound: tuple) -> list[float] | None:
    """A compound array's edges from the outside in, when it is symmetric about the
    pen's centre line (else ``None``)."""
    values = sorted(min(max(v, 0.0), 1.0) for v in compound)
    if len(values) < 2 or len(values) % 2:
        return None
    n = len(values)
    if any(abs(values[i] + values[n - 1 - i] - 1) > 1e-3 for i in range(n)):
        return None
    return [values[i] for i in range(n // 2)]


def _region(figures, width: float) -> str:
    """A mask's region: the figures' box and a margin wider than any stroke on them."""
    xs = [x for f in figures for x, _ in _flatten(f, 2)]
    ys = [y for f in figures for _, y in _flatten(f, 2)]
    pad = 2 * width + 1
    return (f'x="{num(min(xs) - pad)}" y="{num(min(ys) - pad)}" width="{num(max(xs) - min(xs) + 2 * pad)}" '
            f'height="{num(max(ys) - min(ys) + 2 * pad)}"')


def _ends(fig: Figure):
    """``((start, outward direction), (end, outward direction))`` of an open figure."""
    pts = _flatten(fig, 6)
    if len(pts) < 2:
        return None

    def direction(a, b):
        dx, dy = a[0] - b[0], a[1] - b[1]
        length = math.hypot(dx, dy)
        return (dx / length, dy / length) if length else None

    start = next((direction(pts[0], q) for q in pts[1:] if direction(pts[0], q)), None)
    end = next((direction(pts[-1], q) for q in reversed(pts[:-1]) if direction(pts[-1], q)), None)
    if start is None or end is None:
        return None
    return (pts[0], start), (pts[-1], end)


def _cap_shape(cap: int, point, direction, width: float) -> Figure | None:
    (px, py), (dx, dy) = point, direction
    nx, ny = -dy, dx
    h = width / 2
    # Square and triangle caps reach a little back over the line, so that no seam shows.
    e = h / 4
    px, py = px - dx * e, py - dy * e
    if cap == CAP_SQUARE:
        h2 = h + e
        return gdi.polyline_figure([(px + nx * h, py + ny * h), (px + nx * h + dx * h2, py + ny * h + dy * h2),
                                    (px - nx * h + dx * h2, py - ny * h + dy * h2), (px - nx * h, py - ny * h)], True)
    if cap == CAP_ROUND:
        px, py = px + dx * e, py + dy * e
        return gdi.ellipse_figure(px - h, py - h, px + h, py + h)
    if cap == CAP_TRIANGLE:
        return gdi.polyline_figure([(px + nx * h, py + ny * h), (px + dx * (h + e), py + dy * (h + e)),
                                    (px - nx * h, py - ny * h)], True)
    px, py = px + dx * e, py + dy * e
    if cap == CAP_ARROW_ANCHOR:
        # Measured: two widths across, sqrt(3) widths long, the tip on the end point.
        length = math.sqrt(3) * width
        bx, by = px - dx * length, py - dy * length
        return gdi.polyline_figure([(px, py), (bx + nx * width, by + ny * width), (bx - nx * width, by - ny * width)],
                                   True)
    if cap == CAP_ROUND_ANCHOR:
        return gdi.ellipse_figure(px - width, py - width, px + width, py + width)
    if cap == CAP_SQUARE_ANCHOR:
        return gdi.rect_figure(px - width, py - width, px + width, py + width)
    if cap == CAP_DIAMOND_ANCHOR:
        return gdi.polyline_figure([(px + dx * width, py + dy * width), (px + nx * width, py + ny * width),
                                    (px - dx * width, py - dy * width), (px - nx * width, py - ny * width)], True)
    return None


def _shortened(fig: Figure, at_start: float, at_end: float) -> Figure:
    """An open figure with its first and last straight segments shortened."""
    out = Figure(*fig.start)
    out.segments = list(fig.segments)
    if at_start and out.segments and len(out.segments[0]) == 2:
        (x0, y0), (x1, y1) = fig.start, out.segments[0]
        length = math.hypot(x1 - x0, y1 - y0)
        if length > at_start:
            t = at_start / length
            out.start = (x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
    if at_end and out.segments and len(out.segments[-1]) == 2:
        x1, y1 = out.segments[-1]
        x0, y0 = (out.segments[-2][-2:] if len(out.segments) > 1 else out.start)
        length = math.hypot(x1 - x0, y1 - y0)
        if length > at_end:
            t = at_end / length
            out.segments[-1] = (x1 - (x1 - x0) * t, y1 - (y1 - y0) * t)
    return out


def _lines(text: str, size: float, bold: bool, family: str, width: float | None) -> list[str]:
    """``text`` broken at its line breaks and, given a width, wrapped at spaces (a word
    longer than the line broken by characters), measured with the renderers' metrics."""
    from ..text.measure import DefaultTextMeasurer

    measurer = DefaultTextMeasurer()

    def measure(s: str) -> float:
        return measurer.measure_text_width(s, size * 0.75, bold, family or "Arial")

    out = []
    for paragraph in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if width is None or width <= 0:
            out.append(paragraph)
            continue
        line = ""
        for word in paragraph.split(" "):
            candidate = word if not line else line + " " + word
            if not line or measure(candidate) <= width + 1e-6:
                line = candidate
                while measure(line) > width + 1e-6 and len(line) > 1:
                    # Break a word too long for the line by characters.
                    cut = len(line) - 1
                    while cut > 1 and measure(line[:cut]) > width + 1e-6:
                        cut -= 1
                    out.append(line[:cut])
                    line = line[cut:]
                continue
            out.append(line)
            line = word
        out.append(line)
    return out


def _image_markup(image: Image, x, y, w, h, interpolation: int, *, padded: bool = False) -> str:
    if image.kind == "svg":
        return _nested_svg(image, x, y, w, h)
    if padded and image.padded:
        href = "data:image/png;base64," + base64.b64encode(image.padded).decode("ascii")
    else:
        href = f"data:{image.mime};base64," + base64.b64encode(image.data).decode("ascii")
    sharp = ' image-rendering="optimizeSpeed" style="image-rendering:pixelated"' if interpolation == 5 else ""
    return (f'<image x="{num(x)}" y="{num(y)}" width="{num(w)}" height="{num(h)}" preserveAspectRatio="none"'
            f'{sharp} href="{href}"/>')


def _nested_svg(image: Image, x, y, w, h) -> str:
    """A metafile drawn by this module, inline as a nested ``<svg>`` (its ids are its own)."""
    svg = image.data.decode("utf-8", errors="replace")
    head_end = svg.find(">")
    view = svg[:head_end]
    start = view.find('viewBox="')
    view_box = view[start + 9 : view.find('"', start + 9)] if start >= 0 else f"0 0 {num(w)} {num(h)}"
    inner = svg[head_end + 1 : svg.rfind("</svg>")]
    return (f'<svg x="{num(x)}" y="{num(y)}" width="{num(w)}" height="{num(h)}" viewBox="{view_box}" '
            f'preserveAspectRatio="none" overflow="hidden">{inner}</svg>')


def _shade(brush: PathGradient, polygons, centre, x0, y0, pw, ph, step_x, step_y) -> bytearray:
    """The path gradient's pixels: each triangle of the centre and a boundary edge shaded
    from the centre colour to the edge's colours (barycentric), the blend applied along
    the way from the boundary (0) to the centre (1); transparent outside the boundary.
    Row by row, over the span of each row inside the triangle."""
    rgba = bytearray(pw * ph * 4)
    surround = brush.surround or (brush.center_color,)
    cc = _channels(brush.center_color)
    blend, preset, focus = brush.blend, brush.preset, brush.focus
    plain = blend is None and preset is None and focus <= 0
    cxp, cyp = centre
    for poly in polygons:
        n = len(poly)
        colours = [_channels(surround[min(i, len(surround) - 1)]) for i in range(n)]
        for i in range(n):
            (ax, ay), (bx, by) = poly[i], poly[(i + 1) % n]
            ca, cb = colours[i], colours[(i + 1) % n]
            denominator = (by - cyp) * (ax - cxp) + (cxp - bx) * (ay - cyp)
            if abs(denominator) < 1e-12:
                continue
            # l1 (corner a) and l2 (corner b) are linear in the pixel: l = gx * x + gy * y + k.
            g1x, g1y = (by - cyp) / denominator, (cxp - bx) / denominator
            g2x, g2y = (cyp - ay) / denominator, (ax - cxp) / denominator
            k1 = -g1x * cxp - g1y * cyp
            k2 = -g2x * cxp - g2y * cyp
            lo_y = max(int((min(ay, by, cyp) - y0) / step_y), 0)
            hi_y = min(int((max(ay, by, cyp) - y0) / step_y) + 1, ph)
            for j in range(lo_y, hi_y):
                py = y0 + (j + 0.5) * step_y
                # The span of x where l1, l2 and 1 - l1 - l2 are all >= 0.
                lo, hi = -math.inf, math.inf
                for gx, c in ((g1x, g1y * py + k1), (g2x, g2y * py + k2),
                              (-g1x - g2x, 1 - (g1y + g2y) * py - k1 - k2)):
                    if abs(gx) < 1e-15:
                        if c < -1e-9:
                            lo, hi = 1.0, 0.0
                        continue
                    bound = -c / gx
                    if gx > 0:
                        lo = max(lo, bound)
                    else:
                        hi = min(hi, bound)
                first = max(math.ceil((lo - x0) / step_x - 0.5 - 1e-9), 0)
                last = min(math.floor((hi - x0) / step_x - 0.5 + 1e-9), pw - 1)
                if last < first:
                    continue
                row = j * pw
                px = x0 + (first + 0.5) * step_x
                l1 = g1x * px + g1y * py + k1
                l2 = g2x * px + g2y * py + k2
                d1, d2 = g1x * step_x, g2x * step_x
                for i2 in range(first, last + 1):
                    a1 = l1 if l1 > 0 else 0.0
                    a2 = l2 if l2 > 0 else 0.0
                    l0 = 1 - a1 - a2
                    if l0 < 0:
                        l0 = 0.0
                    if plain:
                        colour = [cc[c] * l0 + ca[c] * a1 + cb[c] * a2 for c in range(4)]
                    else:
                        edge = a1 + a2
                        u = a2 / edge if edge > 1e-12 else 0.0
                        bc = [ca[c] + (cb[c] - ca[c]) * u for c in range(4)]
                        t = l0  # 0 on the boundary, 1 at the centre
                        if focus > 0:
                            t = 1.0 if t >= 1 - focus else t / (1 - focus)
                        if preset is not None:
                            colour = list(_channels(_at(preset, t, colours=True)))
                        else:
                            f = _at(blend, t) if blend is not None else t
                            colour = [bc[c] + (cc[c] - bc[c]) * f for c in range(4)]
                    k = (row + i2) * 4
                    rgba[k : k + 4] = bytes(min(255, max(0, int(v + 0.5))) for v in colour)
                    l1 += d1
                    l2 += d2
    return rgba


def _at(stops, t: float, *, colours: bool = False):
    """A piecewise-linear value of ``(position, value)`` stops at ``t``; for ARGB stops,
    the colour."""
    if not stops:
        return 0xFF000000 if colours else t
    if t <= stops[0][0]:
        return stops[0][1]
    for (p0, v0), (p1, v1) in zip(stops, stops[1:]):
        if t <= p1:
            f = (t - p0) / (p1 - p0) if p1 > p0 else 1.0
            return _lerp_argb(v0, v1, f) if colours else v0 + (v1 - v0) * f
    return stops[-1][1]


# --------------------------------------------------------------------------------------
# Object parsing
# --------------------------------------------------------------------------------------


def _blend(d: _Data, colours: bool) -> tuple:
    n = _count(d, 8)
    positions = d.floats(n)
    values = list(d.take(f"{n}I")) if colours else d.floats(n)
    return tuple(zip(positions, values))


def parse_brush(d: _Data, pp: PlusPlayer):
    _version, kind = d.u32(), d.u32()
    if kind == 0:
        return Solid(d.u32())
    if kind == 1:
        style, fore, back = d.take("III")
        return Hatch(style, fore, back)
    if kind == 2:
        flags, wrap = d.u32(), d.i32()
        matrix = _matrix(d) if flags & 0x02 else IDENTITY
        image = parse_image(d, pp)
        if not isinstance(image, Image):
            return None
        return Texture(image, wrap, matrix)
    if kind == 3:
        flags, wrap, center_color = d.u32(), d.i32(), d.u32()
        center = tuple(d.floats(2))
        n = _count(d, 4)
        surround = tuple(d.take(f"{n}I"))
        if flags & 0x01:
            size = d.i32()
            path = parse_path(_Data(d.bytes(size)), pp)
            boundary = tuple(tuple(_flatten(f, 8)) for f in path.figures) if path else ()
        else:
            m = _count(d, 8)
            boundary = (tuple(_points(d, m, compressed=False)),)
        matrix = _matrix(d) if flags & 0x02 else IDENTITY
        blend = preset = None
        if flags & 0x04:
            preset = tuple(sorted(_blend(d, True)))  # positions from the boundary (0) to the centre
        elif flags & 0x08 or flags & 0x10:
            blend = _blend(d, False)
        focus = 0.0
        if flags & 0x40:
            _n = d.u32()
            fx, fy = d.floats(2)
            focus = min(max((fx + fy) / 2, 0.0), 0.999)
        return PathGradient(center_color, center, surround, boundary, matrix, blend, preset, focus)
    if kind == 4:
        flags, _wrap = d.u32(), d.i32()
        rect = tuple(d.floats(4))
        start, end, reserved1, reserved2 = d.take("IIII")
        matrix = _matrix(d) if flags & 0x02 else IDENTITY
        # Windows draws the Reserved colours (GDI+ writes the start and end again there).
        c0, c1 = reserved1, reserved2
        stops = ((0.0, c0), (1.0, c1))
        if flags & 0x04:
            stops = tuple(sorted(_blend(d, True)))
        elif flags & 0x08 or flags & 0x10:
            stops = tuple((p, _lerp_argb(c0, c1, f)) for p, f in sorted(_blend(d, False)))
        if flags & 0x80:
            pp.p.skip("EmfPlus gamma-corrected gradients (drawn without gamma)")
        return Linear(rect, c0, c1, matrix, stops)
    return None


def parse_pen(d: _Data, pp: PlusPlayer) -> Pen | None:
    _version, _kind = d.u32(), d.u32()
    flags, unit = d.u32(), d.u32()
    width = d.f32()
    values = {}
    if flags & 0x0001:
        values["matrix"] = _matrix(d)
    if flags & 0x0002:
        values["start_cap"] = d.i32()
    if flags & 0x0004:
        values["end_cap"] = d.i32()
    if flags & 0x0008:
        values["join"] = d.u32()
    if flags & 0x0010:
        values["miter"] = d.f32()
    if flags & 0x0020:
        values["dash"] = d.i32()
    if flags & 0x0040:
        values["dash_cap"] = d.i32()
    if flags & 0x0080:
        values["dash_offset"] = d.f32()
    if flags & 0x0100:
        n = _count(d, 4)
        values["dash_array"] = tuple(d.floats(n))
        values.setdefault("dash", 5)
    if flags & 0x0200:
        values["align"] = d.i32()
    if flags & 0x0400:
        n = _count(d, 4)
        values["compound"] = tuple(d.floats(n))
    for bit, key in ((0x0800, "start_cap"), (0x1000, "end_cap")):
        if flags & bit:
            size = d.u32()
            d.bytes(size)
            values[key] = CAP_CUSTOM
    brush = parse_brush(d, pp)
    if brush is None:
        return None
    return Pen(width=abs(width), unit=unit, brush=brush, **values)


def parse_path(d: _Data, pp: PlusPlayer) -> Path | None:
    _version = d.u32()
    count = d.u32()
    flags = d.u32()
    if count > d.left():
        raise ValueError("point count runs past the record")
    pp.p.count_points(count)
    points = _points(d, count, compressed=bool(flags & 0x4000), relative=bool(flags & 0x0800))
    types: list[int] = []
    if flags & 0x1000:
        while len(types) < count and d.left() >= 2:
            run, kind = d.take("BB")
            types.extend([kind] * max(run & 0x3F, 1))
        types = types[:count]
    else:
        types = list(d.bytes(min(count, d.left())))
    figures: list[Figure] = []
    k = 0
    fig: Figure | None = None
    while k < len(points) and k < len(types):
        kind = types[k] & 0x07
        if kind == 0 or fig is None:
            fig = Figure(*points[k])
            figures.append(fig)
            k += 1
        elif kind == 3 and k + 2 < len(points):
            fig.segments.append((*points[k], *points[k + 1], *points[k + 2]))
            k += 2
            if types[min(k, len(types) - 1)] & 0x80:
                fig.closed = True
                fig = None
            k += 1
            continue
        else:
            fig.segments.append(points[k])
            k += 1
        if fig is not None and types[k - 1] & 0x80:
            fig.closed = True
            fig = None
    return Path(tuple(figures))


def parse_region(d: _Data, pp: PlusPlayer, depth: int = 0):
    if depth == 0:
        _version, _count_nodes = d.u32(), d.u32()
    if depth > 64:
        raise ValueError("region too deep")
    kind = d.u32()
    if kind in (1, 2, 3, 4, 5):
        left = parse_region(d, pp, depth + 1)
        right = parse_region(d, pp, depth + 1)
        return ({1: "and", 2: "or", 3: "xor", 4: "exclude", 5: "complement"}[kind], left, right)
    if kind == 0x10000000:
        return ("rect", tuple(d.floats(4)))
    if kind == 0x10000001:
        size = d.i32()
        path = parse_path(_Data(d.bytes(size)), pp)
        return ("path", path.figures if path else ())
    if kind == 0x10000002:
        return ("empty",)
    if kind == 0x10000003:
        return ("inf",)
    raise ValueError("unknown region node")


_FORMATS = {0x00030101: "i1", 0x00030402: "i4", 0x00030803: "i8", 0x00101004: "g16", 0x00021005: "555",
            0x00021006: "565", 0x00061007: "1555", 0x00021808: "24", 0x00022009: "32", 0x0026200A: "argb",
            0x000E200B: "pargb"}


def parse_image(d: _Data, pp: PlusPlayer):
    _version, kind = d.u32(), d.u32()
    if kind == 1:
        width, height, stride, fmt, data_type = d.take("iiiII")
        if width <= 0 or height <= 0:
            return Other("an empty bitmap")
        pp.p.pixels += width * height
        if pp.p.pixels > gdi.MAX_TOTAL_PIXELS:
            pp.p.skip("bitmaps beyond the pixel cap")
            return Other("bitmap")
        payload = d.b[d.at :]
        if data_type == 1:
            return _compressed(payload, width, height, pp)
        return _pixels(payload, width, height, stride, fmt, pp)
    if kind == 2:
        _mtype, size = d.take("II")
        payload = d.bytes(min(size, d.left()))
        return _metafile_image(payload, pp)
    return Other("an image of unknown type")


def _compressed(payload: bytes, width: int, height: int, pp: PlusPlayer):
    for magic, mime in ((b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8", "image/jpeg"), (b"GIF8", "image/gif")):
        if payload.startswith(magic):
            return Image("bitmap", payload, mime, float(width), float(height), _pad_png(payload))
    if payload.startswith(b"BM") and len(payload) > 14:
        split = dib.split_packed_dib(payload[14:])
        if split is not None:
            image = dib.dib_to_image(*split)
            if image is not None:
                return Image("bitmap", image.data, image.mime_type, float(width), float(height),
                             _pad_png(image.data))
    pp.p.skip("EmfPlus compressed bitmaps other than PNG, JPEG, GIF or BMP (not drawn)")
    return Other("bitmap")


def _pixels(payload: bytes, width: int, height: int, stride: int, fmt: int, pp: PlusPlayer):
    kind = _FORMATS.get(fmt)
    if kind is None:
        pp.p.skip(f"EmfPlus bitmaps in pixel format 0x{fmt:08X} (not drawn)")
        return Other("bitmap")
    palette: list[tuple[int, int, int, int]] = []
    at = 0
    if kind.startswith("i"):
        if len(payload) < 8:
            return Other("bitmap")
        _style, n = struct.unpack_from("<II", payload, 0)
        n = min(n, 256, (len(payload) - 8) // 4)
        palette = [_channels(v) for v in struct.unpack_from(f"<{n}I", payload, 8)]
        at = 8 + 4 * n
    bits = {"i1": 1, "i4": 4, "i8": 8, "g16": 16, "555": 16, "565": 16, "1555": 16, "24": 24}.get(kind, 32)
    row_bytes = (width * bits + 7) // 8
    step = abs(stride) if stride else (row_bytes + 3) & ~3
    if step < row_bytes or at + step * (height - 1) + row_bytes > len(payload):
        pp.p.skip("an EmfPlus bitmap shorter than its size (not drawn)")
        return Other("bitmap")
    rgba = bytearray(width * height * 4)
    alpha = False
    for y in range(height):
        source_row = y if stride >= 0 else height - 1 - y
        row = payload[at + source_row * step : at + source_row * step + row_bytes]
        out = y * width * 4
        for x in range(width):
            if kind in ("argb", "pargb", "32"):
                b, g, r, a = row[4 * x : 4 * x + 4]
                if kind == "32":
                    a = 255
                elif kind == "pargb" and a:
                    r, g, b = (min(255, round(v * 255 / a)) for v in (r, g, b))
            elif kind == "24":
                b, g, r = row[3 * x : 3 * x + 3]
                a = 255
            elif kind in ("555", "565", "1555", "g16"):
                v = row[2 * x] | (row[2 * x + 1] << 8)
                if kind == "565":
                    r, g, b, a = (v >> 11) * 255 // 31, ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31, 255
                elif kind == "g16":
                    r = g = b = v >> 8
                    a = 255
                else:
                    r, g, b = ((v >> 10) & 31) * 255 // 31, ((v >> 5) & 31) * 255 // 31, (v & 31) * 255 // 31
                    a = 255 if kind == "555" or v & 0x8000 else 0
            else:
                per = 8 // bits if bits < 8 else 1
                if bits == 8:
                    index = row[x]
                else:
                    byte = row[x // per]
                    shift = 8 - bits * (x % per + 1)
                    index = (byte >> shift) & ((1 << bits) - 1)
                r, g, b, a = palette[index] if index < len(palette) else (0, 0, 0, 255)
            if a != 255:
                alpha = True
            rgba[out + 4 * x : out + 4 * x + 4] = bytes((r, g, b, a))
    png = dib.encode_png(width, height, bytes(rgba), has_alpha=alpha)
    return Image("bitmap", png, "image/png", float(width), float(height), _padded(width, height, rgba))


def _padded(width: int, height: int, rgba) -> bytes:
    """A PNG of the pixels with a transparent column and row after them."""
    row = 4 * width
    out = bytearray()
    for y in range(height):
        out += rgba[y * row : (y + 1) * row] + bytes(4)
    out += bytes(4 * (width + 1))
    return dib.encode_png(width + 1, height + 1, bytes(out), has_alpha=True)


def _pad_png(data: bytes) -> bytes | None:
    """:func:`_padded` of an 8-bit RGB or RGBA, non-interlaced PNG; ``None`` for any
    other (or one larger than the decoding cap)."""
    try:
        import zlib

        if data[12:16] != b"IHDR":
            return None
        width, height, depth, colour, _c, _f, interlace = struct.unpack(">IIBBBBB", data[16:29])
        if depth != 8 or colour not in (2, 6) or interlace or width * height > 4_000_000:
            return None
        channels = 4 if colour == 6 else 3
        at, compressed = 8, bytearray()
        while at + 8 <= len(data):
            length = struct.unpack(">I", data[at : at + 4])[0]
            tag = data[at + 4 : at + 8]
            if tag == b"IDAT":
                compressed += data[at + 8 : at + 8 + length]
            if tag == b"IEND":
                break
            at += 12 + length
        stride = width * channels
        raw = zlib.decompressobj().decompress(bytes(compressed), (stride + 1) * height)
        if len(raw) < (stride + 1) * height:
            return None
        previous = bytearray(stride)
        rgba = bytearray()
        for y in range(height):
            kind = raw[y * (stride + 1)]
            line = bytearray(raw[y * (stride + 1) + 1 : (y + 1) * (stride + 1)])
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = previous[i]
                c = previous[i - channels] if i >= channels else 0
                if kind == 1:
                    line[i] = (line[i] + a) & 0xFF
                elif kind == 2:
                    line[i] = (line[i] + b) & 0xFF
                elif kind == 3:
                    line[i] = (line[i] + (a + b) // 2) & 0xFF
                elif kind == 4:
                    pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                    line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 0xFF
            previous = line
            if channels == 4:
                rgba += line
            else:
                for x in range(width):
                    rgba += line[3 * x : 3 * x + 3] + b"\xff"
        return _padded(width, height, rgba)
    except Exception:  # a picture we cannot pad is drawn unpadded
        return None


def _metafile_image(payload: bytes, pp: PlusPlayer):
    if pp.nesting >= MAX_NESTING:
        pp.p.skip("EmfPlus metafile images nested too deep (not drawn)")
        return Other("metafile")
    from . import _draw  # the package's player: the nested metafile drawn by the same rules

    try:
        drawing = _draw(payload, pp.p.font_mapping, nesting=pp.nesting + 1)
    except Exception:  # a nested metafile is as untrusted as the outer one
        drawing = None
    if drawing is None or not drawing.drawn:
        pp.p.skip("an EmfPlus metafile image that draws nothing")
        return Other("metafile")
    for name, count in drawing.skipped:
        for _ in range(count):
            pp.p.skip(name)
    return Image("svg", drawing.svg, "image/svg+xml", drawing.width, drawing.height)


def parse_font(d: _Data, pp: PlusPlayer) -> FontObj:
    _version = d.u32()
    em = d.f32()
    unit, style, _reserved, length = d.take("IiII")
    family = d.bytes(min(length, 64) * 2).decode("utf-16-le", errors="replace").split("\0", 1)[0]
    return FontObj(em, unit, style, family.strip())


def parse_string_format(d: _Data, pp: PlusPlayer) -> StringFormat:
    _version, flags, _language, align, line_align = d.take("IIIII")
    _digits, _digit_language = d.take("II")
    _first_tab = d.f32()
    _hotkey = d.i32()
    leading, trailing = d.floats(2)
    return StringFormat(flags, align, line_align, leading, trailing)


_PARSERS = {1: parse_brush, 2: parse_pen, 3: parse_path, 4: parse_region, 5: parse_image, 6: parse_font,
            7: parse_string_format}


# --------------------------------------------------------------------------------------
# Record handlers
# --------------------------------------------------------------------------------------


def _object(pp: PlusPlayer, flags: int, d: _Data):
    index = flags & 0xFF
    kind = (flags >> 8) & 0x7F
    if index >= 64:
        return False
    data = d.b
    if flags & 0x8000:
        total = struct.unpack_from("<I", data, 0)[0]
        chunk = data[4:]
        held = pp.partial.get(index)
        if held is None or held[0] != kind:
            if total > MAX_OBJECT_BYTES:
                pp.p.skip("an EmfPlus object larger than the cap")
                return True
            held = (kind, total, bytearray())
            pp.partial[index] = held
        held[2].extend(chunk)
        if len(held[2]) < held[1]:
            return True
        data = bytes(held[2][: held[1]])
        del pp.partial[index]
    elif index in pp.partial:
        held = pp.partial.pop(index)
        data = bytes(held[2]) + data
    parser = _PARSERS.get(kind)
    if parser is None:
        pp.objects[index] = Other({8: "image attributes", 9: "custom line cap"}.get(kind, "object"))
        return True
    try:
        obj = parser(_Data(data), pp)
    except Stop:
        raise
    except Exception:
        obj = None
    if obj is None:
        pp.objects[index] = Other("unreadable")
        pp.p.skip("EmfPlusObject " + {1: "brush", 2: "pen", 3: "path", 4: "region", 5: "image", 6: "font",
                                       7: "string format"}[kind] + " (unreadable)")
        return True
    pp.objects[index] = obj
    return True


def _clear(pp, flags, d):
    colour = d.u32()
    x, y, w, h = pp.p.canvas
    pp._write(f'<path d="{path_data([gdi.rect_figure(x, y, x + w, y + h)])}"{_fill(colour)}/>')


def _fill_rects(pp, flags, d):
    brush = pp._brush(flags, d.u32())
    n = _count(d, 8 if flags & 0x4000 else 16)
    pp.p.count_points(4 * n)
    pp.fill([_rect_figure(*r) for r in _rects(d, n, bool(flags & 0x4000))], brush)


def _draw_rects(pp, flags, d):
    pen = pp._pen(flags)
    n = _count(d, 8 if flags & 0x4000 else 16)
    pp.p.count_points(4 * n)
    pp.stroke([_rect_figure(*r) for r in _rects(d, n, bool(flags & 0x4000))], pen)


def _poly_points(pp, flags, d):
    n = _count(d, 1 if flags & 0x0800 else 4 if flags & 0x4000 else 8)
    pp.p.count_points(n)
    return _points(d, n, compressed=bool(flags & 0x4000), relative=bool(flags & 0x0800))


def _fill_polygon(pp, flags, d):
    brush = pp._brush(flags, d.u32())
    points = _poly_points(pp, flags, d)
    if len(points) >= 2:
        pp.fill([gdi.polyline_figure(points, True)], brush, evenodd=True)


def _draw_lines(pp, flags, d):
    pen = pp._pen(flags)
    points = _poly_points(pp, flags, d)
    if len(points) >= 2:
        pp.stroke([gdi.polyline_figure(points, bool(flags & 0x2000))], pen)


def _ellipse_rect(flags, d):
    return _rects(d, 1, bool(flags & 0x4000))[0]


def _fill_ellipse(pp, flags, d):
    brush = pp._brush(flags, d.u32())
    x, y, w, h = _ellipse_rect(flags, d)
    pp.fill([gdi.ellipse_figure(x, y, x + w, y + h)], brush)


def _draw_ellipse(pp, flags, d):
    x, y, w, h = _ellipse_rect(flags, d)
    pp.stroke([gdi.ellipse_figure(x, y, x + w, y + h)], pp._pen(flags))


def _pie_figure(start, sweep, rect, pie: bool) -> Figure:
    x, y, w, h = rect
    first, segments = _arc(x, y, w, h, start, sweep)
    fig = Figure(*first)
    fig.segments = list(segments)
    if pie:
        fig.segments.append((x + w / 2, y + h / 2))
        fig.closed = True
    return fig


def _fill_pie(pp, flags, d):
    brush = pp._brush(flags, d.u32())
    start, sweep = d.floats(2)
    pp.fill([_pie_figure(start, sweep, _ellipse_rect(flags, d), True)], brush)


def _draw_pie(pp, flags, d):
    start, sweep = d.floats(2)
    pp.stroke([_pie_figure(start, sweep, _ellipse_rect(flags, d), True)], pp._pen(flags))


def _draw_arc(pp, flags, d):
    start, sweep = d.floats(2)
    pp.stroke([_pie_figure(start, sweep, _ellipse_rect(flags, d), False)], pp._pen(flags))


def _path_object(pp, index) -> Path | None:
    path = pp.objects.get(index & 0xFF)
    return path if isinstance(path, Path) else None


def _fill_path(pp, flags, d):
    brush = pp._brush(flags, d.u32())
    path = _path_object(pp, flags)
    if path is None:
        return False
    figures = []
    for fig in path.figures:
        closed = Figure(*fig.start)
        closed.segments = list(fig.segments)
        closed.closed = True
        figures.append(closed)
    pp.fill(figures, brush, evenodd=True)


def _draw_path(pp, flags, d):
    path = _path_object(pp, flags)
    if path is None:
        return False
    pp.stroke(list(path.figures), pp._pen(d.u32()))


def _fill_region(pp, flags, d):
    brush = pp._brush(flags, d.u32())
    region = pp.objects.get(flags & 0xFF)
    if not isinstance(region, Region):
        return False
    saved = pp.state
    ok = pp.set_clip_region(region.node, C_INTERSECT, pp.matrix())
    if ok:
        inverse = invert(pp.matrix())
        x, y, w, h = pp.p.canvas
        if inverse is not None:
            corners = [apply(inverse, cx, cy) for cx, cy in ((x, y), (x + w, y), (x + w, y + h), (x, y + h))]
            pp.fill([gdi.polyline_figure(corners, True)], brush)
    pp.state = saved
    return ok


def _fill_closed_curve(pp, flags, d):
    brush = pp._brush(flags, d.u32())
    tension = d.f32()
    points = _poly_points(pp, flags, d)
    if len(points) < 3:
        return
    fig = Figure(*points[0])
    fig.segments = _cardinal(points, tension, True)
    fig.closed = True
    pp.fill([fig], brush, evenodd=not flags & 0x2000)


def _draw_closed_curve(pp, flags, d):
    tension = d.f32()
    points = _poly_points(pp, flags, d)
    if len(points) < 3:
        return
    fig = Figure(*points[0])
    fig.segments = _cardinal(points, tension, True)
    fig.closed = True
    pp.stroke([fig], pp._pen(flags))


def _draw_curve(pp, flags, d):
    tension = d.f32()
    offset, segments = d.u32(), d.u32()
    points = _poly_points(pp, flags, d)
    if len(points) < 2:
        return
    beziers = _cardinal(points, tension, False)
    offset = min(offset, len(beziers))
    chosen = beziers[offset : offset + segments]
    if not chosen:
        return
    fig = Figure(*points[offset])
    fig.segments = chosen
    pp.stroke([fig], pp._pen(flags))


def _draw_beziers(pp, flags, d):
    points = _poly_points(pp, flags, d)
    fig = gdi.bezier_figure(points)
    if fig is not None and fig.segments:
        pp.stroke([fig], pp._pen(flags))


def _image_object(pp, flags) -> Image | None:
    image = pp.objects.get(flags & 0xFF)
    return image if isinstance(image, Image) else None


def _src_rect(pp, d) -> tuple:
    _attributes, unit = d.u32(), d.i32()
    sx, sy, sw, sh = d.floats(4)
    if unit not in (U_PIXEL, U_WORLD, U_DISPLAY):
        k = pp._unit(unit)
        sx, sy, sw, sh = sx * k, sy * k, sw * k, sh * k
    return sx, sy, sw, sh


def _draw_image(pp, flags, d):
    image = _image_object(pp, flags)
    if image is None:
        return False
    src = _src_rect(pp, d)
    x, y, w, h = _rects(d, 1, bool(flags & 0x4000))[0]
    pp.draw_image(image, src, (w, 0.0, 0.0, h, x, y))


def _draw_image_points(pp, flags, d):
    image = _image_object(pp, flags)
    if image is None:
        return False
    src = _src_rect(pp, d)
    n = _count(d, 1 if flags & 0x0800 else 4 if flags & 0x4000 else 8)
    points = _points(d, n, compressed=bool(flags & 0x4000), relative=bool(flags & 0x0800))
    if len(points) < 3:
        return False
    (ux, uy), (rx, ry), (lx, ly) = points[:3]
    pp.draw_image(image, src, (rx - ux, ry - uy, lx - ux, ly - uy, ux, uy))


def _font_object(pp, flags) -> FontObj | None:
    font = pp.objects.get(flags & 0xFF)
    return font if isinstance(font, FontObj) else None


def _draw_string(pp, flags, d):
    font = _font_object(pp, flags)
    brush = pp._brush(flags, d.u32())
    fmt_id, length = d.u32(), d.u32()
    rect = tuple(d.floats(4))
    length = min(length, d.left() // 2, gdi.MAX_TEXT_CHARS)
    text = d.bytes(2 * length).decode("utf-16-le", errors="replace")
    fmt = pp.objects.get(fmt_id & 0xFF) if fmt_id < 64 else None
    if font is None:
        return False
    pp.draw_string(font, brush, fmt if isinstance(fmt, StringFormat) else StringFormat(), rect, text)


def _draw_driver_string(pp, flags, d):
    font = _font_object(pp, flags)
    brush = pp._brush(flags, d.u32())
    options, matrix_present, count = d.take("III")
    count = min(count, d.left() // 10, gdi.MAX_TEXT_CHARS)
    glyphs = list(d.take(f"{count}H")) if count else []
    positions = _points(d, count, compressed=False)
    matrix = _matrix(d) if matrix_present and d.left() >= 24 else None
    if font is None:
        return False
    return pp.draw_driver_string(font, brush, options, glyphs, positions, matrix)


def _rendering_origin(pp, flags, d):
    x, y = d.take("ii")
    pp.set(origin=(float(x), float(y)))


def _interpolation(pp, flags, d):
    pp.set(interpolation=flags & 0xFF)


def _compositing(pp, flags, d):
    pp.set(compositing=flags & 0xFF)


def _save(pp, flags, d):
    index = d.u32()
    if len(pp.saves) >= MAX_SAVES:
        pp.p.skip("EmfPlusSave beyond the depth cap")
        return
    pp.order += 1
    pp.saves[index] = (pp.order, pp.state)


def _restore(pp, flags, d):
    index = d.u32()
    saved = pp.saves.get(index)
    if saved is None:
        return
    order, state = saved
    pp.state = state
    for key in [k for k, (o, _s) in pp.saves.items() if o >= order]:
        del pp.saves[key]


def _begin_container(pp, flags, d):
    dst = d.floats(4)
    src = d.floats(4)
    index = d.u32()
    unit = (flags >> 8) & 0xFF
    outer = pp.state
    base = pp.matrix()
    if unit not in (U_WORLD, U_DISPLAY) and src[2] and src[3]:
        k = pp._unit(unit)
        sx, sy, sw, sh = src
        dx, dy, dw, dh = (v * k for v in dst)
        mapping = (dw / sw, 0.0, 0.0, dh / sh, dx - sx * dw / sw, dy - sy * dh / sh)
        base = mul(mapping, base)
    _push_container(pp, index, outer, base)


def _begin_container_np(pp, flags, d):
    _push_container(pp, d.u32(), pp.state, pp.matrix())


def _push_container(pp, index, outer, base):
    if len(pp.containers) >= MAX_SAVES:
        pp.p.skip("EmfPlusBeginContainer beyond the depth cap")
        return
    pp.order += 1
    pp.containers.append((index, outer))
    pp.saves[("c", index)] = (pp.order, outer)  # type: ignore[index]
    pp.state = State(base=base, clip=outer.clip, base_clip=outer.clip, interpolation=outer.interpolation,
                     compositing=outer.compositing, origin=outer.origin)


def _end_container(pp, flags, d):
    index = d.u32()
    for k in range(len(pp.containers) - 1, -1, -1):
        if pp.containers[k][0] == index:
            pp.state = pp.containers[k][1]
            del pp.containers[k:]
            order = pp.saves.get(("c", index), (0, None))[0]  # type: ignore[call-overload]
            for key in [key for key, (o, _s) in pp.saves.items() if o >= order]:
                del pp.saves[key]
            return


def _set_world(pp, flags, d):
    pp.set(world=_matrix(d))


def _reset_world(pp, flags, d):
    pp.set(world=IDENTITY)


def _apply_world(pp, flags, op: Matrix):
    """Prepend (the operation first, in world space) or, with the ``A`` flag, append."""
    world = pp.state.world
    pp.set(world=mul(world, op) if flags & 0x2000 else mul(op, world))


def _multiply_world(pp, flags, d):
    _apply_world(pp, flags, _matrix(d))


def _translate_world(pp, flags, d):
    dx, dy = d.floats(2)
    _apply_world(pp, flags, _translate(dx, dy))


def _scale_world(pp, flags, d):
    sx, sy = d.floats(2)
    _apply_world(pp, flags, (sx, 0.0, 0.0, sy, 0.0, 0.0))


def _rotate_world(pp, flags, d):
    angle = math.radians(d.f32())
    c, s = math.cos(angle), math.sin(angle)
    _apply_world(pp, flags, (c, s, -s, c, 0.0, 0.0))


def _set_page(pp, flags, d):
    scale = d.f32()
    if scale <= 0:
        return False
    pp.set(page_scale=scale, page_unit=(flags >> 8) & 0xFF)


def _reset_clip(pp, flags, d):
    pp.set(clip=pp.state.base_clip)


def _set_clip_rect(pp, flags, d):
    x, y, w, h = d.floats(4)
    return pp.combine([_rect_figure(x, y, w, h).mapped(pp.matrix())], (flags >> 8) & 0x0F, evenodd=False)


def _set_clip_path(pp, flags, d):
    path = _path_object(pp, flags)
    if path is None:
        return False
    m = pp.matrix()
    figures = []
    for fig in path.figures:
        mapped = fig.mapped(m)
        mapped.closed = True
        figures.append(mapped)
    return pp.combine(figures, (flags >> 8) & 0x0F, evenodd=True)


def _set_clip_region(pp, flags, d):
    region = pp.objects.get(flags & 0xFF)
    if not isinstance(region, Region):
        return False
    return pp.set_clip_region(region.node, (flags >> 8) & 0x0F, pp.matrix())


def _offset_clip(pp, flags, d):
    dx, dy = d.floats(2)
    clip = pp.state.clip
    if clip is None:
        return True
    if clip.parts is None:
        return False
    m = pp.matrix()
    ox, oy = apply(m, dx, dy)
    zx, zy = apply(m, 0.0, 0.0)
    shift = _translate(ox - zx, oy - zy)
    parts = [(tuple(f.mapped(shift) for f in figs), eo) for figs, eo in clip.parts]
    pp.set(clip=pp._clip_of(parts, None))
    return True


_HANDLERS = {
    0x4008: _object, 0x4009: _clear, 0x400A: _fill_rects, 0x400B: _draw_rects, 0x400C: _fill_polygon,
    0x400D: _draw_lines, 0x400E: _fill_ellipse, 0x400F: _draw_ellipse, 0x4010: _fill_pie, 0x4011: _draw_pie,
    0x4012: _draw_arc, 0x4013: _fill_region, 0x4014: _fill_path, 0x4015: _draw_path, 0x4016: _fill_closed_curve,
    0x4017: _draw_closed_curve, 0x4018: _draw_curve, 0x4019: _draw_beziers, 0x401A: _draw_image,
    0x401B: _draw_image_points, 0x401C: _draw_string, 0x401D: _rendering_origin, 0x4021: _interpolation,
    0x4023: _compositing, 0x4025: _save, 0x4026: _restore, 0x4027: _begin_container,
    0x4028: _begin_container_np, 0x4029: _end_container, 0x402A: _set_world, 0x402B: _reset_world,
    0x402C: _multiply_world, 0x402D: _translate_world, 0x402E: _scale_world, 0x402F: _rotate_world,
    0x4030: _set_page, 0x4031: _reset_clip, 0x4032: _set_clip_rect, 0x4033: _set_clip_path,
    0x4034: _set_clip_region, 0x4035: _offset_clip, 0x4036: _draw_driver_string,
}

__all__ = ["PlusPlayer", "NAMES", "argb"]
