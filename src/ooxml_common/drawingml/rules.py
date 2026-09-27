"""Where Word and PowerPoint measurably draw the same DrawingML differently.

The renderers here were moved from pptx2svg, where every rule was measured against
PowerPoint -- or, where it was not measured, is pptx2svg's long-standing behaviour, which
its fidelity baselines hold byte for byte.  docx2svg measured the same markup in Word
(its ``tools/make_dml_probe.py``: 73 pages of colour transforms, gradients, patterns,
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
      gradient of exactly two stops, at 0 and 100%, blends in linear light (Word writes
      it in a linear profile), any other in sRGB.
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
    """

    name: str
    color: ColorRules
    gradients: str = "bounding-box"
    dashes: str = "stroke-width"
    arrowheads: str = "markers"
    default_join: str | None = None
    pattern_phase: str = "shape"


#: PowerPoint, as pptx2svg reproduces it.  The default everywhere here.
POWERPOINT = DrawingRules("powerpoint", color.POWERPOINT)

#: Word, as docx2svg measured it.
WORD = DrawingRules("word", color.WORD, gradients="office", dashes="office", arrowheads="office",
                    default_join="round", pattern_phase="page")
