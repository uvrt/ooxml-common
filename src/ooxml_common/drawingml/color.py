"""Colour resolution: scheme lookup through the colour map, then DrawingML transforms.

Two indirections stack here.  ``a:schemeClr val="tx1"`` names a *colour map slot*, not a
theme colour; the slide master's ``p:clrMap`` says which theme entry (``dk1``, ``lt1``,
...) that slot points at, and a layout or slide may override the map.  Only then do the
transforms -- ``lumMod``, ``lumOff``, ``tint``, ``shade``, ``alpha`` -- apply, in the
order PowerPoint applies them.

**Both applications apply the transforms in document order, on channels clamped to 0-1
between steps, and where they measurably differ the caller says which it is reproducing**,
through :class:`ColorRules` -- :data:`POWERPOINT` (the default) or :data:`WORD`.  Each was
measured against its own application:

* **Word** -- docx2svg's ``tools/make_dml_probe.py`` (its ROADMAP.md, "DrawingML drawn by
  the shared renderers"), 54 swatches, every one Word's to the level under :data:`WORD`.
  The order matters (``lumOff 40000`` before ``lumMod 60000`` is ``517CC8``, not the
  paired ``8FAADC``); the channels stay unrounded between steps (Office's theme gradient
  stops, three transforms each, came out a level off when every step rounded), and the
  result is rounded a half down: black at ``lumMod 50000 lumOff 50000`` (127.5 levels)
  is ``7F7F7F`` (F.3).  ``satMod`` leaves the saturation **unbounded above** --
  ``satMod 200000`` on ``4472C4`` is ``0460FF``, the HLS formula evaluated with a
  saturation over 1 and each channel clamped, where clamping the saturation gives
  ``0961FF``.  ``tint`` and ``shade`` blend in linear light; ``lumMod``, ``lumOff``,
  ``satMod``, ``satOff``, ``hueMod``, ``hueOff`` and ``comp`` (the hue turned half way)
  work in HLS on the sRGB channels; ``gray`` is a Rec. 601 luma of the sRGB channels and
  ``inv`` inverts in linear light; ``a:scrgbClr`` is linear light.

* **PowerPoint** -- pptx2svg's ``tools/make_color_probe.py`` (its ROADMAP.md, "Colour
  transforms, measured"): 3,108 swatches read exactly off PowerPoint 16's PDF export, of
  which :data:`POWERPOINT` draws 3,102 to the level (the composition pptx2svg had before
  drew 1,507, and :data:`WORD`'s draws 2,902).  It composes as Word does, in order and
  with the saturation unbounded above: ``tint 95000 satMod 170000`` on ``ED7D31`` is
  ``FF7818`` (a raster reading of the same fill had put it at ``FF7718``).  What differs:

  - **the colour is kept as linear-light channels in 1/100000** -- an ``a:scrgbClr``'s
    percentages -- from the base colour on, after every step except inside a run of HLS
    transforms, which stays on sRGB channels (each step still clamped) and is kept where
    it ends.  That quantum, and no other, puts the half levels where PowerPoint does:
    3,102 swatches agree with it, against 2,997 kept in 1/1000000, 2,990 in 1/65535, 2,899
    in 1/10000 and 2,960 unrounded; black at ``lumOff 50000`` is ``7F7F7F`` this way, not
    by rounding a half down, and a level kept between two HLS steps puts 28 of the
    swatches a level off;
  - **the saturation is unbounded below** as well: ``satOff -50000`` on ``70AD47`` is
    ``7C7084``, the hue turned over, not the grey ``7A7A7A`` a floor at 0 gives;
  - **a grey given a saturation is red at hue 0 with its blue channel extrapolated**:
    ``satOff 25000`` on ``808080`` is ``A06000`` -- red at the high level, green at the
    low one, blue at ``3 * low - 2 * high``, which is the HLS ramp evaluated a third of a
    turn back without wrapping it;
  - ``gray`` weighs the sRGB channels by **Rec. 709**: ``ED7D31`` is ``8F8F8F``, where
    Rec. 601 gives ``969696``.  (Word's one ``gray`` swatch, ``4472C4``, is ``6E6E6E``
    under either weighting, so :data:`WORD` keeps the 601 it was written with.)
  - ``gamma`` reads the channels as linear light and encodes them as sRGB (``4472C4``
    is ``8DB2E3``), ``invGamma`` the reverse (``0F2B8D``); ``alphaMod`` multiplies the
    opacity and ``alphaOff`` adds to it.  Word's probe had none of these, so :data:`WORD`
    does not apply them.

  What PowerPoint draws and :data:`POWERPOINT` does not: two swatches land within a few
  thousandths of a half level and are drawn a level the other way; and ``lumMod 200000``
  then ``lumOff`` on ``FFE699`` is ``FFDFDF`` (``00FFFF`` for ``lumOff -50000``), where
  the seven other bases measured go white and then grey as the clamp says.

**A known defect, moved as it is.**  PowerPoint shades a chart's accent cycle in linear
light, and HLS ``lumMod`` on sRGB puts accent1's blue at 150 where PowerPoint drew 173
(pptx2svg ROADMAP.md, the ``ofPie`` accent cycle).  That ramp is not a DrawingML transform,
and pptx2svg's chart layout carries its own conversion for it.
"""

from __future__ import annotations

import colorsys
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from .model import ResolvedColor, SourceColor


#: The transforms Word's probe measured, and so the ones :data:`WORD` applies.
WORD_TRANSFORMS = frozenset({
    "lumMod", "lumOff", "satMod", "satOff", "hueMod", "hueOff", "comp", "tint", "shade",
    "inv", "gray", "alpha",
})

#: PowerPoint's, measured: Word's and ``gamma``, ``invGamma``, ``alphaMod``, ``alphaOff``.
POWERPOINT_TRANSFORMS = WORD_TRANSFORMS | {"gamma", "invGamma", "alphaMod", "alphaOff"}

#: Luma weights of the sRGB channels for ``gray``.
REC_601 = (0.299, 0.587, 0.114)
REC_709 = (0.2126, 0.7152, 0.0722)


@dataclass(frozen=True)
class ColorRules:
    """How one application applies a colour's transforms and turns the result into levels.

    Both apply the transforms in document order on channels clamped to 0-1 between steps
    (module docstring).  ``round_channel`` takes a channel as a float on 0-255 and returns
    the level drawn, before clamping.  ``precision`` is the quantum the channels are kept
    in between steps, as linear-light fractions (100000: an ``a:scrgbClr``'s
    percentages), or ``None`` to keep them unrounded.  ``transforms`` are the kinds
    applied; any other is passed over.  ``luma`` weighs the sRGB channels for ``gray``.
    ``negative_saturation`` lets ``satMod`` / ``satOff`` take the saturation below 0, and
    ``achromatic_extrapolates`` draws a grey given a saturation as PowerPoint does.
    """

    name: str
    round_channel: Callable[[float], int]
    precision: int | None = None
    transforms: frozenset[str] = WORD_TRANSFORMS
    luma: tuple[float, float, float] = REC_601
    negative_saturation: bool = False
    achromatic_extrapolates: bool = False


def round_half_even(value: float) -> int:
    """Python's ``round``: the nearest level, a tie to the even one."""
    return int(round(value))


def round_half_down(value: float) -> int:
    """The nearest level, a tie to the lower one: Word's, measured (127.5 -> 127).

    The epsilon is docx2svg's: a channel computed as 127.49999999999999 or 127.50000000001
    from an exact half is a half, not a hair either side of one.
    """
    return math.ceil(value - 0.5 - 1e-9)


#: PowerPoint, as pptx2svg's colour probe measured it.  The default everywhere here.
POWERPOINT = ColorRules(
    "powerpoint",
    round_half_even,
    precision=100000,
    transforms=POWERPOINT_TRANSFORMS,
    luma=REC_709,
    negative_saturation=True,
    achromatic_extrapolates=True,
)

#: Word, as docx2svg measured it: every transform in document order on unrounded
#: channels, the result rounded a half down.
WORD = ColorRules("word", round_half_down)


class Theme(Protocol):
    """What resolution reads from a theme: its ``a:clrScheme``, unresolved."""

    color_scheme: Mapping[str, SourceColor]


class ColorMapOverride(Protocol):
    """``p:clrMap`` / ``p:clrMapOvr``, or Word's ``w:clrSchemeMapping`` once its values
    (``light1``, ``dark1``, ...) are spelled as the slots they name (``lt1``, ``dk1``)."""

    mapping: Mapping[str, str]

#: ``p:clrMap`` when a master does not declare one.
DEFAULT_COLOR_MAP: dict[str, str] = {
    "bg1": "lt1",
    "tx1": "dk1",
    "bg2": "lt2",
    "tx2": "dk2",
    "accent1": "accent1",
    "accent2": "accent2",
    "accent3": "accent3",
    "accent4": "accent4",
    "accent5": "accent5",
    "accent6": "accent6",
    "hlink": "hlink",
    "folHlink": "folHlink",
}

#: Office default theme, used when a deck's theme is missing or incomplete.
FALLBACK_SCHEME_COLORS: dict[str, str] = {
    "dk1": "#000000",
    "lt1": "#ffffff",
    "dk2": "#44546a",
    "lt2": "#e7e6e6",
    "accent1": "#4472c4",
    "accent2": "#ed7d31",
    "accent3": "#a5a5a5",
    "accent4": "#ffc000",
    "accent5": "#5b9bd5",
    "accent6": "#70ad47",
    "hlink": "#0563c1",
    "folHlink": "#954f72",
}

BLACK = ResolvedColor(hex="#000000", alpha=1.0)


class ColorContext:
    """Everything needed to turn a :class:`SourceColor` into a concrete colour."""

    __slots__ = ("theme", "color_map", "scheme", "rules")

    def __init__(
        self,
        theme: Theme | None,
        color_map: dict[str, str],
        rules: ColorRules = POWERPOINT,
    ):
        self.theme = theme
        self.color_map = color_map
        self.rules = rules
        self.scheme = build_color_scheme(theme, color_map, rules)


def build_effective_color_map(
    master: ColorMapOverride | None = None,
    layout_override: ColorMapOverride | None = None,
    slide_override: ColorMapOverride | None = None,
) -> dict[str, str]:
    """Layer the colour maps: schema default < master < layout override < slide override."""
    mapping = dict(DEFAULT_COLOR_MAP)
    for source in (master, layout_override, slide_override):
        if source is not None:
            mapping.update(source.mapping)
    return mapping


def build_color_scheme(
    theme: Theme | None, color_map: dict[str, str], rules: ColorRules = POWERPOINT
) -> dict[str, str]:
    """Flatten the theme's ``a:clrScheme`` into ``{name: "#rrggbb"}``."""
    colors = dict(FALLBACK_SCHEME_COLORS)
    if theme is None:
        return colors
    # A partial context is enough here: scheme entries are srgb/sysClr in practice, and a
    # scheme entry that references another slot is resolved through `colors` as it fills in.
    context = _BootstrapContext(theme, color_map, colors, rules)
    for name, color in theme.color_scheme.items():
        resolved = resolve_color(context, color)
        if resolved is not None:
            colors[name] = resolved.hex
    return colors


class _BootstrapContext:
    """Stand-in context used while the scheme table is still being built."""

    __slots__ = ("theme", "color_map", "scheme", "rules")

    def __init__(self, theme, color_map, scheme, rules: ColorRules = POWERPOINT):
        self.theme = theme
        self.color_map = color_map
        self.scheme = scheme
        self.rules = rules


def resolve_color(
    context: ColorContext | _BootstrapContext,
    color: SourceColor | None,
    visited: frozenset[str] = frozenset(),
) -> ResolvedColor | None:
    if color is None:
        return None
    rules = _rules(context)
    linear = getattr(color, "linear", None)
    if linear is not None:
        return apply_transforms_linear(linear, color.transforms, rules)
    base = _resolve_base_hex(context, color, visited)
    if base is None:
        return None
    return _apply_transforms(base, color.transforms, rules)


def resolve_color_or(
    context: ColorContext | _BootstrapContext,
    color: SourceColor | None,
    default: ResolvedColor = BLACK,
) -> ResolvedColor:
    return resolve_color(context, color) or default


def apply_transforms(
    value: str, transforms, rules: ColorRules = POWERPOINT
) -> ResolvedColor:
    """A concrete colour (``RRGGBB`` or ``#rrggbb``, any case) after its transforms.

    For a consumer that looks up the base colour itself -- docx2svg resolves a theme slot
    through Word's ``w:clrSchemeMapping`` -- and wants only the transforms applied.
    ``transforms`` are :class:`~ooxml_common.drawingml.model.ColorTransform` values
    (anything with ``kind`` and ``value``), in document order.
    """
    return _apply_transforms(_normalize_hex(value), transforms, rules)


def apply_transforms_linear(
    linear: tuple[float, float, float], transforms, rules: ColorRules = POWERPOINT
) -> ResolvedColor:
    """As :func:`apply_transforms`, from channels in linear light (an ``a:scrgbClr``'s)."""
    return _apply_sequential([_linear_to_srgb(v) / 255 for v in linear], transforms, rules)


def _rules(context) -> ColorRules:
    """The context's rules; a context written before there were any is PowerPoint's."""
    return getattr(context, "rules", POWERPOINT)


def _resolve_base_hex(context, color: SourceColor, visited: frozenset[str]) -> str | None:
    if color.kind == "srgb":
        return _normalize_hex(color.hex)
    if color.kind == "system":
        return _normalize_hex(color.last_color or "000000")
    if color.kind == "scheme":
        mapped = context.color_map.get(color.scheme, color.scheme)
        if mapped in visited:
            # A colour map cycle (tx1 -> dk1 -> tx1); stop rather than recurse.
            return "#000000"
        scheme_color = context.theme.color_scheme.get(mapped) if context.theme else None
        if scheme_color is not None:
            resolved = resolve_color(context, scheme_color, visited | {mapped})
            return resolved.hex if resolved is not None else None
        return context.scheme.get(mapped) or FALLBACK_SCHEME_COLORS.get(mapped)
    return None


def _apply_transforms(
    initial_hex: str, transforms, rules: ColorRules = POWERPOINT
) -> ResolvedColor:
    return _apply_sequential([c / 255 for c in _hex_to_rgb(initial_hex)], transforms, rules)


def _normalize_hex(value: str) -> str:
    normalized = value.lstrip("#").lower()
    return f"#{normalized.rjust(6, '0')[:6]}"


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    normalized = value.lstrip("#")
    return (
        int(normalized[0:2], 16),
        int(normalized[2:4], 16),
        int(normalized[4:6], 16),
    )


def _rgb_to_hex(r: float, g: float, b: float, rules: ColorRules = POWERPOINT) -> str:
    return "#" + "".join(f"{max(0, min(255, rules.round_channel(v))):02x}" for v in (r, g, b))


def _linear_to_srgb(value: float) -> float:
    """A linear-light channel, 0-1, as an sRGB level on 0-255 (unrounded)."""
    value = max(0.0, min(1.0, value))
    if value <= 0.0031308:
        return value * 12.92 * 255
    return (1.055 * value ** (1 / 2.4) - 0.055) * 255


def _srgb_to_linear_unit(value: float) -> float:
    """An sRGB channel, 0-1, in linear light, 0-1."""
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


#: The transforms worked in HLS on the sRGB channels.
_HLS_TRANSFORMS = frozenset({"lumMod", "lumOff", "satMod", "satOff", "hueMod", "hueOff", "comp"})


def _apply_sequential(rgb: list[float], transforms, rules: ColorRules) -> ResolvedColor:
    """Each transform in document order on sRGB channels 0-1, clamped between steps and
    kept to ``rules.precision`` except within a run of HLS transforms, rounded to levels
    once at the end (module docstring)."""
    alpha = 1.0
    keep = _keeper(rules.precision)
    rgb = [keep(channel) for channel in rgb]
    applied = [transform for transform in transforms if transform.kind in rules.transforms]
    for index, transform in enumerate(applied):
        kind = transform.kind
        amount = transform.value / 100000
        rgb = [max(0.0, min(1.0, channel)) for channel in rgb]
        if kind in _HLS_TRANSFORMS:
            achromatic = max(rgb) == min(rgb)
            hue, lum, sat = colorsys.rgb_to_hls(*rgb)
            if kind == "lumMod":
                lum = max(0.0, min(1.0, lum * amount))
            elif kind == "lumOff":
                lum = max(0.0, min(1.0, lum + amount))
            elif kind == "satMod":
                sat = sat * amount if rules.negative_saturation else max(0.0, sat * amount)
            elif kind == "satOff":
                sat = sat + amount if rules.negative_saturation else max(0.0, sat + amount)
            elif kind == "hueMod":
                hue = (hue * amount) % 1.0
            elif kind == "hueOff":
                hue = (hue + transform.value / 60000 / 360) % 1.0
            else:
                hue = (hue + 0.5) % 1.0
            rgb = _hls_to_rgb_unbounded(hue, lum, sat)
            if achromatic and sat != 0 and rules.achromatic_extrapolates:
                # PowerPoint's grey is red at hue 0, its blue a third of a turn back on
                # the ramp, unwrapped (module docstring).
                high, low = rgb[0], rgb[1]
                rgb[2] = 3 * low - 2 * high
        elif kind == "tint":
            rgb = [
                _linear_to_srgb(_srgb_to_linear_unit(c) * amount + (1 - amount)) / 255 for c in rgb
            ]
        elif kind == "shade":
            rgb = [_linear_to_srgb(_srgb_to_linear_unit(c) * amount) / 255 for c in rgb]
        elif kind == "inv":
            rgb = [_linear_to_srgb(1 - _srgb_to_linear_unit(c)) / 255 for c in rgb]
        elif kind == "gray":
            luma = sum(weight * c for weight, c in zip(rules.luma, rgb))
            rgb = [luma, luma, luma]
        elif kind == "gamma":
            rgb = [_linear_to_srgb(c) / 255 for c in rgb]
        elif kind == "invGamma":
            rgb = [_srgb_to_linear_unit(c) for c in rgb]
        elif kind == "alpha":
            alpha = amount
        elif kind == "alphaMod":
            alpha = max(0.0, min(1.0, alpha * amount))
        elif kind == "alphaOff":
            alpha = max(0.0, min(1.0, alpha + amount))
        following = applied[index + 1].kind if index + 1 < len(applied) else None
        if not (kind in _HLS_TRANSFORMS and following in _HLS_TRANSFORMS):
            # A run of HLS transforms stays on sRGB channels; it is kept where it ends.
            rgb = [keep(channel) for channel in rgb]
    return ResolvedColor(hex=_rgb_to_hex(*(c * 255 for c in rgb), rules=rules), alpha=alpha)


def _keeper(precision: int | None) -> Callable[[float], float]:
    """What a step's channel becomes before the next: itself, or -- PowerPoint -- its
    linear-light value in ``1 / precision``, an ``a:scrgbClr`` percentage, as sRGB again."""
    if precision is None:
        return lambda channel: channel

    def keep(channel: float) -> float:
        linear = _srgb_to_linear_unit(max(0.0, min(1.0, channel)))
        return _linear_to_srgb(math.floor(linear * precision + 0.5) / precision) / 255

    return keep


def _hls_to_rgb_unbounded(hue: float, lum: float, sat: float) -> list[float]:
    """HLS to RGB by the textbook formula, *not* clamping the saturation to 0-1: both
    applications let ``satMod`` push it past 1 and clamp the channels instead, and
    PowerPoint lets it go below 0 (module docstring)."""
    if sat == 0 or lum in (0.0, 1.0):
        # Black and white whatever the saturation: exactly, not to a rounding error that
        # the next transform would read as a hue.
        return [lum, lum, lum]
    high = lum * (1 + sat) if lum < 0.5 else lum + sat - lum * sat
    low = 2 * lum - high

    def channel(t: float) -> float:
        t %= 1.0
        if t < 1 / 6:
            return low + (high - low) * 6 * t
        if t < 1 / 2:
            return high
        if t < 2 / 3:
            return low + (high - low) * (2 / 3 - t) * 6
        return low

    return [channel(hue + 1 / 3), channel(hue), channel(hue - 1 / 3)]
