"""The package reader and a picture's natural size, through their public API.

A package is built here, in memory, from the chart gallery's parts
(``tests/fixtures/charts``), so the whole road a consumer takes -- open the ZIP, find the
document from the root relationships, follow a relationship to a chart part, read it
and lay it out -- runs on this package alone.  The pictures are a few bytes of header
written here: their natural size is read from the header, never from the pixels.
"""

from __future__ import annotations

import io
import struct
import zipfile
import zlib

import pytest

import goldens
from ooxml_common import imagemeta
from ooxml_common.opc import (
    CONTENT_TYPES_PART,
    REL_CHART,
    REL_IMAGE,
    REL_OFFICE_DOCUMENT,
    REL_SLIDE,
    OpcPackage,
    normalize_part_path,
    rels_path_for,
    resolve_target,
)

CT = "http://schemas.openxmlformats.org/package/2006/content-types"
RELS = "http://schemas.openxmlformats.org/package/2006/relationships"
HYPERLINK = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"


def _rels(*entries: str) -> str:
    return f'<Relationships xmlns="{RELS}">{"".join(entries)}</Relationships>'


def _package(*, root_rels: bool = True) -> bytes:
    chart = (goldens.FIXTURES / "charts" / "gallery-07-pieChart.xml").read_bytes()
    parts = {
        CONTENT_TYPES_PART: (
            f'<Types xmlns="{CT}">'
            '<Default Extension="XML" ContentType="application/xml"/>'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default ContentType="nothing/without-an-extension"/>'
            '<Override PartName="/ppt/presentation.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
            '<Override PartName="/ppt/charts/chart7.xml"/>'
            "<Comment/></Types>"
        ),
        "ppt/presentation.xml": "<presentation/>",
        "ppt/_rels/presentation.xml.rels": _rels(
            f'<Relationship Id="rId1" Type="{REL_SLIDE}" Target="slides/slide1.xml"/>'),
        "ppt/slides/slide1.xml": "<sld/>",
        "ppt/slides/_rels/slide1.xml.rels": _rels(
            f'<Relationship Id="rIdChart" Type="{REL_CHART}" Target="../charts/chart7.xml"/>',
            f'<Relationship Id="rIdPicture" Type="{REL_IMAGE}" Target="/ppt/media/image1.png"/>',
            f'<Relationship Id="rIdSecond" Type="{REL_IMAGE}" Target="../media/./image2.gif"/>',
            f'<Relationship Id="rIdLink" Type="{HYPERLINK}" Target="https://example.com/" TargetMode="External"/>',
            '<Relationship Id="rIdBroken" Target="nowhere.xml"/>',
            "<Other/>"),
        "ppt/charts/chart7.xml": chart,
        "ppt/media/image1.png": png(16, 8),
        "ppt/media/image2.gif": gif(3, 5),
    }
    if root_rels:
        parts["_rels/.rels"] = _rels(
            f'<Relationship Id="rId1" Type="{REL_OFFICE_DOCUMENT}" Target="ppt/presentation.xml"/>')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("ppt/media/", b"")
        for name, data in parts.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_a_package_is_read_from_bytes_a_file_or_a_stream(tmp_path):
    data = _package()
    path = tmp_path / "deck.pptx"
    path.write_bytes(data)
    for source in (data, str(path), io.BytesIO(data)):
        package = OpcPackage.open(source)
        assert package.presentation_part() == "ppt/presentation.xml"
        assert "ppt/media" not in package.parts and package.has_part("/ppt/media/image1.png")


def test_content_types_come_from_the_overrides_the_defaults_and_the_extension():
    package = OpcPackage.open(_package())
    assert package.content_type("/ppt/presentation.xml").endswith("presentation.main+xml")
    assert package.content_type("ppt/slides/slide1.xml") == "application/xml"  # Default, any case
    assert package.content_type("ppt/charts/chart7.xml") == "application/xml"  # an Override naming none
    assert package.content_type("ppt/media/image1.png") == "image/png"  # the extension alone
    assert package.content_type("ppt/media/image2.gif") == "image/gif"
    assert package.content_type("ppt/media/unknown.bin") is None


def test_relationships_resolve_against_the_part_that_declares_them():
    package = OpcPackage.open(_package())
    slide = "ppt/slides/slide1.xml"
    rels = package.relationships(slide)
    assert sorted(rels) == ["rIdChart", "rIdLink", "rIdPicture", "rIdSecond"]  # rIdBroken has no Type
    assert rels["rIdLink"].is_external and rels["rIdLink"].target_part is None
    assert package.related_part(slide, "rIdChart") == "ppt/charts/chart7.xml"
    assert package.related_part(slide, "rIdPicture") == "ppt/media/image1.png"  # an absolute target
    assert package.related_part(slide, "rIdSecond") == "ppt/media/image2.gif"
    assert package.related_part(slide, "rIdLink") is None
    assert package.related_part(slide, "rIdMissing") is None
    assert package.related_part(slide, None) is None
    assert package.relationships(slide) is rels  # read once
    assert package.related_parts_of_type(slide, REL_IMAGE) == ["ppt/media/image1.png", "ppt/media/image2.gif"]
    assert package.first_related_part(slide, REL_IMAGE) == "ppt/media/image1.png"
    assert package.first_related_part(slide, REL_SLIDE) is None
    assert package.relationships("ppt/media/image1.png") == {}
    assert package.first_related_part("ppt/presentation.xml", REL_SLIDE) == slide


def test_a_chart_is_found_read_and_laid_out_through_the_package():
    package = OpcPackage.open(_package())
    part = package.related_part("ppt/slides/slide1.xml", "rIdChart")
    element, notes = goldens.chart_element(package.read_xml(part), 288, 288)
    assert notes == [] and element.chart.kind == "pieChart"
    assert package.read("ppt/nothing.xml") is None and package.read_xml("ppt/nothing.xml") is None


def test_without_root_relationships_the_presentation_is_found_by_its_usual_path():
    package = OpcPackage.open(_package(root_rels=False))
    assert package.presentation_part() == "ppt/presentation.xml"
    package.parts.pop("ppt/presentation.xml")
    assert package.presentation_part() is None
    assert OpcPackage(parts={}).content_type("a.EMF") == "image/emf"
    assert OpcPackage(parts={}).content_type("a.xml") is None


@pytest.mark.parametrize(
    "path,normal",
    [("/ppt/slides/slide1.xml", "ppt/slides/slide1.xml"), ("ppt\\media\\a.png", "ppt/media/a.png"),
     ("ppt/slides/../media/./a.png", "ppt/media/a.png"), ("", "")],
)
def test_part_paths_are_normalised(path, normal):
    assert normalize_part_path(path) == normal


def test_a_part_s_relationships_live_beside_it():
    assert rels_path_for("ppt/slides/slide1.xml") == "ppt/slides/_rels/slide1.xml.rels"
    assert rels_path_for("") == "_rels/.rels"
    assert resolve_target("ppt/slides", "/word/x.xml") == "word/x.xml"
    assert resolve_target("ppt/slides", "../charts/c.xml") == "ppt/charts/c.xml"


# -- pictures ---------------------------------------------------------------------------


def _chunk(tag: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)


def png(width: int, height: int, *, per_metre: tuple[int, int, int] | None = None,
        profile: bytes | None = None, compression: int = 0) -> bytes:
    data = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    if profile is not None:
        data += _chunk(b"iCCP", b"probe\x00" + bytes([compression]) + zlib.compress(profile))
    if per_metre is not None:
        data += _chunk(b"pHYs", struct.pack(">IIB", *per_metre))
    data += _chunk(b"tEXt", b"Comment\x00made up") + _chunk(b"IDAT", zlib.compress(b"\x00" * (width * 3 + 1)))
    return data + _chunk(b"IEND", b"")


def gif(width: int, height: int) -> bytes:
    return b"GIF89a" + struct.pack("<HH", width, height) + b"\x00\x00\x00;"


def jpeg(width: int, height: int, *, units: int = 0, density: tuple[int, int] = (1, 1),
         profile_chunks: list[bytes] = (), frame: int = 0xC0) -> bytes:
    data = b"\xff\xd8"
    app0 = b"JFIF\x00\x01\x02" + bytes([units]) + struct.pack(">HH", *density) + b"\x00\x00"
    data += b"\xff\xe0" + struct.pack(">H", len(app0) + 2) + app0
    for index, chunk in enumerate(profile_chunks, 1):
        body = b"ICC_PROFILE\x00" + bytes([index, len(profile_chunks)]) + chunk
        data += b"\xff\xe2" + struct.pack(">H", len(body) + 2) + body
    data += b"\xff\xd0\x00"  # a restart marker and a stray byte
    data += b"\xff\xc4\x00\x03\x00"  # a table, which shares the frame markers' range
    sof = struct.pack(">BHHB", 8, height, width, 3) + b"\x01\x11\x00" * 3
    data += bytes([0xFF, frame]) + struct.pack(">H", len(sof) + 2) + sof
    return data + b"\xff\xda\x00\x02\xff\xd9"


def bmp(width: int, height: int, *, per_metre: tuple[int, int] = (0, 0), core: bool = False) -> bytes:
    if core:
        return b"BM" + b"\x00" * 12 + struct.pack("<IHHHH", 12, width, height, 1, 24) + b"\x00" * 4
    info = struct.pack("<IiiHHIIiiII", 40, width, -height, 1, 24, 0, 0, per_metre[0], per_metre[1], 0, 0)
    return b"BM" + b"\x00" * 12 + info


@pytest.mark.parametrize(
    "data,size",
    [
        # 144 dpi when nothing is stated: half a point a pixel (the module's measurement).
        (png(32, 32), (16.0, 16.0)),
        (png(48, 24), (24.0, 12.0)),
        # pHYs in pixels per metre: 72 dpi is 2834.6 a metre.
        (png(32, 32, per_metre=(2835, 2835, 1)), (32 * 72 / (2835 * 0.0254),) * 2),
        (png(32, 32, per_metre=(2835, 2835, 0)), (16.0, 16.0)),  # aspect only: no size
        (jpeg(32, 32), (16.0, 16.0)),
        (jpeg(64, 32, units=1, density=(96, 96)), (48.0, 24.0)),
        (jpeg(20, 10, units=2, density=(100, 100), frame=0xC2), (20 * 72 / 254, 10 * 72 / 254)),
        (gif(3, 5), (1.5, 2.5)),
        (bmp(30, 20, per_metre=(3780, 3780)), (30 * 72 / (3780 * 0.0254), 20 * 72 / (3780 * 0.0254))),
        (bmp(30, 20), (15.0, 10.0)),
        (bmp(8, 4, core=True), (4.0, 2.0)),
    ],
)
def test_a_picture_s_natural_size_comes_from_its_header(data, size):
    assert imagemeta.natural_size_pt(data) == pytest.approx(size)


@pytest.mark.parametrize(
    "data",
    [b"", b"<svg/>", b"GIF89a\x00", gif(0, 5), b"BM" + b"\x00" * 30, bmp(0, 4), b"BM" + b"\x00" * 12 + b"\x10" + b"\x00" * 15,
     b"\x89PNG\r\n\x1a\n" + _chunk(b"IEND", b""), b"\xff\xd8\xff\xda\x00\x02", b"\xff\xd8" + b"\x00" * 6,
     jpeg(0, 0)],
)
def test_a_header_that_states_no_size_gives_none(data):
    assert imagemeta.natural_size_pt(data) is None


def test_a_picture_s_colour_profile_is_found_in_png_and_jpeg():
    profile = b"made-up profile bytes " * 8
    assert imagemeta.icc_profile(png(2, 2, profile=profile)) == profile
    assert imagemeta.icc_profile(png(2, 2)) is None
    assert imagemeta.icc_profile(png(2, 2, profile=profile, compression=1)) is None
    broken = png(2, 2, profile=profile).replace(zlib.compress(profile), b"not deflate")
    assert imagemeta.icc_profile(broken) is None
    assert imagemeta.icc_profile(b"\x89PNG\r\n\x1a\n" + _chunk(b"iCCP", b"no terminator")) is None
    # A JPEG may split one profile over several APP2 markers; they are joined in order.
    assert imagemeta.icc_profile(jpeg(2, 2, profile_chunks=[profile[:50], profile[50:]])) == profile
    assert imagemeta.icc_profile(jpeg(2, 2)) is None
    assert imagemeta.icc_profile(gif(1, 1)) is None
