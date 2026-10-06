"""The shared Office font lookup: locations, each application's measured order, the face
reader, and advance tables built from installed faces with their legacy kern pairs.

Office is not needed: the OFL faces of the ``pptx2svg-fonts`` bundle stand in for an
application's bundle, macOS's folders and the cloud cache, linked into temporary folders
(new links, read in place), and the tests that need them skip without the bundle.
"""

from __future__ import annotations

import shutil
import struct
from pathlib import Path

import pytest

from ooxml_common.fonts import bundle_dir, embedded, office
from ooxml_common.fonts.sfnt import read_sfnt, write_sfnt
from ooxml_common.text import kerning

BUNDLE = bundle_dir()
needs_bundle = pytest.mark.skipif(BUNDLE is None, reason="the pptx2svg-fonts bundle is not installed")


def _link(link: Path, target: Path) -> None:
    """A new link to an OFL face in a temporary folder; a copy where the platform will
    not make links (Windows without the privilege)."""
    try:
        link.symlink_to(target)
    except OSError:
        shutil.copyfile(target, link)


@pytest.fixture
def places(monkeypatch, tmp_path):
    """Three empty locations: an application bundle, the system's folders, the cloud cache."""
    roots = {name: tmp_path / name for name in ("bundle", "system", "cloud")}
    for root in roots.values():
        root.mkdir()
    monkeypatch.setattr(office, "OFFICE_CLOUD_FONTS", roots["cloud"])
    monkeypatch.setattr(office, "system_font_dirs", lambda: (roots["system"],))
    return roots


def _app(template: office.Application, bundle: Path) -> office.Application:
    return office.Application(template.name, bundle, template.layout, template.drawing, template.prefer_bundle)


# -- Locations and orders ---------------------------------------------------------------


def test_the_measured_orders():
    assert office.POWERPOINT.layout == office.POWERPOINT.drawing == ("powerpoint", "system", "cloud")
    assert office.WORD.layout == ("system", "word", "cloud")
    assert office.WORD.drawing == ("word", "system", "cloud")
    assert office.WORD.prefer_bundle == frozenset({"symbol"})
    with pytest.raises(ValueError):
        office.WORD.order("printing")


def test_the_cloud_cache_is_one_folder_per_family(tmp_path):
    assert office.cloud_font_dirs(tmp_path / "missing") == ()
    (tmp_path / "Aptos Display").mkdir()
    (tmp_path / "stray.txt").write_text("")
    assert office.cloud_font_dirs(tmp_path) == (tmp_path / "Aptos Display",)


def test_words_flat_folder_list(monkeypatch, tmp_path):
    """docx2svg's ``FONT_DIRS``: macOS's four, Word's bundle, then the cache's families;
    the drawing order puts the bundle first."""
    (tmp_path / "Lato").mkdir()
    monkeypatch.setattr(office, "OFFICE_CLOUD_FONTS", tmp_path)
    assert office.font_dirs(office.WORD) == office.MACOS_FONT_DIRS + (office.WORD_FONTS, tmp_path / "Lato")
    assert office.font_dirs(office.WORD, "drawing") == (office.WORD_FONTS,) + office.MACOS_FONT_DIRS + (
        tmp_path / "Lato",)


def test_nothing_is_found_where_nothing_is_installed(places, tmp_path):
    app = _app(office.POWERPOINT, tmp_path / "absent")
    assert office.search_dirs(app) == (("system", places["system"]),)
    assert office.find("Aptos", app) == ()
    assert office.find(None) == () and office.find("+mn-lt") == ()


# -- Finding a face ---------------------------------------------------------------------


@needs_bundle
def test_powerpoint_takes_its_bundle_first_and_word_lays_out_with_the_system(places):
    _link(places["bundle"] / "Carlito-Regular.ttf", BUNDLE / "Carlito-Regular.ttf")
    _link(places["system"] / "Carlito-Bold.ttf", BUNDLE / "Carlito-Bold.ttf")
    _link(places["system"] / "Carlito-Regular.ttf", BUNDLE / "Carlito-Regular.ttf")
    (places["cloud"] / "Lato").mkdir()
    _link(places["cloud"] / "Lato" / "1234.ttf", BUNDLE / "Lato-Regular.ttf")
    powerpoint = _app(office.POWERPOINT, places["bundle"])
    word = _app(office.WORD, places["bundle"])
    # The first location that has the family wins, all its styles from there.
    assert [face.location for face in office.find("Carlito", powerpoint)] == ["powerpoint"]
    assert {face.location for face in office.find("carlito ", word)} == {"system"}
    assert len(office.find("Carlito", word)) == 2
    assert [face.location for face in office.find("Carlito", word, "drawing")] == ["word"]
    # The cache is searched last, and answers where nothing else does.
    assert [face.location for face in office.find("Lato", word)] == ["cloud"]


@needs_bundle
def test_a_prefer_bundle_family_is_laid_out_from_the_bundle(places):
    _link(places["bundle"] / "Tinos-Regular.ttf", BUNDLE / "Tinos-Regular.ttf")
    _link(places["system"] / "Tinos-Regular.ttf", BUNDLE / "Tinos-Regular.ttf")
    word = office.Application("word", places["bundle"], office.WORD.layout, office.WORD.drawing,
                              prefer_bundle=frozenset({"tinos"}))
    assert [face.location for face in office.find("Tinos", word)] == ["word"]


@needs_bundle
def test_the_header_index_names_faces_as_documents_and_resvg_do(tmp_path):
    faces = office.faces_in(BUNDLE / "Carlito-BoldItalic.ttf", "system")
    assert len(faces) == 1
    face = faces[0]
    assert face.families == frozenset({"carlito"}) and face.rasteriser_families == frozenset({"carlito"})
    assert (face.bold, face.italic, face.css, face.variable) == (True, True, (700, 5, "italic"), False)
    assert office.faces_in(BUNDLE / "NotoSansJP[wght].ttf", "system")[0].variable
    (tmp_path / "broken.ttf").write_bytes(b"\x00\x01\x00\x00garbage")
    (tmp_path / "empty.otf").write_bytes(b"")
    assert office.faces_in(tmp_path / "broken.ttf", "system") == []
    assert office.faces_in(tmp_path / "empty.otf", "system") == []


# -- Reading a face ---------------------------------------------------------------------


@needs_bundle
def test_the_face_reader_agrees_with_fonttools():
    ttlib = pytest.importorskip("fontTools.ttLib")
    path = BUNDLE / "Tinos-Regular.ttf"
    ((_, face),) = office.faces_of(path)
    reference = ttlib.TTFont(str(path))
    cmap = reference.getBestCmap()
    for char in "AVaw.,Ω€":
        assert face.advance(char) == reference["hmtx"][cmap[ord(char)]][0]
    assert face.units_per_em == reference["head"].unitsPerEm
    assert face.style == (False, False) and not face.variable
    assert "Tinos" in face.families() and face.rasteriser_families[0] == "Tinos"
    assert face.legacy_kern == {} and face.kern("A", "V") == 0   # GPOS only


def _kern_table(pairs: dict[tuple[int, int], int]) -> bytes:
    """A legacy ``kern`` table, version 0, one horizontal format 0 subtable."""
    body = b"".join(struct.pack(">HHh", left, right, value) for (left, right), value in sorted(pairs.items()))
    count = len(pairs)
    subtable = struct.pack(">HHHHHHH", 0, 14 + len(body), 0x0001, count, 0, 0, 0) + body
    return struct.pack(">HH", 0, 1) + subtable


def test_the_legacy_table_is_read_first_subtable_first():
    table = _kern_table({(36, 57): -80, (55, 82): -40})
    assert office.read_legacy_kern(table) == {(36, 57): -80, (55, 82): -40}
    second = struct.pack(">HHHHHHH", 0, 20, 0x0001, 1, 0, 0, 0) + struct.pack(">HHh", 36, 57, -10)
    two = struct.pack(">HH", 0, 2) + table[4:] + second
    assert office.read_legacy_kern(two)[(36, 57)] == -80
    assert office.read_legacy_kern(b"") == {}


# -- Advance tables with their kern pairs ------------------------------------------------


@needs_bundle
def test_a_table_built_from_a_face_carries_its_legacy_pairs():
    """``metrics_from_faces`` reads the legacy ``kern`` table into ``legacy_kerning``, by
    character, every character of a shared glyph included; the old private name works."""
    assert embedded._metrics_for is embedded.metrics_from_faces
    data = (BUNDLE / "Carlito-Regular.ttf").read_bytes()
    plain = embedded.metrics_from_faces({(False, False): data})
    assert plain.legacy_kerning is None and plain.kerning is None and not plain.variable
    face = read_sfnt(data)
    from ooxml_common.fonts.sfnt import _cmap

    glyphs = _cmap(face.tables[b"cmap"])
    kerned = write_sfnt(list(face.tables.items()) + [(b"kern", _kern_table({(glyphs[ord("A")], glyphs[ord("V")]): -80}))])
    table = embedded.metrics_from_faces({(False, False): kerned})
    assert table.legacy_kerning.adjustment("A", "V") == -80
    assert table.kern_table(kerning.POWERPOINT) is table.legacy_kerning
    assert table.kern_table(kerning.FEATURE) is None
    variable = embedded.metrics_from_faces({(False, False): (BUNDLE / "NotoSansJP[wght].ttf").read_bytes()})
    assert variable.variable


@needs_bundle
def test_installed_faces_are_measured_with_their_own_file(places):
    _link(places["bundle"] / "Lato-Regular.ttf", BUNDLE / "Lato-Regular.ttf")
    app = _app(office.POWERPOINT, places["bundle"])
    table = office.metrics("Lato", app)
    assert table is not None and table.widths["W"] > 0
    # A family the generated tables measure as itself keeps its table; another is measured.
    assert office.has_own_table("Calibri") and office.has_own_table("Lato")
    assert not office.has_own_table("Rockwell") and not office.has_own_table("Aptos Narrow")
    assert office.layout_metrics(["Lato", "Calibri", "Absent Sans"], app) == {}
    found = office.layout_metrics(["Lato", "Corporate Sans"], app, measure=lambda family: table)
    assert found == {"corporate sans": table}


def test_css_matching_as_resvg_does():
    class F:
        def __init__(self, css):
            self.css = css

    regular, bold, light = F((400, 5, "normal")), F((700, 5, "normal")), F((300, 5, "normal"))
    assert office.css_match([regular, bold, light], 5, "normal", 400) == [regular]
    assert office.css_match([regular, bold, light], 5, "normal", 600) == [bold]
    assert office.css_match([bold, light], 5, "normal", 400) == [light]
    assert office.weight_order(500, [300, 400, 700]) == [400, 300, 700]
    assert office.CSS_STRETCH[4] == "normal"
