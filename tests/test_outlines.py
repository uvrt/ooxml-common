"""Text as outlines (``ooxml_common.outlines``): the paths resvg would draw.

The bundle's faces (``pptx2svg-fonts``) are the fonts; the tests that need them skip
without it.  Where resvg-py is installed, an outlined SVG is rasterised against the
same SVG with its text and the two PNGs must be the same bytes: resvg draws both, the
one shaping and placing the glyphs itself, the other drawing the paths this package
made.  Made-up text only.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ooxml_common.fonts import bundle_dir
from ooxml_common.outlines import FontSetup, outline_text
from ooxml_common.outlines.face import load_face, path_data
from ooxml_common.outlines.fontdb import database, parse_families
from ooxml_common.outlines.shaper import shape, shapeable

BUNDLE = bundle_dir()
needs_bundle = pytest.mark.skipif(BUNDLE is None, reason="pptx2svg-fonts is not installed")
GENERIC = {"sans_serif_family": "Carlito", "serif_family": "Tinos", "monospace_family": "Cousine"}


def _setup() -> FontSetup:
    assert BUNDLE is not None
    return FontSetup.of(sorted(str(p) for p in Path(BUNDLE).glob("*.ttf")), (), False, GENERIC)


def _svg(body: str, defs: str = "") -> str:
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="600" height="100" viewBox="0 0 600 100">'
            f'{defs}<rect width="600" height="100" fill="#fff"/>{body}</svg>')


def _png(svg: str) -> bytes:
    resvg_py = pytest.importorskip("resvg_py")
    setup = _setup()
    return bytes(resvg_py.svg_to_bytes(svg_string=svg, font_files=list(setup.font_files), skip_system_fonts=True,
                                       zoom=2, **GENERIC))


# --------------------------------------------------------------------------------------
# Path data
# --------------------------------------------------------------------------------------

def test_path_data_is_relative_and_rounded_once():
    commands = [("M", 10, 20), ("L", 30, 20), ("L", 30, 50), ("Q", 40, 60, 50.5, 50), ("Z",),
                ("M", 0, 0), ("L", 1.0004, 2), ("Z",)]
    # Font units are y up; the path is y down.
    assert path_data(commands, 1.0, 1.0) == "M10-20h20v-30q10-10 20.5 0zm-10 20l1-2z"


def test_numbers_are_separated_only_where_they_would_run_together():
    commands = [("M", 0.5, 0), ("L", 1, 0.5), ("Z",)]
    assert path_data(commands, 1.0, 1.0) == "M.5 0l.5-.5z"


# --------------------------------------------------------------------------------------
# Faces, the database, shaping
# --------------------------------------------------------------------------------------

def test_font_families_parse_as_svgtypes_does():
    assert parse_families("'Aptos Display', Aptos,  Some   Face , sans-serif") == [
        ("Aptos Display", False), ("Aptos", False), ("Some Face", False), ("sans-serif", True)]


@needs_bundle
def test_a_run_is_drawn_in_the_first_family_any_face_answers_to():
    db = database(_setup())
    face = db.query("Nowhere, Carlito, sans-serif", 700, 5, "normal")
    assert face is not None and Path(face.path).name == "Carlito-Bold.ttf"
    # No family of the stack is loaded: the generic keyword's face, then serif's.
    assert Path(db.query("Nowhere", 400, 5, "normal").path).name == "Tinos-Regular.ttf"
    assert Path(db.query("Nowhere, sans-serif", 400, 5, "italic").path).name == "Carlito-Italic.ttf"


@needs_bundle
def test_a_character_its_face_lacks_falls_back_to_the_first_loaded_face_that_has_it():
    db = database(_setup())
    base = db.query("Carlito", 400, 5, "normal")
    fallback = db.fallback(ord("日"), [base])
    assert fallback is not None and "NotoSansJP" in Path(fallback.path).name


@needs_bundle
def test_kerning_and_ligatures_are_applied():
    face = load_face(str(Path(BUNDLE) / "Carlito-Regular.ttf"), 0)
    assert face is not None
    av = shape(face, "AV")
    plain = [face.advance(face.glyph(ord(c))) for c in "AV"]
    assert av[0].x_advance < plain[0]                  # the pair is kerned
    assert [g.x_advance for g in shape(face, "AV", kerning=False)] == plain
    fi = shape(face, "fi")
    assert len(fi) == 1 and fi[0].id != face.glyph(ord("f"))   # one ligature glyph


@needs_bundle
def test_a_variable_face_is_drawn_at_the_weight_asked_for():
    face = load_face(str(Path(BUNDLE) / "Arimo[wght].ttf"), 0)
    assert face is not None
    bold = face.coordinates([(b"wght", 700.0)])
    assert bold and bold[0] > 0
    gid = face.glyph(ord("m"))
    assert face.advance(gid, bold) > face.advance(gid)
    assert face.outline(gid, bold) != face.outline(gid)


def test_complex_scripts_are_not_shaped_here():
    assert shapeable("Plain text, 日本語, Ελληνικά")
    assert not shapeable("שלום")
    assert not shapeable("مرحبا")
    assert not shapeable("नमस्ते")


# --------------------------------------------------------------------------------------
# The document
# --------------------------------------------------------------------------------------

CASES = [
    '<text x="10" y="60" font-family="Carlito" font-size="40">Hamburgefonstiv AVATAR fi ffl</text>',
    '<text x="10" y="60" font-family="Arimo" font-size="40" font-weight="bold">Bold variable Wave</text>',
    '<text x="10" y="60" font-family="Raleway" font-size="40" font-weight="300">Light Raleway fi</text>',
    '<text x="300" y="60" font-family="Lato" font-size="30" text-anchor="middle" fill="#c00">Centred '
    '<tspan font-weight="bold" fill="#00c">bold</tspan> mix</text>',
    '<text x="10" y="60" font-family="Carlito, sans-serif" font-size="30">日本語 mixed テキスト</text>',
    '<text x="10" y="60" xml:space="preserve" font-family="Tinos" font-size="30"><tspan x="10" '
    'text-decoration="underline">Under line</tspan><tspan x="200" font-style="italic" '
    'text-decoration="line-through">struck</tspan></text>',
    '<g transform="translate(20 0) rotate(3)"><text x="10" y="60" font-family="Lato" font-size="36" '
    'opacity="0.7">In a group</text></g>',
]


@needs_bundle
@pytest.mark.parametrize("body", CASES)
def test_the_outlines_draw_the_pixels_the_text_draws(body):
    svg = _svg(body)
    outlined = outline_text(svg, _setup())
    assert outlined.kept == [] and "<text" not in outlined.svg
    assert _png(outlined.svg) == _png(svg)


@needs_bundle
def test_a_gradient_is_spread_over_the_text_box():
    defs = ('<defs><linearGradient id="fade"><stop offset="0" stop-color="#f00"/>'
            '<stop offset="1" stop-color="#00f"/></linearGradient></defs>')
    svg = _svg('<text x="10" y="60" font-family="Lato" font-size="40" fill="url(#fade)">A gradient</text>', defs)
    outlined = outline_text(svg, _setup())
    # Restated in user space over the text's box, not left to the outlines' own box
    # (pptx2svg's tests hold the pixels: within a sixteenth on a few edge pixels).
    found = re.search(r'<linearGradient[^>]*id="fade-t[^"]*"[^>]*>', outlined.svg)
    assert found and 'gradientUnits="userSpaceOnUse"' in found.group(0) and 'x2="1"' in found.group(0)


@needs_bundle
def test_repeated_glyphs_are_one_definition_each():
    svg = _svg('<text x="10" y="40" font-family="Carlito" font-size="20">aaaa</text>'
               '<text x="10" y="80" font-family="Carlito" font-size="30">aa</text>')
    outlined = outline_text(svg, _setup())
    assert outlined.svg.count("<path id=") == 1
    assert outlined.svg.count("<use ") == 6
    # Definitions are named by face, glyph and instance: the same text draws the same bytes.
    assert outline_text(svg, _setup()).svg == outlined.svg


@needs_bundle
def test_selectable_text_is_kept_transparent_over_the_outlines():
    svg = _svg('<text x="10" y="60" font-family="Carlito" font-size="40" fill="#123456">Find me</text>')
    outlined = outline_text(svg, _setup(), selectable=True)
    assert 'aria-hidden="true"' in outlined.svg
    layer = re.search(r"<text[^>]*>Find me</text>", outlined.svg)
    assert layer and 'fill-opacity="0"' in layer.group(0) and "data-text-layer" in layer.group(0)
    assert _png(outlined.svg) == _png(svg)


@needs_bundle
@pytest.mark.parametrize("body, reason", [
    ('<text x="10" y="60" font-family="Carlito" font-size="30">שלום</text>', "complex-script"),
    ('<text x="10" y="60" font-family="Carlito" font-size="30" rotate="10">Turned</text>', "rotate"),
    ('<text x="10" y="60" font-family="Carlito" writing-mode="tb" font-size="30">Down</text>', "vertical"),
])
def test_what_is_not_drawn_as_resvg_would_stays_text(body, reason):
    svg = _svg(body)
    outlined = outline_text(svg, _setup())
    assert outlined.svg == svg
    assert len(outlined.kept) == 1 and reason in outlined.kept[0].reason


def test_a_style_sheet_keeps_every_text():
    svg = _svg('<style>text { font-size: 30px }</style><text x="10" y="60">Styled</text>')
    outlined = outline_text(svg, FontSetup.of((), (), False))
    assert outlined.svg == svg and outlined.kept


def test_an_svg_without_text_is_returned_as_it_is():
    svg = _svg('<rect x="1" y="1" width="2" height="2"/>')
    assert outline_text(svg, FontSetup.of((), (), False)).svg is svg


# --------------------------------------------------------------------------------------
# More of usvg's layout and harfrust's shaping, against resvg's pixels
# --------------------------------------------------------------------------------------

def _decoded(png: bytes) -> list[bytes]:
    """The rows of a PNG as resvg writes it (8-bit RGBA, not interlaced), unfiltered."""
    import struct
    import zlib

    width, height, depth, colour = struct.unpack(">IIBB", png[16:26])
    assert (depth, colour) == (8, 6)
    data, at = b"", 8
    while at < len(png):
        length, kind = struct.unpack(">I4s", png[at:at + 8])
        if kind == b"IDAT":
            data += png[at + 8:at + 8 + length]
        at += 12 + length
    raw, stride, rows, previous = zlib.decompress(data), width * 4, [], bytes(width * 4)
    for y in range(height):
        kind, line = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for x in range(stride):
            left = line[x - 4] if x >= 4 else 0
            up, corner = previous[x], previous[x - 4] if x >= 4 else 0
            if kind == 1:
                line[x] = (line[x] + left) & 255
            elif kind == 2:
                line[x] = (line[x] + up) & 255
            elif kind == 3:
                line[x] = (line[x] + (left + up) // 2) & 255
            elif kind == 4:
                estimate = left + up - corner
                pa, pb, pc = abs(estimate - left), abs(estimate - up), abs(estimate - corner)
                line[x] = (line[x] + (left if pa <= pb and pa <= pc else up if pb <= pc else corner)) & 255
        rows.append(bytes(line))
        previous = line
    return rows


def _worst(a: bytes, b: bytes) -> int:
    """The largest difference of one channel of one pixel between two PNGs."""
    if a == b:
        return 0
    return max(abs(x - y) for left, right in zip(_decoded(a), _decoded(b)) for x, y in zip(left, right))


MORE = [
    # Marks positioned on their bases, and composed forms.
    '<text x="10" y="60" font-family="Arimo" font-size="36">Véronique näive café</text>',
    '<text x="10" y="60" font-family="Lato" font-size="36">office affluent fjord Th</text>',
    # Marks with no composed form: attached by GPOS (mark-to-base, mark-to-mark), and
    # decomposed in a contextual substitution.
    *(f'<text x="10" y="60" font-family="{family}" font-size="40">q\u0301 x\u0308\u0301 g\u0323 Ka\u0300</text>'
      for family in ("Arimo", "Lato", "Tinos", "Raleway", "Caladea")),
    # Spaces the face may lack, drawn at HarfBuzz's widths; default ignorables hidden.
    *(f'<text x="10" y="60" xml:space="preserve" font-family="{family}" font-size="30">'
      'a\u2003b\u2009c\u200ad\u2007e\u202ff\u200bg\u00adh\u2060i</text>' for family in ("Cousine", "Carlito")),
    '<text x="10" y="60" font-family="Carlito" font-size="30">Ελληνικά Кириллица ﬁ ½ ‰</text>',
    '<text x="10" y="60" font-family="Noto Sans JP" font-size="28" font-weight="bold">「日本語」ですか？ｶﾀｶﾅ</text>',
    # Spacing and lengths.
    '<text x="10" y="60" font-family="Carlito" font-size="30" letter-spacing="3" word-spacing="9">Spaced out words</text>',
    '<text x="10" y="60" font-family="Carlito" font-size="30" textLength="400">Stretched by spacing</text>',
    '<text x="10" y="60" font-family="Carlito" font-size="30" textLength="400" lengthAdjust="spacingAndGlyphs">'
    'Stretched glyphs</text>',
    '<text x="10" y="60" dx="0 4 8" dy="0 -5 5" font-family="Tinos" font-size="30">Shifted letters</text>',
    '<text x="10" y="60" font-family="Tinos" font-size="30">H<tspan baseline-shift="sub" font-size="18">2</tspan>O '
    'x<tspan baseline-shift="30%">n</tspan> <tspan baseline-shift="-4">low</tspan></text>',
    # Whitespace, links, visibility, paint.
    '<text x="10" y="60" font-family="Carlito" font-size="30">  Collapsed   <tspan> spaces </tspan>  here  </text>',
    '<text x="10" y="60" font-family="Carlito" font-size="30"><a href="https://example.com/x">Linked</a> '
    '<tspan visibility="hidden">gone</tspan> <tspan fill="none" stroke="#080" stroke-width="1.2">hollow</tspan> '
    '<tspan fill-opacity="0.4">faint</tspan></text>',
    '<text x="590" y="60" font-family="Cousine, monospace" font-size="24" text-anchor="end" font-kerning="none">'
    'AVAT <tspan text-decoration="overline underline">To</tspan> end</text>',
]


@needs_bundle
@pytest.mark.parametrize("body", MORE)
def test_more_layout_and_shaping_draws_the_pixels_the_text_draws(body):
    svg = _svg(body)
    outlined = outline_text(svg, _setup())
    assert outlined.kept == [] and "<text" not in outlined.svg
    assert _worst(_png(outlined.svg), _png(svg)) <= 64


# --------------------------------------------------------------------------------------
# CFF outlines, from a made-up face
# --------------------------------------------------------------------------------------

def _cff_face(path: Path) -> None:
    """A made-up CFF face, "Made Up Sans": a box, a diamond, a curved glyph and a space."""
    fontbuilder = pytest.importorskip("fontTools.fontBuilder")
    from fontTools.pens.t2CharStringPen import T2CharStringPen

    names = [".notdef", "space", "A", "B", "C"]
    builder = fontbuilder.FontBuilder(1000, isTTF=False)
    builder.setupGlyphOrder(names)
    builder.setupCharacterMap({0x20: "space", 0x41: "A", 0x42: "B", 0x43: "C"})
    advances = {".notdef": 500, "space": 250, "A": 600, "B": 640, "C": 700}
    charstrings = {}
    for name in names:
        pen = T2CharStringPen(advances[name], None)
        if name in (".notdef", "A"):
            pen.moveTo((50, 0)); pen.lineTo((450, 0)); pen.lineTo((450, 700)); pen.lineTo((50, 700)); pen.closePath()
            pen.moveTo((150, 100)); pen.lineTo((150, 600)); pen.lineTo((350, 600)); pen.lineTo((350, 100)); pen.closePath()
        elif name == "B":
            pen.moveTo((320, 0)); pen.lineTo((620, 350)); pen.lineTo((320, 700)); pen.lineTo((20, 350)); pen.closePath()
        elif name == "C":
            pen.moveTo((650, 100)); pen.curveTo((500, -20), (100, -20), (60, 350))
            pen.curveTo((100, 720), (500, 720), (650, 600)); pen.lineTo((600, 560))
            pen.curveTo((480, 650), (170, 650), (140, 350)); pen.curveTo((170, 50), (480, 50), (600, 140))
            pen.closePath()
        charstrings[name] = pen.getCharString()
    builder.setupCFF("MadeUpSans-Regular", {"FullName": "Made Up Sans"}, charstrings, {})
    builder.setupHorizontalMetrics({name: (advances[name], 0) for name in names})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "Made Up Sans", "styleName": "Regular"})
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
    builder.setupPost()
    builder.save(str(path))


def test_cff_outlines_are_the_charstrings_drawn(tmp_path):
    font = tmp_path / "made-up-sans.otf"
    _cff_face(font)
    from fontTools.pens.recordingPen import RecordingPen
    from fontTools.ttLib import TTFont

    ours = load_face(str(font), 0)
    assert ours is not None and ours.unsupported is None
    reference = TTFont(str(font))
    glyphs = reference.getGlyphSet()
    for name in ("A", "B", "C"):
        pen = RecordingPen()
        glyphs[name].draw(pen)
        expected = []
        for op, points in pen.value:
            if op == "closePath":
                expected.append(("Z",))
            else:
                expected.append(({"moveTo": "M", "lineTo": "L", "curveTo": "C"}[op],
                                 *[float(v) for point in points for v in point]))
        drawn = ours.outline(reference.getGlyphID(name))
        assert [(c[0], *[round(v, 3) for v in c[1:]]) for c in drawn] == \
            [(c[0], *[round(v, 3) for v in c[1:]]) for c in expected]


#: A CID-keyed CFF face (subroutines, hint masks, a collection) where macOS has it.
SYSTEM_CFF = Path("/System/Library/Fonts/AppleSDGothicNeo.ttc")


@pytest.mark.skipif(not SYSTEM_CFF.is_file(), reason="no CID-keyed CFF face on this machine")
def test_a_cff_face_outlined_draws_the_pixels_its_text_draws():
    resvg_py = pytest.importorskip("resvg_py")
    svg = _svg('<text x="10" y="70" font-family="Apple SD Gothic Neo" font-size="40">한국어 Hello fi</text>')
    outlined = outline_text(svg, FontSetup.of([str(SYSTEM_CFF)], (), False))
    assert outlined.kept == [] and "<text" not in outlined.svg

    def draw(document: str) -> bytes:
        return bytes(resvg_py.svg_to_bytes(svg_string=document, font_files=[str(SYSTEM_CFF)], skip_system_fonts=True))

    assert draw(outlined.svg) == draw(svg)
