# Why ooxml-common exists

Back to the [README](../README.md).

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
