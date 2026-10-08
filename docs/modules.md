# What is in ooxml-common

Back to the [README](../README.md).

## Modules

| Module | What it is |
| --- | --- |
| `ooxml_common.opc` | The OPC container: ZIP parts, content types, relationships |
| `ooxml_common.kinds` | The package kinds: which extension names which (`.docx`, `.dotm`, `.potx`, `.xltm`...), whether it is a template and may carry macros, its main part's content type, and `kind_mismatch` for a package whose content type its file name does not take |
| `ooxml_common.xmlutil` | Namespace-agnostic helpers over `xml.etree` |
| `ooxml_common.units` | EMU, point, pixel and angle conversions |
| `ooxml_common.fonts` | The font bundle probe, embedded-font decoding (EOT, MicroType Express, SFNT) and the substitution report; `metrics_from_faces` builds an advance table, legacy kern pairs included, from a family's font files |
| `ooxml_common.fonts.office` | Where Office for Mac finds a face, read in place: the applications' bundles, macOS's folders and Office's cloud-font cache (`cloud_font_dirs`), in each application's measured order (`POWERPOINT`, `WORD`); a header-only index with the names and CSS keys resvg files a face under (`find`, `css_match`), a standard-library face reader (`Face`), and advance tables built from installed faces (`metrics`, `layout_metrics`) |
| `ooxml_common.text.metrics` | Generated advance-width tables for the faces measured |
| `ooxml_common.text.kerning` | Kerning class matrices: each face's OpenType feature (`KERNING`, from GPOS) and the legacy `kern` table of the face it stands for (`LEGACY_KERNING`); `KerningSource`, which of the two an application charges |
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
| `ooxml_common.drawingml.textmeasure` | A text body measured without drawing it: `measure_text_body`, `measure_shape_text` and `measure_text` give each line's break positions, width and height, the height the text needs, and where the text area sits in the frame (`area_left`, `area_top`): each paragraph wrapped inside its `marL`, exactly as the body is anchored and autofit estimates it, or with `as_drawn=True` with line breaks kept where it does not wrap, as it is drawn |
| `ooxml_common.drawingml.wrap` | Breaking a DrawingML paragraph into lines |
| `ooxml_common.drawingml.diagram` | SmartArt: finding a diagram's cached drawing from its data part |
| `ooxml_common.chart.read` | A chart part (`c:chartSpace`) read, with its cached values |
| `ooxml_common.chart.layout` | A chart laid out and lowered to scene elements, every constant measured on PowerPoint |
| `ooxml_common.chart.rules` | Where Word and PowerPoint lay a chart out differently, as a parameter |

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
