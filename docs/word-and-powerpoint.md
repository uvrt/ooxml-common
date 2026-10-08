# Where Word and PowerPoint differ

Back to the [README](../README.md).

Where the two applications measurably draw the same DrawingML differently, the shared code
takes the application as a parameter rather than choosing one rule for both:
`ooxml_common.drawingml.rules.DrawingRules` (`POWERPOINT`, the default, and `WORD`), which
carries `ooxml_common.drawingml.color.ColorRules`, and which `fill.render_fill_attrs`,
`fill.render_outline_attrs` and `fill.render_arrowheads` take. Word's column was measured
by docx2svg's `tools/make_dml_probe.py`, read off Word's PDF (docx2svg ROADMAP.md,
"DrawingML drawn by the shared renderers"); PowerPoint's is what pptx2svg draws, which its
fidelity baselines hold, and its colour rows were measured the same way by pptx2svg's
`tools/make_color_probe.py` (pptx2svg ROADMAP.md, "Colour transforms, measured").

| | PowerPoint (`POWERPOINT`) | Word (`WORD`), measured |
| --- | --- | --- |
| A transformed channel's level | kept as linear light in **1/100000** (an `a:scrgbClr` percentage) between steps, rounded at the end (black at `lumOff 50000` is `7F7F7F`) | unrounded between steps, the nearest, **a half down** (black at `lumMod 50000 lumOff 50000` is `7F7F7F`) |
| Composing transforms | in document order, a run of HLS steps on sRGB channels; saturation unbounded **above and below**, a grey given one red with its blue extrapolated; `gray` by **Rec. 709**; `gamma`, `invGamma`, `alphaMod`, `alphaOff` applied. 3,102 / 3,108 swatches (pptx2svg's `tools/make_color_probe.py`) | **in document order, unrounded**, saturation unbounded above, `gray` by Rec. 601, `inv` in linear light; `a:scrgbClr` read as linear light. 54 / 54 swatches |
| A linear gradient's span | the box's width, in box units | through the centre, **corner to corner** projected on the direction; `scaled` stretches the unit square's; `rotWithShape="0"` holds the angle to the page |
| A two-stop 0-100% gradient | blended in sRGB | eased (cosine) **in linear light**; a stop's alpha not drawn |
| Path gradients | radial, to the farthest corner | `circle` from the `fillToRect` point to the corners' circle round the centre; `rect` / `shape` rectangular rings |
| Dashes | preset times width, the cap on each dash | round cap: each dash a width shorter, each gap a width longer; square cap: squared only at the line's ends; `sysDashDot`, `sysDashDotDot` |
| Arrowheads | SVG markers, 5 / 8 / 12 px | 2 / 3 / 5 times the width (2 pt at least), the line cut back under a triangle or stealth |
| An outline's join when none is stated | miter (SVG's) | **round** |
| A pattern's 8 pt cell | registered to the shape | registered to the **page**, square to it on a rotated shape |
| A custom path's outline (`custom_path_strokes`) | scaled with the path by its `scale()` | at its **stated width**: the coordinates are scaled instead |
| A run's glyphs (`text_size_grid`) | at the stated size | at the size **rounded to the 300 dpi device pixel** (10 pt drawn 10.08) |
| A text body's first baseline (`first_baseline`) | the measurer's ascent, scaled by the spacing | the **spaced line box less the face's descent**; the next line a descent on, then its box less its descent |
| Kerning (`kerning`) | **a static face's legacy `kern` table**, never its GPOS pairs; a **variable** face's GPOS pairs (pptx2svg's `tools/make_kern_source_probe.py`, 29 lines in 15 faces) | **the legacy `kern` table** where a run kerns (`w:kern`), and nothing for a variable face (docx2svg's `tools/make_wrap_kern_probe.py`: 324 / 324 wrap verdicts) |
| Autofit (`autofit`) | **what the file stores**, measured on pptx2svg's `tools/make_autofit_probe.py`: `normAutofit` text at its `fontScale`, each size rounded to a whole point half up, with `lnSpcReduction` off a percentage spacing in points of percent, and at full size, overflowing, when nothing is stored; a `spAutoFit` shape at its stored extent | not measured: `normAutofit` text shrunk until it fits, a `spAutoFit` shape grown to its text |

Most of Word's column is probably Office's shared engine and so PowerPoint's too; that is
not measured, and pptx2svg's output is not moved on a guess. The colour rows are the
exception, measured on both: they compose alike, and `tint` and `shade` in linear light and
`lumMod` / `lumOff` / `satMod` in HLS are the same in both. And one known defect moved as
it was: PowerPoint shades a chart's accent cycle in linear light, where HLS `lumMod` is up
to 23 levels off (pptx2svg ROADMAP.md) -- that ramp is not a DrawingML transform, and
pptx2svg's chart layout carries its own conversion for it.

The kerning row is a rule about tables, not a change to them: `KERNING` is still each
face's OpenType feature, a `DefaultTextMeasurer` built without a `kerning` charges it, and
a `DrawingRules` that names none keeps it. A `RenderContext` built without a measurer gets
one charging its rules' source; a caller building its own passes
`kerning=rules.kerning`.

Every renderer also takes `dpi`, the pixels per inch of the caller's user space: 96 for
pptx2svg, 300 for docx2svg, which draws on Word's device grid.

The shape, text body and group renderers read the rules from their `RenderContext`
(`rules`, `POWERPOINT` by default), and a chart's layout takes
`ooxml_common.chart.rules.ChartRules` (`POWERPOINT`, the default), which carries the
`DrawingRules` its scene is drawn with. Every constant of the layout was measured on
PowerPoint (pptx2svg ROADMAP.md, Phase 3); where Word is measured to lay a chart out
differently, the difference becomes a field there.  `WORD` carries what docx2svg's
`tools/make_chart_probe.py` measured on 58 charts of its own, read off Word's PDF in three
documents (no settings part, compatibility modes 14 and 15, which draw every chart alike):

| | PowerPoint (`POWERPOINT`) | Word (`WORD`), measured |
| --- | --- | --- |
| A chart space stating no fill, no line | transparent | **white**, outlined `898989` at **0.5 pt**, each default on its own |
| A plot area stating no fill; its own line | nothing; not drawn | **white** (a radar's: the square round its web; a pie's: none); drawn |
| A title's band and baseline | 1.4769 line boxes; 1.5046 ascents down | its **pitch + 9 pt**; **7.5 pt + 0.9412 em** down, whatever the face |
| A side legend's pads | 1.6 em to the plot, 1.01 em to the edge; placed off the plot | **13.25 pt and half the key**, and **10.13 pt**; placed against the **frame** (a left one 8.25 pt and half the key in) |
| A top legend with a title; `legendPos="tr"` | over the title; a top band | **under** the title; a **column** at the right from the top |
| Legend order | series order | **reversed** for clustered bars, and for stacked columns at the side |
| Clustered horizontal bars | the first series at the top of its group | the first series at the **bottom** |
| A line series stating a width and no colour | 1.5 pt | its **stated width** |
| A legend key of a series with a line | not outlined | **outlined** |
| A `c:title` with no text; one with text and `c:autoTitleDeleted` `1` | none; none | the sole series' **name** (over several, Word's own "Chart Title", its band kept and its words the caller's); **drawn** |
| An axis' `c:title` | not drawn | **drawn**: at the left turned to read upwards, at the bottom across, each its **pitch + 9 pt** off the plot and its line box **12.5 pt** in from the frame (or a legend there) |
| A plot shorter than 1.1 em of its value labels | what is left | the band under it gives up **half the shortfall** |

The last three rows are docx2svg's `tools/make_chart_text_probe.py` (80 charts, the same
three documents). A chart's default axis and gridline colour is the caller's too
(`ChartStyle.line_color`): Word draws them `898989` in a chart stating Word 365's chart
style (`c14:style`).

At 10 pt the side legend's pads are PowerPoint's to 0.03 pt and an 18 pt Arial title's band
its to 0.002 pt, the one size and face each was measured at in PowerPoint; where the two
part, PowerPoint was not measured, and pptx2svg's output does not move.

What a chart cannot know is the consumer's, and comes in as parameters: the theme's faces,
text colour and accent cycle (`chart.layout.ChartStyle`), and how a fill, an outline, a
title's rich text and a theme typeface (`+mn-lt`) resolve -- `ChartBuilder`'s
`resolve_fill`, `resolve_outline`, `resolve_text` and `resolve_typeface`, each the
consumer's own inheritance. Text is measured through the `TextMeasurer` protocol, as
everywhere here.
