"""An Enhanced Metafile's GDI records played into SVG (MS-EMF, 2.3).

The header's ``rclFrame`` -- the picture's extent in hundredths of a millimetre -- is
what is mapped onto the picture's box; ``rclBounds`` plays no part (measured: a frame
twice the drawing's size draws it at half size, a frame starting at (50, 50) px moves it
by that, tight bounds change nothing).  The frame is converted to the reference device's
pixels with ``szlDevice / szlMillimeters`` -- not ``szlMicrometers``, which Windows'
drawing ruled out to a tenth of a point -- and is **inclusive**: its device extent plus
one pixel fills the box.  That is the 0.9975 Windows draws a 400 x 300 px frame at in a
400 x 300 pt box (px 40 at 139.9 pt, px 360 at 459.1; 240 at y 299.40 pt), where Mac
PowerPoint maps the frame exactly.

EMF+ (records carried in ``EMR_COMMENT``) is played by :mod:`.emfplus`, as Windows
PowerPoint plays it: once a file's first EMF+ comment is read, its GDI records are not
drawn -- a dual file's are the fallback for players without EMF+, an EMF+-only file's
are not meant to be drawn -- except those that follow an ``EmfPlusGetDC``, until the
next EMF+ record.  A file whose EMF+ records draw nothing at all is drawn from its GDI
records instead (``gdi_only``), and :attr:`MetafileDrawing.gdi_fallback` says so.
"""

from __future__ import annotations

import math
import struct

from . import gdi
from .dib import split_packed_dib
from .emfplus import PlusPlayer
from .gdi import Brush, Figure, Font, Pen, Placeholder, Player, Stop

EMF_SIGNATURE = 0x464D4520
EMF_PLUS_IDENTIFIER = 0x2B464D45
MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_RECORD_BYTES = 4 * 1024 * 1024
MAX_RECORDS = 100_000

NAMES = {
    1: "HEADER", 2: "POLYBEZIER", 3: "POLYGON", 4: "POLYLINE", 5: "POLYBEZIERTO", 6: "POLYLINETO",
    7: "POLYPOLYLINE", 8: "POLYPOLYGON", 9: "SETWINDOWEXTEX", 10: "SETWINDOWORGEX", 11: "SETVIEWPORTEXTEX",
    12: "SETVIEWPORTORGEX", 13: "SETBRUSHORGEX", 14: "EOF", 15: "SETPIXELV", 16: "SETMAPPERFLAGS",
    17: "SETMAPMODE", 18: "SETBKMODE", 19: "SETPOLYFILLMODE", 20: "SETROP2", 21: "SETSTRETCHBLTMODE",
    22: "SETTEXTALIGN", 23: "SETCOLORADJUSTMENT", 24: "SETTEXTCOLOR", 25: "SETBKCOLOR", 26: "OFFSETCLIPRGN",
    27: "MOVETOEX", 28: "SETMETARGN", 29: "EXCLUDECLIPRECT", 30: "INTERSECTCLIPRECT", 31: "SCALEVIEWPORTEXTEX",
    32: "SCALEWINDOWEXTEX", 33: "SAVEDC", 34: "RESTOREDC", 35: "SETWORLDTRANSFORM", 36: "MODIFYWORLDTRANSFORM",
    37: "SELECTOBJECT", 38: "CREATEPEN", 39: "CREATEBRUSHINDIRECT", 40: "DELETEOBJECT", 41: "ANGLEARC",
    42: "ELLIPSE", 43: "RECTANGLE", 44: "ROUNDRECT", 45: "ARC", 46: "CHORD", 47: "PIE", 48: "SELECTPALETTE",
    49: "CREATEPALETTE", 50: "SETPALETTEENTRIES", 51: "RESIZEPALETTE", 52: "REALIZEPALETTE", 53: "EXTFLOODFILL",
    54: "LINETO", 55: "ARCTO", 56: "POLYDRAW", 57: "SETARCDIRECTION", 58: "SETMITERLIMIT", 59: "BEGINPATH",
    60: "ENDPATH", 61: "CLOSEFIGURE", 62: "FILLPATH", 63: "STROKEANDFILLPATH", 64: "STROKEPATH",
    65: "FLATTENPATH", 66: "WIDENPATH", 67: "SELECTCLIPPATH", 68: "ABORTPATH", 70: "COMMENT", 71: "FILLRGN",
    72: "FRAMERGN", 73: "INVERTRGN", 74: "PAINTRGN", 75: "EXTSELECTCLIPRGN", 76: "BITBLT", 77: "STRETCHBLT",
    78: "MASKBLT", 79: "PLGBLT", 80: "SETDIBITSTODEVICE", 81: "STRETCHDIBITS", 82: "EXTCREATEFONTINDIRECTW",
    83: "EXTTEXTOUTA", 84: "EXTTEXTOUTW", 85: "POLYBEZIER16", 86: "POLYGON16", 87: "POLYLINE16",
    88: "POLYBEZIERTO16", 89: "POLYLINETO16", 90: "POLYPOLYLINE16", 91: "POLYPOLYGON16", 92: "POLYDRAW16",
    93: "CREATEMONOBRUSH", 94: "CREATEDIBPATTERNBRUSHPT", 95: "EXTCREATEPEN", 96: "POLYTEXTOUTA",
    97: "POLYTEXTOUTW", 98: "SETICMMODE", 99: "CREATECOLORSPACE", 100: "SETCOLORSPACE", 101: "DELETECOLORSPACE",
    102: "GLSRECORD", 103: "GLSBOUNDEDRECORD", 104: "PIXELFORMAT", 105: "DRAWESCAPE", 106: "EXTESCAPE",
    108: "SMALLTEXTOUT", 109: "FORCEUFIMAPPING", 110: "NAMEDESCAPE", 111: "COLORCORRECTPALETTE",
    112: "SETICMPROFILEA", 113: "SETICMPROFILEW", 114: "ALPHABLEND", 115: "SETLAYOUT", 116: "TRANSPARENTBLT",
    118: "GRADIENTFILL", 119: "SETLINKEDUFIS", 120: "SETTEXTJUSTIFICATION", 121: "COLORMATCHTOTARGETW",
    122: "CREATECOLORSPACEW",
}

#: Records with nothing to draw for an SVG: colour management, palettes, the brush
#: origin, stretch modes, font mapping hints, escapes.
_IGNORED = {13, 16, 21, 23, 28, 48, 50, 51, 52, 65, 98, 100, 101, 104, 105, 106, 109, 110, 111, 112, 113,
            119, 120, 121}


def is_emf(data: bytes) -> bool:
    if len(data) < 88:
        return False
    record_type, record_size = struct.unpack_from("<II", data, 0)
    return record_type == 1 and record_size >= 88 and struct.unpack_from("<I", data, 40)[0] == EMF_SIGNATURE


class Header:
    def __init__(self, data: bytes):
        size = struct.unpack_from("<I", data, 4)[0]
        self.bounds = struct.unpack_from("<4i", data, 8)
        self.frame = struct.unpack_from("<4i", data, 24)
        self.device = struct.unpack_from("<2i", data, 72)
        self.millimeters = struct.unpack_from("<2i", data, 80)
        self.size = size
        dev_x, dev_y = self.device
        mm_x, mm_y = self.millimeters
        if dev_x > 0 and dev_y > 0 and mm_x > 0 and mm_y > 0:
            self.per_mm = (dev_x / mm_x, dev_y / mm_y)
        else:
            self.per_mm = (96 / 25.4, 96 / 25.4)

    def canvas(self) -> tuple[float, float, float, float]:
        """The frame in device pixels, inclusive (``x, y, width, height``)."""
        l, t, r, b = self.frame
        if r > l and b > t:
            sx, sy = self.per_mm[0] / 100, self.per_mm[1] / 100
            return l * sx, t * sy, (r - l) * sx + 1, (b - t) * sy + 1
        l, t, r, b = self.bounds
        if r >= l and b >= t:
            return float(l), float(t), float(r - l + 1), float(b - t + 1)
        return 0.0, 0.0, 1.0, 1.0

    def natural_size(self) -> tuple[float, float]:
        """The frame's size at 96 px to the inch, the size Office gives the picture."""
        l, t, r, b = self.frame
        if r > l and b > t:
            return (r - l) / 2540 * 96, (b - t) / 2540 * 96
        _x, _y, w, h = self.canvas()
        return w, h


def play(data: bytes, *, font_mapping=None, gdi_only: bool = False, nesting: int = 0):
    """``(player, header, emf_plus)`` for EMF bytes, or ``None`` when they are not one.

    ``emf_plus`` is whether the file carries EMF+ records; unless ``gdi_only``, they are
    what is drawn (with the GDI records after an ``EmfPlusGetDC``)."""
    if not is_emf(data) or len(data) > MAX_INPUT_BYTES:
        return None
    header = Header(data)
    player = Player(device_per_mm=header.per_mm, font_mapping=font_mapping, canvas=header.canvas())
    reader = _Reader(player, gdi_only=gdi_only, nesting=nesting)
    offset = 0
    try:
        for _ in range(MAX_RECORDS):
            if offset + 8 > len(data):
                break
            record_type, record_size = struct.unpack_from("<II", data, offset)
            if record_size < 8 or record_size % 4 or record_size > MAX_RECORD_BYTES or offset + record_size > len(data):
                player.skip("a record whose size runs past the file (the rest is not read)")
                break
            if record_type == 14:
                break
            record = data[offset : offset + record_size]
            offset += record_size
            if record_type == 1:
                continue
            reader.record(record_type, record)
        else:
            player.truncated = True
    except Stop:
        pass
    return player, header, reader.emf_plus


class _Reader:
    def __init__(self, player: Player, *, gdi_only: bool = False, nesting: int = 0):
        self.p = player
        self.emf_plus = False
        self.gdi_only = gdi_only
        self.nesting = nesting
        #: The EMF+ player, from the first EMF+ comment on.
        self.plus: PlusPlayer | None = None
        self.handlers = {
            2: self.polybezier, 85: self.polybezier, 3: self.polygon, 86: self.polygon,
            4: self.polyline, 87: self.polyline, 5: self.polybezierto, 88: self.polybezierto,
            6: self.polylineto, 89: self.polylineto, 7: self.polypolyline, 90: self.polypolyline,
            8: self.polypolygon, 91: self.polypolygon, 56: self.polydraw, 92: self.polydraw,
            9: self.window_ext, 10: self.window_org, 11: self.viewport_ext, 12: self.viewport_org,
            31: self.scale_viewport, 32: self.scale_window, 15: self.set_pixel, 17: self.map_mode,
            18: self.bk_mode, 19: self.fill_mode, 20: self.rop2, 22: self.text_align, 24: self.text_color,
            25: self.bk_color, 27: self.moveto, 29: self.exclude_clip, 30: self.intersect_clip,
            33: self.save_dc, 34: self.restore_dc, 35: self.world, 36: self.modify_world,
            37: self.select, 38: self.create_pen, 39: self.create_brush, 40: self.delete,
            41: self.angle_arc, 42: self.ellipse, 43: self.rectangle, 44: self.round_rect,
            45: self.arc, 46: self.arc, 47: self.arc, 55: self.arc, 49: self.placeholder,
            99: self.placeholder, 122: self.placeholder, 54: self.lineto, 57: self.arc_direction,
            58: self.miter_limit, 59: self.begin_path, 60: self.end_path, 61: self.close_figure,
            62: self.fill_path, 63: self.stroke_and_fill_path, 64: self.stroke_path, 66: self.widen_path,
            67: self.select_clip_path, 68: self.abort_path, 70: self.comment, 71: self.fill_rgn,
            74: self.paint_rgn, 75: self.ext_select_clip_rgn, 76: self.bitblt, 77: self.stretchblt,
            80: self.set_dibits, 81: self.stretchdibits, 82: self.create_font, 83: self.text_a,
            84: self.text_w, 93: self.mono_brush, 94: self.dib_brush, 95: self.ext_pen,
            114: self.alphablend, 116: self.transparentblt, 118: self.gradient_fill, 115: self.set_layout,
        }

    def record(self, record_type: int, rec: bytes) -> None:
        if self.plus is not None and record_type != 70 and not self.plus.get_dc:
            return  # an EMF+ file's GDI records: not drawn (Windows)
        if record_type in _IGNORED:
            return
        handler = self.handlers.get(record_type)
        name = "EMR_" + NAMES.get(record_type, f"0x{record_type:X}")
        if handler is None:
            self.p.skip(name)
            return
        try:
            if handler(rec) is False:
                self.p.skip(name)
        except Stop:
            raise
        except Exception:  # a record that cannot be read is named, never fatal
            self.p.skip(name + " (unreadable)")

    # ---- points -------------------------------------------------------------------------

    def _points(self, rec: bytes, count_at: int, start: int, small: bool) -> list[tuple[int, int]]:
        count = struct.unpack_from("<I", rec, count_at)[0]
        size = 4 if small else 8
        count = min(count, (len(rec) - start) // size)
        self.p.count_points(count)
        fmt = "<" + ("h" if small else "i") * (2 * count)
        flat = struct.unpack_from(fmt, rec, start)
        return list(zip(flat[0::2], flat[1::2]))

    def _simple(self, rec: bytes) -> list[tuple[int, int]]:
        small = struct.unpack_from("<I", rec, 0)[0] in (85, 86, 87, 88, 89, 92)
        return self._points(rec, 24, 28, small)

    def polybezier(self, rec):
        points = self._simple(rec)
        if self.p.in_path():
            self.p.add_to_path(gdi.bezier_figure(points))
        else:
            self.p.paint([gdi.bezier_figure(points)], fill=False, stroke=True)

    def polygon(self, rec):
        points = self._simple(rec)
        self.p.shape([gdi.polyline_figure(points, closed=True)], fill=True)

    def polyline(self, rec):
        points = self._simple(rec)
        if self.p.in_path():
            self.p.add_to_path(gdi.polyline_figure(points))
        else:
            self.p.paint([gdi.polyline_figure(points)], fill=False, stroke=True)

    def polylineto(self, rec):
        self.p.poly_to(self._simple(rec), bezier=False)

    def polybezierto(self, rec):
        self.p.poly_to(self._simple(rec), bezier=True)

    def _poly_poly(self, rec):
        small = struct.unpack_from("<I", rec, 0)[0] in (90, 91)
        polys, total = struct.unpack_from("<II", rec, 24)
        polys = min(polys, (len(rec) - 32) // 4)
        counts = struct.unpack_from(f"<{polys}I", rec, 32)
        start = 32 + 4 * polys
        size = 4 if small else 8
        total = min(total, sum(counts), (len(rec) - start) // size)
        self.p.count_points(total)
        flat = struct.unpack_from("<" + ("h" if small else "i") * (2 * total), rec, start)
        points = list(zip(flat[0::2], flat[1::2]))
        out, k = [], 0
        for n in counts:
            out.append(points[k : k + n])
            k += n
        return [p for p in out if p]

    def polypolyline(self, rec):
        figures = [gdi.polyline_figure(p) for p in self._poly_poly(rec)]
        if self.p.in_path():
            for fig in figures:
                self.p.add_to_path(fig)
        else:
            self.p.paint(figures, fill=False, stroke=True)

    def polypolygon(self, rec):
        figures = [gdi.polyline_figure(p, closed=True) for p in self._poly_poly(rec)]
        self.p.shape(figures, fill=True)

    def polydraw(self, rec):
        small = struct.unpack_from("<I", rec, 0)[0] == 92
        points = self._points(rec, 24, 28, small)
        types = rec[28 + len(points) * (4 if small else 8):][: len(points)]
        p = self.p
        k = 0
        while k < len(points):
            kind = types[k] & 0x06 if k < len(types) else 2
            if kind == 6:
                p.move_to(*points[k])
                k += 1
            elif kind == 2:
                p.line_to(*points[k])
                k += 1
            elif kind == 4 and k + 2 < len(points):
                p.poly_to(points[k : k + 3], bezier=True)
                k += 2
                k += 1
            else:
                k += 1
                continue
            if k - 1 < len(types) and types[k - 1] & 0x01:
                if p.in_path():
                    p.close_figure()

    # ---- mapping ------------------------------------------------------------------------

    def _pair(self, rec):
        return struct.unpack_from("<ii", rec, 8)

    def window_ext(self, rec):
        x, y = self._pair(rec)
        if x and y:
            self.p.set(window_ext=(float(x), float(y)))

    def window_org(self, rec):
        self.p.set(window_org=tuple(float(v) for v in self._pair(rec)))

    def viewport_ext(self, rec):
        x, y = self._pair(rec)
        if x and y:
            self.p.set(viewport_ext=(float(x), float(y)))

    def viewport_org(self, rec):
        self.p.set(viewport_org=tuple(float(v) for v in self._pair(rec)))

    def _scaled(self, ext, rec):
        xn, xd, yn, yd = struct.unpack_from("<4i", rec, 8)
        if not xd or not yd or not xn or not yn:
            return None
        return ext[0] * xn / xd, ext[1] * yn / yd

    def scale_viewport(self, rec):
        ext = self._scaled(self.p.dc.viewport_ext, rec)
        if ext:
            self.p.set(viewport_ext=ext)

    def scale_window(self, rec):
        ext = self._scaled(self.p.dc.window_ext, rec)
        if ext:
            self.p.set(window_ext=ext)

    def map_mode(self, rec):
        mode = struct.unpack_from("<I", rec, 8)[0]
        if not 1 <= mode <= 8:
            return False
        self.p.set(map_mode=mode)

    def world(self, rec):
        return self.p.set_world(struct.unpack_from("<6f", rec, 8))

    def modify_world(self, rec):
        values = struct.unpack_from("<6fI", rec, 8)
        return self.p.modify_world(values[:6], values[6])

    # ---- state --------------------------------------------------------------------------

    def _u32(self, rec, at=8):
        return struct.unpack_from("<I", rec, at)[0]

    def bk_mode(self, rec):
        self.p.set(bk_mode=self._u32(rec))

    def fill_mode(self, rec):
        self.p.set(fill_mode=gdi.WINDING if self._u32(rec) == 2 else gdi.ALTERNATE)

    def rop2(self, rec):
        mode = self._u32(rec)
        self.p.flush()
        self.p.set(rop2=mode)
        if mode not in (1, 11, 13, 16):
            self.p.skip(f"EMR_SETROP2 mode {mode} (drawn as R2_COPYPEN)")

    def text_align(self, rec):
        self.p.set(text_align=self._u32(rec))

    def text_color(self, rec):
        self.p.set(text_color=gdi.color(self._u32(rec)))

    def bk_color(self, rec):
        self.p.set(bk_color=gdi.color(self._u32(rec)))

    def moveto(self, rec):
        self.p.move_to(*self._pair(rec))

    def lineto(self, rec):
        self.p.line_to(*self._pair(rec))

    def save_dc(self, rec):
        self.p.save_dc()

    def restore_dc(self, rec):
        self.p.restore_dc(struct.unpack_from("<i", rec, 8)[0])

    def arc_direction(self, rec):
        self.p.set(arc_direction=gdi.AD_CLOCKWISE if self._u32(rec) == 2 else gdi.AD_COUNTERCLOCKWISE)

    def miter_limit(self, rec):
        raw = self._u32(rec)
        value = float(raw)
        if raw > 0x3F000000:  # some writers store a float
            value = struct.unpack_from("<f", rec, 8)[0]
        if math.isfinite(value) and value > 0:
            self.p.set(miter_limit=value)

    def set_layout(self, rec):
        return self._u32(rec) == 0

    def comment(self, rec):
        if len(rec) >= 16 and struct.unpack_from("<I", rec, 12)[0] == EMF_PLUS_IDENTIFIER:
            self.emf_plus = True
            if self.gdi_only:
                return
            if self.plus is None:
                self.plus = PlusPlayer(self.p, nesting=self.nesting)
            size = struct.unpack_from("<I", rec, 8)[0]
            self.plus.play(rec[16 : 12 + min(size, len(rec) - 12)])

    # ---- objects ------------------------------------------------------------------------

    def select(self, rec):
        self.p.select(self._u32(rec))

    def delete(self, rec):
        self.p.delete(self._u32(rec))

    def placeholder(self, rec):
        self.p.create(self._u32(rec), Placeholder(NAMES.get(self._u32(rec, 0), "object")))

    def create_pen(self, rec):
        index, style, width, _wy, colorref = struct.unpack_from("<IIiiI", rec, 8)
        kind = style & 0x0F
        self.p.create(index, Pen(style=style, width=float(abs(width)), color=gdi.color(colorref),
                                 geometric=abs(width) > 1 or bool(style & gdi.PS_GEOMETRIC), plain=True,
                                 null=kind == gdi.PS_NULL))

    def ext_pen(self, rec):
        index, off_bmi, cb_bmi, _off_bits, _cb_bits = struct.unpack_from("<5I", rec, 8)
        style, width, brush_style, colorref, _hatch, entries = struct.unpack_from("<6I", rec, 28)
        entries = min(entries, (len(rec) - 52) // 4, 64)
        user = tuple(struct.unpack_from(f"<{entries}I", rec, 52)) if entries else ()
        geometric = bool(style & gdi.PS_GEOMETRIC)
        null = (style & 0x0F) == gdi.PS_NULL or brush_style == 1
        self.p.create(index, Pen(style=style, width=float(width) if geometric else 0.0,
                                 color=gdi.color(colorref), geometric=geometric, plain=False,
                                 user_style=user, null=null))

    def create_brush(self, rec):
        index, style, colorref, hatch = struct.unpack_from("<IIII", rec, 8)
        if style == 1:
            brush = Brush("null")
        elif style == 2:
            brush = Brush("hatch", gdi.color(colorref), hatch)
        elif style == 0:
            brush = Brush("solid", gdi.color(colorref))
        else:
            self.p.create(index, Brush("solid", gdi.color(colorref)))
            return False
        self.p.create(index, brush)

    def _brush_image(self, rec, palette=None):
        index, _usage, off_bmi, cb_bmi, off_bits, cb_bits = struct.unpack_from("<6I", rec, 8)
        header = rec[off_bmi : off_bmi + cb_bmi]
        bits = rec[off_bits : off_bits + cb_bits]
        if palette is not None and len(header) >= 48:
            header = header[:40] + palette + header[48:]
        from .dib import dib_to_image

        image = dib_to_image(header, bits)
        if image is None or image.mime_type != "image/png":
            return index, None
        w, h = struct.unpack_from("<ii", header, 4)
        return index, Brush("pattern", image=(image.data, abs(w), abs(h)))

    def dib_brush(self, rec):
        index, brush = self._brush_image(rec)
        self.p.create(index, brush or Brush("solid", "#808080"))
        return brush is not None

    def mono_brush(self, rec):
        """A monochrome pattern: its 0 bits in the text colour, 1 bits in the background's
        (as they stand when the brush is created)."""
        def quad(hex_color):
            r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
            return bytes((b, g, r, 0))
        palette = quad(self.p.dc.text_color) + quad(self.p.dc.bk_color)
        index, brush = self._brush_image(rec, palette)
        self.p.create(index, brush or Brush("solid", "#808080"))
        return brush is not None

    def create_font(self, rec):
        index = self._u32(rec)
        height, _width, escapement, _orientation, weight = struct.unpack_from("<5i", rec, 12)
        italic, underline, strike, _charset, _out, _clip, _quality, pitch = struct.unpack_from("<8B", rec, 32)
        raw = rec[40:104]
        face = raw.decode("utf-16-le", errors="replace").split("\0", 1)[0]
        self.p.create(index, Font(height=float(height), escapement=float(escapement), weight=weight,
                                  italic=bool(italic), underline=bool(underline), strike=bool(strike),
                                  face=face.strip(), pitch_family=pitch))

    # ---- shapes -------------------------------------------------------------------------

    def _box(self, rec, at=8):
        l, t, r, b = struct.unpack_from("<4i", rec, at)
        return l, t, r, b

    def _inside(self, l, t, r, b):
        """``PS_INSIDEFRAME``: a geometric pen's outline drawn inside the box."""
        pen = self.p.dc.pen
        if pen.kind == gdi.PS_INSIDEFRAME and pen.geometric and pen.width > 1:
            half = pen.width / 2
            l, r = (l + half, r - half) if l <= r else (l - half, r + half)
            t, b = (t + half, b - half) if t <= b else (t - half, b + half)
        return l, t, r, b

    def rectangle(self, rec):
        self.p.shape([gdi.rect_figure(*self._inside(*self._box(rec)))], fill=True)

    def ellipse(self, rec):
        self.p.shape([gdi.ellipse_figure(*self._inside(*self._box(rec)))], fill=True)

    def round_rect(self, rec):
        l, t, r, b = self._inside(*self._box(rec))
        w, h = struct.unpack_from("<ii", rec, 24)
        self.p.shape([gdi.round_rect_figure(l, t, r, b, w, h)], fill=True)

    def arc(self, rec):
        kind = self._u32(rec, 0)
        l, t, r, b = self._box(rec)
        xs, ys, xe, ye = struct.unpack_from("<4i", rec, 24)
        draw_arc(self.p, {45: "arc", 46: "chord", 47: "pie", 55: "arcto"}[kind], l, t, r, b, xs, ys, xe, ye)

    def angle_arc(self, rec):
        x, y, radius = struct.unpack_from("<iiI", rec, 8)
        start, sweep = struct.unpack_from("<ff", rec, 20)
        if not (math.isfinite(start) and math.isfinite(sweep)):
            return False
        p = self.p
        a0 = -math.radians(start)
        delta = -math.radians(sweep)
        sx, sy = x + radius * math.cos(a0), y + radius * math.sin(a0)
        segments = gdi.arc_segments(x, y, radius, radius, a0, delta)
        if p.in_path():
            p.line_to(sx, sy)
            fig = p._path_figure()
            m = p.matrix()
            for seg in segments:
                fig.segments.append(tuple(v for i in range(0, 6, 2) for v in gdi.apply(m, seg[i], seg[i + 1])))
        else:
            fig = Figure(*p.dc.position)
            fig.segments.append((sx, sy))
            fig.segments += segments
            p.paint([fig], fill=False, stroke=True)
        if segments:
            p.set(position=(segments[-1][4], segments[-1][5]))

    def set_pixel(self, rec):
        x, y, colorref = struct.unpack_from("<iiI", rec, 8)
        self.p.pixel(x, y, colorref)

    # ---- paths and clipping ---------------------------------------------------------------

    def begin_path(self, rec):
        self.p.begin_path()

    def end_path(self, rec):
        self.p.end_path()

    def close_figure(self, rec):
        self.p.close_figure()

    def abort_path(self, rec):
        self.p.abort_path()

    def widen_path(self, rec):
        self.p.path_widened = True

    def fill_path(self, rec):
        self.p.use_path(fill=True, stroke=False)

    def stroke_path(self, rec):
        self.p.use_path(fill=False, stroke=True)

    def stroke_and_fill_path(self, rec):
        self.p.use_path(fill=True, stroke=True)

    def select_clip_path(self, rec):
        mode = self._u32(rec)
        figures = self.p.path_done
        self.p.path_done = None
        if not figures:
            return
        for fig in figures:
            fig.closed = True
        return self.p.set_clip(figures, mode, evenodd=self.p.dc.fill_mode == gdi.ALTERNATE)

    def intersect_clip(self, rec):
        self.p.clip_rect(*self._box(rec), exclude=False)

    def exclude_clip(self, rec):
        self.p.clip_rect(*self._box(rec), exclude=True)

    def _region_rects(self, rec, at):
        if len(rec) < at + 32:
            return []
        _size, _type, count, _bytes = struct.unpack_from("<4I", rec, at)
        count = min(count, (len(rec) - at - 32) // 16)
        self.p.count_points(4 * count)
        return [struct.unpack_from("<4i", rec, at + 32 + 16 * k) for k in range(count)]

    def ext_select_clip_rgn(self, rec):
        size, mode = struct.unpack_from("<II", rec, 8)
        rects = self._region_rects(rec, 16) if size else []
        figures = [gdi.rect_figure(*r) for r in rects] or None
        return self.p.set_clip(figures, mode)

    def fill_rgn(self, rec):
        _size, index = struct.unpack_from("<II", rec, 24)
        brush = self.p.objects.get(index) if not index & 0x80000000 else gdi.STOCK.get(index & 0x7FFFFFFF)
        if not isinstance(brush, Brush):
            return False
        self.p.device_rects(self._region_rects(rec, 32), brush)

    def paint_rgn(self, rec):
        self.p.device_rects(self._region_rects(rec, 28), self.p.dc.brush)

    # ---- bitmaps ------------------------------------------------------------------------

    def _bits(self, rec, off_bmi, cb_bmi, off_bits, cb_bits):
        if not cb_bmi or off_bmi + cb_bmi > len(rec) or off_bits + cb_bits > len(rec):
            return b"", b""
        return rec[off_bmi : off_bmi + cb_bmi], rec[off_bits : off_bits + cb_bits]

    def stretchdibits(self, rec):
        x, y, xs, ys, cxs, cys = struct.unpack_from("<6i", rec, 24)
        off_bmi, cb_bmi, off_bits, cb_bits, _usage, rop = struct.unpack_from("<6I", rec, 48)
        cx, cy = struct.unpack_from("<ii", rec, 72)
        header, bits = self._bits(rec, off_bmi, cb_bmi, off_bits, cb_bits)
        self.p.image((x, y, cx, cy), (xs, ys, cxs, cys), header, bits, rop)

    def _blt(self, rec, stretch: bool, *, alpha=False, transparent=False):
        x, y, cx, cy, rop, xs, ys = struct.unpack_from("<4iIii", rec, 24)
        # xformSrc (24 bytes at 52) and crBkColorSrc (76) follow; the bitmap's after them.
        _usage, off_bmi, cb_bmi, off_bits, cb_bits = struct.unpack_from("<5I", rec, 80)
        cxs, cys = struct.unpack_from("<ii", rec, 100) if stretch and len(rec) >= 108 else (cx, cy)
        header, bits = self._bits(rec, off_bmi, cb_bmi, off_bits, cb_bits)
        if alpha:
            constant = (rop >> 16) & 0xFF
            self.p.image((x, y, cx, cy), (xs, ys, cxs, cys), header, bits, gdi.SRCCOPY, alpha=constant / 255)
        elif transparent:
            self.p.image((x, y, cx, cy), (xs, ys, cxs, cys), header, bits, gdi.SRCCOPY, transparent=rop)
        else:
            self.p.image((x, y, cx, cy), (xs, ys, cxs, cys), header, bits, rop)

    def bitblt(self, rec):
        self._blt(rec, stretch=False)

    def stretchblt(self, rec):
        self._blt(rec, stretch=True)

    def alphablend(self, rec):
        self._blt(rec, stretch=True, alpha=True)

    def transparentblt(self, rec):
        self._blt(rec, stretch=True, transparent=True)

    def set_dibits(self, rec):
        x, y, xs, ys, cxs, cys = struct.unpack_from("<6i", rec, 24)
        off_bmi, cb_bmi, off_bits, cb_bits = struct.unpack_from("<4I", rec, 48)
        header, bits = self._bits(rec, off_bmi, cb_bmi, off_bits, cb_bits)
        scale = 1 / (gdi.scale_of(self.p.matrix()) or 1)
        self.p.image((x, y, cxs * scale, cys * scale), (xs, ys, cxs, cys), header, bits, gdi.SRCCOPY)

    def gradient_fill(self, rec):
        n_ver, n_tri, mode = struct.unpack_from("<III", rec, 24)
        n_ver = min(n_ver, (len(rec) - 36) // 16)
        self.p.count_points(n_ver)
        vertices = []
        for k in range(n_ver):
            x, y, r, g, b, _a = struct.unpack_from("<iiHHHH", rec, 36 + 16 * k)
            vertices.append((x, y, "#%02X%02X%02X" % (r >> 8, g >> 8, b >> 8)))
        at = 36 + 16 * n_ver
        if mode in (0, 1):
            n_tri = min(n_tri, (len(rec) - at) // 8)
            for k in range(n_tri):
                i, j = struct.unpack_from("<II", rec, at + 8 * k)
                if i < len(vertices) and j < len(vertices):
                    (x0, y0, c0), (x1, y1, c1) = vertices[i], vertices[j]
                    self.p.gradient_rect(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1),
                                         c0 if (x0 <= x1 if mode == 0 else y0 <= y1) else c1,
                                         c1 if (x0 <= x1 if mode == 0 else y0 <= y1) else c0, mode == 1)
            return
        if mode == 2:
            n_tri = min(n_tri, (len(rec) - at) // 12)
            for k in range(n_tri):
                ids = struct.unpack_from("<III", rec, at + 12 * k)
                if all(i < len(vertices) for i in ids):
                    corners = [vertices[i] for i in ids]
                    mean = tuple(sum(int(c[2][1 + 2 * ch : 3 + 2 * ch], 16) for c in corners) // 3 for ch in range(3))
                    self.p.flat_polygon([(c[0], c[1]) for c in corners], "#%02X%02X%02X" % mean)
            self.p.skip("EMR_GRADIENTFILL triangles (drawn in their mean colour)")
            return
        return False

    # ---- text ---------------------------------------------------------------------------

    def _text(self, rec, wide: bool):
        x, y, count, off_string, options = struct.unpack_from("<iiIII", rec, 36)
        rect = struct.unpack_from("<4i", rec, 56)
        off_dx = struct.unpack_from("<I", rec, 72)[0]
        count = min(count, gdi.MAX_TEXT_CHARS)
        if options & gdi.ETO_GLYPH_INDEX:
            self.p.skip("EMR_EXTTEXTOUTW by glyph index (not drawn)")
            return
        width = 2 if wide else 1
        raw = rec[off_string : off_string + count * width]
        text = raw.decode("utf-16-le" if wide else "cp1252", errors="replace")
        dx = None
        pdy = bool(options & gdi.ETO_PDY)
        if off_dx and off_dx < len(rec):
            n = count * (2 if pdy else 1)
            n = min(n, (len(rec) - off_dx) // 4)
            values = list(struct.unpack_from(f"<{n}i", rec, off_dx))
            dx = values[0::2] if pdy else values
            if len(dx) < count:
                dx = None
        self.p.text(x, y, text, dx, options, rect)

    def text_w(self, rec):
        self._text(rec, wide=True)

    def text_a(self, rec):
        self._text(rec, wide=False)


def draw_arc(p: Player, kind: str, l, t, r, b, xs, ys, xe, ye) -> None:
    """``ARC``, ``ARCTO``, ``CHORD`` and ``PIE``: the ellipse of the box from the ray
    through the start point to the ray through the end point, counter-clockwise unless
    ``SETARCDIRECTION`` says otherwise."""
    cx, cy, rx, ry = (l + r) / 2, (t + b) / 2, abs(r - l) / 2, abs(b - t) / 2
    if not rx or not ry:
        return
    a0 = math.atan2((ys - cy) / ry, (xs - cx) / rx)
    a1 = math.atan2((ye - cy) / ry, (xe - cx) / rx)
    if p.dc.arc_direction == gdi.AD_CLOCKWISE:
        sweep = (a1 - a0) % (2 * math.pi) or 2 * math.pi
    else:
        sweep = -((a0 - a1) % (2 * math.pi) or 2 * math.pi)
    start = (cx + rx * math.cos(a0), cy + ry * math.sin(a0))
    segments = gdi.arc_segments(cx, cy, rx, ry, a0, sweep)
    end = (segments[-1][4], segments[-1][5]) if segments else start
    if kind == "arcto":
        if p.in_path():
            p.line_to(*start)
            fig = p._path_figure()
            m = p.matrix()
            for seg in segments:
                fig.segments.append(tuple(v for i in range(0, 6, 2) for v in gdi.apply(m, seg[i], seg[i + 1])))
        else:
            fig = Figure(*p.dc.position)
            fig.segments.append(start)
            fig.segments += segments
            p.paint([fig], fill=False, stroke=True)
        p.set(position=end)
        return
    fig = Figure(*start)
    fig.segments = list(segments)
    if kind == "pie":
        fig.segments.append((cx, cy))
    if kind in ("pie", "chord"):
        fig.closed = True
    if p.in_path():
        p.add_to_path(fig)
    else:
        p.paint([fig], fill=kind != "arc", stroke=True)


__all__ = ["play", "is_emf", "Header", "NAMES", "split_packed_dib"]
