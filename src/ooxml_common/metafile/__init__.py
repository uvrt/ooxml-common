"""EMF and WMF pictures drawn from their GDI records, as SVG.

PowerPoint and Word keep pasted vector artwork, clip art and many templates' decorations
as Enhanced (or Windows) Metafiles: lists of GDI calls.  :func:`metafile_to_svg` plays
those calls -- pens, brushes, lines, polygons, rectangles, ellipses, arcs, paths, clips,
mapping modes and world transforms, bitmaps, text -- into one SVG document whose
``viewBox`` is the picture's frame, to be drawn stretched over the picture's box
(``preserveAspectRatio="none"``, as Office stretches a metafile).

Windows PowerPoint is the reference (round 7; PowerPoint for Mac's metafile player is a
reimplementation that differs from it -- null pens, fill modes, palettes, dashes,
rotated text -- and from the file's GDI meaning):
:mod:`.gdi` and :mod:`.emfplus` list what was measured.  An EMF+ file -- dual or not --
is drawn from its EMF+ records, as Windows draws it, its GDI records skipped but those
after an ``EmfPlusGetDC``; :attr:`MetafileDrawing.emf_plus` reports one.

* :mod:`.gdi` -- the device context and the SVG it draws;
* :mod:`.emf` -- the EMF record reader;
* :mod:`.emfplus` -- the EMF+ records an EMF's comments carry;
* :mod:`.wmf` -- the WMF record reader (placeable or not);
* :mod:`.dib` -- device-independent bitmaps to PNG (moved from pptx2svg).

The input is untrusted: sizes, record counts, objects, points, output and decoded pixels
are capped, every read is bounds-checked, and nothing here raises for any bytes.
"""

from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass

from . import emf as _emf
from . import wmf as _wmf
from .gdi import MARKER

__all__ = ["MetafileDrawing", "inline_metafile_images", "metafile_to_svg"]


@dataclass(frozen=True)
class MetafileDrawing:
    """A metafile drawn as SVG, and what was left out."""

    #: A standalone SVG document, UTF-8.
    svg: bytes
    #: The picture's own size in pixels at 96 to the inch (an EMF's frame, a placeable
    #: WMF's box).
    width: float
    height: float
    #: What was not drawn (or drawn approximately), by record or reason, with counts.
    skipped: tuple[tuple[str, int], ...] = ()
    #: The file carries EMF+ records, and they are what was drawn (its GDI records only
    #: after an ``EmfPlusGetDC``).
    emf_plus: bool = False
    #: Its EMF+ records drew nothing, so its GDI records were drawn instead.
    gdi_fallback: bool = False
    #: A cap stopped the playback before the end of the file.
    truncated: bool = False
    #: How many elements were drawn; ``0`` when the metafile draws nothing this player
    #: draws (an EMF+-only file, a file of skipped records), and the caller draws its
    #: placeholder.
    drawn: int = 0

    @property
    def complete(self) -> bool:
        """Every record was understood: nothing skipped, not drawn from an EMF+ file's GDI
        fallback, not truncated."""
        return not self.skipped and not self.gdi_fallback and not self.truncated

    def warning(self) -> str | None:
        """One sentence naming what was not drawn, or ``None`` when everything was."""
        parts = []
        if self.skipped:
            parts.append("not drawn: " + ", ".join(f"{name} (x{count})" if count > 1 else name
                                                   for name, count in self.skipped))
        if self.gdi_fallback:
            parts.append("its EMF+ records draw nothing, so its GDI records are drawn instead (Windows draws "
                         "only the EMF+ records)")
        if self.truncated:
            parts.append("it is larger than the player's limits, so the rest of it is not drawn")
        return "; ".join(parts) or None


def metafile_to_svg(data: bytes, *, font_mapping: dict[str, str] | None = None) -> MetafileDrawing | None:
    """Draw EMF or WMF bytes as SVG, or ``None`` when they are neither (or unreadable).

    A metafile that draws nothing comes back with :attr:`MetafileDrawing.drawn` 0, so
    that :meth:`MetafileDrawing.warning` can still say why.

    ``font_mapping`` is the renderer's font substitution map
    (:data:`ooxml_common.text.fontmap.DEFAULT_FONT_MAPPING` when ``None``), so that a
    metafile's text names the faces the rest of the page is drawn in.
    """
    try:
        return _draw(bytes(data), font_mapping)
    except Exception:  # hostile bytes must never take the conversion down
        return None


def _draw(data: bytes, font_mapping, *, nesting: int = 0) -> MetafileDrawing | None:
    """The drawing; ``nesting`` counts the EMF+ metafile images this one is inside."""
    prefix = "m" + hashlib.sha1(data).hexdigest()[:10] + "-"
    fallback = False
    if _emf.is_emf(data):
        played = _emf.play(data, font_mapping=font_mapping, nesting=nesting)
        if played is None:
            return None
        player, header, emf_plus = played
        if emf_plus and not player.drawn and not player.truncated:
            again = _emf.play(data, font_mapping=font_mapping, gdi_only=True, nesting=nesting)
            if again is not None and again[0].drawn:
                player, fallback = again[0], True
        width, height = header.natural_size()
    elif _wmf.is_wmf(data):
        played = _wmf.play(data, font_mapping=font_mapping)
        if played is None:
            return None
        player, (width, height) = played
        emf_plus = False
    else:
        return None
    player.id_prefix = prefix
    svg = _with_prefix(player.svg(width, height), prefix)
    return MetafileDrawing(svg=svg, width=width, height=height,
                           skipped=tuple(sorted(player.skipped.items())), emf_plus=emf_plus,
                           gdi_fallback=fallback, truncated=player.truncated, drawn=player.drawn)


def _with_prefix(svg: bytes, prefix: str) -> bytes:
    """Ids are made as the drawing is played and the prefix is set after; ``emf-`` is
    what every id starts with until then."""
    return svg.replace(b'id="emf-', f'id="{prefix}'.encode()).replace(b"url(#emf-", f"url(#{prefix}".encode())


_IMAGE = re.compile(r"<image\b([^>]*?)\bhref=\"data:image/svg\+xml;base64,([A-Za-z0-9+/=]+)\"([^>]*?)/>")
_ATTRIBUTE = re.compile(r'([\w:-]+)="([^"]*)"')
_ROOT = re.compile(rb"<svg\b[^>]*>")
_VIEWBOX = re.compile(rb'viewBox="([^"]*)"')
_LIMIT = 64 * 1024 * 1024
#: Base64 characters of a picture read to find its root (768 bytes; a multiple of four).
_HEAD = 1024


#: payload -> what :func:`inline_metafile_images` writes inline for it, or ``None`` (not a
#: picture this module drew): a slide is rasterised in several passes and calls.
_INLINE: dict = {}
_INLINE_LIMIT = 64
#: At most this many characters of payload kept (the content kept is about three quarters).
_INLINE_CHARS = 32 * 1024 * 1024


def _inline_parts(encoded: str) -> "tuple[str | None, str] | None":
    """``(viewBox or None, the content inside the root)`` of a picture :func:`metafile_to_svg`
    drew, from its base64 payload; ``None`` for any other picture."""
    if len(encoded) > _LIMIT:
        return None
    if len(encoded) > _HEAD and not _drawn_here(encoded[:_HEAD]):
        # The root, read from the payload's first bytes, is not one this module wrote:
        # not decoded whole (a photograph's SVG picture is megabytes, every slide).
        return None
    try:
        data = base64.b64decode(encoded, validate=True)
    except ValueError:
        return None
    root = _ROOT.search(data)
    if root is None or root.start() > 64 or MARKER.encode() not in root.group(0) or not data.rstrip().endswith(b"</svg>"):
        return None
    view_box = _VIEWBOX.search(root.group(0))
    inner = data[root.end() : data.rstrip().rfind(b"</svg>")].decode("utf-8", errors="replace")
    return (view_box.group(1).decode() if view_box else None), inner


def _drawn_here(head: str) -> bool:
    """Whether a picture whose payload starts ``head`` may be one :func:`metafile_to_svg`
    drew: false only where its first bytes hold a whole ``<svg>`` root tag that is not
    one -- past the 64th byte, or without the marker -- or are not base64 at all, which
    the whole payload's decoding would say too."""
    try:
        data = base64.b64decode(head, validate=True)
    except ValueError:
        return False
    root = _ROOT.search(data)
    if root is None:
        return b"<svg" in data       # a root tag longer than the head: decode it all
    return root.start() <= 64 and MARKER.encode() in root.group(0)


def inline_metafile_images(svg: str) -> str:
    """``svg`` with every picture drawn by :func:`metafile_to_svg` written inline, as a
    nested ``<svg>``, instead of as an ``<image>`` of an SVG.

    For a rasteriser: resvg (resvg-py 0.5) draws an SVG picture's shapes but none of its
    text -- an SVG it reads through an ``<image>`` gets no fonts -- so a metafile's words
    vanished from the PNG.  Inline, they are drawn with the page's fonts.  Only pictures
    this module drew are touched (their root carries ``data-ooxml-metafile``), and their
    ids are already unique to each metafile.  The ``<image>``'s own attributes (a
    transform, a clip, a filter) move to a group around the nested ``<svg>``.
    """
    if MARKER not in svg and "data:image/svg+xml;base64," not in svg:
        return svg

    def replace(match: re.Match) -> str:
        encoded = match.group(2)
        parts = _INLINE.get(encoded, False)
        if parts is False:
            parts = _inline_parts(encoded)
            if len(_INLINE) >= _INLINE_LIMIT or sum(map(len, _INLINE)) + len(encoded) > _INLINE_CHARS:
                _INLINE.clear()
            _INLINE[encoded] = parts
        if parts is None:
            return match.group(0)
        view_box, inner = parts
        attributes = dict(_ATTRIBUTE.findall(match.group(1) + " " + match.group(3)))
        box = " ".join(f'{name}="{attributes.pop(name)}"' for name in ("x", "y", "width", "height")
                       if name in attributes)
        attributes.pop("preserveAspectRatio", None)
        outer = "".join(f' {name}="{value}"' for name, value in attributes.items())
        view = f' viewBox="{view_box}"' if view_box is not None else ""
        return (f"<g{outer}><svg {box}{view} preserveAspectRatio=\"none\" overflow=\"hidden\">"
                f"{inner}</svg></g>")

    return _IMAGE.sub(replace, svg)
