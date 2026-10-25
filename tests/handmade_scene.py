"""A scene written by hand for the golden suite (``tests/test_goldens.py``): what the
generated decks' slides do not carry -- columns, vertical and rotated text, autofit,
every bullet kind and numbering scheme, run decorations, highlights and tabs; groups that
scale unevenly, turn and flip; every effect, on a shape and on a picture; arrowheads,
dashes and compound lines; cropped, outlined and tiled pictures; pattern and path
gradient fills; a table with merged cells.

Each is a list of elements in EMU on a 10 x 7.5 inch page, in :data:`SCENES`.  The pictures are 2 x 2 flat-colour PNGs
written here and one small SVG.
"""

from __future__ import annotations

import base64
import struct
import zlib

from ooxml_common.drawingml import scene as m

WIDTH, HEIGHT = 9144000, 6858000
INCH = 914400


def _png(rgb: tuple[int, int, int]) -> str:
    raw = b"".join(b"\x00" + bytes(rgb) * 2 for _ in range(2))

    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
            + chunk(b"pHYs", struct.pack(">IIB", 3780, 3780, 1))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
    return base64.b64encode(data).decode("ascii")


PNG_RED = _png((200, 40, 40))
PNG_BLUE = _png((40, 70, 200))
SVG = base64.b64encode(
    b'<svg xmlns="http://www.w3.org/2000/svg" width="20" height="10" viewBox="0 0 20 10">'
    b'<rect width="20" height="10" fill="#3a7"/><circle cx="10" cy="5" r="4" fill="#fff"/></svg>'
).decode("ascii")


def color(hex_value: str, alpha: float = 1.0) -> m.ResolvedColor:
    return m.ResolvedColor(hex=hex_value, alpha=alpha)


def box(x: float, y: float, w: float, h: float, **extra) -> m.Transform:
    return m.Transform(offset_x=x * INCH, offset_y=y * INCH, extent_width=w * INCH, extent_height=h * INCH, **extra)


def run(text: str, size: float = 10, **properties) -> m.TextRun:
    return m.TextRun(text, m.RunProperties(font_size=size, font_family=properties.pop("font_family", "Carlito"),
                                           **properties))


def para(*runs: m.TextRun, **properties) -> m.Paragraph:
    return m.Paragraph(runs=list(runs), properties=m.ParagraphProperties(**properties))


def text(*paragraphs: m.Paragraph, **body) -> m.TextBody:
    return m.TextBody(paragraphs=list(paragraphs), body_properties=m.BodyProperties(**body))


def shape(transform, body=None, *, preset="rect", fill=None, outline=None, **extra) -> m.ShapeElement:
    return m.ShapeElement(transform=transform, geometry=m.PresetGeometry(preset=preset), fill=fill, outline=outline,
                          text_body=body, **extra)


LOREM = ("Columns fill one before the next, each to the body's height, with the gap between "
         "them the body's own; a paragraph that does not fit moves on whole.")


def _text_shapes() -> list:
    numbered = [para(run(f"{scheme} item"), bullet=m.AutoNumBullet(scheme=scheme, start_at=start),
                     margin_left=228600, indent=-228600)
                for scheme, start in (("arabicPeriod", 1), ("arabicParenR", 2), ("arabicPlain", 3),
                                      ("romanUcPeriod", 4), ("romanLcPeriod", 1994), ("alphaUcPeriod", 27),
                                      ("alphaLcPeriod", 2), ("alphaUcParenR", 3), ("alphaLcParenR", 52),
                                      ("thaiAlphaPeriod", 1))]
    numbered.append(para(run("continues the arabicPeriod list"), bullet=m.AutoNumBullet(scheme="arabicPeriod"),
                         level=1, margin_left=457200, indent=-228600))
    bullets = [
        para(run("a character bullet in its own colour and size"),
             bullet=m.CharBullet(char="■"), bullet_color=color("#C00000", 0.5), bullet_size_pct=1.5,
             bullet_font="Wingdings", margin_left=228600, indent=-228600),
        para(run("a bullet sized in points"), bullet=m.CharBullet(char="–"), bullet_size_points=14,
             margin_left=228600, indent=-228600),
        para(run("a picture bullet"), bullet=m.BlipBullet(image_data=PNG_BLUE, mime_type="image/png"),
             margin_left=228600, indent=-228600),
        para(run("no bullet at all"), bullet=m.NoBullet()),
        para(run("bullet coloured by its run", color=color("#2E75B6")), bullet=m.CharBullet(char="•"),
             margin_left=228600, indent=-228600),
        para(),
    ]
    decorated = [
        para(run("highlighted", highlight=color("#FFFF00")), run(" and ", highlight=None),
             run("highlighted again", highlight=color("#00FFFF", 0.6)), alignment="ctr"),
        para(run("right-aligned highlight", highlight=color("#FFC000")), alignment="r"),
        para(run("double", underline=True, underline_style="dbl"), run(" wavy", underline=True, underline_style="wavy"),
             run(" dotted", underline=True, underline_style="dotted"), run(" struck", strikethrough=True),
             run(" x", baseline=0.3), run("2", baseline=-0.25), run(" sup", baseline=0.3, size=14)),
        para(run("a link", hyperlink=m.Hyperlink(url="https://example.com/?a=1&b=2", tooltip="made up")),
             run(" outlined", outline=m.TextOutline(width=6350, color=color("#7030A0"))),
             run(" faint", color=color("#000000", 0.4)), run(" bold face", bold=True, font_family="Liberation Sans"),
             run(" synthetic bold", bold=True, font_family="No Such Face", color=color("#203864", 0.7)),
             run(" italic", italic=True)),
        para(run("漢字とLatinが混ざる行 한글", font_family_ea="Noto Sans JP")),
        para(run("tab\tstops\tset\there"), tab_stops=[m.TabStop(position=914400), m.TabStop(position=1828800, alignment="ctr"),
                                                       m.TabStop(position=2743200, alignment="r")]),
        para(run("decimal\t12.50"), tab_stops=[m.TabStop(position=1371600, alignment="dec")]),
        para(run("points line spacing, space before"), line_spacing=m.PointsSpacing(18),
             space_before=m.PointsSpacing(6), space_after=m.PercentSpacing(0.5)),
        para(run("justified text runs to both edges when it wraps onto a second line at this width"),
             alignment="just"),
    ]
    vertical = []
    for index, vert in enumerate(("vert", "vert270", "eaVert", "wordArtVert", "mongolianVert")):
        vertical.append(shape(box(7.0 + 0.55 * index, 0.2, 0.5, 2.0),
                              text(para(run(f"{vert} text runs down")), vert=vert, anchor="ctr", margin_top=0),
                              outline=m.Outline(width=6350, fill=m.SolidFill(color("#808080")))))
    return [
        shape(box(0.2, 0.2, 3.2, 1.6), text(*(para(run(LOREM)) for _ in range(3)), num_col=2),
              outline=m.Outline(width=6350, fill=m.SolidFill(color("#808080")))),
        shape(box(0.2, 1.9, 3.2, 0.6), text(para(run("")), num_col=3)),
        shape(box(3.6, 0.2, 3.2, 2.6), text(*numbered, anchor="b")),
        shape(box(0.2, 2.6, 3.2, 1.8), text(*bullets, auto_fit="normAutofit", font_scale=0.8, ln_spc_reduction=0.1)),
        shape(box(3.6, 2.9, 3.2, 2.4), text(*decorated, auto_fit="spAutofit", wrap="square")),
        shape(box(0.2, 4.5, 3.2, 0.5), text(para(run("no wrap: this line runs past the edge of its box")), wrap="none",
                                             anchor="ctr")),
        shape(box(0.2, 5.1, 2.0, 1.0), text(para(run("text turned inside its shape")), rotation=30, anchor="ctr"),
              preset="ellipse", fill=m.SolidFill(color("#E2F0D9"))),
        shape(box(2.4, 5.1, 1.2, 1.0, rotation=45, flip_h=True), text(para(run("turned and flipped"))),
              preset="triangle", fill=m.SolidFill(color("#FBE5D6"))),
        *vertical,
    ]


def _groups() -> list:
    child = shape(box(0, 0, 1, 1, rotation=30), text(para(run("in a stretched group"))), preset="roundRect",
                  fill=m.SolidFill(color("#DEEBF7")), outline=m.Outline(width=12700, fill=m.SolidFill(color("#2F5597"))))
    plain = shape(box(1, 0, 1, 1), text(para(run("beside it"))), fill=m.SolidFill(color("#FFF2CC")))
    stretched = m.GroupElement(transform=box(7.0, 2.4, 2.0, 0.6), child_transform=box(0, 0, 2, 1),
                               children=[child, plain],
                               effects=m.EffectList(outer_shadow=m.OuterShadow(38100, 25400, 2700000, color("#000000", 0.4))))
    inner = m.GroupElement(transform=box(0.5, 0.5, 1, 1, flip_v=True), child_transform=box(0, 0, 2, 2),
                           children=[shape(box(0, 0, 2, 2), text(para(run("halved, flipped"))), preset="ellipse",
                                           fill=m.SolidFill(color("#C5E0B4")))])
    uniform = m.GroupElement(transform=box(7.0, 3.2, 2.0, 2.0, rotation=15, flip_h=True), child_transform=box(0, 0, 4, 4),
                             children=[shape(box(0, 0, 4, 1), text(para(run("a uniform group at half size"))),
                                             fill=m.SolidFill(color("#F8CBAD"))), inner,
                                       m.ConnectorElement(transform=box(0, 2, 4, 2), geometry=m.PresetGeometry("line"),
                                                          outline=m.Outline(width=25400, fill=m.SolidFill(color("#000000")),
                                                                            tail_end=m.ArrowEndpoint("triangle")))])
    swapped = m.GroupElement(transform=box(7.0, 5.4, 2.0, 1.0, rotation=90), child_transform=box(0, 0, 1, 1),
                             children=[shape(box(0, 0, 1, 1, rotation=90), preset="rightArrow",
                                             fill=m.SolidFill(color("#A9D18E")))])
    empty = m.GroupElement(transform=box(0, 0, 0, 0), child_transform=box(0, 0, 0, 0))
    return [stretched, uniform, swapped, empty]


def _effects_and_lines() -> list:
    shadow = m.EffectList(outer_shadow=m.OuterShadow(50800, 38100, 2700000, color("#000000", 0.5), alignment="tl",
                                                     rotate_with_shape=False),
                          inner_shadow=m.InnerShadow(63500, 25400, 13500000, color("#203864", 0.6)),
                          glow=m.Glow(101600, color("#FFC000", 0.6)), soft_edge=m.SoftEdge(31750))
    elements = [
        shape(box(0.3, 6.3, 0.8, 0.5, rotation=20), preset="star5", fill=m.SolidFill(color("#5B9BD5")), effects=shadow),
        shape(box(1.3, 6.3, 0.8, 0.5), preset="rect", fill=m.SolidFill(color("#ED7D31")),
              effects=m.EffectList(glow=m.Glow(63500, color("#70AD47")))),
        shape(box(2.3, 6.3, 0.8, 0.5), preset="ellipse", fill=m.SolidFill(color("#A5A5A5")),
              effects=m.EffectList(soft_edge=m.SoftEdge(63500))),
        shape(box(3.3, 6.3, 0.8, 0.5), text(para(run("shadowed text box"))),
              effects=m.EffectList(outer_shadow=m.OuterShadow(0, 50800, 5400000, color("#808080")))),
    ]
    heads = ("triangle", "stealth", "diamond", "oval", "arrow")
    for index, (head, dash, compound) in enumerate(zip(heads, ("dash", "sysDot", "lgDashDotDot", "solid", "sysDashDot"),
                                                       ("sng", "dbl", "thickThin", "thinThick", "tri"))):
        elements.append(m.ConnectorElement(
            transform=box(4.3 + 0.5 * index, 5.5, 0.4, 1.2, flip_h=index % 2 == 1),
            geometry=m.PresetGeometry("bentConnector3" if index % 2 else "line"),
            outline=m.Outline(width=19050 + 6350 * index, fill=m.SolidFill(color("#7030A0")), dash_style=dash,
                              line_cap=("rnd", "sq", "flat", "rnd", "sq")[index],
                              line_join=("round", "bevel", "miter", None, "round")[index],
                              head_end=m.ArrowEndpoint(head, ("sm", "med", "lg", "sm", "lg")[index],
                                                       ("lg", "sm", "med", "med", "sm")[index]),
                              tail_end=m.ArrowEndpoint(heads[-1 - index]), compound=compound),
            effects=m.EffectList(outer_shadow=m.OuterShadow(12700, 12700, 0, color("#000000", 0.3))) if index == 0 else None))
    elements.append(m.ConnectorElement(transform=box(6.8, 5.5, 0.1, 1.2), geometry=m.PresetGeometry("line"),
                                       outline=m.Outline(width=12700, fill=m.SolidFill(color("#00B050")),
                                                         custom_dash=[3.0, 1.0, 1.0, 1.0],
                                                         head_end=m.ArrowEndpoint("none"))))
    elements.append(m.ConnectorElement(transform=box(6.9, 5.5, 0.0, 0.0), geometry=m.PresetGeometry("line")))
    return elements


def _pictures_and_fills() -> list:
    effects = m.BlipEffects(grayscale=True, bi_level=m.BiLevelEffect(0.4), blur=m.BlurEffect(12700, grow=False),
                            lum=m.LumEffect(0.2, -0.1), duotone=m.DuotoneEffect(color("#000000"), color("#4472C4")),
                            clr_change=m.ClrChangeEffect(color("#C82828"), color("#C82828", 0.0)), alpha=0.6)
    gradient = m.GradientFill(stops=[m.GradientStop(0.0, color("#FFFFFF")), m.GradientStop(0.6, color("#9DC3E6", 0.8)),
                                     m.GradientStop(1.0, color("#1F4E79"))],
                              gradient_type="radial", center_x=0.3, center_y=0.6, path="rect", focus=(0.3, 0.6, 0.7, 0.4))
    shaped = m.GradientFill(stops=[m.GradientStop(0.0, color("#FFE699")), m.GradientStop(1.0, color("#C55A11"))],
                            gradient_type="radial", center_x=0.5, center_y=0.5, path="shape", focus=(0.5, 0.5, 0.5, 0.5))
    linear = m.GradientFill(stops=[m.GradientStop(0.0, color("#E2F0D9")), m.GradientStop(1.0, color("#385723"))],
                            angle=135, scaled=True, rotate_with_shape=False)
    tiled = m.ImageFill(image_data=PNG_RED, mime_type="image/png",
                        tile=m.ImageFillTile(tx=12700, ty=-25400, sx=2.0, sy=1.5, flip="xy", align="ctr"))
    elements = [
        m.ImageElement(transform=box(0.3, 0.2, 1.0, 0.7), image_data=PNG_RED, mime_type="image/png", blip_effects=effects,
                       src_rect=m.SrcRect(left=0.1, top=0.2, right=0.05, bottom=0.1), geometry=m.PresetGeometry("ellipse"),
                       outline=m.Outline(width=19050, fill=m.SolidFill(color("#000000"))),
                       effects=m.EffectList(outer_shadow=m.OuterShadow(38100, 38100, 2700000, color("#000000", 0.5)),
                                            soft_edge=m.SoftEdge(12700)),
                       hyperlink=m.Hyperlink(url="https://example.com/picture")),
        m.ImageElement(transform=box(1.5, 0.2, 1.0, 0.7, rotation=10), image_data=PNG_BLUE, mime_type="image/png",
                       stretch=m.StretchFillRect(left=-0.1, top=0.1, right=-0.1, bottom=0.1),
                       blip_effects=m.BlipEffects(blur=m.BlurEffect(25400))),
        m.ImageElement(transform=box(2.7, 0.2, 1.0, 0.7), image_data=PNG_BLUE, mime_type="image/png",
                       tile=m.TileInfo(sx=0.5, sy=0.5, flip="x", align="br")),
        m.ImageElement(transform=box(3.9, 0.2, 1.0, 0.5), image_data=SVG, mime_type="image/svg+xml",
                       blip_effects=m.BlipEffects(alpha=0.5)),
        shape(box(0.3, 1.1, 1.0, 0.7), fill=gradient),
        shape(box(1.5, 1.1, 1.0, 0.7), preset="hexagon", fill=shaped),
        shape(box(2.7, 1.1, 1.0, 0.7, rotation=30), fill=linear),
        shape(box(3.9, 1.1, 1.0, 0.7), preset="ellipse", fill=tiled),
        shape(box(5.1, 1.1, 1.0, 0.7), fill=m.ImageFill(image_data=SVG, mime_type="image/svg+xml")),
        shape(box(6.3, 1.1, 1.0, 0.7), fill=m.ImageFill(image_data=PNG_RED, mime_type="image/png",
                                                        tile=m.ImageFillTile(sx=0.25, sy=0.25))),
    ]
    for index, preset in enumerate(("pct5", "pct50", "horz", "vert", "dkDnDiag", "ltUpDiag", "cross", "diagCross",
                                    "smGrid", "lgCheck", "shingle", "weave", "sphere", "noSuchPattern")):
        elements.append(shape(box(0.3 + 0.62 * index, 2.0, 0.55, 0.45), fill=m.PatternFill(
            preset=preset, foreground_color=color("#1F4E79"), background_color=color("#FFFFFF", 0.5 if index % 3 == 0 else 1.0)),
            outline=m.Outline(width=9525, fill=m.GradientFill(stops=[m.GradientStop(0, color("#000000")),
                                                                    m.GradientStop(1, color("#FF0000"))]))))
    return elements


def _table() -> list:
    def cell(label, **extra):
        return m.TableCell(text_body=text(para(run(label)), anchor=extra.pop("anchor", "t")), **extra)

    thin = m.Outline(width=12700, fill=m.SolidFill(color("#000000")))
    rows = [
        m.TableRow(height=0.3 * INCH, cells=[
            cell("spans two", grid_span=2, fill=m.SolidFill(color("#4472C4")),
                 borders=m.CellBorders(top=thin, bottom=thin, left=thin, right=thin)),
            cell("", h_merge=True), cell("third", fill=m.PatternFill("pct20", color("#000000"), color("#FFFFFF")))]),
        m.TableRow(height=0.3 * INCH, cells=[
            cell("spans two rows", row_span=2, anchor="ctr", borders=m.CellBorders(right=thin)),
            cell("a long label that wraps inside its narrow cell and makes the row taller"),
            cell("last", fill=m.NoFill(), anchor="b")]),
        m.TableRow(height=0.2 * INCH, cells=[cell("", v_merge=True), cell("x"), cell("y")]),
    ]
    data = m.TableData(rows=rows, columns=[m.TableColumn(width=0.8 * INCH)] * 3,
                       background=m.SolidFill(color("#F2F2F2")),
                       effects=m.EffectList(outer_shadow=m.OuterShadow(25400, 25400, 2700000, color("#000000", 0.3))))
    return [m.TableElement(transform=box(4.6, 3.0, 2.4, 1.0), table=data)]


#: Each scene on a page of its own, so that a diff names the part that changed.
SCENES = {
    "handmade-text": _text_shapes,
    "handmade-groups": _groups,
    "handmade-effects-and-lines": _effects_and_lines,
    "handmade-pictures-and-fills": _pictures_and_fills,
    "handmade-table": _table,
}
