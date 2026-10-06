"""How much room a text body takes: its lines, where they break, and how tall they stack.

The layout :mod:`~ooxml_common.drawingml.textbody` draws with, without drawing: the frame
shrunk to the geometry's text rectangle, turned for vertical text, less its insets; each
paragraph broken into lines by :func:`~ooxml_common.drawingml.wrap.wrap_paragraph`; each
line as tall as its paragraph's tallest run (``a:lnSpc`` applied); the paragraphs' space
before and after added, not collapsed, as PowerPoint does::

    from ooxml_common.drawingml.textmeasure import measure_shape_text, measure_text

    measured = measure_shape_text(shape, context)       # a scene ShapeElement
    if measured.needed > measured.available:
        print("overflows by", measured.needed - measured.available, "px")
    for line in measured.lines:
        print(line.paragraph, line.start, line.end, line.width, line.height)

    measure_text("Quarterly results", "Arial", 24, width=300).lines[0].width

Lengths are CSS pixels (96 to the inch, :func:`~ooxml_common.units.emu_to_px` and
:func:`~ooxml_common.units.px_to_emu` convert); font sizes are points.

**By default it measures what autofit measures.**  The height is
:func:`~ooxml_common.drawingml.textbody._estimate_text_height`'s, number for number: the
estimate a body is anchored by, ``spAutoFit`` grows a shape with and ``normAutofit``'s
fitting shrinks text with.  Each paragraph wraps to the text width less its ``marL``, as
the drawing pass and PowerPoint wrap it (until ooxml-common 0.5 the estimate, and so this,
wrapped every paragraph to the full width).  The estimate keeps one simplification: a
paragraph that does not wrap is one line, breaks and all.  With ``as_drawn=True`` that
does not hold either: a paragraph that does not wrap still breaks at each line break
(``a:br``), as PowerPoint draws it.  Either way a multi-column body's height is its
one-column height divided by the columns.  A stored ``fontScale`` scales each size exactly, not rounded to the point as
:func:`~ooxml_common.drawingml.textbody._stored_autofit` rounds it for drawing, and
``lnSpcReduction`` takes a fraction off each line's height rather than percentage points
off its spacing.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..units import emu_to_px, px_to_emu
from . import scene as m
from .context import RenderContext
from .shape import _outline_width, text_geometry
from .textbody import (
    _default_font_size,
    _default_line_height_ratio,
    _line_height_px,
    _paragraph_natural_height,
    _resolve_dimensions,
    _segment_width,
    _spacing_px,
    _text_area,
)
from .wrap import LineSegment, wrap_paragraph

_WHITESPACE = " \t\n\r"


@dataclass(frozen=True)
class MeasuredLine:
    """One line of a measured paragraph.

    ``start`` and ``end`` are offsets into the paragraph's text (its runs' text joined):
    the line is ``text[start:end]``, and what lies between one line's ``end`` and the next
    one's ``start`` -- the space a break consumed, trailing spaces, a line break -- draws
    nothing.  ``width`` is the line's advance in px, kerning included, without the
    paragraph's bullet or indent; ``height`` the line's pitch in px, ``a:lnSpc`` applied.
    """

    paragraph: int
    start: int
    end: int
    text: str
    width: float
    height: float


@dataclass(frozen=True)
class MeasuredParagraph:
    """One paragraph: its ``lines`` (an empty paragraph has one, of no text), the
    ``line_height`` each takes (px), its single-line ``natural_height`` before ``a:lnSpc``
    (pt), its ``space_before`` and ``space_after`` (px; the first paragraph's space before
    is not counted in the height, as PowerPoint does not draw it), and the effective
    ``sizes`` (pt, scale applied, each once, smallest first) of the runs that hold text.
    ``width`` is what its lines wrap to, px: the text width less its ``marL``."""

    index: int
    text: str
    lines: tuple[MeasuredLine, ...]
    line_height: float
    natural_height: float
    space_before: float
    space_after: float
    sizes: tuple[float, ...]
    width: float

    @property
    def has_text(self) -> bool:
        return bool(self.sizes)


@dataclass(frozen=True)
class TextBodyMeasure:
    """A text body measured in its frame.

    ``width`` and ``height`` are the text area's (the frame, in its geometry's text
    rectangle, turned for vertical text) and ``insets`` its ``(left, top, right, bottom)``
    insets, px; ``text_width`` is what each line wraps to (per column), ``columns`` how
    many there are and ``wraps`` whether lines wrap at all.  ``default_size`` (pt) is the
    size a run without one takes and ``font_scale`` the scale every size was multiplied by.

    ``text_height`` is the height the lines and the spacing between paragraphs take, px
    (0 without text); ``needed`` adds the top and bottom insets (0 without text), and
    ``available`` is the text area's height -- the text fits when ``needed`` is no more.

    ``area_left`` and ``area_top`` are where the text area's top-left corner sits in the
    frame, px: the geometry's text rectangle's offset (a ``roundRect``'s clear of its
    corners, an ``ellipse``'s inscribed rectangle) -- for :func:`measure_shape_text`, in
    the shape's own frame, a SmartArt shape's text box (``dsp:txXfrm``) offset included.
    The insets are inside the area, so the first line starts ``area_left + insets[0]``
    from the frame's left.
    """

    paragraphs: tuple[MeasuredParagraph, ...]
    width: float
    height: float
    insets: tuple[float, float, float, float]
    text_width: float
    columns: int
    wraps: bool
    default_size: float
    font_scale: float
    text_height: float
    needed: float
    area_left: float = 0.0
    area_top: float = 0.0

    @property
    def area_offset(self) -> tuple[float, float]:
        """``(area_left, area_top)``, px."""
        return self.area_left, self.area_top

    @property
    def available(self) -> float:
        return self.height

    @property
    def overflow(self) -> float:
        """How much more height the text needs than it has, px; 0 when it fits."""
        return max(0.0, self.needed - self.available)

    @property
    def has_text(self) -> bool:
        return any(paragraph.has_text for paragraph in self.paragraphs)

    @property
    def lines(self) -> tuple[MeasuredLine, ...]:
        """Every paragraph's lines, in order."""
        return tuple(line for paragraph in self.paragraphs for line in paragraph.lines)

    @property
    def tallest_line(self) -> float:
        """The greatest line height of any paragraph with text, px; 0 without text."""
        return max((p.line_height for p in self.paragraphs if p.has_text), default=0.0)


def measure_text_body(
    text_body: m.TextBody,
    frame: m.Transform,
    context: RenderContext | None = None,
    *,
    geometry: tuple | None = None,
    outline_width: float = 0.0,
    font_scale: float | None = None,
    as_drawn: bool = False,
) -> TextBodyMeasure:
    """Measure ``text_body`` laid out in ``frame`` (EMU, in slide units: a shape inside a
    group at its on-slide size), as the shape's text rectangle ``geometry``
    (:func:`~ooxml_common.drawingml.shape.text_geometry`) and the context's
    :class:`~ooxml_common.drawingml.rules.DrawingRules` place it.

    ``font_scale`` multiplies every size; ``None`` takes what the body stores --
    ``normAutofit``'s ``fontScale``, else 1 -- which is what PowerPoint draws a file it has
    not re-fitted at.  ``context`` supplies the text measurer (the generated tables by
    default).  ``as_drawn`` lays each paragraph out as it is drawn rather than as autofit
    estimates it (the module's doc says how the two differ)."""
    context = context or RenderContext()
    properties = text_body.body_properties
    area, area_left, area_top = _text_area(frame, geometry, outline_width, context.rules)
    dims = _resolve_dimensions(properties, emu_to_px(area.extent_width), emu_to_px(area.extent_height))
    columns = max(1, properties.num_col)
    text_width = (dims.width - dims.margin_left - dims.margin_right) / columns
    paragraphs = text_body.paragraphs
    if font_scale is None:
        font_scale = properties.font_scale if properties.auto_fit == "normAutofit" else 1.0
    default_size = _default_font_size(paragraphs)
    wraps = properties.wrap != "none"
    reduction = properties.ln_spc_reduction

    # The sum below is _estimate_text_height's, term for term and in its order, so that the
    # two agree to the last bit (tests/test_textmeasure.py holds them to it).
    total = 0.0
    default_ratio = _default_line_height_ratio(paragraphs, context)
    previous_space_after = 0.0
    scaled_default = default_size * font_scale
    measured: list[MeasuredParagraph] = []
    for index, paragraph in enumerate(paragraphs):
        has_text = any(run.text for run in paragraph.runs)
        natural = _paragraph_natural_height(paragraph, default_size, font_scale, context, default_ratio)
        line_height = _line_height_px(paragraph, natural, reduction)
        width = text_width - emu_to_px(paragraph.properties.margin_left or 0)
        if wraps and has_text:
            wrapped = [line.segments for line in
                       wrap_paragraph(paragraph, width, scaled_default, font_scale, context.measurer)]
        elif has_text and as_drawn:
            wrapped = _broken_at_line_breaks(paragraph)
        else:
            wrapped = [[LineSegment(run.text, run.properties) for run in paragraph.runs if run.text]]
        total += len(wrapped) * line_height
        space_before = _spacing_px(paragraph.properties.space_before, natural)
        if index > 0:
            total += previous_space_after + space_before
        space_after = _spacing_px(paragraph.properties.space_after, natural)
        previous_space_after = space_after
        measured.append(_paragraph(index, paragraph, wrapped, width, line_height, natural, space_before,
                                   space_after, default_size, font_scale, context,
                                   strip=has_text and as_drawn and not wraps))

    has_text = any(paragraph.has_text for paragraph in measured)
    text_height = total if has_text else 0.0
    if columns > 1 and properties.vert == "horz":
        text_height /= columns
    insets = dims.margin_top + dims.margin_bottom
    return TextBodyMeasure(
        paragraphs=tuple(measured),
        width=dims.width,
        height=dims.height,
        insets=(dims.margin_left, dims.margin_top, dims.margin_right, dims.margin_bottom),
        text_width=text_width,
        columns=columns,
        wraps=wraps,
        default_size=default_size,
        font_scale=font_scale,
        text_height=text_height,
        needed=text_height + insets if has_text else 0.0,
        area_left=emu_to_px(area_left),
        area_top=emu_to_px(area_top),
    )


def measure_shape_text(
    shape: m.ShapeElement,
    context: RenderContext | None = None,
    *,
    scale: tuple[float, float] = (1.0, 1.0),
    font_scale: float | None = None,
    as_drawn: bool = False,
) -> TextBodyMeasure | None:
    """Measure a scene shape's text in its frame: its text box (SmartArt's ``dsp:txXfrm``)
    or its own, in its geometry's text rectangle; ``None`` for a shape without a text body.

    ``scale`` is the product of the enclosing groups' ``ext``/``chExt`` ratios, ``(x,
    y)``: the frame grows with the group and the type inside it does not
    (:attr:`~ooxml_common.drawingml.context.RenderContext.group_scale`).  ``font_scale``
    and ``as_drawn`` are :func:`measure_text_body`'s; the area's offsets are in the
    shape's frame (:class:`TextBodyMeasure`)."""
    if shape.text_body is None:
        return None
    box = shape.text_transform or shape.transform
    box = replace(box, extent_width=box.extent_width * scale[0], extent_height=box.extent_height * scale[1])
    geometry = text_geometry(shape) if shape.text_transform is None else None
    measured = measure_text_body(shape.text_body, box, context, geometry=geometry,
                                 outline_width=_outline_width(shape), font_scale=font_scale,
                                 as_drawn=as_drawn)
    if shape.text_transform is None:
        return measured
    # A SmartArt shape's text box sits at its own offset in the shape's frame.
    frame = shape.transform
    return replace(measured,
                   area_left=measured.area_left + emu_to_px((box.offset_x - frame.offset_x) * scale[0]),
                   area_top=measured.area_top + emu_to_px((box.offset_y - frame.offset_y) * scale[1]))


def measure_text(
    text: str,
    font: str | None = None,
    size: float = 18.0,
    width: float | None = None,
    *,
    bold: bool = False,
    italic: bool = False,
    east_asian_font: str | None = None,
    line_spacing: float | None = None,
    insets: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
    context: RenderContext | None = None,
) -> TextBodyMeasure:
    """Measure a plain string in ``font`` at ``size`` points in a box ``width`` px wide (no
    wrapping when ``None``), laid out as drawn (``as_drawn``): each ``\\n`` starts a
    paragraph and each ``\\v`` breaks a line within one, as PowerPoint's text does.
    ``insets`` are the box's ``(left, top, right, bottom)``, px, inside ``width``; none by
    default.

    ``line_spacing`` is a multiple of the font's line height (``1.5``); ``None`` is single.
    ``font`` is a typeface name as a run states it (``"Calibri"``); the measurer maps it as
    it maps any run's, so a face it has no table for is measured as its substitute.  For
    example::

        measured = measure_text("Revenue grew 12 % in the third quarter", "Arial", 18, 240)
        len(measured.lines), measured.text_height       # lines, px
    """
    run = m.RunProperties(font_size=size, font_family=font, font_family_ea=east_asian_font,
                          bold=bold, italic=italic)
    spacing = None if line_spacing is None else m.PercentSpacing(round(line_spacing * 100000))
    paragraphs = [m.Paragraph(runs=[m.TextRun(line.replace("\v", "\n"), run)] if line else [],
                              properties=m.ParagraphProperties(line_spacing=spacing),
                              end_para_run_properties=run)
                  for line in text.split("\n")]
    left, top, right, bottom = insets
    body = m.BodyProperties(margin_left=px_to_emu(left), margin_top=px_to_emu(top),
                            margin_right=px_to_emu(right), margin_bottom=px_to_emu(bottom),
                            wrap="square" if width is not None else "none")
    frame = m.Transform(extent_width=0.0 if width is None else px_to_emu(width))
    return measure_text_body(m.TextBody(paragraphs=paragraphs, body_properties=body), frame, context,
                             as_drawn=True)


def _broken_at_line_breaks(paragraph: m.Paragraph) -> list[list[LineSegment]]:
    """A paragraph that does not wrap, as lines at its line breaks: each run's text split
    at ``\\n``, a piece per run on each line."""
    lines: list[list[LineSegment]] = [[]]
    for run in paragraph.runs:
        for position, part in enumerate(run.text.split("\n")):
            if position:
                lines.append([])
            if part:
                lines[-1].append(LineSegment(part, run.properties))
    return lines


def _paragraph(index, paragraph, wrapped, wrap_width, line_height, natural, space_before, space_after,
               default_size, font_scale, context, *, strip: bool = False) -> MeasuredParagraph:
    text = "".join(run.text for run in paragraph.runs)
    lines: list[MeasuredLine] = []
    cursor = 0
    for segments in wrapped:
        line_text = "".join(segment.text for segment in segments)
        if strip:
            # A line at a break keeps the width of its trailing spaces but not their text.
            line_text = line_text.rstrip()
        # A line is a stretch of the paragraph's text; between two, only what a break
        # consumed is skipped: white space, and at most one line break.
        while (lines or line_text) and cursor < len(text) and text[cursor] in _WHITESPACE \
                and not (line_text and text.startswith(line_text, cursor)):
            cursor += 1
            if text[cursor - 1] == "\n":
                break
        start = cursor
        cursor = start + len(line_text)
        width = sum(_segment_width(segment, default_size, font_scale, context) for segment in segments)
        lines.append(MeasuredLine(index, start, cursor, line_text, width, line_height))
    sizes = tuple(sorted({round((run.properties.font_size or default_size) * font_scale, 2)
                          for run in paragraph.runs if run.text}))
    return MeasuredParagraph(index, text, tuple(lines), line_height, natural, space_before,
                             space_after, sizes, wrap_width)


__all__ = ["MeasuredLine", "MeasuredParagraph", "TextBodyMeasure", "measure_shape_text",
           "measure_text", "measure_text_body"]
