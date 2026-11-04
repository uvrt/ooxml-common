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
