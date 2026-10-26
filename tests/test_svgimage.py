"""An SVG picture's natural size, and its root restated in pixels (``ooxml_common.svgimage``).

The sizes are PowerPoint 16's, measured with pptx2svg's ``tools/make_svg_size_probe.py``:
30 SVG pictures in 2:1 frames, each with a blue square of known side, every one landing
where :func:`natural_size` says (``tools/read_svg_size_probe.py``: 30 of 30).
"""

from __future__ import annotations

import base64
import gzip
import re
import time

import pytest

from ooxml_common import svgimage
from ooxml_common.svgimage import length, natural_size, with_pixel_size, with_pixel_sized_images

NS = 'xmlns="http://www.w3.org/2000/svg"'
BODY = '<rect width="10" height="10" fill="#f00"/><g><path d="M0 0h1"/></g>'


def _attributes(text: str) -> dict[str, str]:
    return dict(re.findall(r'([\w-]+)="([^"]*)"', text))


@pytest.mark.parametrize("value, pixels", [
    ("96", 96), ("96px", 96), ("72pt", 96), ("6pc", 96), ("1in", 96), ("2.54cm", 96),
    ("25.4mm", 96), ("6em", 72), ("12ex", 72), ("0.72e2pt", 96), (".5in", 48),
])
def test_a_length_in_pixels(value, pixels):
    found = length(value)
    assert found is not None and found[1] == "px"
    assert found[0] == pytest.approx(pixels)


def test_a_percentage_is_kept_as_one():
    assert length("50%") == (50.0, "%")


@pytest.mark.parametrize("value", ["6PC", "2IN", " 72pt ", "72 pt", "1Q", "5vw", "auto", ""])
def test_what_powerpoint_does_not_read_is_no_length(value):
    """Measured: an upper-case unit or a space reads as no size at all."""
    assert length(value) is None


@pytest.mark.parametrize("root, size", [
    # With a viewBox: a length is a length; a percentage or nothing is the viewBox's.
    ('width="72pt" height="72pt" viewBox="0 0 20 20"', (96, 96)),
    ('width="2in" height="1in" viewBox="0 0 20 20"', (192, 96)),
    ('width="12em" height="6em" viewBox="0 0 20 20"', (144, 72)),
    ('width="100%" height="50%" viewBox="0 0 20 10"', (20, 10)),
    ('viewBox="0 0 20 10"', (20, 10)),
    ('width="2in" viewBox="0 0 20 10"', (192, 96)),
    ('height="1in" viewBox="0,0,20,10"', (192, 96)),
    ('width="2IN" height="1IN" viewBox="0 0 20 20"', (20, 20)),
    # Without one: a length is a length, a percentage is of 500 px, nothing is 500 px.
    ('width="72pt" height="72pt"', (96, 96)),
    ('width="6em" height="6em"', (72, 72)),
    ('width="6em" height="6em" font-size="20"', (120, 120)),
    ('width="6em" height="6em" style="fill:red; font-size: 20px"', (120, 120)),
    ('width="6em" height="6em" font-size="12pt"', (96, 96)),
    ('width="6em" height="6em" font-size="larger"', (72, 72)),
    ('width="50%" height="50%"', (250, 250)),
    ("", (500, 500)),
    ('width="1in"', (96, 500)),
    ('width=" 72pt " height="72pt"', (500, 96)),
])
def test_the_natural_size_is_powerpoints(root, size):
    assert natural_size(_attributes(root)) == pytest.approx(size)


@pytest.mark.parametrize("root", [
    'width="0" height="10"', 'width="-1in" height="1in"', 'width="0%" height="0%"',
    'viewBox="0 0 0 10"', 'viewBox="0 0 10"', 'viewBox="a b c d"',
])
def test_a_size_nothing_draws_is_left_to_the_rasteriser(root):
    assert natural_size(_attributes(root)) is None


def _rewritten(svg: str | bytes) -> str:
    data = svg.encode() if isinstance(svg, str) else svg
    result = with_pixel_size(data)
    assert result is not None
    return result.decode("utf-8")


@pytest.mark.parametrize("size, width, height", [
    ('width="72pt" height="72pt"', "96", "96"),
    ('width="6pc" height="6pc"', "96", "96"),
    ('width="1in" height="0.5in"', "96", "48"),
    ('width="2.54cm" height="2.54cm"', "96", "96"),
    ('width="25.4mm" height="25.4mm"', "96", "96"),
    ('width="100%" height="100%"', "20", "20"),
    ('width="6em" height="6em"', "72", "72"),
    ("", "20", "20"),
])
def test_the_root_is_restated_in_pixels_and_nothing_else_changes(size, width, height):
    original = f'<svg {NS} {size} viewBox="0 0 20 20" id="art">{BODY}</svg>'
    rewritten = _rewritten(original)
    root = re.match(r"<svg[^>]*>", rewritten).group(0)
    assert f'width="{width}"' in root and f'height="{height}"' in root
    assert 'viewBox="0 0 20 20"' in root and 'id="art"' in root and NS in root
    assert rewritten.endswith(f">{BODY}</svg>")
    assert rewritten.count("width=") == original.count("width=") + (size == "")


def test_a_root_with_no_viewbox_gets_one_of_its_own_size():
    """CairoSVG makes the ``<image>`` the viewport and draws an SVG with no viewBox
    unscaled; with one it scales it, as PowerPoint does."""
    root = re.match(r"<svg[^>]*>", _rewritten(f'<svg {NS} width="1in" height="72pt">{BODY}</svg>'))
    assert root.group(0) == f'<svg {NS} width="96" height="96" viewBox="0 0 96 96">'


def test_an_svg_already_in_pixels_is_left_alone():
    assert with_pixel_size(f'<svg {NS} width="20" height="10px" viewBox="0 0 20 10"/>'.encode()) is None


def test_the_root_keeps_its_prefix_quotes_and_self_closing_form():
    svg = ("<?xml version='1.0'?>\n<!-- art -->\n"
           "<s:svg xmlns:s='http://www.w3.org/2000/svg' data-x='a>b' width='72pt'\n"
           "  height='72pt' viewBox='0 0 1 1'/>")
    assert _rewritten(svg) == ("<?xml version='1.0'?>\n<!-- art -->\n"
                               "<s:svg xmlns:s='http://www.w3.org/2000/svg' data-x='a>b' "
                               'width="96"\n  height="96" viewBox=\'0 0 1 1\'/>')


def test_a_root_with_no_namespace_is_still_an_svg():
    assert 'width="96"' in _rewritten(f'<svg width="1in" height="1in">{BODY}</svg>')


def test_an_external_document_type_is_kept_and_not_fetched():
    svg = ('<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" '
           '"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">'
           f'<svg {NS} width="1in" height="1in" viewBox="0 0 1 1"/>')
    assert _rewritten(svg).startswith("<!DOCTYPE svg PUBLIC")


@pytest.mark.parametrize("svg", [
    f'<!DOCTYPE svg [<!ENTITY c "red">]><svg {NS} width="1in" height="1in"/>',
    f'<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg {NS} width="&x;"/>',
    f'<!DOCTYPE svg [<!ATTLIST svg width CDATA "1in">]><svg {NS}/>',
    '<html xmlns="http://www.w3.org/1999/xhtml" width="1in"/>',
    '<svg xmlns="urn:other" width="1in"/>',
    f'<svg {NS} width="1in"',
    "not markup at all",
    "",
])
def test_what_is_unsafe_or_not_an_svg_is_left_alone(svg):
    assert with_pixel_size(svg.encode()) is None


def test_an_entity_bomb_is_refused_before_it_is_expanded():
    levels = "".join(f'<!ENTITY e{i} "{"&e%d;" % (i - 1) * 10}">' for i in range(1, 10))
    bomb = f'<!DOCTYPE svg [<!ENTITY e0 "lol">{levels}]><svg {NS} width="&e9;"/>'.encode()
    started = time.perf_counter()
    assert with_pixel_size(bomb) is None
    assert time.perf_counter() - started < 1


def test_an_svg_in_another_encoding_comes_back_as_utf8():
    """resvg reads UTF-8 only: a Latin-1 or UTF-16 SVG drew nothing."""
    latin = (f'<?xml version="1.0" encoding="ISO-8859-1"?><svg {NS} width="10" height="10">'
             "<title>caf\xe9</title></svg>").encode("latin-1")
    rewritten = with_pixel_size(latin)
    assert rewritten.startswith(b'<?xml version="1.0" encoding="UTF-8"?>')
    assert "caf\xe9".encode() in rewritten
    utf16 = f'<?xml version="1.0" encoding="UTF-16"?><svg {NS} width="1in" height="1in"/>'
    rewritten = with_pixel_size(utf16.encode("utf-16"))
    assert rewritten.decode("utf-8").endswith('width="96" height="96" viewBox="0 0 96 96"/>')


def test_a_byte_order_mark_is_dropped():
    rewritten = with_pixel_size(b"\xef\xbb\xbf" + f'<svg {NS} width="10" height="10" viewBox="0 0 1 1"/>'.encode())
    assert rewritten == f'<svg {NS} width="10" height="10" viewBox="0 0 1 1"/>'.encode()


def test_an_unknown_encoding_is_left_alone():
    assert with_pixel_size(b'<?xml version="1.0" encoding="x-nonesuch"?><svg/>') is None


def test_gzipped_svg_is_decompressed_and_restated():
    rewritten = with_pixel_size(gzip.compress(f'<svg {NS} width="1in" height="1in"/>'.encode()))
    assert rewritten.startswith(b"<svg") and b'width="96"' in rewritten


def test_a_gzip_bomb_is_left_alone(monkeypatch):
    monkeypatch.setattr(svgimage, "LIMIT", 1000)
    packed = gzip.compress(f'<svg {NS} width="1in">'.encode() + b" " * 5000 + b"</svg>")
    assert len(packed) < 1000
    assert with_pixel_size(packed) is None


def _uri(svg: bytes) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(svg).decode()


def test_every_embedded_svg_in_a_page_is_restated():
    pt = f'<svg {NS} width="72pt" height="72pt" viewBox="0 0 1 1"/>'.encode()
    px = f'<svg {NS} width="96" height="96" viewBox="0 0 1 1"/>'.encode()
    png = "data:image/png;base64,iVBORw0KGgo="
    page = (f'<svg {NS}><image href="{_uri(pt)}"/><image href="{_uri(px)}"/>'
            f'<image href="{png}"/><pattern><image href="{_uri(pt)}"/></pattern></svg>')
    rewritten = with_pixel_sized_images(page)
    uris = re.findall(r'href="([^"]+)"', rewritten)
    assert uris == [_uri(with_pixel_size(pt)), _uri(px), png, _uri(with_pixel_size(pt))]
    assert base64.b64decode(uris[0].split(",")[1]) == (
        f'<svg {NS} width="96" height="96" viewBox="0 0 1 1"/>'.encode())


def test_a_page_with_no_embedded_svg_is_returned_as_it_is():
    page = f'<svg {NS}><rect/></svg>'
    assert with_pixel_sized_images(page) is page


def test_an_undecodable_data_uri_is_left_alone():
    page = '<image href="data:image/svg+xml;base64,AAA="/>'
    assert with_pixel_sized_images(page) == page
