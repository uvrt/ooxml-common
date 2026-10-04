"""The chart, shape tree and text body code moved from pptx2svg, exercised from here.

pptx2svg's suite holds the measurements -- every constant in ``chart/layout.py`` has its
probe there, and its VRT snapshots and fidelity baselines hold the output byte for byte.
What this file holds is the promise a second consumer depends on: that the moved code
reads, lays out and draws a chart and a SmartArt drawing with nothing but this package,
given only what a consumer must supply (the theme's faces and colours, and how a fill,
an outline and a title resolve).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from ooxml_common.chart import rules as chart_rules
from ooxml_common.chart.layout import (
    DRAWABLE_CHART_KINDS,
    EMU_PER_POINT,
    ChartBuilder,
    ChartStyle,
    default_font_size,
    drawable_plots,
)
from ooxml_common.chart.read import CHART_GROUP_ELEMENTS, flat_chart_kind, parse_chart_space
from ooxml_common.drawingml import rules as drawing_rules
from ooxml_common.drawingml import scene as m
from ooxml_common.drawingml import source_tree as s
from ooxml_common.drawingml.context import RenderContext
from ooxml_common.drawingml.diagram import (
    diagram_child_transform,
    diagram_drawing_part,
)
from ooxml_common.drawingml.elements import render_element
from ooxml_common.drawingml.read_tree import parse_shape_tree

C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"

BAR_CHART = f"""<c:chartSpace xmlns:c="{C}" xmlns:a="{A}">
  <c:chart>
    <c:plotArea>
      <c:barChart>
        <c:barDir val="col"/><c:grouping val="clustered"/>
        <c:ser>
          <c:idx val="0"/><c:order val="0"/>
          <c:tx><c:strRef><c:strCache><c:ptCount val="1"/>
            <c:pt idx="0"><c:v>Sales</c:v></c:pt></c:strCache></c:strRef></c:tx>
          <c:spPr><a:solidFill><a:srgbClr val="4472C4"/></a:solidFill></c:spPr>
          <c:cat><c:strRef><c:strCache><c:ptCount val="3"/>
            <c:pt idx="0"><c:v>North</c:v></c:pt><c:pt idx="1"><c:v>South</c:v></c:pt>
            <c:pt idx="2"><c:v>West</c:v></c:pt></c:strCache></c:strRef></c:cat>
          <c:val><c:numRef><c:numCache><c:formatCode>General</c:formatCode><c:ptCount val="3"/>
            <c:pt idx="0"><c:v>4</c:v></c:pt><c:pt idx="1"><c:v>7</c:v></c:pt>
            <c:pt idx="2"><c:v>2</c:v></c:pt></c:numCache></c:numRef></c:val>
        </c:ser>
        <c:axId val="1"/><c:axId val="2"/>
      </c:barChart>
      <c:catAx><c:axId val="1"/><c:delete val="0"/><c:axPos val="b"/><c:crossAx val="2"/></c:catAx>
      <c:valAx><c:axId val="2"/><c:delete val="0"/><c:axPos val="l"/><c:crossAx val="1"/></c:valAx>
    </c:plotArea>
    <c:legend><c:legendPos val="r"/></c:legend>
  </c:chart>
</c:chartSpace>"""


def _solid(source):
    if isinstance(source, s.SourceSolidFill) and isinstance(source.color, s.SrgbColor):
        return m.SolidFill(m.ResolvedColor(hex="#" + source.color.hex.upper()))
    return None


def _outline(source):
    return None if source is None else m.Outline(width=source.width or 9525, fill=_solid(source.fill))


def _title(rich, text, size, align):
    return m.TextBody(
        paragraphs=[m.Paragraph(runs=[m.TextRun(text, m.RunProperties(font_size=size))])]
    )


def _build(xml: str, width_pt: float = 360, height_pt: float = 216):
    source = parse_chart_space(ET.fromstring(xml))
    plots = drawable_plots(source)
    builder = ChartBuilder(
        source,
        plots[0],
        width_pt=width_pt,
        height_pt=height_pt,
        style=ChartStyle(
            font_family="Arial",
            font_size=default_font_size(source),
            color=m.ResolvedColor(hex="#000000"),
            accents=[m.ResolvedColor(hex="#4472C4")],
        ),
        resolve_fill=_solid,
        resolve_outline=_outline,
        resolve_text=_title,
        plots=plots,
    )
    return builder, *builder.build()


def test_a_chart_is_read_laid_out_and_drawn_with_this_package_alone():
    builder, children, data = _build(BAR_CHART)

    assert builder.rules is chart_rules.POWERPOINT
    assert data.kind == "barChart" and data.categories == ["North", "South", "West"]
    assert [series.values for series in data.series] == [[4.0, 7.0, 2.0]]

    # Three bars in the series' own fill, among the axis, gridlines and labels.
    bars = [
        child
        for child in children
        if isinstance(child, m.ShapeElement)
        and isinstance(child.fill, m.SolidFill)
        and child.fill.color.hex == "#4472C4"
        and child.text_body is None
    ]
    assert len(bars) >= 3
    texts = {
        run.text
        for child in children
        if isinstance(child, m.ShapeElement) and child.text_body
        for paragraph in child.text_body.paragraphs
        for run in paragraph.runs
    }
    assert {"North", "South", "West", "Sales"} <= texts

    frame = m.Transform(extent_width=360 * EMU_PER_POINT, extent_height=216 * EMU_PER_POINT)
    chart = m.ChartElement(
        transform=frame, chart=data, child_transform=frame, children=children
    )
    context = RenderContext()
    svg = render_element(chart, context)
    assert svg.startswith("<g") and "North" in svg and "#4472C4" in svg


def test_every_group_the_reader_knows_is_one_the_layout_draws():
    assert {flat_chart_kind(kind) for kind in CHART_GROUP_ELEMENTS} == DRAWABLE_CHART_KINDS


def test_powerpoint_is_the_default_everywhere():
    assert RenderContext().rules is drawing_rules.POWERPOINT
    assert chart_rules.POWERPOINT.drawing is drawing_rules.POWERPOINT


class _Package:
    """The part of an OPC package the diagram lookup reads."""

    def __init__(self, parts: dict[str, str], rels: dict[str, dict[str, tuple[str, str]]]):
        self.parts = parts
        self.rels = rels

    def has_part(self, path):
        return path in self.parts

    def read_xml(self, path):
        return ET.fromstring(self.parts[path]) if path in self.parts else None

    def related_part(self, owner, rel_id):
        return self.rels.get(owner, {}).get(rel_id, (None, None))[0]

    def related_parts_of_type(self, owner, rel_type):
        return [target for target, kind in self.rels.get(owner, {}).values() if kind == rel_type]

    def first_related_part(self, owner, rel_type):
        found = self.related_parts_of_type(owner, rel_type)
        return found[0] if found else None


DSP = "http://schemas.microsoft.com/office/drawing/2008/diagram"
DRAWING_REL = "http://schemas.microsoft.com/office/2007/relationships/diagramDrawing"


def test_the_cached_drawing_is_keyed_from_the_data_part_through_the_owner():
    data = (
        f'<dgm:dataModel xmlns:dgm="http://schemas.openxmlformats.org/drawingml/2006/diagram" '
        f'xmlns:dsp="{DSP}"><dgm:extLst><dgm:ext><dsp:dataModelExt relId="rId9"/>'
        "</dgm:ext></dgm:extLst></dgm:dataModel>"
    )
    package = _Package(
        {"word/diagrams/data1.xml": data, "word/diagrams/drawing1.xml": "<x/>",
         "word/diagrams/drawing2.xml": "<x/>"},
        {"word/document.xml": {"rId4": ("word/diagrams/data1.xml", "dm"),
                               "rId9": ("word/diagrams/drawing1.xml", DRAWING_REL),
                               "rId10": ("word/diagrams/drawing2.xml", DRAWING_REL)}},
    )
    assert diagram_drawing_part(package, "word/document.xml", "word/diagrams/data1.xml") == (
        "word/diagrams/drawing1.xml"
    )
    # Without the key, two drawings on the owner cannot be told apart.
    package.parts["word/diagrams/data1.xml"] = "<dgm:dataModel xmlns:dgm='urn:x'/>"
    assert diagram_drawing_part(package, "word/document.xml", "word/diagrams/data1.xml") is None


DATA_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/diagramData"


def _keyed_data_model(rel_id: str) -> str:
    return (
        f'<dgm:dataModel xmlns:dgm="http://schemas.openxmlformats.org/drawingml/2006/diagram" '
        f'xmlns:dsp="{DSP}"><dgm:extLst><dgm:ext><dsp:dataModelExt relId="{rel_id}"/>'
        "</dgm:ext></dgm:extLst></dgm:dataModel>"
    )


def test_the_only_drawing_left_is_not_handed_to_a_diagram_it_does_not_belong_to():
    # Two diagrams on one part; the first's drawing and key were dropped (an editor's
    # invalidated cache), so the part's one drawing is the second diagram's.
    unkeyed = "<dgm:dataModel xmlns:dgm='http://schemas.openxmlformats.org/drawingml/2006/diagram'/>"
    package = _Package(
        {"word/diagrams/data1.xml": unkeyed, "word/diagrams/data2.xml": _keyed_data_model("rId12"),
         "word/diagrams/drawing2.xml": "<x/>"},
        {"word/document.xml": {"rId4": ("word/diagrams/data1.xml", DATA_REL),
                               "rId8": ("word/diagrams/data2.xml", DATA_REL),
                               "rId12": ("word/diagrams/drawing2.xml", DRAWING_REL)}},
    )
    assert diagram_drawing_part(package, "word/document.xml", "word/diagrams/data1.xml") is None
    assert diagram_drawing_part(package, "word/document.xml", "word/diagrams/data2.xml") == (
        "word/diagrams/drawing2.xml"
    )
    # Named from the other data model's own relationships instead: still the other's.
    package.parts["word/diagrams/data2.xml"] = unkeyed
    package.rels["word/diagrams/data2.xml"] = {"rId1": ("word/diagrams/drawing2.xml", DRAWING_REL)}
    assert diagram_drawing_part(package, "word/document.xml", "word/diagrams/data1.xml") is None
    # A drawing no other data model names is still the lone diagram's, as before.
    package.rels["word/diagrams/data2.xml"] = {}
    package.parts["word/diagrams/data2.xml"] = unkeyed
    del package.rels["word/document.xml"]["rId8"]
    assert diagram_drawing_part(package, "word/document.xml", "word/diagrams/data1.xml") == (
        "word/diagrams/drawing2.xml"
    )


def test_a_cached_drawing_is_an_ordinary_shape_tree():
    drawing = ET.fromstring(
        f'<dsp:drawing xmlns:dsp="{DSP}" xmlns:a="{A}"><dsp:spTree>'
        "<dsp:nvGrpSpPr/><dsp:grpSpPr/>"
        '<dsp:sp modelId="{1}"><dsp:nvSpPr><dsp:cNvPr id="0" name=""/><dsp:cNvSpPr/></dsp:nvSpPr>'
        '<dsp:spPr><a:xfrm><a:off x="10" y="20"/><a:ext cx="300" cy="400"/></a:xfrm>'
        '<a:prstGeom prst="ellipse"><a:avLst/></a:prstGeom></dsp:spPr>'
        "<dsp:txBody><a:bodyPr/><a:p><a:r><a:t>Node</a:t></a:r></a:p></dsp:txBody>"
        '<dsp:txXfrm><a:off x="12" y="22"/><a:ext cx="200" cy="300"/></dsp:txXfrm>'
        "</dsp:sp></dsp:spTree></dsp:drawing>"
    )
    sp_tree = drawing.find(f"{{{DSP}}}spTree")
    shapes = parse_shape_tree(sp_tree)
    assert len(shapes) == 1 and isinstance(shapes[0], s.SourceShape)
    assert shapes[0].geometry.preset == "ellipse"
    assert shapes[0].text_body.paragraphs[0].runs[0].text == "Node"
    assert shapes[0].text_transform.width == 200

    frame = m.Transform(offset_x=1000, offset_y=2000, extent_width=500, extent_height=600)
    inner = diagram_child_transform(sp_tree, frame)
    assert (inner.offset_x, inner.offset_y, inner.extent_width, inner.extent_height) == (
        0, 0, 500, 600
    )
