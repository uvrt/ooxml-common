# ooxml-common

The format-neutral half of an Office Open XML renderer, shared by
[pptx2svg](https://github.com/uvrt/pptx2svg) and
[docx2svg](https://github.com/uvrt/docx2svg): the OPC container, units, DrawingML
data, embedded-font decoding and, above all, the measured text metrics.

Standard library only at runtime. Python 3.10+.

## Why it exists

docx2svg needs to measure text with the same advance widths, kerning classes and font
substitutions that pptx2svg measured against PowerPoint. The alternatives were to depend
on a PowerPoint renderer in order to measure a Word document, or to copy the tables and
let two copies of each measured constant drift apart. This package holds one copy that
both use.

It was extracted from pptx2svg **with its git history**. Every constant here came with a
record of the observations that fixed it and the hypotheses they refuted; `git log
--follow` on any moved file shows that record back to pptx2svg's first commit.

## What is in it

| Module | What it is |
| --- | --- |
| `ooxml_common.opc` | The OPC container: ZIP parts, content types, relationships |
| `ooxml_common.xmlutil` | Namespace-agnostic helpers over `xml.etree` |
| `ooxml_common.units` | EMU, point, pixel and angle conversions |
| `ooxml_common.fonts` | The font bundle probe, embedded-font decoding (EOT, MicroType Express, SFNT) and the substitution report |
| `ooxml_common.text.metrics` | Generated advance-width tables for the faces measured |
| `ooxml_common.text.kerning` | Kerning class matrices, measured from each face's GPOS |
| `ooxml_common.text.fontmap` | Clone substitution with its grading (`exact`, `compatible`, `approximate`, `missing`) |
| `ooxml_common.text.measure` | The `TextMeasurer` protocol and both implementations |
| `ooxml_common.drawingml.guides` | Shape-guide formula evaluation |
| `ooxml_common.drawingml.preset_specs` | Preset shape geometries compiled from ECMA-376 |
| `ooxml_common.drawingml.pattern` | The 54 `a:pattFill` presets |

## What is deliberately not in it

- **Line breaking.** pptx2svg's `text/wrap.py` breaks DrawingML paragraphs. The method
  carries over to Word; the types do not. The paragraph protocol a shared line breaker
  should take is being decided by docx2svg's Phase 3, which breaks lines against Word's
  own output, not in advance.
- **Anything that takes a document model.** pptx2svg's `render/fill.py` and
  `render/geometry.py` are candidates once the DrawingML value types they take are lifted
  out of its slide model. `render/text.py` lays out an `a:bodyPr` text box, which a Word
  body does not have.
- **The fidelity harnesses.** pptx2svg scores rasterised slides by SSIM; docx2svg
  measures glyph boxes in a vector PDF. They share the idea of an oracle and none of the
  code.
- **The metric generators.** `tools/extract_font_metrics.py` and
  `tools/derive_preset_geometry.py` stay in pptx2svg for now and write into this package:
  the first reads Office's faces through pptx2svg's fidelity-harness font profile, and
  the second's manifest is pptx2svg's renderer policy.

## Install

Not on PyPI yet. From a checkout:

```sh
pip install -e .                  # stdlib only
pip install -e '.[measure]'       # + fontTools, to measure real font files
pip install -e '.[dev]'           # + pytest
```

## Font files

The `[fonts]` extra is the **`pptx2svg-fonts`** distribution: the OFL-licensed font
files the metric tables were measured from. It keeps its name and its home in the
pptx2svg repository (`packages/pptx2svg-fonts`) because renaming a distribution is
disruptive and `ooxml_common.fonts` finds it by import name alone, so where it lives
changes nothing here. It is not on PyPI either; install it from a pptx2svg checkout:

```sh
pip install -e ../pptx2svg/packages/pptx2svg-fonts
```

The tests that need the files skip with a reason when it is absent.

No Microsoft font file enters this repository in any form. The tables record
measurements of those designs, which are facts; the files are not ours to redistribute.

## Tests

```sh
python -m pytest -q
```

`tests/test_independence.py` holds the two promises that make the package shareable:
nothing here imports a consumer, and nothing here needs more than the standard library
at runtime.

## Licence

MIT, for the source. Not for font files; see [LICENSE](LICENSE).
