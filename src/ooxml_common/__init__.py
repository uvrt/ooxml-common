"""The parts of an Office Open XML renderer that do not depend on the document format.

Extracted from `pptx2svg <https://github.com/uvrt/pptx2svg>`_ with its history, so that
`docx2svg <https://github.com/uvrt/docx2svg>`_ can measure text with the same tables
rather than a second copy of them.  Everything here was already free of pptx2svg's slide
model before it moved; nothing here imports either consumer.

* :mod:`ooxml_common.opc` -- the OPC container: ZIP parts, content types, relationships;
* :mod:`ooxml_common.xmlutil` -- namespace-agnostic helpers over ``xml.etree``;
* :mod:`ooxml_common.units` -- EMU, point, pixel and angle conversions;
* :mod:`ooxml_common.fonts` -- the font bundle probe, embedded-font decoding (EOT, MTX,
  SFNT) and the substitution report;
* :mod:`ooxml_common.text` -- measured advance widths, kerning classes, the font map
  with its grading, and the :class:`~ooxml_common.text.measure.TextMeasurer` protocol;
* :mod:`ooxml_common.drawingml` -- shape-guide formulas, the ECMA-376 preset shape
  geometries and the 54 pattern-fill presets.

Standard library only at runtime, like both consumers.  Capability arrives through
extras: ``[measure]`` (fontTools, for measuring real font files) and ``[fonts]`` (the
OFL font files the tables were measured from).

Line breaking is deliberately **not** here.  pptx2svg's ``text/wrap.py`` breaks DrawingML
paragraphs, and which paragraph protocol a shared line breaker should take is a question
docx2svg's Phase 3 answers by breaking lines against Word, not one to settle in advance.
"""

__version__ = "0.1.0"
