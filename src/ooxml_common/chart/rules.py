"""Where Word and PowerPoint lay out and draw the same chart differently.

Every constant in :mod:`~ooxml_common.chart.layout` was measured on PowerPoint's own
export (pptx2svg ROADMAP.md, Phase 3), and PowerPoint's is what pptx2svg's fidelity
baselines hold byte for byte.  Word draws a ``c:chartSpace`` with the same Office chart
engine, but it is a different application with its own defaults, so where Word is
measured to differ the difference is a field here rather than a second layout, as
:class:`~ooxml_common.drawingml.rules.DrawingRules` does for fills and outlines.  The
caller says which application it is reproducing.

Nothing is assumed of Word that has not been measured on Word, so a field appears here
only with the measurement that fixed it.  The measurements are docx2svg's
``tools/make_chart_probe.py``: 58 charts written by hand, each on a page of its own,
exported by Word 16.106 on macOS in three documents (no settings part, compatibility
mode 14 and mode 15, which draw every chart identically) and read off the PDF.  Several
of these may well be PowerPoint's behaviour too -- the engine is shared -- but where
PowerPoint was measured on one size or one case only, the field keeps what pptx2svg
draws until PowerPoint is measured again.
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
    * ``chart_fill`` and ``chart_line`` -- what the chart space is painted with where its
      ``c:spPr`` states no fill, or no ``a:ln``: ``None`` for nothing (PowerPoint's:
      transparent, measured by pptx2svg), else ``RRGGBB`` and ``(RRGGBB, width in
      EMU)``.  Word fills it **white** and outlines it in ``898989`` at **0.5 pt**, each
      independently: a ``c:spPr`` stating only a fill keeps the default line, one
      stating only a line keeps the white fill, and an explicit ``a:noFill`` draws
      nothing.
    * ``plot_fill`` -- the same for the plot area's fill: Word fills it white -- a
      radar's plot area being the square round its web, and a pie or doughnut having none
      to fill.
    * ``plot_line`` -- whether the plot area's own ``a:ln`` is drawn round it.  pptx2svg
      draws only its fill; Word draws the line it states, at its width (1 pt, 0.75 pt),
      and no line where it states none.
    * ``title`` -- how a title takes its band and its baseline.  ``"lines"``: the band is
      :data:`~ooxml_common.chart.layout.TITLE_BAND_LINES` line boxes and the baseline
      :data:`~ooxml_common.chart.layout.TITLE_BASELINE_ASCENTS` ascents below the frame's
      top (PowerPoint's, each measured on one 18 pt Arial title).  ``"pitch"``, Word's:
      the band is the title's line pitch (its box and the face's line gap) **plus
      9.0 pt**, to 0.003 pt for Arial and Aptos at 8 to 36 pt, bold or not; and the
      baseline stands **7.5 pt + 0.9412 em** below the frame's top whatever the face
      (every Aptos title from 8 to 36 pt on Word's device pixel, an Arial one at 28 pt a
      pixel off).  The two agree for an 18 pt Arial title, the one PowerPoint measured.
    * ``side_legend`` -- the pads round a legend at the side.  ``"em"``: the plot-side
      pad 1.6 em and the outer 1.01 em, the legend placed a pad off the plot
      (PowerPoint's, measured at 10 pt).  ``"word"``: the plot-side pad is **13.25 pt
      and half the key**, the outer one **10.13 pt**, at 6 to 18 pt of legend text and
      the same at 10 pt as PowerPoint's; and the legend stands against the **frame**, not
      the plot -- where the plot gives up room to a category label centred on its edge
      (an area chart, a scatter) or to a horizontal bar chart's last value label, the
      plot shrinks and the legend does not move.  On the left, the key stands 8.25 pt
      and half the key in from the frame's edge.
    * ``legend_under_title`` -- whether a legend at the top stands under the title (Word)
      rather than at the frame's top over it.
    * ``top_right_legend`` -- ``"band"``: a ``legendPos="tr"`` legend is a top one
      (pptx2svg's; PowerPoint is not measured).  ``"column"``, Word's: a column of
      entries at the right, placed as a right legend is across and from where a top
      legend's first row stands down; the plot gives up the side band, the rows' pitch at
      its top and the 6 pt pad at its bottom.
    * ``legend_order`` -- ``"series"``: entries in series order.  ``"stack"``, Word's:
      **reversed** for clustered horizontal bars, at the side and below alike, and for
      stacked and 100% columns beside a legend at the side -- the orders the series stand
      in, bottom to top -- while stacked columns over a legend below, stacked bars and
      everything else keep series order.
    * ``bars_upward`` -- whether a clustered horizontal bar chart puts its first series
      at the **bottom** of each category's group (Word), rather than at the top.
    * ``stated_line_width`` -- whether a line series whose ``a:ln`` states a width and no
      colour is drawn at that width (Word: ``<a:ln w="28575"/>`` came back 2.25 pt in the
      series' accent) rather than at the default 1.5 pt.
    * ``legend_key_outlines`` -- whether a legend key is outlined with its series' line
      where the series states one (Word: a 0.75 pt black ``a:ln`` and a 1.5 pt purple one
      came back round their keys), rather than only where it has no fill.
    * ``auto_title`` -- which title a chart shows (docx2svg's
      ``make_chart_text_probe.py``).  ``False``: a ``c:title`` with text, unless
      ``c:autoTitleDeleted`` is ``1`` (pptx2svg's).  ``True``, Word's: a ``c:title`` with
      text **whatever** ``c:autoTitleDeleted`` says; a ``c:title`` with no text the sole
      series' **name** (a pie's too), or -- over several series, or where
      ``c:autoTitleDeleted`` is ``1`` -- Word's own "Chart Title" in its interface's
      language, which the caller supplies or leaves out
      (:attr:`~ooxml_common.chart.layout.ChartBuilder.default_title`); and no ``c:title``
      but ``c:autoTitleDeleted`` stated ``0`` the sole series' name, nothing over
      several.  Without ``c:autoTitleDeleted`` and without a ``c:title``, nothing.
    * ``axis_titles`` -- whether an axis' ``c:title`` is laid out and drawn.  ``False``
      (pptx2svg's): neither.  ``True``, Word's: a title on an axis at the left is turned
      to read upwards (whatever its ``a:bodyPr`` says, but for an explicit ``rot="0"``,
      which is not modelled and is left undrawn), one at the bottom reads across; each
      takes its line pitch **plus 9.0 pt** off the plot's side -- the chart title's band
      -- and its line box stands **12.5 pt** in from the frame's edge (or the edge of a
      legend there), centred on the plot.  Measured on Aptos and Arial titles of 10 to
      18 pt, on columns, bars and lines, beside a legend at every side, to Word's device
      pixel.
    """

    name: str
    drawing: DrawingRules
    chart_fill: str | None = None
    chart_line: tuple[str, float] | None = None
    plot_fill: str | None = None
    plot_line: bool = False
    title: str = "lines"
    side_legend: str = "em"
    legend_under_title: bool = False
    top_right_legend: str = "band"
    legend_order: str = "series"
    bars_upward: bool = False
    stated_line_width: bool = False
    legend_key_outlines: bool = False
    auto_title: bool = False
    axis_titles: bool = False


#: PowerPoint, as pptx2svg reproduces it.  The default everywhere here.
POWERPOINT = ChartRules("powerpoint", drawing.POWERPOINT)

#: Word, as docx2svg measured it (``tools/make_chart_probe.py``).
WORD = ChartRules(
    "word",
    drawing.WORD,
    chart_fill="FFFFFF",
    chart_line=("898989", 6350.0),
    plot_fill="FFFFFF",
    plot_line=True,
    title="pitch",
    side_legend="word",
    legend_under_title=True,
    top_right_legend="column",
    legend_order="stack",
    bars_upward=True,
    stated_line_width=True,
    legend_key_outlines=True,
    auto_title=True,
    axis_titles=True,
)
