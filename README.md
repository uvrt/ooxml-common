# ooxml-common

The format-neutral half of an Office Open XML renderer, shared by
[pptx2svg](https://github.com/uvrt/pptx2svg) and
[docx2svg](https://github.com/uvrt/docx2svg): the OPC container, units, embedded-font
decoding, the measured text metrics, and DrawingML -- its value types, colour resolution,
the complete preset geometry table, and fills, outlines, markers and effects drawn as SVG
-- and what is drawn with them: shapes, text bodies and groups, SmartArt's cached drawing,
and charts, read, laid out and drawn.

Standard library only at runtime. Python 3.10+.

## Why it exists

docx2svg needs to measure text with the same advance widths, kerning classes and font
substitutions that pptx2svg measured against PowerPoint. The alternatives were to depend
on a PowerPoint renderer in order to measure a Word document, or to copy the tables and
let two copies of each measured constant drift apart. This package holds one copy that
both use.

It was extracted from pptx2svg **with its git history**, in three steps: first what
already imported nothing from pptx2svg's slide model, then DrawingML's value types lifted
out of that model with the renderers that take them, then the charts and the shape tree
with the shape and text body renderers that draw them. Every constant here came with a
record of the observations that fixed it and the hypotheses they refuted; `git log
--follow` on any moved file shows that record back to pptx2svg's first commit.

docx2svg needs DrawingML drawn too -- a Word document's floating shapes are DrawingML --
and the alternative was a second copy of pptx2svg's renderers, which docx2svg had
started to write (its ROADMAP.md, "Floating drawings -- measured", F.10).

And a Word document holds charts and SmartArt diagrams, which pptx2svg draws. A chart is
data plus styling in both formats -- the same `c:chartSpace` part -- and is lowered to
ordinary shapes, lines and text bodies; a SmartArt diagram carries the same cached
`dsp:drawing` shape tree in both. So the chart reader and layout, the shape tree and text
body readers, and the renderers that draw the result moved here too.

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
| `ooxml_common.imagemeta` | A picture's natural size, which a tiled fill is measured in, and the ICC profile it carries |
| `ooxml_common.icc` | A matrix/TRC RGB profile read, and its colours converted to sRGB exactly, as PowerPoint converts a profiled picture |
| `ooxml_common.drawingml.model` | DrawingML's value types: colour choices and resolved colours, fills, outlines, effects, transforms, geometry, picture tiling |
| `ooxml_common.drawingml.source` | DrawingML as the XML states it: unresolved fills, outlines, shape styles, effects, transforms, geometry, the theme's format scheme |
| `ooxml_common.drawingml.read` | The reader: `a:` XML (a slide's or a Word shape's) into those types, and a theme's colour and format schemes |
| `ooxml_common.drawingml.color` | Colour resolution through a colour map and theme, with every transform, under per-application `ColorRules` |
| `ooxml_common.drawingml.guides` | Shape-guide formula evaluation |
| `ooxml_common.drawingml.preset_specs` | The preset geometries pptx2svg draws from ECMA-376 |
| `ooxml_common.drawingml.presets` | The rest, and `PRESETS`: every name `ST_ShapeType` allows |
| `ooxml_common.drawingml.preset_text_rects` | Every preset's text rectangle (`a:rect`), from the same source (`tools/derive_preset_text_rects.py`) |
| `ooxml_common.drawingml.geometry` | A geometry as SVG: pptx2svg's one element per shape, or path data per `a:path`; the rectangle its text is laid out in (`text_rect`), and that drawn in by the outline as Word does and PowerPoint does not (`text_area`) |
| `ooxml_common.drawingml.fill` | Solid, gradient, pattern and picture fills; outlines with dashes, caps and joins; arrowheads |
| `ooxml_common.drawingml.effect` | Shadows, glow, soft edges and picture effects as SVG filters |
| `ooxml_common.drawingml.pattern` | The 54 `a:pattFill` presets |
| `ooxml_common.drawingml.rules` | Where Word and PowerPoint draw the same DrawingML differently, as a parameter of the renderers |
| `ooxml_common.drawingml.svg` | What the renderers need of the consumer's SVG document (`SvgDefs`), and `num` |
| `ooxml_common.drawingml.scene` | The drawable scene: resolved text bodies, shapes, connectors, pictures, groups, tables and charts |
| `ooxml_common.drawingml.source_tree` | A shape tree and its text as the XML states them, before inheritance |
| `ooxml_common.drawingml.read_tree` | The shape tree reader (`p:spTree`, a group, SmartArt's `dsp:spTree`) |
| `ooxml_common.drawingml.read_text` | The text body reader (`a:txBody`, `c:rich`, `c:txPr`) |
| `ooxml_common.drawingml.context` | `RenderContext`: the text measurer, font map, definitions, ids and `DrawingRules` of one render |
| `ooxml_common.drawingml.elements` | An element or a group as SVG, through a group's child space |
| `ooxml_common.drawingml.shape` | A shape, connector, picture or table as SVG |
| `ooxml_common.drawingml.textbody` | A text body laid out in its frame (`a:bodyPr`) and drawn as SVG text |
| `ooxml_common.drawingml.wrap` | Breaking a DrawingML paragraph into lines |
| `ooxml_common.drawingml.diagram` | SmartArt: finding a diagram's cached drawing from its data part |
| `ooxml_common.chart.read` | A chart part (`c:chartSpace`) read, with its cached values |
| `ooxml_common.chart.layout` | A chart laid out and lowered to scene elements, every constant measured on PowerPoint |
| `ooxml_common.chart.rules` | Where Word and PowerPoint lay a chart out differently, as a parameter |

## Where Word and PowerPoint differ

Where the two applications measurably draw the same DrawingML differently, the shared code
takes the application as a parameter rather than choosing one rule for both:
`ooxml_common.drawingml.rules.DrawingRules` (`POWERPOINT`, the default, and `WORD`), which
carries `ooxml_common.drawingml.color.ColorRules`, and which `fill.render_fill_attrs`,
`fill.render_outline_attrs` and `fill.render_arrowheads` take. Word's column was measured
by docx2svg's `tools/make_dml_probe.py`, read off Word's PDF (docx2svg ROADMAP.md,
"DrawingML drawn by the shared renderers"); PowerPoint's is what pptx2svg has always
drawn, which its fidelity baselines hold byte for byte.

| | PowerPoint (`POWERPOINT`) | Word (`WORD`), measured |
| --- | --- | --- |
| A transformed channel's level | the nearest, a half to even | the nearest, **a half down** (black at `lumMod 50000 lumOff 50000` is `7F7F7F`) |
| Composing transforms | `lumMod` with `lumOff` in one pass wherever they are; a level rounded after each; saturation clamped at 1; `hueMod`, `hueOff`, `satOff`, `gray`, `inv`, `comp` not applied | **in document order, unrounded**, saturation unbounded above, all of them applied (`inv` in linear light); `a:scrgbClr` read as linear light. 54 / 54 swatches, against 36 |
| A linear gradient's span | the box's width, in box units | through the centre, **corner to corner** projected on the direction; `scaled` stretches the unit square's; `rotWithShape="0"` holds the angle to the page |
| A two-stop 0-100% gradient | blended in sRGB | eased (cosine) **in linear light**; a stop's alpha not drawn |
| Path gradients | radial, to the farthest corner | `circle` from the `fillToRect` point to the corners' circle round the centre; `rect` / `shape` rectangular rings |
| Dashes | preset times width, the cap on each dash | round cap: each dash a width shorter, each gap a width longer; square cap: squared only at the line's ends; `sysDashDot`, `sysDashDotDot` |
| Arrowheads | SVG markers, 5 / 8 / 12 px | 2 / 3 / 5 times the width (2 pt at least), the line cut back under a triangle or stealth |
| An outline's join when none is stated | miter (SVG's) | **round** |
| A pattern's 8 pt cell | registered to the shape | registered to the **page**, square to it on a rotated shape |

Most of Word's column is probably Office's shared engine and so PowerPoint's too; that is
not measured, and pptx2svg's output is not moved on a guess. `tint` and `shade` in linear
light and `lumMod` / `lumOff` / `satMod` in HLS are measured the same in both. And one
known defect moved as it was: PowerPoint shades a chart's accent cycle in linear light,
where the HLS `lumMod` here is up to 23 levels off (pptx2svg ROADMAP.md) -- pptx2svg's
chart ramp carries its own conversion, and fixing the general transform would move every
deck, so it waits for a change that is allowed to.

Every renderer also takes `dpi`, the pixels per inch of the caller's user space: 96 for
pptx2svg, 300 for docx2svg, which draws on Word's device grid.

The shape, text body and group renderers read the rules from their `RenderContext`
(`rules`, `POWERPOINT` by default), and a chart's layout takes
`ooxml_common.chart.rules.ChartRules` (`POWERPOINT`, the default), which carries the
`DrawingRules` its scene is drawn with. Every constant of the layout was measured on
PowerPoint (pptx2svg ROADMAP.md, Phase 3); where Word is measured to lay a chart out
differently, the difference becomes a field there.

What a chart cannot know is the consumer's, and comes in as parameters: the theme's faces,
text colour and accent cycle (`chart.layout.ChartStyle`), and how a fill, an outline, a
title's rich text and a theme typeface (`+mn-lt`) resolve -- `ChartBuilder`'s
`resolve_fill`, `resolve_outline`, `resolve_text` and `resolve_typeface`, each the
consumer's own inheritance. Text is measured through the `TextMeasurer` protocol, as
everywhere here.

## What is deliberately not in it

- **Line breaking for a Word paragraph.** `drawingml.wrap` breaks DrawingML paragraphs
  -- a text body's, which a chart and a SmartArt shape carry in Word too. A Word body's
  paragraphs are a different model and docx2svg breaks them against Word's own output.
- **Anything that takes a document model.** The resolver that turns what the reader read
  into drawable values through a slide's inheritance -- placeholders, masters, list
  styles -- is pptx2svg's, and a Word document's is docx2svg's; so is drawing a whole
  slide or page. (The readers and the renderers of what they resolve to are here: what
  they read and draw is the same in both formats.)
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
