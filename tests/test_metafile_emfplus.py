"""EMF+ pictures drawn from their EMF+ records (``ooxml_common.metafile.emfplus``).

The files are built here, record by record from [MS-EMFPLUS], by a small writer of our
own.  The numbers they are held to are Windows PowerPoint's (PowerPoint for Microsoft
365, round 7): its PDF export of 28 made-up EMF+ files (slide 26 does not export) in a
400 x 300 pt picture at (100, 60), and its slide show of slides 11 to 15, 23 and 26
(which wins where the two differ), each canvas 400 x 300 px on a 96 dpi
reference device, so that one EMF+ pixel is 400/401 pt.  Positions are compared in
points on that slide, to 0.1 pt unless a test says otherwise.  Tests marked *spec* hold
the player to [MS-EMFPLUS] where Windows has not been measured.
"""

from __future__ import annotations

import base64
import math
import re
import struct
import xml.etree.ElementTree as ET
import zlib

import pytest

from ooxml_common.metafile import metafile_to_svg

SVG = "{http://www.w3.org/2000/svg}"
PX = 2540 / 96
VERSION = 0xDBC01002
U_WORLD, U_DISPLAY, U_PIXEL, U_POINT, U_INCH = 0, 1, 2, 3, 4


def argb(r, g, b, a=255):
    return (a << 24) | (r << 16) | (g << 8) | b


WHITE, RED, GREEN, BLUE = argb(255, 255, 255), argb(230, 40, 40), argb(0, 192, 0), argb(40, 90, 230)


def f4(*values):
    return struct.pack(f"<{len(values)}f", *values)


def pad(data):
    return data + b"\0" * ((-len(data)) % 4)


# --------------------------------------------------------------------------------------
# The writer
# --------------------------------------------------------------------------------------


def solid(colour):
    return struct.pack("<III", VERSION, 0, colour)


def pen(width, colour=WHITE, unit=U_WORLD, **optional):
    """An EmfPlusPen; ``optional`` fields by their PenData flag, in the spec's order."""
    order = [("matrix", 0x1, "6f"), ("start", 0x2, "i"), ("end", 0x4, "i"), ("join", 0x8, "I"),
             ("miter", 0x10, "f"), ("style", 0x20, "i"), ("dash_cap", 0x40, "i"), ("offset", 0x80, "f"),
             ("dash", 0x100, None), ("align", 0x200, "i"), ("compound", 0x400, None)]
    flags, data = 0, b""
    for name, bit, fmt in order:
        if name not in optional:
            continue
        flags |= bit
        value = optional[name]
        if fmt is None:
            data += struct.pack("<I", len(value)) + f4(*value)
        elif fmt == "6f":
            data += f4(*value)
        else:
            data += struct.pack("<" + fmt, value)
    brush = optional.get("brush", solid(colour))
    return struct.pack("<IIIIf", VERSION, 0, flags, unit, width) + data + brush


def path_object(points, types):
    return pad(struct.pack("<III", VERSION, len(points), 0) + b"".join(f4(*p) for p in points) + bytes(types))


def bitmap(width, height, rows, fmt=0x0026200A):
    """Pixels top-down: ARGB (straight), PARGB (premultiplied) or 24-bit RGB."""
    if fmt == 0x00021808:
        stride = (width * 3 + 3) & ~3
        data = b"".join(pad(b"".join(bytes((b, g, r)) for r, g, b, _a in row)) for row in rows)
    else:
        stride = width * 4
        pre = fmt == 0x000E200B
        data = b"".join(bytes((round(b * a / 255) if pre else b, round(g * a / 255) if pre else g,
                               round(r * a / 255) if pre else r, a)) for row in rows for r, g, b, a in row)
    return struct.pack("<IIiiiII", VERSION, 1, width, height, stride, fmt, 0) + data


def png(width, height, rows):
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    raw = b"".join(b"\0" + b"".join(bytes(p) for p in row) for row in rows)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class Plus:
    """EMF+ records in, EMF bytes out (an EMF header for a 400 x 300 px frame on a
    1920 x 1080 px, 508 x 286 mm device; EMF+ header; end of file)."""

    def __init__(self, dual=True):
        self.emf: list[bytes] = []
        self.buffer: list[bytes] = []
        self.r(0x4001, 1 if dual else 0, struct.pack("<IIII", VERSION, 1, 96, 96))

    def r(self, kind, flags=0, data=b""):
        data = pad(data)
        self.buffer.append(struct.pack("<HHII", kind, flags, 12 + len(data), len(data)) + data)
        return self

    def flush(self):
        if self.buffer:
            payload = struct.pack("<I", 0x2B464D45) + b"".join(self.buffer)
            self.gdi(70, struct.pack("<I", len(payload)) + payload, flush=False)
            self.buffer = []

    def gdi(self, kind, payload=b"", flush=True):
        if flush:
            self.flush()
        payload = pad(payload)
        self.emf.append(struct.pack("<II", kind, 8 + len(payload)) + payload)
        return self

    def obj(self, kind, index, data):
        return self.r(0x4008, (kind << 8) | index, data)

    def brush(self, index, data):
        return self.obj(1, index, data if isinstance(data, bytes) else solid(data))

    def pen(self, index, *args, **kwargs):
        return self.obj(2, index, pen(*args, **kwargs))

    def fill_rects(self, colour, *rects, brush=None):
        flags, value = (0x8000, colour) if brush is None else (0, brush)
        return self.r(0x400A, flags, struct.pack("<II", value, len(rects)) + b"".join(f4(*r) for r in rects))

    def draw_rects(self, pen_id, *rects):
        return self.r(0x400B, pen_id, struct.pack("<I", len(rects)) + b"".join(f4(*r) for r in rects))

    def draw_lines(self, pen_id, points, closed=False):
        return self.r(0x400D, pen_id | (0x2000 if closed else 0),
                      struct.pack("<I", len(points)) + b"".join(f4(*p) for p in points))

    def fill_polygon(self, colour, points):
        return self.r(0x400C, 0x8000, struct.pack("<II", colour, len(points)) + b"".join(f4(*p) for p in points))

    def build(self):
        self.r(0x4002)
        self.flush()
        frame = tuple(round(v * PX) for v in (0, 0, 400, 300))
        eof = struct.pack("<5I", 14, 20, 0, 16, 20)
        total = 108 + sum(map(len, self.emf)) + len(eof)
        header = struct.pack("<II4i4iIIIIHHIII", 1, 108, 0, 0, 399, 299, *frame, 0x464D4520, 0x10000, total,
                             len(self.emf) + 2, 1, 0, 0, 0, 0)
        header += struct.pack("<4i3I2I", 1920, 1080, 508, 286, 0, 0, 0, 508000, 285750)
        return header + b"".join(self.emf) + eof


def gdi_red_rect(p: Plus):
    """GDI records: a red brush, the null pen, a rectangle (220, 20)-(380, 140)."""
    p.gdi(39, struct.pack("<4I", 1, 0, 0x0000FF, 0)).gdi(37, struct.pack("<I", 1))
    p.gdi(37, struct.pack("<I", 0x80000008)).gdi(43, struct.pack("<4i", 220, 20, 380, 140))


# --------------------------------------------------------------------------------------
# Reading the SVG back as slide points
# --------------------------------------------------------------------------------------


def _parse_matrix(text):
    m = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    for kind, args in re.findall(r"(matrix|translate|rotate|scale)\(([^)]*)\)", text or ""):
        v = [float(a) for a in args.replace(",", " ").split()]
        if kind == "matrix":
            step = tuple(v)
        elif kind == "translate":
            step = (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0)
        elif kind == "scale":
            step = (v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0)
        else:
            a = math.radians(v[0])
            step = (math.cos(a), math.sin(a), -math.sin(a), math.cos(a), 0, 0)
        m = _mul(step, m)
    return m


def _mul(first, then):
    a1, b1, c1, d1, e1, f1 = first
    a2, b2, c2, d2, e2, f2 = then
    return (a1 * a2 + b1 * c2, a1 * b2 + b1 * d2, c1 * a2 + d1 * c2, c1 * b2 + d1 * d2,
            e1 * a2 + f1 * c2 + e2, e1 * b2 + f1 * d2 + f2)


def _numbers(d):
    return [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?(?:e-?\d+)?", d)]


class Drawn:
    """The drawing, its elements outside ``<defs>`` with their device matrices."""

    def __init__(self, data: bytes):
        self.drawing = metafile_to_svg(data)
        assert self.drawing is not None
        self.root = ET.fromstring(self.drawing.svg)
        self.vb = [float(v) for v in self.root.get("viewBox").split()]
        self.items: list[tuple[ET.Element, tuple]] = []
        self.defs = self.root.find(SVG + "defs")
        self._walk(self.root, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0))

    def _walk(self, element, m):
        for child in element:
            if child.tag == SVG + "defs":
                continue
            cm = _mul(_parse_matrix(child.get("transform")), m)
            self.items.append((child, cm))
            if child.tag != SVG + "text":
                self._walk(child, cm)

    def of(self, tag):
        return [(e, m) for e, m in self.items if e.tag == SVG + tag]

    def slide(self, x, y):
        vx, vy, vw, vh = self.vb
        return 100 + (x - vx) * 400 / vw, 60 + (y - vy) * 300 / vh

    def points(self, element, m):
        values = _numbers(element.get("d"))
        out = []
        for x, y in zip(values[0::2], values[1::2]):
            out.append(self.slide(m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]))
        return out

    def bbox(self, element, m):
        pts = self.points(element, m)
        return (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))

    def device_width(self, element, m):
        return float(element.get("stroke-width")) * math.sqrt(abs(m[0] * m[3] - m[1] * m[2]))

    def by_id(self, ref):
        wanted = re.search(r"url\(#([^)]+)\)", ref).group(1)
        return next(e for e in self.root.iter() if e.get("id") == wanted)

    def paths(self, **attrs):
        return [(e, m) for e, m in self.of("path") if all(e.get(k.replace("_", "-")) == v for k, v in attrs.items())]


def close(found, expected, tolerance=0.1):
    assert len(found) == len(expected)
    for f, e in zip(found, expected):
        assert f == pytest.approx(e, abs=tolerance), (found, expected)


# --------------------------------------------------------------------------------------
# Which records are drawn
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("dual", [False, True])
def test_an_emf_plus_file_is_drawn_from_its_emf_plus_records_only(dual):
    """Windows slides 1 and 2: the EMF+ green rect at 119.95..279.56 pt; the GDI red
    rectangle not drawn, dual flag or not."""
    p = Plus(dual).fill_rects(GREEN, (20, 20, 160, 120))
    gdi_red_rect(p)
    drawn = Drawn(p.build())
    assert drawn.drawing.emf_plus and drawn.drawing.complete and drawn.drawing.warning() is None
    paths = drawn.of("path")
    assert [e.get("fill") for e, _ in paths] == ["#00C000"]
    close(drawn.bbox(*paths[0]), (119.95, 79.94, 279.56, 199.64))


def test_gdi_records_after_get_dc_are_drawn_until_the_next_emf_plus_record():
    """Windows slide 28: green, the GDI red rectangle, blue; not the GDI rectangle after
    the blue EMF+ one."""
    p = Plus().fill_rects(GREEN, (20, 20, 160, 100)).r(0x4004)
    gdi_red_rect(p)
    p.fill_rects(BLUE, (20, 180, 160, 100))
    p.gdi(43, struct.pack("<4i", 220, 180, 380, 280))  # after an EMF+ record: the fallback
    fills = [e.get("fill") for e, _ in Drawn(p.build()).of("path")]
    assert fills == ["#00C000", "#FF0000", "#285AE6"]


def test_unknown_emf_plus_records_are_named():
    p = Plus().r(0x4039, 0, bytes(8)).fill_rects(GREEN, (0, 0, 10, 10))
    drawing = metafile_to_svg(p.build())
    assert drawing.warning() == "not drawn: EmfPlusSetTSGraphics"


# --------------------------------------------------------------------------------------
# Pens
# --------------------------------------------------------------------------------------


def test_pen_width_is_centred_on_the_outline():
    """Windows slide 3: width 12 on (270, 130) 110 x 120 from 363.35 pt to 375.32."""
    p = Plus().pen(1, 12).draw_rects(1, (270, 130, 110, 120))
    drawn = Drawn(p.build())
    (path, m), = drawn.of("path")
    assert path.get("stroke-width") == "12" and path.get("fill") == "none"
    close(drawn.bbox(path, m)[:2], (369.34, 189.67))  # the outline: the band is 6 either side


def test_world_unit_widths_scale_with_the_world_transform_and_pixel_widths_do_not():
    """Windows slide 4 (ScaleWorldTransform 2): a world width 5 is a 10 px band (from
    114.96 to 124.94 pt); a pixel width keeps its device pixels (Windows' PDF draws them
    at 0.16 pt a pixel, its slide show unmeasured; here a reference-device pixel)."""
    p = Plus().r(0x402E, 0, f4(2, 2)).pen(1, 5).pen(2, 5, unit=U_PIXEL)
    p.draw_rects(1, (10, 55, 70, 30)).draw_rects(2, (110, 55, 70, 30))
    drawn = Drawn(p.build())
    (world, mw), (pixel, mp) = drawn.of("path")
    assert drawn.device_width(world, mw) == pytest.approx(10)
    assert drawn.device_width(pixel, mp) == pytest.approx(5)


def test_flat_square_and_round_caps():
    """Windows slide 5: flat ends at 139.9 pt; square and round reach 8 px past (131.92)."""
    p = Plus()
    for k, cap in enumerate((0, 1, 2)):
        p.pen(1, 16, start=cap, end=cap).draw_lines(1, [(40, 30 + 45 * k), (170, 30 + 45 * k)])
    caps = [e.get("stroke-linecap") for e, _ in Drawn(p.build()).of("path")]
    assert caps == [None, "square", "round"]


def test_an_arrow_anchor_is_two_widths_across_with_its_tip_on_the_end():
    """Windows slide 5: tip at 139.9 pt, base 27.65 pt in at y 293.51..325.43, the line
    from 155.86 to 253.62 pt (a width in at each end)."""
    p = Plus().pen(1, 16, start=0x14, end=0x14).draw_lines(1, [(40, 210), (170, 210)])
    drawn = Drawn(p.build())
    line, heads = drawn.of("path")
    close(drawn.bbox(*line)[::2], (155.86, 253.62), 0.1)
    xs = [x for x, _ in drawn.points(*heads)]
    ys = [y for _, y in drawn.points(*heads)]
    assert min(xs) == pytest.approx(139.9, abs=0.1) and max(xs) == pytest.approx(269.58, abs=0.1)
    assert min(ys) == pytest.approx(253.51, abs=0.1) and max(ys) == pytest.approx(285.43, abs=0.1)
    assert sorted(set(round(x, 1) for x in xs))[1] == pytest.approx(167.55, abs=0.15)


def test_triangle_caps_reach_half_the_width():
    """Windows slide 5: a triangle cap's point 8 px past the end (131.92 pt)."""
    p = Plus().pen(1, 16, start=3, end=3).draw_lines(1, [(40, 165), (170, 165)])
    drawn = Drawn(p.build())
    _line, caps = drawn.of("path")
    xs = [x for x, _ in drawn.points(*caps)]
    close((min(xs), max(xs)), (131.92, 277.56))


@pytest.mark.parametrize("join, miter, svg_join", [
    (0, None, "miter-clip"),   # Miter: past the limit, cut at it (Windows: a flat top 11.3 px up)
    (3, 2.0, None),            # MiterClipped: past the limit, bevelled
    (1, None, "bevel"),
    (2, None, "round"),
])
def test_joins(join, miter, svg_join):
    kwargs = {"join": join} if miter is None else {"join": join, "miter": miter}
    p = Plus().pen(1, 12, **kwargs).draw_lines(1, [(220, 150), (235, 70), (250, 150)])
    (path, _m), = Drawn(p.build()).of("path")
    assert path.get("stroke-linejoin") == svg_join
    if join in (0, 3):
        assert path.get("stroke-miterlimit") == ("2" if miter else "10")


@pytest.mark.parametrize("options, dashes, offset", [
    ({"style": 1}, "18 6", None),                  # Windows: 29.93..47.88 on, 6 off
    ({"style": 2}, "6 6", None),
    ({"style": 3}, "18 6 6 6", None),
    ({"style": 4}, "18 6 6 6 6 6", None),
    ({"style": 5, "dash": [4, 1, 1, 1]}, "24 6 6 6", None),
    ({"style": 5, "dash": [2, 2], "offset": 1.0}, "12 12", "6"),   # first dash 6 long
])
def test_dash_styles_are_multiples_of_the_width(options, dashes, offset):
    p = Plus().pen(1, 6, **options).draw_lines(1, [(30, 25), (370, 25)])
    (path, _m), = Drawn(p.build()).of("path")
    assert path.get("stroke-dasharray") == dashes
    assert path.get("stroke-dashoffset") == offset


def test_a_round_dash_cap_is_inside_the_dash_and_the_line_ends_flat():
    """Windows slide 6: width 10, dashes 20 long between round ends (30 in all), every
    40; the line's own ends flat."""
    p = Plus().pen(1, 10, style=1, dash_cap=2).draw_lines(1, [(30, 229), (370, 229)])
    drawn = Drawn(p.build())
    (path, _m), = drawn.of("path")
    assert path.get("stroke-dasharray") == "20 20" and path.get("stroke-linecap") == "round"
    mask_group = next(e for e, _ in drawn.of("g") if e.get("mask"))
    mask = drawn.by_id(mask_group.get("mask"))
    assert mask.find(SVG + "path").get("stroke-linecap") is None  # flat


def test_inset_alignment_keeps_a_closed_stroke_inside():
    """Windows slide 7: a width 16 inset pen on (230, 30) 140 x 90 fills 229.52..245.48
    pt inside the rectangle: the stroke doubled and clipped to the figure."""
    p = Plus().pen(1, 16, align=1).draw_rects(1, (230, 30, 140, 90))
    drawn = Drawn(p.build())
    (path, _m), = drawn.of("path")
    assert path.get("stroke-width") == "32"
    clip = drawn.by_id(path.get("clip-path"))
    assert _numbers(clip.find(SVG + "path").get("d"))[:2] == [230, 30]


def test_a_compound_pen_draws_its_bands():
    """Windows slide 7: width 30 with [0 .2 .4 .6 .8 1] is three 6 px bands (y 164.58..
    170.57, 176.55..182.54, 188.52..194.51 pt): a mask of nested strokes 30 white, 18
    black, 6 white."""
    p = Plus().pen(1, 30, compound=[0, 0.2, 0.4, 0.6, 0.8, 1]).draw_lines(1, [(30, 180), (370, 180)])
    drawn = Drawn(p.build())
    group = next(e for e, _ in drawn.of("g") if e.get("mask"))
    strokes = [(s.get("stroke"), s.get("stroke-width")) for s in drawn.by_id(group.get("mask"))]
    assert strokes == [("#FFFFFF", "30"), ("#000000", "18"), ("#FFFFFF", "6")]


# --------------------------------------------------------------------------------------
# Shapes
# --------------------------------------------------------------------------------------


def test_pie_angles_turn_clockwise_from_the_x_axis():
    """Windows slide 8: FillPie start 0 sweep 270 on (20, 150) 110 x 110 leaves out the
    upper right quarter: the outline runs from (184.68, 264.48) pt to the centre."""
    p = Plus().r(0x4010, 0x8000, struct.pack("<I", RED) + f4(0, 270) + f4(20, 150, 110, 110))
    drawn = Drawn(p.build())
    (path, m), = drawn.of("path")
    pts = drawn.points(path, m)
    close(pts[0], (229.68, 264.48))
    close(pts[-1], (174.82, 264.48))
    close(drawn.bbox(path, m), (119.95, 209.62, 229.68, 319.35))


def test_fill_polygon_is_even_odd_and_a_winding_closed_curve_nonzero():
    """Windows slides 9 and 12: the pentagram's centre empty; FillClosedCurve with W
    filled."""
    star = [(90 + 70 * math.sin(math.radians(144 * i)), 90 - 70 * math.cos(math.radians(144 * i))) for i in range(5)]
    p = Plus().fill_polygon(GREEN, star)
    for flags in (0x8000, 0xA000):
        p.r(0x4016, flags, struct.pack("<I", GREEN) + f4(0) + struct.pack("<I", 5) + b"".join(f4(*q) for q in star))
    rules = [e.get("fill-rule") for e, _ in Drawn(p.build()).of("path")]
    assert rules == ["evenodd", "evenodd", None]


def test_cardinal_spline_control_points_are_a_third_of_the_tension_times_the_chord():
    """Fitted to Windows slide 10 (tension 0.5 and 1 within 0.2 px of the stroke)."""
    pts = [(30, 40), (100, 0), (170, 40), (240, 0)]
    p = Plus().pen(1, 3).r(0x4018, 1, f4(1.0) + struct.pack("<III", 0, 3, 4) + b"".join(f4(*q) for q in pts))
    drawn = Drawn(p.build())
    (path, _m), = drawn.of("path")
    values = _numbers(path.get("d"))
    # The first Bézier: (30,40) + (100-30, 0-40)/3, then (100,0) - (170-30, 40-40)/3.
    assert values[:8] == pytest.approx([30, 40, 30 + 70 / 3, 40 - 40 / 3, 100 - 140 / 3, 0, 100, 0], abs=1e-3)


def test_draw_curve_offset_and_segments_keep_the_neighbours_tangents():
    pts = [(30, 40), (100, 0), (170, 40), (240, 0), (310, 40), (370, 10)]
    p = Plus().pen(1, 3).r(0x4018, 1, f4(0.5) + struct.pack("<III", 1, 3, 6) + b"".join(f4(*q) for q in pts))
    (path, _m), = Drawn(p.build()).of("path")
    values = _numbers(path.get("d"))
    assert values[:2] == [100, 0] and values[-2:] == [310, 40]
    assert values[2:4] == pytest.approx([100 + 0.5 / 3 * 140, 0], abs=1e-3)


def test_a_path_fills_even_odd_closing_open_subpaths_and_strokes_only_closed_ones():
    """Windows slides 11 and 12."""
    path = path_object([(20, 170), (100, 260), (180, 170), (220, 20), (300, 20), (300, 100)], [0, 1, 1, 0, 1, 0x81])
    p = Plus().obj(3, 0, path).r(0x4014, 0x8000, struct.pack("<I", BLUE)).pen(1, 3).r(0x4015, 0, struct.pack("<I", 1))
    (fill, _m1), (stroke, _m2) = Drawn(p.build()).of("path")
    assert fill.get("fill-rule") == "evenodd" and fill.get("d").count("Z") == 2
    assert stroke.get("d").count("Z") == 1


# --------------------------------------------------------------------------------------
# Brushes
# --------------------------------------------------------------------------------------


def test_hatches_are_eight_device_pixels_and_a_transparent_back_shows_through():
    """Windows slide 13 (slide show: lines every 8 screen pixels; here 8 reference
    pixels)."""
    p = Plus().brush(0, struct.pack("<5I", VERSION, 1, 0, WHITE, argb(30, 64, 175)))
    p.brush(1, struct.pack("<5I", VERSION, 1, 5, WHITE, 0x00000000))
    p.fill_rects(0, (20, 20, 110, 120), brush=0).fill_rects(0, (20, 160, 110, 120), brush=1)
    drawn = Drawn(p.build())
    fills = [e.get("fill") for e, _ in drawn.of("path")]
    assert fills[0] == "#1E40AF" and fills[1].startswith("url(") and fills[2].startswith("url(")
    assert len(fills) == 3  # no back layer for the transparent one
    pattern = drawn.by_id(fills[1])
    assert (pattern.get("width"), pattern.get("height")) == ("8", "8")


def linear(rect, c1, c2, *, wrap=0, matrix=None, factors=None, preset=None, reserved=None):
    flags, optional = 0, b""
    if matrix:
        flags |= 0x02
        optional += f4(*matrix)
    if preset:
        flags |= 0x04
        positions, colours = preset
        optional += struct.pack("<I", len(positions)) + f4(*positions) + struct.pack(f"<{len(colours)}I", *colours)
    if factors:
        flags |= 0x08
        positions, values = factors
        optional += struct.pack("<I", len(positions)) + f4(*positions) + f4(*values)
    r1, r2 = reserved if reserved is not None else (c1, c2)
    return struct.pack("<IIIi", VERSION, 4, flags, wrap) + f4(*rect) + struct.pack("<4I", c1, c2, r1, r2) + optional


def _gradient(drawn):
    (path, _m), = drawn.of("path")
    return drawn.by_id(path.get("fill"))


def test_a_linear_gradient_runs_along_its_rectangle_and_is_not_repeated():
    """Windows slide 14: red at 20 px to blue at 190 (PDF samples linear in sRGB); a
    57 px brush rectangle with WrapMode Tile is blue past 77 px (no repeat)."""
    p = Plus().brush(0, linear((210, 140, 57, 40), RED, BLUE, wrap=0)).fill_rects(0, (210, 140, 170, 40), brush=0)
    gradient = _gradient(Drawn(p.build()))
    assert gradient.tag == SVG + "linearGradient"
    assert [gradient.get(k) for k in ("x1", "y1", "x2", "y2")] == ["210", "140", "267", "140"]
    assert gradient.get("spreadMethod") is None  # pad
    assert [s.get("stop-color") for s in gradient] == ["#E62828", "#285AE6"]


def test_the_gradient_colours_are_the_reserved_fields():
    """Windows rev 1 of slide 14: Reserved1/Reserved2 0 (transparent) drew nothing."""
    p = Plus().brush(0, linear((20, 20, 170, 60), RED, BLUE, reserved=(0, 0))).fill_rects(0, (20, 20, 170, 60), brush=0)
    stops = [(s.get("stop-color"), s.get("stop-opacity")) for s in _gradient(Drawn(p.build()))]
    assert stops == [("#000000", "0"), ("#000000", "0")]


def test_blend_factors_and_preset_colours_are_stops():
    """Preset red/yellow/green: Windows' slide show (rev 1) red, yellow, green."""
    yellow = argb(250, 210, 30)
    p = Plus().brush(0, linear((20, 110, 170, 60), RED, BLUE, factors=([0, 0.5, 1], [0, 1, 0])))
    p.brush(1, linear((20, 200, 170, 60), RED, GREEN, preset=([0, 0.5, 1], [RED, yellow, GREEN])))
    p.fill_rects(0, (20, 110, 170, 60), brush=0).fill_rects(0, (20, 200, 170, 60), brush=1)
    drawn = Drawn(p.build())
    (a, _), (b, _) = drawn.of("path")
    assert [(s.get("offset"), s.get("stop-color")) for s in drawn.by_id(a.get("fill"))] == [
        ("0", "#E62828"), ("0.5", "#285AE6"), ("1", "#E62828")]
    assert [s.get("stop-color") for s in drawn.by_id(b.get("fill"))] == ["#E62828", "#FAD21E", "#00C000"]


def test_a_brush_transform_turns_the_gradient():
    m = (math.cos(math.pi / 4), math.sin(math.pi / 4), -math.sin(math.pi / 4), math.cos(math.pi / 4), 10, -20)
    p = Plus().brush(0, linear((230, 10, 100, 100), RED, BLUE, matrix=m)).fill_rects(0, (230, 10, 100, 100), brush=0)
    gradient = _gradient(Drawn(p.build()))
    assert gradient.get("gradientTransform").startswith("matrix(0.707 0.707 -0.707 0.707 10 -20")


def path_gradient(center_colour, center, surround, boundary):
    data = struct.pack("<IIIiI", VERSION, 3, 0, 4, center_colour) + f4(*center)
    data += struct.pack("<I", len(surround)) + struct.pack(f"<{len(surround)}I", *surround)
    return data + struct.pack("<i", len(boundary)) + b"".join(f4(*q) for q in boundary)


def _png_pixels(href):
    data = base64.b64decode(href.split(",", 1)[1])
    width, height = struct.unpack(">II", data[16:24])
    channels = 4 if data[25] == 6 else 3
    at, raw = 8, b""
    while at + 8 <= len(data) and data[at + 4 : at + 8] != b"IEND":
        length = struct.unpack(">I", data[at : at + 4])[0]
        if data[at + 4 : at + 8] == b"IDAT":
            raw += data[at + 8 : at + 8 + length]
        at += 12 + length
    raw = zlib.decompress(raw)
    stride = width * channels + 1

    def pixel(x, y):
        at = y * stride + 1 + channels * x
        return tuple(raw[at : at + channels]) + ((255,) if channels == 3 else ())

    return width, height, pixel


def test_a_path_gradient_shades_from_the_centre_to_the_corners():
    """Windows slides 15 (PDF and slide show): white at the centroid, red, green and
    blue at the corners, triangle by triangle; drawn as a bitmap clipped to the shape."""
    tri = [(100, 20), (180, 160), (20, 160)]
    p = Plus().brush(0, path_gradient(WHITE, (100, 340 / 3), [RED, GREEN, BLUE], tri))
    p.r(0x400C, 0, struct.pack("<II", 0, 3) + b"".join(f4(*q) for q in tri))
    drawn = Drawn(p.build())
    (image, _m), = drawn.of("image")
    x0, y0 = float(image.get("x")), float(image.get("y"))
    width, height, pixel = _png_pixels(image.get("href"))
    scale = width / float(image.get("width"))

    def at(x, y):
        return pixel(int((x - x0) * scale), int((y - y0) * scale))

    assert at(100, 340 / 3) == pytest.approx((255, 255, 255, 255), abs=4)
    assert at(100, 26)[:3] == pytest.approx((230, 40, 40), abs=20)
    assert at(174, 157)[:3] == pytest.approx((0, 192, 0), abs=20)
    assert at(30, 30)[3] == 0  # outside the boundary: nothing
    group = next(e for e, _ in drawn.of("g") if e.get("clip-path"))
    assert group.find(SVG + "image") is image


def texture(image, wrap=0, matrix=None):
    flags = 0x02 if matrix else 0
    return struct.pack("<IIIi", VERSION, 2, flags, wrap) + (f4(*matrix) if matrix else b"") + image


QUAD = [[(230, 40, 40, 255)] * 2 + [(255, 255, 255, 255)] * 2] * 2 + [[(255, 255, 255, 255)] * 2 + [(40, 90, 230, 255)] * 2] * 2


def test_texture_tiles_start_at_the_origin_and_clamp_draws_once():
    """Windows slide 16: scale 8 gives 32 px tiles from (0, 0) (31.92 pt); Clamp one
    image at (250, 180) 32 x 32; TileFlipXY drawn as Tile; pixels sharp."""
    image = bitmap(4, 4, QUAD)
    p = Plus().brush(0, texture(image, 3, (8, 0, 0, 8, 0, 0))).brush(1, texture(image, 4, (8, 0, 0, 8, 250, 180)))
    p.fill_rects(0, (20, 20, 170, 120), brush=0).fill_rects(0, (210, 160, 170, 120), brush=1)
    drawn = Drawn(p.build())
    (tiled, _m), = drawn.of("path")
    pattern = drawn.by_id(tiled.get("fill"))
    assert (pattern.get("width"), pattern.get("height")) == ("4", "4")
    assert pattern.get("patternTransform") == "matrix(8 0 0 8 0 0)"
    assert pattern.find(SVG + "image").get("image-rendering") == "optimizeSpeed"
    clamped = [(e, m) for e, m in drawn.of("image") if not any(e is c for c in pattern.iter())]
    (image_el, m), = clamped
    close(drawn.slide(m[4], m[5]), (349.38, 239.55))
    assert m[0] == pytest.approx(8)


# --------------------------------------------------------------------------------------
# Transforms and state
# --------------------------------------------------------------------------------------

ARROW = [(0, 8), (40, 8), (40, 0), (60, 18), (40, 36), (40, 28), (0, 28)]


@pytest.mark.parametrize("op, append, expected", [
    (0x402D, False, (159.85, 99.89, 189.78, 117.84)),   # Windows slide 17: translate (40, 0)
    (0x402D, True, (209.73, 109.86, 239.66, 127.82)),   # slide 18 at base (70, 50): 40 px
    (0x402F, True, (289.04, 222.69, 317.45, 244.76)),   # rotate 30 about the canvas origin
])
def test_world_transform_operations_prepend_unless_appended(op, append, expected):
    base = (0.5, 0, 0, 0.5, 40, 40) if not append else ((0.5, 0, 0, 0.5, 70, 50) if op == 0x402D else (0.5, 0, 0, 0.5, 250, 40))
    data = f4(40, 0) if op == 0x402D else f4(30)
    p = Plus().r(0x402A, 0, f4(*base)).r(op, 0x2000 if append else 0, data).fill_polygon(RED, ARROW)
    drawn = Drawn(p.build())
    close(drawn.bbox(*drawn.of("path")[0]), expected, 0.15)


def test_the_page_scale_is_honoured_and_a_low_byte_unit_is_not():
    """Windows slide 19: point x 0.5 written in the low byte drew (232.5, 7.5) 60 x 30 px
    (unit not converted, scale applied); a unit in the high byte is converted (spec)."""
    p = Plus().r(0x4030, U_POINT, f4(0.5)).fill_rects(RED, (465, 15, 120, 60))
    p.r(0x4030, U_INCH << 8, f4(1.0)).fill_rects(GREEN, (1, 1, 0.5, 0.25))
    drawn = Drawn(p.build())
    (low, m1), (high, m2) = drawn.of("path")
    close(drawn.bbox(low, m1), (331.94, 67.48, 391.79, 97.4))
    close(drawn.bbox(high, m2), (100 + 96 * 400 / 401, 60 + 96 * 0.99757, 100 + 144 * 400 / 401, 60 + 120 * 0.99757))


def test_a_container_without_a_page_unit_does_not_map_and_end_container_restores():
    """Windows slide 20: BeginContainer dst (20,160) 160x120 src (0,0) 80x60, unit in the
    low byte: the ellipse drawn at (0, 0) 80 x 60 (no mapping); a rotation inside a
    nested container gone after its EndContainer."""
    p = Plus().r(0x4027, U_PIXEL, f4(20, 160, 160, 120) + f4(0, 0, 80, 60) + struct.pack("<I", 10))
    p.r(0x400E, 0x8000, struct.pack("<I", RED) + f4(0, 0, 80, 60))
    p.r(0x4028, 0, struct.pack("<I", 11)).r(0x402F, 0, f4(45)).r(0x4029, 0, struct.pack("<I", 11))
    p.fill_rects(GREEN, (0, 0, 20, 20)).r(0x4029, 0, struct.pack("<I", 10))
    drawn = Drawn(p.build())
    (ellipse, m1), (rect, m2) = drawn.of("path")
    close(drawn.bbox(ellipse, m1), (100, 60, 179.8, 119.84))
    close(drawn.bbox(rect, m2), (100, 60, 119.95, 79.94))


def test_a_container_with_a_page_unit_maps_its_source_onto_its_destination():
    """*spec*: BeginContainer's unit in the flags' high byte."""
    p = Plus().r(0x4027, U_PIXEL << 8, f4(20, 160, 160, 120) + f4(0, 0, 80, 60) + struct.pack("<I", 1))
    p.fill_rects(RED, (0, 0, 80, 60))
    drawn = Drawn(p.build())
    close(drawn.bbox(*drawn.of("path")[0]), (119.95, 219.61, 279.56, 339.30))


def test_restore_returns_to_its_save_and_drops_later_ones():
    """Windows slide 20: Save 2, translate, Save 3, translate, Restore 2: untransformed
    (magenta at 459.12 pt)."""
    p = Plus().r(0x4025, 0, struct.pack("<I", 2)).r(0x402D, 0, f4(50, 50)).r(0x4025, 0, struct.pack("<I", 3))
    p.r(0x402D, 0, f4(50, 50)).r(0x4026, 0, struct.pack("<I", 2)).fill_rects(RED, (360, 20, 30, 30))
    p.r(0x4026, 0, struct.pack("<I", 3)).fill_rects(GREEN, (0, 0, 10, 10))
    drawn = Drawn(p.build())
    (first, m1), (second, m2) = drawn.of("path")
    close(drawn.bbox(first, m1)[:2], (459.12, 79.94))
    close(drawn.bbox(second, m2)[:2], (100, 60))  # Save 3 was dropped: nothing to restore


def _clip_chain(drawn, element):
    """The clipPaths an element is drawn in, outermost first, as their path data."""
    ids = []
    parents = {c: p for p in drawn.root.iter() for c in p}
    node = element
    while node is not None:
        ref = node.get("clip-path")
        if ref:
            clip = drawn.by_id(ref)
            while clip is not None:
                ids.append([(p.get("d"), p.get("clip-rule")) for p in clip])
                ref = clip.get("clip-path")
                clip = drawn.by_id(ref) if ref else None
        node = parents.get(node)
    return ids


def test_clip_rect_replace_intersect_exclude_and_reset():
    """Windows slide 21: replace then intersect -> both clips; Exclude an even-odd
    region with a hole; ResetClip -> none.  A clip rectangle is in world units through
    the transform (slide 20: translated with it)."""
    p = Plus().r(0x4032, 0, f4(20, 20, 160, 120)).r(0x4032, 1 << 8, f4(60, 60, 160, 120))
    p.fill_rects(GREEN, (0, 0, 200, 200))
    p.r(0x4032, 4 << 8, f4(260, 60, 80, 80)).fill_rects(RED, (200, 0, 200, 200))
    p.r(0x4031).fill_rects(BLUE, (0, 220, 400, 40))
    p.r(0x402D, 0, f4(200, 0)).r(0x4032, 0, f4(0, 0, 50, 50)).fill_rects(WHITE, (0, 0, 10, 10))
    drawn = Drawn(p.build())
    green, red, blue, white = (e for e, _ in drawn.of("path"))
    assert len(_clip_chain(drawn, green)) == 2
    excluded = _clip_chain(drawn, red)
    assert excluded[0][0][1] == "evenodd"
    assert _clip_chain(drawn, blue) == []
    assert _numbers(_clip_chain(drawn, white)[0][0][0])[:2] == [200, 0]


def test_clip_path_is_even_odd_in_device_space():
    circle = path_object([(10, 10), (90, 10), (90, 90), (10, 90)], [0, 1, 1, 0x81])
    p = Plus().obj(3, 0, circle).r(0x4033, 0).fill_rects(RED, (0, 0, 100, 100))
    drawn = Drawn(p.build())
    (path, _m), = drawn.of("path")
    (rule,) = {r for (d, r) in _clip_chain(drawn, path)[0]}
    assert rule == "evenodd"


# --------------------------------------------------------------------------------------
# Images
# --------------------------------------------------------------------------------------

MARKER = [[(230, 40, 40, 255) if x < 2 and y < 2 else (40, 90, 230, 255) if x >= 6 and y < 2
           else (255, 255, 255, 255) for x in range(8)] for y in range(6)]


def draw_image(p, index, src, dst):
    return p.r(0x401A, index, struct.pack("<Ii", 63, U_PIXEL) + f4(*src) + f4(*dst))


@pytest.mark.parametrize("payload", [
    bitmap(8, 6, MARKER), bitmap(8, 6, MARKER, 0x00021808), bitmap(8, 6, MARKER, 0x000E200B),
    struct.pack("<IIiiiII", VERSION, 1, 8, 6, 32, 0x0026200A, 1) + png(8, 6, MARKER),
])
def test_bitmaps_are_top_down_and_drawn_in_their_destination(payload):
    """Windows slide 22: red top-left whatever the pixel format; 8 x 6 into (40, 20) 64 x 48
    at 139.9..203.75 pt."""
    p = Plus().obj(5, 0, pad(payload))
    draw_image(p, 0, (0, 0, 8, 6), (40, 20, 64, 48))
    drawn = Drawn(p.build())
    (image, m), = drawn.of("image")
    close(drawn.slide(m[4], m[5]), (139.9, 79.94))
    close(drawn.slide(m[0] * 8 + m[4], m[3] * 6 + m[5]), (203.75, 127.82))
    width, height, pixel = _png_pixels(image.get("href"))
    assert pixel(0, 0)[:3] == (230, 40, 40) and pixel(7, 0)[:3] == (40, 90, 230) and pixel(0, 5)[:3] == (255, 255, 255)


def test_draw_image_points_maps_three_corners():
    """Windows slide 22: mirrored (upper-right left of upper-left) at 299.51..363.35 pt."""
    p = Plus().obj(5, 0, bitmap(8, 6, MARKER))
    p.r(0x401B, 0, struct.pack("<Ii", 63, U_PIXEL) + f4(0, 0, 8, 6) + struct.pack("<I", 3)
        + f4(264, 150) + f4(200, 150) + f4(264, 198))
    drawn = Drawn(p.build())
    (_image, m), = drawn.of("image")
    assert m[0] < 0
    close(drawn.slide(m[4], m[5]), (363.35, 209.62))


def test_a_source_rectangle_is_clipped():
    p = Plus().obj(5, 0, bitmap(8, 6, MARKER))
    draw_image(p, 0, (4, 0, 4, 3), (130, 20, 64, 48))
    drawn = Drawn(p.build())
    (_image, m), = drawn.of("image")
    close(drawn.slide(m[0] * 4 + m[4], m[5]), (229.68, 79.94))  # source x 4 at the destination's left
    assert any(e.get("clip-path") for e, _ in drawn.of("g"))


def test_nearest_neighbour_interpolation_is_sharp():
    """Windows' slide show (slide 23): NearestNeighbor sharp; Default, Bilinear and
    HighQualityBicubic smoothed."""
    p = Plus().obj(5, 0, bitmap(8, 6, MARKER))
    draw_image(p, 0, (0, 0, 8, 6), (0, 0, 80, 60))
    p.r(0x4021, 5)
    draw_image(p, 0, (0, 0, 8, 6), (100, 0, 80, 60))
    smooth, sharp = (e for e, _ in Drawn(p.build()).of("image"))
    assert smooth.get("image-rendering") is None and sharp.get("image-rendering") == "optimizeSpeed"


def test_a_metafile_image_is_drawn_inline():
    inner = Plus().fill_rects(GREEN, (0, 0, 400, 300)).build()
    p = Plus().obj(5, 0, pad(struct.pack("<IIII", VERSION, 2, 3, len(inner)) + inner))
    draw_image(p, 0, (0, 0, 400, 300), (0, 0, 200, 150))
    drawn = Drawn(p.build())
    assert any(e.get("fill") == "#00C000" for e, _ in drawn.of("path"))


# --------------------------------------------------------------------------------------
# Text (Windows' PDF of slides 24 and 25; slide 26, DrawDriverString, does not export)
# --------------------------------------------------------------------------------------


def font(size, unit=U_PIXEL, style=0, family="Arial"):
    return pad(struct.pack("<IfIiII", VERSION, size, unit, style, 0, len(family)) + family.encode("utf-16-le"))


def string_format(align=0, line_align=0, flags=0):
    return struct.pack("<IIIIIIIfifffIii", VERSION, flags, 0x0409, align, line_align, 0, 0x0409, 0.0, 0, 0.0, 0.0,
                       1.0, 0, 0, 0)


def draw_string(p, font_id, colour, fmt, rect, text):
    return p.r(0x401C, 0x8000 | font_id, struct.pack("<III", colour, fmt, len(text)) + f4(*rect)
               + text.encode("utf-16-le"))


def test_draw_string_sizes_alignment_and_first_baseline():
    """Windows slide 24: 18 pt is 24 px (the same ink width as 24 px); Near text at the
    box's x (ink from 21.7 px, Arial's L bearing 1.76 px), Center a sixth of an em left of
    the centre (ink centred at 196.5 px), Far a third of an em in; the first baseline
    41.08 px for a top of 20 (0.97 of Arial's ascent)."""
    p = Plus().obj(6, 0, font(24)).obj(6, 1, font(18, U_POINT, 3))
    for k in range(3):
        p.obj(7, 10 + k, string_format(k))
    draw_string(p, 0, WHITE, 10, (20, 20, 360, 36), "Left")
    draw_string(p, 1, WHITE, 11, (20, 64, 360, 36), "Centre")
    draw_string(p, 0, WHITE, 12, (20, 108, 360, 36), "Right")
    texts = [e for e, _ in Drawn(p.build()).of("text")]
    assert [t.get("font-size") for t in texts] == ["24", "24", "24"]
    assert [(t.get("x"), t.get("text-anchor")) for t in texts] == [("20", None), ("196", "middle"), ("372", "end")]
    assert float(texts[0].get("y")) == pytest.approx(41.08, abs=0.1)
    assert texts[1].get("font-weight") == "bold" and texts[1].get("font-style") == "italic"


def test_draw_string_wraps_in_its_rectangle_and_clips_unless_told_not_to():
    fox = "The quick brown fox jumps over the lazy dog"
    p = Plus().obj(6, 0, font(20)).obj(7, 1, string_format()).obj(7, 2, string_format(flags=0x1000))
    draw_string(p, 0, WHITE, 1, (20, 200, 200, 90), fox)
    draw_string(p, 0, WHITE, 2, (240, 200, 140, 90), fox)
    drawn = Drawn(p.build())
    texts = [e for e, _ in drawn.of("text")]
    wrapped = [t for t in texts if t.get("x") == "20"]
    assert len(wrapped) == 3 and " ".join(t.text for t in wrapped) == fox
    assert len([t for t in texts if t.get("x") == "240"]) == 1
    clips = [drawn.by_id(e.get("clip-path")) for e, _ in drawn.of("g") if e.get("clip-path")]
    assert len(clips) == 2
    # Windows: the clip is the box moved a sixth of an em left (16.72 pt for 19.95).
    assert _numbers(clips[0].find(SVG + "path").get("d"))[:2] == pytest.approx([20 - 20 / 6, 200], abs=0.01)


@pytest.mark.parametrize("line_align, baseline", [(0, 44.6), (1, 157.27), (2, 269.95)])
def test_line_alignment(line_align, baseline):
    """Windows slide 25: Arial 28 px in (20, 20) 110 x 260, baselines 44.49, 156.88 and
    269.28 pt (44.6, 157.27, 269.95 px)."""
    p = Plus().obj(6, 0, font(28)).obj(7, 1, string_format(1, line_align))
    draw_string(p, 0, WHITE, 1, (20, 20, 110, 260), "Middle")
    (text, _m), = Drawn(p.build()).of("text")
    assert float(text.get("y")) == pytest.approx(baseline, abs=0.1)


def test_driver_string_places_each_character_and_skips_glyph_indices():
    p = Plus().obj(6, 0, font(32))
    glyphs = struct.pack("<4H", *map(ord, "ABCD"))
    positions = b"".join(f4(x, 60) for x in (20, 70, 120, 170))
    for options in (0x1, 0x0):
        p.r(0x4036, 0x8000, struct.pack("<IIII", WHITE, options, 0, 4) + glyphs + positions)
    drawn = Drawn(p.build())
    (text, _m), = drawn.of("text")
    assert text.text == "ABCD" and text.get("x") == "20 70 120 170" and text.get("y") == "60 60 60 60"
    assert "EmfPlusDrawDriverString by glyph index" in drawn.drawing.warning()


# --------------------------------------------------------------------------------------
# Colour
# --------------------------------------------------------------------------------------


def test_translucent_colours_and_source_copy():
    """Windows slides 27 and 29: alpha as opacity (0.502 for 128); SourceCopy blended as
    SourceOver."""
    p = Plus().fill_rects(argb(230, 40, 40, 128), (20, 20, 160, 50)).pen(1, 10, argb(30, 200, 220, 160))
    p.draw_rects(1, (220, 180, 160, 50)).r(0x4023, 1).fill_rects(argb(230, 40, 40, 128), (20, 200, 160, 80))
    drawn = Drawn(p.build())
    fill, stroke, copy = (e for e, _ in drawn.of("path"))
    assert fill.get("fill-opacity") == "0.502" and stroke.get("stroke-opacity") == "0.627"
    assert copy.get("fill-opacity") == "0.502" and drawn.drawing.warning() is None


# --------------------------------------------------------------------------------------
# Hostile input
# --------------------------------------------------------------------------------------


def _busy() -> bytes:
    p = Plus().pen(1, 4, style=1, compound=[0, 0.3, 0.7, 1], start=0x14, end=3)
    p.brush(2, path_gradient(WHITE, (10, 10), [RED], [(0, 0), (20, 0), (20, 20)]))
    p.brush(3, linear((0, 0, 50, 50), RED, BLUE, factors=([0, 1], [0, 1])))
    p.obj(3, 4, path_object([(0, 0), (10, 0), (10, 10), (0, 10)], [0, 3, 3, 0x83]))
    p.obj(5, 5, bitmap(2, 2, [[(1, 2, 3, 4)] * 2] * 2)).obj(6, 6, font(12)).obj(7, 7, string_format())
    p.draw_lines(1, [(0, 0), (50, 50), (90, 10)]).fill_rects(0, (0, 0, 20, 20), brush=2)
    p.fill_rects(0, (0, 0, 50, 50), brush=3).r(0x4033, 1 << 8 | 4).r(0x4015, 4, struct.pack("<I", 1))
    draw_image(p, 5, (0, 0, 2, 2), (0, 0, 20, 20))
    draw_string(p, 6, WHITE, 7, (0, 0, 100, 50), "hello world")
    return p.build()


def test_truncation_and_corruption_never_raise():
    data = _busy()
    assert metafile_to_svg(data).drawn > 0
    for cut in range(0, len(data), 5):
        metafile_to_svg(data[:cut])
    for at in range(108, len(data), 3):
        broken = bytearray(data)
        broken[at] ^= 0xFF
        metafile_to_svg(bytes(broken))


def test_lying_counts_and_objects_are_capped():
    p = Plus().r(0x400A, 0x8000, struct.pack("<II", RED, 0x7FFFFFFF) + f4(0, 0, 1, 1))
    p.r(0x4008, 0x8000 | (1 << 8) | 3, struct.pack("<I", 0xFFFFFFF0) + bytes(8))
    p.obj(3, 2, struct.pack("<III", VERSION, 0x7FFFFFFF, 0))
    p.obj(5, 3, struct.pack("<IIiiiII", VERSION, 1, 100000, 100000, 400000, 0x0026200A, 0))
    p.r(0x4008, 200, b"")  # an object id past 63
    drawing = metafile_to_svg(p.build())
    assert drawing is not None and drawing.drawn == 0


def test_continued_objects_are_assembled():
    data = solid(GREEN)
    p = Plus()
    p.r(0x4008, 0x8000 | (1 << 8) | 0, struct.pack("<I", len(data)) + data[:8])
    p.r(0x4008, 0x8000 | (1 << 8) | 0, struct.pack("<I", len(data)) + data[8:])
    p.fill_rects(0, (0, 0, 10, 10), brush=0)
    (path, _m), = Drawn(p.build()).of("path")
    assert path.get("fill") == "#00C000"


def test_the_output_is_reproducible():
    assert metafile_to_svg(_busy()).svg == metafile_to_svg(_busy()).svg


def test_an_image_is_sampled_as_windows_samples_it():
    """Windows' slide show (slide 23): a 4 x 4 checker in 80 x 80 with NearestNeighbor
    starts with a 10 px block and stops 10 px early; smoothed ones fade out at the right
    and bottom.  The bitmap is drawn half a source pixel up and left with a transparent
    column and row after it, clipped to the source rectangle."""
    rows = [[(230, 40, 40, 255) if (x + y) % 2 == 0 else (255, 255, 255, 255) for x in range(4)] for y in range(4)]
    p = Plus().obj(5, 0, bitmap(4, 4, rows)).r(0x4021, 5)
    draw_image(p, 0, (0, 0, 4, 4), (220, 20, 80, 80))
    drawn = Drawn(p.build())
    (image, m), = drawn.of("image")
    assert (image.get("x"), image.get("y"), image.get("width"), image.get("height")) == ("-0.5", "-0.5", "5", "5")
    width, height, pixel = _png_pixels(image.get("href"))
    assert (width, height) == (5, 5) and pixel(4, 0)[3] == 0 and pixel(0, 4)[3] == 0 and pixel(0, 0)[3] == 255
    close(drawn.slide(m[0] * -0.5 + m[4], m[5]), (100 + 210 * 400 / 401, 60 + 20 * 0.99757))
