"""Where a run's inherited text properties come from: the chain PowerPoint walks, as measured.

A run that states no colour, size or face takes each from the first layer below it that
states one.  Which layers there are depends on what holds the text, and this module is the
one place that says so -- pptx2svg draws with it and pptx-agent reports with it, so the
colour a check measures is the colour the renderer draws.

**Text in a shape that is not a placeholder** -- a text box, an autoshape, a group's
member -- walks:

1. the run (``a:rPr``);
2. the paragraph (``a:pPr/a:defRPr``);
3. the shape's own ``a:lstStyle``, at the paragraph's level;
4. the shape's ``p:style/a:fontRef`` (its colour; its ``idx`` names the face);
5. the presentation's ``p:defaultTextStyle``, at the paragraph's level;

and then nothing: black, 18 pt.  The master's ``p:otherStyle`` is **not** on the way, for
colour, size or face.  Measured on PowerPoint 16.106 (Mac), 23 October 2026, with made-up
decks giving every candidate layer its own colour and size, read three ways that agreed on
every probe -- the slide show on screen, the PDF export's text colour, and AppleScript's
``font color``/``font size``/``font name`` of the text range:

* ``defaultTextStyle`` ``defPPr`` black and ``lvl1pPr``..``lvl9pPr`` white, ``otherStyle``
  ``tx1``: a text box draws **white** (the production report, on Windows, is the same);
* each level its own colour and size in both styles: a level-1 paragraph draws in
  ``defaultTextStyle``'s ``lvl2pPr`` colour and size, never ``otherStyle``'s;
* ``defaultTextStyle`` with no colour, ``otherStyle`` with one: black; a face only in
  ``otherStyle`` (Georgia): Arial, as for text nothing names a face for;
* ``fontRef`` ``lt1`` over a ``defaultTextStyle`` colour: white; the shape's list style
  over the ``fontRef``: the list style's;
* a style level that states only a size leaves the colour to the layers below: each
  property is resolved on its own;
* neither a list style's nor ``defaultTextStyle``'s ``defPPr`` is a fallback for a level the
  style does not have: a level-3 paragraph whose ``defaultTextStyle`` stops at ``lvl3pPr``
  draws black at 18 pt, whatever ``defPPr`` says;
* a theme colour goes through the slide's colour map (master, layout, slide override).

**A placeholder** walks its layout's and its master's placeholders' list styles and then the
master's ``titleStyle``, ``bodyStyle`` or ``otherStyle`` (by placeholder type) before
``defaultTextStyle``.  **A table cell** walks its table style's ``a:tcTxStyle`` and the
master's ``otherStyle`` (a cell does take ``otherStyle``'s size: measured, 28 pt where
``defaultTextStyle`` said 20) before ``defaultTextStyle``.  Neither was re-measured here:
both keep the order the renderer drew them with, and the ``defPPr`` fallback with it.

The layer names are also the short *source* names tools report ("defaultTextStyle lvl1",
"style fontRef", "master bodyStyle lvl2"): :func:`source_name`.
"""

from __future__ import annotations

from typing import Any, Iterable

RUN = "run"
PARAGRAPH = "paragraph"
LIST_STYLE = "list style"
LAYOUT = "layout"
MASTER = "master"
FONT_REF = "style fontRef"
TABLE_STYLE = "table style"
DEFAULT_TEXT_STYLE = "defaultTextStyle"
#: The source of a value nothing on the way states.
NOTHING = "default"

#: What a run is drawn in when nothing on the way states it.
DEFAULT_COLOR = "000000"
DEFAULT_SIZE = 18.0

_TITLE = frozenset({"title", "ctrTitle"})
_BODY = frozenset({"body", "subTitle", "obj"})

#: Kinds of text holder, by the chain they walk.
SHAPE = "shape"
PLACEHOLDER = "placeholder"
TABLE_CELL = "table cell"

#: Layers that hold one ``lvl<n>pPr`` per outline level.
_LEVELLED = frozenset({LIST_STYLE, LAYOUT, MASTER, DEFAULT_TEXT_STYLE,
                       "master titleStyle", "master bodyStyle", "master otherStyle"})


def master_text_style(placeholder_type: str | None) -> str:
    """The master's ``p:txStyles`` child a placeholder of ``placeholder_type`` takes its
    levels from: ``"titleStyle"``, ``"bodyStyle"`` or ``"otherStyle"`` (an untyped
    placeholder is a body one, ``obj``)."""
    kind = placeholder_type or "obj"
    if kind in _TITLE:
        return "titleStyle"
    return "bodyStyle" if kind in _BODY else "otherStyle"


def holder_kind(placeholder_type: str | None, *, table_cell: bool = False,
                placeholder: bool | None = None) -> str:
    """:data:`SHAPE`, :data:`PLACEHOLDER` or :data:`TABLE_CELL`.  ``placeholder`` defaults
    to whether a placeholder type is given."""
    if table_cell:
        return TABLE_CELL
    is_placeholder = placeholder if placeholder is not None else placeholder_type is not None
    return PLACEHOLDER if is_placeholder else SHAPE


def inherited_layers(placeholder_type: str | None = None, *, table_cell: bool = False,
                     placeholder: bool | None = None) -> tuple[str, ...]:
    """The layers below the run and its paragraph, nearest first, for text held by a
    placeholder of ``placeholder_type``, a table cell, or (neither) a plain shape."""
    kind = holder_kind(placeholder_type, table_cell=table_cell, placeholder=placeholder)
    if kind == SHAPE:
        return (LIST_STYLE, FONT_REF, DEFAULT_TEXT_STYLE)
    if kind == TABLE_CELL:
        return (LIST_STYLE, TABLE_STYLE, "master otherStyle", DEFAULT_TEXT_STYLE)
    return (LIST_STYLE, LAYOUT, MASTER, f"master {master_text_style(placeholder_type)}",
            DEFAULT_TEXT_STYLE)


def layers(placeholder_type: str | None = None, *, table_cell: bool = False,
           placeholder: bool | None = None) -> tuple[str, ...]:
    """The whole chain, nearest first: the run, the paragraph, :func:`inherited_layers`."""
    return (RUN, PARAGRAPH) + inherited_layers(placeholder_type, table_cell=table_cell,
                                               placeholder=placeholder)


def default_paragraph_fallback(kind: str) -> bool:
    """Whether a style's ``defPPr`` stands in for a level it does not have.  Measured not to
    for a plain shape's list style and ``defaultTextStyle``; kept, unmeasured, for
    placeholders and table cells."""
    return kind != SHAPE


def is_levelled(layer: str) -> bool:
    """Whether ``layer`` is a list style with one entry per outline level."""
    return layer in _LEVELLED


def source_name(layer: str, level: int = 0) -> str:
    """The short name of where a value comes from: the layer, with the 1-based level for
    a list style (``"defaultTextStyle lvl1"`` for a level-0 paragraph)."""
    return f"{layer} lvl{level + 1}" if layer in _LEVELLED else layer


def first_stated(candidates: Iterable[tuple[str, Any]]) -> tuple[Any, str]:
    """``(value, layer)`` of the first candidate whose value is not ``None``, nearest
    first; ``(None, NOTHING)`` when none states one."""
    for layer, value in candidates:
        if value is not None:
            return value, layer
    return None, NOTHING


__all__ = ["DEFAULT_COLOR", "DEFAULT_SIZE", "DEFAULT_TEXT_STYLE", "FONT_REF", "LAYOUT",
           "LIST_STYLE", "MASTER", "NOTHING", "PARAGRAPH", "PLACEHOLDER", "RUN", "SHAPE",
           "TABLE_CELL", "TABLE_STYLE", "default_paragraph_fallback", "first_stated",
           "holder_kind", "inherited_layers", "is_levelled", "layers", "master_text_style",
           "source_name"]
