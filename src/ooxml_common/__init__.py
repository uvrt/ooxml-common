"""The parts of an Office Open XML renderer that do not depend on the document format.

Extracted from `pptx2svg <https://github.com/uvrt/pptx2svg>`_ with its history, so that
`docx2svg <https://github.com/uvrt/docx2svg>`_ can measure text with the same tables
rather than a second copy of them, and draw DrawingML with the same renderers.  Nothing
here imports either consumer.  The first extraction took what was already free of
pptx2svg's slide model; the second lifted DrawingML's value types out of that model so its
fill, outline, effect, geometry and colour renderers could follow; the third brought the
charts and the shape tree, with the shape and text body renderers that draw them.

* :mod:`ooxml_common.opc` -- the OPC container: ZIP parts, content types, relationships;
* :mod:`ooxml_common.kinds` -- which kind of package an extension names (``.docx``,
  ``.potm``...) and the main part's content type that kind needs;
* :mod:`ooxml_common.xmlutil` -- namespace-agnostic helpers over ``xml.etree``;
* :mod:`ooxml_common.units` -- EMU, point, pixel and angle conversions;
* :mod:`ooxml_common.locales` -- the regional settings a conversion or an edit is in
  (:class:`~ooxml_common.locales.Locale`), en-US unless the caller says otherwise;
* :mod:`ooxml_common.numfmt` -- a number format code read once: its sections, its
  tokens, and whether it shows a date, a time, a percent, a text (measured in Excel);
* :mod:`ooxml_common.dates` -- a date's serial printed in its number format code, with
  the month and day names measured per locale;
* :mod:`ooxml_common.fonts` -- the font bundle probe, embedded-font decoding (EOT, MTX,
  SFNT) and the substitution report;
* :mod:`ooxml_common.text` -- measured advance widths, kerning classes, the font map
  with its grading, and the :class:`~ooxml_common.text.measure.TextMeasurer` protocol;
* :mod:`ooxml_common.imagemeta` -- a picture's natural size, which a tiled fill is
  measured in;
* :mod:`ooxml_common.svgimage` -- an SVG picture's natural size as PowerPoint reads it,
  and the SVG with that size restated in pixels for a rasteriser;
* :mod:`ooxml_common.raster` -- SVG to PNG through an installed rasteriser (resvg-py,
  then cairosvg), and a page drawn in passes, for both renderers;
* :mod:`ooxml_common.metafile` -- EMF and WMF pictures drawn from their GDI records as
  SVG, as Windows PowerPoint draws them, and device-independent bitmaps as PNG;
* :mod:`ooxml_common.drawingml` -- DrawingML's value types, colour resolution with every
  transform, shape-guide formulas, the complete ECMA-376 preset table with geometry as
  SVG path data, and fills, outlines, markers and effects as SVG; and the drawable scene
  -- shapes, text bodies, groups -- with its readers and renderers, and SmartArt's cached
  drawing; and Office's built-in data both formats' consumers need -- PowerPoint's
  built-in table styles and the Office theme of a new file, measured;
* :mod:`ooxml_common.chart` -- a chart part read, laid out and lowered to that scene.

Standard library only at runtime, like both consumers.  Capability arrives through
extras: ``[measure]`` (fontTools, for measuring real font files) and ``[fonts]`` (the
OFL font files the tables were measured from).

A Word paragraph's line breaking is deliberately **not** here: docx2svg breaks a Word
body's paragraphs against Word's own output.  :mod:`ooxml_common.drawingml.wrap` breaks a
DrawingML text body's, which a chart and a SmartArt shape carry in either format.
"""

__version__ = "0.33.1"
