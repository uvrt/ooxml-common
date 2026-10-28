"""The colour Word draws for a theme colour with a tint or shade: :func:`word_theme_tint`.

WordprocessingML names a theme colour with a tint or shade as hex bytes beside it --
``w:color w:themeColor="accent1" w:themeShade="BF"``, ``w:shd w:themeFill="background2"
w:themeFillTint="99"``, a border's ``w:themeColor`` / ``w:themeTint`` -- and keeps an RGB
value too (``w:val``, ``w:fill``).  **Word draws the theme colour, not that value**
(measured, round 21: decoy values were never drawn).

**What is measured.**  Word 16.106 for Mac, 2026-10-28: 560 made-up swatches -- the
Office theme's colours and four random themes, tints and shades from ``01`` to ``FE``, on
table cell shading and on text -- read from Word's PDF, whose colours are Word's sRGB levels
unconverted (an ICC-based sRGB colour space, every value n/255); text and shading gave the
same colour every time.  The same swatches captured on screen (ScreenCaptureKit) agree
with the PDF everywhere the display can tell: greys exactly, colours within the one level
the display's colour conversion blurs.  Lane B's 27 swatches (round 21, T7) agree too.

**The rule, which draws all of them to the level**, is Windows' integer HLS arithmetic
on a scale of ``1530`` (six hue sectors of 255), every step rounded down but the hue's
per-channel terms, which round up:

* ``L = 3 * (max + min)``; ``S = floor(1530 * (max - min) / (max + min))``, or over
  ``510 - max - min`` above the middle; the hue from ``ceil(255 * (max - c) / (max -
  min))`` for each channel ``c``, as Windows' ``ColorRGBToHLS`` combines them;
* a shade ``s``: ``L' = floor(L * s / 255)``; a tint ``t``: ``L' = floor((L * t + 1530 *
  (255 - t)) / 255)``;
* back with ``ColorHLSToRGB``'s two magnitudes (``m2 = floor(L' * (1530 + S) / 1530)`` up
  to the middle, ``L' + S - floor(L' * S / 1530)`` above; ``m1 = 2 * L' - m2``) and the hue
  ramp, each step and each channel (``floor(v * 255 / 1530)``) rounded down.

``FF`` -- or no tint and no shade -- is the theme colour itself (the arithmetic above would
move some colours a level); ``00`` tint is white, ``00`` shade black.  With both a tint
and a shade, the tint alone counts.  A grey is ``floor(L' / 6)`` -- floor of ``grey * s /
255`` for a shade, ``grey * t / 255 + 255 - t`` for a tint.

The float HLS of DrawingML's ``lumMod`` / ``lumOff`` (:mod:`ooxml_common.drawingml.color`)
gets 353 of the 560 to the level and the rest one level off: these attributes are not
DrawingML transforms, and Word does not compute them as one.

Standard library only.
"""

from __future__ import annotations

__all__ = ["word_theme_tint"]

#: The HLS scale: six hue sectors of 255.
SCALE = 1530
_SECTOR = SCALE // 6


def _hex_byte(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        amount = int(value, 16)
    except (TypeError, ValueError):
        return None
    return amount if 0 <= amount <= 255 else None


def word_theme_tint(base: str, tint: str | None = None, shade: str | None = None) -> str:
    """``base`` (``RRGGBB``, a ``#`` allowed) with Word's ``w:themeTint`` / ``w:themeShade``
    (hex bytes, ``"BF"``; ``None`` or an unreadable value: none) applied as Word draws it,
    as upper-case ``RRGGBB`` (module docstring).  With both, the tint alone counts."""
    base = base.lstrip("#").upper()
    r, g, b = (int(base[k:k + 2], 16) for k in (0, 2, 4))
    amount = _hex_byte(tint)
    tinting = amount is not None
    if not tinting:
        amount = _hex_byte(shade)
    if amount is None or amount == 255:
        return base
    high, low = max(r, g, b), min(r, g, b)
    lum = 3 * (high + low)
    if tinting:
        lum2 = (lum * amount + SCALE * (255 - amount)) // 255
    else:
        lum2 = lum * amount // 255
    if high == low:
        grey = lum2 * 255 // SCALE
        return "%02X%02X%02X" % (grey, grey, grey)
    span = high - low
    sat = span * SCALE // (high + low) if high + low <= 255 else span * SCALE // (510 - high - low)

    def term(channel: int) -> int:            # ceil(255 * (high - channel) / span)
        return -((-(high - channel) * _SECTOR) // span)

    rd, gd, bd = term(r), term(g), term(b)
    if r == high:
        hue = bd - gd
    elif g == high:
        hue = SCALE // 3 + rd - bd
    else:
        hue = 2 * SCALE // 3 + gd - rd
    hue %= SCALE
    m2 = lum2 * (SCALE + sat) // SCALE if 2 * lum2 <= SCALE else lum2 + sat - lum2 * sat // SCALE
    m1 = 2 * lum2 - m2

    def channel(h: int) -> int:
        h %= SCALE
        if h < _SECTOR:
            value = m1 + (m2 - m1) * h // _SECTOR
        elif h < SCALE // 2:
            value = m2
        elif h < 2 * SCALE // 3:
            value = m1 + (m2 - m1) * (2 * SCALE // 3 - h) // _SECTOR
        else:
            value = m1
        return max(0, min(255, value * 255 // SCALE))

    return "%02X%02X%02X" % (channel(hue + SCALE // 3), channel(hue), channel(hue - SCALE // 3))
