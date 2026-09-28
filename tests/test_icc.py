"""A picture's ICC profile, read and applied: the samples PowerPoint wrote.

Every expected colour below is what PowerPoint's PDF export held for a flat patch of a
probe picture (pptx2svg's ``tools/make_exposed_probe.py``): PowerPoint converts a
profiled picture to sRGB, and this is that conversion.
"""

from __future__ import annotations

import struct
import zlib

import pytest

from ooxml_common import icc, imagemeta

D50 = (0.9642, 1.0, 0.8249)
ADOBE = ((0.60974, 0.31111, 0.01947), (0.20528, 0.62567, 0.06087), (0.14919, 0.06322, 0.74457))
P3 = ((0.51512, 0.24120, -0.00105), (0.29198, 0.69225, 0.04189), (0.15710, 0.06657, 0.78407))
SRGB = tuple(tuple(icc.SRGB_COLORANTS[row][column] for row in range(3)) for column in range(3))


def _s15(value: float) -> bytes:
    return struct.pack(">i", round(value * 65536))


def _profile(primaries, curve: bytes, *, extra=()) -> bytes:
    """A version 2 RGB display profile with the three ``primaries`` and one ``curve``."""

    def xyz(values) -> bytes:
        return b"XYZ \x00\x00\x00\x00" + b"".join(_s15(v) for v in values)

    tags = [(b"wtpt", xyz(D50)), (b"rXYZ", xyz(primaries[0])), (b"gXYZ", xyz(primaries[1])),
            (b"bXYZ", xyz(primaries[2])), (b"rTRC", curve), (b"gTRC", curve), (b"bTRC", curve),
            *extra]
    offset = 132 + 12 * len(tags)
    table = data = b""
    for signature, body in tags:
        while (offset + len(data)) % 4:
            data += b"\x00"
        table += signature + struct.pack(">II", offset + len(data), len(body))
        data += body
    header = (struct.pack(">I", offset + len(data)) + b"none" + bytes([2, 0x10, 0, 0]) + b"mntrRGB XYZ "
              + b"\x00" * 12 + b"acsp" + b"\x00" * 24 + struct.pack(">I", 0) + b"".join(_s15(v) for v in D50)
              + b"\x00" * 48)
    return header + struct.pack(">I", len(tags)) + table + data


def _gamma(value: float) -> bytes:
    return b"curv\x00\x00\x00\x00" + struct.pack(">IH", 1, round(value * 256)) + b"\x00\x00"


def _srgb_curve() -> bytes:
    params = (2.4, 1 / 1.055, 0.055 / 1.055, 1 / 12.92, 0.04045)
    return b"para\x00\x00\x00\x00" + struct.pack(">HH", 3, 0) + b"".join(_s15(v) for v in params)


#: (patch, PowerPoint's sample) under each probe profile: the PNG's, which PowerPoint
#: re-encoded losslessly.  Every one within a level of the exact conversion but one: the
#: Adobe profile's near-black patch, 12, which PowerPoint (16.x on macOS) wrote as 10 and
#: exact arithmetic -- and little CMS, and MuPDF drawing a profiled picture PowerPoint
#: passed through, as it did ``real-college-template``'s -- make 4.  One reading, which a
#: slope limit of 1/16 on the source curve near black would explain; not modelled.
PROBE_SAMPLES = {
    "adobe": [((128, 128, 128), (129, 129, 129)), ((200, 100, 50), (227, 100, 42)),
              ((30, 60, 90), (0, 57, 91)), ((240, 230, 10), (244, 231, 0)),
              ((255, 0, 0), (255, 0, 0))],
    "p3": [((128, 128, 128), (146, 146, 146)), ((200, 100, 50), (224, 113, 49)),
           ((30, 60, 90), (24, 78, 112)), ((240, 230, 10), (245, 235, 0)), ((12, 12, 12), (13, 13, 13))],
}


@pytest.mark.parametrize("name", list(PROBE_SAMPLES))
def test_a_matrix_profile_converts_to_srgb_as_powerpoint_does(name):
    data = _profile(ADOBE, _gamma(563 / 256)) if name == "adobe" else _profile(P3, _gamma(1.8))
    profile = icc.parse(data)
    assert profile is not None and not icc.is_srgb(profile)
    convert = icc.ToSRGB(profile)
    for patch, powerpoint in PROBE_SAMPLES[name]:
        got = convert.convert(*patch)
        assert all(abs(a - b) <= 1 for a, b in zip(got, powerpoint)), (patch, got, powerpoint)
    if name == "adobe":
        assert convert.convert(12, 12, 12) == (4, 4, 4)  # PowerPoint: 10, see above
        packed = bytes([200, 100, 50, 7, 128, 128, 128, 255])
        assert convert.convert_pixels(packed, 4) == bytes([227, 100, 42, 7, 129, 129, 129, 255])
        assert convert.convert_pixels(packed[:3], 3) == bytes([227, 100, 42])


def test_srgb_is_recognised_and_moves_nothing():
    profile = icc.parse(_profile(SRGB, _srgb_curve()))
    assert profile is not None and icc.is_srgb(profile)
    convert = icc.ToSRGB(profile)
    assert all(convert.convert(v, v, v) == (v, v, v) for v in range(256))


def test_a_lookup_table_profile_or_a_non_profile_is_refused():
    assert icc.parse(_profile(ADOBE, _gamma(2.2), extra=[(b"A2B0", b"mft2" + b"\x00" * 60)])) is None
    assert icc.parse(b"not a profile") is None
    assert icc.parse(None) is None
    grey = bytearray(_profile(ADOBE, _gamma(2.2)))
    grey[16:20] = b"GRAY"
    assert icc.parse(bytes(grey)) is None


def test_the_curve_forms():
    table = b"curv\x00\x00\x00\x00" + struct.pack(">I3H", 3, 0, 16384, 65535)
    profile = icc.parse(_profile(ADOBE, table))
    assert profile.curves[0](0.5) == pytest.approx(16384 / 65535)
    assert profile.curves[0](0.75) == pytest.approx((16384 / 65535 + 1) / 2)
    identity = icc.parse(_profile(ADOBE, b"curv\x00\x00\x00\x00" + struct.pack(">I", 0)))
    assert identity.curves[1](0.3) == 0.3
    srgb = icc.parse(_profile(ADOBE, _srgb_curve()))
    assert srgb.curves[2](0.5) == pytest.approx(icc.srgb_decode(0.5), abs=1e-4)


def _chunk(tag: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body))


def test_a_pictures_profile_is_read_from_a_png_and_a_jpeg():
    profile = _profile(ADOBE, _gamma(2.2))
    png = (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
           + _chunk(b"iCCP", b"probe\x00\x00" + zlib.compress(profile))
           + _chunk(b"IDAT", zlib.compress(b"\x00\x01\x02\x03")) + _chunk(b"IEND", b""))
    assert imagemeta.icc_profile(png) == profile
    # A JPEG's profile may be split across APP2 markers, numbered from 1.
    half = len(profile) // 2
    app2 = b"".join(
        b"\xff\xe2" + struct.pack(">H", 2 + 14 + len(part)) + b"ICC_PROFILE\x00" + bytes([index, 2]) + part
        for index, part in ((2, profile[half:]), (1, profile[:half]))
    )
    jpeg = b"\xff\xd8" + app2 + b"\xff\xda\x00\x02" + b"\x00" * 8 + b"\xff\xd9"
    assert imagemeta.icc_profile(jpeg) == profile
    assert imagemeta.icc_profile(b"\x89PNG\r\n\x1a\n" + _chunk(b"IEND", b"")) is None
    assert imagemeta.icc_profile(b"GIF89a") is None
