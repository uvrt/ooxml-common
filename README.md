# ooxml-common

The format-neutral half of an Office Open XML renderer, shared by
[pptx2svg](https://github.com/uvrt/pptx2svg) and
[docx2svg](https://github.com/uvrt/docx2svg): the OPC container, units, embedded-font
decoding, the measured text metrics, and DrawingML -- its value types, colour resolution,
the complete preset geometry table, and fills, outlines, markers and effects drawn as SVG.

Standard library only at runtime. Python 3.10+.

## Why it exists

docx2svg needs to measure text with the same advance widths, kerning classes and font
substitutions that pptx2svg measured against PowerPoint. The alternatives were to depend
on a PowerPoint renderer in order to measure a Word document, or to copy the tables and
let two copies of each measured constant drift apart. This package holds one copy that
both use.

It was extracted from pptx2svg **with its git history**, in two steps: first what
already imported nothing from pptx2svg's slide model, then DrawingML's value types lifted
out of that model with the renderers that take them. Every constant here came with a
record of the observations that fixed it and the hypotheses they refuted; `git log
--follow` on any moved file shows that record back to pptx2svg's first commit.

docx2svg needs DrawingML drawn too -- a Word document's floating shapes are DrawingML --
and the alternative was a second copy of pptx2svg's renderers, which docx2svg had
started to write (its ROADMAP.md, "Floating drawings -- measured", F.10).

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
| `ooxml_common.imagemeta` | A picture's natural size, which a tiled fill is measured in |
| `ooxml_common.drawingml.model` | DrawingML's value types: colour choices and resolved colours, fills, outlines, effects, transforms, geometry, picture tiling |
| `ooxml_common.drawingml.source` | DrawingML as the XML states it: unresolved fills, outlines, shape styles, effects, transforms, geometry, the theme's format scheme |
| `ooxml_common.drawingml.read` | The reader: `a:` XML (a slide's or a Word shape's) into those types, and a theme's colour and format schemes |
| `ooxml_common.drawingml.color` | Colour resolution through a colour map and theme, with every transform, under per-application `ColorRules` |
| `ooxml_common.drawingml.guides` | Shape-guide formula evaluation |
| `ooxml_common.drawingml.preset_specs` | The preset geometries pptx2svg draws from ECMA-376 |
| `ooxml_common.drawingml.presets` | The rest, and `PRESETS`: every name `ST_ShapeType` allows |
| `ooxml_common.drawingml.geometry` | A geometry as SVG: pptx2svg's one element per shape, or path data per `a:path` |
| `ooxml_common.drawingml.fill` | Solid, gradient, pattern and picture fills; outlines with dashes, caps and joins; arrowheads |
| `ooxml_common.drawingml.effect` | Shadows, glow, soft edges and picture effects as SVG filters |
| `ooxml_common.drawingml.pattern` | The 54 `a:pattFill` presets |
| `ooxml_common.drawingml.svg` | What the renderers need of the consumer's SVG document (`SvgDefs`), and `num` |

## Where Word and PowerPoint differ

Where the two applications measurably draw the same DrawingML differently, the shared code
takes the application as a parameter rather than choosing one rule for both. Today there
is one such difference, and `ooxml_common.drawingml.color.ColorRules` carries it:

| | PowerPoint (`POWERPOINT`, the default) | Word (`WORD`) |
| --- | --- | --- |
| A transformed channel's level | the nearest, a half to even (pptx2svg's rule; its swatches are within 2/255 of PowerPoint) | the nearest, **a half down** -- black at `lumMod 50000 lumOff 50000` is `7F7F7F` (docx2svg ROADMAP.md, F.3) |

Everything else follows PowerPoint's measurements and is **unmeasured for Word**:
`tint` and `shade` in linear light, `satMod` in HLS, the order transforms apply in. And one
known defect moved as it was: PowerPoint shades a chart's accent cycle in linear light,
where the HLS `lumMod` here is up to 23 levels off (pptx2svg ROADMAP.md) -- pptx2svg's
chart ramp carries its own conversion, and fixing the general transform would move every
deck, so it waits for a change that is allowed to.

## What is deliberately not in it

- **Line breaking.** pptx2svg's `text/wrap.py` breaks DrawingML paragraphs. The method
  carries over to Word; the types do not. The paragraph protocol a shared line breaker
  should take is being decided by docx2svg's Phase 3, which breaks lines against Word's
  own output, not in advance.
- **Anything that takes a document model.** `render/text.py` lays out an `a:bodyPr`
  text box, which a Word body does not have; the shape renderer that places elements on a
  slide, and the resolver that turns what the reader read into drawable values through a
  slide's inheritance, are pptx2svg's.  (The reader itself is here: what it reads is the
  same in both formats.)
- **The fidelity harnesses.** pptx2svg scores rasterised slides by SSIM; docx2svg
  measures glyph boxes in a vector PDF. They share the idea of an oracle and none of the
  code.
- **The metric generators.** `tools/extract_font_metrics.py` and
  `tools/derive_preset_geometry.py` stay in pptx2svg for now and write into this package:
  the first reads Office's faces through pptx2svg's fidelity-harness font profile, and
  the second's manifest is pptx2svg's renderer policy. The second also writes
  `drawingml/presets.py` -- every preset its manifest leaves out -- so that `PRESETS` is
  the whole table.

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
