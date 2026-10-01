"""Where Word and PowerPoint lay out and draw the same chart differently.

Every constant in :mod:`~ooxml_common.chart.layout` was measured on PowerPoint's own
export (pptx2svg ROADMAP.md, Phase 3), and PowerPoint's is what pptx2svg's fidelity
baselines hold byte for byte.  Word draws a ``c:chartSpace`` with the same Office chart
engine, but it is a different application with its own defaults, so where Word is
measured to differ the difference is a field here rather than a second layout, as
:class:`~ooxml_common.drawingml.rules.DrawingRules` does for fills and outlines.  The
caller says which application it is reproducing.

Nothing is assumed of Word that has not been measured on Word, so a field appears here
only with the measurement that fixed it.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..drawingml import rules as drawing
from ..drawingml.rules import DrawingRules


@dataclass(frozen=True)
class ChartRules:
    """How one application lays out and draws a chart.

    * ``drawing`` -- how the chart's fills, outlines and text rectangles are drawn: the
      :class:`~ooxml_common.drawingml.rules.DrawingRules` a caller puts on the
      :class:`~ooxml_common.drawingml.context.RenderContext` the chart is drawn with.
    """

    name: str
    drawing: DrawingRules


#: PowerPoint, as pptx2svg reproduces it.  The default everywhere here.
POWERPOINT = ChartRules("powerpoint", drawing.POWERPOINT)
