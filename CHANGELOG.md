# Changelog

Versions are set in `pyproject.toml`; there are no release tags or PyPI releases yet.

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
