"""Charts: ``c:chartSpace`` read, laid out and lowered to the drawable scene.

Moved from pptx2svg with their history, so that a chart in a Word document is drawn by
the code that draws one on a slide:

* :mod:`~ooxml_common.chart.read` reads a chart part into a ``SourceChart`` -- the data,
  the cached workbook values, and the styling as the XML states it;
* :mod:`~ooxml_common.chart.layout` lays it out -- title, legend, axes, plot area, every
  mark and label -- and lowers it to :mod:`~ooxml_common.drawingml.scene` elements in the
  frame's own coordinate space, which :func:`~ooxml_common.drawingml.elements.render_element`
  draws as a group.

There is no cached picture of a chart in either format: the part is data plus styling,
and every position is computed.  What the layout cannot know is the consumer's: the
theme's faces and colours (:class:`~ooxml_common.chart.layout.ChartStyle`), and how a
fill, an outline, a title's rich text and a theme typeface resolve
(``ChartBuilder``'s ``resolve_*`` callables).
"""
