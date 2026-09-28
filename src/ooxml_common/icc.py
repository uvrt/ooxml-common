"""ICC colour profiles: an RGB matrix/TRC profile read, and its colours converted to sRGB.

A picture can say what its samples mean.  PowerPoint honours it: measured by pptx2svg's
``tools/make_exposed_probe.py``, a PNG carrying an ``iCCP`` chunk and a JPEG carrying an
``APP2`` profile -- two synthetic matrix/TRC profiles, Adobe RGB's primaries at gamma
563/256 and Display P3's at 1.8 -- came out of PowerPoint's PDF export **converted to
sRGB** and tagged sRGB, every flat patch within a level of what the arithmetic below
gives, but one: the Adobe profile's near-black 12, which PowerPoint (16.x on macOS) wrote
as 10 where this, and little CMS, give 4 -- a single reading, consistent with a slope
limit of 1/16 on the source curve near black, and not modelled.  (A picture PowerPoint
passes through instead, as it did ``real-college-template``'s photograph, keeps its profile
in the PDF and the reader converts it: that is little CMS's arithmetic, which this is.)  An SVG renderer that
reads the samples as sRGB -- resvg does -- draws the untransformed colours: on
``real-college-template``'s Adobe RGB photograph, a mean of 4 levels and a maximum of 39
off.

A full colour-management system is not something a standard-library package can carry,
and it does not need one for the profiles pictures actually hold: Adobe RGB, Display P3,
ProPhoto, a camera's or a display's are **matrix/TRC** profiles -- three tone curves and a
3 x 3 matrix to the D50 connection space -- and for those the conversion is exact
arithmetic, which is what this module does:

    sRGB = encode( clip( S⁻¹ · P · decode(rgb) ) )

``P`` is the profile's colorants (``rXYZ``, ``gXYZ``, ``bXYZ``, already adapted to D50 as
the ICC specification requires), ``decode`` its three curves (``curv``: identity, a gamma
or a table; ``para``: the five parametric forms), ``S`` sRGB's colorants as the IEC
61966-2.1 profile states them, and ``encode`` sRGB's curve; out-of-gamut colours are
clipped, which is relative colorimetric without black-point compensation -- little CMS's
default and what the probe's samples say PowerPoint used.  Against little CMS on
``real-college-template``'s photograph: mean difference 0.03 of a level, at most 1.

A profile that is **not** matrix/TRC -- one whose conversion is a lookup table
(``A2B0``/``A2B1``), a grey or CMYK one -- is refused (:func:`parse` returns ``None``) rather
than approximated: its matrix, where it carries one at all, is not what a CMS would use.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Callable, Sequence

#: sRGB's colorants, adapted to D50, as the IEC 61966-2.1 profile states them (and as
#: little CMS builds its own sRGB profile, to the s15Fixed16 they are stored in).
SRGB_COLORANTS = (
    (0.4360747, 0.3850649, 0.1430804),
    (0.2225045, 0.7168786, 0.0606169),
    (0.0139322, 0.0971045, 0.7141733),
)

#: Tags whose presence makes a profile's conversion a lookup table rather than its matrix.
_LUT_TAGS = (b"A2B0", b"A2B1", b"A2B2")


@dataclass(frozen=True)
class RGBProfile:
    """A matrix/TRC RGB profile: ``matrix`` maps linear RGB to D50 XYZ (rows X, Y, Z),
    ``curves`` decode each channel's 0..1 value to linear light."""

    description: str
    matrix: tuple[tuple[float, float, float], ...]
    curves: tuple[Callable[[float], float], Callable[[float], float], Callable[[float], float]]


def _tags(data: bytes) -> dict[bytes, bytes]:
    if len(data) < 132:
        return {}
    (count,) = struct.unpack_from(">I", data, 128)
    tags = {}
    for index in range(min(count, 1000)):
        offset = 132 + 12 * index
        if offset + 12 > len(data):
            break
        signature, start, size = struct.unpack_from(">4sII", data, offset)
        if start + size <= len(data):
            tags[signature] = data[start:start + size]
    return tags


def _s15(data: bytes, offset: int) -> float:
    return struct.unpack_from(">i", data, offset)[0] / 65536.0


def _xyz(tag: bytes | None) -> tuple[float, float, float] | None:
    if tag is None or len(tag) < 20 or tag[:4] != b"XYZ ":
        return None
    return (_s15(tag, 8), _s15(tag, 12), _s15(tag, 16))


def _curve(tag: bytes | None) -> Callable[[float], float] | None:
    if tag is None or len(tag) < 12:
        return None
    kind = tag[:4]
    if kind == b"curv":
        (count,) = struct.unpack_from(">I", tag, 8)
        if count == 0:
            return lambda value: value
        if count == 1:
            gamma = struct.unpack_from(">H", tag, 12)[0] / 256.0
            return lambda value: value ** gamma if value > 0 else 0.0
        if len(tag) < 12 + 2 * count:
            return None
        table = [value / 65535.0 for value in struct.unpack_from(f">{count}H", tag, 12)]
        last = count - 1

        def tabulated(value: float) -> float:
            position = min(max(value, 0.0), 1.0) * last
            below = int(position)
            if below >= last:
                return table[last]
            fraction = position - below
            return table[below] + (table[below + 1] - table[below]) * fraction

        return tabulated
    if kind == b"para":
        (function,) = struct.unpack_from(">H", tag, 8)
        counts = {0: 1, 1: 3, 2: 4, 3: 5, 4: 7}
        if function not in counts or len(tag) < 12 + 4 * counts[function]:
            return None
        g, a, b, c, d, e, f = ([_s15(tag, 12 + 4 * i) for i in range(counts[function])] + [0.0] * 7)[:7]
        if function == 0:
            return lambda x: x ** g if x > 0 else 0.0
        if function == 1:
            return lambda x: (a * x + b) ** g if x >= -b / a and a * x + b > 0 else 0.0
        if function == 2:
            return lambda x: (a * x + b) ** g + c if x >= -b / a and a * x + b > 0 else c
        if function == 3:
            return lambda x: (a * x + b) ** g if x >= d and a * x + b > 0 else c * x
        return lambda x: (a * x + b) ** g + e if x >= d and a * x + b > 0 else c * x + f
    return None


def parse(data: bytes | None) -> RGBProfile | None:
    """``data`` as a matrix/TRC RGB profile, or ``None`` when it is not one (or not a
    profile at all): the conversion of anything else is not this module's to guess."""
    if not data or len(data) < 132 or data[36:40] != b"acsp":
        return None
    if data[16:20] != b"RGB " or data[20:24] != b"XYZ ":
        return None
    tags = _tags(data)
    if any(tag in tags for tag in _LUT_TAGS):
        return None
    colorants = [_xyz(tags.get(name)) for name in (b"rXYZ", b"gXYZ", b"bXYZ")]
    curves = [_curve(tags.get(name)) for name in (b"rTRC", b"gTRC", b"bTRC")]
    if any(value is None for value in colorants) or any(value is None for value in curves):
        return None
    matrix = tuple(tuple(colorants[column][row] for column in range(3)) for row in range(3))
    return RGBProfile(_description(tags.get(b"desc")), matrix, tuple(curves))  # type: ignore[arg-type]


def _description(tag: bytes | None) -> str:
    if tag is None or len(tag) < 12:
        return ""
    if tag[:4] == b"desc":
        (count,) = struct.unpack_from(">I", tag, 8)
        return tag[12:12 + count].split(b"\x00", 1)[0].decode("latin-1")
    if tag[:4] == b"mluc" and len(tag) >= 28:
        (records,) = struct.unpack_from(">I", tag, 8)
        if records:
            length, offset = struct.unpack_from(">II", tag, 20)
            return tag[offset:offset + length].decode("utf-16-be", "replace")
    return ""


def srgb_decode(value: float) -> float:
    """sRGB's own curve, 0..1 to linear light."""
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def srgb_encode(value: float) -> float:
    """Linear light to sRGB, 0..1, clipped."""
    if value <= 0.0:
        return 0.0
    if value >= 1.0:
        return 1.0
    return value * 12.92 if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055


def is_srgb(profile: RGBProfile, tolerance: float = 0.5) -> bool:
    """Whether converting through ``profile`` would move no 8-bit colour by ``tolerance``
    of a level or more: its colorants sRGB's to 0.001 and each curve sRGB's to that
    tolerance at every level."""
    for row, expected in zip(profile.matrix, SRGB_COLORANTS):
        if any(abs(value - want) > 0.001 for value, want in zip(row, expected)):
            return False
    for curve in profile.curves:
        for level in range(256):
            if abs(srgb_encode(curve(level / 255)) * 255 - level) >= tolerance:
                return False
    return True


def _invert(matrix: Sequence[Sequence[float]]) -> tuple[tuple[float, float, float], ...]:
    (a, b, c), (d, e, f), (g, h, i) = matrix
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    return (
        ((e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det),
        ((f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det),
        ((d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det),
    )


def _multiply(left, right) -> tuple[tuple[float, float, float], ...]:
    return tuple(
        tuple(sum(left[row][k] * right[k][column] for k in range(3)) for column in range(3))
        for row in range(3)
    )


#: Resolution of the linear-light lookup the encoder uses: a level of error at most a
#: twentieth of an 8-bit step, where sRGB's curve is steepest.
_ENCODE_STEPS = 65535


class ToSRGB:
    """8-bit RGB through ``profile`` to 8-bit sRGB, exactly (see the module docstring).

    ``convert(r, g, b)`` for one colour; :meth:`convert_rows` for packed rows, with a
    cache, since a picture repeats its colours."""

    def __init__(self, profile: RGBProfile) -> None:
        self.matrix = _multiply(_invert(SRGB_COLORANTS), profile.matrix)
        self.decode = [[curve(level / 255.0) for level in range(256)] for curve in profile.curves]
        self._encode = [round(srgb_encode(step / _ENCODE_STEPS) * 255) for step in range(_ENCODE_STEPS + 1)]

    def convert(self, r: int, g: int, b: int) -> tuple[int, int, int]:
        lr, lg, lb = self.decode[0][r], self.decode[1][g], self.decode[2][b]
        encode, steps = self._encode, _ENCODE_STEPS
        out = []
        for row in self.matrix:
            value = row[0] * lr + row[1] * lg + row[2] * lb
            out.append(0 if value <= 0.0 else 255 if value >= 1.0 else encode[int(value * steps + 0.5)])
        return out[0], out[1], out[2]

    def convert_pixels(self, pixels: bytes, channels: int) -> bytes:
        """``pixels`` packed RGB (``channels`` 3) or RGBA (4); alpha passes through."""
        cache: dict[bytes, bytes] = {}
        out = bytearray(len(pixels))
        convert = self.convert
        for start in range(0, len(pixels) - channels + 1, channels):
            key = pixels[start:start + 3]
            found = cache.get(key)
            if found is None:
                found = bytes(convert(key[0], key[1], key[2]))
                cache[key] = found
            out[start:start + 3] = found
            if channels == 4:
                out[start + 3] = pixels[start + 3]
        return bytes(out)


__all__ = [
    "RGBProfile",
    "SRGB_COLORANTS",
    "ToSRGB",
    "is_srgb",
    "parse",
    "srgb_decode",
    "srgb_encode",
]
