"""SVG to PNG: the rasterisers both renderers hand their SVG to, and how they are called.

Rasterising is delegated to an existing renderer, never reimplemented.  Two backends,
tried in this order (:data:`BACKENDS`):

* **resvg** -- `resvg-py <https://pypi.org/project/resvg-py/>`_, Python bindings for the
  Rust renderer `resvg <https://github.com/linebender/resvg>`_.  Prebuilt wheels and no
  system library behind them, and the only backend that takes font arguments, so the
  only one that can render reproducibly.
* **cairosvg** -- for hosts that already have Cairo.  It draws from the host's
  fontconfig and nothing else, and its SVG filter support is weaker.

Neither is a dependency: this module imports only the standard library, and a backend
is imported when it is probed or called.  What each renderer adds on top -- which fonts
to hand over, what to do to the SVG first, the install hint in an error -- is the
renderer's own (pptx2svg's ``png.py``, docx2svg's ``png.py``).

**Passes.**  resvg files a face under one family name, and of two faces answering to
the same name, weight, width and style it keeps the first it loads -- Aptos Display and
Aptos are both "Aptos" at 400 -- so a page asking for both is drawn in passes, each with
its own files, each over the last (:func:`pass_svg`, :func:`draw_in_passes`).  Which
text goes in which pass is the renderer's plan: PowerPoint and Word find a face in
different places and orders, so the plans differ; drawing them is this module.
"""

from __future__ import annotations

import base64
import re
from typing import Callable, Iterable, Literal, Mapping, Sequence

__all__ = [
    "BACKENDS",
    "Backend",
    "RasterizerNotAvailable",
    "as_bytes",
    "available_backends",
    "choose_backend",
    "draw_in_passes",
    "importable",
    "pass_svg",
    "preferred_backend",
    "render_with_cairosvg",
    "render_with_resvg",
    "without_undrawn_text",
]

Backend = Literal["resvg", "cairosvg", "auto"]


class RasterizerNotAvailable(RuntimeError):
    """No SVG-to-PNG backend is installed (or not the one asked for)."""


#: ``(backend name, module to import)``, in preference order.  resvg first: it takes the
#: font arguments, and it ships prebuilt wheels with no system library behind them.
BACKENDS: tuple[tuple[str, str], ...] = (
    ("resvg", "resvg_py"),
    ("cairosvg", "cairosvg"),
)


def importable(module: str) -> bool:
    """Whether ``module`` imports, treating **any** failure as "not available".

    Deliberately not ``except ImportError``.  cairosvg is a Python wheel in front of a
    *system* library, and with the wheel installed but libcairo missing -- a Mac or a slim
    container that never installed Cairo -- importing it raises ``OSError('no library
    called "cairo-2" was found')``.  Caught as ``ImportError`` only, that took down every
    caller, including those about to choose resvg and never touch Cairo.  A backend that
    cannot be imported is unavailable; why is not this function's business.
    """
    try:
        __import__(module)
    except Exception:
        return False
    return True


def available_backends() -> list[str]:
    """The backends that import right now, best first."""
    return [name for name, module in BACKENDS if importable(module)]


def preferred_backend() -> str | None:
    """The best backend that imports, without importing the ones after it.

    ``backend="auto"`` only needs the winner, and probing further costs an import of a
    library that will not be used -- for cairosvg, loading a system library, the slowest
    and most fragile import of the two.
    """
    for name, module in BACKENDS:
        if importable(module):
            return name
    return None


def choose_backend(backend: str, *, none_installed: str) -> str:
    """The backend to draw with: ``backend``, or for ``"auto"`` the best installed.

    :raises RasterizerNotAvailable: ``"auto"`` and none imports; ``none_installed`` is
        the message (the renderer's install hint).
    :raises ValueError: a name that is not a backend.
    """
    if backend == "auto":
        chosen = preferred_backend()
        if chosen is None:
            raise RasterizerNotAvailable(none_installed)
        return chosen
    if backend not in {name for name, _ in BACKENDS}:
        raise ValueError(f"unknown rasterizer backend: {backend!r}")
    return backend


def as_bytes(value) -> bytes:
    """resvg-py has returned both ``bytes`` and ``list[int]`` across releases."""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, Iterable):
        return bytes(value)
    raise TypeError(f"unexpected rasterizer result type: {type(value)!r}")


def render_with_resvg(
    svg: str,
    *,
    width: int | None = None,
    height: int | None = None,
    scale: float | None = None,
    background: str | None = None,
    font_dirs: Sequence[str] | None = None,
    font_files: Sequence[str] | None = None,
    skip_system_fonts: bool = False,
    families: Mapping[str, str] | None = None,
    not_installed: str = "resvg-py is not installed",
) -> bytes:
    """``svg`` drawn by resvg-py, as PNG bytes.

    ``width``/``height`` set the output size in pixels (give one and the aspect ratio is
    kept); ``scale`` multiplies the SVG's own size instead (resvg's ``zoom``).
    ``background`` is a CSS colour painted behind the image.  resvg loads
    ``font_files``, then ``font_dirs``, and the host's fonts unless ``skip_system_fonts``.
    ``families`` points resvg's generic family keywords at faces, by its own option
    names (``{"sans_serif_family": "Carlito"}``; also ``serif_family``,
    ``monospace_family``, ``cursive_family``, ``fantasy_family``): its defaults --
    Arial, Times New Roman, Courier New -- may be absent, and with system fonts off a
    keyword nothing answers to draws nothing.

    resvg-py opens and parses every file it is handed on every call, so it is handed
    only those that can take part in drawing ``svg``, in the order it would have loaded
    them, which draws the same pixels (:func:`ooxml_common.fonts.rasterdb.needed_font_files`).

    :raises RasterizerNotAvailable: resvg-py does not import (``not_installed`` is the
        message).
    """
    try:
        import resvg_py
    except ImportError as error:  # pragma: no cover - exercised only without resvg-py
        raise RasterizerNotAvailable(not_installed) from error
    from .fonts.rasterdb import needed_font_files

    files = [str(path) for path in font_files or ()]
    dirs: list[str] | None = [str(path) for path in font_dirs or ()]
    needed = needed_font_files(svg, font_files=files, font_dirs=dirs,
                               system_fonts=not skip_system_fonts,
                               families=dict(families) if families else None)
    if needed is not None:
        files, dirs = needed, None

    options: dict = {"svg_string": svg}
    if width is not None:
        options["width"] = int(width)
    if height is not None:
        options["height"] = int(height)
    if scale is not None:
        options["zoom"] = float(scale)
    if background is not None:
        options["background"] = background
    if dirs:
        options["font_dirs"] = list(dirs)
    if files:
        options["font_files"] = list(files)
    if skip_system_fonts:
        options["skip_system_fonts"] = True
    if families:
        options.update(families)
    return as_bytes(resvg_py.svg_to_bytes(**options))


def render_with_cairosvg(
    svg: str,
    *,
    width: int | None = None,
    height: int | None = None,
    scale: float | None = None,
    background: str | None = None,
    not_installed: str = "cairosvg is not installed",
) -> bytes:
    """``svg`` drawn by CairoSVG, as PNG bytes: ``width``/``height`` (its
    ``output_width``/``output_height``), ``scale`` and ``background`` (its
    ``background_color``) as :func:`render_with_resvg` takes them.  It takes no font
    arguments: it draws from the host's fontconfig.

    :raises RasterizerNotAvailable: cairosvg does not import.
    """
    try:
        import cairosvg
    except ImportError as error:  # pragma: no cover - exercised only without cairosvg
        raise RasterizerNotAvailable(not_installed) from error
    options: dict = {"bytestring": svg.encode("utf-8")}
    if width is not None:
        options["output_width"] = int(width)
    if height is not None:
        options["output_height"] = int(height)
    if scale is not None:
        options["scale"] = float(scale)
    if background is not None:
        options["background_color"] = background
    return cairosvg.svg2png(**options)


# --------------------------------------------------------------------------------------
# Passes: one SVG drawn in several, each with its own fonts, each over the last
# --------------------------------------------------------------------------------------

_FAMILY_ATTRIBUTE = re.compile(r'\sfont-family="([^"]*)"')
_ROOT = re.compile(r"<svg\b[^>]*>")
_VIEWBOX = re.compile(r'viewBox="\s*([-\d.eE]+)[\s,]+([-\d.eE]+)[\s,]+([-\d.eE]+)[\s,]+([-\d.eE]+)\s*"')


def pass_svg(svg: str, stacks: Mapping[str, int], number: int, underlay: bytes | None) -> str:
    """``svg`` for pass ``number``: ``stacks`` gives a ``font-family`` attribute's value
    its pass (a value it lacks is pass 0's).

    Pass 0 is the SVG with the text of every later pass hidden.  A later pass is the SVG
    with *everything* hidden but its own text, over ``underlay`` -- the passes before it,
    as PNG, drawn pixel for pixel beneath.  ``visibility`` hides without moving: hidden
    glyphs keep their advance, so nothing after them shifts.  A text's pass draws it over
    whatever the page draws after it (a drawing in front of the text).  Texts a pass
    draws nothing of are left out of it (:func:`without_undrawn_text`).
    """
    def element(match: re.Match) -> str:
        own = stacks.get(match.group(1), 0)
        if number == 0:
            return match.group(0) + (' visibility="hidden"' if own != 0 else "")
        return match.group(0) + (' visibility="visible"' if own == number else ' visibility="hidden"')

    out = _FAMILY_ATTRIBUTE.sub(element, svg)
    if number == 0 or underlay is None:
        return without_undrawn_text(out)
    root = _ROOT.search(out)
    if root is None:
        return out
    box = _VIEWBOX.search(root.group(0))
    if box is not None:
        x, y, width, height = box.groups()
    else:
        x = y = "0"
        width = re.search(r'\bwidth="([\d.]+)', root.group(0)).group(1)  # type: ignore[union-attr]
        height = re.search(r'\bheight="([\d.]+)', root.group(0)).group(1)  # type: ignore[union-attr]
    image = (
        f'<image x="{x}" y="{y}" width="{width}" height="{height}" preserveAspectRatio="none" '
        f'image-rendering="optimizeSpeed" visibility="visible" '
        f'href="data:image/png;base64,{base64.b64encode(underlay).decode("ascii")}"/>'
    )
    # Definitions inherit `visibility` from where they are written, not from where they
    # are used, and a hidden shape in a clip path clips everything away.
    for tag in ("clipPath", "mask", "pattern", "marker", "symbol"):
        out = out.replace(f"<{tag} ", f'<{tag} visibility="visible" ').replace(
            f"<{tag}>", f'<{tag} visibility="visible">')
    head = out[: root.end()]
    head = head[:-1] + ' visibility="hidden">'
    return without_undrawn_text(head + image + out[root.end():])


def draw_in_passes(svg: str, stacks: Mapping[str, int], count: int,
                   draw: Callable[[int, str], bytes]) -> bytes:
    """``svg`` drawn in ``count`` passes: ``draw(number, document)`` rasterises pass
    ``number``'s document (:func:`pass_svg`, over the passes before it; ``svg`` itself
    when there is one pass) with that pass's fonts, and the last pass's PNG is the
    image.  A background belongs to pass 0 alone: a later one would cover the underlay.
    """
    if count < 1:
        raise ValueError("a drawing has at least one pass")
    image: bytes | None = None
    for number in range(count):
        document = svg if count == 1 else pass_svg(svg, stacks, number, image)
        image = draw(number, document)
    assert image is not None
    return image


_TAG = re.compile(r"""<(?:[^>"']|"[^"]*"|'[^']*')*>""")
_TAG_NAME = re.compile(r"<\s*(/?)\s*([^\s/>]+)")
_ATTRIBUTE = re.compile(r"""([^\s=/<>]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
#: Attributes on a text element or around it whose result depends on the bounding box of
#: everything inside, hidden or not, or that paint without the text's glyphs (a filter
#: floods its region): a text under one is never left out.
_BOX_DEPENDENT = frozenset({"filter", "mask", "clip-path", "opacity", "style", "mix-blend-mode",
                            "isolation"})
#: Where a hidden text still takes part: a definition is drawn where it is used.
_DEFINITIONS = frozenset({"defs", "clipPath", "mask", "pattern", "marker", "symbol"})


def without_undrawn_text(svg: str) -> str:
    """``svg`` without the ``<text>`` elements it draws nothing of: none of their
    characters is under a visible element (:func:`pass_svg`).  resvg lays a hidden text
    out all the same -- its faces found, every run shaped, at the cost of a drawn one
    where opening a font file is slow -- and draws none of it, so leaving it out changes
    no pixel.  A text is kept where it might still count: under a filter, mask, clip,
    opacity, style or blend (what they do depends on the box of all they hold), in a
    definition, or in an SVG this scanner does not follow (``<!`` sections, ``<use>``)."""
    if "<!" in svg or "<use" in svg or "<text" not in svg or "visibility" not in svg:
        return svg                   # nothing hidden, or nothing this scanner follows
    pieces: list[str] = []
    kept_to = 0
    # Per open element: (name, effectively visible, guarded).
    stack: list[tuple[str, bool, bool]] = [("", True, False)]
    text_start = None                    # where the open <text> begins, if one is open
    text_depth = 0
    text_drawn = False
    data_from = 0
    for match in _TAG.finditer(svg):
        token = match.group(0)
        if text_start is not None and stack[-1][1] and match.start() > data_from:
            text_drawn = True            # characters under a visible element
        data_from = match.end()
        if token.startswith("<?"):
            continue
        head = _TAG_NAME.match(token)
        if head is None:
            return svg
        closing, name = head.group(1) == "/", head.group(2).rpartition(":")[2]
        if closing:
            if len(stack) <= 1 or stack[-1][0] != name:
                return svg               # not well formed: leave it to the rasteriser
            stack.pop()
            if text_start is not None and len(stack) == text_depth:
                if not text_drawn:
                    pieces.append(svg[kept_to:text_start])
                    kept_to = match.end()
                text_start = None
            continue
        attributes = {key: first if first is not None else second
                      for key, first, second in _ATTRIBUTE.findall(token)}
        parent_visible, parent_guarded = stack[-1][1], stack[-1][2]
        value = attributes.get("visibility", "inherit").strip()
        visible = parent_visible if value == "inherit" else value == "visible"
        guarded = parent_guarded or name in _DEFINITIONS or bool(_BOX_DEPENDENT & attributes.keys())
        if text_start is None and name == "text" and not guarded:
            text_start, text_depth, text_drawn = match.start(), len(stack), False
        if text_start is not None and guarded:
            text_drawn = True
        if token.endswith("/>"):
            if text_start is not None and len(stack) == text_depth:
                # A self-closed <text/> draws nothing either way.
                text_start = None
            continue
        stack.append((name, visible, guarded))
    if text_start is not None or len(stack) != 1:
        return svg
    pieces.append(svg[kept_to:])
    return "".join(pieces)
