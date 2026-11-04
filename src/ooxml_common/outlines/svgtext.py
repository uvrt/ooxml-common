"""An SVG's ``<text>`` elements drawn as glyph outlines, as resvg would draw them.

Each ``<text>`` becomes a ``<g>`` with the element's own attributes but the text ones
(its transform, filter, clip, opacity and identity attributes kept), holding per span
its underline, its glyphs and its line-through, in usvg's order.  A glyph drawn with an
opaque fill and no stroke is a ``<use>`` of a path in ``<defs>`` -- one definition per
outline, under an id made of it (:func:`glyph_id`), so repeated letters cost one reference
each, and the references of consecutive spans of one paint and size share a group; any
other span's glyphs are one ``<path>``, as resvg makes them, so a stroke or a translucent
fill paints the run once.  The definitions can be a set shared by many pages
(``outline_text(glyphs=)``, :func:`glyph_sheet`, :func:`embed_glyphs`).  Positions follow usvg's layout (``ooxml_common.outlines`` names the
version): text chunks at each absolutely positioned character, ``text-anchor`` over the
chunk's advance, ``dx``/``dy``, ``baseline-shift``, ``letter-spacing``,
``word-spacing``, ``textLength`` with ``lengthAdjust``, and each chunk shaped whole
with every span's face (:mod:`.shaper`), the first span's glyphs replaced by the later
spans' for their own characters.

A text this module does not draw as resvg would is left as it is and reported
(:class:`KeptText`): right-to-left or complex-script text, a face with colour or CFF2
glyphs, ``textPath``, ``rotate``, vertical writing, a ``<style>`` sheet, a span whose
font-family no loaded face answers to.
"""

from __future__ import annotations

import hashlib
import re
import struct
import threading
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Callable

from .face import OutlineFace, path_data
from .fontdb import Database, FontSetup, HeaderFace, database
from .shaper import shape, shapeable

__all__ = ["KeptText", "Outlined", "embed_glyphs", "glyph_id", "glyph_sheet", "outline_text"]

_SVG = "http://www.w3.org/2000/svg"
_NS = "{" + _SVG + "}"
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
_XLINK = "{http://www.w3.org/1999/xlink}"

Matrix = tuple[float, float, float, float, float, float]
_IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _mul(m: Matrix, n: Matrix) -> Matrix:
    """``m`` after ``n``: the point goes through ``n`` first."""
    a, b, c, d, e, f = m
    a2, b2, c2, d2, e2, f2 = n
    return (a * a2 + c * b2, b * a2 + d * b2, a * c2 + c * d2, b * c2 + d * d2,
            a * e2 + c * f2 + e, b * e2 + d * f2 + f)


def _translate(x: float, y: float) -> Matrix:
    return (1.0, 0.0, 0.0, 1.0, x, y)


def _apply(m: Matrix, x: float, y: float) -> tuple[float, float]:
    return m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]


@dataclass(frozen=True)
class KeptText:
    """A ``<text>`` left as text: why (``reason``), the face or family it names and up
    to eight of its characters."""

    reason: str
    family: str
    sample: str

    def message(self) -> str:
        return f"{self.family or 'text'}: {self.reason} ({self.sample!r} kept as text)"


@dataclass
class Outlined:
    """The SVG with its text as outlines, and the texts left as text."""

    svg: str
    kept: list[KeptText] = field(default_factory=list)
    #: Texts drawn as outlines.
    outlined: int = 0
    #: Characters no loaded face has, drawn as the face's missing-glyph box, as resvg does.
    missing: list[str] = field(default_factory=list)
    #: The ids of the glyph definitions the document uses, in the order of their first use.
    glyphs: list[str] = field(default_factory=list)


class _Keep(Exception):
    def __init__(self, reason: str, family: str = "") -> None:
        super().__init__(reason)
        self.reason, self.family = reason, family


# --------------------------------------------------------------------------------------
# Styles
# --------------------------------------------------------------------------------------

#: Properties that inherit (what a tspan takes from its text and the text from its group).
_INHERITED = frozenset({
    "fill", "fill-opacity", "fill-rule", "stroke", "stroke-width", "stroke-opacity", "stroke-linejoin",
    "stroke-linecap", "stroke-miterlimit", "stroke-dasharray", "stroke-dashoffset", "paint-order",
    "visibility", "font-family", "font-size", "font-weight", "font-style", "font-stretch", "font-variant",
    "font-kerning", "font-variation-settings", "font-optical-sizing", "font-feature-settings",
    "text-anchor", "letter-spacing", "word-spacing", "writing-mode", "direction", "kerning",
    "text-rendering", "dominant-baseline", "color",
})
#: Attributes of text and its spans that the outlines replace.
_TEXT_ONLY = frozenset({
    "x", "y", "dx", "dy", "rotate", "textLength", "lengthAdjust", "font-family", "font-size",
    "font-weight", "font-style", "font-stretch", "font-variant", "font-kerning", "font-variation-settings",
    "font-optical-sizing", "font-feature-settings", "font", "text-anchor", "letter-spacing", "word-spacing",
    "text-decoration", "text-decoration-style", "text-decoration-line", "text-decoration-color",
    "baseline-shift", "dominant-baseline", "alignment-baseline", "kerning", "writing-mode", "direction",
    "unicode-bidi", "text-rendering", "white-space", "font-synthesis", "glyph-orientation-vertical",
    _XML_SPACE,
})
#: Paint a span's glyphs take from the spans around them.
_PAINT = ("fill", "fill-opacity", "stroke", "stroke-width", "stroke-opacity", "stroke-linejoin",
          "stroke-linecap", "stroke-miterlimit", "stroke-dasharray", "stroke-dashoffset", "paint-order",
          "color")


def _style(attrib: dict) -> dict:
    """An element's presentation attributes with its ``style`` declarations over them."""
    out = {key: value for key, value in attrib.items() if key != "style"}
    style = attrib.get("style")
    if style:
        for declaration in style.split(";"):
            name, _, value = declaration.partition(":")
            name, value = name.strip(), value.strip()
            if name and value:
                out[name] = value
    return out


class _Node:
    """An element of a text: its local name and its (style-merged) properties."""

    __slots__ = ("tag", "props", "parent", "element")

    def __init__(self, tag: str, props: dict, parent: "_Node | None", element: ET.Element | None) -> None:
        self.tag, self.props, self.parent, self.element = tag, props, parent, element

    def chain(self):
        node: _Node | None = self
        while node is not None:
            yield node
            node = node.parent

    def find(self, name: str, default=None):
        for node in self.chain():
            if name in node.props:
                value = node.props[name]
                if value != "inherit":
                    return value
        return default


def _number(value: str | None, default: float | None = None, font_size: float = 12.0) -> float | None:
    if value is None:
        return default
    text = value.strip()
    match = re.fullmatch(r"([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*(px|pt|em|%)?", text)
    if not match:
        return default
    number = float(match.group(1))
    unit = match.group(2)
    if unit == "pt":
        number *= 4.0 / 3.0
    elif unit == "em":
        number *= font_size
    elif unit == "%":
        return default
    return number


def _numbers(value: str | None) -> list[float] | None:
    if value is None:
        return None
    out = []
    for part in re.split(r"[\s,]+", value.strip()):
        if not part:
            continue
        found = _number(part)
        if found is None:
            return None
        out.append(found)
    return out


def _font_size(node: _Node) -> float:
    """usvg's ``resolve_font_size``: the nearest stated size, relative ones against
    their parent's; 12 at the root."""
    nodes = list(node.chain())[::-1]
    size = 12.0
    for n in nodes:
        value = n.props.get("font-size")
        if value is None:
            continue
        value = value.strip()
        named = {"xx-small": 9.0, "x-small": 10.0, "small": 13.0, "medium": 16.0, "large": 18.0,
                 "x-large": 24.0, "xx-large": 32.0}
        if value in named:
            size = named[value]
        elif value.endswith("%"):
            try:
                size = size * float(value[:-1]) / 100.0
            except ValueError:
                pass
        elif value == "larger":
            size *= 1.2
        elif value == "smaller":
            size /= 1.2
        else:
            found = _number(value, None, size)
            if found is not None:
                size = found
    return size


def _font_weight(node: _Node) -> int:
    weight = 400
    for n in list(node.chain())[::-1]:
        value = n.props.get("font-weight", "")
        if value == "normal":
            weight = 400
        elif value == "bold":
            weight = 700
        elif value in ("100", "200", "300", "400", "500", "600", "700", "800", "900"):
            weight = int(value)
        elif value == "bolder":
            weight = max(100, min(900, weight + (300 if weight == 400 else 100)))
        elif value == "lighter":
            weight = max(100, min(900, weight - (200 if weight == 400 else 100)))
    return weight


_STRETCH = {"ultra-condensed": 1, "extra-condensed": 2, "condensed": 3, "narrower": 3, "semi-condensed": 4,
            "semi-expanded": 6, "expanded": 7, "wider": 7, "extra-expanded": 8, "ultra-expanded": 9}
_WDTH = {1: 50.0, 2: 62.5, 3: 75.0, 4: 87.5, 5: 100.0, 6: 112.5, 7: 125.0, 8: 150.0, 9: 200.0}


# --------------------------------------------------------------------------------------
# Characters, positions, chunks, spans
# --------------------------------------------------------------------------------------

@dataclass
class _Span:
    start: int
    end: int
    node: _Node
    font_key: tuple
    font_size: float
    anchor: str
    kerning: bool
    letter_spacing: float
    word_spacing: float
    text_length: float | None
    length_adjust: str
    visible: bool
    baseline_shift: list
    decorations: dict
    face: "HeaderFace | None" = None
    variations: tuple = ()


@dataclass
class _Chunk:
    x: float | None
    y: float | None
    text: str
    spans: list[_Span]


def _trim(text: str, preserve: bool) -> str:
    out = []
    previous = "0"
    for char in text:
        if char in "\r\n\t":
            char = " "
        if not preserve and char == " " and previous == " ":
            continue
        previous = char
        out.append(char)
    return "".join(out)


class _TextNode:
    __slots__ = ("text", "owner", "depth")

    def __init__(self, text: str, owner: _Node, depth: int) -> None:
        self.text, self.owner, self.depth = text, owner, depth


def _preserve(node: _Node, default: bool) -> bool:
    for n in node.chain():
        value = n.props.get(_XML_SPACE)
        if value is not None:
            return value == "preserve"
    return default


def _collect(element: ET.Element, node: _Node, depth: int, out: list[_TextNode], nodes: dict) -> None:
    preserve = _preserve(node, False)
    if element.text:
        out.append(_TextNode(_trim(element.text, preserve), node, depth))
    for child in element:
        tag = child.tag.rpartition("}")[2] if isinstance(child.tag, str) else ""
        if tag in ("tspan", "a"):
            child_node = _Node("tspan" if tag == "tspan" else "a", _style(child.attrib), node, child)
            nodes[id(child)] = child_node
            _collect(child, child_node, depth + 1, out, nodes)
        elif tag in ("textPath", "tref"):
            raise _Keep(f"<{tag}>")
        if child.tail:
            out.append(_TextNode(_trim(child.tail, preserve), node, depth))


def _trim_nodes(nodes: list[_TextNode], text_node: _Node) -> None:
    """usvg's ``trim_text_nodes``: leading, trailing and doubled spaces across nodes."""
    root_preserve = _preserve(text_node, False)
    if len(nodes) == 1:
        if not root_preserve:
            t = nodes[0].text
            if t == " ":
                nodes[0].text = ""
            elif len(t) >= 2:
                if t[0] == " ":
                    t = t[1:]
                if t and t[-1] == " ":
                    t = t[:-1]
                nodes[0].text = t
        return
    last_non_empty: _TextNode | None = None
    count = len(nodes) - 1
    for i in range(count):
        n1, n2 = nodes[i], nodes[i + 1]
        depth1, depth2 = n1.depth, n2.depth
        if not n1.text and last_non_empty is not None:
            n1 = last_non_empty
        p1, p2 = _preserve(n1.owner, root_preserve), _preserve(n2.owner, root_preserve)
        c1 = n1.text[:1]
        c2 = n1.text[-1:]
        c3 = n2.text[:1]
        c4 = n2.text[-1:]
        if depth1 < depth2:
            if c3 == " " and not p2:
                n2.text = n2.text[1:]
        else:
            if c2 == " " and c2 == c3:
                if not p1 and not p2:
                    n1.text = n1.text[:-1]
                elif p1 and not p2:
                    n2.text = n2.text[1:]
        if i == 0 and c1 == " " and not p1 and n1.text:
            n1.text = n1.text[1:]
        elif i == count - 1 and c4 == " " and n2.text and not p2:
            n2.text = n2.text[:-1]
        if i == count - 1 and c2 == " " and n1.text and not n2.text and n1.text.endswith(" "):
            n1.text = n1.text[:-1]
        if n1.text.strip():
            last_non_empty = n1


# --------------------------------------------------------------------------------------
# The outliner
# --------------------------------------------------------------------------------------

def _fmt(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _matrix_attr(m: Matrix) -> str:
    if m[0] == 1.0 and m[1] == 0.0 and m[2] == 0.0 and m[3] == 1.0:
        return f'x="{_fmt(m[4])}" y="{_fmt(m[5])}"'
    return f'transform="matrix({" ".join(_fmt(v) for v in m)})"'


#: Shaped runs across documents: a page of one-character chunks shapes few distinct ones.
_SHAPED: dict[tuple, list] = {}
_SHAPED_LOCK = threading.Lock()
_SHAPED_LIMIT = 50000


@dataclass
class _ShapedGlyph:
    id: int
    byte: int
    cluster_len: int
    dx: int
    dy: int
    width: int
    face: OutlineFace
    header: HeaderFace
    coords: tuple


@dataclass
class _Cluster:
    byte: int
    codepoint: int
    glyphs: list
    advance: float
    width: float
    ascent: float
    descent: float
    transform: Matrix = _IDENTITY
    has_shift: bool = False


class _Run:
    """A span's glyphs as references: the paint they share and each glyph's id and
    matrix; ``single`` where it is one glyph, or one-glyph spans joined (:func:`_joined`)."""

    __slots__ = ("paint", "placed", "single")

    def __init__(self, paint: str, placed: "list[tuple[str, Matrix]]", single: bool) -> None:
        self.paint, self.placed, self.single = paint, placed, single

    def linear(self) -> "tuple[float, float, float, float] | None":
        """The scale every glyph shares, ``None`` where they do not share one."""
        first = self.placed[0][1][:4]
        return first if all(m[:4] == first for _, m in self.placed) else None  # type: ignore[return-value]


#: Base 62 digits, for glyph ids.
_DIGITS62 = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
#: How many base 62 digits of its outline's hash a glyph's id takes (``g`` and six: about
#: 36 bits), more only where a shorter one is already another outline's.
ID_DIGITS = 6
_HASHES: dict[str, str] = {}
_HASHES_LOCK = threading.Lock()


def _hash62(data: str) -> str:
    """``data``'s SHA-1 in base 62 (27 digits), remembered across documents."""
    found = _HASHES.get(data)
    if found is not None:
        return found
    number = int.from_bytes(hashlib.sha1(data.encode("ascii")).digest(), "big")
    digits = []
    while number:
        number, digit = divmod(number, 62)
        digits.append(_DIGITS62[digit])
    found = "".join(digits).ljust(27, "0")
    with _HASHES_LOCK:
        if len(_HASHES) >= _SHAPED_LIMIT:
            _HASHES.clear()
        _HASHES[data] = found
    return found


class _Outliner:
    def __init__(self, fonts: Callable[[str | None], FontSetup], selectable: bool,
                 glyphs: "dict[str, str] | None" = None) -> None:
        self.fonts = fonts
        self.selectable = selectable
        #: Paint servers restated for the outlines.
        self.defs: dict[str, str] = {}
        #: Glyph definitions by id: the caller's, shared by its documents, or this one's.
        self.glyphs: dict[str, str] = glyphs if glyphs is not None else {}
        #: This document's glyph ids, in the order of their first use.
        self.used: dict[str, None] = {}
        self.kept: list[KeptText] = []
        self.missing: list[str] = []
        self.outlined = 0
        self._shaped: dict[tuple, list[_ShapedGlyph]] = {}
        self._databases: dict[str | None, Database] = {}
        self.document: str | None = None
        self.bbox: tuple[float, float, float, float] | None = None

    # -- faces ----------------------------------------------------------------------------

    def _database(self, family_value: str | None) -> Database:
        found = self._databases.get(family_value)
        if found is None:
            found = self._databases[family_value] = database(self.fonts(family_value))
        return found

    def _face(self, header: HeaderFace, family: str) -> OutlineFace:
        face = header.face()
        if face is None:
            raise _Keep("face not readable", family)
        if face.unsupported:
            raise _Keep(face.unsupported, family)
        return face

    def _coords(self, face: OutlineFace, span: _Span) -> tuple:
        if not face.axes:
            return ()
        settings = list(span.variations)
        if any(tag == b"opsz" for tag, *_ in face.axes) and not any(t == b"opsz" for t, _ in settings):
            settings.append((b"opsz", span.font_size))
        return face.coordinates(settings)

    # -- shaping --------------------------------------------------------------------------

    def _shape_with(self, text: str, header: HeaderFace, span: _Span, family: str) -> list[_ShapedGlyph]:
        face = self._face(header, family)
        coords = self._coords(face, span)
        key = (header.path, header.number, header.stamp, text, coords, span.kerning)
        found = self._shaped.get(key)
        if found is None:
            with _SHAPED_LOCK:
                found = _SHAPED.get(key)
        if found is not None:
            self._shaped[key] = found
            return found
        glyphs = shape(face, text, coords, kerning=span.kerning)
        out = []
        for k, g in enumerate(glyphs):
            end = glyphs[k + 1].cluster if k + 1 < len(glyphs) else len(text.encode("utf-8"))
            out.append(_ShapedGlyph(g.id, g.cluster, max(end - g.cluster, 0), g.x_offset, g.y_offset,
                                    g.x_advance, face, header, coords))
        self._shaped[key] = out
        with _SHAPED_LOCK:
            if len(_SHAPED) >= _SHAPED_LIMIT:
                _SHAPED.clear()
            _SHAPED[key] = out
        return out

    def _shape_text(self, text: str, span: _Span, db: Database, family: str) -> list[_ShapedGlyph]:
        base = span.face
        assert base is not None
        glyphs = self._shape_with(text, base, span, family)
        used = [base]
        encoded = text.encode("utf-8")
        while True:
            missing = next((g for g in glyphs if g.id == 0), None)
            if missing is None:
                break
            char = encoded[missing.byte:].decode("utf-8", "ignore")[:1]
            if not char:
                break
            fallback = db.fallback(ord(char), used)
            if fallback is None:
                break
            other = self._shape_with(text, fallback, span, family)
            if all(g.id != 0 for g in other):
                glyphs = other
                break
            if len(other) != len(glyphs):
                break
            glyphs = [o if g.id == 0 and o.id != 0 else g for g, o in zip(glyphs, other)]
            used.append(fallback)
        for g in glyphs:
            if g.id == 0:
                self.missing.append(encoded[g.byte:].decode("utf-8", "ignore")[:1])
        return glyphs

    def _process_chunk(self, chunk: _Chunk, family_of: Callable[[_Span], str]) -> list[_Cluster]:
        glyphs: list[_ShapedGlyph] = []
        for span in chunk.spans:
            if span.face is None:
                continue
            db = self._database(span.node.find("font-family"))
            new = self._shape_text(chunk.text, span, db, family_of(span))
            if not glyphs:
                glyphs = list(new)
                continue
            positions: set[int] = set()
            iterator = iter(new)
            for g in iterator:
                if not span.start <= g.byte < span.end:
                    continue
                idx = next((k for k, old in enumerate(glyphs) if old.byte == g.byte and k not in positions), None)
                if idx is None:
                    continue
                positions.add(idx)
                previous_len = glyphs[idx].cluster_len
                if previous_len < g.cluster_len:
                    for _ in range(1, g.cluster_len):
                        if idx + 1 < len(glyphs):
                            del glyphs[idx + 1]
                elif previous_len > g.cluster_len:
                    for j in range(1, previous_len):
                        extra = next(iterator, None)
                        if extra is not None:
                            glyphs.insert(idx + j, extra)
                glyphs[idx] = g
        clusters: list[_Cluster] = []
        k = 0
        encoded = chunk.text.encode("utf-8")
        while k < len(glyphs):
            byte = glyphs[k].byte
            end = k
            while end < len(glyphs) and glyphs[end].byte == byte:
                end += 1
            owner = next((s for s in chunk.spans if s.start <= byte < s.end), None)
            if owner is not None:
                clusters.append(self._form_cluster(glyphs[k:end], encoded, byte, owner.font_size))
            k = end
        return clusters

    @staticmethod
    def _form_cluster(glyphs: list[_ShapedGlyph], encoded: bytes, byte: int, font_size: float) -> _Cluster:
        x = 0
        width = advance = 0.0
        placed = []
        for g in glyphs:
            scale = font_size / g.face.units_per_em
            placed.append((g, x + g.dx, -g.dy, scale))
            x += g.width
            glyph_width = g.width * scale
            advance += glyph_width
            width = max(width, glyph_width)
        first = glyphs[0]
        scale = font_size / first.face.units_per_em
        metrics = first.face.metrics
        char = encoded[byte:].decode("utf-8", "ignore")[:1]
        return _Cluster(byte, ord(char) if char else 0, placed, advance, width,
                        metrics["ascent"] * scale, metrics["descent"] * scale)

    # -- one text -------------------------------------------------------------------------

    def outline(self, element: ET.Element, outer: list[dict]) -> str:
        ancestors: _Node | None = None
        for attrib in outer:
            ancestors = _Node("g", _style(attrib), ancestors, None)
        text_node = _Node("text", _style(element.attrib), ancestors, element)
        if text_node.find("writing-mode", "lr-tb") not in ("lr", "lr-tb", "rl", "rl-tb", "horizontal-tb"):
            raise _Keep("vertical writing")
        nodes: dict[int, _Node] = {id(element): text_node}
        texts: list[_TextNode] = []
        _collect(element, text_node, 0, texts, nodes)
        if any("rotate" in child.attrib for child in element.iter()):
            raise _Keep("rotate")
        _trim_nodes(texts, text_node)
        full = "".join(t.text for t in texts)
        sample = full.strip()[:8]
        if not full:
            return ""
        if not shapeable(full):
            raise _Keep("right-to-left or complex-script text", "")

        # Positions, per character (usvg's resolve_positions_list).
        total = len(full)
        xs: list[float | None] = [None] * total
        ys: list[float | None] = [None] * total
        dxs = [0.0] * total
        dys = [0.0] * total
        offset_of: dict[int, int] = {}
        counts: dict[int, int] = {}
        position = 0
        # Map each element to the characters under it.
        order: list[tuple[str, object]] = []

        def walk(el: ET.Element) -> None:
            order.append(("open", el))
            if el.text:
                order.append(("text", el))
            for child in el:
                tag = child.tag.rpartition("}")[2] if isinstance(child.tag, str) else ""
                if tag in ("tspan", "a"):
                    walk(child)
                if child.tail:
                    order.append(("tail", child))
            order.append(("close", el))

        walk(element)
        text_iter = iter(texts)
        stack: list[ET.Element] = []
        for kind, el in order:
            if kind == "open":
                offset_of[id(el)] = position
                stack.append(el)  # type: ignore[arg-type]
            elif kind == "close":
                stack.pop()
                counts[id(el)] = position - offset_of[id(el)]
            else:
                position += len(next(text_iter).text)
        for el in element.iter():
            if id(el) not in offset_of:
                continue
            start, count = offset_of[id(el)], counts[id(el)]
            props = nodes[id(el)].props if id(el) in nodes else {}
            for name, absolute in (("x", xs), ("y", ys)):
                values = _numbers(props.get(name))
                for i in range(min(len(values or ()), count)):
                    absolute[start + i] = values[i]  # type: ignore[index]
            for name, relative in (("dx", dxs), ("dy", dys)):
                values = _numbers(props.get(name))
                for i in range(min(len(values or ()), count)):
                    relative[start + i] = values[i]  # type: ignore[index]

        # Chunks and spans (usvg's collect_text_chunks).
        chunks: list[_Chunk] = []
        index = 0
        chunk_bytes = 0
        for t in texts:
            owner = t.owner
            if not t.text:
                continue
            span_template = self._span(owner, text_node)
            new_span = True
            for char in t.text:
                size = len(char.encode("utf-8"))
                if xs[index] is not None or ys[index] is not None or not chunks:
                    chunk_bytes = 0
                    span = _copy_span(span_template, 0, size)
                    chunks.append(_Chunk(xs[index], ys[index], char, [span]))
                elif new_span:
                    span = _copy_span(span_template, chunk_bytes, chunk_bytes + size)
                    chunks[-1].text += char
                    chunks[-1].spans.append(span)
                else:
                    chunks[-1].text += char
                    chunks[-1].spans[-1].end += size
                new_span = False
                index += 1
                chunk_bytes += size

        family_of = lambda span: (span.node.find("font-family") or "").split(",")[0].strip(" '\"")  # noqa: E731
        for chunk in chunks:
            for span in chunk.spans:
                if span.face is None:
                    db = self._database(span.node.find("font-family"))
                    weight, stretch, style = span.font_key[1:]
                    span.face = db.query(span.font_key[0], weight, stretch, style)
                    if span.face is None:
                        raise _Keep("no loaded font answers to its font-family", family_of(span))
                    self._face(span.face, family_of(span))

        laid: list[tuple] = []
        last_x = last_y = 0.0
        char_offset = 0
        for chunk in chunks:
            x = chunk.x if chunk.x is not None else last_x
            y = chunk.y if chunk.y is not None else last_y
            clusters = self._process_chunk(chunk, family_of)
            if not clusters:
                char_offset += len(chunk.text)
                continue
            self._letter_spacing(chunk, clusters)
            self._word_spacing(chunk, clusters)
            self._length_adjust(chunk, clusters)
            end_x, end_y = self._positions(chunk, char_offset, clusters, dxs, dys)
            for span in chunk.spans:
                if span.face is not None:
                    laid.append((span, chunk, clusters, x, y))
            char_offset += len(chunk.text)
            last_x, last_y = x + end_x, y + end_y
        self.bbox = self._text_bbox(laid)
        pieces: list[str | _Run] = []
        for span, chunk, clusters, x, y in laid:
            pieces.extend(self._draw_span(span, chunk, clusters, x, y, text_node))
        self.outlined += 1
        del sample
        return _joined(pieces)

    def _span_ts(self, span: _Span, x: float, y: float) -> Matrix:
        assert span.face is not None
        return _mul(_translate(x, y), _translate(0.0, self._baseline(span, self._face(span.face, ""))))

    def _text_bbox(self, laid) -> "tuple[float, float, float, float] | None":
        """usvg's text bounding box -- what a paint server's ``objectBoundingBox`` is of:
        every cluster of each span's chunk, its advance (1 where it has none) wide and its
        face's ascent to descent tall, through the cluster's and the span's transforms."""
        xs: list[float] = []
        ys: list[float] = []
        for span, _chunk, clusters, x, y in laid:
            span_ts = self._span_ts(span, x, y)
            for cluster in clusters:
                advance = cluster.advance if cluster.advance > 0 else 1.0
                m = _mul(span_ts, cluster.transform)
                for px, py in ((0.0, -cluster.ascent), (advance, -cluster.ascent),
                               (advance, -cluster.descent), (0.0, -cluster.descent)):
                    qx, qy = _apply(m, px, py)
                    xs.append(qx)
                    ys.append(qy)
        if not xs:
            return None
        return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)

    def paint_value(self, value: str) -> str:
        """A fill or stroke for the outlines: a gradient in the text's bounding box
        (``objectBoundingBox``, the default) restated in user space over that box, since
        the outlines' own box is another; anything else as it is."""
        match = re.fullmatch(r"\s*url\(\s*#([^)\s]+)\s*\)\s*(.*)", value)
        if match is None or self.document is None:
            return value
        ident = match.group(1)
        source = _definition(self.document, ident)
        if source is None:
            return value
        tag = _TAG_NAME.match(source)
        name = tag.group(2) if tag else ""
        if name not in ("linearGradient", "radialGradient"):
            raise _Keep(f"a {name or 'paint'} paint server")
        head = source[:source.find(">") + 1]
        attributes = dict((k, a if a is not None else b) for k, a, b in _ATTRIBUTE.findall(head))
        if attributes.get("gradientUnits", "objectBoundingBox") != "objectBoundingBox":
            return value
        if self.bbox is None or self.bbox[2] <= 0 or self.bbox[3] <= 0:
            return value
        bx, by, bw, bh = self.bbox
        box = f"matrix({_fmt_scale(bw)} 0 0 {_fmt_scale(bh)} {_fmt(bx)} {_fmt(by)})"
        transform = (box + " " + attributes["gradientTransform"]) if "gradientTransform" in attributes else box
        # Of the box and the gradient both: two pages' gradients of one id are two.
        new_id = ident + "-t" + hashlib.sha1((box + source).encode()).hexdigest()[:8]
        if new_id not in self.defs:
            # The geometry restated in the box's own units: a percentage, and a default
            # (which is one), would otherwise be of the viewport in user space.
            if name == "linearGradient":
                geometry = {"x1": "0", "y1": "0", "x2": "1", "y2": "0"}
            else:
                geometry = {"cx": ".5", "cy": ".5", "r": ".5", "fr": "0"}
            for key in list(geometry):
                given = attributes.get(key)
                if given is not None:
                    geometry[key] = _fraction(given)
            if name == "radialGradient":
                geometry["fx"] = _fraction(attributes["fx"]) if "fx" in attributes else geometry["cx"]
                geometry["fy"] = _fraction(attributes["fy"]) if "fy" in attributes else geometry["cy"]
            new_head = re.sub(r'\s(?:id|gradientUnits|gradientTransform|x1|y1|x2|y2|cx|cy|r|fx|fy|fr)="[^"]*"',
                              "", head)
            stated = "".join(f' {key}="{value}"' for key, value in geometry.items())
            new_head = new_head[:-1].rstrip("/") + (
                f' id="{new_id}" gradientUnits="userSpaceOnUse"{stated} gradientTransform="{transform}"'
                + ("/>" if head.endswith("/>") else ">"))
            self.defs[new_id] = new_head + source[len(head):]
        return f"url(#{new_id})" + (" " + match.group(2) if match.group(2) else "")

    def _span(self, owner: _Node, text_node: _Node) -> _Span:
        size = _font_size(owner)
        weight = _font_weight(owner)
        stretch = _STRETCH.get(owner.find("font-stretch", "normal") or "normal", 5)
        style = owner.find("font-style", "normal")
        style = style if style in ("normal", "italic", "oblique") else "normal"
        variations: list[tuple[bytes, float]] = []
        settings = owner.find("font-variation-settings")
        if settings and settings != "normal":
            for part in settings.split(","):
                bits = part.strip().split()
                if len(bits) == 2 and len(bits[0].strip("'\"")) == 4:
                    try:
                        variations.append((bits[0].strip("'\"").encode(), float(bits[1])))
                    except ValueError:
                        pass
        tags = {t for t, _ in variations}
        if b"wght" not in tags:
            variations.append((b"wght", float(weight)))
        if b"wdth" not in tags and stretch != 5:
            variations.append((b"wdth", _WDTH[stretch]))
        if b"ital" not in tags and style == "italic":
            variations.append((b"ital", 1.0))
        if b"slnt" not in tags and style == "oblique":
            variations.append((b"slnt", -12.0))
        kerning = True
        kern_value = owner.find("kerning")
        if kern_value is not None and _number(kern_value) == 0.0:
            kerning = False
        elif owner.find("font-kerning") == "none":
            kerning = False
        text_length = _number(owner.props.get("textLength"))
        if text_length is not None and text_length < 0:
            text_length = None
        shifts = []
        for node in owner.chain():
            if node is text_node or node.tag == "g":
                break
            value = node.props.get("baseline-shift")
            if value is None:
                continue
            value = value.strip()
            if value in ("sub", "super", "baseline"):
                shifts.append(value)
            elif value.endswith("%"):
                try:
                    shifts.append(_font_size(node) * float(value[:-1]) / 100.0)
                except ValueError:
                    shifts.append("baseline")
            else:
                found = _number(value)
                shifts.append(found if found is not None else "baseline")
        if all(s == "baseline" for s in shifts):
            shifts = []
        decorations = {}
        for line in ("underline", "overline", "line-through"):
            declared = None
            for node in owner.chain():
                value = node.props.get("text-decoration")
                if value and line in value.split():
                    declared = node
                    break
            if declared is None:
                continue
            for node in owner.chain():
                value = node.props.get("text-decoration")
                if (value and line in value.split()) or node is text_node:
                    decorations[line] = node
                    break
        if owner.find("font-variant") == "small-caps":
            raise _Keep("small-caps")
        return _Span(
            0, 0, owner, (owner.find("font-family"), weight, stretch, style), size,
            owner.find("text-anchor", "start") or "start", kerning,
            _number(owner.find("letter-spacing"), 0.0, size) or 0.0,
            _number(owner.find("word-spacing"), 0.0, size) or 0.0,
            text_length, owner.props.get("lengthAdjust", "spacing"),
            owner.find("visibility", "visible") == "visible", shifts, decorations,
            variations=tuple(variations))

    # -- usvg's chunk passes ---------------------------------------------------------------

    @staticmethod
    def _span_at(chunk: _Chunk, byte: int) -> _Span | None:
        return next((s for s in chunk.spans if s.start <= byte < s.end), None)

    def _letter_spacing(self, chunk: _Chunk, clusters: list[_Cluster]) -> None:
        if not any(abs(s.letter_spacing) > 1e-6 for s in chunk.spans):
            return
        for i, cluster in enumerate(clusters):
            span = self._span_at(chunk, cluster.byte)
            if span is None:
                continue
            if i != len(clusters) - 1:
                cluster.advance += span.letter_spacing
            if not cluster.advance >= 0:
                cluster.width = cluster.advance = 0.0
                cluster.glyphs = []

    def _word_spacing(self, chunk: _Chunk, clusters: list[_Cluster]) -> None:
        if not any(abs(s.word_spacing) > 1e-6 for s in chunk.spans):
            return
        for cluster in clusters:
            if cluster.codepoint in (0x20, 0xA0, 0x1361, 0x10100, 0x10101, 0x1039F, 0x1091F):
                span = self._span_at(chunk, cluster.byte)
                if span is not None:
                    cluster.advance += span.word_spacing

    def _length_adjust(self, chunk: _Chunk, clusters: list[_Cluster]) -> None:
        for span in chunk.spans:
            if span.text_length is None:
                continue
            indexes = sorted({k for k, c in enumerate(clusters) if span.start <= c.byte < span.end})
            if not indexes:
                continue
            width = sum(clusters[k].width for k in indexes)
            if span.length_adjust == "spacing" or span.length_adjust not in ("spacing", "spacingAndGlyphs"):
                factor = (span.text_length - width) / (len(indexes) - 1) if len(indexes) > 1 else 0.0
                for k in indexes:
                    clusters[k].advance = clusters[k].width + factor
            else:
                if width == 0:
                    continue
                factor = span.text_length / width
                if factor < 0.001:
                    continue
                for k in indexes:
                    clusters[k].transform = _mul(clusters[k].transform, (factor, 0.0, 0.0, 1.0, 0.0, 0.0))

    def _positions(self, chunk: _Chunk, offset: int, clusters: list[_Cluster], dxs, dys) -> tuple[float, float]:
        total = sum(c.advance for c in clusters)
        anchor = chunk.spans[0].anchor if chunk.spans else "start"
        x = -total / 2 if anchor == "middle" else -total if anchor == "end" else 0.0
        y = 0.0
        text = chunk.text
        for cluster in clusters:
            cp = offset + len(text.encode("utf-8")[:cluster.byte].decode("utf-8", "ignore"))
            if cp < len(dxs):
                dx, dy = dxs[cp], dys[cp]
                x += dx
                y += dy
                cluster.has_shift = abs(dx) > 1e-6 or abs(dy) > 1e-6
            cluster.transform = _mul(cluster.transform, _translate(x, y))
            x += cluster.advance
        return x, y

    # -- drawing ---------------------------------------------------------------------------

    def _baseline(self, span: _Span, face: OutlineFace) -> float:
        metrics = face.metrics
        scale = span.font_size / face.units_per_em
        shift = 0.0
        for value in reversed(span.baseline_shift):
            if value == "sub":
                shift -= metrics["subscript_offset"] * scale
            elif value == "super":
                shift += metrics["superscript_offset"] * scale
            elif isinstance(value, float):
                shift += value
        baseline = span.node.find("dominant-baseline", "auto")
        if baseline not in ("auto", "alphabetic", "use-script", "no-change", "reset-size", None):
            raise _Keep("dominant-baseline")
        alignment = span.node.props.get("alignment-baseline")
        if alignment not in (None, "auto", "baseline", "alphabetic"):
            raise _Keep("alignment-baseline")
        return -shift

    def _paint_attrs(self, node: _Node, text_node: _Node) -> str:
        """The paint a span inherits from the spans between it and the text."""
        chain = []
        for n in node.chain():
            if n is text_node:
                break
            chain.append(n)
        merged: dict[str, str] = {}
        for n in reversed(chain):
            for key in _PAINT:
                if key in n.props:
                    merged[key] = n.props[key]
        for key in ("fill", "stroke"):
            if key in merged:
                merged[key] = self.paint_value(merged[key])
        return "".join(f' {k}="{_escape(v)}"' for k, v in merged.items())

    def _draw_span(self, span: _Span, chunk: _Chunk, clusters: list[_Cluster], x: float, y: float,
                   text_node: _Node) -> "list[str | _Run]":
        """The span drawn: markup, and its glyphs as a :class:`_Run` of references where
        they are drawn so, which :meth:`outline` joins with the next span's where both
        share their paint and scale."""
        if not span.visible:
            return []
        assert span.face is not None
        base_face = self._face(span.face, "")
        span_ts = self._span_ts(span, x, y)
        mine = [c for c in clusters if span.start <= c.byte < span.end]
        if not mine:
            return []
        paint = self._paint_attrs(span.node, text_node)
        out: list[str | _Run] = []
        metrics = base_face.metrics
        scale = span.font_size / base_face.units_per_em

        def decoration(line: str, offset: float) -> str:
            node = span.decorations.get(line)
            if node is None:
                return ""
            thickness = metrics["underline_thickness"] * scale
            pieces = []
            started = False
            width = 0.0
            transform = _IDENTITY
            runs = []
            for cluster in clusters:
                if span.start <= cluster.byte < span.end:
                    if started and cluster.has_shift:
                        runs.append((width, transform))
                        started = False
                    if not started:
                        width, transform, started = cluster.advance, cluster.transform, True
                    else:
                        width += cluster.advance
                elif started:
                    runs.append((width, transform))
                    started = False
            if started:
                runs.append((width, transform))
            for width, transform in runs:
                m = _mul(span_ts, _mul(transform, _translate(0.0, offset)))
                corners = [_apply(m, px, py) for px, py in
                           ((0.0, -thickness / 2), (width, -thickness / 2), (width, thickness / 2), (0.0, thickness / 2))]
                pieces.append("M" + "L".join(f"{_fmt(a)} {_fmt(b)}" for a, b in corners) + "Z")
            deco_paint = self._paint_attrs(node, text_node) if node is not text_node else ""
            return f'<path d="{"".join(pieces)}"{deco_paint}/>' if pieces else ""

        out.append(decoration("overline", -metrics["ascent"] * scale))
        out.append(decoration("underline", -metrics["underline_position"] * scale))
        merged = self._merged(span, paint, text_node)
        placed: list[tuple[str, Matrix]] = []
        combined: list[str] = []
        for cluster in mine:
            cluster_ts = _mul(span_ts, cluster.transform)
            for glyph, gx, gy, gscale in cluster.glyphs:
                m = _mul(cluster_ts, _translate(gx * gscale, gy * gscale))
                if merged:
                    commands = glyph.face.outline(glyph.id, glyph.coords)
                    if not commands:
                        continue
                    if m[0] == 1.0 and m[1] == 0.0 and m[2] == 0.0 and m[3] == 1.0:
                        combined.append(path_data(commands, gscale, gscale, m[4], m[5]))
                    else:
                        combined.append(_transformed(commands, gscale, m))
                else:
                    ref = self._glyph_def(glyph)
                    if ref is not None:
                        placed.append((ref, _mul(m, (gscale, 0.0, 0.0, gscale, 0.0, 0.0))))
        if merged and combined:
            out.append(f'<path d="{"".join(combined)}"{paint}/>')
        elif placed:
            out.append(_Run(paint, placed, len(placed) == 1))
        out.append(decoration("line-through", -metrics["line_through_position"] * scale))
        out = [piece for piece in out if piece]
        anchor = next((n for n in span.node.chain() if n.tag == "a"), None)
        if anchor is not None and out:
            attrs = "".join(f' {_attr_name(k)}="{_escape(v)}"' for k, v in anchor.element.attrib.items()  # type: ignore[union-attr]
                            if k not in _TEXT_ONLY and k not in _PAINT and k != "style")
            return [f"<a{attrs}>{_joined(out)}</a>"]
        return out

    def _merged(self, span: _Span, paint: str, text_node: _Node) -> bool:
        """Whether the span's glyphs are drawn as one path (a stroke, a translucent fill
        or paint server) rather than as references."""
        stroke = span.node.find("stroke", "none")
        fill = span.node.find("fill", "black")
        fill_opacity = span.node.find("fill-opacity", "1")
        opacity = _number(fill_opacity, 1.0)
        return (stroke not in (None, "none") or (opacity is not None and opacity < 1.0)
                or (fill or "").startswith("url("))

    def _glyph_def(self, glyph: _ShapedGlyph) -> str | None:
        """The id of the glyph's definition: its outline in font units, y down -- one per
        outline, whatever the face, file or size it is drawn from (:func:`glyph_id`)."""
        data = glyph.face.glyph_data(glyph.id, glyph.coords)
        if not data:
            return None
        ident = glyph_id(data, self.glyphs)
        self.used[ident] = None
        return ident


def glyph_id(data: str, glyphs: "dict[str, str]") -> str:
    """The id of the glyph whose path data is ``data``, its definition added to
    ``glyphs`` (id -> ``<path id d/>``) where it is not there yet.

    The id is made of the outline itself -- ``g`` and the first :data:`ID_DIGITS` base 62
    digits of its hash -- so the same glyph has the same id on every page, in every
    render of a document and in every document, wherever its font file was read from,
    and two ids name two outlines.  An id already another outline's in ``glyphs`` (one
    chance in about 10**10 for two given outlines) takes one more digit, and so on."""
    digest = _hash62(data)
    for length in range(ID_DIGITS, len(digest) + 1):
        ident = "g" + digest[:length]
        element = f'<path id="{ident}" d="{data}"/>'
        found = glyphs.get(ident)
        if found is None:
            glyphs[ident] = element
            return ident
        if found == element:
            return ident
    raise AssertionError("a SHA-1 collision")  # pragma: no cover


def _joined(pieces: "list[str | _Run]") -> str:
    """The pieces' markup, consecutive one-glyph runs of references that share their paint
    and scale joined into one group: a line of characters a renderer placed one by one
    (docx2svg writes an ``x`` for each) is one group, not one a glyph.  A span of more
    glyphs is a group of its own, as it was."""
    out: list[str] = []
    pending: _Run | None = None
    for piece in pieces:
        if isinstance(piece, _Run):
            if pending is not None and pending.single and piece.single and pending.paint == piece.paint \
                    and pending.linear() is not None and pending.linear() == piece.linear():
                pending = _Run(pending.paint, pending.placed + piece.placed, True)
                continue
            if pending is not None:
                out.append(_uses(pending))
            pending = piece
            continue
        if pending is not None:
            out.append(_uses(pending))
            pending = None
        out.append(piece)
    if pending is not None:
        out.append(_uses(pending))
    return "".join(out)


def _uniform(placed) -> "tuple[float, float] | None":
    """The scale every glyph of ``placed`` shares, where it is a scale only."""
    linear = placed[0][1][:4]
    if linear[1] == 0.0 and linear[2] == 0.0 and linear[0] != 0.0 and linear[3] != 0.0 and all(
            m[:4] == linear for _, m, *_ in placed):
        return linear[0], linear[3]
    return None


def _uses(run: _Run) -> str:
    """References to glyph definitions, each with its matrix: a group whose matrix is the
    first glyph's, its glyphs at their offsets from it in font units (two decimals), where
    they all share a scale (one size, nothing stretched); else a matrix each.

    One-glyph spans joined (:func:`_joined`) are each where their own group would have put
    them: resvg reckons ``origin + scale * offset`` in single precision, and a glyph a
    ten-thousandth of a pixel off its own ``translate`` lights an edge pixel otherwise.
    Each takes the shortest offset, to four decimals, that lands on its position in
    single precision (:func:`_offset`), and starts a new group where none does."""
    placed, paint = run.placed, run.paint
    scale = _uniform(placed)
    if scale is None:
        each = "".join(f'<use href="#{ref}" transform="matrix({" ".join(_fmt_scale(v) for v in m[:4])} '
                       f'{_fmt(m[4])} {_fmt(m[5])})"/>' for ref, m in placed)
        return f"<g{paint}>{each}</g>" if paint else each
    sx, sy = scale
    scale_x, scale_y = _fmt_scale(sx), _fmt_scale(sy)
    both = scale_x if sx == sy else f"{scale_x} {scale_y}"
    if not run.single:
        ox, oy = placed[0][1][4], placed[0][1][5]
        refs = []
        for ref, m in placed:
            u, v = (m[4] - ox) / sx, (m[5] - oy) / sy
            position = (f' x="{_fmt_units(u)}"' if abs(u) > 5e-5 else "") + (
                f' y="{_fmt_units(v)}"' if abs(v) > 5e-5 else "")
            refs.append(f'<use href="#{ref}"{position}/>')
        return f'<g{paint} transform="translate({_fmt(ox)} {_fmt(oy)}) scale({both})">{"".join(refs)}</g>'
    groups: list[str] = []
    refs = []
    tx = ty = ""
    for ref, m in placed:
        x, y = _fmt(m[4]), _fmt(m[5])
        if refs:
            dx, dy = _offset(_f32(float(x)), tx, scale_x), _offset(_f32(float(y)), ty, scale_y)
            if dx is not None and dy is not None:
                position = (f' x="{dx}"' if dx != "0" else "") + (f' y="{dy}"' if dy != "0" else "")
                refs.append(f'<use href="#{ref}"{position}/>')
                continue
            groups.append(f'<g transform="translate({tx} {ty}) scale({both})">{"".join(refs)}</g>')
        tx, ty = x, y
        refs = [f'<use href="#{ref}"/>']
    groups.append(f'<g transform="translate({tx} {ty}) scale({both})">{"".join(refs)}</g>')
    if len(groups) == 1:
        return groups[0][:2] + paint + groups[0][2:]
    return f"<g{paint}>{''.join(groups)}</g>"


_F32 = struct.Struct("<f")


def _f32(value: float) -> float:
    """``value`` as the nearest single-precision float, as resvg holds a number."""
    try:
        return _F32.unpack(_F32.pack(value))[0]
    except OverflowError:
        return value


def _offset(place: float, origin: str, scale: str) -> "str | None":
    """The shortest offset in font units, to four decimals, from a group's origin
    (``origin``, in user units, as written) at its ``scale`` (as written) that resvg puts
    at ``place`` -- ``origin + scale * offset`` in single precision; ``None`` where none
    does.  A glyph a ten-thousandth of a pixel off its place lights an edge pixel."""
    t, s = _f32(float(origin)), _f32(float(scale))
    if place == t:
        return "0"
    if s == 0.0:
        return None
    centre = (place - t) / s
    for digits in range(5):
        step = 10.0 ** -digits
        base = round(centre, digits)
        for k in (0, -1, 1, -2, 2, -3, 3):
            text = _fmt_units(base + k * step, digits)
            if _f32(_f32(s * _f32(float(text))) + t) == place:
                return text
    return None


def _fmt_units(value: float, digits: int = 2) -> str:
    """An offset in font units, to ``digits`` decimals."""
    text = f"{value:.{digits}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _fmt_scale(value: float) -> str:
    """A scale: eight significant digits."""
    return f"{value:.8g}"


def _transformed(commands, scale: float, m: Matrix) -> str:
    parts = []
    for command in commands:
        op = command[0]
        if op == "Z":
            parts.append("Z")
            continue
        values = command[1:]
        coords = []
        for i in range(0, len(values), 2):
            px, py = _apply(m, values[i] * scale, -values[i + 1] * scale)
            coords.append(_fmt(px))
            coords.append(_fmt(py))
        parts.append(op + " ".join(coords))
    return "".join(parts)


def _copy_span(template: _Span, start: int, end: int) -> _Span:
    import copy

    span = copy.copy(template)
    span.start, span.end = start, end
    return span


def _escape(value: str) -> str:
    return value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


def _attr_name(key: str) -> str:
    if key.startswith(_XLINK):
        return "xlink:" + key[len(_XLINK):]
    if key == _XML_SPACE:
        return "xml:space"
    return key


# --------------------------------------------------------------------------------------
# The document
# --------------------------------------------------------------------------------------

_TAG = re.compile(r"""<(?:!--.*?--|!\[CDATA\[.*?\]\]>|[^>"']|"[^"]*"|'[^']*')*>""", re.S)
_TAG_NAME = re.compile(r"<\s*(/?)\s*([^\s/>]+)")
_ATTRIBUTE = re.compile(r"""([^\s=/<>]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_ROOT = re.compile(r"<svg\b[^>]*>")


def _unescape(value: str) -> str:
    return (value.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'")
            .replace("&amp;", "&"))


def outline_text(svg: str, fonts: "FontSetup | Callable[[str | None], FontSetup]", *,
                 selectable: bool = False, glyphs: "dict[str, str] | None" = None) -> Outlined:
    """``svg`` with every ``<text>`` drawn as the outlines resvg would draw it with
    ``fonts`` -- one :class:`FontSetup`, or a function giving the setup a text's
    ``font-family`` value is drawn with (a renderer drawing in passes).

    With ``selectable`` each outlined text is followed by the text itself, transparent
    (``fill-opacity`` and ``stroke-opacity`` 0), for a viewer to select, search and copy;
    the outlines are ``aria-hidden`` so that a screen reader reads the text once.

    Each glyph is defined once, in font units, and drawn by reference (``<use
    href="#g…">``); its id is made of its outline (:func:`glyph_id`), so it is the same on
    every page and in every render.  The document's definitions go into a ``<defs
    data-outline-glyphs="">`` first in it, in the order of their first use -- unless
    ``glyphs`` is given: a dict (id -> ``<path id d/>``) shared by a document's pages, which
    the definitions go into instead, the page then holding only the references.  Such a
    page needs the definitions beside it: :func:`glyph_sheet` writes them once, for an
    HTML page that shows the pages inline, and :func:`embed_glyphs` puts a page's own back
    into it, standalone again.

    A text left as text is listed in :attr:`Outlined.kept`; the rest of the document is
    copied as it is."""
    setup_of: Callable[[str | None], FontSetup]
    if isinstance(fonts, FontSetup):
        fixed = fonts
        setup_of = lambda _value: fixed  # noqa: E731
    else:
        setup_of = fonts
    if "<text" not in svg:
        return Outlined(svg)
    outliner = _Outliner(setup_of, selectable, glyphs)
    outliner.document = svg
    if re.search(r"<style\b", svg):
        outliner.kept.append(KeptText("a <style> sheet this module does not follow", "", ""))
        return Outlined(svg, outliner.kept)
    pieces: list[str] = []
    kept_to = 0
    stack: list[tuple[str, dict]] = []
    in_defs = 0
    pos = 0
    while True:
        match = _TAG.search(svg, pos)
        if match is None:
            break
        token = match.group(0)
        pos = match.end()
        if token.startswith(("<!", "<?")):
            continue
        head = _TAG_NAME.match(token)
        if head is None:
            continue
        closing, name = head.group(1) == "/", head.group(2).rpartition(":")[2]
        if closing:
            if stack:
                popped = stack.pop()[0]
                if popped in ("defs", "clipPath", "mask", "pattern", "marker", "symbol"):
                    in_defs -= 1
            continue
        attributes = {_attr_key(key): _unescape(first if first is not None else second)
                      for key, first, second in _ATTRIBUTE.findall(token)}
        if name == "text" and not token.endswith("/>"):
            end = svg.find("</text>", pos)
            if end < 0:
                break
            source = svg[match.start():end + len("</text>")]
            pos = end + len("</text>")
            replacement = _one_text(outliner, source, [a for _, a in stack], selectable and not in_defs)
            if replacement is not None:
                pieces.append(svg[kept_to:match.start()])
                pieces.append(replacement)
                kept_to = pos
            continue
        if token.endswith("/>"):
            continue
        if name in ("defs", "clipPath", "mask", "pattern", "marker", "symbol"):
            in_defs += 1
        stack.append((name, attributes))
    pieces.append(svg[kept_to:])
    out = "".join(pieces)
    own = "" if glyphs is not None else "".join(outliner.glyphs[ident] for ident in outliner.used)
    definitions = own + "".join(value for value in outliner.defs.values() if value)
    if definitions:
        root = _ROOT.search(out)
        if root is not None:
            out = out[:root.end()] + f'<defs data-outline-glyphs="">{definitions}</defs>' + out[root.end():]
    return Outlined(out, outliner.kept, outliner.outlined, outliner.missing, list(outliner.used))


#: A reference to a glyph definition.
_GLYPH_REF = re.compile(r'href="#(g[0-9A-Za-z]+)"')


def glyph_sheet(glyphs: "dict[str, str]") -> str:
    """The glyph definitions of documents outlined with a shared ``glyphs`` dict
    (:func:`outline_text`) as one ``<svg>`` element that draws nothing and takes no room:
    put once in an HTML page, before or after the pages' own ``<svg>`` elements, every
    page's references resolve to it.  Ordered by id, so that the same glyphs write the
    same bytes whatever order the pages were drawn in."""
    definitions = "".join(glyphs[ident] for ident in sorted(glyphs))
    return (f'<svg xmlns="{_SVG}" width="0" height="0" style="position:absolute" aria-hidden="true" '
            f'data-outline-glyphs=""><defs>{definitions}</defs></svg>')


def embed_glyphs(svg: str, glyphs: "dict[str, str]") -> str:
    """``svg``, outlined with a shared ``glyphs`` dict, with the definitions it uses put
    back into it -- into its ``<defs data-outline-glyphs="">`` (one is made first in it
    where it has none), in the order of their first use: the document a page outlined
    on its own would be, standalone, to rasterise or to save.  A reference ``glyphs``
    does not hold is left as it is; a document holding its definitions already is
    returned as it is."""
    wanted: dict[str, None] = {}
    for ident in _GLYPH_REF.findall(svg):
        if ident in glyphs:
            wanted[ident] = None
    have = set(re.findall(r'<path id="(g[0-9A-Za-z]+)"', svg))
    missing = "".join(glyphs[ident] for ident in wanted if ident not in have)
    if not missing:
        return svg
    block = svg.find('<defs data-outline-glyphs="">')
    if block >= 0:
        at = block + len('<defs data-outline-glyphs="">')
        return svg[:at] + missing + svg[at:]
    root = _ROOT.search(svg)
    if root is None:
        return svg
    return svg[:root.end()] + f'<defs data-outline-glyphs="">{missing}</defs>' + svg[root.end():]


def _fraction(value: str) -> str:
    """A bounding-box length as a plain number (``50%`` -> ``0.5``)."""
    value = value.strip()
    if value.endswith("%"):
        try:
            return _fmt_scale(float(value[:-1]) / 100.0)
        except ValueError:
            return value
    return value


def _definition(svg: str, ident: str) -> str | None:
    """The element with ``id="ident"`` in ``svg``, from its start tag to its end."""
    match = re.search(r'<([A-Za-z]+)\b[^>]*\sid="' + re.escape(ident) + r'"[^>]*>', svg)
    if match is None:
        return None
    if match.group(0).endswith("/>"):
        return match.group(0)
    end = svg.find(f"</{match.group(1)}>", match.end())
    return svg[match.start():end + len(match.group(1)) + 3] if end >= 0 else None


def _attr_key(key: str) -> str:
    if key == "xml:space":
        return _XML_SPACE
    if key.startswith("xlink:"):
        return _XLINK + key[6:]
    return key


def _one_text(outliner: _Outliner, source: str, outer: list[dict], selectable: bool) -> str | None:
    try:
        element = ET.fromstring(_with_namespaces(source))
    except ET.ParseError:
        outliner.kept.append(KeptText("not well-formed", "", source[:40]))
        return None
    sample = "".join(element.itertext()).strip()[:8]
    family = ""
    for attrib in [*outer, element.attrib]:
        family = _style(attrib).get("font-family", family)
    try:
        drawn = outliner.outline(element, outer)
    except _Keep as keep:
        outliner.kept.append(KeptText(keep.reason, keep.family or family.split(",")[0].strip(" '\""), sample))
        return None
    attrs = []
    props = element.attrib
    for key, value in props.items():
        if key in _TEXT_ONLY or key in ("id",):
            continue
        if key in ("fill", "stroke"):
            try:
                value = outliner.paint_value(value)
            except _Keep as keep:
                outliner.kept.append(KeptText(keep.reason, family.split(",")[0].strip(" '\""), sample))
                return None
        if key == "style":
            kept = ";".join(d for d in value.split(";") if d.partition(":")[0].strip() not in _TEXT_ONLY
                            and d.strip())
            if kept:
                attrs.append(f'style="{_escape(kept)}"')
            continue
        attrs.append(f'{_attr_name(key)}="{_escape(value)}"')
    if "id" in props:
        attrs.insert(0, f'id="{_escape(props["id"])}"')
    rendering = _style(dict(props)).get("text-rendering")
    if rendering == "optimizeSpeed":
        attrs.append('shape-rendering="crispEdges"')
    attrs.append('fill-rule="nonzero"')
    if selectable:
        attrs.append('aria-hidden="true"')
    group = f"<g {' '.join(attrs)}>{drawn}</g>"
    if selectable:
        group += _selectable(source)
    return group


def _with_namespaces(source: str) -> str:
    head = _TAG_NAME.match(source)
    end = source.find(">")
    insert = f' xmlns="{_SVG}" xmlns:xlink="http://www.w3.org/1999/xlink"'
    if source[end - 1] == "/":
        end -= 1
    return source[:end] + insert + source[end:] if head else source


_OPACITY_ATTR = re.compile(r'\s(?:fill-opacity|stroke-opacity)="[^"]*"')
_FILTER_ATTR = re.compile(r'\sfilter="[^"]*"')


def _selectable(source: str) -> str:
    """The text, transparent, to select and search: its own ``fill-opacity`` and
    ``stroke-opacity`` zero and its spans' removed, its filter dropped (a shadow of
    nothing still floods some filters)."""
    end = source.find(">")
    head, rest = source[:end], source[end:]
    head = _FILTER_ATTR.sub("", _OPACITY_ATTR.sub("", head))
    rest = _OPACITY_ATTR.sub("", rest)
    if head.endswith("/"):
        head = head[:-1]
    return head + ' fill-opacity="0" stroke-opacity="0" data-text-layer=""' + rest
