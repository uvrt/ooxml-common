"""The shape tree and its text as the XML states them, before any inheritance.

Moved from pptx2svg's ``parse/source.py`` with the shape tree reader
(:mod:`~ooxml_common.drawingml.read_tree`) and the text body reader
(:mod:`~ooxml_common.drawingml.read_text`), because a SmartArt diagram's cached drawing
is a shape tree in both formats and a chart's text is a text body.  The slide, layout,
master, theme and table-style types stayed in pptx2svg.

Deliberately *unresolved*.  Theme colours stay as ``SchemeColor("accent1")`` with their
lumMod/tint/shade transforms unapplied, images stay as relationship ids, and ``+mn-lt``
stays as the literal string.  Resolution needs context the reader does not have -- which
theme, which colour map, which style a placeholder inherits -- so it belongs to the
consumer.

``None`` means "not specified here, inherit from the layer above"; that distinction is
what makes placeholder and list-style inheritance work, so no field gets a concrete
default at parse time.

Every type of :mod:`~ooxml_common.drawingml.source` is importable from here too.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Union

from .scene import (
    ArrowEndpoint,
    BulletType,
    CompoundLineType,
    CustomGeometryPath,
    DashStyle,
    LineCap,
    LineJoin,
    RectangleAlignment,
    SpacingValue,
    TabStop,
    TextVerticalType,
)

# --------------------------------------------------------------------------------------
# DrawingML
# --------------------------------------------------------------------------------------

# The unresolved DrawingML types -- colour choices, fills, outlines, shape styles,
# effects, transforms and geometry -- importable from here as well.
from .model import (  # noqa: E402,F401
    ColorTransform,
    ColorTransformKind,
    SchemeColor,
    SourceColor,
    SrgbColor,
    SystemColor,
)
from .source import (  # noqa: E402,F401
    SourceBlipEffects,
    SourceCustomGeometry,
    SourceEffectList,
    SourceFill,
    SourceFormatScheme,
    SourceGeometry,
    SourceGlow,
    SourceGradientFill,
    SourceGradientStop,
    SourceGroupFill,
    SourceImageFill,
    SourceImageFillTile,
    SourceInnerShadow,
    SourceNoFill,
    SourceOuterShadow,
    SourceOutline,
    SourcePatternFill,
    SourcePresetGeometry,
    SourceShapeStyle,
    SourceSoftEdge,
    SourceSolidFill,
    SourceStyleReference,
    SourceTransform,
)


# --------------------------------------------------------------------------------------
# Text
# --------------------------------------------------------------------------------------


@dataclass
class SourceRunProperties:
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None
    #: ``a:rPr@u`` verbatim (``"dbl"``, ``"wavy"``, ``"dotDash"``...) when it is not
    #: ``"sng"``; the bool above only says *whether* the run is underlined.
    underline_style: str | None = None
    strikethrough: bool | None = None
    baseline: float | None = None
    #: points
    font_size: float | None = None
    typeface: str | None = None
    typeface_ea: str | None = None
    typeface_cs: str | None = None
    color: SourceColor | None = None
    highlight: SourceColor | None = None
    outline_width: float | None = None
    outline_color: SourceColor | None = None
    hyperlink_rel_id: str | None = None
    hyperlink_tooltip: str | None = None
    #: ``a:rPr@lang`` verbatim (``"en-US"``, ``"ja-JP"``, ``"ja"``): which of a theme's
    #: East Asian faces ``+mn-ea`` names -- a Japanese run's is the ``Jpan`` entry
    #: (:func:`ooxml_common.text.fontmap.theme_east_asian`).
    lang: str | None = None
    #: ``a:rPr@altLang``: the run's East Asian language where ``lang`` is not one.
    alt_lang: str | None = None


@dataclass
class SourceTextRun:
    text: str
    properties: SourceRunProperties | None = None


@dataclass
class SourceBlipBullet:
    """``a:buBlip`` as parsed -- a relationship id, not yet an image.

    The model's :class:`~ooxml_common.drawingml.scene.BlipBullet` carries the bytes; turning one into
    the other needs the package, which is the resolver's to hold and not the reader's.
    """

    relationship_id: str
    type: Literal["blip"] = "blip"


#: A bullet as *parsed*.  Identical to the model's union except for the picture bullet,
#: which is still a relationship id at this stage.
SourceBulletType = Union[BulletType, SourceBlipBullet]


@dataclass
class SourceParagraphProperties:
    align: Literal["l", "ctr", "r", "just"] | None = None
    level: int | None = None
    line_spacing: SpacingValue | None = None
    space_before: SpacingValue | None = None
    space_after: SpacingValue | None = None
    margin_left: float | None = None
    indent: float | None = None
    bullet: SourceBulletType | None = None
    bullet_font: str | None = None
    bullet_color: SourceColor | None = None
    bullet_size_pct: float | None = None
    #: ``a:buSzPts@val`` in points -- the absolute spelling of a bullet's size.
    bullet_size_points: float | None = None
    tab_stops: list[TabStop] | None = None
    default_run_properties: SourceRunProperties | None = None


@dataclass
class SourceParagraph:
    runs: list[SourceTextRun] = field(default_factory=list)
    properties: SourceParagraphProperties | None = None
    end_para_run_properties: SourceRunProperties | None = None


@dataclass
class SourceTextStyle:
    """``a:lstStyle`` / ``p:titleStyle`` -- per-outline-level default paragraph properties."""

    default_paragraph: SourceParagraphProperties | None = None
    #: index 0 == lvl1pPr ... index 8 == lvl9pPr
    levels: list[SourceParagraphProperties | None] = field(
        default_factory=lambda: [None] * 9
    )


@dataclass
class SourceTextBodyProperties:
    margin_left: float | None = None
    margin_right: float | None = None
    margin_top: float | None = None
    margin_bottom: float | None = None
    anchor: Literal["t", "ctr", "b"] | None = None
    wrap: Literal["square", "none"] | None = None
    auto_fit: Literal["noAutofit", "normAutofit", "spAutofit"] | None = None
    font_scale: float | None = None
    ln_spc_reduction: float | None = None
    num_col: int | None = None
    vert: TextVerticalType | None = None
    rotation: float | None = None
    #: ``a:bodyPr@defTabSz`` -- the interval of the implicit tab stops, in EMU.
    default_tab_size: float | None = None


@dataclass
class SourceTextBody:
    paragraphs: list[SourceParagraph] = field(default_factory=list)
    properties: SourceTextBodyProperties | None = None
    list_style: SourceTextStyle | None = None


# --------------------------------------------------------------------------------------
# Shape tree nodes
# --------------------------------------------------------------------------------------


@dataclass
class SourcePlaceholder:
    type: str | None = None
    idx: int | None = None


@dataclass
class SourceShape:
    name: str | None = None
    shape_id: str | None = None
    alt_text: str | None = None
    placeholder: SourcePlaceholder | None = None
    transform: SourceTransform | None = None
    geometry: SourceGeometry | None = None
    fill: SourceFill | None = None
    outline: SourceOutline | None = None
    effects: SourceEffectList | None = None
    style: SourceShapeStyle | None = None
    text_body: SourceTextBody | None = None
    #: ``dsp:txXfrm`` -- SmartArt places a shape's text box separately from the shape.
    text_transform: SourceTransform | None = None
    #: A custom geometry's ``a:rect`` with the geometry it is evaluated in:
    #: ``(parse_geometry_spec, parse_text_rect)``, or ``None``.
    text_rect: tuple | None = None
    #: ``p:cNvPr@hidden`` -- the shape exists but is not drawn.
    hidden: bool = False
    hyperlink_rel_id: str | None = None
    kind: Literal["shape"] = "shape"


@dataclass
class SourceConnector:
    name: str | None = None
    shape_id: str | None = None
    alt_text: str | None = None
    transform: SourceTransform | None = None
    geometry: SourceGeometry | None = None
    outline: SourceOutline | None = None
    effects: SourceEffectList | None = None
    #: ``p:cNvPr@hidden`` -- the shape exists but is not drawn.
    hidden: bool = False
    style: SourceShapeStyle | None = None
    kind: Literal["connector"] = "connector"


@dataclass
class SourceImage:
    blip_relationship_id: str | None = None
    #: ``asvg:svgBlip@r:embed`` -- the vector original, when the blip carries one.
    svg_relationship_id: str | None = None
    name: str | None = None
    shape_id: str | None = None
    alt_text: str | None = None
    placeholder: SourcePlaceholder | None = None
    transform: SourceTransform | None = None
    geometry: SourceGeometry | None = None
    outline: SourceOutline | None = None
    effects: SourceEffectList | None = None
    blip_effects: SourceBlipEffects | None = None
    src_rect: tuple[float, float, float, float] | None = None
    stretch: tuple[float, float, float, float] | None = None
    tile: SourceImageFillTile | None = None
    #: ``p:cNvPr@hidden`` -- the shape exists but is not drawn.
    hidden: bool = False
    hyperlink_rel_id: str | None = None
    kind: Literal["image"] = "image"


@dataclass
class SourceTableCell:
    text_body: SourceTextBody | None = None
    fill: SourceFill | None = None
    border_top: SourceOutline | None = None
    border_bottom: SourceOutline | None = None
    border_left: SourceOutline | None = None
    border_right: SourceOutline | None = None
    grid_span: int = 1
    row_span: int = 1
    h_merge: bool = False
    v_merge: bool = False
    margin_left: float | None = None
    margin_right: float | None = None
    margin_top: float | None = None
    margin_bottom: float | None = None
    anchor: Literal["t", "ctr", "b"] | None = None


@dataclass
class SourceTableRow:
    height: float = 0.0
    cells: list[SourceTableCell] = field(default_factory=list)


@dataclass
class SourceTable:
    name: str | None = None
    shape_id: str | None = None
    alt_text: str | None = None
    transform: SourceTransform | None = None
    columns: list[float] = field(default_factory=list)
    rows: list[SourceTableRow] = field(default_factory=list)
    #: ``a:tblPr`` flags saying which conditional regions of the table style apply.
    first_row: bool = False
    last_row: bool = False
    first_col: bool = False
    last_col: bool = False
    band_row: bool = False
    band_col: bool = False
    #: ``a:tableStyleId`` -- a GUID, resolved against ``tableStyles.xml`` or the built-in
    #: catalogue.  ``None`` means "use the presentation's default table style".
    #: ``p:cNvPr@hidden`` -- the shape exists but is not drawn.
    hidden: bool = False
    style_id: str | None = None
    kind: Literal["table"] = "table"


@dataclass
class SourceGroup:
    name: str | None = None
    shape_id: str | None = None
    alt_text: str | None = None
    transform: SourceTransform | None = None
    child_transform: SourceTransform | None = None
    fill: SourceFill | None = None
    effects: SourceEffectList | None = None
    #: ``p:cNvPr@hidden`` -- the shape exists but is not drawn.
    hidden: bool = False
    children: list["SourceShapeNode"] = field(default_factory=list)
    kind: Literal["group"] = "group"


@dataclass
class SourceUnsupported:
    """A graphic frame we can position but not draw (chart, SmartArt, OLE, media)."""

    what: str
    name: str | None = None
    shape_id: str | None = None
    alt_text: str | None = None
    transform: SourceTransform | None = None
    #: Relationship id of a rendered fallback, when the frame ships one.
    fallback_rel_id: str | None = None
    #: ``p:cNvPr@hidden`` -- the shape exists but is not drawn.
    hidden: bool = False
    fallback_part: str | None = None
    kind: Literal["unsupported"] = "unsupported"


SourceShapeNode = Union[
    SourceShape, SourceConnector, SourceImage, SourceTable, SourceGroup, SourceUnsupported
]


# --------------------------------------------------------------------------------------
# Colour map
# --------------------------------------------------------------------------------------


@dataclass
class SourceColorMap:
    """``p:clrMap`` / ``p:clrMapOvr`` -- slot name -> colour-scheme key."""

    mapping: dict[str, str] = field(default_factory=dict)
