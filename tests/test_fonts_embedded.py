"""Fonts a deck carries in ``<p:embeddedFontLst>``.

Two kinds of test here, and the split is deliberate.

**Against real PowerPoint output.**  ``tests/fixtures/real-basic-theme.pptx`` embeds eight
faces -- Lato and Raleway, all four cuts each -- as EOT 2.2 payloads that PowerPoint wrote
and MicroType Express compressed.  Nothing in this repository produced them, so decoding
them is a real test of the decoder rather than our writer agreeing with our reader.  That
the roadmap recorded "no corpus deck embeds fonts" turned out to be wrong is the reason
this feature could be tested in CI at all.

**Against synthetic EOTs.**  The uncompressed and XOR-obfuscated variants, and every
``fsType`` refusal, have no example in any deck on hand, so they are built here.  A
synthetic font with one deliberate advance width also makes the measurement assertion
sharp in a way a real face cannot: if every glyph is 1234/2048 em wide, a string of ten
characters has exactly one right answer.

Only the synthetic half travelled to ooxml-common: it exercises the decoders alone.
The real-deck half reads ``<p:embeddedFontLst>`` through pptx2svg's parser and stays in
pptx2svg's copy of this file, together with the fixtures it reads.
"""

from __future__ import annotations

import io
import struct

import pytest

from ooxml_common.fonts.eot import (
    EMBEDDING_BITMAP_ONLY,
    EMBEDDING_EDITABLE,
    EMBEDDING_NO_SUBSETTING,
    EMBEDDING_PREVIEW_PRINT,
    EMBEDDING_RESTRICTED,
    EotError,
    decode_eot,
    embedding_refusal,
    read_eot_header,
)
from ooxml_common.fonts.mtx import MtxDecodeError, decode_mtx
from ooxml_common.fonts.sfnt import SfntError, read_sfnt, relabel, write_sfnt



# --------------------------------------------------------------------------------------
# A font built here, so a measurement has exactly one right answer
# --------------------------------------------------------------------------------------

#: Every glyph in the probe face advances this much, in a 2048-unit em.  A round number
#: nothing else in the project uses, so a width computed from any other table is obvious.
PROBE_ADVANCE = 1234
PROBE_UPM = 2048
PROBE_ASCENDER = 1700
PROBE_DESCENDER = -500
#: The code points the probe face maps: printable ASCII.
PROBE_FIRST, PROBE_LAST = 0x20, 0x7E


def build_probe_font(*, fs_type: int = 0, advance: int = PROBE_ADVANCE) -> bytes:
    """A minimal but valid TrueType file with a known advance for every mapped glyph.

    No ``glyf``: nothing in these tests rasterises it, and :func:`read_sfnt` needs only
    the metric tables.  ``write_sfnt`` supplies the directory and the checksums.
    """
    glyphs = PROBE_LAST - PROBE_FIRST + 2  # + .notdef

    head = bytearray(54)
    struct.pack_into(">II", head, 0, 0x00010000, 0x00010000)  # version, fontRevision
    struct.pack_into(">I", head, 12, 0x5F0F3CF5)  # magicNumber
    struct.pack_into(">HH", head, 16, 0x000B, PROBE_UPM)  # flags, unitsPerEm
    struct.pack_into(">hhhh", head, 36, 0, PROBE_DESCENDER, advance, PROBE_ASCENDER)
    struct.pack_into(">hhh", head, 48, 2, 0, 0)  # lowestRecPPEM, indexToLocFormat, glyphDataFormat

    hhea = bytearray(36)
    struct.pack_into(">I", hhea, 0, 0x00010000)
    struct.pack_into(">hhh", hhea, 4, PROBE_ASCENDER, PROBE_DESCENDER, 0)
    struct.pack_into(">H", hhea, 10, advance)  # advanceWidthMax
    struct.pack_into(">H", hhea, 34, glyphs)  # numberOfHMetrics

    maxp = struct.pack(">IH", 0x00005000, glyphs)
    hmtx = b"".join(struct.pack(">Hh", advance, 0) for _ in range(glyphs))

    # cmap: one (3, 10) subtable in format 12 -- simpler to write by hand than format 4
    # and ranked first by the reader.
    group = struct.pack(">III", PROBE_FIRST, PROBE_LAST, 1)
    subtable = struct.pack(">HHIII", 12, 0, 16 + len(group), 0, 1) + group
    cmap = struct.pack(">HHHHI", 0, 1, 3, 10, 12) + subtable

    os2 = bytearray(96)
    struct.pack_into(">H", os2, 0, 4)  # version
    struct.pack_into(">H", os2, 2, advance)  # xAvgCharWidth
    struct.pack_into(">HH", os2, 4, 400, 5)  # usWeightClass, usWidthClass
    struct.pack_into(">H", os2, 8, fs_type)
    struct.pack_into(">H", os2, 62, 0x0040)  # fsSelection: REGULAR
    struct.pack_into(">HH", os2, 64, PROBE_FIRST, PROBE_LAST)
    struct.pack_into(">hhh", os2, 68, PROBE_ASCENDER, PROBE_DESCENDER, 0)

    name = _name_table([(1, "Probe Face"), (2, "Regular"), (4, "Probe Face"), (6, "ProbeFace")])

    return write_sfnt(
        [
            (b"OS/2", bytes(os2)),
            (b"cmap", cmap),
            (b"head", bytes(head)),
            (b"hhea", bytes(hhea)),
            (b"hmtx", hmtx),
            (b"maxp", maxp),
            (b"name", name),
        ]
    )


def _name_table(entries: list[tuple[int, str]]) -> bytes:
    records = [(3, 1, 0x409, name_id, value.encode("utf-16-be")) for name_id, value in entries]
    header = bytearray(struct.pack(">HHH", 0, len(records), 6 + 12 * len(records)))
    strings = bytearray()
    for platform, encoding, language, name_id, raw in records:
        header += struct.pack(
            ">HHHHHH", platform, encoding, language, name_id, len(raw), len(strings)
        )
        strings += raw
    return bytes(header + strings)


def wrap_as_eot(
    font: bytes,
    *,
    family: str = "Probe Face",
    style: str = "Regular",
    flags: int = 0,
    fs_type: int = 0,
    weight: int = 400,
) -> bytes:
    """Wrap a font in an EOT 1.0 container.

    Version 0x00010000 rather than 2.2 on purpose: the header's variable tail differs by
    version, and building the oldest one exercises the fact that the reader derives the
    font-data offset from ``EOTSize - FontDataSize`` rather than by walking that tail.
    """
    if flags & 0x10000000:  # TTEMBED_XORENCRYPTDATA
        font = bytes(byte ^ 0x50 for byte in font)

    names = b""
    for value in (family, style, "Version 1.000", f"{family} {style}"):
        encoded = value.encode("utf-16-le")
        names += struct.pack("<HH", 0, len(encoded)) + encoded

    header = bytearray(80)
    struct.pack_into("<I", header, 8, 0x00010000)  # Version
    struct.pack_into("<I", header, 12, flags)
    struct.pack_into("<I", header, 28, weight)
    struct.pack_into("<HH", header, 32, fs_type, 0x504C)  # fsType, MagicNumber
    body = bytes(header) + names
    struct.pack_into("<I", header, 0, len(body) + len(font))  # EOTSize
    struct.pack_into("<I", header, 4, len(font))  # FontDataSize
    return bytes(header) + names + font


@pytest.fixture(scope="module")
def probe_font() -> bytes:
    return build_probe_font()


# --------------------------------------------------------------------------------------
# The EOT container
# --------------------------------------------------------------------------------------


def test_an_uncompressed_payload_round_trips(probe_font):
    assert decode_eot(wrap_as_eot(probe_font)) == probe_font


def test_an_xor_obfuscated_payload_round_trips(probe_font):
    assert decode_eot(wrap_as_eot(probe_font, flags=0x10000000)) == probe_font


def test_the_header_reports_what_it_was_given(probe_font):
    header = read_eot_header(wrap_as_eot(probe_font, family="Probe Face", style="Bold", weight=700))
    assert header.family_name == "Probe Face"
    assert header.style_name == "Bold"
    assert header.weight == 700
    assert header.font_data_size == len(probe_font)
    assert not header.compressed and not header.encrypted


def test_a_payload_without_the_magic_number_is_refused(probe_font):
    data = bytearray(wrap_as_eot(probe_font))
    struct.pack_into("<H", data, 34, 0x1234)
    with pytest.raises(EotError, match="magic number"):
        read_eot_header(bytes(data))


def test_a_truncated_payload_is_refused(probe_font):
    with pytest.raises(EotError):
        read_eot_header(wrap_as_eot(probe_font)[:60])


def test_garbage_in_the_compressed_payload_does_not_escape_as_something_else(probe_font):
    data = wrap_as_eot(probe_font, flags=0x00000004)  # claims MTX, is not
    with pytest.raises(EotError, match="MicroType Express"):
        decode_eot(data)


def test_mtx_rejects_a_payload_shorter_than_its_header():
    with pytest.raises(MtxDecodeError):
        decode_mtx(b"\x03\x00\x00")


# --------------------------------------------------------------------------------------
# The fsType gate
#
# Bits are from the OpenType spec's OS/2 fsType field.  The rule is LibreOffice's
# `sufficientTTFRights`: refuse only a font whose permission field says restricted licence
# and says nothing else.
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fs_type",
    [
        0x0000,  # installable
        EMBEDDING_PREVIEW_PRINT,
        EMBEDDING_EDITABLE,
        EMBEDDING_RESTRICTED | EMBEDDING_PREVIEW_PRINT,  # restrictive *and* permissive
        EMBEDDING_RESTRICTED | EMBEDDING_EDITABLE,
        EMBEDDING_NO_SUBSETTING,  # we never subset, so this is not our business
        EMBEDDING_EDITABLE | EMBEDDING_NO_SUBSETTING,
    ],
)
def test_permitted_fs_type_values_are_allowed(fs_type):
    assert embedding_refusal(fs_type) is None


@pytest.mark.parametrize(
    "fs_type, reason",
    [
        (EMBEDDING_RESTRICTED, "restricted-licence"),
        (EMBEDDING_BITMAP_ONLY, "bitmap embedding only"),
        (EMBEDDING_EDITABLE | EMBEDDING_BITMAP_ONLY, "bitmap embedding only"),
    ],
)
def test_refused_fs_type_values_say_why(fs_type, reason):
    refusal = embedding_refusal(fs_type)
    assert refusal is not None and reason in refusal


def test_a_restricted_header_is_refused_before_anything_is_decoded(probe_font):
    with pytest.raises(EotError, match="restricted-licence"):
        decode_eot(wrap_as_eot(probe_font, fs_type=EMBEDDING_RESTRICTED))


# --------------------------------------------------------------------------------------
# Relabelling -- so the rasteriser can find the face the SVG asks for
# --------------------------------------------------------------------------------------


def test_the_face_takes_the_name_the_deck_gave_it(probe_font):
    relabelled = read_sfnt(relabel(probe_font, "Deck Says This", bold=True, italic=False))
    assert relabelled.family_name == "Deck Says This"
    assert relabelled.subfamily_name == "Bold"
    assert relabelled.weight_class == 700


def test_relabelling_keeps_every_advance_width(probe_font):
    before = read_sfnt(probe_font)
    after = read_sfnt(relabel(probe_font, "Something Else", bold=False, italic=True))
    assert after.advances == before.advances
    assert after.units_per_em == before.units_per_em
