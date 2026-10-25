"""The golden-output harness: made-up inputs under ``tests/fixtures/``, what this package
makes of them under ``tests/golden/``.

The goldens are a photograph of this package's own output on the day they were written,
as pptx2svg's VRT snapshots are of its: they say that the output *changed*, never that it
is *right*.  Correctness is measured in the renderers (pptx2svg and docx2svg score theirs
against PowerPoint and Word); what these hold is that the code here, called through its
public API with nothing else installed, still produces the bytes it produced then.

What a consumer would supply -- how a fill, an outline and a title resolve, the theme's
faces and colours -- is supplied here as plainly as it can be: colours through
:class:`~ooxml_common.drawingml.color.ColorContext` with no theme (this package's own
fallback scheme), solid, gradient and pattern fills as they are stated, a title's runs
with their own size, weight and colour.  Not pptx2svg's cascade, and not meant to be: the
inputs are the same, the consumer is this file.

Regenerate after a deliberate change with ``python -m pytest tests/test_goldens.py
--update-goldens``.  The flag rewrites the files and *skips* rather than passes, so it can
never make a run green; read the diff before committing it.
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import json
import re
import struct
import zlib
from pathlib import Path

import pytest

from ooxml_common.chart import layout as chart_layout
from ooxml_common.chart import read as chart_read
from ooxml_common.chart import rules as chart_rules
from ooxml_common.drawingml import scene as m
from ooxml_common.drawingml import source as s
from ooxml_common.drawingml.color import DEFAULT_COLOR_MAP, ColorContext, resolve_color
from ooxml_common.drawingml.context import RenderContext
from ooxml_common.drawingml.elements import render_element
from ooxml_common.locales import EN_US, Locale
from ooxml_common.units import emu_to_px

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
GOLDEN = HERE / "golden"

RULES = {"powerpoint": chart_rules.POWERPOINT, "word": chart_rules.WORD}
COLORS = {
    name: ColorContext(None, dict(DEFAULT_COLOR_MAP), rules=rules.drawing.color)
    for name, rules in RULES.items()
}


def manifest(name: str) -> dict:
    """``tests/fixtures/<name>.json``: each fixture's settings and where it came from."""
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


# -- what a consumer supplies -----------------------------------------------------------


def color(source, rules: str = "powerpoint") -> m.ResolvedColor | None:
    return resolve_color(COLORS[rules], source)


def fill(source, rules: str = "powerpoint") -> m.Fill | None:
    """A stated fill as it is stated; an image or group fill draws nothing here."""
    if isinstance(source, s.SourceNoFill):
        return m.NoFill()
    if isinstance(source, s.SourceSolidFill):
        resolved = color(source.color, rules)
        return m.SolidFill(color=resolved) if resolved is not None else None
    if isinstance(source, s.SourceGradientFill):
        stops = [m.GradientStop(position=stop.position, color=color(stop.color, rules))
                 for stop in source.stops if color(stop.color, rules) is not None]
        if not stops:
            return None
        return m.GradientFill(stops=stops, angle=source.angle / 60000, gradient_type=source.gradient_type,
                              center_x=source.center_x, center_y=source.center_y, path=source.path,
                              focus=source.focus, scaled=source.scaled,
                              rotate_with_shape=source.rotate_with_shape)
    if isinstance(source, s.SourcePatternFill):
        foreground, background = color(source.foreground_color, rules), color(source.background_color, rules)
        if foreground is None or background is None:
            return None
        return m.PatternFill(preset=source.preset, foreground_color=foreground, background_color=background)
    return None


def outline(source, rules: str = "powerpoint") -> m.Outline | None:
    if source is None:
        return None
    paint = fill(source.fill, rules) if source.fill is not None else None
    if isinstance(paint, m.NoFill):
        return None
    return m.Outline(width=source.width if source.width is not None else 9525,
                     fill=paint if isinstance(paint, (m.SolidFill, m.GradientFill)) else None,
                     dash_style=source.dash_style or "solid",
                     custom_dash=list(source.custom_dash) if source.custom_dash else None,
                     line_cap=source.line_cap, line_join=source.line_join, head_end=source.head_end,
                     tail_end=source.tail_end, compound=source.compound)


def title_text(rich, text: str, size: float, align: str, rules: str = "powerpoint") -> m.TextBody:
    """A chart or axis title: its runs with their own size, weight and colour, else
    ``text`` at ``size``."""
    paragraphs = []
    for paragraph in (rich.paragraphs if rich is not None else []):
        runs = []
        for run in paragraph.runs:
            props = run.properties
            runs.append(m.TextRun(run.text, m.RunProperties(
                font_size=(props.font_size if props and props.font_size else size),
                font_family=props.typeface if props else None,
                bold=bool(props and props.bold), italic=bool(props and props.italic),
                color=color(props.color, rules) if props and props.color is not None else None)))
        paragraphs.append(m.Paragraph(runs=runs, properties=m.ParagraphProperties(alignment=align)))
    if not any(paragraph.runs for paragraph in paragraphs):
        paragraphs = [m.Paragraph(runs=[m.TextRun(text, m.RunProperties(font_size=size))],
                                  properties=m.ParagraphProperties(alignment=align))]
    return m.TextBody(paragraphs=paragraphs, body_properties=chart_layout.CHART_TEXT_BODY)


def chart_style(source, rules: str = "powerpoint") -> chart_layout.ChartStyle:
    accents = chart_layout.accent_colors(lambda key: color(s.SchemeColor(scheme=key), rules))
    return chart_layout.ChartStyle(font_family="Aptos", font_size=chart_layout.default_font_size(source),
                                   color=color(s.SchemeColor(scheme="tx1"), rules), accents=accents)


def locale(settings: dict | None) -> Locale:
    return Locale(**settings) if settings else EN_US


# -- charts -----------------------------------------------------------------------------


def chart_element(xml, width_pt: float, height_pt: float, rules: str = "powerpoint",
                  settings: dict | None = None) -> tuple[m.ChartElement | None, list[str]]:
    """A chart part laid out in a frame of ``width_pt`` x ``height_pt``, as a consumer
    would: read, its drawable groups found, built.  ``None`` and the reason where it
    draws nothing."""
    source = chart_read.parse_chart_space(xml)
    if source is None:
        return None, ["no c:chart"]
    plots = chart_layout.drawable_plots(source)
    if not plots:
        return None, ["not drawn: " + ",".join(sorted(plot.kind for plot in source.plots))]
    builder = chart_layout.ChartBuilder(
        source, plots[0], width_pt=width_pt, height_pt=height_pt, style=chart_style(source, rules),
        resolve_fill=lambda paint: fill(paint, rules), resolve_outline=lambda line: outline(line, rules),
        resolve_text=lambda rich, text, size, align: title_text(rich, text, size, align, rules),
        resolve_typeface=lambda face: "Aptos" if face and face.startswith("+") else face,
        plots=plots, rules=RULES[rules], locale=locale(settings))
    children, data = builder.build()
    notes = []
    if builder.flattened_three_d:
        notes.append("flattened: " + ",".join(builder.flattened_three_d))
    if builder.default_title_wanted:
        notes.append("default title wanted")
    notes.extend(f"axis title not drawn: {reason}" for reason in dict.fromkeys(builder.axis_titles_not_drawn))
    frame = m.Transform(extent_width=width_pt * chart_layout.EMU_PER_POINT,
                        extent_height=height_pt * chart_layout.EMU_PER_POINT)
    return m.ChartElement(transform=frame, chart=data, child_transform=dataclasses.replace(frame),
                          children=children), notes


# -- drawing ----------------------------------------------------------------------------


def svg_document(elements, width_emu: float, height_emu: float, rules: str = "powerpoint",
                 notes: list[str] = (), **context) -> str:
    """``elements`` drawn by :func:`render_element` into one SVG document, one element a
    line, so that a diff names the element that changed."""
    render = RenderContext(rules=RULES[rules].drawing, **context)
    body = [render_element(element, render) for element in elements]
    width, height = emu_to_px(width_emu), emu_to_px(height_emu)
    lines = [f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
             f'viewBox="0 0 {width:g} {height:g}" width="{width:g}" height="{height:g}">']
    lines += [f"<!-- {note} -->" for note in notes]
    if render.defs:
        lines.append("<defs>")
        lines += render.defs
        lines.append("</defs>")
    lines += [fragment for fragment in body if fragment]
    lines.append("</svg>")
    return stable("\n".join(lines) + "\n")


# -- PNG, independent of the zlib that wrote it ------------------------------------------


def png_identity(data: bytes) -> str:
    """A PNG as its size, colour type and the SHA-256 of its *inflated* image data: the
    pixels, whichever zlib build deflated them (deflate output differs between builds,
    and the goldens are checked on every platform)."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return f"not-png:{hashlib.sha256(data).hexdigest()[:16]}"
    offset, idat, head = 8, b"", ""
    while offset + 8 <= len(data):
        (length,) = struct.unpack_from(">I", data, offset)
        tag, body = data[offset + 4 : offset + 8], data[offset + 8 : offset + 8 + length]
        if tag == b"IHDR":
            width, height, depth, colour = struct.unpack_from(">IIBB", body)
            head = f"{width}x{height}:{depth}:{colour}"
        elif tag == b"IDAT":
            idat += body
        else:
            head += f":{tag.decode('latin-1')}" if tag != b"IEND" else ""
        offset += 12 + length
    try:
        pixels = hashlib.sha256(zlib.decompress(idat)).hexdigest()[:16]
    except zlib.error:
        pixels = "undecodable"
    return f"{head}:{pixels}"


_PNG_URI = re.compile(r"data:image/png;base64,([A-Za-z0-9+/=]+)")


def stable(svg: str) -> str:
    """``svg`` with each embedded PNG written as :func:`png_identity`."""
    import base64

    return _PNG_URI.sub(lambda found: "data:image/png;pixels," + png_identity(base64.b64decode(found.group(1))), svg)


# -- models as text ---------------------------------------------------------------------


def dump(value):
    """A model (dataclasses all the way down) as JSON-able data: each dataclass a dict
    led by its class name, its fields that differ from their defaults after it."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        out = {"@": type(value).__name__}
        for item in dataclasses.fields(value):
            current = getattr(value, item.name)
            if item.default is not dataclasses.MISSING and _same(current, item.default):
                continue
            if item.default_factory is not dataclasses.MISSING and _same(current, item.default_factory()):
                continue
            out[item.name] = dump(current)
        return out
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): dump(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [dump(item) for item in value]
    if isinstance(value, (bytes, bytearray)):
        return {"bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()[:16]}
    if isinstance(value, float):
        return round(value, 6)
    if value is None or isinstance(value, (str, int, bool)):
        return value
    return repr(value)


def _same(current, default) -> bool:
    try:
        return type(current) is type(default) and current == default
    except Exception:  # noqa: BLE001 -- an incomparable value is simply written
        return False


def dump_text(value) -> str:
    return json.dumps(dump(value), indent=1, ensure_ascii=False, sort_keys=False) + "\n"


# -- scene fixtures --------------------------------------------------------------------


def _scene_classes() -> dict[str, type]:
    from ooxml_common.drawingml import model

    found = {}
    for module in (model, m):
        for name in dir(module):
            value = getattr(module, name)
            if isinstance(value, type) and dataclasses.is_dataclass(value):
                found.setdefault(value.__name__, value)
    return found


def to_data(value):
    """A scene element as JSON-able data that :func:`from_data` reads back as it was:
    as :func:`dump`, but exact -- no rounding, and a tuple kept a tuple."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        out = {"@": type(value).__name__}
        for item in dataclasses.fields(value):
            current = getattr(value, item.name)
            if item.default is not dataclasses.MISSING and _same(current, item.default):
                continue
            if item.default_factory is not dataclasses.MISSING and _same(current, item.default_factory()):
                continue
            out[item.name] = to_data(current)
        return out
    if isinstance(value, tuple):
        return {"()": [to_data(item) for item in value]}
    if isinstance(value, list):
        return [to_data(item) for item in value]
    if isinstance(value, dict):
        return {"{}": [[to_data(key), to_data(item)] for key, item in value.items()]}
    if isinstance(value, frozenset):
        return {"frozenset": sorted(to_data(item) for item in value)}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"a scene fixture cannot hold a {type(value).__name__}")


def from_data(data, classes: dict[str, type] | None = None):
    classes = classes if classes is not None else _scene_classes()
    if isinstance(data, list):
        return [from_data(item, classes) for item in data]
    if isinstance(data, dict):
        if "@" in data:
            kind = classes[data["@"]]
            return kind(**{key: from_data(item, classes) for key, item in data.items() if key != "@"})
        if "()" in data:
            return tuple(from_data(item, classes) for item in data["()"])
        if "{}" in data:
            return {from_data(key, classes): from_data(item, classes) for key, item in data["{}"]}
        if "frozenset" in data:
            return frozenset(from_data(item, classes) for item in data["frozenset"])
        raise ValueError(f"not a scene value: {sorted(data)}")
    return data


# -- comparing --------------------------------------------------------------------------


def check(request, path: Path, produced: str) -> None:
    """``produced`` must be ``path``'s bytes; with ``--update-goldens`` it becomes them
    and the test skips."""
    if request.config.getoption("--update-goldens"):
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_text(encoding="utf-8") != produced:
            path.write_text(produced, encoding="utf-8", newline="\n")
        pytest.skip(f"golden written: {path.relative_to(HERE)}")
    assert path.exists(), (
        f"no golden at {path.relative_to(HERE)}; write it with "
        "`python -m pytest tests/test_goldens.py --update-goldens` and read it before committing"
    )
    expected = path.read_text(encoding="utf-8")
    if produced != expected:
        failed = HERE / "golden-diffs" / path.relative_to(GOLDEN)
        failed.parent.mkdir(parents=True, exist_ok=True)
        failed.write_text(produced, encoding="utf-8", newline="\n")
        pytest.fail(
            f"{path.relative_to(HERE)} changed; the new output is at {failed.relative_to(HERE)}. "
            "If the change is meant, rewrite the goldens with --update-goldens and say in the "
            "commit which change the new bytes are.",
            pytrace=False,
        )
