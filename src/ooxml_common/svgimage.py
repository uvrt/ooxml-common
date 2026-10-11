"""An SVG picture's **natural size**, and the same SVG with that size stated in pixels.

A picture can be an SVG: PowerPoint 2016 and later keep an inserted SVG behind
``asvg:svgBlip``, beside the PNG it rasterised from it, and a renderer that can draw SVG
embeds the SVG itself, as an ``<image>`` whose ``href`` is a ``data:image/svg+xml`` URI.
The SVG's root says what size it is -- ``width="72pt"``, ``height="2.54cm"``, a
percentage, nothing at all -- and PowerPoint draws the SVG **at that size, then stretches
the result to the frame**.  The rasterisers a renderer hands its page to read that size
differently, and :func:`with_pixel_sized_images` is what the page goes through first:

* **resvg** (resvg-py 0.5) draws nothing for a root whose size has any unit but ``px`` --
  "SVG has an invalid size" -- so the picture vanished from the PNG without a word.  It
  draws nothing from an SVG that is not UTF-8 either.  Its ``em`` is 16 px, and a root
  with no ``viewBox`` and no usable size is as big as its content.
* **CairoSVG** takes the ``<image>``'s own rectangle as the viewport of an SVG with no
  ``viewBox``, and draws it unscaled there.

:func:`with_pixel_size` restates the root's ``width`` and ``height`` in pixels as
PowerPoint reads them, and gives a root with no ``viewBox`` one of exactly that size
(``0 0 width height``, which draws the same).  Nothing else changes: the rewrite is of
those attributes in the root's start tag, and an SVG that is not UTF-8 is re-encoded.
After it both rasterisers draw every case below as PowerPoint does, but one: CairoSVG
reads no root's ``preserveAspectRatio`` and stretches a ``viewBox`` out of proportion with
the root (PowerPoint letterboxes it), and it ignores a ``viewBox``'s origin in an
embedded SVG.  Neither is a size, and the SVG is left to say what it says.

**What PowerPoint does**, measured on PowerPoint 16 for Mac's PDF export (2026-10-11):
30 SVG pictures in 2:1 frames, each drawing a blue square of known side in user space,
from pptx2svg's ``tools/make_svg_size_probe.py``; ``tools/read_svg_size_probe.py`` finds
all 30 where :func:`natural_size` puts them::

    width, height          with a viewBox                without one
    -------------          --------------                -----------
    px, pt, pc, in, cm,    that length, 96 px to the     that length
    mm, or a bare number   inch
    em, ex                 the root's font-size, 12 px   the same
                           when it states none; ex half
    %, missing or          the viewBox's size; one       500 px; a percentage
    unreadable             length given, the other in    is of 500 px
                           the viewBox's proportions

The ``viewBox`` is then fitted into that size by the root's ``preserveAspectRatio`` (a
2 x 1 inch root over a square ``viewBox`` comes out letterboxed and centred), and the
whole stretched to the frame.  Units are case-sensitive and take no spaces: ``6PC`` and
`` 72pt `` read as no size.  An exponent is read (``0.72e2pt`` is 96 px).  The 12 px
``em`` is not CSS's 16, and the 500 px is not the SVG specification's percentage of the
``<image>``'s rectangle: both are PowerPoint's.  Not measured, and left as they are: a
size of zero or below, which nothing draws, and units PowerPoint was not shown (``Q``,
``vw``), read as no size.

**The SVG is untrusted.**  It is read with expat, no external entity or DTD loaded, only
as far as its root's start tag.  An SVG whose document type has an internal subset --
where entities are declared -- is left exactly as it is, as is one that is not
well-formed that far, whose root is not ``svg`` (in the SVG namespace or none), that is
larger than :data:`LIMIT` (after decompressing a gzipped one), or whose ``viewBox`` is not
four numbers with a positive width and height.
"""

from __future__ import annotations

import base64
import codecs
import gzip
import io
import re
import zlib
from xml.parsers import expat

SVG_NS = "http://www.w3.org/2000/svg"
#: The largest SVG rewritten, in bytes, before and after decompression.
LIMIT = 32 * 1024 * 1024

#: CSS pixels per unit -- 96 to the inch, as an SVG's user unit is.
PIXELS_PER_UNIT = {"": 1.0, "px": 1.0, "pt": 96 / 72, "pc": 16.0, "in": 96.0,
                   "cm": 96 / 2.54, "mm": 96 / 25.4}
#: A root's font-size when it states none, in px: what PowerPoint resolves ``em`` against.
DEFAULT_FONT_SIZE = 12.0
#: The side of a root with no ``viewBox`` and no readable length, in px; a percentage is
#: of this.  PowerPoint's, measured; not the SVG specification's.
DEFAULT_SIDE = 500.0

_NUMBER = r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?"
_LENGTH = re.compile(rf"({_NUMBER})(px|pt|pc|in|cm|mm|em|ex|%)?")
_FONT_SIZE_DECL = re.compile(r"(?:^|;)\s*font-size\s*:\s*([^;!]+?)\s*(?:!important\s*)?(?:;|$)")
_DECLARATION = re.compile(rb"\A<\?xml[^>]*\?>")
_ENCODING = re.compile(rb"""\A<\?xml[^>]*?encoding\s*=\s*["']([A-Za-z0-9._-]+)["']""")
_ATTRIBUTE = re.compile(r"""\s*([^\s=/>]+)\s*=\s*("[^"]*"|'[^']*')""")
_DATA_URI = re.compile(r"data:image/svg\+xml;base64,([A-Za-z0-9+/=]+)")

#: Rewritten SVGs by their base64 text: a deck repeats its pictures across slides.
_CACHE: dict[str, str | None] = {}
_CACHE_LIMIT = 64


class _Refused(Exception):
    """The SVG is one this module leaves alone."""


class _Root(Exception):
    """Raised from expat's start handler: the root has been read, parsing can stop."""

    def __init__(self, name: str, attributes: dict[str, str], offset: int):
        self.name, self.attributes, self.offset = name, attributes, offset


def length(value: str | None, font_size: float = DEFAULT_FONT_SIZE) -> tuple[float, str] | None:
    """A root's ``width`` or ``height`` as PowerPoint reads it: ``(pixels, "px")``,
    ``(percent, "%")``, or ``None`` when it is absent or unreadable."""
    if value is None:
        return None
    match = _LENGTH.fullmatch(value)
    if match is None:
        return None
    number, unit = float(match.group(1)), match.group(2) or ""
    if unit == "%":
        return number, "%"
    if unit == "em":
        return number * font_size, "px"
    if unit == "ex":
        return number * font_size / 2, "px"
    return number * PIXELS_PER_UNIT[unit], "px"


def _font_size(attributes: dict[str, str]) -> float:
    """The root's own font-size in px, from its ``style`` or its attribute, when it states
    an absolute one; else :data:`DEFAULT_FONT_SIZE`."""
    stated = None
    style = attributes.get("style")
    if style:
        found = _FONT_SIZE_DECL.search(style)
        stated = found.group(1) if found else None
    if stated is None:
        stated = attributes.get("font-size")
    if stated is not None:
        match = _LENGTH.fullmatch(stated.strip())
        if match is not None and (match.group(2) or "") in PIXELS_PER_UNIT:
            size = float(match.group(1)) * PIXELS_PER_UNIT[match.group(2) or ""]
            if size > 0:
                return size
    return DEFAULT_FONT_SIZE


def view_box(value: str | None) -> tuple[float, float, float, float] | None:
    """A ``viewBox``'s four numbers, or ``None`` when absent; a ``ValueError`` when it is
    stated but unusable (not four numbers, or a width or height of zero or below)."""
    if value is None:
        return None
    parts = [part for part in re.split(r"[\s,]+", value.strip()) if part]
    if len(parts) != 4 or not all(re.fullmatch(_NUMBER, part) for part in parts):
        raise ValueError(f"unusable viewBox {value!r}")
    box = tuple(float(part) for part in parts)
    if box[2] <= 0 or box[3] <= 0:
        raise ValueError(f"unusable viewBox {value!r}")
    return box  # type: ignore[return-value]


def natural_size(attributes: dict[str, str]) -> tuple[float, float] | None:
    """The size PowerPoint draws an SVG at before stretching it to its frame, in px, from
    its root's attributes (the table in the module docstring); ``None`` for a size of
    zero or below, or an unusable ``viewBox``, which are left to the rasteriser."""
    try:
        box = view_box(attributes.get("viewBox"))
    except ValueError:
        return None
    font_size = _font_size(attributes)
    width, height = (length(attributes.get(name), font_size) for name in ("width", "height"))
    if any(side is not None and side[1] == "px" and side[0] <= 0 for side in (width, height)):
        return None
    if box is not None:
        absolute_w = width[0] if width is not None and width[1] == "px" else None
        absolute_h = height[0] if height is not None and height[1] == "px" else None
        if absolute_w is not None and absolute_h is not None:
            return absolute_w, absolute_h
        if absolute_w is not None:
            return absolute_w, absolute_w * box[3] / box[2]
        if absolute_h is not None:
            return absolute_h * box[2] / box[3], absolute_h
        return box[2], box[3]
    sides = []
    for side in (width, height):
        if side is None:
            sides.append(DEFAULT_SIDE)
        elif side[1] == "px":
            sides.append(side[0])
        elif side[0] > 0:
            sides.append(DEFAULT_SIDE * side[0] / 100)
        else:
            return None
    return sides[0], sides[1]


def _number(value: float) -> str:
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _decoded(data: bytes) -> bytes:
    """``data`` as UTF-8, from what its byte-order mark or declaration says it is, with a
    declaration that says UTF-8; a ``_Refused`` for an encoding Python does not know."""
    encoding = None
    for mark, name in ((codecs.BOM_UTF32_LE, "utf-32"), (codecs.BOM_UTF32_BE, "utf-32"),
                       (codecs.BOM_UTF8, "utf-8-sig"), (codecs.BOM_UTF16_LE, "utf-16"),
                       (codecs.BOM_UTF16_BE, "utf-16")):
        if data.startswith(mark):
            encoding = name
            break
    if encoding is None:
        if data.startswith(b"<\x00?\x00"):
            encoding = "utf-16-le"
        elif data.startswith(b"\x00<\x00?"):
            encoding = "utf-16-be"
        else:
            declared = _ENCODING.match(data)
            encoding = declared.group(1).decode("ascii") if declared else "utf-8"
    try:
        info = codecs.lookup(encoding)
        if info.name == "utf-8" and not data.startswith(codecs.BOM_UTF8):
            data.decode("utf-8")
            return data
        text = data.decode(encoding)
    except (LookupError, UnicodeDecodeError) as error:
        raise _Refused(str(error)) from error
    raw = text.lstrip("\ufeff").encode("utf-8")
    return _DECLARATION.sub(b'<?xml version="1.0" encoding="UTF-8"?>', raw, count=1)


def _root(data: bytes) -> _Root:
    """The root's qualified name, attributes and byte offset, read with expat: no DTD, no
    entity, nothing past the root's start tag."""
    parser = expat.ParserCreate(namespace_separator=" ")
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)

    def doctype(name, system_id, public_id, has_internal_subset):
        if has_internal_subset:
            raise _Refused("a document type with an internal subset")

    def entity(*_args):
        raise _Refused("an entity declaration")

    def start(name, attributes):
        raise _Root(name, attributes, parser.CurrentByteIndex)

    def external(*_args):
        raise _Refused("an external entity")

    parser.StartDoctypeDeclHandler = doctype
    parser.EntityDeclHandler = entity
    parser.UnparsedEntityDeclHandler = entity
    parser.ExternalEntityRefHandler = external
    parser.StartElementHandler = start
    try:
        parser.Parse(data, True)
    except _Root as root:
        return root
    except expat.ExpatError as error:
        raise _Refused(str(error)) from error
    raise _Refused("no root element")


def _start_tag_end(text: bytes, offset: int) -> int:
    """The index just past the ``>`` closing the start tag at ``offset``."""
    quote = None
    for index in range(offset + 1, len(text)):
        char = text[index]
        if quote is not None:
            if char == quote:
                quote = None
        elif char in (0x22, 0x27):
            quote = char
        elif char == 0x3E:
            return index + 1
    raise _Refused("an unterminated start tag")


def _states(attributes: dict[str, str], width: float, height: float) -> bool:
    """Whether the root already says ``width`` x ``height`` in pixels."""
    def pixels(value: str | None) -> float | None:
        match = _LENGTH.fullmatch(value or "")
        return float(match.group(1)) if match and match.group(2) in (None, "px") else None

    return pixels(attributes.get("width")) == width and pixels(attributes.get("height")) == height


def with_pixel_size(data: bytes) -> bytes | None:
    """``data``, an SVG, with its root's ``width`` and ``height`` restated in pixels as
    PowerPoint reads them, and a ``viewBox`` of that size when it has none (module
    docstring); ``None`` when it is left alone -- unsafe, unreadable, or already so."""
    if len(data) > LIMIT:
        return None
    try:
        if data[:2] == b"\x1f\x8b":
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as packed:
                data = packed.read(LIMIT + 1)
            if len(data) > LIMIT:
                return None
        utf8 = _decoded(data)
        root = _root(utf8)
    except (_Refused, OSError, EOFError, zlib.error):
        return None
    local = root.name.rsplit(" ", 1)[-1]
    namespace = root.name.rsplit(" ", 1)[0] if " " in root.name else None
    if local != "svg" or namespace not in (SVG_NS, None):
        return None
    size = natural_size(root.attributes)
    if size is None:
        return None
    width, height = size
    stated_box = view_box(root.attributes.get("viewBox"))
    stated = {"width": _number(width), "height": _number(height)}
    if stated_box is None:
        stated["viewBox"] = f"0 0 {stated['width']} {stated['height']}"
    if utf8 is data and stated_box is not None and _states(root.attributes, width, height):
        return None

    start = root.offset
    try:
        end = _start_tag_end(utf8, start)
    except _Refused:
        return None
    tag = utf8[start:end].decode("utf-8")
    closing = "/>" if tag.endswith("/>") else ">"
    body = tag[1:len(tag) - len(closing)]
    name_end = re.match(r"[^\s/>]+", body).end()  # type: ignore[union-attr]
    # Each attribute where it stood, the two restated in place; what was missing at the end.
    attributes = []
    for match in _ATTRIBUTE.finditer(body, name_end):
        name = match.group(1)
        if name in stated:
            attributes.append(f'{match.group(0)[:match.start(2) - match.start(0)]}'
                              f'"{stated.pop(name)}"')
        else:
            attributes.append(match.group(0))
    attributes.extend(f' {name}="{value}"' for name, value in stated.items())
    rebuilt = f"<{body[:name_end]}{''.join(attributes)}{closing}"
    return utf8[:start] + rebuilt.encode("utf-8") + utf8[end:]


def with_pixel_sized_images(svg: str) -> str:
    """``svg`` with every ``data:image/svg+xml;base64,`` picture in it passed through
    :func:`with_pixel_size` -- what a page goes through before a rasteriser draws it."""
    if "data:image/svg+xml;base64," not in svg:
        return svg

    def replace(match: re.Match) -> str:
        encoded = match.group(1)
        if encoded not in _CACHE:
            if len(_CACHE) >= _CACHE_LIMIT:
                _CACHE.clear()
            try:
                rewritten = with_pixel_size(base64.b64decode(encoded, validate=True))
            except ValueError:
                rewritten = None
            _CACHE[encoded] = (None if rewritten is None
                               else base64.b64encode(rewritten).decode("ascii"))
        found = _CACHE[encoded]
        return match.group(0) if found is None else f"data:image/svg+xml;base64,{found}"

    return _DATA_URI.sub(replace, svg)
