"""This package's output on made-up inputs, held byte for byte (``tests/goldens.py``).

Every input is generated, none collected: the chart parts, shape trees and resolved
scenes of pptx2svg's two generated decks (``tools/make_chart_gallery.py``,
``tools/make_feature_sweep.py``, whose docstrings say what each slide carries), and the
chart parts pptx2svg's own tests write inline.  ``tests/fixtures/*.json`` names each
one's source.  No Office output and no third-party document is among them.

* **charts** -- each chart part read (:func:`~ooxml_common.chart.read.parse_chart_space`),
  laid out (:class:`~ooxml_common.chart.layout.ChartBuilder`, under PowerPoint's rules and,
  where the manifest says so, Word's) and drawn (:func:`~ooxml_common.drawingml.elements.
  render_element`), as one SVG;
* **trees** -- each ``p:spTree`` read (:func:`~ooxml_common.drawingml.read_tree.
  parse_shape_tree`), as its source model in JSON;
* **themes** -- each theme's colour and format schemes read, as their source model;
* **scenes** -- each resolved slide drawn by :func:`~ooxml_common.drawingml.elements.
  render_element`, under PowerPoint's rules and Word's, as one SVG -- and the scenes
  ``tests/handmade_scene.py`` builds, for what those slides do not carry;
* **metafiles** -- EMF and WMF files of every record kind the players read
  (``tests/metafile_sweep.py``) drawn as SVG, and the bitmaps they carry decoded;
* **presets** -- every preset geometry drawn as a shape with its name for text, under
  both rules, and each one's path data and text rectangle as a consumer that draws the
  paths itself reads them.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest

import goldens
import handmade_scene
import metafile_sweep
from ooxml_common.metafile import inline_metafile_images, metafile_to_svg
from ooxml_common.metafile.dib import decode_dib, dib_to_image
from ooxml_common.drawingml import scene as m
from ooxml_common.drawingml.geometry import (
    PRESET_ALIASES,
    PRESET_GEOMETRIES,
    path_ends,
    preset_path_data,
    text_rect,
    trim_path,
)
from ooxml_common.drawingml.presets import PRESETS
from ooxml_common.drawingml.read import parse_color_scheme, parse_format_scheme
from ooxml_common.drawingml.read_tree import parse_shape_tree
from ooxml_common.xmlutil import child

CHARTS = goldens.manifest("charts")
TREES = goldens.manifest("trees")
SCENES = goldens.manifest("scenes")
THEMES = goldens.manifest("themes")

CHART_CASES = [(name, rules) for name, entry in CHARTS.items() for rules in entry["rules"]]


@pytest.mark.parametrize("name,rules", CHART_CASES, ids=[f"{name}-{rules}" for name, rules in CHART_CASES])
def test_a_chart_lays_out_and_draws_as_it_did(request, name, rules):
    entry = CHARTS[name]
    xml = ET.parse(goldens.FIXTURES / "charts" / f"{name}.xml").getroot()
    element, notes = goldens.chart_element(xml, entry["width_pt"], entry["height_pt"], rules, entry.get("locale"))
    if element is None:
        produced = "".join(f"<!-- {note} -->\n" for note in notes)
    else:
        produced = goldens.svg_document([element], element.transform.extent_width,
                                        element.transform.extent_height, rules, notes)
    goldens.check(request, goldens.GOLDEN / "charts" / f"{name}-{rules}.svg", produced)


@pytest.mark.parametrize("name", list(TREES))
def test_a_shape_tree_reads_as_it_did(request, name):
    tree = ET.parse(goldens.FIXTURES / "trees" / f"{name}.xml").getroot()
    goldens.check(request, goldens.GOLDEN / "trees" / f"{name}.json", goldens.dump_text(parse_shape_tree(tree)))


@pytest.mark.parametrize("name", list(THEMES))
def test_a_theme_reads_as_it_did(request, name):
    elements = child(ET.parse(goldens.FIXTURES / "themes" / f"{name}.xml").getroot(), "themeElements")
    read = {"colors": parse_color_scheme(child(elements, "clrScheme")),
            "formats": parse_format_scheme(child(elements, "fmtScheme"))}
    goldens.check(request, goldens.GOLDEN / "themes" / f"{name}.json", goldens.dump_text(read))


SCENE_CASES = [(name, rules) for name in [*SCENES, *handmade_scene.SCENES] for rules in goldens.RULES]


@pytest.mark.parametrize("name,rules", SCENE_CASES, ids=[f"{name}-{rules}" for name, rules in SCENE_CASES])
def test_a_scene_draws_as_it_did(request, name, rules):
    if name in handmade_scene.SCENES:
        elements, width, height = handmade_scene.SCENES[name](), handmade_scene.WIDTH, handmade_scene.HEIGHT
    else:
        data = json.loads((goldens.FIXTURES / "scenes" / f"{name}.json").read_text(encoding="utf-8"))
        elements, width, height = goldens.from_data(data["elements"]), data["width_emu"], data["height_emu"]
    produced = goldens.svg_document(elements, width, height, rules)
    goldens.check(request, goldens.GOLDEN / "scenes" / f"{name}-{rules}.svg", produced)


# -- preset geometry ---------------------------------------------------------------------

#: Each preset in a 1.2 x 0.75 inch box, eight to a row, its name as its text.
CELL_W, CELL_H, GAP, PER_ROW = 1097280, 685800, 182880, 8


def _preset_sheet() -> tuple[list, float, float]:
    elements = []
    names = sorted(PRESET_GEOMETRIES) + ["noSuchPreset"]
    for index, name in enumerate(names):
        column, row = index % PER_ROW, index // PER_ROW
        transform = m.Transform(offset_x=GAP + column * (CELL_W + GAP), offset_y=GAP + row * (CELL_H + GAP),
                                extent_width=CELL_W, extent_height=CELL_H, rotation=0.0)
        body = m.TextBody(paragraphs=[m.Paragraph(runs=[m.TextRun(name, m.RunProperties(font_size=7))],
                                                  properties=m.ParagraphProperties(alignment="ctr"))],
                          body_properties=m.BodyProperties(anchor="ctr"))
        elements.append(m.ShapeElement(
            transform=transform, geometry=m.PresetGeometry(preset=name),
            fill=m.SolidFill(m.ResolvedColor("#DCE6F2")),
            outline=m.Outline(width=12700, fill=m.SolidFill(m.ResolvedColor("#1F4E79"))),
            text_body=body))
    rows = -(-len(names) // PER_ROW)
    return elements, GAP + PER_ROW * (CELL_W + GAP), GAP + rows * (CELL_H + GAP)


@pytest.mark.parametrize("rules", list(goldens.RULES))
def test_every_preset_draws_as_it_did(request, rules):
    elements, width, height = _preset_sheet()
    goldens.check(request, goldens.GOLDEN / "presets" / f"sheet-{rules}.svg",
                  goldens.svg_document(elements, width, height, rules))


def test_every_preset_s_path_data_and_text_rectangle_are_as_they_were(request):
    """What a consumer drawing each path itself reads (docx2svg does): the paths, their
    paint flags, the text rectangle, and an open path's ends and its trimmed form."""
    out = {}
    for name in sorted(PRESETS) + sorted(PRESET_ALIASES) + ["noSuchPreset"]:
        paths = preset_path_data(name, 120, 72, x=4, y=2)
        entry = {"text_rect": [round(value, 4) for value in text_rect(("preset", name, {}), 120, 72)]}
        if paths is None:
            entry["paths"] = None
        else:
            entry["paths"] = []
            for path in paths:
                item = {"d": path.d, "fill": path.fill, "stroke": path.stroke}
                ends = path_ends(path.d)
                if ends is not None:
                    item["ends"] = [[round(value, 4) for value in end] for end in ends]
                    item["trimmed"] = trim_path(path.d, 3, 4)
                entry["paths"].append(item)
        out[name] = entry
    goldens.check(request, goldens.GOLDEN / "presets" / "path-data.json",
                  json.dumps(out, indent=1, ensure_ascii=False) + "\n")


# -- metafiles ----------------------------------------------------------------------------


@pytest.mark.parametrize("name", list(metafile_sweep.METAFILES))
def test_a_metafile_draws_as_it_did(request, name):
    drawing = metafile_to_svg(metafile_sweep.METAFILES[name]())
    assert drawing is not None
    notes = [f"{drawing.width:g} x {drawing.height:g} px; {drawing.drawn} drawn; emf+ {drawing.emf_plus}; "
             f"gdi fallback {drawing.gdi_fallback}; truncated {drawing.truncated}",
             f"warning: {drawing.warning()}"]
    produced = "".join(f"<!-- {note} -->\n" for note in notes) + drawing.svg.decode("utf-8") + "\n"
    goldens.check(request, goldens.GOLDEN / "metafiles" / f"{name}.svg", goldens.stable(produced))


def test_a_metafile_picture_in_a_page_is_drawn_in_place(request):
    """``inline_metafile_images``: a page's pictures that :func:`metafile_to_svg` drew,
    written inline as nested ``<svg>``s for a rasteriser that draws no text in an SVG
    picture; any other picture left as it is."""
    import base64

    def image(data, extra="", mime="image/svg+xml"):
        return f'<image {extra}width="40" height="30" href="data:{mime};base64,{base64.b64encode(data).decode()}"/>'

    drawn = metafile_to_svg(metafile_sweep.emf_text()).svg
    page = ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
            + image(drawn, 'x="5" y="5" transform="rotate(5)" ')
            + image(metafile_to_svg(metafile_sweep.wmf_placeable()).svg, 'preserveAspectRatio="none" ')
            + image(drawn, 'clip-path="url(#c)" ')
            + image(b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>')
            + image(b"<svg " + b" " * 200 + b'xmlns="http://www.w3.org/2000/svg"/>')
            + image(b"\x89PNG\r\n\x1a\n", mime="image/png")
            + '<image width="1" height="1" href="data:image/svg+xml;base64,!!!!"/>'
            + "</svg>")
    goldens.check(request, goldens.GOLDEN / "metafiles" / "inlined-page.svg",
                  goldens.stable(inline_metafile_images(page)) + "\n")
    assert inline_metafile_images("<svg/>") == "<svg/>"


def test_a_device_independent_bitmap_decodes_as_it_did(request):
    out = {}
    for name, (header, bits) in metafile_sweep.DIBS.items():
        image = dib_to_image(header, bits)
        pixels = decode_dib(header, bits)
        out[name] = {
            "image": None if image is None else [image.mime_type, goldens.png_identity(image.data)
                                                 if image.mime_type == "image/png" else len(image.data)],
            "pixels": None if pixels is None else goldens.dump(pixels),
        }
    goldens.check(request, goldens.GOLDEN / "metafiles" / "dibs.json", json.dumps(out, indent=1) + "\n")


def test_every_fixture_is_in_its_manifest():
    for kind, listed, suffix in (("charts", CHARTS, ".xml"), ("trees", TREES, ".xml"), ("scenes", SCENES, ".json"),
                                 ("themes", THEMES, ".xml")):
        found = {path.name[: -len(suffix)] for path in (goldens.FIXTURES / kind).glob("*" + suffix)}
        assert found == set(listed), kind
        assert all(entry.get("source") for entry in listed.values()), kind


def test_every_golden_has_a_case():
    expected = {f"charts/{name}-{rules}.svg" for name, rules in CHART_CASES}
    expected |= {f"trees/{name}.json" for name in TREES} | {f"scenes/{name}-{rules}.svg" for name, rules in SCENE_CASES}
    expected |= {f"presets/sheet-{rules}.svg" for rules in goldens.RULES} | {"presets/path-data.json"}
    expected |= {f"themes/{name}.json" for name in THEMES}
    expected |= {f"metafiles/{name}.svg" for name in metafile_sweep.METAFILES}
    expected |= {"metafiles/inlined-page.svg", "metafiles/dibs.json"}
    found = {path.relative_to(goldens.GOLDEN).as_posix() for path in goldens.GOLDEN.rglob("*") if path.is_file()}
    assert found <= expected, sorted(found - expected)
