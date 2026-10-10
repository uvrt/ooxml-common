# Changelog

Versions are set in `pyproject.toml`; there are no release tags or PyPI releases yet.

## Unreleased
- Python 3.14 and 3.15: CI runs the suite on both, on Linux, macOS and Windows, and the
  classifiers declare them. `requires-python` stays `>=3.10`. No code change was needed.

## 0.8.0 -- 2026-10-10
- An application's own font folders, for both renderers: `ooxml_common.fonts.office.user_font_dirs()` -- an explicit `font_dirs`, else `OOXML_FONT_DIRS` (`os.pathsep`-separated), else none -- searched before every other location (`USER`, `user_search_dirs`, `with_subfolders`, `user_families`; `search_dirs(font_dirs=...)`, `metrics(dirs=...)`), and `check_families(supplied=...)` grading their faces `exact`.
- A table row of empty cells is one line tall, as PowerPoint draws it: an empty paragraph is laid out at its end-of-paragraph size when a row's height is measured, instead of the row keeping a shorter stored height (measured: 28.8 pt for 18 pt Aptos cells stored 14.4 and 18 pt).
- A legend at the top stands under the chart's title in PowerPoint too, not over it (`ChartRules.legend_under_title` now defaults to true; Word already did): measured on radar, column and line charts in PowerPoint 16 for Mac, where the legend's first baseline moves down by the title's band.

## 0.7.0 -- 2026-10-08
- Draw chart text in the colour its `c:txPr` cascade states -- tick and category labels, legend entries, data labels, and titles that state none of their own -- as PowerPoint and Word do, plain `tx1` where nothing states one.
- Print a number format's text round the number (`"€"#,##0.0"m"` is `€12.4m`), its zero section, scaling, optional decimals and exponent; honour a data label's and an axis' `sourceLinked`.
- Stand a radar's category labels off their vertex by 4% of the radius, centred on the anchor on a sloping spoke.

## 0.6.0 -- 2026-10-06
- Resolve a run's Japanese face as PowerPoint does.
- Find installed faces by their English typographic family.

## 0.5.0 -- 2026-10-06
- Kern with the table each application charges: the legacy `kern` table, measured (`KerningSource`, `LEGACY_KERNING`).
- `ooxml_common.fonts.office`: find faces where Office for Mac keeps them, in each application's measured order.
- Measure text as it is drawn (`as_drawn`), wrapping inside `marL`, and report the text area's offset.

## 0.4.6 -- 2026-10-06
- Measure a text body through a public API (`drawingml.textmeasure`).
- Name the package kinds (`ooxml_common.kinds`, `kind_mismatch`).

## 0.4.5 -- 2026-10-06
- Draw autofit as PowerPoint opens a file: what it stores, nothing re-fitted.

## 0.4.4 -- 2026-10-04 (0.4.3 the same day)
- Show the titles Word shows; lay out and draw axis titles as Word does; give a short plot back half of what it lacks.
- Let the caller colour a chart's default axes, ticks and gridlines.
- Compose colour transforms as PowerPoint does, each step kept in scRGB percentages.
- Start a run at the advance of the run before it, in its own face.

## 0.4.2 -- 2026-10-03
- Keep the font collection a shape's `fontRef` names.

## 0.4.1 -- 2026-10-01
- Lay a chart out as Word does (`ChartRules.WORD`).
- Draw a custom path's outline, a run's glyphs and a first baseline as Word does.

## 0.4.0 -- 2026-10-01
- The chart reader and layout, the shape tree and text body readers and their renderers moved here from pptx2svg.
- Find a SmartArt diagram's cached drawing for either format.
- Since 0.3.2: read a picture's ICC profile and convert matrix/TRC colours to sRGB; draw axis tick marks where PowerPoint draws them.

## 0.3.0 to 0.3.2 -- 2026-09-27 to 2026-09-28
- DrawingML's reader and renderers (fills, outlines, effects, patterns) moved here from pptx2svg.
- Draw DrawingML as Word does where Word measurably differs (`DrawingRules`, `ColorRules`).
- 0.3.1, 0.3.2: lay a shape's text out in its geometry's text rectangle, and say where Word and PowerPoint put it against the outline.

## 0.2.0 -- 2026-09-27
- DrawingML's value types moved here, keeping each application's colour rule.
- Carry every preset geometry, and draw any geometry as path data.
- Leave reading a deck's faces to the consumer; keep the tests that need only the tables.

## 0.1.0 -- 2026-09-25
- Extracted from pptx2svg with its git history: OPC, units, fonts, measured text metrics.
