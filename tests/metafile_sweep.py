"""Metafiles written by hand for the golden suite (``tests/test_goldens.py``): one record of
each kind the EMF and WMF players read, built with ``tests/test_metafile_gdi.py``'s writer
and laid out from MS-EMF and MS-WMF, plus the device-independent bitmaps those records
carry in every depth and layout ``metafile.dib`` decodes.

None of it is from Office.  The goldens hold what the players draw of it; the numbers
those drawings are measured against are in ``tests/test_metafile_gdi.py``.
"""

from __future__ import annotations

import struct

from test_metafile_gdi import BLACK_BRUSH, NULL_BRUSH, NULL_PEN, RED, WHITE, Emf, _wmf, rgb

BLUE, GREEN, GREY = rgb(0, 0, 255), rgb(0, 160, 0), rgb(128, 128, 128)


# -- device-independent bitmaps ---------------------------------------------------------


def dib(width: int, height: int, bpp: int, *, compression: int = 0, palette=None, masks=(),
        top_down: bool = False, clr_used: int = 0, header_size: int = 40, data: bytes | None = None):
    """``(header, bits)``: a BITMAPINFOHEADER (or a V4/V5 one, ``header_size``) with its
    masks and palette, and rows of a made-up pattern unless ``data`` is given."""
    stride = ((width * bpp + 31) // 32) * 4
    if data is None:
        data = bytes((x * 37 + y * 11) & 0xFF for y in range(height) for x in range(stride))
    header = struct.pack("<IiiHHIIiiII", header_size, width, -height if top_down else height, 1, bpp, compression,
                         len(data), 3780, 3780, clr_used, 0)
    if header_size > 40:
        header += b"".join(struct.pack("<I", value) for value in (list(masks) + [0] * 4)[:4])
        header += b"\0" * (header_size - 56)
    else:
        header += b"".join(struct.pack("<I", value) for value in masks)
    if palette is not None:
        header += b"".join(bytes((b, g, r, 0)) for r, g, b in palette)
    return header, data


def _palette(count: int):
    return [((k * 85) & 0xFF, (k * 51 + 30) & 0xFF, (255 - k * 17) & 0xFF) for k in range(count)]


#: name -> (header, bits); what ``dib_to_image`` makes of each is a golden of its own.
DIBS = {
    "1bpp": dib(9, 3, 1, palette=[(0, 0, 0), (255, 255, 255)]),
    "4bpp": dib(5, 4, 4, palette=_palette(16)),
    "4bpp-short-palette": dib(5, 2, 4, palette=_palette(3), clr_used=3),
    "8bpp-top-down": dib(4, 3, 8, palette=_palette(256), top_down=True),
    "16bpp-555": dib(3, 2, 16),
    "16bpp-565": dib(3, 2, 16, compression=3, masks=(0xF800, 0x07E0, 0x001F)),
    "24bpp": dib(3, 3, 24),
    "32bpp-no-alpha": dib(2, 2, 32, data=bytes([10, 20, 30, 0] * 4)),
    "32bpp-alpha": dib(2, 2, 32, data=bytes([10, 20, 30, 128, 40, 50, 60, 255] * 2)),
    "32bpp-bitfields": dib(2, 2, 32, compression=3, masks=(0x00FF0000, 0x0000FF00, 0x000000FF)),
    "32bpp-alpha-bitfields": dib(2, 2, 32, compression=6, masks=(0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000),
                                 data=bytes([1, 2, 3, 100] * 4)),
    "32bpp-v5": dib(2, 2, 32, compression=3, masks=(0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000),
                    header_size=124, data=bytes([9, 8, 7, 200] * 4)),
    "rle8": dib(4, 2, 8, compression=1, palette=_palette(4), clr_used=4, data=b"\x04\x01\x00\x00\x02\x02\x00\x01"),
    "jpeg": dib(2, 2, 0, compression=4, data=b"\xff\xd8\xff\xd9"),
    "png": dib(2, 2, 0, compression=5, data=b"\x89PNG\r\n\x1a\n"),
    "short-bits": dib(8, 8, 24, data=b"\0" * 10),
    "no-palette": dib(2, 2, 8, palette=[]),
    "bad-depth": dib(2, 2, 7),
    "zero-width": dib(0, 2, 24, data=b""),
}


def _packed(header_bits) -> bytes:
    header, bits = header_bits
    return header + bits


# -- EMF ----------------------------------------------------------------------------------


def _bitmap_record(e: Emf, kind: int, fixed: bytes, header: bytes, bits: bytes, offsets_at: int) -> None:
    """A bitmap record: ``fixed`` up to the offsets, which sit at ``offsets_at`` within it
    (counted from the record's start), the header and bits after it."""
    start = 8 + len(fixed)
    off_bmi, off_bits = start, start + len(header)
    patched = bytearray(fixed)
    struct.pack_into("<4I", patched, offsets_at - 8, off_bmi, len(header), off_bits, len(bits))
    e.rec(kind, bytes(patched) + header + bits)


def emf_shapes() -> bytes:
    e = Emf()
    pen = e.pen(0, 4, BLUE)
    e.select(pen).select(e.brush(0, rgb(250, 220, 120)))
    e.box(43, 10, 10, 90, 60)  # RECTANGLE
    e.box(42, 100, 10, 180, 60)  # ELLIPSE
    e.box(44, 190, 10, 270, 60, 20, 12)  # ROUNDRECT
    for kind, x in ((45, 10), (46, 100), (47, 190), (55, 280)):  # ARC, CHORD, PIE, ARCTO
        e.box(kind, x, 70, x + 80, 130, x + 80, 100, x, 100)
    e.rec(57, struct.pack("<I", 2))  # SETARCDIRECTION clockwise
    e.box(45, 10, 140, 90, 200, 90, 170, 10, 170)
    e.rec(57, struct.pack("<I", 1))
    e.rec(41, struct.pack("<iiIff", 140, 170, 30, 30.0, 240.0))  # ANGLEARC
    e.rec(41, struct.pack("<iiIff", 140, 170, 30, float("nan"), 1.0))
    e.poly16(86, [(200, 140), (260, 140), (230, 200)])  # POLYGON16
    e.rec(3, struct.pack("<4iI", 0, 0, 0, 0, 3) + struct.pack("<6i", 270, 140, 330, 140, 300, 200))  # POLYGON
    e.poly16(87, [(10, 210), (60, 260), (110, 210)])  # POLYLINE16
    e.rec(4, struct.pack("<4iI", 0, 0, 0, 0, 2) + struct.pack("<4i", 120, 210, 170, 260))  # POLYLINE
    e.poly16(85, [(180, 210), (200, 260), (240, 260), (260, 210)])  # POLYBEZIER16
    e.rec(2, struct.pack("<4iI", 0, 0, 0, 0, 4) + struct.pack("<8i", 270, 210, 290, 260, 330, 260, 350, 210))
    e.rec(27, struct.pack("<ii", 10, 270))  # MOVETO
    e.poly16(89, [(40, 290), (70, 270)])  # POLYLINETO16
    e.poly16(88, [(80, 290), (100, 290), (110, 270)])  # POLYBEZIERTO16
    e.rec(6, struct.pack("<4iI", 0, 0, 0, 0, 1) + struct.pack("<2i", 130, 290))  # POLYLINETO
    e.rec(5, struct.pack("<4iI", 0, 0, 0, 0, 3) + struct.pack("<6i", 140, 270, 150, 270, 160, 290))  # POLYBEZIERTO
    e.rec(90, struct.pack("<4iII", 0, 0, 0, 0, 2, 4) + struct.pack("<II", 2, 2)  # POLYPOLYLINE16
          + struct.pack("<8h", 170, 270, 190, 290, 200, 270, 220, 290))
    e.rec(7, struct.pack("<4iII", 0, 0, 0, 0, 1, 2) + struct.pack("<I", 2) + struct.pack("<4i", 230, 270, 250, 290))
    e.rec(91, struct.pack("<4iII", 0, 0, 0, 0, 2, 6) + struct.pack("<II", 3, 3)  # POLYPOLYGON16
          + struct.pack("<12h", 260, 270, 280, 270, 270, 290, 290, 270, 310, 270, 300, 290))
    e.rec(8, struct.pack("<4iII", 0, 0, 0, 0, 1, 3) + struct.pack("<I", 3) + struct.pack("<6i", 320, 270, 340, 270, 330, 290))
    e.rec(92, struct.pack("<4iI", 0, 0, 0, 0, 5) + struct.pack("<10h", 350, 200, 380, 200, 390, 220, 395, 240, 360, 250)
          + bytes([6, 2, 4, 4, 4 | 1]))  # POLYDRAW16: move, line, bezier, closed
    e.rec(56, struct.pack("<4iI", 0, 0, 0, 0, 2) + struct.pack("<4i", 350, 260, 390, 280) + bytes([6, 3]))  # POLYDRAW
    e.rec(15, struct.pack("<iiI", 395, 295, RED))  # SETPIXELV
    e.select(NULL_PEN).select(NULL_BRUSH)
    e.box(43, 0, 0, 5, 5)
    e.select(BLACK_BRUSH).select(e.pen(5, 0, 0))  # PS_NULL
    e.box(43, 5, 5, 8, 8)
    inside = e.pen(6, 10, GREEN)  # PS_INSIDEFRAME
    e.select(inside).box(43, 300, 10, 390, 60)
    e.rec(40, struct.pack("<I", inside))  # DELETEOBJECT
    e.rec(39, struct.pack("<4I", e.handle(), 3, RED, 0))  # an unknown brush style
    e.rec(39, struct.pack("<4I", e.handle(), 2, RED, 3))  # HS_FDIAGONAL
    e.rec(999, b"")  # an unknown record
    e.rec(13, b"")  # ignored
    e.rec(49, struct.pack("<I", e.handle()))  # CREATEPALETTE, a placeholder
    e.rec(115, struct.pack("<I", 1))  # SETLAYOUT right-to-left
    return e.build()


def emf_paths_and_clips() -> bytes:
    e = Emf()
    e.select(e.extpen(0x00010000 | 0x00002000 | 0x00000200, 6, BLUE))  # geometric, flat cap, miter join
    e.rec(58, struct.pack("<I", 4))  # SETMITERLIMIT as an integer
    e.rec(58, struct.pack("<f", 6.0))  # and as a float
    e.rec(19, struct.pack("<I", 2))  # SETPOLYFILLMODE winding
    e.rec(59)  # BEGINPATH
    e.rec(27, struct.pack("<ii", 20, 20)).rec(54, struct.pack("<ii", 120, 20))
    e.box(45, 20, 20, 120, 100, 120, 60, 20, 60)
    e.rec(55, struct.pack("<8i", 20, 20, 120, 100, 20, 60, 120, 60))  # ARCTO in a path
    e.rec(41, struct.pack("<iiIff", 70, 60, 20, 0.0, 90.0))  # ANGLEARC in a path
    e.poly16(87, [(30, 90), (60, 95)])
    e.poly16(85, [(60, 95), (80, 99), (100, 90), (110, 95)])
    e.rec(90, struct.pack("<4iII", 0, 0, 0, 0, 1, 2) + struct.pack("<I", 2) + struct.pack("<4h", 30, 30, 40, 40))
    e.rec(61)  # CLOSEFIGURE
    e.rec(60)  # ENDPATH
    e.rec(66)  # WIDENPATH
    e.rec(63)  # STROKEANDFILLPATH
    e.rec(59).box(42, 150, 20, 250, 100).rec(60).rec(64)  # STROKEPATH
    e.rec(59).box(43, 260, 20, 360, 100).rec(60).rec(62)  # FILLPATH
    e.rec(59).box(43, 0, 0, 1, 1).rec(68)  # ABORTPATH
    e.rec(33)  # SAVEDC
    e.rec(59).box(42, 20, 120, 200, 280).rec(60).rec(67, struct.pack("<I", 5))  # SELECTCLIPPATH, RGN_COPY
    e.select(e.brush(2, RED, 5)).box(43, 0, 110, 220, 300)  # clipped hatch
    e.rec(34, struct.pack("<i", -1))  # RESTOREDC
    e.rec(30, struct.pack("<4i", 230, 120, 330, 220))  # INTERSECTCLIPRECT
    e.rec(29, struct.pack("<4i", 250, 140, 280, 170))  # EXCLUDECLIPRECT
    e.select(e.brush(0, GREEN)).box(43, 220, 110, 400, 300)
    e.rec(75, struct.pack("<II", 0, 5))  # EXTSELECTCLIPRGN, no region: clip off
    region = struct.pack("<4I", 32, 1, 2, 32) + struct.pack("<4i", 0, 0, 0, 0) + struct.pack("<8i", 340, 120, 360, 140, 370, 150, 390, 170)
    e.rec(75, struct.pack("<II", len(region), 1) + region)  # RGN_AND
    e.rec(71, struct.pack("<4iII", 0, 0, 0, 0, len(region), BLACK_BRUSH) + region)  # FILLRGN, a stock brush
    e.rec(71, struct.pack("<4iII", 0, 0, 0, 0, len(region), 77) + region)  # a brush that is not there
    e.rec(74, struct.pack("<4iI", 0, 0, 0, 0, len(region)) + region)  # PAINTRGN
    e.rec(75, struct.pack("<II", 0, 5))
    e.rec(67, struct.pack("<I", 5))  # SELECTCLIPPATH with no path
    for mode in (1, 11, 13, 16, 7):  # SETROP2: drawn modes, then one that is not
        e.rec(20, struct.pack("<I", mode))
    e.rec(18, struct.pack("<I", 2))  # SETBKMODE opaque
    e.rec(25, struct.pack("<I", rgb(255, 255, 0)))  # SETBKCOLOR
    e.select(e.pen(1, 1, BLACK_BRUSH & 0))  # PS_DASH, cosmetic
    e.rec(27, struct.pack("<ii", 20, 290)).rec(54, struct.pack("<ii", 380, 290))
    return e.build()


def emf_mapping() -> bytes:
    e = Emf()
    e.rec(17, struct.pack("<I", 8))  # SETMAPMODE anisotropic
    e.rec(17, struct.pack("<I", 99))  # one that does not exist
    e.rec(9, struct.pack("<ii", 800, 600)).rec(10, struct.pack("<ii", -50, -50))  # window ext, org
    e.rec(11, struct.pack("<ii", 400, 300)).rec(12, struct.pack("<ii", 0, 0))  # viewport ext, org
    e.rec(9, struct.pack("<ii", 0, 5))  # a zero extent is refused
    e.rec(31, struct.pack("<4i", 1, 1, 1, 1))  # SCALEVIEWPORTEXTEX
    e.rec(32, struct.pack("<4i", 2, 2, 2, 2))  # SCALEWINDOWEXTEX
    e.rec(32, struct.pack("<4i", 1, 0, 1, 1))  # a zero denominator
    e.select(e.pen(0, 8, RED)).select(e.brush(0, rgb(200, 230, 255)))
    e.box(43, 0, 0, 200, 150)
    e.rec(35, struct.pack("<6f", 0.8, 0.2, -0.2, 0.8, 300.0, 100.0))  # SETWORLDTRANSFORM
    e.box(42, 0, 0, 200, 150)
    for mode, matrix in ((2, (1.0, 0.0, 0.0, 1.0, 20.0, 0.0)), (3, (1.0, 0.0, 0.0, 1.0, 0.0, 20.0)), (1, (1, 0, 0, 1, 0, 0)),
                         (4, (0.5, 0.0, 0.0, 0.5, 0.0, 0.0)), (9, (1, 0, 0, 1, 0, 0))):
        e.rec(36, struct.pack("<6fI", *matrix, mode))  # MODIFYWORLDTRANSFORM
        e.box(44, 210, 160, 300, 220, 30, 30)
    e.rec(35, struct.pack("<6f", 0.0, 0.0, 0.0, 0.0, 0.0, 0.0))  # a singular transform
    return e.build(frame=(0, 0, 400, 300))


def emf_text() -> bytes:
    e = Emf()
    e.rec(24, struct.pack("<I", rgb(40, 40, 160)))  # SETTEXTCOLOR
    for index, (height, weight, escapement, align) in enumerate(((-24, 400, 0, 0), (-18, 700, 450, 24), (20, 400, 0, 6),
                                                                  (-16, 400, -300, 2))):
        font = e.font(height, weight, escapement, ("Arial", "Times New Roman", "Courier New", "Symbol")[index])
        e.select(font)
        e.rec(22, struct.pack("<I", align))  # SETTEXTALIGN
        e.text(20 + 90 * index, 60 + 50 * index, f"Text {index}", [12] * 6)
    e.rec(18, struct.pack("<I", 2)).rec(25, struct.pack("<I", rgb(255, 240, 200)))
    s = "boxed"
    body = struct.pack("<4iIff", 0, 0, -1, -1, 1, 0, 0)
    body += struct.pack("<iiIII4iI", 30, 250, len(s), 76, 0x0002 | 0x0004, 20, 230, 200, 270, 0)  # ETO_OPAQUE | CLIPPED
    e.rec(83, body + s.encode("cp1252").ljust(8, b"\0"))  # EXTTEXTOUTA, no dx
    s = "pdy"
    body = struct.pack("<4iIff", 0, 0, -1, -1, 1, 0, 0)
    body += struct.pack("<iiIII4iI", 220, 250, len(s), 76, 0x2000, 0, 0, -1, -1, 84)  # ETO_PDY
    e.rec(84, body + s.encode("utf-16-le").ljust(8, b"\0") + struct.pack("<6i", 10, 0, 10, 2, 10, 0))
    body = struct.pack("<4iIff", 0, 0, -1, -1, 1, 0, 0)
    body += struct.pack("<iiIII4iI", 300, 250, 2, 76, 0x0010, 0, 0, -1, -1, 0)  # ETO_GLYPH_INDEX
    e.rec(84, body + b"\x01\x00\x02\x00")
    return e.build()


def emf_bitmaps() -> bytes:
    e = Emf()
    header, bits = DIBS["24bpp"]
    # STRETCHDIBITS: bounds, x, y, xSrc, ySrc, cxSrc, cySrc, offsets, usage, rop, cxDest, cyDest
    for x, rop in ((10, 0x00CC0020), (60, 0x008800C6), (110, 0x00EE0086), (160, 0x00660046)):
        _bitmap_record(e, 81, struct.pack("<4i6i4III2i", 0, 0, 0, 0, x, 10, 0, 0, 3, 3, 0, 0, 0, 0, 0, rop, 40, 40),
                       header, bits, 48)
    one = DIBS["1bpp"]
    _bitmap_record(e, 81, struct.pack("<4i6i4III2i", 0, 0, 0, 0, 210, 10, 0, 0, 9, 3, 0, 0, 0, 0, 0, 0x00CC0020, 90, 30),
                   *one, 48)
    blt = struct.pack("<4i4iIii6fI5I", 0, 0, 0, 0, 10, 70, 40, 40, 0x00CC0020, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0)
    _bitmap_record(e, 76, blt, header, bits, 84)  # BITBLT
    patblt = struct.pack("<4i4iIii6fI5I", 0, 0, 0, 0, 60, 70, 40, 40, 0x00F00021, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0)
    e.rec(76, patblt)  # BITBLT with no bitmap: a PATCOPY
    stretch = blt + struct.pack("<ii", 3, 3)
    for kind, x, rop in ((77, 110, 0x00CC0020), (114, 160, 0x00800000), (116, 210, 0x00FFFFFF)):
        fixed = bytearray(stretch)
        struct.pack_into("<i", fixed, 16 - 8 + 16, x)
        struct.pack_into("<I", fixed, 40 - 8, rop)
        _bitmap_record(e, kind, bytes(fixed), header, bits, 84)
    _bitmap_record(e, 80, struct.pack("<4i6i4III", 0, 0, 0, 0, 260, 70, 0, 0, 3, 3, 0, 0, 0, 0, 0, 0), header, bits, 48)  # SETDIBITSTODEVICE
    _bitmap_record(e, 81, struct.pack("<4i6i4III2i", 0, 0, 0, 0, 310, 70, 0, 0, 2, 2, 0, 0, 0, 0, 0, 0x00CC0020, 40, 40),
                   *DIBS["32bpp-alpha"], 48)
    _bitmap_record(e, 81, struct.pack("<4i6i4III2i", 0, 0, 0, 0, 10, 130, 0, 0, 2, 2, 0, 0, 0, 0, 0, 0x00CC0020, 40, 40),
                   *DIBS["bad-depth"], 48)
    # Pattern brushes: a DIB one and a monochrome one, then a rectangle each.
    for kind, pattern in ((94, DIBS["8bpp-top-down"]), (93, DIBS["1bpp"]), (94, DIBS["jpeg"])):
        index = e.handle()
        head, data = pattern
        fixed = struct.pack("<6I", index, 0, 0, 0, 0, 0)
        start = 8 + len(fixed)
        patched = bytearray(fixed)
        struct.pack_into("<4I", patched, 8, start, len(head), start + len(head), len(data))
        e.rec(kind, bytes(patched) + head + data)
        e.select(index).box(43, 60 + 50 * (kind - 93), 130, 100 + 50 * (kind - 93), 170)
    # GRADIENTFILL: two rectangles (horizontal, vertical) and a triangle.
    vertices = b"".join(struct.pack("<iiHHHH", x, y, r, g, b, 0) for x, y, r, g, b in
                        ((10, 190, 0xFF00, 0, 0), (110, 230, 0, 0, 0xFF00), (120, 190, 0, 0xFF00, 0), (220, 230, 0xFF00, 0xFF00, 0)))
    e.rec(118, struct.pack("<4iIII", 0, 0, 0, 0, 4, 1, 0) + vertices + struct.pack("<II", 1, 0))
    e.rec(118, struct.pack("<4iIII", 0, 0, 0, 0, 4, 1, 1) + vertices + struct.pack("<II", 2, 3))
    e.rec(118, struct.pack("<4iIII", 0, 0, 0, 0, 4, 1, 2) + vertices + struct.pack("<III", 0, 1, 2))
    e.rec(118, struct.pack("<4iIII", 0, 0, 0, 0, 4, 1, 7) + vertices)
    return e.build()


def emf_with_plus_comment() -> bytes:
    """An EMF+ comment that draws nothing, so the GDI records are drawn instead."""
    e = Emf()
    plus = struct.pack("<HHII", 0x4001, 1, 28, 16) + struct.pack("<II", 0xDBC01002, 0)  # EmfPlusHeader
    plus += struct.pack("<HHII", 0x4002, 0, 12, 0)  # EmfPlusEndOfFile
    e.rec(70, struct.pack("<II", len(plus) + 4, 0x2B464D45) + plus)
    e.rec(70, struct.pack("<II", 4, 0))  # an ordinary comment
    e.select(e.brush(0, GREEN)).box(43, 50, 50, 350, 250)
    return e.build()


# -- WMF ----------------------------------------------------------------------------------


def _words(data: bytes) -> list[int]:
    data += b"\0" * (len(data) % 2)
    return list(struct.unpack(f"<{len(data) // 2}h", data))


def _colour(value: int) -> list[int]:
    return _words(struct.pack("<I", value))


def wmf_records(box=(0, 0, 400, 300)) -> list[tuple]:
    header, bits = DIBS["24bpp"]
    packed = _words(header + bits)
    face = _words(b"Arial".ljust(32, b"\0"))
    text = b"Hello"
    return [
        (0x0103, 8),  # SETMAPMODE
        (0x020B, 0, 0), (0x020C, 300, 400), (0x020F, 0, 0),  # window org, ext, offset
        (0x0410, 1, 1, 1, 1), (0x0410, 0, 1, 1, 1),  # SCALEWINDOWEXT
        (0x020D, 0, 0), (0x020E, 1, 1), (0x0211, 0, 0), (0x0412, 1, 1, 1, 1),  # viewport: not drawn
        (0x0102, 2), (0x0106, 2), (0x0104, 13), (0x0104, 6), (0x012E, 0),
        (0x0201, *_colour(rgb(255, 255, 200))), (0x0209, *_colour(BLUE)),
        (0x02FA, 0, 3, 0, *_colour(RED)),  # CREATEPENINDIRECT -> slot 0
        (0x02FC, 0, *_colour(rgb(200, 230, 255)), 0),  # CREATEBRUSHINDIRECT solid -> slot 1
        (0x02FC, 2, *_colour(GREEN), 4),  # hatch -> 2
        (0x02FC, 1, 0, 0, 0),  # null -> 3
        (0x02FC, 9, *_colour(GREY), 0),  # an unknown style -> 4
        (0x02FB, -20, 0, 0, 0, 700, *_words(bytes([1, 1, 0, 0, 0, 0, 0, 0])), *face),  # CREATEFONTINDIRECT -> 5
        (0x0142, 0, 0, *packed),  # DIBCREATEPATTERNBRUSH -> 6
        (0x00F7, 0),  # CREATEPALETTE: a placeholder -> 7
        (0x012D, 0), (0x012D, 1),
        (0x041B, 60, 90, 10, 10),  # RECTANGLE (bottom, right, top, left)
        (0x0418, 60, 180, 10, 100),  # ELLIPSE
        (0x061C, 12, 20, 60, 270, 10, 190),  # ROUNDRECT
        (0x012D, 2),
        (0x0324, 3, 300, 10, 390, 10, 345, 60),  # POLYGON
        (0x0325, 3, 10, 70, 60, 120, 110, 70),  # POLYLINE
        (0x0538, 2, 3, 3, 120, 70, 160, 70, 140, 110, 170, 70, 210, 70, 190, 110),  # POLYPOLYGON
        (0x0817, 100, 220, 100, 300, 130, 300, 70, 220),  # ARC
        (0x0830, 100, 310, 100, 390, 130, 390, 70, 310),  # CHORD
        (0x081A, 170, 10, 170, 90, 200, 90, 140, 10),  # PIE
        (0x041F, *_colour(RED), 150, 150),  # SETPIXEL
        (0x0214, 140, 100), (0x0213, 190, 160),  # MOVETO, LINETO
        (0x001E,),  # SAVEDC
        (0x0416, 260, 260, 140, 170),  # INTERSECTCLIPRECT
        (0x0415, 220, 220, 180, 180),  # EXCLUDECLIPRECT
        (0x012D, 6), (0x041B, 290, 290, 130, 160),
        (0x0127, -1),  # RESTOREDC
        (0x012D, 5), (0x0521, len(text), *_words(text), 200, 300),  # TEXTOUT
        (0x0A32, 240, 300, 5, 0x0006, 220, 300, 260, 390, *_words(text), 10, 10, 10, 10, 10),  # EXTTEXTOUT opaque
        (0x0A32, 280, 300, 2, 0, *_words(b"no")),
        (0x061D, *_colour(0x00F00021), 20, 40, 230, 10),  # PATBLT
        (0x0F43, *_colour(0x00CC0020), 0, 3, 3, 0, 0, 40, 40, 230, 60, *packed),  # STRETCHDIB
        (0x0B41, *_colour(0x00CC0020), 3, 3, 0, 0, 40, 40, 230, 110, *packed),  # DIBSTRETCHBLT
        (0x0940, *_colour(0x00CC0020), 0, 0, 3, 3, 230, 160, *packed),  # DIBBITBLT
        (0x0940, *_colour(0x00CC0020), 0, 0, 3, 3, 230, 210),  # with no bitmap
        (0x01F0, 7), (0x01F0, 0),  # DELETEOBJECT
        (0x02FA, 0, 1, 0, *_colour(BLACK_BRUSH & 0)),  # a new pen takes the freed slot
        (0x014C, 0), (0x014C, 1),  # SETLAYOUT
        (0x0626, 0),  # ESCAPE: ignored
        (0x0419, 0),  # FLOODFILL: not drawn
    ]


def wmf_placeable() -> bytes:
    return _wmf(wmf_records())


def wmf_without_placeable_header() -> bytes:
    """No placeable header: the picture's box is its first SETWINDOWORG / SETWINDOWEXT."""
    data = _wmf(wmf_records())
    return data[22:]


#: name -> the metafile's bytes.
METAFILES = {
    "emf-shapes": emf_shapes,
    "emf-paths-and-clips": emf_paths_and_clips,
    "emf-mapping": emf_mapping,
    "emf-text": emf_text,
    "emf-bitmaps": emf_bitmaps,
    "emf-plus-comment-falls-back": emf_with_plus_comment,
    "wmf-placeable": wmf_placeable,
    "wmf-window-only": wmf_without_placeable_header,
}
