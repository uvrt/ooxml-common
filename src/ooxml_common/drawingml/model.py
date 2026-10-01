"""DrawingML's value types: colours, fills, outlines, effects, transforms and geometry.

Moved from ``pptx2svg.model`` (which re-exports every name here, so the classes are the
same objects through either path; its text, element and chart types followed to
:mod:`~ooxml_common.drawingml.scene`, and its slide types stayed there).  They are what :mod:`~ooxml_common.drawingml.fill`,
:mod:`~ooxml_common.drawingml.geometry` and :mod:`~ooxml_common.drawingml.effect` draw,
and what :mod:`~ooxml_common.drawingml.color` resolves a colour choice into.

Two stages of a colour live here.  A **colour choice** (:class:`SrgbColor`,
:class:`SchemeColor`, :class:`SystemColor`) is what the XML says: a scheme slot such as
``tx1`` with its ``lumMod`` / ``tint`` / ``alpha`` transforms unapplied, because the colour
map and the theme that give it a value belong to the document, not to the shape.  A
:class:`ResolvedColor` is the concrete ``#rrggbb`` and opacity that choice comes to, and
every fill, outline and effect below carries only resolved colours: by the time anything
is drawn there is no theme left to look anything up in.

Lengths stay in EMU because shape geometry, line widths and effect radii all arrive in
EMU and only become pixels at the moment they are written into the SVG.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Union

# --------------------------------------------------------------------------------------
# Colour choices, as the XML states them
# --------------------------------------------------------------------------------------

ColorTransformKind = Literal[
    "lumMod", "lumOff", "tint", "shade", "alpha", "satMod", "satOff",
    # Read since the reader moved here; applied only under rules that measured them
    # (:data:`~ooxml_common.drawingml.color.WORD`).  ``gray``, ``inv`` and ``comp`` take no
    # value and are carried with 0.
    "hueMod", "hueOff", "gray", "inv", "comp",
]


@dataclass(frozen=True)
class ColorTransform:
    kind: ColorTransformKind
    #: OOXML 1/1000-percent
    value: float


@dataclass
class SrgbColor:
    hex: str
    transforms: list[ColorTransform] = field(default_factory=list)
    kind: Literal["srgb"] = "srgb"
    #: For an ``a:scrgbClr``, its channels as stated -- *linear* light, 0-1 -- which
    #: ``hex`` approximates by reading them as sRGB (the reader's long-standing reading).
    #: Rules that measured the conversion (Word's) start from these instead.  Not part of
    #: the value's identity.
    linear: tuple[float, float, float] | None = field(default=None, compare=False, repr=False)


@dataclass
class SchemeColor:
    """A ``a:schemeClr`` reference; ``scheme`` is a colour-map slot such as ``tx1``."""

    scheme: str
    transforms: list[ColorTransform] = field(default_factory=list)
    kind: Literal["scheme"] = "scheme"


@dataclass
class SystemColor:
    value: str
    last_color: str | None = None
    transforms: list[ColorTransform] = field(default_factory=list)
    kind: Literal["system"] = "system"


SourceColor = Union[SrgbColor, SchemeColor, SystemColor]


# --------------------------------------------------------------------------------------
# Colour and fill
# --------------------------------------------------------------------------------------

ImageMimeType = str
RectangleAlignment = Literal["tl", "t", "tr", "l", "ctr", "r", "bl", "b", "br"]


@dataclass(frozen=True)
class ResolvedColor:
    hex: str
    alpha: float = 1.0


@dataclass
class SolidFill:
    color: ResolvedColor
    type: Literal["solid"] = "solid"


@dataclass
class GradientStop:
    position: float
    color: ResolvedColor


@dataclass
class GradientFill:
    stops: list[GradientStop]
    angle: float = 0.0
    gradient_type: Literal["linear", "radial"] = "linear"
    center_x: float | None = None
    center_y: float | None = None
    type: Literal["gradient"] = "gradient"
    #: What rules that measured the gradient's geometry need (Word's; see
    #: :mod:`~ooxml_common.drawingml.fill`), and pptx2svg's renderer does not read:
    #: ``a:path@path`` (``circle`` / ``rect`` / ``shape``), ``a:fillToRect`` as 0-1 insets,
    #: ``a:lin@scaled`` and ``@rotWithShape``.  Not part of the value's identity.
    path: str | None = field(default=None, compare=False)
    focus: tuple[float, float, float, float] | None = field(default=None, compare=False)
    scaled: bool | None = field(default=None, compare=False)
    rotate_with_shape: bool | None = field(default=None, compare=False)


@dataclass
class ImageFillTile:
    tx: float = 0.0
    ty: float = 0.0
    sx: float = 1.0
    sy: float = 1.0
    flip: Literal["none", "x", "y", "xy"] = "none"
    align: RectangleAlignment = "tl"


@dataclass
class ImageFill:
    #: base64-encoded payload, ready for a ``data:`` URI.
    image_data: str
    mime_type: ImageMimeType
    tile: ImageFillTile | None = None
    type: Literal["image"] = "image"


@dataclass
class PatternFill:
    preset: str
    foreground_color: ResolvedColor
    background_color: ResolvedColor
    type: Literal["pattern"] = "pattern"


@dataclass
class NoFill:
    type: Literal["none"] = "none"


Fill = Union[SolidFill, GradientFill, ImageFill, PatternFill, NoFill]


# --------------------------------------------------------------------------------------
# Line / outline
# --------------------------------------------------------------------------------------

ArrowType = Literal["none", "triangle", "stealth", "diamond", "oval", "arrow"]
ArrowSize = Literal["sm", "med", "lg"]
LineCap = Literal["butt", "round", "square"]
LineJoin = Literal["miter", "round", "bevel"]
#: ``a:ln@cmpd``.  Every value but ``sng`` lays two or three parallel strokes across the
#: stated width; SVG gives a path one centred stroke, so the others are drawn as a single
#: stroke of the full width and declared through the ``line-compound-flattened`` warning.
CompoundLineType = Literal["sng", "dbl", "thickThin", "thinThick", "tri"]
DashStyle = Literal[
    "solid", "dash", "dot", "dashDot", "lgDash", "lgDashDot", "lgDashDotDot", "sysDash", "sysDot"
]


@dataclass
class ArrowEndpoint:
    type: ArrowType
    width: ArrowSize = "med"
    length: ArrowSize = "med"


@dataclass
class Outline:
    #: EMU
    width: float = 9525
    fill: Union[SolidFill, GradientFill, None] = None
    dash_style: DashStyle = "solid"
    custom_dash: list[float] | None = None
    line_cap: LineCap | None = None
    line_join: LineJoin | None = None
    head_end: ArrowEndpoint | None = None
    tail_end: ArrowEndpoint | None = None
    #: ``a:ln@cmpd``.  ``None`` and ``"sng"`` both mean one stroke; anything else is
    #: drawn as one stroke of the full width, which the resolver warns about.
    compound: CompoundLineType | None = None


# --------------------------------------------------------------------------------------
# Effects
# --------------------------------------------------------------------------------------


@dataclass
class OuterShadow:
    blur_radius: float
    distance: float
    #: degrees
    direction: float
    color: ResolvedColor
    alignment: RectangleAlignment = "b"
    rotate_with_shape: bool = True


@dataclass
class InnerShadow:
    blur_radius: float
    distance: float
    direction: float
    color: ResolvedColor


@dataclass
class Glow:
    radius: float
    color: ResolvedColor


@dataclass
class SoftEdge:
    radius: float


@dataclass
class EffectList:
    outer_shadow: OuterShadow | None = None
    inner_shadow: InnerShadow | None = None
    glow: Glow | None = None
    soft_edge: SoftEdge | None = None

    def is_empty(self) -> bool:
        return not (self.outer_shadow or self.inner_shadow or self.glow or self.soft_edge)


@dataclass
class BiLevelEffect:
    threshold: float


@dataclass
class BlurEffect:
    radius: float
    grow: bool = True


@dataclass
class LumEffect:
    brightness: float = 0.0
    contrast: float = 0.0


@dataclass
class DuotoneEffect:
    color1: ResolvedColor
    color2: ResolvedColor


@dataclass
class ClrChangeEffect:
    clr_from: ResolvedColor
    clr_to: ResolvedColor


@dataclass
class BlipEffects:
    grayscale: bool = False
    bi_level: BiLevelEffect | None = None
    blur: BlurEffect | None = None
    lum: LumEffect | None = None
    duotone: DuotoneEffect | None = None
    clr_change: ClrChangeEffect | None = None
    #: ``a:alphaModFix@amt`` -- 0..1 opacity over the whole picture.
    alpha: float | None = None


# --------------------------------------------------------------------------------------
# Transform and geometry
# --------------------------------------------------------------------------------------


@dataclass
class Transform:
    #: all EMU
    offset_x: float = 0.0
    offset_y: float = 0.0
    extent_width: float = 0.0
    extent_height: float = 0.0
    #: degrees
    rotation: float = 0.0
    flip_h: bool = False
    flip_v: bool = False


@dataclass
class PresetGeometry:
    preset: str
    adjust_values: dict[str, float] = field(default_factory=dict)
    type: Literal["preset"] = "preset"


@dataclass
class CustomGeometryPath:
    width: float
    height: float
    #: SVG path data in the path's own coordinate space.
    commands: str


@dataclass
class CustomGeometry:
    paths: list[CustomGeometryPath] = field(default_factory=list)
    type: Literal["custom"] = "custom"


Geometry = Union[PresetGeometry, CustomGeometry]


# --------------------------------------------------------------------------------------
# A picture's crop, stretch and tiling
# --------------------------------------------------------------------------------------


@dataclass
class SrcRect:
    left: float = 0.0
    top: float = 0.0
    right: float = 0.0
    bottom: float = 0.0


@dataclass
class StretchFillRect:
    left: float = 0.0
    top: float = 0.0
    right: float = 0.0
    bottom: float = 0.0


@dataclass
class TileInfo:
    tx: float = 0.0
    ty: float = 0.0
    sx: float = 1.0
    sy: float = 1.0
    flip: Literal["none", "x", "y", "xy"] = "none"
    align: RectangleAlignment = "tl"


# --------------------------------------------------------------------------------------
# Theme
# --------------------------------------------------------------------------------------


@dataclass
class ColorScheme:
    dk1: str = "#000000"
    lt1: str = "#ffffff"
    dk2: str = "#44546a"
    lt2: str = "#e7e6e6"
    accent1: str = "#4472c4"
    accent2: str = "#ed7d31"
    accent3: str = "#a5a5a5"
    accent4: str = "#ffc000"
    accent5: str = "#5b9bd5"
    accent6: str = "#70ad47"
    hlink: str = "#0563c1"
    folHlink: str = "#954f72"
