"""One face's font program, read as resvg reads it: character map, advances, metrics,
variations and glyph outlines.

resvg (0.48, through resvg-py 0.5) shapes with harfrust and draws outlines with skrifa;
this module reads the same tables the same way, standard library only:

* **Character map** -- harfrust's choice of subtable: a full-repertoire Unicode one
  (format 12 or 13), else a BMP one, else a symbol font's ``(3, 0)``, whose U+F0xx
  glyphs a character U+00xx also reaches.
* **Advances** -- ``hmtx``, moved by ``HVAR`` (or, without it, by ``gvar``'s phantom
  points) at the instance asked for.
* **Variations** -- ``fvar`` coordinates normalised and mapped through ``avar``, rounded
  to F2Dot14 as both libraries do; resvg sets ``wght`` from ``font-weight`` on every run,
  ``wdth`` from ``font-stretch``, ``ital`` for italic and ``opsz`` to the font size.
* **Outlines** -- unhinted, in font units: ``glyf`` (simple and composite glyphs, moved by
  ``gvar`` with untouched points interpolated) and ``CFF`` (Type 2 charstrings, CID-keyed
  or not).  ``CFF2`` and colour glyphs (``COLR``, ``sbix``, ``CBDT``, ``SVG``) are not
  drawn here: :attr:`OutlineFace.unsupported` says why, and the caller keeps the text.

Nothing is cached across faces but the face itself (:func:`load_face`); a face keeps the
glyphs it has drawn, per instance.
"""

from __future__ import annotations

import functools
import struct
import threading
from typing import Iterable, Sequence

from ..fonts.office import _cmap_subtable, font_offsets, read_legacy_kern, table_directory

__all__ = ["OutlineFace", "load_face", "path_data"]

#: A path in font units: ``("M", x, y)``, ``("L", x, y)``, ``("Q", x1, y1, x, y)``,
#: ``("C", x1, y1, x2, y2, x, y)``, ``("Z",)``.
Command = tuple


class FaceError(Exception):
    """A table could not be read."""


def _f2dot14(value: int) -> float:
    return value / 16384.0


def _round_f2dot14(value: float) -> float:
    return round(value * 16384.0) / 16384.0


# --------------------------------------------------------------------------------------
# Item variation stores (HVAR, GDEF) and tuple scalars
# --------------------------------------------------------------------------------------


def _region_scalar(region: Sequence[tuple[float, float, float]], coords: Sequence[float]) -> float:
    scalar = 1.0
    for axis, (start, peak, end) in enumerate(region):
        coord = coords[axis] if axis < len(coords) else 0.0
        if peak == 0.0 or start > peak or peak > end or (start < 0.0 < end):
            continue
        if coord == peak:
            continue
        if coord <= start or coord >= end:
            return 0.0
        if coord < peak:
            scalar *= (coord - start) / (peak - start)
        else:
            scalar *= (end - coord) / (end - peak)
    return scalar


class ItemVariationStore:
    """``ItemVariationStore``: deltas by ``(outer, inner)`` at normalised coordinates."""

    def __init__(self, data: bytes, offset: int) -> None:
        self.data = data
        self.offset = offset
        _fmt, regions_at, count = struct.unpack_from(">HIH", data, offset)
        self.subtables = struct.unpack_from(f">{count}I", data, offset + 8)
        at = offset + regions_at
        axes, regions = struct.unpack_from(">HH", data, at)
        self.regions = []
        for r in range(regions):
            region = []
            for a in range(axes):
                start, peak, end = struct.unpack_from(">hhh", data, at + 4 + 6 * (r * axes + a))
                region.append((_f2dot14(start), _f2dot14(peak), _f2dot14(end)))
            self.regions.append(region)
        self._scalars: dict[tuple, list[float]] = {}

    def delta(self, outer: int, inner: int, coords: Sequence[float]) -> float:
        if outer >= len(self.subtables) or not any(coords):
            return 0.0
        key = tuple(coords)
        at = self.offset + self.subtables[outer]
        items, word_count, region_count = struct.unpack_from(">HHH", self.data, at)
        if inner >= items:
            return 0.0
        indices = struct.unpack_from(f">{region_count}H", self.data, at + 6)
        scalars_key = (outer,) + key
        scalars = self._scalars.get(scalars_key)
        if scalars is None:
            scalars = [_region_scalar(self.regions[i], coords) for i in indices]
            self._scalars[scalars_key] = scalars
        long_words = bool(word_count & 0x8000)
        words = word_count & 0x7FFF
        size_word, size_short = (4, 2) if long_words else (2, 1)
        row = words * size_word + (region_count - words) * size_short
        base = at + 6 + 2 * region_count + inner * row
        total = 0.0
        pos = base
        for k in range(region_count):
            if k < words:
                value = struct.unpack_from(">i" if long_words else ">h", self.data, pos)[0]
                pos += size_word
            else:
                value = struct.unpack_from(">h" if long_words else ">b", self.data, pos)[0]
                pos += size_short
            if value and scalars[k]:
                total += value * scalars[k]
        return total


def _delta_set_index(data: bytes, offset: int, index: int) -> tuple[int, int]:
    fmt, entry_format = struct.unpack_from(">BB", data, offset)
    if fmt == 0:
        count = struct.unpack_from(">H", data, offset + 2)[0]
        at = offset + 4
    else:
        count = struct.unpack_from(">I", data, offset + 2)[0]
        at = offset + 6
    if count == 0:
        return 0, index
    index = min(index, count - 1)
    size = ((entry_format >> 4) & 3) + 1
    inner_bits = (entry_format & 0xF) + 1
    raw = int.from_bytes(data[at + index * size:at + (index + 1) * size], "big")
    return raw >> inner_bits, raw & ((1 << inner_bits) - 1)


# --------------------------------------------------------------------------------------
# gvar
# --------------------------------------------------------------------------------------


def _read_points(data: bytes, pos: int) -> tuple[list[int] | None, int]:
    """Packed point numbers: ``None`` for "all points"."""
    count = data[pos]
    pos += 1
    if count & 0x80:
        count = ((count & 0x7F) << 8) | data[pos]
        pos += 1
    if count == 0:
        return None, pos
    points: list[int] = []
    last = 0
    while len(points) < count:
        control = data[pos]
        pos += 1
        run = (control & 0x7F) + 1
        words = control & 0x80
        for _ in range(run):
            if words:
                value = struct.unpack_from(">H", data, pos)[0]
                pos += 2
            else:
                value = data[pos]
                pos += 1
            last += value
            points.append(last)
            if len(points) >= count:
                break
    return points, pos


def _read_deltas(data: bytes, pos: int, count: int) -> tuple[list[int], int]:
    out: list[int] = []
    while len(out) < count:
        control = data[pos]
        pos += 1
        run = (control & 0x3F) + 1
        if control & 0x80:
            out.extend([0] * run)
        elif control & 0x40:
            out.extend(struct.unpack_from(f">{run}h", data, pos))
            pos += 2 * run
        else:
            out.extend(struct.unpack_from(f">{run}b", data, pos))
            pos += run
    return out[:count], pos


def _iup(deltas: list[float], coords: list[float], touched: list[bool], ends: Sequence[int]) -> None:
    """Interpolate untouched points' deltas within each contour (one axis)."""
    start = 0
    for end in ends:
        indices = [i for i in range(start, end + 1) if touched[i]]
        if indices and len(indices) < end - start + 1:
            for n, i in enumerate(indices):
                j = indices[(n + 1) % len(indices)]
                k = i + 1
                while True:
                    if k > end:
                        k = start
                    if k == j:
                        break
                    c1, c2 = coords[i], coords[j]
                    d1, d2 = deltas[i], deltas[j]
                    c = coords[k]
                    if c1 == c2:
                        deltas[k] = d1 if d1 == d2 else 0.0
                    else:
                        lo, hi, dlo, dhi = (c1, c2, d1, d2) if c1 < c2 else (c2, c1, d2, d1)
                        if c <= lo:
                            deltas[k] = dlo
                        elif c >= hi:
                            deltas[k] = dhi
                        else:
                            deltas[k] = dlo + (c - lo) * (dhi - dlo) / (hi - lo)
                    k += 1
        start = end + 1


# --------------------------------------------------------------------------------------
# CFF
# --------------------------------------------------------------------------------------


def _index(data: bytes, pos: int) -> tuple[list[tuple[int, int]], int]:
    """A CFF INDEX: ``[(start, end)]`` into ``data`` and where it ends."""
    count = struct.unpack_from(">H", data, pos)[0]
    if count == 0:
        return [], pos + 2
    size = data[pos + 2]
    offsets = [int.from_bytes(data[pos + 3 + i * size:pos + 3 + (i + 1) * size], "big") for i in range(count + 1)]
    base = pos + 3 + (count + 1) * size - 1
    return [(base + offsets[i], base + offsets[i + 1]) for i in range(count)], base + offsets[-1]


def _dict(data: bytes, start: int, end: int) -> dict[int, list[float]]:
    out: dict[int, list[float]] = {}
    operands: list[float] = []
    pos = start
    while pos < end:
        b0 = data[pos]
        if b0 <= 21:
            pos += 1
            op = b0
            if b0 == 12:
                op = 1200 + data[pos]
                pos += 1
            out[op] = operands
            operands = []
        elif b0 == 28:
            operands.append(struct.unpack_from(">h", data, pos + 1)[0])
            pos += 3
        elif b0 == 29:
            operands.append(struct.unpack_from(">i", data, pos + 1)[0])
            pos += 5
        elif b0 == 30:
            text = ""
            pos += 1
            done = False
            while not done:
                byte = data[pos]
                pos += 1
                for nibble in (byte >> 4, byte & 0xF):
                    if nibble == 0xF:
                        done = True
                        break
                    text += "0123456789.EE?-"[nibble] + ("-" if nibble == 0xC else "")
            try:
                operands.append(float(text.replace("E-", "e-").replace("E", "e")))
            except ValueError:
                operands.append(0.0)
        elif 32 <= b0 <= 246:
            operands.append(b0 - 139)
            pos += 1
        elif 247 <= b0 <= 250:
            operands.append((b0 - 247) * 256 + data[pos + 1] + 108)
            pos += 2
        elif 251 <= b0 <= 254:
            operands.append(-(b0 - 251) * 256 - data[pos + 1] - 108)
            pos += 2
        else:
            pos += 1
    return out


def _bias(count: int) -> int:
    return 107 if count < 1240 else 1131 if count < 33900 else 32768


class _Cff:
    def __init__(self, data: bytes) -> None:
        self.data = data
        header_size = data[2]
        _names, pos = _index(data, header_size)
        tops, pos = _index(data, pos)
        _strings, pos = _index(data, pos)
        self.gsubrs, _ = _index(data, pos)
        top = _dict(data, *tops[0])
        self.charstrings, _ = _index(data, int(top[17][0]))
        self.fd_select: list[int] | None = None
        self.privates: list[tuple[list[tuple[int, int]], int, int]] = []  # (subrs, default, nominal)
        if 1230 in top:  # ROS: CID-keyed
            fds, _ = _index(data, int(top[1236][0]))
            for start, end in fds:
                self.privates.append(self._private(_dict(data, start, end)))
            self.fd_select = self._read_fd_select(int(top[1237][0]), len(self.charstrings))
        else:
            self.privates.append(self._private(top))

    def _private(self, top: dict) -> tuple[list[tuple[int, int]], int, int]:
        if 18 not in top:
            return [], 0, 0
        size, offset = int(top[18][0]), int(top[18][1])
        private = _dict(self.data, offset, offset + size)
        subrs: list[tuple[int, int]] = []
        if 19 in private:
            subrs, _ = _index(self.data, offset + int(private[19][0]))
        return subrs, 0, 0

    def _read_fd_select(self, at: int, glyphs: int) -> list[int]:
        fmt = self.data[at]
        if fmt == 0:
            return list(self.data[at + 1:at + 1 + glyphs])
        out = [0] * glyphs
        if fmt == 3:
            count = struct.unpack_from(">H", self.data, at + 1)[0]
            for i in range(count):
                first, fd = struct.unpack_from(">HB", self.data, at + 3 + 3 * i)
                last = struct.unpack_from(">H", self.data, at + 3 + 3 * (i + 1))[0]
                for g in range(first, min(last, glyphs)):
                    out[g] = fd
        return out

    def outline(self, gid: int) -> list[Command]:
        if gid >= len(self.charstrings):
            return []
        fd = self.fd_select[gid] if self.fd_select is not None and gid < len(self.fd_select) else 0
        subrs = self.privates[fd][0] if fd < len(self.privates) else []
        return _Type2(self.data, self.gsubrs, subrs).run(*self.charstrings[gid])


class _Type2:
    """A Type 2 charstring interpreter drawing to commands (no hints)."""

    def __init__(self, data: bytes, gsubrs, subrs) -> None:
        self.data = data
        self.gsubrs, self.subrs = gsubrs, subrs
        self.gbias, self.bias = _bias(len(gsubrs)), _bias(len(subrs))
        self.stack: list[float] = []
        self.stems = 0
        self.x = self.y = 0.0
        self.out: list[Command] = []
        self.open = False
        self.width_parsed = False
        self.done = False

    def _move(self, dx: float, dy: float) -> None:
        if self.open:
            self.out.append(("Z",))
        self.x += dx
        self.y += dy
        self.out.append(("M", self.x, self.y))
        self.open = True

    def _line(self, dx: float, dy: float) -> None:
        self.x += dx
        self.y += dy
        self.out.append(("L", self.x, self.y))

    def _curve(self, a: float, b: float, c: float, d: float, e: float, f: float) -> None:
        x1, y1 = self.x + a, self.y + b
        x2, y2 = x1 + c, y1 + d
        self.x, self.y = x2 + e, y2 + f
        self.out.append(("C", x1, y1, x2, y2, self.x, self.y))

    def run(self, start: int, end: int) -> list[Command]:
        self._exec(start, end, 0)
        if self.open:
            self.out.append(("Z",))
        return self.out

    def _width(self, expected: "tuple[int, ...] | int") -> None:
        """Drop the advance width the first stack-clearing operator may carry ahead of
        its operands: there when the operand count is not one the operator takes
        (``expected``: a count, or 2 for "an even number")."""
        if self.width_parsed:
            return
        self.width_parsed = True
        count = len(self.stack)
        if isinstance(expected, tuple):
            extra = count not in expected
        else:
            extra = count % 2 == 1
        if extra and self.stack:
            self.stack.pop(0)

    def _exec(self, pos: int, end: int, depth: int) -> None:
        data = self.data
        st = self.stack
        while pos < end and not self.done:
            b0 = data[pos]
            pos += 1
            if b0 >= 32 or b0 == 28:
                if b0 == 28:
                    st.append(struct.unpack_from(">h", data, pos)[0])
                    pos += 2
                elif b0 <= 246:
                    st.append(b0 - 139)
                elif b0 <= 250:
                    st.append((b0 - 247) * 256 + data[pos] + 108)
                    pos += 1
                elif b0 <= 254:
                    st.append(-(b0 - 251) * 256 - data[pos] - 108)
                    pos += 1
                else:
                    st.append(struct.unpack_from(">i", data, pos)[0] / 65536.0)
                    pos += 4
                continue
            if b0 in (1, 3, 18, 23):  # hstem vstem hstemhm vstemhm
                self._width(2)
                self.stems += len(st) // 2
                st.clear()
            elif b0 in (19, 20):  # hintmask cntrmask
                self._width(2)
                self.stems += len(st) // 2
                st.clear()
                pos += (self.stems + 7) // 8
            elif b0 == 21:  # rmoveto
                self._width((2,))
                self._move(st[-2], st[-1])
                st.clear()
            elif b0 == 22:  # hmoveto
                self._width((1,))
                self._move(st[-1], 0)
                st.clear()
            elif b0 == 4:  # vmoveto
                self._width((1,))
                self._move(0, st[-1])
                st.clear()
            elif b0 == 5:  # rlineto
                for i in range(0, len(st) - 1, 2):
                    self._line(st[i], st[i + 1])
                st.clear()
            elif b0 in (6, 7):  # hlineto vlineto
                horizontal = b0 == 6
                for value in st:
                    self._line(value, 0) if horizontal else self._line(0, value)
                    horizontal = not horizontal
                st.clear()
            elif b0 == 8:  # rrcurveto
                for i in range(0, len(st) - 5, 6):
                    self._curve(*st[i:i + 6])
                st.clear()
            elif b0 == 24:  # rcurveline
                i = 0
                while i + 6 <= len(st) - 2:
                    self._curve(*st[i:i + 6])
                    i += 6
                self._line(st[i], st[i + 1])
                st.clear()
            elif b0 == 25:  # rlinecurve
                i = 0
                while i + 2 <= len(st) - 6:
                    self._line(st[i], st[i + 1])
                    i += 2
                self._curve(*st[i:i + 6])
                st.clear()
            elif b0 in (26, 27):  # vvcurveto hhcurveto
                i = 0
                first = 0.0
                if len(st) % 4 == 1:
                    first = st[0]
                    i = 1
                while i + 4 <= len(st):
                    a, b, c, d = st[i:i + 4]
                    if b0 == 26:
                        self._curve(first, a, b, c, 0, d)
                    else:
                        self._curve(a, first, b, c, d, 0)
                    first = 0.0
                    i += 4
                st.clear()
            elif b0 in (30, 31):  # vhcurveto hvcurveto
                horizontal = b0 == 31
                i = 0
                while i + 4 <= len(st):
                    last = st[i + 4] if len(st) - i == 5 else 0.0
                    a, b, c, d = st[i:i + 4]
                    if horizontal:
                        self._curve(a, 0, b, c, last, d)
                    else:
                        self._curve(0, a, b, c, d, last)
                    horizontal = not horizontal
                    i += 4
                st.clear()
            elif b0 == 10 or b0 == 29:  # callsubr callgsubr
                index = int(st.pop())
                if b0 == 10:
                    index += self.bias
                    table = self.subrs
                else:
                    index += self.gbias
                    table = self.gsubrs
                if 0 <= index < len(table) and depth < 10:
                    start, end_at = table[index]
                    self._exec(start, end_at, depth + 1)
            elif b0 == 11:  # return
                return
            elif b0 == 14:  # endchar
                self._width((0, 4))
                self.done = True
                return
            elif b0 == 12:
                op = data[pos]
                pos += 1
                if op == 35:  # flex
                    self._curve(*st[0:6])
                    self._curve(*st[6:12])
                elif op == 34:  # hflex
                    y0 = self.y
                    self._curve(st[0], 0, st[1], st[2], st[3], 0)
                    self._curve(st[4], 0, st[5], y0 - self.y, st[6], 0)
                elif op == 36:  # hflex1
                    y0 = self.y
                    self._curve(st[0], st[1], st[2], st[3], st[4], 0)
                    self._curve(st[5], 0, st[6], st[7], st[8], y0 - (self.y + st[7]))
                elif op == 37:  # flex1
                    x0, y0 = self.x, self.y
                    dx = st[0] + st[2] + st[4] + st[6] + st[8]
                    dy = st[1] + st[3] + st[5] + st[7] + st[9]
                    self._curve(*st[0:6])
                    if abs(dx) > abs(dy):
                        self._curve(st[6], st[7], st[8], st[9], st[10], y0 - (self.y + st[7] + st[9]))
                    else:
                        self._curve(st[6], st[7], st[8], st[9], x0 - (self.x + st[6] + st[8]), st[10])
                st.clear()
            else:
                st.clear()


# --------------------------------------------------------------------------------------
# The face
# --------------------------------------------------------------------------------------

#: Tables that make a face's glyphs pictures rather than outlines.
_COLOUR_TABLES = (b"COLR", b"sbix", b"CBDT", b"SVG ")


class OutlineFace:
    """A face of a font file (``path``, collection index ``number``)."""

    def __init__(self, data: bytes, number: int = 0, *, source: str = "") -> None:
        self.source = source
        self.number = number
        self.data = data
        offsets = font_offsets(data)
        self.offset = offsets[number]
        self.tables = table_directory(data, self.offset)
        head = self.table(b"head")
        if head is None:
            raise FaceError("no head table")
        self.units_per_em = struct.unpack_from(">H", head, 18)[0] or 1000
        self.index_to_loc = struct.unpack_from(">h", head, 50)[0]
        maxp = self.table(b"maxp")
        self.glyph_count = struct.unpack_from(">H", maxp, 4)[0] if maxp else 0
        self._lock = threading.Lock()
        self._outlines: dict[tuple, list[Command]] = {}
        self._advances_cache: dict[tuple, int] = {}
        self._cff: _Cff | None = None
        self._cmap: tuple[dict[int, int], bool] | None = None

    # -- tables ------------------------------------------------------------------------

    def table(self, tag: bytes) -> bytes | None:
        found = self.tables.get(tag)
        if found is None:
            return None
        offset, length = found
        return self.data[offset:offset + length]

    @functools.cached_property
    def unsupported(self) -> str | None:
        """Why this module does not draw the face's glyphs, or ``None``."""
        for tag in _COLOUR_TABLES:
            if tag in self.tables:
                return f"colour glyphs ({tag.decode().strip()})"
        if b"CFF2" in self.tables and b"glyf" not in self.tables:
            return "CFF2 outlines"
        if b"glyf" not in self.tables and b"CFF " not in self.tables:
            return "no outlines"
        return None

    # -- character map ------------------------------------------------------------------

    def _read_cmap(self) -> tuple[dict[int, int], bool]:
        if self._cmap is None:
            table = self.table(b"cmap")
            mapping: dict[int, int] = {}
            symbol = False
            if table:
                count = struct.unpack_from(">H", table, 2)[0]
                subtables: dict[tuple[int, int], int] = {}
                for i in range(count):
                    platform, encoding, offset = struct.unpack_from(">HHI", table, 4 + 8 * i)
                    subtables.setdefault((platform, encoding), offset)

                def fmt(key: tuple[int, int]) -> int:
                    return struct.unpack_from(">H", table, subtables[key])[0]

                chosen = None
                for key in ((3, 10), (0, 6), (0, 4)):
                    if key in subtables and fmt(key) in (12, 13):
                        chosen = key
                        break
                if chosen is None:
                    for key in ((3, 1), (0, 3), (0, 2), (0, 1), (0, 0), (3, 10), (0, 6), (0, 4)):
                        if key in subtables:
                            chosen = key
                            break
                if chosen is None and (3, 0) in subtables:
                    chosen, symbol = (3, 0), True
                if chosen is None and (1, 0) in subtables:
                    chosen = (1, 0)
                if chosen is not None:
                    try:
                        mapping = _cmap_subtable(table, subtables[chosen])
                    except struct.error:
                        mapping = {}
            self._cmap = (mapping, symbol)
        return self._cmap

    def glyph(self, code: int) -> int:
        """The glyph a character maps to (0 where none)."""
        mapping, symbol = self._read_cmap()
        found = mapping.get(code)
        if found is None and symbol and code <= 0xFF:
            found = mapping.get(0xF000 + code)
        return found or 0

    def has_char(self, code: int) -> bool:
        return self.glyph(code) != 0

    # -- variations -----------------------------------------------------------------------

    @functools.cached_property
    def axes(self) -> list[tuple[bytes, float, float, float]]:
        fvar = self.table(b"fvar")
        if not fvar:
            return []
        axes_at, _, count, size = struct.unpack_from(">HHHH", fvar, 4)
        out = []
        for i in range(count):
            at = axes_at + i * size
            tag = fvar[at:at + 4]
            low, default, high = (v / 65536.0 for v in struct.unpack_from(">iii", fvar, at + 4))
            out.append((tag, low, default, high))
        return out

    @functools.cached_property
    def _avar(self) -> list[list[tuple[float, float]]]:
        avar = self.table(b"avar")
        if not avar:
            return []
        count = struct.unpack_from(">H", avar, 6)[0]
        pos = 8
        out = []
        for _ in range(count):
            pairs = struct.unpack_from(">H", avar, pos)[0]
            pos += 2
            segment = []
            for _ in range(pairs):
                a, b = struct.unpack_from(">hh", avar, pos)
                segment.append((_f2dot14(a), _f2dot14(b)))
                pos += 4
            out.append(segment)
        return out

    def coordinates(self, settings: Iterable[tuple[bytes, float]]) -> tuple[float, ...]:
        """Normalised coordinates for ``(axis tag, user value)`` settings (the last of a
        tag wins); empty for a face without ``fvar``."""
        if not self.axes:
            return ()
        wanted = dict(settings)
        out = []
        for index, (tag, low, default, high) in enumerate(self.axes):
            value = wanted.get(tag, default)
            value = min(max(value, low), high)
            if value < default:
                n = -(default - value) / (default - low) if default != low else 0.0
            elif value > default:
                n = (value - default) / (high - default) if high != default else 0.0
            else:
                n = 0.0
            if index < len(self._avar):
                segment = self._avar[index]
                for k in range(1, len(segment)):
                    (a0, b0), (a1, b1) = segment[k - 1], segment[k]
                    if n <= a1:
                        n = b0 + (b1 - b0) * (n - a0) / (a1 - a0) if a1 != a0 else b0
                        break
            out.append(_round_f2dot14(n))
        return tuple(out) if any(out) else ()

    @functools.cached_property
    def _hvar(self) -> tuple[ItemVariationStore, int] | None:
        hvar = self.table(b"HVAR")
        if not hvar:
            return None
        store_at, advance_map = struct.unpack_from(">II", hvar, 4)
        try:
            return ItemVariationStore(hvar, store_at), advance_map
        except struct.error:
            return None

    @functools.cached_property
    def gdef_store(self) -> ItemVariationStore | None:
        gdef = self.table(b"GDEF")
        if not gdef or len(gdef) < 18:
            return None
        major, minor = struct.unpack_from(">HH", gdef, 0)
        if (major, minor) < (1, 3):
            return None
        at = struct.unpack_from(">I", gdef, 14)[0]
        return ItemVariationStore(gdef, at) if at else None

    # -- advances -----------------------------------------------------------------------

    @functools.cached_property
    def _hmtx(self) -> tuple[int, ...]:
        hhea = self.table(b"hhea")
        hmtx = self.table(b"hmtx")
        if not hhea or not hmtx:
            return (0,)
        count = struct.unpack_from(">H", hhea, 34)[0]
        count = min(count, len(hmtx) // 4) or 1
        return struct.unpack_from(f">{2 * count}H", hmtx, 0)[0::2]

    def advance(self, gid: int, coords: tuple[float, ...] = ()) -> int:
        """The glyph's horizontal advance in font units at ``coords``, rounded as
        harfrust rounds a varied advance."""
        advances = self._hmtx
        base = advances[gid] if gid < len(advances) else advances[-1]
        if not coords:
            return base
        key = (gid, coords)
        found = self._advances_cache.get(key)
        if found is not None:
            return found
        delta = 0.0
        hvar = self._hvar
        if hvar is not None:
            store, advance_map = hvar
            hvar_table = self.table(b"HVAR")
            outer, inner = (_delta_set_index(hvar_table, advance_map, gid) if advance_map  # type: ignore[arg-type]
                            else (0, gid))
            delta = store.delta(outer, inner, coords)
        elif b"gvar" in self.tables and b"glyf" in self.tables:
            phantoms = self._glyf_points(gid, coords)[2]
            delta = (phantoms[1][0] - phantoms[0][0]) - base
        value = int(round(base + delta)) if hvar is None else base + int(round(delta))
        self._advances_cache[key] = value
        return value

    # -- metrics --------------------------------------------------------------------------

    @functools.cached_property
    def metrics(self) -> dict[str, float]:
        """resvg's ``ResolvedFont`` numbers, font units (default instance)."""
        upem = self.units_per_em
        hhea = self.table(b"hhea")
        os2 = self.table(b"OS/2")
        post = self.table(b"post")
        ascent = descent = 0.0
        if hhea:
            ascent, descent = struct.unpack_from(">hh", hhea, 4)
        if os2 and len(os2) >= 78:
            selection = struct.unpack_from(">H", os2, 62)[0]
            typo_ascent, typo_descent = struct.unpack_from(">hh", os2, 68)
            if selection & 0x80 or (ascent == 0 and descent == 0):
                ascent, descent = typo_ascent, typo_descent
            if ascent == 0 and descent == 0:
                win_ascent, win_descent = struct.unpack_from(">HH", os2, 74)
                ascent, descent = win_ascent, -win_descent
        x_height = 0.0
        if os2 and len(os2) >= 88 and struct.unpack_from(">H", os2, 0)[0] >= 2:
            x_height = struct.unpack_from(">h", os2, 86)[0]
        if x_height <= 0:
            x_height = round((ascent - descent) * 0.45)
        strike = None
        if os2 and len(os2) >= 30:
            size, position = struct.unpack_from(">hh", os2, 26)
            strike = position
        line_through = strike if strike is not None else x_height // 2
        if post and len(post) >= 12:
            position, thickness = struct.unpack_from(">hh", post, 8)
            if thickness <= 0:
                thickness = upem // 12
        else:
            position, thickness = -(upem // 9), upem // 12
        sub, sup = round(upem / 0.2), round(upem / 0.4)
        if os2 and len(os2) >= 26:
            sub = struct.unpack_from(">h", os2, 16)[0]
            sup = struct.unpack_from(">h", os2, 24)[0]
        return {"ascent": ascent, "descent": descent, "x_height": x_height,
                "underline_position": position, "underline_thickness": thickness,
                "line_through_position": line_through, "subscript_offset": sub,
                "superscript_offset": sup}

    # -- legacy kern ----------------------------------------------------------------------

    @functools.cached_property
    def legacy_kern(self) -> dict[tuple[int, int], int]:
        table = self.table(b"kern")
        return read_legacy_kern(table) if table else {}

    # -- outlines -------------------------------------------------------------------------

    def outline(self, gid: int, coords: tuple[float, ...] = ()) -> list[Command]:
        """The glyph's outline in font units (y up), at ``coords``."""
        key = (gid, coords)
        found = self._outlines.get(key)
        if found is not None:
            return found
        if b"glyf" in self.tables:
            points, ends, phantoms = self._glyf_points(gid, coords)
            # The outline moved so that its first phantom point (x minimum less the left
            # side bearing) is the origin, as skrifa and FreeType place it: a face whose
            # glyphs' left side bearing is not their x minimum (Word's Symbol) draws at
            # the bearing.
            shift = phantoms[0][0]
            if shift:
                points = [[p[0] - shift, p[1], p[2]] for p in points]
            commands = _quadratic_path(points, ends)
        elif b"CFF " in self.tables:
            with self._lock:
                if self._cff is None:
                    self._cff = _Cff(self.table(b"CFF ") or b"")
            commands = self._cff.outline(gid)
        else:
            commands = []
        self._outlines[key] = commands
        return commands

    def glyph_data(self, gid: int, coords: tuple[float, ...] = ()) -> str:
        """The glyph's path data in font units, y down (``""`` for a glyph with no
        outline), kept with the face."""
        cache = self.__dict__.setdefault("_definitions", {})
        key = (gid, coords)
        found = cache.get(key)
        if found is None:
            commands = self.outline(gid, coords)
            found = cache[key] = path_data(commands, 1.0, 1.0) if commands else ""
        return found

    def definition(self, gid: int, coords: tuple[float, ...], ident: str) -> str:
        """``<path id=ident d=...>`` of the glyph in font units, y down (``""`` for a
        glyph with no outline)."""
        found = self.glyph_data(gid, coords)
        return f'<path id="{ident}" d="{found}"/>' if found else ""

    def _loca(self, gid: int) -> tuple[int, int]:
        loca = self.tables.get(b"loca")
        if loca is None or gid + 1 >= self.glyph_count + 1:
            return 0, 0
        at = loca[0]
        if self.index_to_loc == 0:
            a, b = struct.unpack_from(">HH", self.data, at + 2 * gid)
            return 2 * a, 2 * b
        return struct.unpack_from(">II", self.data, at + 4 * gid)

    def _glyf_points(self, gid: int, coords: tuple[float, ...], depth: int = 0):
        """``(points [(x, y, on_curve)], contour ends, phantom points)`` of a glyf glyph,
        components placed, at ``coords``."""
        glyf_at = self.tables[b"glyf"][0]
        start, end = self._loca(gid) if gid < self.glyph_count else (0, 0)
        advances = self._hmtx
        advance = advances[gid] if gid < len(advances) else advances[-1]
        lsb = self._lsb(gid)
        data = self.data
        points: list[list] = []
        ends: list[int] = []
        components: list[tuple] = []
        x_min = 0
        if end > start:
            at = glyf_at + start
            contours, x_min = struct.unpack_from(">hh", data, at)
            if contours >= 0:
                ends = list(struct.unpack_from(f">{contours}H", data, at + 10))
                count = ends[-1] + 1 if ends else 0
                pos = at + 10 + 2 * contours
                instructions = struct.unpack_from(">H", data, pos)[0]
                pos += 2 + instructions
                flags: list[int] = []
                while len(flags) < count:
                    flag = data[pos]
                    pos += 1
                    flags.append(flag)
                    if flag & 8:
                        repeat = data[pos]
                        pos += 1
                        flags.extend([flag] * repeat)
                flags = flags[:count]
                xs = []
                value = 0
                for flag in flags:
                    if flag & 2:
                        d = data[pos]
                        pos += 1
                        value += d if flag & 16 else -d
                    elif not flag & 16:
                        value += struct.unpack_from(">h", data, pos)[0]
                        pos += 2
                    xs.append(value)
                ys = []
                value = 0
                for flag in flags:
                    if flag & 4:
                        d = data[pos]
                        pos += 1
                        value += d if flag & 32 else -d
                    elif not flag & 32:
                        value += struct.unpack_from(">h", data, pos)[0]
                        pos += 2
                    ys.append(value)
                points = [[float(x), float(y), bool(f & 1)] for x, y, f in zip(xs, ys, flags)]
            else:
                pos = at + 10
                more = True
                while more:
                    cflags, glyph = struct.unpack_from(">HH", data, pos)
                    pos += 4
                    if cflags & 1:
                        a, b = struct.unpack_from(">hh" if cflags & 2 else ">HH", data, pos)
                        pos += 4
                    else:
                        a, b = struct.unpack_from(">bb" if cflags & 2 else ">BB", data, pos)
                        pos += 2
                    matrix = (1.0, 0.0, 0.0, 1.0)
                    if cflags & 8:
                        s = _f2dot14(struct.unpack_from(">h", data, pos)[0])
                        pos += 2
                        matrix = (s, 0.0, 0.0, s)
                    elif cflags & 0x40:
                        sx, sy = struct.unpack_from(">hh", data, pos)
                        pos += 4
                        matrix = (_f2dot14(sx), 0.0, 0.0, _f2dot14(sy))
                    elif cflags & 0x80:
                        m = struct.unpack_from(">hhhh", data, pos)
                        pos += 8
                        matrix = tuple(_f2dot14(v) for v in m)  # type: ignore[assignment]
                    components.append((glyph, cflags, float(a), float(b), matrix))
                    more = bool(cflags & 0x20)
        phantoms = [[float(x_min - lsb), 0.0], [float(x_min - lsb + advance), 0.0], [0.0, 0.0], [0.0, 0.0]]
        if coords and b"gvar" in self.tables:
            if components:
                fake = [[c[2], c[3], True] for c in components]
                self._apply_gvar(gid, coords, fake, [len(fake) - 1] if fake else [], phantoms, composite=True)
                components = [(c[0], c[1], p[0], p[1], c[4]) for c, p in zip(components, fake)]
            else:
                self._apply_gvar(gid, coords, points, ends, phantoms, composite=False)
        if components and depth < 8:
            for glyph, component_flags, a, b, matrix in components:
                sub_points, sub_ends, _ = self._glyf_points(glyph, coords, depth + 1)
                xx, xy, yx, yy = matrix
                placed = [[xx * p[0] + yx * p[1], xy * p[0] + yy * p[1], p[2]] for p in sub_points]
                if component_flags & 2:
                    dx, dy = a, b
                    if component_flags & 0x800:  # SCALED_COMPONENT_OFFSET
                        dx, dy = xx * a + yx * b, xy * a + yy * b
                else:
                    pa, pb = int(a), int(b)
                    if 0 <= pa < len(points) and 0 <= pb < len(placed):
                        dx, dy = points[pa][0] - placed[pb][0], points[pa][1] - placed[pb][1]
                    else:
                        dx = dy = 0.0
                base = len(points)
                points.extend([[p[0] + dx, p[1] + dy, p[2]] for p in placed])
                ends.extend(base + e for e in sub_ends)
        return points, ends, phantoms

    def _lsb(self, gid: int) -> int:
        hmtx = self.table(b"hmtx")
        count = len(self._hmtx)
        if not hmtx:
            return 0
        if gid < count:
            return struct.unpack_from(">h", hmtx, 4 * gid + 2)[0]
        at = 4 * count + 2 * (gid - count)
        return struct.unpack_from(">h", hmtx, at)[0] if at + 2 <= len(hmtx) else 0

    @functools.cached_property
    def _gvar(self):
        gvar = self.table(b"gvar")
        if not gvar:
            return None
        _, _, axis_count, shared_count, shared_at, glyph_count, flags, data_at = struct.unpack_from(">HHHHIHHI", gvar, 0)
        shared = [tuple(_f2dot14(v) for v in struct.unpack_from(f">{axis_count}h", gvar, shared_at + 2 * axis_count * i))
                  for i in range(shared_count)]
        if flags & 1:
            offsets = struct.unpack_from(f">{glyph_count + 1}I", gvar, 20)
        else:
            offsets = tuple(2 * v for v in struct.unpack_from(f">{glyph_count + 1}H", gvar, 20))
        return gvar, axis_count, shared, offsets, data_at

    def _apply_gvar(self, gid: int, coords: tuple[float, ...], points: list, ends: list[int],
                    phantoms: list, *, composite: bool) -> None:
        info = self._gvar
        if info is None:
            return
        gvar, axis_count, shared, offsets, data_at = info
        if gid + 1 >= len(offsets):
            return
        start, end = data_at + offsets[gid], data_at + offsets[gid + 1]
        if end <= start:
            return
        all_points = points + [[p[0], p[1], True] for p in phantoms]
        total = len(all_points)
        count_field, data_offset = struct.unpack_from(">HH", gvar, start)
        tuples = count_field & 0x0FFF
        pos = start + 4
        serialized = start + data_offset
        shared_points: list[int] | None = None
        if count_field & 0x8000:
            shared_points, serialized = _read_points(gvar, serialized)
        dx = [0.0] * total
        dy = [0.0] * total
        xs = [p[0] for p in all_points]
        ys = [p[1] for p in all_points]
        for _ in range(tuples):
            size, index = struct.unpack_from(">HH", gvar, pos)
            pos += 4
            if index & 0x8000:
                peak = tuple(_f2dot14(v) for v in struct.unpack_from(f">{axis_count}h", gvar, pos))
                pos += 2 * axis_count
            else:
                peak = shared[index & 0x0FFF]
            if index & 0x4000:
                inter_start = tuple(_f2dot14(v) for v in struct.unpack_from(f">{axis_count}h", gvar, pos))
                inter_end = tuple(_f2dot14(v) for v in struct.unpack_from(f">{axis_count}h", gvar, pos + 2 * axis_count))
                pos += 4 * axis_count
                region = list(zip(inter_start, peak, inter_end))
            else:
                region = [(min(p, 0.0), p, max(p, 0.0)) for p in peak]
            scalar = _region_scalar(region, coords)
            here = serialized
            serialized += size
            if scalar == 0.0:
                continue
            numbers = shared_points
            if index & 0x2000:
                numbers, here = _read_points(gvar, here)
            count = total if numbers is None else len(numbers)
            ddx, here = _read_deltas(gvar, here, count)
            ddy, here = _read_deltas(gvar, here, count)
            if numbers is None:
                for i in range(total):
                    dx[i] += ddx[i] * scalar
                    dy[i] += ddy[i] * scalar
                continue
            tx = [0.0] * total
            ty = [0.0] * total
            touched = [False] * total
            for k, n in enumerate(numbers):
                if n < total:
                    tx[n] += ddx[k]
                    ty[n] += ddy[k]
                    touched[n] = True
            if not composite and ends:
                _iup(tx, xs, touched, ends)
                _iup(ty, ys, touched, ends)
            for i in range(total):
                dx[i] += tx[i] * scalar
                dy[i] += ty[i] * scalar
        # Each point's summed delta rounded to a whole font unit, as skrifa (and FreeType)
        # apply them: measured, the rounded outline is resvg's pixel for pixel.
        for i, p in enumerate(points):
            p[0] += round(dx[i])
            p[1] += round(dy[i])
        for k in range(4):
            i = len(points) + k
            phantoms[k][0] += round(dx[i])
            phantoms[k][1] += round(dy[i])


def _quadratic_path(points: list, ends: Sequence[int]) -> list[Command]:
    """TrueType contours as move/line/quad commands, the implied on-curve points between
    two off-curve ones made explicit, as skrifa draws them."""
    out: list[Command] = []
    start = 0
    for end in ends:
        contour = points[start:end + 1]
        start = end + 1
        if not contour:
            continue
        n = len(contour)
        first = next((i for i, p in enumerate(contour) if p[2]), None)
        if first is None:
            # Every point off the curve: start at the midpoint of the last and first.
            a, b = contour[-1], contour[0]
            origin = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            order = contour
        else:
            origin = (contour[first][0], contour[first][1])
            order = contour[first + 1:] + contour[:first + 1]
        out.append(("M", origin[0], origin[1]))
        pending = None
        for p in order:
            if p[2]:
                if pending is None:
                    out.append(("L", p[0], p[1]))
                else:
                    out.append(("Q", pending[0], pending[1], p[0], p[1]))
                    pending = None
            else:
                if pending is not None:
                    mid = ((pending[0] + p[0]) / 2, (pending[1] + p[1]) / 2)
                    out.append(("Q", pending[0], pending[1], mid[0], mid[1]))
                pending = (p[0], p[1])
        if pending is not None:
            out.append(("Q", pending[0], pending[1], origin[0], origin[1]))
        if n:
            out.append(("Z",))
    return out


#: Decimals of a path coordinate, in the SVG's user units.
DIGITS = 3


def _fmt(value: float) -> str:
    text = f"{value:.{DIGITS}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def path_data(commands: Sequence[Command], scale_x: float, scale_y: float, dx: float = 0.0, dy: float = 0.0,
              digits: int = DIGITS) -> str:
    """SVG path data for ``commands``: each point ``(x, y)`` drawn at
    ``(dx + x * scale_x, dy - y * scale_y)`` (font units are y up).  Written short and
    exact: every point rounded to ``digits`` decimals first, so that no rounding
    accumulates along a contour; relative commands, ``h``/``v`` for axis-aligned lines;
    ``t`` for a quadratic and ``s`` for a cubic whose first control point is the last
    one's reflection (TrueType's implied on-curve points make every run of off-curve
    points one), where it is so in the rounded numbers; a command letter written once
    for a run of the same command, a line straight after a move not at all; a separator
    only where two numbers would run together."""
    step = 10 ** digits
    parts: list[str] = []
    cx = cy = 0          # the current point, in units of 10 ** -digits
    sx = sy = 0          # the subpath's start
    last = ""
    # The last curve's kind (``"q"`` or ``"c"``) and its last control point, for t and s.
    curve = ""
    kx = ky = 0

    def fixed(x: float, y: float) -> tuple[int, int]:
        return round((dx + x * scale_x) * step), round((dy - y * scale_y) * step)

    def number(value: int) -> str:
        if value % step == 0:
            return str(value // step)
        sign = "-" if value < 0 else ""
        whole, frac = divmod(abs(value), step)
        text = f"{frac:0{digits}d}".rstrip("0")
        return f"{sign}{whole}.{text}" if whole else f"{sign}.{text}"

    previous = ""         # the last number written, "" after a command letter

    def emit(op: str, values: Sequence[int]) -> None:
        nonlocal last, previous
        text = ""
        # After a relative move, further pairs are relative lines (SVG 1.1, 8.3.2).
        if op != last and not (op == "l" and last == "m"):
            text, previous = op, ""
        for value in values:
            item = number(value)
            # A separator only where the number would otherwise run into the last one.
            if previous and not (item[0] == "-" or (item[0] == "." and "." in previous)):
                text += " "
            text += item
            previous = item
        parts.append(text)
        last = op

    for command in commands:
        op = command[0]
        if op == "Z":
            parts.append("z")
            last, previous, curve = "z", "", ""
            cx, cy = sx, sy
            continue
        points = [fixed(command[i], command[i + 1]) for i in range(1, len(command), 2)]
        if op == "M":
            x, y = points[0]
            last = ""
            # The first move absolute: path data is joined glyph after glyph.
            emit("M", (x, y)) if not parts else emit("m", (x - cx, y - cy))
            cx, cy = sx, sy = x, y
            curve = ""
        elif op == "L":
            x, y = points[0]
            if y == cy:
                emit("h", (x - cx,))
            elif x == cx:
                emit("v", (y - cy,))
            else:
                emit("l", (x - cx, y - cy))
            cx, cy = x, y
            curve = ""
        elif op == "Q":
            (qx, qy), (x, y) = points
            if curve == "q" and qx == 2 * cx - kx and qy == 2 * cy - ky:
                emit("t", (x - cx, y - cy))
            else:
                emit("q", (qx - cx, qy - cy, x - cx, y - cy))
            curve, kx, ky = "q", qx, qy
            cx, cy = x, y
        else:
            (ax, ay), (bx, by), (x, y) = points
            if curve == "c" and ax == 2 * cx - kx and ay == 2 * cy - ky:
                emit("s", (bx - cx, by - cy, x - cx, y - cy))
            else:
                emit("c", (ax - cx, ay - cy, bx - cx, by - cy, x - cx, y - cy))
            curve, kx, ky = "c", bx, by
            cx, cy = x, y
    return "".join(parts)


_FACES: dict[tuple[str, int, int, int], OutlineFace | None] = {}
_FACES_LOCK = threading.Lock()


def load_face(path: str, number: int, stamp: tuple[int, int] = (0, 0)) -> OutlineFace | None:
    """The face ``number`` of the file at ``path``, read once per process per file
    version (``stamp``: modification time and size); ``None`` where it cannot be read."""
    key = (path, number, stamp[0], stamp[1])
    with _FACES_LOCK:
        if key in _FACES:
            return _FACES[key]
    try:
        with open(path, "rb") as handle:
            data = handle.read()
        face: OutlineFace | None = OutlineFace(data, number, source=path)
    except (OSError, struct.error, FaceError, IndexError, ValueError):
        face = None
    with _FACES_LOCK:
        _FACES[key] = face
    return face
