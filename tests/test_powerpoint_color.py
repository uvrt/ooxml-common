"""PowerPoint's measured colour transforms.

Every expected value below was read off PowerPoint 16's PDF export of pptx2svg's
``tools/make_color_probe.py`` (pptx2svg ROADMAP.md, "Colour transforms, measured"), whose
swatches PowerPoint writes as vector fills, so each is the level drawn, exactly.
"""

from __future__ import annotations

from xml.etree.ElementTree import fromstring

import pytest

from ooxml_common.drawingml import color, read
from ooxml_common.drawingml import model as m

A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'


def _t(*pairs):
    return [m.ColorTransform(kind, value) for kind, value in pairs]


# (base, transforms, PowerPoint's level) -- a selection of the probe's 3,108 swatches.
POWERPOINT_SWATCHES = [
    # In order, with the saturation unbounded above, as Word.
    ("ED7D31", _t(("tint", 95000), ("satMod", 170000)), "FF7818"),
    ("4472C4", _t(("satMod", 200000)), "0460FF"),
    ("4472C4", _t(("satMod", 200000), ("satMod", 200000)), "003EFF"),
    ("4472C4", _t(("satMod", 200000), ("satMod", 50000)), "4371C0"),
    ("4472C4", _t(("lumMod", 60000), ("lumOff", 40000)), "8FAADC"),
    ("4472C4", _t(("lumOff", 40000), ("lumMod", 60000)), "517CC8"),
    ("4472C4", _t(("hueOff", 1800000)), "5644C4"),
    ("4472C4", _t(("comp", 0)), "C49644"),
    ("4472C4", _t(("comp", 0), ("lumMod", 50000)), "644C20"),
    ("4472C4", _t(("inv", 0)), "F8EBB3"),
    ("4472C4", _t(("inv", 0), ("tint", 50000)), "FCF5DD"),
    # Kept in scRGB percentages between steps: black at 127.5 levels is 7F.
    ("000000", _t(("lumOff", 50000)), "7F7F7F"),
    # A run of HLS steps stays on sRGB channels: white after the clamp loses its hue.
    ("FFE699", _t(("lumOff", 40000), ("lumMod", 60000)), "999999"),
    # The saturation unbounded below, and a grey given one.
    ("70AD47", _t(("satOff", -50000)), "7C7084"),
    ("808080", _t(("satOff", 25000)), "A06000"),
    ("808080", _t(("satOff", 50000), ("satMod", 50000)), "905030"),
    # Rec. 709 grey; gamma and invGamma.
    ("ED7D31", _t(("gray", 0)), "8F8F8F"),
    ("ED7D31", _t(("gray", 0), ("tint", 50000)), "D1D1D1"),
    ("4472C4", _t(("gamma", 0)), "8DB2E3"),
    ("4472C4", _t(("invGamma", 0)), "0F2B8D"),
    ("4472C4", _t(("gamma", 0), ("tint", 50000)), "D0DDF2"),
    ("4472C4", _t(("invGamma", 0), ("shade", 50000)), "081D66"),
    ("4472C4", _t(("gamma", 0), ("invGamma", 0)), "4472C4"),
]


@pytest.mark.parametrize("base, transforms, expected", POWERPOINT_SWATCHES)
def test_powerpoint_composes_transforms_as_measured(base, transforms, expected):
    assert color.apply_transforms(base, transforms).hex == "#" + expected.lower()


def test_powerpoint_multiplies_and_offsets_the_opacity():
    # Drawn at 64/255 and 191/255.
    assert color.apply_transforms("4472C4", _t(("alpha", 50000), ("alphaMod", 50000))).alpha == 0.25
    assert color.apply_transforms("4472C4", _t(("alpha", 50000), ("alphaOff", 25000))).alpha == 0.75


@pytest.mark.parametrize(
    "element, expected",
    [
        ('<a:scrgbClr r="50000" g="20000" b="0"/>', "BC7C00"),
        ('<a:scrgbClr r="50000" g="20000" b="0"><a:satMod val="150000"/></a:scrgbClr>', "EA8A00"),
        ('<a:hslClr hue="14400000" sat="50000" lum="25000"><a:satMod val="150000"/></a:hslClr>',
         "101070"),
        ('<a:srgbClr val="4472C4"><a:gamma/><a:tint val="50000"/></a:srgbClr>', "D0DDF2"),
    ],
)
def test_the_reader_and_powerpoint_rules_together(element, expected):
    node = fromstring(f"<a:solidFill {A}>{element}</a:solidFill>")
    context = color.ColorContext(None, color.build_effective_color_map())
    assert color.resolve_color(context, read.parse_color(node)).hex == "#" + expected.lower()
