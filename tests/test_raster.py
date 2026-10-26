"""ooxml_common.raster: the contract both renderers rasterise through.

pptx2svg's and docx2svg's ``svg_to_png`` call these, and their PNGs are held byte for byte
by their own suites; here the mechanism is held without either renderer: which backend is
chosen and what is imported to choose it, the options each backend is called with (a
stand-in module records them, so neither backend need be installed), and the passes a page
is drawn in.  The tests that draw for real skip without resvg-py.
"""

from __future__ import annotations

import builtins
import struct
import subprocess
import sys
import types

import pytest

from ooxml_common import raster
from ooxml_common.fonts import rasterdb

TEXTLESS = '<svg xmlns="http://www.w3.org/2000/svg" width="4" height="2"><rect width="4" height="2"/></svg>'


# -- Backends: which, and what is imported to know -----------------------------------------


def test_the_module_imports_with_no_backend_installed():
    """Standard library only: with both backends unimportable it imports, and says none is."""
    code = ("import sys; sys.modules['resvg_py'] = sys.modules['cairosvg'] = None; "
            "from ooxml_common import raster; "
            "print(raster.available_backends(), raster.preferred_backend())")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.split() == ["[]", "None"]


def test_resvg_comes_first():
    assert [name for name, _ in raster.BACKENDS] == ["resvg", "cairosvg"]


@pytest.fixture
def broken_cairo(monkeypatch):
    """cairosvg's wheel without libcairo: importing it raises OSError, not ImportError."""
    real_import = builtins.__import__
    imported: list[str] = []

    def fake_import(name, *args, **kwargs):
        imported.append(name)
        if name == "cairosvg":
            raise OSError('no library called "cairo-2" was found')
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "cairosvg", raising=False)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    return imported


def test_a_backend_that_cannot_load_is_absent_rather_than_fatal(broken_cairo):
    assert raster.importable("cairosvg") is False
    assert "cairosvg" not in raster.available_backends()


def test_the_preferred_backend_imports_nothing_after_it(monkeypatch, broken_cairo):
    monkeypatch.setitem(sys.modules, "resvg_py", types.ModuleType("resvg_py"))
    broken_cairo.clear()
    assert raster.preferred_backend() == "resvg"
    assert "cairosvg" not in broken_cairo


def test_choosing_a_backend(monkeypatch):
    assert raster.choose_backend("cairosvg", none_installed="x") == "cairosvg"
    assert raster.choose_backend("resvg", none_installed="x") == "resvg"
    with pytest.raises(ValueError, match="unknown rasterizer backend: 'pdf'"):
        raster.choose_backend("pdf", none_installed="x")
    monkeypatch.setitem(sys.modules, "resvg_py", None)
    monkeypatch.setitem(sys.modules, "cairosvg", types.ModuleType("cairosvg"))
    assert raster.choose_backend("auto", none_installed="x") == "cairosvg"
    monkeypatch.setitem(sys.modules, "cairosvg", None)
    with pytest.raises(raster.RasterizerNotAvailable, match="install one, please"):
        raster.choose_backend("auto", none_installed="install one, please")


def test_as_bytes_takes_what_resvg_py_has_returned():
    assert raster.as_bytes(b"\x89P") == b"\x89P"
    assert raster.as_bytes(bytearray(b"ab")) == b"ab"
    assert raster.as_bytes([137, 80]) == b"\x89P"
    with pytest.raises(TypeError):
        raster.as_bytes(3)


# -- The call to each backend -------------------------------------------------------------


@pytest.fixture
def fake_resvg(monkeypatch):
    calls: list[dict] = []
    module = types.ModuleType("resvg_py")
    module.svg_to_bytes = lambda **options: calls.append(options) or [137, 80, 78, 71]
    monkeypatch.setitem(sys.modules, "resvg_py", module)
    return calls


def test_resvg_is_called_with_each_option_by_its_own_name(fake_resvg, monkeypatch):
    monkeypatch.setattr(rasterdb, "needed_font_files", lambda *a, **k: None)
    png = raster.render_with_resvg(TEXTLESS, width=40.0, height=20, scale=2, background="#fff",
                                   font_dirs=["/fonts"], font_files=["/a.ttf"], skip_system_fonts=True,
                                   families={"sans_serif_family": "Carlito"})
    assert png == b"\x89PNG"
    assert fake_resvg == [{"svg_string": TEXTLESS, "width": 40, "height": 20, "zoom": 2.0,
                           "background": "#fff", "font_dirs": ["/fonts"], "font_files": ["/a.ttf"],
                           "skip_system_fonts": True, "sans_serif_family": "Carlito"}]


def test_resvg_gets_nothing_it_was_not_asked_for(fake_resvg):
    raster.render_with_resvg(TEXTLESS)
    assert fake_resvg == [{"svg_string": TEXTLESS}]


def test_resvg_is_handed_only_the_files_it_needs(fake_resvg, monkeypatch):
    seen = {}

    def needed(svg, **kwargs):
        seen.update(kwargs)
        return ["/b.ttf"]

    monkeypatch.setattr(rasterdb, "needed_font_files", needed)
    from pathlib import Path

    raster.render_with_resvg(TEXTLESS, font_dirs=[Path("/fonts")], font_files=[Path("/a.ttf")],
                             families={"serif_family": "Tinos"})
    # Paths are handed over as strings; the folders become the files they hold.
    assert seen == {"font_files": [str(Path("/a.ttf"))], "font_dirs": [str(Path("/fonts"))],
                    "system_fonts": True,
                    "families": {"serif_family": "Tinos"}}
    assert fake_resvg[0]["font_files"] == ["/b.ttf"] and "font_dirs" not in fake_resvg[0]


def test_an_svg_without_text_loads_no_font(fake_resvg):
    raster.render_with_resvg(TEXTLESS, font_dirs=["/fonts"], font_files=["/a.ttf"])
    assert fake_resvg == [{"svg_string": TEXTLESS}]


def test_cairosvg_is_called_with_its_own_option_names(monkeypatch):
    calls: list[dict] = []
    module = types.ModuleType("cairosvg")
    module.svg2png = lambda **options: calls.append(options) or b"png"
    monkeypatch.setitem(sys.modules, "cairosvg", module)
    assert raster.render_with_cairosvg(TEXTLESS, width=8.0, height=4, scale=3, background="red") == b"png"
    assert calls == [{"bytestring": TEXTLESS.encode("utf-8"), "output_width": 8, "output_height": 4,
                      "scale": 3.0, "background_color": "red"}]
    raster.render_with_cairosvg(TEXTLESS)
    assert calls[1] == {"bytestring": TEXTLESS.encode("utf-8")}


def test_a_missing_backend_says_how_to_install_it(monkeypatch):
    monkeypatch.setitem(sys.modules, "resvg_py", None)
    monkeypatch.setitem(sys.modules, "cairosvg", None)
    with pytest.raises(raster.RasterizerNotAvailable, match=r"run `pip install them\[png\]`"):
        raster.render_with_resvg(TEXTLESS, not_installed="resvg-py is not installed; run `pip install them[png]`")
    with pytest.raises(raster.RasterizerNotAvailable, match="cairosvg is not installed"):
        raster.render_with_cairosvg(TEXTLESS)


def test_resvg_draws_for_real():
    if not raster.importable("resvg_py"):
        pytest.skip("resvg-py is not installed")
    png = raster.render_with_resvg(TEXTLESS, width=40, background="#00ff00")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", png[16:24]) == (40, 20)


# -- Passes -------------------------------------------------------------------------------

TWO_STACKS = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 20" width="10" height="20">'
              '<clipPath id="c"/><text><tspan font-family="A, serif">a</tspan>'
              '<tspan font-family="B, serif">b</tspan></text></svg>')


def test_pass_zero_hides_the_text_of_later_passes():
    first = raster.pass_svg(TWO_STACKS, {"A, serif": 0, "B, serif": 1}, 0, None)
    assert 'font-family="A, serif">' in first
    assert 'font-family="B, serif" visibility="hidden">' in first


def test_a_later_pass_hides_everything_but_its_own_text_over_the_ones_before():
    later = raster.pass_svg(TWO_STACKS, {"B, serif": 1}, 1, b"\x89PNG")
    assert later.startswith('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 20" '
                            'width="10" height="20" visibility="hidden"><image x="0" y="0" '
                            'width="10" height="20" preserveAspectRatio="none"')
    assert "href=\"data:image/png;base64,iVBORw==\"" in later
    assert 'font-family="A, serif" visibility="hidden">' in later
    assert 'font-family="B, serif" visibility="visible">' in later
    assert '<clipPath visibility="visible" id="c"/>' in later


def test_a_root_without_a_view_box_is_overlaid_at_its_size():
    svg = TWO_STACKS.replace(' viewBox="0 0 10 20"', "")
    later = raster.pass_svg(svg, {"B, serif": 1}, 1, b"png")
    assert '<image x="0" y="0" width="10" height="20"' in later


def test_drawing_in_passes_draws_each_over_the_last():
    seen: list[tuple[int, str]] = []

    def draw(number, document):
        seen.append((number, document))
        return f"pass{number}".encode()

    stacks = {"B, serif": 1}
    assert raster.draw_in_passes(TWO_STACKS, stacks, 2, draw) == b"pass1"
    assert seen[0] == (0, raster.pass_svg(TWO_STACKS, stacks, 0, None))
    assert seen[1] == (1, raster.pass_svg(TWO_STACKS, stacks, 1, b"pass0"))


def test_one_pass_is_the_svg_as_it_is():
    seen = []
    assert raster.draw_in_passes(TWO_STACKS, {}, 1, lambda n, d: seen.append(d) or b"x") == b"x"
    assert seen == [TWO_STACKS]
    with pytest.raises(ValueError):
        raster.draw_in_passes(TWO_STACKS, {}, 0, lambda n, d: b"")


def test_a_text_a_pass_draws_nothing_of_is_left_out():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg"><text visibility="hidden">a<tspan>b</tspan></text>'
           '<text visibility="hidden"><tspan visibility="visible">c</tspan></text>'
           '<text><tspan visibility="hidden">d</tspan></text><text/></svg>')
    assert raster.without_undrawn_text(svg) == (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<text visibility="hidden"><tspan visibility="visible">c</tspan></text><text/></svg>')


@pytest.mark.parametrize("svg", [
    '<svg xmlns="http://www.w3.org/2000/svg"><!-- note --><text visibility="hidden">a</text></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg"><text id="t" visibility="hidden">a</text><use href="#t"/></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg"><text visibility="hidden">a</svg>',
    '<svg xmlns="http://www.w3.org/2000/svg"><g filter="url(#f)"><text visibility="hidden">a</text></g></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg"><defs><text visibility="hidden">a</text></defs></svg>',
])
def test_what_may_still_count_is_kept(svg):
    assert raster.without_undrawn_text(svg) == svg


def test_passes_draw_for_real():
    if not raster.importable("resvg_py"):
        pytest.skip("resvg-py is not installed")
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 4" width="8" height="4">'
           '<rect width="8" height="4" fill="#fff"/><rect width="4" height="4" fill="#f00"/></svg>')
    once = raster.render_with_resvg(svg)
    twice = raster.draw_in_passes(svg, {}, 2, lambda n, d: raster.render_with_resvg(d))
    assert struct.unpack(">II", twice[16:24]) == struct.unpack(">II", once[16:24]) == (8, 4)
