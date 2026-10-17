"""EMF and WMF pictures drawn from their GDI records (``ooxml_common.metafile``).

The metafiles are built here, record by record from MS-EMF and MS-WMF, by a small writer
of our own.  The numbers they are held to are Windows PowerPoint's (PowerPoint for
Microsoft 365, round 7): its PDF export and slide show of 23 made-up metafiles in a
400 x 300 pt picture at (100, 60), each canvas 400 x 300 px on a 1920 x 1080 px,
508 x 286 mm reference device.  Positions are compared in points on that slide, to
0.05 pt unless a test says otherwise.
"""

from __future__ import annotations

import base64
import math
import re
import struct
import xml.etree.ElementTree as ET
import zlib

import pytest

from ooxml_common.metafile import inline_metafile_images, metafile_to_svg

SVG = "{http://www.w3.org/2000/svg}"
STOCK = 0x80000000
NULL_BRUSH, BLACK_BRUSH, WHITE_PEN, NULL_PEN = STOCK | 5, STOCK | 4, STOCK | 6, STOCK | 8
PX = 2540 / 96


def rgb(r, g, b):
    return r | (g << 8) | (b << 16)


WHITE, RED = rgb(255, 255, 255), rgb(255, 0, 0)


class Emf:
    """Records in, EMF bytes out: header (1920 x 1080 px, 508 x 286 mm) and EOF added."""

    def __init__(self):
        self.records: list[bytes] = []
        self.handles = 1

    def rec(self, kind, payload=b""):
        payload += b"\0" * ((-len(payload)) % 4)
        self.records.append(struct.pack("<II", kind, 8 + len(payload)) + payload)
        return self

    def handle(self):
        self.handles += 1
        return self.handles - 1

    def pen(self, style, width, colour):
        h = self.handle()
        self.rec(38, struct.pack("<IIiiI", h, style, width, 0, colour))
        return h

    def extpen(self, style, width, colour, entries=()):
        h = self.handle()
        self.rec(95, struct.pack("<5I", h, 0, 0, 0, 0) + struct.pack("<6I", style, width, 0, colour, 0, len(entries))
                 + b"".join(struct.pack("<I", e) for e in entries))
        return h

    def brush(self, style, colour, hatch=0):
        h = self.handle()
        self.rec(39, struct.pack("<4I", h, style, colour, hatch))
        return h

    def font(self, height, weight=400, escapement=0, face="Arial"):
        h = self.handle()
        lf = struct.pack("<5i8B", height, 0, escapement, escapement, weight, 0, 0, 0, 0, 0, 0, 0, 0)
        self.rec(82, struct.pack("<I", h) + lf + face.encode("utf-16-le").ljust(64, b"\0"))
        return h

    def select(self, h):
        return self.rec(37, struct.pack("<I", h))

    def poly16(self, kind, points):
        return self.rec(kind, struct.pack("<4iI", 0, 0, 0, 0, len(points)) + b"".join(struct.pack("<hh", *p) for p in points))

    def box(self, kind, *values):
        return self.rec(kind, struct.pack(f"<{len(values)}i", *values))

    def text(self, x, y, string, dx):
        s = string.encode("utf-16-le")
        s += b"\0" * ((-len(s)) % 4)
        body = struct.pack("<4iIff", 0, 0, -1, -1, 1, 0, 0)
        body += struct.pack("<iiIII4iI", x, y, len(string), 76, 0, 0, 0, -1, -1, 76 + len(s))
        return self.rec(84, body + s + b"".join(struct.pack("<i", d) for d in dx))

    def build(self, frame=(0, 0, 400, 300)):
        frame01 = tuple(round(v * PX) for v in frame)
        eof = struct.pack("<5I", 14, 20, 0, 16, 20)
        total = 108 + sum(map(len, self.records)) + len(eof)
        header = struct.pack("<II4i4iIIIIHHIII", 1, 108, 0, 0, 399, 299, *frame01, 0x464D4520, 0x10000, total,
                             len(self.records) + 2, self.handles, 0, 0, 0, 0)
        header += struct.pack("<4i3I2I", 1920, 1080, 508, 286, 0, 0, 0, 508000, 285750)
        return header + b"".join(self.records) + eof


# --------------------------------------------------------------------------------------
# Reading the SVG back as slide points
# --------------------------------------------------------------------------------------


def _matrix(text):
    if not text:
        return (1, 0, 0, 1, 0, 0)
    found = re.match(r"matrix\(([^)]*)\)", text)
    return tuple(float(v) for v in found.group(1).split()) if found else (1, 0, 0, 1, 0, 0)


def _points(d):
    values = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?(?:e-?\d+)?", d)]
    return list(zip(values[0::2], values[1::2]))


class Drawn:
    def __init__(self, data: bytes, box=(100, 60, 400, 300)):
        self.drawing = metafile_to_svg(data)
        assert self.drawing is not None
        self.root = ET.fromstring(self.drawing.svg)
        self.vb = [float(v) for v in self.root.get("viewBox").split()]
        self.box = box
        self.paths = list(self.root.iter(SVG + "path"))
        self.paths = [p for p in self.paths if not _in_defs(self.root, p)]

    def slide(self, x, y):
        bx, by, bw, bh = self.box
        vx, vy, vw, vh = self.vb
        return bx + (x - vx) * bw / vw, by + (y - vy) * bh / vh

    def bbox(self, path):
        a, b, c, d, e, f = _matrix(path.get("transform"))
        pts = [self.slide(a * x + c * y + e, b * x + d * y + f) for x, y in _points(path.get("d"))]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)


def _in_defs(root, element):
    defs = root.find(SVG + "defs")
    return defs is not None and any(element is e for e in defs.iter())


def close(found, expected, tolerance=0.05):
    assert len(found) == len(expected)
    for f, e in zip(found, expected):
        assert f == pytest.approx(e, abs=tolerance), (found, expected)


def line(e: Emf, x0, y0, x1, y1):
    e.rec(27, struct.pack("<ii", x0, y0)).rec(54, struct.pack("<ii", x1, y1))


# --------------------------------------------------------------------------------------
# The frame onto the picture
# --------------------------------------------------------------------------------------


def test_the_frame_is_inclusive_and_mapped_through_the_device_millimetres():
    """Windows: px 40 at 139.9 pt and 360 at 459.1 (0.9975, not 1.000); y 30 at 89.92 and
    240 at 299.40 -- szlMillimeters' 286 mm, not szlMicrometers' 285.75."""
    e = Emf()
    e.select(e.pen(0, 1, RED))
    line(e, 40, 30, 360, 30)
    line(e, 40, 240, 360, 240)
    drawn = Drawn(e.build())
    close(drawn.slide(40, 30), (139.9, 89.92))
    close(drawn.slide(360, 240), (459.1, 299.40))
    assert drawn.drawing.complete and drawn.drawing.warning() is None


@pytest.mark.parametrize("frame, point, expected", [
    ((0, 0, 800, 600), (164, 114), (181.90, 116.95)),   # frame twice the drawing: half size
    ((50, 50, 450, 350), (164, 114), (213.71, 123.88)),  # frame from (50, 50): moved by it
])
def test_the_frame_not_the_bounds_places_the_drawing(frame, point, expected):
    e = Emf()
    e.select(e.brush(0, WHITE)).select(NULL_PEN).box(42, 164, 114, 176, 126)
    drawn = Drawn(e.build(frame))
    close(drawn.bbox(drawn.paths[0])[:2], expected)


# --------------------------------------------------------------------------------------
# Pens and brushes
# --------------------------------------------------------------------------------------


def _stroked(drawn):
    return [p for p in drawn.paths if p.get("stroke")]


def test_null_pen_strokes_nothing_and_null_brush_fills_nothing():
    """Windows (slide 17): the PS_NULL rectangle is filled with no outline; the BS_NULL
    rectangle is outlined and unfilled.  PowerPoint for Mac draws a black outline."""
    e = Emf()
    e.select(e.extpen(5, 0, 0)).select(e.brush(0, RED)).box(43, 260, 230, 380, 290)
    e.select(e.pen(0, 2, WHITE)).select(e.brush(1, 0)).box(43, 40, 250, 160, 290)
    drawn = Drawn(e.build())
    first, second = drawn.paths
    assert first.get("fill") == "#FF0000" and first.get("stroke") is None
    assert second.get("fill") == "none" and second.get("stroke") == "#FFFFFF"
    close(drawn.bbox(first), (359.35, 289.43, 479.05, 349.28))


def test_createpen_widths_are_honoured_with_round_ends():
    """Windows: CREATEPEN width 5 a 5 pt band (y 117.36..122.35), round caps; width 20
    from x 129.93 (radius 10)."""
    e = Emf()
    for y, width in ((60, 5), (240, 20)):
        e.select(e.pen(0, width, WHITE))
        line(e, 40, y, 360, y)
    drawn = Drawn(e.build())
    widths = [float(p.get("stroke-width")) for p in _stroked(drawn)]
    assert widths == [5, 20]
    assert all(p.get("stroke-linecap") == "round" for p in _stroked(drawn))


@pytest.mark.parametrize("style, width, cap, dashes", [
    (1, 5, "round", "10 10"),            # CREATEPEN PS_DASH w5: 15 on, 5 off as drawn
    (1, 1, "round", "2 2"),              # CREATEPEN PS_DASH w1: [1.995 1.995] pt
    (2, 1, "round", "0 2"),              # CREATEPEN PS_DOT w1
])
def test_createpen_dashes(style, width, cap, dashes):
    e = Emf()
    e.select(e.pen(style, width, WHITE))
    line(e, 40, 90, 360, 90)
    path = _stroked(Drawn(e.build()))[0]
    assert path.get("stroke-linecap") == cap
    assert path.get("stroke-dasharray") == dashes


@pytest.mark.parametrize("style, width, entries, cap, dashes", [
    (0x10000 | 0x200 | 1, 6, (), None, "18 6"),             # geometric flat dash: [17.96 5.99] pt
    (0x10000 | 2, 6, (), "round", "0 12"),                  # geometric round dot: [0 11.97] pt
    (0x10000 | 0x200 | 7, 4, (10, 5, 2, 5), None, "10 5 2 5"),  # user style, logical units
])
def test_extcreatepen_dashes(style, width, entries, cap, dashes):
    e = Emf()
    e.select(e.extpen(style, width, WHITE, entries))
    line(e, 240, 60, 380, 60)
    path = _stroked(Drawn(e.build()))[0]
    assert path.get("stroke-linecap") == cap
    assert path.get("stroke-dasharray") == dashes
    assert float(path.get("stroke-width")) == width


def test_geometric_caps_and_joins():
    e = Emf()
    for style in (0x10000 | 0x200 | 0x2000, 0x10000, 0x10000 | 0x100 | 0x1000):
        e.select(e.extpen(style, 16, RED))
        e.poly16(87, [(40, 70), (120, 30), (200, 70)])
    caps = [(p.get("stroke-linecap"), p.get("stroke-linejoin")) for p in _stroked(Drawn(e.build()))]
    assert caps == [(None, None), ("round", "round"), ("square", "bevel")]


def test_a_cosmetic_pen_is_one_device_pixel_whatever_the_mapping():
    e = Emf()
    e.rec(17, struct.pack("<I", 8)).rec(9, struct.pack("<ii", 1000, 1000)).rec(11, struct.pack("<ii", 400, 300))
    e.select(e.pen(0, 0, WHITE))
    line(e, 0, 500, 1000, 500)
    path = _stroked(Drawn(e.build()))[0]
    a, b, c, d, _e, _f = _matrix(path.get("transform"))
    assert float(path.get("stroke-width")) * math.sqrt(abs(a * d - b * c)) == pytest.approx(1, abs=0.01)


def test_hatch_brush_with_an_opaque_background():
    e = Emf()
    e.rec(18, struct.pack("<I", 2)).rec(25, struct.pack("<I", rgb(255, 255, 0)))
    e.select(e.brush(2, rgb(0, 0, 255), 4)).select(NULL_PEN).box(43, 150, 20, 260, 140)
    drawn = Drawn(e.build())
    fills = [p.get("fill") for p in drawn.paths]
    assert fills[0] == "#FFFF00" and fills[1].startswith("url(#")
    pattern = drawn.root.find(f"{SVG}defs/{SVG}pattern")
    assert pattern.get("width") == "8" and pattern.get("height") == "8"


# --------------------------------------------------------------------------------------
# Shapes, fill modes and paths
# --------------------------------------------------------------------------------------


def test_rectangle_roundrect_and_ellipse_fill_exactly_their_box():
    """Windows slide 8: RECTANGLE (20,20,120,100) at 119.95..219.7; ROUNDRECT corner
    40 x 20 has radii 20 x 10 (its straight side from y 89.92); ELLIPSE (280,20,380,100)
    379.3..479.05."""
    e = Emf()
    e.select(NULL_PEN).select(e.brush(0, RED))
    e.box(43, 20, 20, 120, 100).box(44, 140, 20, 260, 100, 40, 20).box(42, 280, 20, 380, 100)
    drawn = Drawn(e.build())
    rect, round_rect, ellipse = drawn.paths
    close(drawn.bbox(rect), (119.95, 79.94, 219.70, 159.75))
    close(drawn.bbox(ellipse), (379.3, 79.94, 479.05, 159.75), 0.1)
    corner = [drawn.slide(x, y) for x, y in _points(round_rect.get("d"))]
    assert any(abs(x - 339.4) < 0.05 and abs(y - 79.94) < 0.05 for x, y in corner)


@pytest.mark.parametrize("mode, rule", [(1, "evenodd"), (2, None)])
def test_setpolyfillmode_is_honoured(mode, rule):
    """Windows slide 21: ALTERNATE leaves the inner square empty, WINDING fills it."""
    e = Emf()
    e.select(NULL_PEN).select(e.brush(0, RED)).rec(19, struct.pack("<I", mode))
    squares = [(20, 20), (160, 20), (160, 160), (20, 160), (60, 60), (120, 60), (120, 120), (60, 120)]
    e.rec(91, struct.pack("<4iII", 0, 0, 0, 0, 2, 8) + struct.pack("<II", 4, 4)
          + b"".join(struct.pack("<hh", *p) for p in squares))
    path = Drawn(e.build()).paths[0]
    assert path.get("fill-rule") == rule
    assert path.get("d").count("M") == 2


def test_shapes_in_a_path_bracket_are_added_to_the_path():
    """Windows slide 9: RECTANGLE and ELLIPSE inside BEGINPATH..ENDPATH, then
    STROKEANDFILLPATH under ALTERNATE: one even-odd ring, outlined."""
    e = Emf()
    e.select(e.pen(0, 4, WHITE)).select(e.brush(0, rgb(0, 0, 255))).rec(19, struct.pack("<I", 1))
    e.rec(59).box(43, 220, 150, 380, 290).box(42, 250, 170, 350, 270).rec(60).box(63, 0, 0, 400, 300)
    drawn = Drawn(e.build())
    assert len(drawn.paths) == 1
    path = drawn.paths[0]
    assert path.get("fill-rule") == "evenodd" and path.get("stroke") == "#FFFFFF"
    assert path.get("d").count("M") == 2
    close(drawn.bbox(path), (319.45, 209.62, 479.05, 349.28))


def test_fillpath_closes_and_never_strokes():
    e = Emf()
    e.select(e.pen(0, 3, WHITE)).select(e.brush(0, rgb(255, 255, 0)))
    e.rec(59).rec(27, struct.pack("<ii", 20, 120)).rec(54, struct.pack("<ii", 70, 20)).rec(54, struct.pack("<ii", 120, 120))
    e.rec(60).box(62, 0, 0, 400, 300)
    path = Drawn(e.build()).paths[0]
    assert path.get("stroke") is None and path.get("d").endswith("Z")


def test_each_lineto_is_stroked_on_its_own():
    """GDI strokes every LINETO separately, caps at both ends (Windows slide 1: the
    bracket's two arms are two round-ended bands)."""
    e = Emf()
    e.select(e.pen(0, 3, WHITE))
    e.rec(27, struct.pack("<ii", 20, 80)).rec(54, struct.pack("<ii", 20, 20)).rec(54, struct.pack("<ii", 80, 20))
    path = _stroked(Drawn(e.build()))[0]
    assert path.get("d").count("M") == 2


# --------------------------------------------------------------------------------------
# Mapping modes and transforms
# --------------------------------------------------------------------------------------


def test_anisotropic_mapping_and_its_anisotropic_pen():
    """Windows slide 10: window 1000 x 1000 onto 400 x 300; the logical rect
    (100,100,900,900) at 139.9..459.1 x 89.92..329.33; a 20-unit pen 8 wide in x, 6 in y."""
    e = Emf()
    e.rec(17, struct.pack("<I", 8)).rec(9, struct.pack("<ii", 1000, 1000)).rec(11, struct.pack("<ii", 400, 300))
    e.select(e.pen(0, 20, WHITE)).select(e.brush(0, RED)).box(43, 100, 100, 900, 900)
    drawn = Drawn(e.build())
    path = drawn.paths[0]
    close(drawn.bbox(path), (139.9, 89.92, 459.1, 329.33))
    a, _b, _c, d, _e, _f = _matrix(path.get("transform"))
    assert float(path.get("stroke-width")) * a == pytest.approx(8)
    assert float(path.get("stroke-width")) * d == pytest.approx(6)


@pytest.mark.parametrize("window_ext, viewport_org, viewport_ext, arrow", [
    ((1000, -1000), (200, 150), (400, 300), [(0, 400), (150, 100), (-150, 100)]),
    ((1000, 1000), (0, 300), (400, -300), [(500, 900), (650, 600), (350, 600)]),
])
def test_negative_extents_turn_the_picture_upright(window_ext, viewport_org, viewport_ext, arrow):
    """Windows slides 11 and 19: the arrow points up, its tip at (299.5, 89.92) and its
    barbs at y 179.7.  PowerPoint for Mac draws these wrongly."""
    e = Emf()
    e.rec(17, struct.pack("<I", 8)).rec(9, struct.pack("<ii", *window_ext))
    e.rec(12, struct.pack("<ii", *viewport_org)).rec(11, struct.pack("<ii", *viewport_ext))
    e.select(NULL_PEN).select(e.brush(0, WHITE)).poly16(86, arrow)
    drawn = Drawn(e.build())
    close(drawn.bbox(drawn.paths[0]), (239.65, 89.92, 359.35, 179.7))


def test_mm_text_with_a_window_origin():
    """Windows slide 19: MM_TEXT with SETWINDOWORGEX(-20, -20) puts (0,0,40,40) at
    device (20,20,60,60)."""
    e = Emf()
    e.rec(10, struct.pack("<ii", -20, -20)).select(NULL_PEN).select(e.brush(0, RED)).box(43, 0, 0, 40, 40)
    drawn = Drawn(e.build())
    close(drawn.bbox(drawn.paths[0]), (119.95, 79.94, 159.85, 119.85))


def test_world_transforms():
    """Windows slide 12: rotate 30 deg about (200, 150), then LEFTMULTIPLY scale 0.5; the
    small rectangle's corners at (268.78, 163.09) and (330.22, 256.16).  MWT_SET is left
    alone by Windows: the rectangle drawn after it stays at the origin (100, 60)."""
    c, s = math.cos(math.radians(30)), math.sin(math.radians(30))
    e = Emf()
    e.rec(35, struct.pack("<6f", c, s, -s, c, 200, 150))
    e.rec(36, struct.pack("<6fI", 0.5, 0, 0, 0.5, 0, 0, 2))
    e.select(NULL_PEN).select(e.brush(0, RED)).box(43, -100, -50, 100, 50)
    e.rec(36, struct.pack("<6fI", 1, 0, 0, 1, 0, 0, 1))
    e.rec(36, struct.pack("<6fI", 1, 0, 0, 1, 20, 20, 4))
    e.box(43, 0, 0, 40, 40)
    drawn = Drawn(e.build())
    close(drawn.bbox(drawn.paths[0]), (243.84, 163.09, 355.16, 256.16), 0.1)
    close(drawn.bbox(drawn.paths[1]), (100, 59.99, 139.9, 99.89))
    assert drawn.drawing.complete


# --------------------------------------------------------------------------------------
# Clipping and the saved state
# --------------------------------------------------------------------------------------


def test_restoredc_restores_the_clip_and_the_pen():
    e = Emf()
    e.select(e.pen(0, 2, WHITE)).rec(33)
    e.select(e.pen(0, 6, RED)).box(30, 100, 75, 300, 225).select(e.brush(0, RED)).box(42, 0, 0, 400, 300)
    e.rec(34, struct.pack("<i", -1)).select(NULL_BRUSH).box(43, 100, 75, 300, 225)
    drawn = Drawn(e.build())
    clipped = drawn.root.find(SVG + "g")
    assert clipped.get("clip-path", "").startswith("url(#")
    assert [p.get("stroke") for p in clipped.iter(SVG + "path")] == ["#FF0000"]
    last = drawn.root.findall(SVG + "path")[-1]
    assert last.get("stroke") == "#FFFFFF" and last.get("stroke-width") == "2"
    clip = drawn.root.find(f"{SVG}defs/{SVG}clipPath/{SVG}path")
    close(drawn.bbox(clip), (199.75, 134.81, 399.25, 284.44))


def test_selectclippath_clips_to_an_ellipse():
    e = Emf()
    e.rec(59).box(42, 100, 50, 300, 250).rec(60).rec(67, struct.pack("<I", 5))
    e.select(NULL_PEN).select(e.brush(0, rgb(0, 200, 0))).box(43, 0, 0, 400, 300)
    drawn = Drawn(e.build())
    clip = drawn.root.find(f"{SVG}defs/{SVG}clipPath/{SVG}path")
    close(drawn.bbox(clip), (199.75, 109.87, 399.25, 309.38), 0.1)


# --------------------------------------------------------------------------------------
# Bitmaps
# --------------------------------------------------------------------------------------


def _png_pixels(data):
    width, height = struct.unpack_from(">II", data, 16)
    kind = data[25]
    idat, at = b"", 8
    while at < len(data):
        length, tag = struct.unpack_from(">I4s", data, at)
        if tag == b"IDAT":
            idat += data[at + 8 : at + 8 + length]
        at += 12 + length
    raw = zlib.decompress(idat)
    channels = 4 if kind == 6 else 3
    stride = width * channels + 1
    return [[tuple(raw[y * stride + 1 + x * channels : y * stride + 1 + x * channels + 3]) for x in range(width)]
            for y in range(height)]


def _stretchdibits(e, dest, bmi, bits, src):
    dx, dy, dw, dh = dest
    body = struct.pack("<4i", dx, dy, dx + dw - 1, dy + dh - 1) + struct.pack("<6i", dx, dy, 0, 0, *src)
    body += struct.pack("<4I", 80, len(bmi), 80 + len(bmi), len(bits)) + struct.pack("<IIii", 0, 0x00CC0020, dw, dh)
    e.rec(81, body + bmi + bits)


def test_stretchdibits_placement_and_a_one_bit_palette():
    """Windows slide 13: the 1-bit checker at (220,20) 160 x 160 is drawn with its
    palette's red and blue (319.45..479.05 x 79.95..239.55); Mac draws black and white."""
    e = Emf()
    palette = bytes((0, 0, 255, 0, 255, 0, 0, 0))
    bmi = struct.pack("<IiiHHIIiiII", 40, 8, 8, 1, 1, 0, 0, 0, 0, 2, 0) + palette
    bits = b"".join(bytes((0xAA if r % 2 else 0x55, 0, 0, 0)) for r in range(8))
    _stretchdibits(e, (220, 20, 160, 160), bmi, bits, (8, 8))
    drawn = Drawn(e.build())
    group = drawn.root.find(SVG + "g")
    a, b, c, d, ex, f = _matrix(group.get("transform"))
    image = group.find(SVG + "image")
    w, h = float(image.get("width")), float(image.get("height"))
    close(drawn.slide(ex, f) + drawn.slide(ex + a * w, f + d * h), (319.45, 79.95, 479.05, 239.55))
    assert image.get("image-rendering") is None  # smoothed, as Windows' slide show draws it
    png = base64.b64decode(image.get("href").split(",", 1)[1])
    colours = {px for row in _png_pixels(png) for px in row}
    assert colours == {(255, 0, 0), (0, 0, 255)}


# --------------------------------------------------------------------------------------
# Text
# --------------------------------------------------------------------------------------


def _text_place(drawn, element_group):
    translate = re.match(r"translate\(([-\d.]+) ([-\d.]+)\)", element_group.get("transform"))
    return float(translate.group(1)), float(translate.group(2))


def test_text_top_aligned_with_dx():
    """Windows slide 16: Arial height -40, TA_TOP at (20, 20): 40 pt, baseline at
    116.08 (ascent 0.905 em below the point), 'l' (the fourth character, Dx 24) at
    191.93; within half a point."""
    e = Emf()
    e.select(e.font(-40)).rec(24, struct.pack("<I", WHITE)).rec(18, struct.pack("<I", 1))
    e.text(20, 20, "Hello EMF", [24] * 9)
    drawn = Drawn(e.build())
    group = drawn.root.find(SVG + "g")
    text = group.find(SVG + "text")
    x0, y0 = _text_place(drawn, group)
    xs = [float(v) for v in text.get("x").split()]
    baseline = drawn.slide(x0 + xs[3], y0 + float(text.get("y")))
    close(baseline, (191.93, 116.08), 0.5)
    assert float(text.get("font-size")) == 40 and text.text == "Hello EMF"
    assert "Arial" in text.get("font-family")


def test_escapement_turns_the_text():
    e = Emf()
    e.select(e.font(-30, 700, escapement=300)).rec(18, struct.pack("<I", 1)).rec(22, struct.pack("<I", 24))
    e.text(200, 250, "Rotated", [20] * 7)
    group = Drawn(e.build()).root.find(SVG + "g")
    assert group.get("transform") == "translate(200 250) rotate(-30)"
    assert group.find(SVG + "text").get("font-weight") == "bold"


def test_centred_text_with_dx_is_centred_on_its_advances():
    """Windows slide 20: 'Centre' TA_CENTER|TA_BASELINE at x 200 with Dx 18 starts at
    246.0 pt (half of 6 x 18 before the point).  Windows' baselines sit up to a pixel
    below the reference point (GDI's rounding); within one point."""
    e = Emf()
    e.select(e.font(-30)).rec(18, struct.pack("<I", 1)).rec(22, struct.pack("<I", 24 | 6))
    e.text(200, 220, "Centre", [18] * 6)
    drawn = Drawn(e.build())
    group = drawn.root.find(SVG + "g")
    x0, y0 = _text_place(drawn, group)
    first = float(group.find(SVG + "text").get("x").split()[0])
    close(drawn.slide(x0 + first, y0), (246.0, 280.35), 1.0)


def test_opaque_background_mode_boxes_the_text():
    e = Emf()
    e.select(e.font(-20)).text(10, 10, "ab", [10, 10])
    group = Drawn(e.build()).root.find(SVG + "g")
    assert group.find(SVG + "rect").get("fill") == "#FFFFFF"


def test_text_inlined_for_a_rasteriser():
    e = Emf()
    e.select(e.font(-20)).rec(18, struct.pack("<I", 1)).text(10, 10, "ab", [10, 10])
    svg = metafile_to_svg(e.build()).svg
    href = "data:image/svg+xml;base64," + base64.b64encode(svg).decode()
    page = (f'<svg xmlns="http://www.w3.org/2000/svg"><image x="5" y="6" width="40" height="30" '
            f'preserveAspectRatio="none" clip-path="url(#k)" href="{href}"/></svg>')
    inlined = inline_metafile_images(page)
    root = ET.fromstring(inlined)
    group = root.find(SVG + "g")
    assert group.get("clip-path") == "url(#k)"
    nested = group.find(SVG + "svg")
    assert (nested.get("x"), nested.get("y"), nested.get("width"), nested.get("height")) == ("5", "6", "40", "30")
    assert nested.find(f".//{SVG}text").text == "ab"
    other = page.replace(href, "data:image/svg+xml;base64," + base64.b64encode(b"<svg/>").decode())
    assert inline_metafile_images(other) == other


# --------------------------------------------------------------------------------------
# EMF+, WMF, and what is not drawn
# --------------------------------------------------------------------------------------


def test_an_emf_plus_dual_file_is_drawn_from_its_gdi_records_and_says_so():
    e = Emf()
    e.rec(70, struct.pack("<II", 28, 0x2B464D45) + struct.pack("<HHII", 0x4001, 1, 28, 16) + bytes(16))
    e.select(NULL_PEN).select(e.brush(0, RED)).box(43, 220, 20, 380, 140)
    drawing = metafile_to_svg(e.build())
    assert drawing.emf_plus and not drawing.complete and drawing.drawn == 1
    assert "EMF+" in drawing.warning()


def test_unsupported_records_are_named_once_each():
    e = Emf()
    e.rec(53, bytes(16)).rec(53, bytes(16)).rec(78, bytes(100))
    e.select(NULL_PEN).select(e.brush(0, RED)).box(43, 0, 0, 10, 10)
    drawing = metafile_to_svg(e.build())
    assert drawing.warning() == "not drawn: EMR_EXTFLOODFILL (x2), EMR_MASKBLT"


def test_a_metafile_that_draws_nothing_says_so():
    drawing = metafile_to_svg(Emf().rec(53, bytes(16)).build())
    assert drawing.drawn == 0 and "EMR_EXTFLOODFILL" in drawing.warning()


def _wmf(records, box=(0, 0, 400, 300), inch=96):
    def r(fn, *words):
        return struct.pack("<IH", 3 + len(words), fn) + b"".join(struct.pack("<h", w) for w in words)
    body = b"".join(r(*rec) for rec in records) + struct.pack("<IH", 3, 0)
    header = struct.pack("<HHHIHIH", 1, 9, 0x0300, 9 + len(body) // 2, 3, 8, 0)
    placeable = struct.pack("<IHhhhhHI", 0x9AC6CDD7, 0, *box, inch, 0)
    checksum = 0
    for k in range(10):
        checksum ^= struct.unpack_from("<H", placeable, 2 * k)[0]
    return placeable + struct.pack("<H", checksum) + header + body


def test_a_placeable_wmf_maps_its_box_and_leaves_out_an_ellipses_last_pixel():
    data = _wmf([(0x02FC, 0, -1, 0x00FF, 0), (0x012D, 0), (0x02FA, 5, 0, 0, 0, 0), (0x012D, 1),
                 (0x0418, 126, 176, 114, 164)])
    drawn = Drawn(data)
    assert drawn.drawing.width == pytest.approx(400) and drawn.drawing.height == pytest.approx(300)
    close(drawn.bbox(drawn.paths[0]), (264, 174, 275, 185))
    assert drawn.paths[0].get("stroke") is None


def test_a_wmf_pen_width_is_honoured():
    data = _wmf([(0x02FA, 0, 3, 0, -1, 0x00FF), (0x012D, 0), (0x0214, 80, 20), (0x0213, 20, 20)])
    path = _stroked(Drawn(data))[0]
    assert path.get("stroke-width") == "3"


@pytest.mark.parametrize("payload", [b"", b"\0" * 200, b"not a metafile", b"\x01\0\0\0" + bytes(100)])
def test_what_is_not_a_metafile_is_none(payload):
    assert metafile_to_svg(payload) is None


def test_truncation_and_corruption_never_raise():
    e = Emf()
    e.select(e.pen(0, 3, WHITE)).select(e.brush(2, RED, 3)).box(43, 1, 2, 30, 40).poly16(86, [(1, 1), (5, 9), (9, 1)])
    e.select(e.font(-12)).text(1, 1, "x", [5])
    e.rec(59).box(42, 0, 0, 9, 9).rec(60).rec(67, struct.pack("<I", 5))
    data = e.build()
    for cut in range(0, len(data), 3):
        metafile_to_svg(data[:cut])
    for at in range(108, len(data), 7):
        broken = bytearray(data)
        broken[at] ^= 0xFF
        metafile_to_svg(bytes(broken))
    wmf = _wmf([(0x02FA, 0, 3, 0, -1, 0x00FF), (0x012D, 0), (0x0324, 3, 0, 0, 10, 10, 20, 0)])
    for cut in range(0, len(wmf), 2):
        metafile_to_svg(wmf[:cut])


def test_lying_counts_are_capped():
    e = Emf()
    e.rec(86, struct.pack("<4iI", 0, 0, 0, 0, 0x7FFFFFFF) + struct.pack("<hh", 1, 1) * 3)
    e.rec(91, struct.pack("<4iII", 0, 0, 0, 0, 0x7FFFFFFF, 0x7FFFFFFF) + bytes(12))
    e.rec(81, bytes(72) + struct.pack("<ii", 10, 10))
    drawing = metafile_to_svg(e.build())
    assert drawing is not None


def test_the_output_is_reproducible():
    e = Emf()
    e.select(e.brush(2, RED, 5)).box(43, 0, 0, 50, 50)
    assert metafile_to_svg(e.build()).svg == metafile_to_svg(e.build()).svg
