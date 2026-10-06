"""Where Word and PowerPoint measurably draw the same DrawingML differently.

The renderers here were moved from pptx2svg, where every rule was measured against
PowerPoint -- or, where it was not measured, is pptx2svg's long-standing behaviour, which
its fidelity baselines hold byte for byte.  docx2svg measured the same markup in Word
(its ``tools/make_dml_probe.py``: 81 pages of colour transforms, gradients, patterns,
dashes, caps, joins, arrowheads, theme style references, group fills and effects, read
off Word's PDF).  Where Word's drawing differs from what the renderers did, the
difference is a field here rather than a second renderer, and the caller says which
application it is reproducing.

Most of these are probably Office's shared drawing engine and so PowerPoint's too; that
is not measured, and pptx2svg's output is not changed on a guess, so :data:`POWERPOINT`
keeps what pptx2svg has always drawn.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..text import kerning as _kerning
from ..text.kerning import KerningSource
from . import color
from .color import ColorRules


@dataclass(frozen=True)
class DrawingRules:
    """How one application draws fills, outlines and arrowheads.

    * ``color`` -- how a colour's transforms compose (:class:`~.color.ColorRules`).
    * ``gradients`` -- ``"bounding-box"``: the gradient vector across the shape's box in
      box units, stops as stated (pptx2svg's).  ``"office"``, measured on Word: a linear
      gradient runs through the box's centre at its angle -- the true angle, or with
      ``scaled`` the angle of the unit square stretched onto the box -- from where the
      first corner meets it to where the last does (the box projected on the direction:
      ``w |cos| + h |sin|``); with ``rotWithShape="0"`` the angle is held to the page
      against the shape's rotation and flips; a ``circle`` path gradient runs from its
      ``fillToRect`` point to a circle round the box's centre through its corners; a
      ``rect`` path gradient is rectangular rings about the ``fillToRect`` rectangle; a
      gradient of exactly two stops, at 0 and 100%, eases between them in linear light
      (Word writes it in a linear profile, with a cosine ease), any other blends straight
      in sRGB; a stop's ``alpha`` is not drawn.
    * ``dashes`` -- ``"stroke-width"``: the preset's dash and gap times the width, with the
      line's own cap on every dash (pptx2svg's).  ``"office"``, measured on Word: a flat
      cap draws exactly that; a round cap shortens each dash by the width and lengthens
      each gap by it, so the rounded dash covers the stated length; a square cap draws
      the flat pattern, square only at the line's ends (so here: butt).  ``sysDashDot``
      and ``sysDashDotDot`` are ``3 1 1 1`` and ``3 1 1 1 1 1``.
    * ``arrowheads`` -- ``"markers"``: SVG markers of a fixed size (pptx2svg's).
      ``"office"``, measured on Word: shapes drawn by :func:`~.fill.render_arrowheads`,
      sized as ``sm`` 2, ``med`` 3 and ``lg`` 5 times the line's width, or 2 pt for a
      line thinner than that, with the line cut back under a triangle or a stealth.
    * ``default_join`` -- the join of an outline that states none: ``None`` for SVG's
      miter (pptx2svg's), ``"round"`` for Word's.
    * ``pattern_phase`` -- ``"shape"``: an ``a:pattFill``'s 8 pt cell registered to the
      shape's corner (pptx2svg's).  ``"page"``: to the page's corner and square to the
      page whatever the shape's rotation (Word's, measured -- and PowerPoint's, measured
      by pptx2svg, which does not reproduce it: ``fill.py``).
    * ``text_outline_inset`` -- how far inside its geometry's text rectangle a shape lays
      its text out, as a fraction of the outline's width
      (:func:`~.geometry.text_area`).  ``0.5`` for Word: half the outline, drawn or
      ``a:noFill``, its width the shape's own or its style's (docx2svg's
      ``make_text_box_probe.py``).  ``0.0`` for PowerPoint, measured: pptx2svg's
      ``tools/make_exposed_probe.py`` set a ``rect``, a ``roundRect`` and an ``ellipse``
      under a 1, 4 and 8 pt line, an 8 pt ``a:noFill`` one with its width, a theme line
      through ``a:lnRef``, and an 8 pt line under zero insets, and every run started
      where the same shape with no outline starts it, to 0.1 pt -- the text rectangle
      and the insets, and nothing for the outline.  Both lay the text out in the text
      rectangle itself (:func:`~.geometry.text_rect`).
    * ``custom_path_strokes`` -- how a custom geometry's path, authored in its own
      coordinates, is put on its shape.  ``"scaled"``: by an SVG ``scale()`` on the path,
      which scales the outline stroked along it with it (pptx2svg's: a chart's 1.5 pt
      line series is drawn 2 pt wide on its points-to-pixels path).  ``"stated"``: the
      coordinates are scaled instead, so the outline keeps its stated width -- Word's,
      measured on docx2svg's ``make_chart_probe.py``: line, scatter and radar series of
      1.5 and 2.25 pt and radar gridlines of 0.5 pt, each at its width.
    * ``text_size_grid`` -- the resolution, in dots an inch, a run's glyphs are drawn on:
      ``None`` for its size as stated (pptx2svg's), ``300`` for Word, whose PDF writes
      chart text at its size rounded to the device's pixel (10 pt as 10.08, 8 pt as 7.92,
      14 pt as 13.92) -- as it draws a document's own text (docx2svg ROADMAP.md, 5.4).
      What is laid out keeps the stated size.
    * ``first_baseline`` -- where a text body's first baseline stands at or below single
      line spacing.  ``"box"``: the measurer's ascent ratio, scaled by the spacing with
      the rest of the line (pptx2svg's, measured on PowerPoint).  ``"descent"``: the
      spaced line box less the face's descent, which the spacing does not scale -- Word's,
      measured on docx2svg's ``make_smartart_probe.py``: a SmartArt shape's text at 90%
      spacing in Aptos of 19 to 47 pt stands 0.817 em below its block's top, which is
      0.9 of Aptos's 1.2207 em box less its 0.2817 em descent, to Word's device pixel.  The
      measurer says what the box and the descent are (docx2svg's gives the face's own).
    * ``autofit`` -- what a text body's autofit does when the file is drawn as it stands.
      ``"stored"``, PowerPoint's, measured on pptx2svg's ``tools/make_autofit_probe.py``:
      nothing is re-fitted on open.  ``a:normAutofit`` applies only what it stores -- a
      ``fontScale`` takes every run to its scaled size rounded to a whole point, half up
      (25 pt at 50 % draws 12.5 as 13, 18 pt at 70 % 12.6 as 13), and an
      ``lnSpcReduction`` comes off a percentage line spacing in percentage points (150 %
      less 20 draws 130 %, not 120) and leaves ``a:spcPts`` and paragraph spacing alone --
      and with nothing stored the text overflows at full size; ``a:spAutoFit`` keeps the
      shape's stored extent.  ``"fit"``, unmeasured (pptx2svg's behaviour before the
      measurement, kept for Word): ``a:normAutofit`` text is shrunk until it fits,
      the reduction scales the line spacing, and a ``spAutoFit`` shape grows to its text.
    * ``kerning`` -- which of a face's kern pairs a line is laid out with
      (:class:`~ooxml_common.text.kerning.KerningSource`; the measurements are
      :mod:`ooxml_common.text.kerning`'s).  The default is the OpenType ``kern`` feature,
      which is what every measurer charged before either application was measured.
      PowerPoint's, measured on pptx2svg's ``tools/make_kern_source_probe.py`` and
      pptx-agent's ``tools/wrap_boundary_probe.py``: a static face's legacy ``kern``
      table only -- Aptos's ``ss``, which only ``GPOS`` holds, is not charged, so "Pass"
      at 18 pt breaks in a box the feature-kerned word fits -- and a variable face's
      ``GPOS`` pairs.  Word's, measured on docx2svg's ``tools/make_wrap_kern_probe.py``:
      the legacy table where a run kerns at all, and no pairs for a variable face.  A
      rule only says which table; the measurer charges it, so a context built without a
      measurer gets one with its rule's source (:class:`~.context.RenderContext`), and a
      caller that builds its own passes ``kerning=rules.kerning``.
    * ``synthetic_bold`` -- how bold East Asian text in a face with no bold cut is drawn
      (MS Gothic, MS Mincho: their ``.ttc`` files hold none).  ``None``: asked for as
      ``font-weight="bold"``, which a rasteriser with no bold face to draw draws regular.
      ``"stroke"``, measured on PowerPoint (pptx2svg's ``tools/make_font_resolution_probe.py``,
      its ``bold-sizes`` deck): the regular outline filled and stroked in the text's
      colour (text rendering mode 2) with a line ``0.12 pt + 2%`` of the size -- 0.28 pt
      at 8 pt, 0.36 at 12, 0.48 at 18, 0.60 at 24, 0.68 at 28.
    """

    name: str
    color: ColorRules
    gradients: str = "bounding-box"
    dashes: str = "stroke-width"
    arrowheads: str = "markers"
    default_join: str | None = None
    pattern_phase: str = "shape"
    text_outline_inset: float = 0.0
    custom_path_strokes: str = "scaled"
    text_size_grid: int | None = None
    first_baseline: str = "box"
    autofit: str = "stored"
    kerning: KerningSource = _kerning.FEATURE
    synthetic_bold: str | None = None


#: PowerPoint, as pptx2svg reproduces it.  The default everywhere here.
POWERPOINT = DrawingRules("powerpoint", color.POWERPOINT, kerning=_kerning.POWERPOINT,
                          synthetic_bold="stroke")

#: Word, as docx2svg measured it.
WORD = DrawingRules("word", color.WORD, gradients="office", dashes="office", arrowheads="office",
                    default_join="round", pattern_phase="page", text_outline_inset=0.5,
                    custom_path_strokes="stated", text_size_grid=300, first_baseline="descent",
                    autofit="fit", kerning=_kerning.WORD)
