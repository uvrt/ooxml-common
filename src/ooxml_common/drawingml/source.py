"""DrawingML as the XML states it, before any theme or inheritance resolves it.

Moved from ``pptx2svg.parse.source`` (which re-exports every name here, so the classes are
the same objects through either path; its text and shape tree types followed to
:mod:`~ooxml_common.drawingml.source_tree`, and its slide, theme and table-style types
stayed there).  These are what :mod:`~ooxml_common.drawingml.read` reads a fill, an
outline, a shape style, an effect list, a transform or a geometry into.

Deliberately *unresolved*.  Theme colours stay as ``SchemeColor("accent1")`` with their
``lumMod`` / ``tint`` / ``shade`` transforms unapplied, and images stay as relationship
ids.  Resolution needs context the reader does not have -- which theme, which colour
map, what a placeholder or a group gives -- so it belongs to the consumer, which turns
these into :mod:`~ooxml_common.drawingml.model`'s values for the renderers.

``None`` means "not specified here, inherit from the layer above"; that distinction is
what makes inheritance work, so no field gets a concrete default at parse time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Union

from .model import (  # noqa: F401 -- the colour choices are re-exported
    ArrowEndpoint,
    ColorTransform,
    ColorTransformKind,
    CompoundLineType,
    CustomGeometryPath,
    DashStyle,
    LineCap,
    LineJoin,
    RectangleAlignment,
    SchemeColor,
    SourceColor,
    SrgbColor,
    SystemColor,
)

# --------------------------------------------------------------------------------------
# Fill and line
# --------------------------------------------------------------------------------------


@dataclass
class SourceSolidFill:
    color: SourceColor
    kind: Literal["solid"] = "solid"


@dataclass
class SourceNoFill:
    kind: Literal["none"] = "none"


@dataclass
class SourceGradientStop:
    position: float
    color: SourceColor


@dataclass
class SourceGradientFill:
    stops: list[SourceGradientStop]
    gradient_type: Literal["linear", "radial"] = "linear"
    #: OOXML 1/60000 degrees
    angle: float = 0.0
    center_x: float | None = None
    center_y: float | None = None
    kind: Literal["gradient"] = "gradient"
    #: ``a:path@path`` -- ``circle``, ``rect`` or ``shape`` -- for a path gradient.
    path: str | None = field(default=None, compare=False)
    #: ``a:fillToRect`` as 0-1 insets ``(l, t, r, b)``, for a path gradient.
    focus: tuple[float, float, float, float] | None = field(default=None, compare=False)
    #: ``a:lin@scaled``: whether the angle is scaled with the shape's aspect.
    scaled: bool | None = field(default=None, compare=False)
    #: ``a:gradFill@rotWithShape``.
    rotate_with_shape: bool | None = field(default=None, compare=False)


@dataclass
class SourceImageFillTile:
    tx: float = 0.0
    ty: float = 0.0
    sx: float = 1.0
    sy: float = 1.0
    flip: Literal["none", "x", "y", "xy"] = "none"
    align: RectangleAlignment = "tl"


@dataclass
class SourceImageFill:
    blip_relationship_id: str
    #: ``asvg:svgBlip@r:embed`` -- the vector original, when the blip carries one.
    svg_relationship_id: str | None = None
    tile: SourceImageFillTile | None = None
    src_rect: tuple[float, float, float, float] | None = None
    stretch: tuple[float, float, float, float] | None = None
    kind: Literal["image"] = "image"


@dataclass
class SourcePatternFill:
    preset: str
    foreground_color: SourceColor
    background_color: SourceColor
    kind: Literal["pattern"] = "pattern"


@dataclass
class SourceGroupFill:
    """``a:grpFill`` -- inherit the enclosing group's fill."""

    kind: Literal["group"] = "group"


SourceFill = Union[
    SourceSolidFill,
    SourceNoFill,
    SourceGradientFill,
    SourceImageFill,
    SourcePatternFill,
    SourceGroupFill,
]


@dataclass
class SourceOutline:
    width: float | None = None
    fill: SourceFill | None = None
    dash_style: DashStyle | None = None
    custom_dash: list[float] | None = None
    line_cap: LineCap | None = None
    line_join: LineJoin | None = None
    head_end: ArrowEndpoint | None = None
    tail_end: ArrowEndpoint | None = None
    #: ``a:ln@cmpd`` -- ``sng`` (the default) or one of the multi-stroke spellings.
    compound: CompoundLineType | None = None


@dataclass
class SourceStyleReference:
    """``a:fillRef`` / ``a:lnRef`` / ``a:effectRef`` -- an index into the theme's fmtScheme.

    ``a:fontRef`` is read into the same shape, but its ``idx`` names a font collection of
    the theme's ``a:fontScheme`` rather than a numbered entry: that is ``collection``
    (``"major"``, ``"minor"`` or ``"none"``), and ``idx`` is then 0.  PowerPoint draws the
    shape's text in the collection's face (measured, pptx2svg's ``make_style_probe.py``).
    """

    idx: int
    color: SourceColor | None = None
    collection: str | None = None


@dataclass
class SourceShapeStyle:
    fill_ref: SourceStyleReference | None = None
    line_ref: SourceStyleReference | None = None
    effect_ref: SourceStyleReference | None = None
    font_ref: SourceStyleReference | None = None


# --------------------------------------------------------------------------------------
# Effects
# --------------------------------------------------------------------------------------


@dataclass
class SourceOuterShadow:
    blur_radius: float
    distance: float
    direction: float
    color: SourceColor
    alignment: RectangleAlignment = "b"
    rotate_with_shape: bool = True


@dataclass
class SourceInnerShadow:
    blur_radius: float
    distance: float
    direction: float
    color: SourceColor


@dataclass
class SourceGlow:
    radius: float
    color: SourceColor


@dataclass
class SourceSoftEdge:
    radius: float


@dataclass
class SourceEffectList:
    outer_shadow: SourceOuterShadow | None = None
    inner_shadow: SourceInnerShadow | None = None
    glow: SourceGlow | None = None
    soft_edge: SourceSoftEdge | None = None


@dataclass
class SourceBlipEffects:
    grayscale: bool = False
    bi_level: float | None = None
    blur: tuple[float, bool] | None = None
    lum: tuple[float, float] | None = None
    duotone: tuple[SourceColor, SourceColor] | None = None
    clr_change: tuple[SourceColor, SourceColor] | None = None
    #: ``a:alphaModFix@amt`` -- 0..1 opacity applied to the whole picture.
    alpha: float | None = None


# --------------------------------------------------------------------------------------
# Geometry and transform
# --------------------------------------------------------------------------------------


@dataclass
class SourceTransform:
    offset_x: float
    offset_y: float
    width: float
    height: float
    #: OOXML 1/60000 degrees
    rotation: float = 0.0
    flip_horizontal: bool = False
    flip_vertical: bool = False


@dataclass
class SourcePresetGeometry:
    preset: str
    adjust_values: dict[str, float] = field(default_factory=dict)
    kind: Literal["preset"] = "preset"


@dataclass
class SourceCustomGeometry:
    paths: list[CustomGeometryPath] = field(default_factory=list)
    kind: Literal["custom"] = "custom"


SourceGeometry = Union[SourcePresetGeometry, SourceCustomGeometry]


# --------------------------------------------------------------------------------------
# The theme's format scheme
# --------------------------------------------------------------------------------------


@dataclass
class SourceFormatScheme:
    """``a:fmtScheme``: what a shape style's ``idx`` indexes (ECMA-376 20.1.4.1.14)."""

    fill_styles: list[SourceFill] = field(default_factory=list)
    line_styles: list[SourceOutline] = field(default_factory=list)
    effect_styles: list[SourceEffectList | None] = field(default_factory=list)
    bg_fill_styles: list[SourceFill] = field(default_factory=list)
