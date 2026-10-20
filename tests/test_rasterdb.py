"""The font files a resvg rasterisation needs (:mod:`ooxml_common.fonts.rasterdb`).

What is kept must draw the same pixels as everything handed over: every face filed under
a name a run can resolve to, every face that maps a character some candidate face of its
run lacks, in the order resvg loads them; and where the SVG could name a face some other
way, the answer is ``None`` (hand over everything).  The fonts are made here: a ``name``
table and a ``cmap`` -- all the module reads.  That the pixels are the same is checked
where resvg is installed, by the renderers' own tests (pptx2svg ``tests/test_png.py``).
"""

from __future__ import annotations

import base64
import os
import struct
import sys
from pathlib import Path

import pytest

from ooxml_common.fonts import office, rasterdb
from ooxml_common.fonts.sfnt import write_sfnt

SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="40">{}</svg>'


def _name(families: dict[int, str]) -> bytes:
    records, storage = [], b""
    for name_id, text in families.items():
        raw = text.encode("utf-16-be")
        records.append(struct.pack(">HHHHHH", 3, 1, 0x409, name_id, len(raw), len(storage)))
        storage += raw
    return struct.pack(">HHH", 0, len(records), 6 + 12 * len(records)) + b"".join(records) + storage


def _cmap(chars: str, platform: int = 3, encoding: int = 10) -> bytes:
    codes = sorted({ord(char) for char in chars})
    groups = b"".join(struct.pack(">III", code, code, index + 1) for index, code in enumerate(codes))
    subtable = struct.pack(">HHIII", 12, 0, 16 + len(groups), 0, len(codes)) + groups
    return struct.pack(">HHHHI", 0, 1, platform, encoding, 12) + subtable


def _font(path: Path, family: str, chars: str = "abcdefghijklmnopqrstuvwxyz ", *,
          typographic: str | None = None) -> Path:
    names = {1: family}
    if typographic:
        names[16] = typographic
    path.write_bytes(write_sfnt([(b"name", _name(names)), (b"cmap", _cmap(chars))]))
    return path


def _text(family: str | None, text: str = "abc") -> str:
    attribute = f' font-family="{family}"' if family is not None else ""
    return f'<text x="0" y="20"{attribute}>{text}</text>'


@pytest.fixture(autouse=True)
def fresh():
    office.refresh_font_dirs()
    yield
    office.refresh_font_dirs()


def _needed(svg, dirs, **kwargs):
    found = rasterdb.needed_font_files(svg, font_dirs=[str(d) for d in dirs], **kwargs)
    return None if found is None else [Path(p).name for p in found]


def test_only_the_faces_a_run_names_are_kept(tmp_path):
    _font(tmp_path / "a.ttf", "Alpha")
    _font(tmp_path / "b.ttf", "Beta")
    _font(tmp_path / "c.ttf", "Gamma")
    assert _needed(SVG.format(_text("Beta, 'Gamma'")), [tmp_path]) == sorted(
        ["b.ttf", "c.ttf"], key=[e.name for e in os.scandir(tmp_path)].index)


def test_names_are_compared_without_case_and_by_either_family_name(tmp_path):
    _font(tmp_path / "display.ttf", "Sample Display", typographic="Sample")
    _font(tmp_path / "other.ttf", "Other")
    # resvg files the face under name ID 16 only; kept by ID 1 too, which keeps more.
    assert _needed(SVG.format(_text("sample")), [tmp_path]) == ["display.ttf"]
    assert _needed(SVG.format(_text("'SAMPLE DISPLAY'")), [tmp_path]) == ["display.ttf"]


def test_the_generic_and_default_families_are_kept(tmp_path):
    _font(tmp_path / "sans.ttf", "Sansy")
    _font(tmp_path / "serif.ttf", "Serifa")
    _font(tmp_path / "other.ttf", "Other")
    families = {"sans_serif_family": "Sansy", "serif_family": "Serifa", "font_family": "Serifa"}
    # Every stack ends in the serif family, which resvg appends to every query.
    assert set(_needed(SVG.format(_text("Missing, sans-serif")), [tmp_path], families=families)) == {
        "sans.ttf", "serif.ttf"}
    assert _needed(SVG.format(_text(None)), [tmp_path], families=families) == ["serif.ttf"]


def test_a_face_for_a_missing_character_is_kept(tmp_path):
    _font(tmp_path / "latin.ttf", "Latin", "abc")
    _font(tmp_path / "kana.ttf", "Kana", "かな")
    _font(tmp_path / "symbols.ttf", "Symbols", "→")
    # 'か' is not in Latin: resvg falls back to the first loaded face that maps it.
    assert set(_needed(SVG.format(_text("Latin", "abかc")), [tmp_path])) == {"latin.ttf", "kana.ttf"}
    assert _needed(SVG.format(_text("Latin", "abc")), [tmp_path]) == ["latin.ttf"]


def test_the_load_order_is_resvgs(tmp_path):
    folder = tmp_path / "fonts"
    (folder / "sub").mkdir(parents=True)
    _font(folder / "sub" / "inner.ttf", "Same")
    _font(folder / "outer.TTF", "Same")
    _font(folder / "mixed.Ttf", "Same")           # not an extension resvg loads from a folder
    _font(folder / ".ttf", "Same")                # no extension at all
    (folder / "notes.txt").write_text("not a font")
    explicit = _font(tmp_path / "explicit.otf", "Same")
    # The files named first, then the folder as the system lists it, a subfolder where
    # it is met; a file that is not there is not loaded.
    order = []
    for entry in os.scandir(folder):
        if entry.name == "sub":
            order.append(str(folder / "sub" / "inner.ttf"))
        elif entry.name == "outer.TTF":
            order.append(str(folder / "outer.TTF"))
    files = [str(explicit), str(tmp_path / "absent.ttf")]
    assert rasterdb.load_order(files, [str(folder)]) == [str(explicit), *order]
    found = rasterdb.needed_font_files(SVG.format(_text("Same")), font_files=files, font_dirs=[str(folder)])
    assert found == [str(explicit), *order]


@pytest.mark.skipif(sys.platform == "win32", reason="symbolic links need privileges on Windows")
def test_links_are_followed_to_their_target(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    target = _font(store / "real.ttf", "Linked")
    folder = tmp_path / "fonts"
    folder.mkdir()
    (folder / "link.ttf").symlink_to(target)
    (folder / "again.ttf").symlink_to(target)
    found = rasterdb.needed_font_files(SVG.format(_text("Linked")), font_dirs=[str(folder)])
    assert found == [os.path.realpath(target)]


def test_a_font_added_to_a_folder_is_seen(tmp_path):
    _font(tmp_path / "a.ttf", "Alpha")
    svg = SVG.format(_text("Alpha, Beta"))
    assert _needed(svg, [tmp_path]) == ["a.ttf"]
    _font(tmp_path / "b.ttf", "Beta")
    stamp = os.stat(tmp_path).st_mtime_ns + 1_000_000_000
    os.utime(tmp_path, ns=(stamp, stamp))
    assert set(_needed(svg, [tmp_path])) == {"a.ttf", "b.ttf"}


def test_a_file_it_cannot_read_is_kept(tmp_path):
    _font(tmp_path / "a.ttf", "Alpha")
    (tmp_path / "broken.ttf").write_bytes(b"\x00\x01\x00\x00garbage")
    assert set(_needed(SVG.format(_text("Alpha")), [tmp_path])) == {"a.ttf", "broken.ttf"}


def test_a_collection_is_one_file(tmp_path):
    one = write_sfnt([(b"name", _name({1: "First"})), (b"cmap", _cmap("abc"))])
    two = write_sfnt([(b"name", _name({1: "Second"})), (b"cmap", _cmap("abc"))])
    header = b"ttcf" + struct.pack(">HHI", 1, 0, 2)
    start = len(header) + 8
    # Each member's table offsets are from the start of the file: shift the second's.
    data = bytearray(header + struct.pack(">II", start, start + len(one)) + one + two)
    count = struct.unpack_from(">H", two, 4)[0]
    for i in range(count):
        at = start + len(one) + 12 + 16 * i + 8
        struct.pack_into(">I", data, at, struct.unpack_from(">I", data, at)[0] + start + len(one))
    for i in range(struct.unpack_from(">H", one, 4)[0]):
        at = start + 12 + 16 * i + 8
        struct.pack_into(">I", data, at, struct.unpack_from(">I", data, at)[0] + start)
    (tmp_path / "pair.ttc").write_bytes(bytes(data))
    _font(tmp_path / "other.ttf", "Other")
    assert _needed(SVG.format(_text("Second")), [tmp_path]) == ["pair.ttc"]


def test_no_text_needs_no_font(tmp_path):
    _font(tmp_path / "a.ttf", "Alpha")
    assert _needed(SVG.format('<rect width="10" height="10"/>'), [tmp_path]) == []


@pytest.mark.parametrize("body", [
    "<style>text { font-family: Beta }</style>" + _text("Alpha"),
    '<text x="0" y="20" style="font-family: Beta">abc</text>',
    '<defs>' + _text("Alpha").replace("<text", '<text id="t"') + '</defs><use href="#t"/>',
    '<image href="picture.svg" width="10" height="10"/>' + _text("Alpha"),
])
def test_a_family_named_another_way_hands_everything_over(tmp_path, body):
    _font(tmp_path / "a.ttf", "Alpha")
    assert _needed(SVG.format(body), [tmp_path]) is None


def test_an_svg_picture_carried_as_data_is_read(tmp_path):
    _font(tmp_path / "a.ttf", "Alpha")
    _font(tmp_path / "b.ttf", "Beta")
    nested = base64.b64encode(SVG.format(_text("Beta")).encode()).decode()
    body = _text("Alpha") + f'<image href="data:image/svg+xml;base64,{nested}" width="10" height="10"/>'
    assert set(_needed(SVG.format(body), [tmp_path])) == {"a.ttf", "b.ttf"}
    png = '<image href="data:image/png;base64,iVBORw0KGgo=" width="1" height="1"/>'
    assert _needed(SVG.format(_text("Alpha") + png), [tmp_path]) == ["a.ttf"]


def test_system_fonts_that_resvg_finds_through_fontconfig_hand_everything_over(tmp_path, monkeypatch):
    _font(tmp_path / "a.ttf", "Alpha")
    monkeypatch.setattr(rasterdb.sys, "platform", "linux")
    assert _needed(SVG.format(_text("Alpha")), [tmp_path], system_fonts=True) is None
    assert _needed(SVG.format(_text("Alpha")), [tmp_path], system_fonts=False) == ["a.ttf"]


def test_a_system_face_lacking_a_character_keeps_the_faces_that_have_it(tmp_path, monkeypatch):
    system = tmp_path / "system"
    system.mkdir()
    _font(system / "base.ttf", "Base", "abc")
    mine = tmp_path / "mine"
    mine.mkdir()
    _font(mine / "kana.ttf", "Kana", "か")
    _font(mine / "other.ttf", "Other", "xyz")
    monkeypatch.setattr(rasterdb, "resvg_system_dirs", lambda: [str(system)])
    assert _needed(SVG.format(_text("Base", "aか")), [mine], system_fonts=True) == ["kana.ttf"]
