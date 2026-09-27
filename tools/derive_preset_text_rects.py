#!/usr/bin/env python3
"""Compile every preset's text rectangle out of ECMA-376's ``presetShapeDefinitions.xml``.

A preset's definition ends with an ``a:rect`` -- four guide names or literals, the
rectangle its text is laid out in (a rounded rectangle's text keeps clear of its
corners, an ellipse's sits in the inscribed rectangle).  pptx2svg's
``tools/derive_preset_geometry.py`` compiles the adjustments, guides and paths into
:mod:`ooxml_common.drawingml.presets`; this script compiles the rectangles beside them into
:mod:`ooxml_common.drawingml.preset_text_rects`, which
:func:`ooxml_common.drawingml.geometry.text_rect` evaluates with those guides.

    python3 tools/derive_preset_text_rects.py --source presetShapeDefinitions.xml
    python3 tools/derive_preset_text_rects.py --check --source ...   # exit 1 if stale

The source is not redistributed here (see the pptx2svg script for why, and where to get
it); ``--source`` takes the inner ``OfficeOpenXML-DrawingMLGeometries.zip`` or the
extracted ``.xml``, whose SHA-256 is verified first.  A definition without an ``a:rect``
(the connectors, ``line``) is its whole box; ``upArrow``, which the file does not define
(pptx2svg's ``SUPPLEMENTS`` writes it), mirrors ``downArrow``'s.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TARGET = HERE.parent / "src" / "ooxml_common" / "drawingml" / "preset_text_rects.py"
DRAWINGML_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
SOURCE_SHA256 = "2f7c868d857c1e3c4b5a6068759fe0e07d77ad58377a6618d1b02ba3507b6939"
WHOLE_BOX = ("l", "t", "r", "b")
#: Presets the file does not define, with the rectangle written here.
SUPPLEMENTS = {"upArrow": ("x1", "y1", "x2", "b")}

HEADER = '''"""Every ECMA-376 preset's text rectangle (``a:rect``), as guide names or literals.

**Generated file -- do not edit.**  Regenerate with::

    python3 tools/derive_preset_text_rects.py --source presetShapeDefinitions.xml

Source: ECMA-376 Part 1, 5th edition (December 2016), electronic addendum
``OfficeOpenXML-DrawingMLGeometries.zip`` -> ``presetShapeDefinitions.xml``
SHA-256 ``{sha}``.  A definition without an ``a:rect`` is its whole box; ``upArrow``, which
that file does not define, mirrors ``downArrow``'s (``SUPPLEMENTS`` in the tool).

Each entry is ``name -> (l, t, r, b)``, evaluated against the preset's guides in
:data:`~ooxml_common.drawingml.presets.PRESETS` by
:func:`~ooxml_common.drawingml.geometry.text_rect`.
"""

# fmt: off
PRESET_TEXT_RECTS: dict = {{
'''


def read_source(path: Path) -> bytes:
    data = path.read_bytes()
    if path.suffix == ".zip":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            data = archive.read("presetShapeDefinitions.xml")
    found = hashlib.sha256(data).hexdigest()
    if found != SOURCE_SHA256:
        raise SystemExit(f"presetShapeDefinitions.xml has SHA-256 {found}, expected {SOURCE_SHA256}")
    return data


def compile_rects(data: bytes) -> dict[str, tuple[str, str, str, str]]:
    root = ET.fromstring(data)
    out: dict[str, tuple[str, str, str, str]] = {}
    for shape in root:
        name = shape.tag.split("}")[-1]
        if name in out:
            continue  # upDownArrow is defined twice, identically
        rect = shape.find(f"{{{DRAWINGML_NS}}}rect")
        out[name] = WHOLE_BOX if rect is None else tuple(rect.get(key) for key in ("l", "t", "r", "b"))
    out.update(SUPPLEMENTS)
    return dict(sorted(out.items()))


def render(rects: dict) -> str:
    lines = [HEADER.format(sha=SOURCE_SHA256)]
    for name, rect in rects.items():
        lines.append(f"    {name!r}: {rect!r},\n")
    lines.append("}\n# fmt: on\n")
    return "".join(lines).replace("'", '"')


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    text = render(compile_rects(read_source(args.source)))
    if args.check:
        if TARGET.read_text() != text:
            print(f"{TARGET} is stale", file=sys.stderr)
            return 1
        return 0
    TARGET.write_text(text)
    print(f"wrote {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
