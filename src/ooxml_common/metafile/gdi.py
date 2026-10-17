"""A GDI device context that draws into SVG: the player both metafile readers drive.

An EMF and a WMF are two spellings of the same thing -- a list of GDI calls -- so the
record readers (:mod:`.emf`, :mod:`.wmf`) only decode their records and call a
:class:`Player`, which keeps the device context GDI keeps (pen, brush, font, colours,
mapping mode, world transform, clip, current position, the saved-state stack, the open
path) and writes what each call draws as SVG.

**Coordinates.**  The SVG's user space is the metafile's *device* space: the reference
device's pixels for an EMF, the placeable header's units for a WMF.  A call's logical
coordinates are written as they are, with the logical-to-device matrix (world transform,
then the mapping mode's window-to-viewport map) as the element's ``transform``, so an
ellipse under a rotation is still an ellipse and a pen widens anisotropically under an
anisotropic map, as Windows draws it (measured, ``MM_ANISOTROPIC`` 1000 x 1000 onto
400 x 300: a 20-unit pen is 8 px wide on a vertical edge and 6 px on a horizontal one).
A path bracket and a clip region are kept in device coordinates, as GDI keeps them.

**What Windows draws** (PowerPoint for Microsoft 365's PDF export and slide show of 23
made-up metafiles, round 7; the brief's oracle results D3 and D4) is what the player
follows, where PowerPoint for Mac's player differs:

* a null pen (``PS_NULL``, ``NULL_PEN``) strokes nothing and a null brush fills nothing;
* every pen width is honoured, ``CREATEPEN``'s too, and is at least one device pixel;
  a ``CREATEPEN`` pen has round caps and mitred joins, a geometric pen's default is
  round and round;
* ``MODIFYWORLDTRANSFORM`` with ``MWT_SET`` (4) changes nothing;
* dash lengths include the caps: ``PS_DASH`` is three widths on and one off, ``PS_DOT``
  one and one (``CREATEPEN`` width 5 dashed: 15 pt dashes, 5 pt gaps; ``EXTCREATEPEN``
  width 6 flat ``PS_DASH`` ``[18 6]``, round ``PS_DOT`` dots 12 apart); a user style's
  entries are logical units (``10 5 2 5`` at width 4: ``[10 5 2 5]``);
* ``SETPOLYFILLMODE`` is honoured: ``ALTERNATE`` even-odd, ``WINDING`` nonzero;
* a shape inside a path bracket is added to the path, not drawn;
* a rectangle, rounded rectangle and ellipse fill exactly their box (no right/bottom
  pixel left out); a rounded rectangle's corner ellipse is ``w x h``, radii ``w/2, h/2``;
* a 1-bit DIB's palette is used, and an enlarged bitmap is smoothed on screen (the SVG
  default; Windows' PDF export draws sharp blocks, its slide show does not);
* escapement turns text, and ``EXTTEXTOUTW``'s ``Dx`` places each character; a top
  aligned string's baseline is the font's ascent below the reference point.

Never raises for any input: each record is played inside a guard, and a record that
cannot be read is named in :attr:`Player.skipped` rather than stopping the rest.
"""

from __future__ import annotations

import base64
import math
import struct
from dataclasses import dataclass, field, replace
from xml.sax.saxutils import escape

from . import dib

#: Caps on the work a hostile metafile can force.  Generous for real files: the largest
#: metafile in a normal deck has a few thousand records and tens of thousands of points.
MAX_GEOMETRY_POINTS = 500_000
MAX_OBJECTS = 65_536
MAX_SAVE_DEPTH = 1_024
MAX_OUTPUT_BYTES = 32 * 1024 * 1024
#: Total decoded pixels over every bitmap in one metafile.
MAX_TOTAL_PIXELS = 64_000_000
#: Characters drawn by one text call.
MAX_TEXT_CHARS = 8_192

#: The attribute on the root of every SVG drawn here, by which
#: :func:`ooxml_common.metafile.inline_metafile_images` recognises one.
MARKER = "data-ooxml-metafile"

Matrix = tuple  # (a, b, c, d, e, f): x' = a x + c y + e, y' = b x + d y + f
IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

# Mapping modes (wingdi.h).
MM_TEXT, MM_LOMETRIC, MM_HIMETRIC, MM_LOENGLISH, MM_HIENGLISH, MM_TWIPS = 1, 2, 3, 4, 5, 6
MM_ISOTROPIC, MM_ANISOTROPIC = 7, 8
#: Millimetres per logical unit of the fixed mapping modes, whose y axis points up.
_FIXED_MM = {MM_LOMETRIC: 0.1, MM_HIMETRIC: 0.01, MM_LOENGLISH: 0.254, MM_HIENGLISH: 0.0254,
             MM_TWIPS: 25.4 / 1440}

ALTERNATE, WINDING = 1, 2
TRANSPARENT, OPAQUE = 1, 2
AD_COUNTERCLOCKWISE, AD_CLOCKWISE = 1, 2
RGN_AND, RGN_OR, RGN_XOR, RGN_DIFF, RGN_COPY = 1, 2, 3, 4, 5

# Pen style bits.
PS_SOLID, PS_DASH, PS_DOT, PS_DASHDOT, PS_DASHDOTDOT, PS_NULL, PS_INSIDEFRAME = 0, 1, 2, 3, 4, 5, 6
PS_USERSTYLE, PS_ALTERNATE = 7, 8
PS_ENDCAP_MASK, PS_ENDCAP_SQUARE, PS_ENDCAP_FLAT = 0x0F00, 0x0100, 0x0200
PS_JOIN_MASK, PS_JOIN_BEVEL, PS_JOIN_MITER = 0xF000, 0x1000, 0x2000
PS_GEOMETRIC = 0x00010000
#: Dash patterns in pen widths, as drawn (caps included): measured on Windows.
_DASHES = {PS_DASH: (3, 1), PS_DOT: (1, 1), PS_DASHDOT: (3, 1, 1, 1), PS_DASHDOTDOT: (3, 1, 1, 1, 1, 1),
           PS_ALTERNATE: (1, 1)}

# Text alignment.
TA_UPDATECP, TA_RIGHT, TA_CENTER, TA_BOTTOM, TA_BASELINE = 1, 2, 6, 8, 24
ETO_OPAQUE, ETO_CLIPPED, ETO_GLYPH_INDEX, ETO_PDY = 0x2, 0x4, 0x10, 0x2000

#: Raster operations drawn: the source copied, or a rectangle filled.
SRCCOPY, BLACKNESS, WHITENESS, PATCOPY = 0x00CC0020, 0x00000042, 0x00FF0062, 0x00F00021
#: Raster operations whose result is the source wherever the destination is the slide's
#: background: drawn as a copy.  The rest are named in the warning.
_COPY_LIKE = {SRCCOPY, 0x00EE0086, 0x00660046, 0x008800C6, 0x00C000CA}  # SRCPAINT, SRCINVERT, SRCAND, MERGECOPY

_KAPPA = 0.5522847498307936


def mul(first: Matrix, then: Matrix) -> Matrix:
    """The matrix that applies ``first`` and then ``then``."""
    a1, b1, c1, d1, e1, f1 = first
    a2, b2, c2, d2, e2, f2 = then
    return (a1 * a2 + b1 * c2, a1 * b2 + b1 * d2, c1 * a2 + d1 * c2, c1 * b2 + d1 * d2,
            e1 * a2 + f1 * c2 + e2, e1 * b2 + f1 * d2 + f2)


def apply(m: Matrix, x: float, y: float) -> tuple[float, float]:
    return m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]


def invert(m: Matrix) -> Matrix | None:
    a, b, c, d, e, f = m
    det = a * d - b * c
    if not det or not math.isfinite(det):
        return None
    return (d / det, -b / det, -c / det, a / det, (c * f - d * e) / det, (b * e - a * f) / det)


def scale_of(m: Matrix) -> float:
    """How much the matrix scales a length, on average: the square root of its area."""
    return math.sqrt(abs(m[0] * m[3] - m[1] * m[2]))


def num(value: float) -> str:
    if not math.isfinite(value):
        return "0"
    rounded = round(value, 3)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.3f}".rstrip("0").rstrip(".")


def color(colorref: int) -> str:
    """A ``COLORREF`` (``0x00bbggrr``) as ``#rrggbb``."""
    return "#%02X%02X%02X" % (colorref & 0xFF, (colorref >> 8) & 0xFF, (colorref >> 16) & 0xFF)


# --------------------------------------------------------------------------------------
# Objects and state
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Pen:
    style: int = PS_SOLID
    width: float = 0.0
    color: str = "#000000"
    geometric: bool = False
    #: ``CREATEPEN``'s pen (round caps and joins), as opposed to ``EXTCREATEPEN``'s.
    plain: bool = True
    user_style: tuple = ()
    null: bool = False

    @property
    def kind(self) -> int:
        return self.style & 0x0F


@dataclass(frozen=True)
class Brush:
    kind: str = "solid"  # solid | null | hatch | pattern
    color: str = "#FFFFFF"
    hatch: int = 0
    #: A pattern brush's bitmap: (PNG bytes, width, height).
    image: tuple | None = None


@dataclass(frozen=True)
class Font:
    height: float = 0.0
    escapement: float = 0.0
    weight: int = 400
    italic: bool = False
    underline: bool = False
    strike: bool = False
    face: str = ""
    pitch_family: int = 0


@dataclass(frozen=True)
class Placeholder:
    """An object the player keeps a slot for and never draws with: a palette, a colour
    space, a region."""

    what: str


STOCK = {
    0: Brush("solid", "#FFFFFF"), 1: Brush("solid", "#C0C0C0"), 2: Brush("solid", "#808080"),
    3: Brush("solid", "#404040"), 4: Brush("solid", "#000000"), 5: Brush("null"),
    6: Pen(color="#FFFFFF"), 7: Pen(color="#000000"), 8: Pen(style=PS_NULL, null=True),
    18: Brush("solid", "#FFFFFF"), 19: Pen(color="#000000"),
}
for _font in (10, 11, 12, 13, 14, 16, 17):
    STOCK[_font] = Font(height=-16, face="Arial")


@dataclass(frozen=True)
class DC:
    pen: Pen = STOCK[7]
    brush: Brush = STOCK[0]
    font: Font = Font(height=-16, face="Arial")
    text_color: str = "#000000"
    bk_color: str = "#FFFFFF"
    bk_mode: int = OPAQUE
    fill_mode: int = ALTERNATE
    text_align: int = 0
    rop2: int = 13
    map_mode: int = MM_TEXT
    window_org: tuple = (0.0, 0.0)
    window_ext: tuple = (1.0, 1.0)
    viewport_org: tuple = (0.0, 0.0)
    viewport_ext: tuple = (1.0, 1.0)
    world: Matrix = IDENTITY
    clip: str | None = None
    position: tuple = (0.0, 0.0)
    miter_limit: float = 10.0
    arc_direction: int = AD_COUNTERCLOCKWISE


class Figure:
    """One subpath: a start point and segments, in whatever space its owner keeps."""

    __slots__ = ("start", "segments", "closed")

    def __init__(self, x: float, y: float):
        self.start = (x, y)
        self.segments: list[tuple] = []
        self.closed = False

    @property
    def end(self) -> tuple[float, float]:
        if not self.segments:
            return self.start
        last = self.segments[-1]
        return last[-2], last[-1]

    def mapped(self, m: Matrix) -> "Figure":
        out = Figure(*apply(m, *self.start))
        for seg in self.segments:
            points = [apply(m, seg[i], seg[i + 1]) for i in range(0, len(seg), 2)]
            out.segments.append(tuple(v for p in points for v in p))
        out.closed = self.closed
        return out


def path_data(figures: list[Figure]) -> str:
    parts = []
    for fig in figures:
        parts.append(f"M{num(fig.start[0])} {num(fig.start[1])}")
        for seg in fig.segments:
            parts.append(("L" if len(seg) == 2 else "C") + " ".join(num(v) for v in seg))
        if fig.closed:
            parts.append("Z")
    return "".join(parts)


def polyline_figure(points, closed=False) -> Figure | None:
    if not points:
        return None
    fig = Figure(*points[0])
    fig.segments = [tuple(p) for p in points[1:]]
    fig.closed = closed
    return fig


def bezier_figure(points) -> Figure | None:
    if not points:
        return None
    fig = Figure(*points[0])
    for i in range(1, len(points) - 2, 3):
        fig.segments.append((*points[i], *points[i + 1], *points[i + 2]))
    return fig


def rect_figure(l, t, r, b) -> Figure:
    fig = Figure(l, t)
    fig.segments = [(r, t), (r, b), (l, b)]
    fig.closed = True
    return fig


def arc_segments(cx, cy, rx, ry, start, sweep) -> list[tuple]:
    """Cubic Béziers along an ellipse from parametric angle ``start`` by ``sweep``
    (radians; positive turns clockwise on a y-down page)."""
    if not sweep:
        return []
    count = max(1, math.ceil(abs(sweep) / (math.pi / 2) - 1e-9))
    step = sweep / count
    k = 4 / 3 * math.tan(step / 4)
    out = []
    t = start
    for _ in range(count):
        c0, s0, c1, s1 = math.cos(t), math.sin(t), math.cos(t + step), math.sin(t + step)
        out.append((cx + rx * (c0 - k * s0), cy + ry * (s0 + k * c0),
                    cx + rx * (c1 + k * s1), cy + ry * (s1 - k * c1),
                    cx + rx * c1, cy + ry * s1))
        t += step
    return out


def ellipse_figure(l, t, r, b) -> Figure:
    cx, cy, rx, ry = (l + r) / 2, (t + b) / 2, abs(r - l) / 2, abs(b - t) / 2
    fig = Figure(cx + rx, cy)
    fig.segments = arc_segments(cx, cy, rx, ry, 0.0, 2 * math.pi)
    fig.closed = True
    return fig


def round_rect_figure(l, t, r, b, w, h) -> Figure:
    l, r = min(l, r), max(l, r)
    t, b = min(t, b), max(t, b)
    rx, ry = min(abs(w) / 2, (r - l) / 2), min(abs(h) / 2, (b - t) / 2)
    if rx <= 0 or ry <= 0:
        return rect_figure(l, t, r, b)
    fig = Figure(l + rx, t)
    hp = math.pi / 2
    fig.segments.append((r - rx, t))
    fig.segments += arc_segments(r - rx, t + ry, rx, ry, -hp, hp)
    fig.segments.append((r, b - ry))
    fig.segments += arc_segments(r - rx, b - ry, rx, ry, 0.0, hp)
    fig.segments.append((l + rx, b))
    fig.segments += arc_segments(l + rx, b - ry, rx, ry, hp, hp)
    fig.segments.append((l, t + ry))
    fig.segments += arc_segments(l + rx, t + ry, rx, ry, math.pi, hp)
    fig.closed = True
    return fig


# --------------------------------------------------------------------------------------
# The player
# --------------------------------------------------------------------------------------


class Stop(Exception):
    """A cap was reached: stop playing, keep what was drawn."""


class Player:
    """The device context and the SVG it draws.

    ``device`` is the reference device's pixels per millimetre (x, y), which the fixed
    mapping modes need; ``font_mapping`` is passed to
    :func:`ooxml_common.text.fontmap.font_family_value` for a font's ``font-family``.
    """

    def __init__(self, *, device_per_mm=(96 / 25.4, 96 / 25.4), font_mapping=None,
                 canvas=(0.0, 0.0, 1.0, 1.0)):
        self.dc = DC()
        self.stack: list[DC] = []
        self.objects: dict[int, object] = {}
        self.device_per_mm = device_per_mm
        self.font_mapping = font_mapping
        self.canvas = canvas  # device rectangle the SVG shows: x, y, w, h
        self.defs: list[str] = []
        self.body: list[str] = []
        self.size = 0
        self.drawn = 0
        self.points = 0
        self.pixels = 0
        self.skipped: dict[str, int] = {}
        self.truncated = False
        self.path: list[Figure] | None = None  # open bracket, device coordinates
        self.path_done: list[Figure] | None = None  # closed bracket, waiting to be used
        self.path_widened = False
        self._ids = 0
        self._open_clip: str | None = None
        self._run: tuple | None = None  # (key, [pieces]) of LINETOs drawn one by one
        self._patterns: dict[tuple, str] = {}
        self._matrix_cache: tuple | None = None
        self.id_prefix = "emf-"

    # ---- bookkeeping ------------------------------------------------------------------

    def skip(self, name: str) -> None:
        self.skipped[name] = self.skipped.get(name, 0) + 1

    def _id(self, prefix: str) -> str:
        """An id unique to this drawing (:attr:`id_prefix`), so that two metafiles drawn
        inline in one page (:func:`ooxml_common.metafile.inline_metafile_images`) never
        share one."""
        self._ids += 1
        return f"{self.id_prefix}{prefix}{self._ids}"

    def count_points(self, n: int) -> None:
        self.points += n
        if self.points > MAX_GEOMETRY_POINTS:
            self.truncated = True
            raise Stop

    def _write(self, text: str, *, drawn: bool = True) -> None:
        self.size += len(text)
        if self.size > MAX_OUTPUT_BYTES:
            self.truncated = True
            raise Stop
        clip = self.dc.clip
        if clip != self._open_clip:
            if self._open_clip is not None:
                self.body.append("</g>")
            if clip is not None:
                self.body.append(f'<g clip-path="url(#{clip})">')
            self._open_clip = clip
        self.body.append(text)
        if drawn:
            self.drawn += 1

    def _def(self, text: str) -> None:
        self.size += len(text)
        if self.size > MAX_OUTPUT_BYTES:
            self.truncated = True
            raise Stop
        self.defs.append(text)

    def flush(self) -> None:
        if self._run is not None:
            key, pieces = self._run
            self._run = None
            self._write(f'<path d="{"".join(pieces)}"{key}/>')

    def svg(self, width: float, height: float) -> bytes:
        self.flush()
        if self._open_clip is not None:
            self.body.append("</g>")
            self._open_clip = None
        x, y, w, h = self.canvas
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="{num(width)}" '
                f'height="{num(height)}" viewBox="{num(x)} {num(y)} {num(w)} {num(h)}" '
                f'preserveAspectRatio="none" {MARKER}="gdi">')
        defs = f"<defs>{''.join(self.defs)}</defs>" if self.defs else ""
        return (head + defs + "".join(self.body) + "</svg>").encode("utf-8")

    # ---- mapping ----------------------------------------------------------------------

    def page_matrix(self) -> Matrix:
        dc = self.dc
        wox, woy = dc.window_org
        vox, voy = dc.viewport_org
        mode = dc.map_mode
        if mode in (MM_ANISOTROPIC, MM_ISOTROPIC):
            wex, wey = dc.window_ext
            vex, vey = dc.viewport_ext
            sx = vex / wex if wex else 1.0
            sy = vey / wey if wey else 1.0
            if mode == MM_ISOTROPIC:
                mag = min(abs(sx), abs(sy))
                sx, sy = math.copysign(mag, sx), math.copysign(mag, sy)
        elif mode in _FIXED_MM:
            unit = _FIXED_MM[mode]
            sx, sy = unit * self.device_per_mm[0], -unit * self.device_per_mm[1]
        else:
            sx, sy = 1.0, 1.0
        return (sx, 0.0, 0.0, sy, vox - wox * sx, voy - woy * sy)

    def matrix(self) -> Matrix:
        """Logical to device: the world transform, then the page's map."""
        dc = self.dc
        key = (dc.world, dc.map_mode, dc.window_org, dc.window_ext, dc.viewport_org, dc.viewport_ext)
        if self._matrix_cache is None or self._matrix_cache[0] != key:
            self._matrix_cache = (key, mul(dc.world, self.page_matrix()))
        return self._matrix_cache[1]

    def set(self, **changes) -> None:
        self.dc = replace(self.dc, **changes)

    def set_world(self, m: Matrix) -> bool:
        if not all(math.isfinite(v) for v in m):
            return False
        self.set(world=tuple(float(v) for v in m))
        return True

    def modify_world(self, m: Matrix, mode: int) -> bool:
        if not all(math.isfinite(v) for v in m):
            return False
        if mode == 1:
            self.set(world=IDENTITY)
        elif mode == 2:
            self.set(world=mul(m, self.dc.world))
        elif mode == 3:
            self.set(world=mul(self.dc.world, m))
        else:
            # 4 (MWT_SET) is in MS-EMF, but Windows' player leaves the transform as it
            # is (measured: a rectangle after MWT_SET translate (20, 20) at (0, 0)).
            return False
        return True

    # ---- state stack and objects --------------------------------------------------------

    def save_dc(self) -> None:
        if len(self.stack) >= MAX_SAVE_DEPTH:
            self.skip("SAVEDC beyond the depth cap")
            return
        self.stack.append(self.dc)

    def restore_dc(self, which: int) -> None:
        if which < 0:
            depth = len(self.stack) + which
        else:
            depth = which - 1
        if depth < 0 or depth >= len(self.stack):
            return
        self.flush()
        self.dc = self.stack[depth]
        del self.stack[depth:]

    def create(self, index: int, obj) -> None:
        if 0 <= index < MAX_OBJECTS:
            self.objects[index] = obj

    def select(self, index: int) -> None:
        obj = STOCK.get(index & 0x7FFFFFFF) if index & 0x80000000 else self.objects.get(index)
        if isinstance(obj, Pen):
            self.flush()
            self.set(pen=obj)
        elif isinstance(obj, Brush):
            self.set(brush=obj)
        elif isinstance(obj, Font):
            self.set(font=obj)

    def delete(self, index: int) -> None:
        self.objects.pop(index, None)

    # ---- paint ------------------------------------------------------------------------

    def _visible(self) -> bool:
        return self.dc.rop2 != 11  # R2_NOP draws nothing

    def _pen_color(self) -> str:
        rop = self.dc.rop2
        return "#000000" if rop == 1 else "#FFFFFF" if rop == 16 else self.dc.pen.color

    def stroke_attrs(self, m: Matrix, *, device: Matrix | None = None) -> str | None:
        """``stroke-*`` attributes of the current pen for a shape in the space of ``m``
        (logical to device), or ``None`` for no stroke.  ``device`` is given for a path
        already in device space: the matrix its logical width is scaled by."""
        pen = self.dc.pen
        if pen.null or pen.kind == PS_NULL:
            return None
        scale = scale_of(m)
        if not scale:
            return None
        pixel = 1 / scale  # one device pixel in the shape's units
        if not pen.geometric and not pen.plain or pen.width <= 0:
            width = pixel
        else:
            width = pen.width * (scale_of(device) if device is not None else 1.0)
            width = max(width, pixel)
        if pen.plain or not pen.geometric:
            # Measured on Windows: round ends, mitred corners (a rectangle's corners are
            # square, a polyline's ends round).
            cap, join = "round", "miter"
        else:
            cap = {PS_ENDCAP_SQUARE: "square", PS_ENDCAP_FLAT: "butt"}.get(pen.style & PS_ENDCAP_MASK, "round")
            join = {PS_JOIN_BEVEL: "bevel", PS_JOIN_MITER: "miter"}.get(pen.style & PS_JOIN_MASK, "round")
        out = f' stroke="{self._pen_color()}" stroke-width="{num(width)}"'
        if cap != "butt":
            out += f' stroke-linecap="{cap}"'
        if join != "miter":
            out += f' stroke-linejoin="{join}"'
        elif self.dc.miter_limit != 4:
            out += f' stroke-miterlimit="{num(max(self.dc.miter_limit, 1))}"'
        dashes = None
        if pen.kind in _DASHES:
            dashes = [v * width for v in _DASHES[pen.kind]]
        elif pen.kind == PS_USERSTYLE and pen.user_style:
            unit = 1.0 if pen.geometric else pixel
            if device is not None:
                unit *= scale_of(device)
            dashes = [v * unit for v in pen.user_style]
        if dashes and sum(dashes) > 0:
            if cap != "butt":
                # GDI's dash includes its caps; SVG adds them outside the dash.
                dashes = [max(v - width, 0.0) if i % 2 == 0 else v + width for i, v in enumerate(dashes)]
            if len(dashes) % 2:
                dashes = dashes * 2
            out += f' stroke-dasharray="{" ".join(num(v) for v in dashes)}"'
        return out

    def fill_attrs(self, m: Matrix, brush: Brush | None = None) -> list[str]:
        """``fill`` attribute strings of the brush, one per painted layer (an opaque hatch
        is its background, then its lines); empty for no fill."""
        brush = brush or self.dc.brush
        rule = ' fill-rule="evenodd"' if self.dc.fill_mode == ALTERNATE else ""
        if brush.kind == "solid":
            fill = "#000000" if self.dc.rop2 == 1 else "#FFFFFF" if self.dc.rop2 == 16 else brush.color
            return [f' fill="{fill}"{rule}']
        if brush.kind == "hatch":
            layers = []
            if self.dc.bk_mode == OPAQUE:
                layers.append(f' fill="{self.dc.bk_color}"{rule}')
            layers.append(f' fill="url(#{self._hatch(brush, m)})"{rule}')
            return layers
        if brush.kind == "pattern" and brush.image is not None:
            return [f' fill="url(#{self._image_pattern(brush, m)})"{rule}']
        return []

    def _pattern_transform(self, m: Matrix) -> str:
        inverse = invert(m)
        if inverse is None or inverse == IDENTITY:
            return ""
        return f' patternTransform="matrix({" ".join(num(v) for v in inverse)})"'

    def _hatch(self, brush: Brush, m: Matrix) -> str:
        """GDI's hatches are 8 x 8 device pixels, one pixel wide."""
        key = ("h", brush.hatch, brush.color, m)
        if key in self._patterns:
            return self._patterns[key]
        pid = self._id("h")
        horizontal, vertical = "M0 0h8v1h-8z", "M0 0h1v8h-1z"
        down = "".join(f"M{i} {i}h1v1h-1z" for i in range(8))
        up = "".join(f"M{7 - i} {i}h1v1h-1z" for i in range(8))
        d = {0: horizontal, 1: vertical, 2: down, 3: up, 4: horizontal + vertical, 5: down + up}.get(
            brush.hatch, horizontal)
        self._def(f'<pattern id="{pid}" patternUnits="userSpaceOnUse" width="8" height="8"'
                  f'{self._pattern_transform(m)}><path d="{d}" fill="{brush.color}"/></pattern>')
        self._patterns[key] = pid
        return pid

    def _image_pattern(self, brush: Brush, m: Matrix) -> str:
        key = ("p", id(brush.image), m)
        if key in self._patterns:
            return self._patterns[key]
        data, w, h = brush.image
        pid = self._id("p")
        href = "data:image/png;base64," + base64.b64encode(data).decode("ascii")
        self._def(f'<pattern id="{pid}" patternUnits="userSpaceOnUse" width="{w}" height="{h}"'
                  f'{self._pattern_transform(m)}><image width="{w}" height="{h}" href="{href}"/></pattern>')
        self._patterns[key] = pid
        return pid

    @staticmethod
    def _transform(m: Matrix) -> str:
        if m == IDENTITY:
            return ""
        return f' transform="matrix({" ".join(num(v) for v in m)})"'

    def paint(self, figures: list[Figure], *, fill: bool, stroke: bool, m: Matrix | None = None,
              device: Matrix | None = None) -> None:
        """Draw figures in the space of ``m`` (default: the logical space) with the brush
        and the pen, as GDI does: the interior first, then the outline."""
        figures = [f for f in figures if f is not None]
        if not figures or not self._visible():
            return
        self.flush()
        m = self.matrix() if m is None else m
        d = path_data(figures)
        transform = self._transform(m)
        layers = self.fill_attrs(m) if fill else []
        stroke_attrs = self.stroke_attrs(m, device=device) if stroke else None
        if not layers and stroke_attrs is None:
            return
        if not layers:
            self._write(f'<path d="{d}"{transform} fill="none"{stroke_attrs}/>')
            return
        for i, layer in enumerate(layers):
            last = i == len(layers) - 1
            self._write(f'<path d="{d}"{transform}{layer}{stroke_attrs if last and stroke_attrs else ""}/>')

    def segment(self, x0, y0, x1, y1) -> None:
        """One ``LINETO``: stroked on its own, caps at both ends, as GDI draws it."""
        if not self._visible():
            return
        m = self.matrix()
        stroke = self.stroke_attrs(m)
        if stroke is None:
            return
        key = f'{self._transform(m)} fill="none"{stroke}'
        piece = f"M{num(x0)} {num(y0)}L{num(x1)} {num(y1)}"
        if self._run is not None and self._run[0] == key:
            self._run[1].append(piece)
        else:
            self.flush()
            self._run = (key, [piece])

    # ---- current position and paths -----------------------------------------------------

    def in_path(self) -> bool:
        return self.path is not None

    def _path_figure(self) -> Figure:
        """The open figure of the bracket, started at the current position if needed."""
        assert self.path is not None
        if not self.path or self.path[-1].closed:
            x, y = apply(self.matrix(), *self.dc.position)
            self.path.append(Figure(x, y))
        return self.path[-1]

    def add_to_path(self, figure: Figure | None) -> None:
        if figure is None or self.path is None:
            return
        self.path.append(figure.mapped(self.matrix()))

    def move_to(self, x, y) -> None:
        self.set(position=(x, y))
        if self.path is not None:
            dx, dy = apply(self.matrix(), x, y)
            if self.path and not self.path[-1].segments and not self.path[-1].closed:
                self.path[-1] = Figure(dx, dy)
            else:
                self.path.append(Figure(dx, dy))

    def line_to(self, x, y) -> None:
        x0, y0 = self.dc.position
        self.set(position=(x, y))
        if self.path is not None:
            self._path_figure().segments.append(apply(self.matrix(), x, y))
        else:
            self.segment(x0, y0, x, y)

    def poly_to(self, points, bezier: bool) -> None:
        """``POLYLINETO`` / ``POLYBEZIERTO``: from the current position on."""
        if not points:
            return
        self.count_points(len(points))
        start = self.dc.position
        if bezier:
            points = points[: len(points) // 3 * 3]
            if not points:
                return
        self.set(position=tuple(points[-1]))
        if self.path is not None:
            fig = self._path_figure()
            m = self.matrix()
            mapped = [apply(m, *p) for p in points]
            if bezier:
                for i in range(0, len(mapped) - 2, 3):
                    fig.segments.append((*mapped[i], *mapped[i + 1], *mapped[i + 2]))
            else:
                fig.segments.extend(mapped)
            return
        fig = Figure(*start)
        if bezier:
            for i in range(0, len(points) - 2, 3):
                fig.segments.append((*points[i], *points[i + 1], *points[i + 2]))
        else:
            fig.segments = [tuple(p) for p in points]
        self.paint([fig], fill=False, stroke=True)

    def shape(self, figures: list[Figure], *, fill: bool, stroke: bool = True) -> None:
        """A drawing call outside a bracket paints; inside one it adds its figures."""
        if self.path is not None:
            for fig in figures:
                self.add_to_path(fig)
            return
        self.paint(figures, fill=fill, stroke=stroke)

    def begin_path(self) -> None:
        self.flush()
        self.path = []
        self.path_done = None
        self.path_widened = False

    def end_path(self) -> None:
        if self.path is not None:
            self.path_done = self.path
            self.path = None

    def abort_path(self) -> None:
        self.path = None
        self.path_done = None

    def close_figure(self) -> None:
        if self.path and not self.path[-1].closed:
            fig = self.path[-1]
            fig.closed = True
            inverse = invert(self.matrix())
            if inverse is not None:
                self.set(position=apply(inverse, *fig.start))

    def use_path(self, *, fill: bool, stroke: bool) -> None:
        figures = self.path_done
        self.path_done = None
        if not figures:
            return
        if fill and not stroke and self.path_widened:
            # FILLPATH after WIDENPATH fills the pen's outline with the brush: drawn as
            # the pen's stroke in the brush's colour.
            self.paint_widened(figures)
            return
        if fill:
            for fig in figures:
                fig.closed = True
        self.paint(figures, fill=fill, stroke=stroke, m=IDENTITY, device=self.matrix())

    def paint_widened(self, figures) -> None:
        brush = self.dc.brush
        if brush.kind != "solid":
            return
        saved = self.dc
        self.set(pen=replace(self.dc.pen, color=brush.color, style=self.dc.pen.style & ~0x0F))
        self.paint(figures, fill=False, stroke=True, m=IDENTITY, device=self.matrix())
        self.dc = replace(self.dc, pen=saved.pen)

    # ---- clipping -----------------------------------------------------------------------

    def _clip(self, d: str, rule: str, parent: str | None) -> str:
        cid = self._id("c")
        chained = f' clip-path="url(#{parent})"' if parent else ""
        self._def(f'<clipPath id="{cid}" clipPathUnits="userSpaceOnUse"{chained}>'
                  f'<path d="{d}"{rule}/></clipPath>')
        return cid

    def _everything(self) -> str:
        x, y, w, h = self.canvas
        margin = 4 * max(w, h, 1.0) + 100000
        return path_data([rect_figure(x - margin, y - margin, x + w + margin, y + h + margin)])

    def set_clip(self, figures: list[Figure] | None, mode: int, *, evenodd: bool = False) -> bool:
        """Combine device-space figures with the clip; ``None`` figures with ``RGN_COPY``
        resets it.  ``False`` for a combination not drawn (OR, XOR)."""
        self.flush()
        current = self.dc.clip
        if mode == RGN_COPY:
            if not figures:
                self.set(clip=None)
                return True
            self.set(clip=self._clip(path_data(figures), ' clip-rule="evenodd"' if evenodd else "", None))
            return True
        if not figures:
            if mode == RGN_AND:
                self.set(clip=self._clip("M0 0Z", "", None))
            return mode in (RGN_AND, RGN_DIFF, RGN_OR)
        if mode == RGN_AND:
            self.set(clip=self._clip(path_data(figures), ' clip-rule="evenodd"' if evenodd else "", current))
            return True
        if mode == RGN_DIFF:
            self.set(clip=self._clip(self._everything() + path_data(figures), ' clip-rule="evenodd"', current))
            return True
        if mode == RGN_OR and current is None:
            return True
        return False

    def clip_rect(self, l, t, r, b, *, exclude: bool) -> None:
        fig = rect_figure(l, t, r, b).mapped(self.matrix())
        self.set_clip([fig], RGN_DIFF if exclude else RGN_AND)

    # ---- pictures -----------------------------------------------------------------------

    def image(self, dest, src, header: bytes, bits: bytes, rop: int, *, alpha: float | None = None,
              transparent: int | None = None) -> None:
        """A bitmap from a DIB: ``dest`` (x, y, w, h) logical, ``src`` (x, y, w, h) in the
        bitmap's pixels (``y`` from the bottom for a bottom-up DIB, as GDI counts it)."""
        if not self._visible():
            return
        x, y, w, h = dest
        if rop == BLACKNESS or rop == WHITENESS:
            self.flush()
            m = self.matrix()
            fill = "#000000" if rop == BLACKNESS else "#FFFFFF"
            self._write(f'<path d="{path_data([rect_figure(x, y, x + w, y + h)])}"{self._transform(m)} fill="{fill}"/>')
            return
        if rop == PATCOPY or not header:
            if rop == PATCOPY:
                self.pattern_rect(x, y, w, h)
            else:
                self.skip(f"raster operation 0x{rop:08X} without a bitmap")
            return
        if rop not in _COPY_LIKE and alpha is None and transparent is None:
            self.skip(f"raster operation 0x{rop:08X}")
            return
        if len(header) >= 12:
            bw, bh = struct.unpack_from("<ii", header, 4)
            self.pixels += abs(bw) * abs(bh)
            if self.pixels > MAX_TOTAL_PIXELS:
                self.skip("bitmaps beyond the pixel cap")
                return
        png = None
        if transparent is not None or alpha is not None:
            decoded = dib.decode_dib(header, bits)
            if decoded is not None:
                rgba = decoded.rgba
                has_alpha = decoded.has_alpha
                if transparent is not None:
                    key = bytes((transparent & 0xFF, (transparent >> 8) & 0xFF, (transparent >> 16) & 0xFF))
                    for i in range(0, len(rgba), 4):
                        if rgba[i : i + 3] == key:
                            rgba[i + 3] = 0
                    has_alpha = True
                png = (dib.encode_png(decoded.width, decoded.height, rgba, has_alpha=has_alpha),
                       "image/png", decoded.width, decoded.height)
        if png is None:
            image = dib.dib_to_image(header, bits)
            if image is None:
                self.skip("a bitmap that cannot be decoded")
                return
            bw, bh = struct.unpack_from("<ii", header, 4)
            png = (image.data, image.mime_type, abs(bw), abs(bh))
        data, mime, bw, bh = png
        bottom_up = struct.unpack_from("<i", header, 8)[0] > 0
        sx, sy, sw, sh = src
        if not sw or not sh:
            sx, sy, sw, sh = 0, 0, bw, bh
        top = bh - sy - sh if bottom_up else sy
        self.flush()
        local = (w / sw, 0.0, 0.0, h / sh, x, y)
        m = mul(local, self.matrix())
        href = f"data:{mime};base64," + base64.b64encode(data).decode("ascii")
        opacity = f' opacity="{num(alpha)}"' if alpha is not None and alpha < 1 else ""
        img = f'<image width="{bw}" height="{bh}" preserveAspectRatio="none" href="{href}"/>'
        if (sx, top, sw, sh) != (0, 0, bw, bh):
            img = (f'<svg width="{num(abs(sw))}" height="{num(abs(sh))}" viewBox="{num(sx)} {num(top)} '
                   f'{num(abs(sw))} {num(abs(sh))}" preserveAspectRatio="none">{img}</svg>')
            if sw < 0 or sh < 0:
                m = mul((math.copysign(1, sw), 0.0, 0.0, math.copysign(1, sh), 0.0, 0.0), m)
        self._write(f"<g{self._transform(m)}{opacity}>{img}</g>")

    def pattern_rect(self, x, y, w, h) -> None:
        saved = self.dc.pen
        self.set(pen=STOCK[8])
        self.paint([rect_figure(x, y, x + w, y + h)], fill=True, stroke=False)
        self.set(pen=saved)

    def pixel(self, x, y, colorref: int) -> None:
        self.flush()
        m = self.matrix()
        dx, dy = apply(m, x, y)
        self._write(f'<rect x="{num(dx)}" y="{num(dy)}" width="1" height="1" fill="{color(colorref)}"/>')

    def device_rects(self, rects, brush: Brush) -> None:
        """Rectangles in device pixels filled with ``brush`` (a region)."""
        figures = [rect_figure(*r) for r in rects]
        if not figures:
            return
        self.flush()
        layers = self.fill_attrs(IDENTITY, brush)
        for layer in layers:
            self._write(f'<path d="{path_data(figures)}"{layer}/>')

    def gradient_rect(self, l, t, r, b, c0: str, c1: str, vertical: bool) -> None:
        self.flush()
        m = self.matrix()
        gid = self._id("g")
        x1, y1, x2, y2 = (l, t, l, b) if vertical else (l, t, r, t)
        self._def(f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="{num(x1)}" y1="{num(y1)}" '
                  f'x2="{num(x2)}" y2="{num(y2)}"><stop offset="0" stop-color="{c0}"/>'
                  f'<stop offset="1" stop-color="{c1}"/></linearGradient>')
        self._write(f'<path d="{path_data([rect_figure(l, t, r, b)])}"{self._transform(m)} fill="url(#{gid})"/>')

    def flat_polygon(self, points, fill: str) -> None:
        self.flush()
        m = self.matrix()
        self._write(f'<path d="{path_data([polyline_figure(points, True)])}"{self._transform(m)} fill="{fill}"/>')

    # ---- text ---------------------------------------------------------------------------

    def text(self, x, y, text: str, dx: list | None, options: int, rect=None, dy: list | None = None) -> None:
        if not self._visible():
            return
        dc = self.dc
        font = dc.font
        m = self.matrix()
        if options & ETO_OPAQUE and rect is not None:
            l, t, r, b = rect
            if r > l and b > t:
                self.flush()
                self._write(f'<path d="{path_data([rect_figure(l, t, r, b)])}"{self._transform(m)} '
                            f'fill="{dc.bk_color}"/>', drawn=True)
        text = "".join(ch for ch in text[:MAX_TEXT_CHARS] if ch >= " " or ch == "\t")
        if not text.strip():
            return
        self.flush()
        if dc.text_align & TA_UPDATECP:
            x, y = dc.position
        px, py = apply(m, x, y)
        xs = math.hypot(m[0], m[1]) or 1.0
        ys = math.hypot(m[2], m[3]) or 1.0
        ascent, descent = _vertical_metrics(font.face)
        if font.height < 0:
            em = -font.height
        elif font.height > 0:
            em = font.height / (ascent + descent)
        else:
            em = 16.0
        size = em * ys
        # Character advances along the baseline, in device pixels.
        advances = None
        if dx:
            advances = []
            units = _code_units(text)
            k = 0
            for count in units:
                advances.append(sum(dx[k : k + count]) * xs)
                k += count
        align = dc.text_align & TA_CENTER
        vertical = dc.text_align & TA_BASELINE
        if vertical == TA_BASELINE:
            base = 0.0
        elif vertical == TA_BOTTOM:
            base = -descent * size
        else:
            base = ascent * size
        total = sum(advances) if advances else None
        start = 0.0
        anchor = ""
        if total is not None:
            if align == TA_CENTER:
                start = -total / 2
            elif align == TA_RIGHT:
                start = -total
        elif align == TA_CENTER:
            anchor = ' text-anchor="middle"'
        elif align == TA_RIGHT:
            anchor = ' text-anchor="end"'
        angle = font.escapement / 10
        group = f"translate({num(px)} {num(py)})" + (f" rotate({num(-angle)})" if angle else "")
        from ..text.fontmap import font_family_value

        family = font_family_value([font.face or "Arial"], self.font_mapping)
        generic = _generic(font.pitch_family)
        if family and not family.endswith(generic) and font.pitch_family & 0xF0:
            family = family.rsplit(", ", 1)[0] + ", " + generic
        attrs = [f'font-size="{num(size)}"']
        if family:
            attrs.append(f'font-family="{escape(family, {chr(34): "&quot;"})}"')
        if font.weight >= 600:
            attrs.append('font-weight="bold"')
        if font.italic:
            attrs.append('font-style="italic"')
        deco = " ".join(n for n, on in (("underline", font.underline), ("line-through", font.strike)) if on)
        if deco:
            attrs.append(f'text-decoration="{deco}"')
        parts = [f'<g transform="{group}">']
        if dc.bk_mode == OPAQUE and total:
            parts.append(f'<rect x="{num(start)}" y="{num(base - ascent * size)}" width="{num(total)}" '
                         f'height="{num((ascent + descent) * size)}" fill="{dc.bk_color}"/>')
        if advances:
            xs_list, pos = [], start
            for advance in advances:
                xs_list.append(num(pos))
                pos += advance
            xattr = " ".join(xs_list)
        else:
            xattr = "0"
        parts.append(f'<text x="{xattr}" y="{num(base)}" fill="{dc.text_color}" {" ".join(attrs)}'
                     f'{anchor} xml:space="preserve">{escape(text)}</text></g>')
        self._write("".join(parts))
        if dc.text_align & TA_UPDATECP and total is not None:
            inverse = invert(m)
            if inverse is not None:
                rad = math.radians(angle)
                ex, ey = px + total * math.cos(rad), py - total * math.sin(rad)
                self.set(position=apply(inverse, ex, ey))


def _code_units(text: str) -> list[int]:
    return [2 if ord(ch) > 0xFFFF else 1 for ch in text]


def _generic(pitch_family: int) -> str:
    return {0x10: "serif", 0x30: "monospace", 0x40: "cursive", 0x50: "fantasy"}.get(pitch_family & 0xF0, "sans-serif")


def _vertical_metrics(face: str) -> tuple[float, float]:
    """Ascent and descent as fractions of the em: the face's measured table, else
    Arial's (1854 and 434 of 2048)."""
    try:
        from ..text.fontmap import metrics_for

        metrics = metrics_for(face) if face else None
    except Exception:  # a table lookup must never stop the drawing
        metrics = None
    if metrics is not None and metrics.units_per_em:
        return metrics.ascender / metrics.units_per_em, abs(metrics.descender) / metrics.units_per_em
    return 1854 / 2048, 434 / 2048
