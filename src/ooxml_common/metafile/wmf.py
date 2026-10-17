"""A Windows Metafile's records played into SVG (MS-WMF, 2.3), the subset EMF shares.

A placeable WMF (key ``0x9AC6CDD7``) states its box in logical units and how many of
them make an inch; the box is what is mapped onto the picture.  The player stands where
Windows' does when it plays a placeable file into a rectangle: ``MM_ANISOTROPIC``, the
window the box, the viewport the picture -- so the file's own ``SETWINDOWORG`` and
``SETWINDOWEXT`` map their window onto the picture, and its ``SETMAPMODE`` and viewport
records, which would tie a unit to whatever device plays the file, are not followed
(the reference file sets ``MM_TEXT`` and Windows' PDF export drew it at 0.5925, Mac's at
0.962: device-dependent, not reproduced).  Measured on Windows: pen widths are honoured,
``PS_NULL`` draws nothing, and an ellipse leaves out its right and bottom pixel (drawn
to ``right - 1``, ``bottom - 1``).

A WMF without the placeable header takes its first window as the box.
"""

from __future__ import annotations

import struct

from . import gdi
from .dib import split_packed_dib
from .gdi import Brush, Font, Pen, Placeholder, Player, Stop
from .emf import draw_arc

PLACEABLE_KEY = 0x9AC6CDD7
MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_RECORDS = 100_000

NAMES = {
    0x0000: "EOF", 0x0035: "REALIZEPALETTE", 0x0037: "SETPALENTRIES", 0x0102: "SETBKMODE",
    0x0103: "SETMAPMODE", 0x0104: "SETROP2", 0x0105: "SETRELABS", 0x0106: "SETPOLYFILLMODE",
    0x0107: "SETSTRETCHBLTMODE", 0x0108: "SETTEXTCHAREXTRA", 0x0127: "RESTOREDC", 0x012A: "INVERTREGION",
    0x012B: "PAINTREGION", 0x012C: "SELECTCLIPREGION", 0x012D: "SELECTOBJECT", 0x012E: "SETTEXTALIGN",
    0x0139: "RESIZEPALETTE", 0x0142: "DIBCREATEPATTERNBRUSH", 0x014C: "SETLAYOUT", 0x01F0: "DELETEOBJECT",
    0x01F9: "CREATEPATTERNBRUSH", 0x0201: "SETBKCOLOR", 0x0209: "SETTEXTCOLOR", 0x020A: "SETTEXTJUSTIFICATION",
    0x020B: "SETWINDOWORG", 0x020C: "SETWINDOWEXT", 0x020D: "SETVIEWPORTORG", 0x020E: "SETVIEWPORTEXT",
    0x020F: "OFFSETWINDOWORG", 0x0211: "OFFSETVIEWPORTORG", 0x0213: "LINETO", 0x0214: "MOVETO",
    0x0220: "OFFSETCLIPRGN", 0x0228: "FILLREGION", 0x0231: "SETMAPPERFLAGS", 0x0234: "SELECTPALETTE",
    0x02FA: "CREATEPENINDIRECT", 0x02FB: "CREATEFONTINDIRECT", 0x02FC: "CREATEBRUSHINDIRECT",
    0x0324: "POLYGON", 0x0325: "POLYLINE", 0x0410: "SCALEWINDOWEXT", 0x0412: "SCALEVIEWPORTEXT",
    0x0415: "EXCLUDECLIPRECT", 0x0416: "INTERSECTCLIPRECT", 0x0418: "ELLIPSE", 0x0419: "FLOODFILL",
    0x041B: "RECTANGLE", 0x041F: "SETPIXEL", 0x0429: "FRAMEREGION", 0x0436: "ANIMATEPALETTE",
    0x0521: "TEXTOUT", 0x0538: "POLYPOLYGON", 0x0548: "EXTFLOODFILL", 0x061C: "ROUNDRECT", 0x061D: "PATBLT",
    0x0626: "ESCAPE", 0x06FF: "CREATEREGION", 0x0817: "ARC", 0x081A: "PIE", 0x0830: "CHORD",
    0x0922: "BITBLT", 0x0940: "DIBBITBLT", 0x0A32: "EXTTEXTOUT", 0x0B23: "STRETCHBLT",
    0x0B41: "DIBSTRETCHBLT", 0x0D33: "SETDIBTODEV", 0x0F43: "STRETCHDIB", 0x001E: "SAVEDC",
    0x00F7: "CREATEPALETTE",
}

_IGNORED = {0x0035, 0x0037, 0x0105, 0x0107, 0x0108, 0x0139, 0x020A, 0x0231, 0x0234, 0x0436, 0x0626}
#: Records that create an object: the slot is taken even when it is never drawn with.
_PLACEHOLDERS = {0x00F7: "palette", 0x01F9: "pattern brush", 0x06FF: "region"}


def is_wmf(data: bytes) -> bool:
    if len(data) >= 22 and struct.unpack_from("<I", data, 0)[0] == PLACEABLE_KEY:
        return True
    if len(data) < 18:
        return False
    kind, header_words, version = struct.unpack_from("<HHH", data, 0)
    return kind in (1, 2) and header_words == 9 and version in (0x0100, 0x0300)


def play(data: bytes, *, font_mapping=None):
    """``(player, natural size)`` for WMF bytes, or ``None`` when they are not one."""
    if not is_wmf(data) or len(data) > MAX_INPUT_BYTES:
        return None
    start = 0
    box = None
    inch = 1440
    if struct.unpack_from("<I", data, 0)[0] == PLACEABLE_KEY:
        left, top, right, bottom, inch = struct.unpack_from("<hhhhH", data, 6)
        if right != left and bottom != top:
            box = (float(min(left, right)), float(min(top, bottom)), float(abs(right - left)), float(abs(bottom - top)))
        inch = inch or 1440
        start = 22
    if len(data) < start + 18:
        return None
    header_words = struct.unpack_from("<H", data, start + 2)[0]
    first = start + header_words * 2
    if box is None:
        box = _first_window(data, first)
        if box is None:
            return None
    x, y, w, h = box
    player = Player(font_mapping=font_mapping, canvas=box)
    player.set(map_mode=gdi.MM_ANISOTROPIC, window_org=(x, y), window_ext=(w, h), viewport_org=(x, y),
               viewport_ext=(w, h))
    reader = _Reader(player)
    offset = first
    try:
        for _ in range(MAX_RECORDS):
            if offset + 6 > len(data):
                break
            words, function = struct.unpack_from("<IH", data, offset)
            size = words * 2
            if size < 6 or offset + size > len(data):
                player.skip("a record whose size runs past the file (the rest is not read)")
                break
            if function == 0:
                break
            reader.record(function, data[offset + 6 : offset + size])
            offset += size
        else:
            player.truncated = True
    except Stop:
        pass
    natural = (w / inch * 96, h / inch * 96) if inch else (w, h)
    return player, natural


def _first_window(data: bytes, offset: int):
    org, ext = (0.0, 0.0), None
    for _ in range(MAX_RECORDS):
        if offset + 6 > len(data):
            break
        words, function = struct.unpack_from("<IH", data, offset)
        if words < 3 or function == 0:
            break
        if function in (0x020B, 0x020C) and offset + 10 <= len(data):
            yy, xx = struct.unpack_from("<hh", data, offset + 6)
            if function == 0x020B:
                org = (float(xx), float(yy))
            elif xx and yy:
                ext = (float(xx), float(yy))
                break
        offset += words * 2
    if ext is None:
        return None
    return org[0], org[1], ext[0], ext[1]


class _Reader:
    def __init__(self, player: Player):
        self.p = player
        self.slots: dict[int, bool] = {}

    def record(self, function: int, params: bytes) -> None:
        if function in _IGNORED:
            return
        name = "META_" + NAMES.get(function, f"0x{function:04X}")
        if function in _PLACEHOLDERS:
            self._add(Placeholder(_PLACEHOLDERS[function]))
            return
        handler = getattr(self, "f%04X" % function, None)
        if handler is None:
            self.p.skip(name)
            return
        try:
            if handler(params) is False:
                self.p.skip(name)
        except Stop:
            raise
        except Exception:  # a record that cannot be read is named, never fatal
            self.p.skip(name + " (unreadable)")

    @staticmethod
    def _h(params: bytes, count: int, at: int = 0):
        return struct.unpack_from(f"<{count}h", params, at)

    def _add(self, obj) -> None:
        """A WMF object takes the lowest free slot."""
        index = 0
        while index in self.slots:
            index += 1
        if index >= gdi.MAX_OBJECTS:
            return
        self.slots[index] = True
        self.p.create(index, obj)

    def _points(self, params: bytes, at: int, count: int):
        count = min(count, (len(params) - at) // 4)
        self.p.count_points(count)
        flat = struct.unpack_from(f"<{2 * count}h", params, at)
        return list(zip(flat[0::2], flat[1::2]))

    def _rect(self, params: bytes, at: int = 0):
        bottom, right, top, left = self._h(params, 4, at)
        return left, top, right, bottom

    # ---- state --------------------------------------------------------------------------

    def f0103(self, params):  # SETMAPMODE: the player's mapping stands (see the module)
        return None

    def f020B(self, params):
        y, x = self._h(params, 2)
        self.p.set(window_org=(float(x), float(y)))

    def f020C(self, params):
        y, x = self._h(params, 2)
        if x and y:
            self.p.set(window_ext=(float(x), float(y)))

    def f020F(self, params):
        y, x = self._h(params, 2)
        ox, oy = self.p.dc.window_org
        self.p.set(window_org=(ox + x, oy + y))

    def f0410(self, params):
        yd, yn, xd, xn = self._h(params, 4)
        if xd and yd and xn and yn:
            ex, ey = self.p.dc.window_ext
            self.p.set(window_ext=(ex * xn / xd, ey * yn / yd))

    def f020D(self, params):
        return False

    f020E = f0211 = f0412 = f020D

    def f0102(self, params):
        self.p.set(bk_mode=struct.unpack_from("<H", params)[0])

    def f0106(self, params):
        self.p.set(fill_mode=gdi.WINDING if struct.unpack_from("<H", params)[0] == 2 else gdi.ALTERNATE)

    def f0104(self, params):
        mode = struct.unpack_from("<H", params)[0]
        self.p.flush()
        self.p.set(rop2=mode)
        if mode not in (1, 11, 13, 16):
            self.p.skip(f"META_SETROP2 mode {mode} (drawn as R2_COPYPEN)")

    def f012E(self, params):
        self.p.set(text_align=struct.unpack_from("<H", params)[0])

    def f0201(self, params):
        self.p.set(bk_color=gdi.color(struct.unpack_from("<I", params)[0]))

    def f0209(self, params):
        self.p.set(text_color=gdi.color(struct.unpack_from("<I", params)[0]))

    def f001E(self, params):
        self.p.save_dc()

    def f0127(self, params):
        self.p.restore_dc(self._h(params, 1)[0])

    def f014C(self, params):
        return struct.unpack_from("<H", params)[0] == 0

    # ---- objects ------------------------------------------------------------------------

    def f012D(self, params):
        self.p.select(struct.unpack_from("<H", params)[0])

    def f01F0(self, params):
        index = struct.unpack_from("<H", params)[0]
        self.slots.pop(index, None)
        self.p.delete(index)

    def f02FA(self, params):
        style, width = struct.unpack_from("<Hh", params)
        colorref = struct.unpack_from("<I", params, 6)[0]
        kind = style & 0x0F
        self._add(Pen(style=style, width=float(abs(width)), color=gdi.color(colorref), geometric=abs(width) > 1,
                      plain=True, null=kind == gdi.PS_NULL))

    def f02FC(self, params):
        style = struct.unpack_from("<H", params)[0]
        colorref = struct.unpack_from("<I", params, 2)[0]
        hatch = struct.unpack_from("<H", params, 6)[0] if len(params) >= 8 else 0
        if style == 1:
            self._add(Brush("null"))
        elif style == 2:
            self._add(Brush("hatch", gdi.color(colorref), hatch))
        else:
            self._add(Brush("solid", gdi.color(colorref)))
            if style != 0:
                return False

    def f0142(self, params):
        split = split_packed_dib(params[4:])
        brush = None
        if split is not None:
            from .dib import dib_to_image

            image = dib_to_image(*split)
            if image is not None and image.mime_type == "image/png":
                w, h = struct.unpack_from("<ii", split[0], 4)
                brush = Brush("pattern", image=(image.data, abs(w), abs(h)))
        self._add(brush or Brush("solid", "#808080"))
        return brush is not None

    def f02FB(self, params):
        height, _width, escapement, _orientation, weight = self._h(params, 5)
        italic, underline, strike, _charset, _out, _clip, _quality, pitch = struct.unpack_from("<8B", params, 10)
        face = params[18:50].split(b"\0", 1)[0].decode("cp1252", errors="replace")
        self._add(Font(height=float(height), escapement=float(escapement), weight=weight, italic=bool(italic),
                       underline=bool(underline), strike=bool(strike), face=face.strip(), pitch_family=pitch))

    # ---- drawing ------------------------------------------------------------------------

    def f0214(self, params):
        y, x = self._h(params, 2)
        self.p.move_to(x, y)

    def f0213(self, params):
        y, x = self._h(params, 2)
        self.p.line_to(x, y)

    def f041B(self, params):
        self.p.shape([gdi.rect_figure(*self._rect(params))], fill=True)

    def f0418(self, params):
        left, top, right, bottom = self._rect(params)
        # Measured on Windows: a WMF ellipse leaves out its right and bottom pixel.
        right += -1 if right > left else 1
        bottom += -1 if bottom > top else 1
        self.p.shape([gdi.ellipse_figure(left, top, right, bottom)], fill=True)

    def f061C(self, params):
        h, w = self._h(params, 2)
        self.p.shape([gdi.round_rect_figure(*self._rect(params, 4), w, h)], fill=True)

    def f0324(self, params):
        count = struct.unpack_from("<H", params)[0]
        self.p.shape([gdi.polyline_figure(self._points(params, 2, count), closed=True)], fill=True)

    def f0325(self, params):
        count = struct.unpack_from("<H", params)[0]
        self.p.paint([gdi.polyline_figure(self._points(params, 2, count))], fill=False, stroke=True)

    def f0538(self, params):
        polys = struct.unpack_from("<H", params)[0]
        polys = min(polys, (len(params) - 2) // 2)
        counts = struct.unpack_from(f"<{polys}H", params, 2)
        points = self._points(params, 2 + 2 * polys, sum(counts))
        figures, k = [], 0
        for n in counts:
            if points[k : k + n]:
                figures.append(gdi.polyline_figure(points[k : k + n], closed=True))
            k += n
        self.p.shape(figures, fill=True)

    def _arc(self, params, kind):
        ye, xe, ys, xs = self._h(params, 4)
        draw_arc(self.p, kind, *self._rect(params, 8), xs, ys, xe, ye)

    def f0817(self, params):
        self._arc(params, "arc")

    def f0830(self, params):
        self._arc(params, "chord")

    def f081A(self, params):
        self._arc(params, "pie")

    def f041F(self, params):
        colorref = struct.unpack_from("<I", params)[0]
        y, x = self._h(params, 2, 4)
        self.p.pixel(x, y, colorref)

    def f0416(self, params):
        self.p.clip_rect(*self._rect(params), exclude=False)

    def f0415(self, params):
        self.p.clip_rect(*self._rect(params), exclude=True)

    def f061D(self, params):
        rop = struct.unpack_from("<I", params)[0]
        h, w, y, x = self._h(params, 4, 4)
        self.p.image((x, y, w, h), (0, 0, 0, 0), b"", b"", rop)

    # ---- bitmaps ------------------------------------------------------------------------

    def _dib(self, params, at):
        split = split_packed_dib(params[at:])
        return split if split is not None else (b"", b"")

    def f0F43(self, params):  # STRETCHDIB
        rop = struct.unpack_from("<I", params)[0]
        sh, sw, sy, sx, dh, dw, dy, dx = self._h(params, 8, 6)
        header, bits = self._dib(params, 22)
        self.p.image((dx, dy, dw, dh), (sx, sy, sw, sh), header, bits, rop)

    def f0B41(self, params):  # DIBSTRETCHBLT
        rop = struct.unpack_from("<I", params)[0]
        sh, sw, sy, sx, dh, dw, dy, dx = self._h(params, 8, 4)
        header, bits = self._dib(params, 20)
        self.p.image((dx, dy, dw, dh), (sx, sy, sw, sh), header, bits, rop)

    def f0940(self, params):  # DIBBITBLT
        rop = struct.unpack_from("<I", params)[0]
        sy, sx, h, w, dy, dx = self._h(params, 6, 4)
        header, bits = self._dib(params, 16)
        self.p.image((dx, dy, w, h), (sx, sy, w, h), header, bits, rop)

    # ---- text ---------------------------------------------------------------------------

    def f0521(self, params):  # TEXTOUT
        count = struct.unpack_from("<H", params)[0]
        raw = params[2 : 2 + count]
        at = 2 + count + (count & 1)
        y, x = self._h(params, 2, at)
        self.p.text(x, y, raw.decode("cp1252", errors="replace"), None, 0)

    def f0A32(self, params):  # EXTTEXTOUT
        y, x, count, options = struct.unpack_from("<hhhH", params)
        at = 8
        rect = None
        if options & (gdi.ETO_OPAQUE | gdi.ETO_CLIPPED):
            left, top, right, bottom = self._h(params, 4, at)
            rect = (left, top, right, bottom)
            at += 8
        count = max(0, min(count, len(params) - at))
        raw = params[at : at + count]
        at += count + (count & 1)
        dx = None
        if len(params) >= at + 2 * count and count:
            dx = list(self._h(params, count, at))
        self.p.text(x, y, raw.decode("cp1252", errors="replace"), dx, options, rect)
