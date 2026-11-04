"""Text as outlines: an SVG whose ``<text>`` is drawn as glyph paths, so that a viewer
needs none of its fonts.

Both renderers write text as ``<text>``, which a browser draws with whatever fonts it
has -- and a face whose licence forbids serving it as a web font cannot be sent along.
:func:`outline_text` draws each text as the paths of the glyphs resvg would draw it with,
from the font files a rasterisation would be handed (:class:`FontSetup`), so the outlined
SVG looks like the PNG: the same faces (fallbacks for characters a face lacks included),
the same shaping (ligatures, kerning, marks), positions, variations of a variable face,
underlines and line-throughs, fills, strokes and paint servers.  Glyph shapes go into
the SVG; font files never do.

* :mod:`.face` -- a face's tables: character map, advances, metrics, variations, glyph
  outlines (TrueType and CFF);
* :mod:`.shaper` -- harfrust's shaping, for left-to-right runs of the scripts without a
  shaper of their own;
* :mod:`.fontdb` -- resvg's font database and usvg's face and fallback choice;
* :mod:`.svgtext` -- usvg's text layout, and the SVG written back.

Measured against resvg 0.48 (resvg-py 0.5), whose source the algorithms follow.  What
this package does not draw as resvg would is kept as text and reported
(:class:`KeptText`): right-to-left and complex-script text, colour (emoji) and CFF2
faces, ``textPath``, ``rotate`` and vertical text.

Standard library only.
"""

from .fontdb import Database, FontSetup
from .svgtext import KeptText, Outlined, embed_glyphs, glyph_id, glyph_sheet, outline_text

__all__ = ["Database", "FontSetup", "KeptText", "Outlined", "embed_glyphs", "glyph_id", "glyph_sheet",
           "outline_text"]
