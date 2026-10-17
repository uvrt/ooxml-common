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
:mod:`.gdi` lists what was measured.  EMF+ records are not played yet; a dual EMF+ file
is drawn from its GDI records, which say what its EMF+ records say for players without
EMF+, and :attr:`MetafileDrawing.emf_plus` reports it.

* :mod:`.gdi` -- the device context and the SVG it draws;
* :mod:`.emf` -- the EMF record reader;
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
    #: The file carries EMF+ records, which are not played; its GDI records were.
    emf_plus: bool = False
    #: A cap stopped the playback before the end of the file.
    truncated: bool = False
    #: How many elements were drawn; ``0`` when the metafile draws nothing this player
    #: draws (an EMF+-only file, a file of skipped records), and the caller draws its
    #: placeholder.
    drawn: int = 0

    @property
    def complete(self) -> bool:
        """Every record was understood: nothing skipped, no EMF+, not truncated."""
        return not self.skipped and not self.emf_plus and not self.truncated

    def warning(self) -> str | None:
        """One sentence naming what was not drawn, or ``None`` when everything was."""
        parts = []
        if self.skipped:
            parts.append("not drawn: " + ", ".join(f"{name} (x{count})" if count > 1 else name
                                                   for name, count in self.skipped))
        if self.emf_plus:
            parts.append("its EMF+ records are not played yet (Windows draws those), so its GDI records "
                         "are drawn instead")
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


def _draw(data: bytes, font_mapping) -> MetafileDrawing | None:
    prefix = "m" + hashlib.sha1(data).hexdigest()[:10] + "-"
    if _emf.is_emf(data):
        played = _emf.play(data, font_mapping=font_mapping)
        if played is None:
            return None
        player, header, emf_plus = played
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
                           truncated=player.truncated, drawn=player.drawn)


def _with_prefix(svg: bytes, prefix: str) -> bytes:
    """Ids are made as the drawing is played and the prefix is set after; ``emf-`` is
    what every id starts with until then."""
    return svg.replace(b'id="emf-', f'id="{prefix}'.encode()).replace(b"url(#emf-", f"url(#{prefix}".encode())


_IMAGE = re.compile(r"<image\b([^>]*?)\bhref=\"data:image/svg\+xml;base64,([A-Za-z0-9+/=]+)\"([^>]*?)/>")
_ATTRIBUTE = re.compile(r'([\w:-]+)="([^"]*)"')
_ROOT = re.compile(rb"<svg\b[^>]*>")
_VIEWBOX = re.compile(rb'viewBox="([^"]*)"')
_LIMIT = 64 * 1024 * 1024


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
        if len(encoded) > _LIMIT:
            return match.group(0)
        try:
            data = base64.b64decode(encoded, validate=True)
        except ValueError:
            return match.group(0)
        root = _ROOT.search(data)
        if root is None or root.start() > 64 or MARKER.encode() not in root.group(0) or not data.rstrip().endswith(b"</svg>"):
            return match.group(0)
        view_box = _VIEWBOX.search(root.group(0))
        inner = data[root.end() : data.rstrip().rfind(b"</svg>")].decode("utf-8", errors="replace")
        attributes = dict(_ATTRIBUTE.findall(match.group(1) + " " + match.group(3)))
        box = " ".join(f'{name}="{attributes.pop(name)}"' for name in ("x", "y", "width", "height")
                       if name in attributes)
        attributes.pop("preserveAspectRatio", None)
        outer = "".join(f' {name}="{value}"' for name, value in attributes.items())
        view = f' viewBox="{view_box.group(1).decode()}"' if view_box else ""
        return (f"<g{outer}><svg {box}{view} preserveAspectRatio=\"none\" overflow=\"hidden\">"
                f"{inner}</svg></g>")

    return _IMAGE.sub(replace, svg)
