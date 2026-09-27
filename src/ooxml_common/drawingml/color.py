"""Colour resolution: scheme lookup through the colour map, then DrawingML transforms.

Two indirections stack here.  ``a:schemeClr val="tx1"`` names a *colour map slot*, not a
theme colour; the slide master's ``p:clrMap`` says which theme entry (``dk1``, ``lt1``,
...) that slot points at, and a layout or slide may override the map.  Only then do the
transforms -- ``lumMod``, ``lumOff``, ``tint``, ``shade``, ``alpha`` -- apply, in the
order PowerPoint applies them.

**Where Word and PowerPoint measurably differ, the caller says which it is reproducing**,
through :class:`ColorRules` -- :data:`POWERPOINT` (the default, and exactly what pptx2svg
has always done) or :data:`WORD`.  One rule is not picked for both, because each was
measured against its own application:

* **Rounding a channel to a level.**  docx2svg measured Word resolving ``lumMod`` /
  ``lumOff`` in HSL and rounding each channel to the nearest level **a half down**: black at
  ``lumMod 50000 lumOff 50000`` (127.5 levels) is drawn ``7F7F7F`` (docx2svg ROADMAP.md,
  "Floating drawings -- measured", F.3; ``tools/make_drawing_probe.py``).  pptx2svg rounds
  with Python's ``round``, half to even -- 127.5 becomes 128, ``808080`` -- and its swatch
  probe found ``lumMod`` / ``lumOff`` within 2/255 of PowerPoint on every swatch (pptx2svg
  ROADMAP.md, "Also found on the way"), which does not settle a half level either way.

* **How transforms compose** -- measured on Word by docx2svg's
  ``tools/make_dml_probe.py`` (ROADMAP.md, "DrawingML drawn by the shared renderers"): 54
  swatches, every one Word's to the level under :data:`WORD` and 36 of them under
  :data:`POWERPOINT`.  Word applies the transforms **in document order**
  (``lumOff 40000`` before ``lumMod 60000`` is ``517CC8``, not the paired ``8FAADC``), **on
  unrounded channels** clamped to 0-1 between steps (Office's theme gradient stops, three
  transforms each, came out a level off when every step rounded), with the **saturation
  unbounded above** (``satMod 200000`` on ``4472C4`` is ``0460FF``: the HLS formula
  evaluated with a saturation over 1, each channel clamped, where clamping the
  saturation gives ``0961FF``), and it applies ``satOff``, ``hueMod``, ``hueOff``,
  ``comp`` (the hue turned half way), ``gray`` (Rec. 601 luma on the sRGB channels) and
  ``inv`` (in linear light), and reads ``a:scrgbClr`` as linear light.  ``tint`` and
  ``shade`` in linear light, and ``lumMod`` / ``lumOff`` / ``satMod`` in HLS, are
  PowerPoint's to the level.  pptx2svg's composition (``lumMod`` with ``lumOff`` in one
  pass wherever they are, a level rounded after every transform, the saturation clamped
  at 1) is unmeasured for PowerPoint beyond its swatches, so :data:`POWERPOINT` keeps it.

**A known defect, moved as it is.**  PowerPoint shades a chart's accent cycle in linear
light, and the HLS-on-sRGB ``lumMod`` here puts accent1's blue at 150 where PowerPoint drew
173 (pptx2svg ROADMAP.md, the ``ofPie`` accent cycle).  pptx2svg's chart ramp carries its
own conversion for that; fixing it here would move every deck, so it is not done in a move.
"""

from __future__ import annotations

import colorsys
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from .model import ResolvedColor, SourceColor


@dataclass(frozen=True)
class ColorRules:
    """How one application applies a colour's transforms and turns the result into levels.

    ``round_channel`` takes a channel as a float on 0-255 and returns the level drawn, before
    clamping.  ``composition`` is ``"paired"`` (pptx2svg's) or ``"sequential"`` (Word's,
    measured); see the module docstring for the evidence behind each instance.
    """

    name: str
    round_channel: Callable[[float], int]
    composition: str = "paired"


def round_half_even(value: float) -> int:
    """Python's ``round``: the nearest level, a tie to the even one.  pptx2svg's rule."""
    return int(round(value))


def round_half_down(value: float) -> int:
    """The nearest level, a tie to the lower one: Word's, measured (127.5 -> 127).

    The epsilon is docx2svg's: a channel computed as 127.49999999999999 or 127.50000000001
    from an exact half is a half, not a hair either side of one.
    """
    return math.ceil(value - 0.5 - 1e-9)


#: PowerPoint, as pptx2svg reproduces it.  The default everywhere here.
POWERPOINT = ColorRules("powerpoint", round_half_even)

#: Word, as docx2svg measured it: every transform in document order on unrounded
#: channels, the result rounded a half down.
WORD = ColorRules("word", round_half_down, "sequential")


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
    if linear is not None and rules.composition == "sequential":
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
    """As :func:`apply_transforms`, from channels in linear light (an ``a:scrgbClr``'s),
    for rules that compose in order (:data:`WORD`); others start from the reader's
    sRGB reading of them."""
    if rules.composition != "sequential":
        hex_value = "".join(f"{round(max(0.0, min(1.0, v)) * 255):02x}" for v in linear)
        return _apply_transforms("#" + hex_value, transforms, rules)
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


def _apply_transforms(initial_hex: str, transforms, rules: ColorRules = POWERPOINT) -> ResolvedColor:
    if rules.composition == "sequential":
        return _apply_sequential([c / 255 for c in _hex_to_rgb(initial_hex)], transforms, rules)
    hex_value = initial_hex
    alpha = 1.0
    kinds = {transform.kind for transform in transforms}

    for transform in transforms:
        kind = transform.kind
        if kind == "lumMod":
            # lumOff is a companion of lumMod; apply both in one pass.
            lum_off = next((t.value for t in transforms if t.kind == "lumOff"), 0)
            hex_value = _apply_luminance(
                hex_value, transform.value / 100000, lum_off / 100000, rules
            )
        elif kind == "lumOff":
            if "lumMod" not in kinds:
                hex_value = _apply_luminance(hex_value, 1.0, transform.value / 100000, rules)
        elif kind == "tint":
            hex_value = _apply_tint(hex_value, transform.value / 100000, rules)
        elif kind == "shade":
            hex_value = _apply_shade(hex_value, transform.value / 100000, rules)
        elif kind == "alpha":
            alpha = transform.value / 100000
        elif kind == "satMod":
            hex_value = _apply_saturation(hex_value, transform.value / 100000, rules)

    return ResolvedColor(hex=hex_value, alpha=alpha)


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


def _apply_luminance(
    value: str, lum_mod: float, lum_off: float, rules: ColorRules = POWERPOINT
) -> str:
    r, g, b = _hex_to_rgb(value)
    hue, lum, sat = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    lum = max(0.0, min(1.0, lum * lum_mod + lum_off))
    red, green, blue = colorsys.hls_to_rgb(hue, lum, sat)
    return _rgb_to_hex(red * 255, green * 255, blue * 255, rules)


def _apply_saturation(value: str, sat_mod: float, rules: ColorRules = POWERPOINT) -> str:
    r, g, b = _hex_to_rgb(value)
    hue, lum, sat = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    sat = max(0.0, min(1.0, sat * sat_mod))
    red, green, blue = colorsys.hls_to_rgb(hue, lum, sat)
    return _rgb_to_hex(red * 255, green * 255, blue * 255, rules)


def _srgb_to_linear(channel: int) -> float:
    value = channel / 255
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(value: float) -> float:
    value = max(0.0, min(1.0, value))
    if value <= 0.0031308:
        return value * 12.92 * 255
    return (1.055 * value ** (1 / 2.4) - 0.055) * 255


def _apply_tint(value: str, amount: float, rules: ColorRules = POWERPOINT) -> str:
    """Keep ``amount`` of the colour and make up the rest with white.

    ECMA-376 defines tint as "a 10% tint is 10% of the input colour combined with 90%
    white" -- so the value is how much of the *original* survives, not how far it moves.
    PowerPoint does the blend in linear-light space, which is why a 40% tint of a mid
    blue comes out visibly paler than a naive sRGB interpolation predicts; verified
    swatch-by-swatch against PowerPoint's own PDF export.
    """
    return _rgb_to_hex(
        *(
            _linear_to_srgb(_srgb_to_linear(channel) * amount + (1 - amount))
            for channel in _hex_to_rgb(value)
        ),
        rules=rules,
    )


def _apply_shade(value: str, amount: float, rules: ColorRules = POWERPOINT) -> str:
    """Keep ``amount`` of the colour and make up the rest with black.

    The linear-light note on :func:`_apply_tint` applies here too.
    """
    return _rgb_to_hex(
        *(
            _linear_to_srgb(_srgb_to_linear(channel) * amount)
            for channel in _hex_to_rgb(value)
        ),
        rules=rules,
    )


def _apply_sequential(rgb: list[float], transforms, rules: ColorRules) -> ResolvedColor:
    """Word's composition (module docstring): each transform in document order on sRGB
    channels 0-1 kept unrounded and clamped between steps, rounded once at the end."""
    alpha = 1.0
    for transform in transforms:
        kind = transform.kind
        amount = transform.value / 100000
        rgb = [max(0.0, min(1.0, channel)) for channel in rgb]
        if kind in ("lumMod", "lumOff", "satMod", "satOff", "hueMod", "hueOff", "comp"):
            hue, lum, sat = colorsys.rgb_to_hls(*rgb)
            if kind == "lumMod":
                lum = max(0.0, min(1.0, lum * amount))
            elif kind == "lumOff":
                lum = max(0.0, min(1.0, lum + amount))
            elif kind == "satMod":
                sat = max(0.0, sat * amount)
            elif kind == "satOff":
                sat = max(0.0, sat + amount)
            elif kind == "hueMod":
                hue = (hue * amount) % 1.0
            elif kind == "hueOff":
                hue = (hue + transform.value / 60000 / 360) % 1.0
            else:
                hue = (hue + 0.5) % 1.0
            rgb = _hls_to_rgb_unbounded(hue, lum, sat)
        elif kind == "tint":
            rgb = [_linear_to_srgb(_srgb_to_linear_unit(c) * amount + (1 - amount)) / 255 for c in rgb]
        elif kind == "shade":
            rgb = [_linear_to_srgb(_srgb_to_linear_unit(c) * amount) / 255 for c in rgb]
        elif kind == "inv":
            rgb = [_linear_to_srgb(1 - _srgb_to_linear_unit(c)) / 255 for c in rgb]
        elif kind == "gray":
            luma = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
            rgb = [luma, luma, luma]
        elif kind == "alpha":
            alpha = amount
    return ResolvedColor(hex=_rgb_to_hex(*(c * 255 for c in rgb), rules=rules), alpha=alpha)


def _srgb_to_linear_unit(value: float) -> float:
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def _hls_to_rgb_unbounded(hue: float, lum: float, sat: float) -> list[float]:
    """HLS to RGB by the textbook formula, *not* clamping the saturation to 1: Word lets
    ``satMod`` push it past 1 and clamps the channels instead (module docstring)."""
    if sat == 0:
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
