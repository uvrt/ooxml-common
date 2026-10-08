# ooxml-common

[![CI](https://github.com/uvrt/ooxml-common/actions/workflows/ci.yml/badge.svg)](https://github.com/uvrt/ooxml-common/actions/workflows/ci.yml)

The format-neutral half of an Office Open XML renderer, shared by
[pptx2svg](https://github.com/uvrt/pptx2svg) and
[docx2svg](https://github.com/uvrt/docx2svg): the OPC container, units, embedded-font
decoding, the measured text metrics, and DrawingML -- its value types, colour resolution,
the complete preset geometry table, and fills, outlines, markers and effects drawn as SVG
-- and what is drawn with them: shapes, text bodies and groups, SmartArt's cached drawing,
and charts, read, laid out and drawn.

Standard library only at runtime. Python 3.10+.

## Install

Not on PyPI yet. From a checkout:

```sh
pip install -e .                  # stdlib only
pip install -e '.[measure]'       # + fontTools, to measure real font files
pip install -e '.[dev]'           # + pytest
```

Or straight from GitHub: `pip install "ooxml-common @ git+https://github.com/uvrt/ooxml-common@main"`.

## Example

```python
from ooxml_common.opc import OpcPackage
from ooxml_common.kinds import kind_for
from ooxml_common.units import emu_to_pt
from ooxml_common.text.measure import DefaultTextMeasurer

package = OpcPackage.open("deck.pptx")           # parts, content types, relationships
print(kind_for("report.dotm"))                   # "dotm"
print(emu_to_pt(914400))                         # 72.0
measurer = DefaultTextMeasurer()                 # measured advance widths and kerning
print(measurer.measure_text_width("Hello, world", 18, font_family="Calibri"))  # CSS px
```

## What is in it, and what is not

- **In:** OPC and package kinds, units, embedded-font decoding and Office's font lookup,
  measured advance-width and kerning tables, clone substitution, DrawingML (reader, colour
  resolution, every preset geometry, fills, outlines, effects, patterns), the shape tree
  and text body readers and renderers, SmartArt's cached drawing, and charts read, laid
  out and drawn. The full module table: [docs/modules.md](docs/modules.md).
- **Where Word and PowerPoint differ**, measurably, the renderers take the application as
  a parameter (`DrawingRules`, `ColorRules`, `ChartRules`) rather than choosing one rule
  for both: [docs/word-and-powerpoint.md](docs/word-and-powerpoint.md).
- **Not in it:** line breaking for a Word paragraph, anything that takes a document model
  (inheritance through placeholders, masters, styles; drawing a whole slide or page), the
  fidelity harnesses, and the metric generators, which stay in pptx2svg for now. Details
  in [docs/modules.md](docs/modules.md#what-is-deliberately-not-in-it).

## Font files

The `[fonts]` extra is the **`pptx2svg-fonts`** distribution, the OFL-licensed font files
the metric tables were measured from; it lives in the pptx2svg repository
(`packages/pptx2svg-fonts`). The tests that need the files skip with a reason when it is
absent. No Microsoft font file enters this repository in any form. More:
[docs/fonts.md](docs/fonts.md).

## Tests

```sh
python -m pytest -q
```

`tests/test_independence.py` holds the two promises that make the package shareable:
nothing here imports a consumer, and nothing here needs more than the standard library
at runtime. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Status

Version 0.7.0, used by pptx2svg and docx2svg from `main`. Changes per version:
[CHANGELOG.md](CHANGELOG.md). Why the package exists and how it was extracted from
pptx2svg with its history: [docs/history.md](docs/history.md).

## Family

- [pptx2svg](https://github.com/uvrt/pptx2svg) -- renders PowerPoint (`.pptx`) slides to SVG and PNG.
- [docx2svg](https://github.com/uvrt/docx2svg) -- renders Word (`.docx`) documents to SVG, page by page.
- [ooxml-common](https://github.com/uvrt/ooxml-common) (this repo) -- the format-neutral reading, DrawingML, fonts and text metrics both renderers share.
- [ooxml-edit](https://github.com/uvrt/ooxml-edit) -- lossless, undoable editing of OOXML packages, shared by both agent layers.
- [pptx-agent](https://github.com/uvrt/pptx-agent) -- an AI-editable PowerPoint layer: inspect, edit, re-render.
- [docx-agent](https://github.com/uvrt/docx-agent) -- an AI-editable Word layer: inspect, edit (optionally as tracked changes), re-render.

## Licence

MIT, for the source. Not for font files; see [LICENSE](LICENSE).
