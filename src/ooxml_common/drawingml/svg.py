"""What the DrawingML renderers need from the SVG document they write into.

:mod:`~ooxml_common.drawingml.fill` and :mod:`~ooxml_common.drawingml.effect` return
*attribute strings*, and anything that needs a ``<defs>`` entry -- a gradient, a pattern,
a marker, a filter -- is registered on the caller's document and referenced by
``url(#id)``.  That document is the consumer's: pptx2svg's ``RenderContext`` carries a
text measurer and font mapping besides, and docx2svg has its own page writer.  So the
renderers here ask for no more than :class:`SvgDefs` -- a way to mint an id and a place to
put a definition -- and :class:`Defs` is the smallest thing that is one.

``num`` is pptx2svg's number formatting for SVG attribute values, moved here from
``pptx2svg.render.context`` (which re-exports it) because every renderer here writes
through it: changing it changes every byte of their output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@runtime_checkable
class SvgDefs(Protocol):
    """Where a renderer registers ``<defs>`` entries, and how it names them."""

    def new_id(self, prefix: str) -> str:
        """A document-unique id beginning with ``prefix``."""
        ...

    def add_def(self, definition: str) -> None:
        """Declare ``definition`` (one element's markup) in the document's ``<defs>``."""
        ...


@dataclass
class Defs:
    """A minimal :class:`SvgDefs`: definitions collected in order, ids from a counter.

    A counter rather than random ids so the same input always produces the same bytes,
    which is what makes output diffable and snapshot-testable -- pptx2svg's
    ``RenderContext`` mints them the same way, ``<prefix>-<n>``.
    """

    defs: list[str] = field(default_factory=list)
    _next_id: int = 0

    def new_id(self, prefix: str) -> str:
        self._next_id += 1
        return f"{prefix}-{self._next_id}"

    def add_def(self, definition: str) -> None:
        if definition:
            self.defs.append(definition)


def num(value: float) -> str:
    """Compact number formatting for SVG attribute values."""
    rounded = round(value, 3)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:g}"
