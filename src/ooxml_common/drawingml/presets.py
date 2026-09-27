"""Every ECMA-376 preset geometry: the ones pptx2svg draws by hand, and the whole table.

**Generated file -- do not edit.**  Regenerate with pptx2svg's::

    python3 tools/derive_preset_geometry.py --source presetShapeDefinitions.xml

which writes :mod:`~ooxml_common.drawingml.preset_specs` and this file together, and whose
``--check`` fails when either has drifted from what the source compiles to.

Source: ECMA-376 Part 1, 5th edition (December 2016), electronic addendum
``OfficeOpenXML-DrawingMLGeometries.zip`` -> ``presetShapeDefinitions.xml``
SHA-256 ``2f7c868d857c1e3c4b5a6068759fe0e07d77ad58377a6618d1b02ba3507b6939``, plus ``upArrow``, which that file does not define (it holds
``upDownArrow`` twice instead): ``SUPPLEMENTS`` in the tool says how it was written.

:data:`~ooxml_common.drawingml.preset_specs.PRESET_SPECS` holds the presets pptx2svg
draws *from the specification*; the others it draws with hand-written generators (a
``rect`` as ``<rect>``), which is its renderer's choice and stays so.  A consumer that
wants the specification's geometry for every name -- docx2svg, which had to write five
of these itself -- reads :data:`PRESETS`: both tables, every name ``ST_ShapeType`` allows,
in the same ``name -> (adjustments, guides, paths)`` form.
"""

from .preset_specs import PRESET_SPECS

# fmt: off
OTHER_PRESET_SPECS: dict = {
    "borderCallout1": (
        (("adj1", 18750), ("adj2", -8333), ("adj3", 112500), ("adj4", -38333),),
        (
            ("y1", "*/ h adj1 100000"), ("x1", "*/ w adj2 100000"), ("y2", "*/ h adj3 100000"),
            ("x2", "*/ w adj4 100000"),
        ),
        (
            ("norm", True, None, (
                ("M", "l", "t"), ("L", "r", "t"), ("L", "r", "b"), ("L", "l", "b"), ("Z",),
            )),
            ("none", True, None, (
                ("M", "x1", "y1"), ("L", "x2", "y2"),
            )),
        ),
    ),
    "borderCallout2": (
        (
            ("adj1", 18750), ("adj2", -8333), ("adj3", 18750), ("adj4", -16667),
            ("adj5", 112500), ("adj6", -46667),
        ),
        (
            ("y1", "*/ h adj1 100000"), ("x1", "*/ w adj2 100000"), ("y2", "*/ h adj3 100000"),
            ("x2", "*/ w adj4 100000"), ("y3", "*/ h adj5 100000"), ("x3", "*/ w adj6 100000"),
        ),
        (
            ("norm", True, None, (
                ("M", "l", "t"), ("L", "r", "t"), ("L", "r", "b"), ("L", "l", "b"), ("Z",),
            )),
            ("none", True, None, (
                ("M", "x1", "y1"), ("L", "x2", "y2"), ("L", "x3", "y3"),
            )),
        ),
    ),
    "diamond": (
        (),
        (("ir", "*/ w 3 4"), ("ib", "*/ h 3 4"),),
        (
            ("norm", True, None, (
                ("M", "l", "vc"), ("L", "hc", "t"), ("L", "r", "vc"), ("L", "hc", "b"), ("Z",),
            )),
        ),
    ),
    "ellipse": (
        (),
        (
            ("idx", "cos wd2 2700000"), ("idy", "sin hd2 2700000"), ("il", "+- hc 0 idx"),
            ("ir", "+- hc idx 0"), ("it", "+- vc 0 idy"), ("ib", "+- vc idy 0"),
        ),
        (
            ("norm", True, None, (
                ("M", "l", "vc"), ("A", "wd2", "hd2", "cd2", "cd4"),
                ("A", "wd2", "hd2", "3cd4", "cd4"), ("A", "wd2", "hd2", "0", "cd4"),
                ("A", "wd2", "hd2", "cd4", "cd4"), ("Z",),
            )),
        ),
    ),
    "flowChartAlternateProcess": (
        (),
        (
            ("x2", "+- r 0 ssd6"), ("y2", "+- b 0 ssd6"), ("il", "*/ ssd6 29289 100000"),
            ("ir", "+- r 0 il"), ("ib", "+- b 0 il"),
        ),
        (
            ("norm", True, None, (
                ("M", "l", "ssd6"), ("A", "ssd6", "ssd6", "cd2", "cd4"), ("L", "x2", "t"),
                ("A", "ssd6", "ssd6", "3cd4", "cd4"), ("L", "r", "y2"),
                ("A", "ssd6", "ssd6", "0", "cd4"), ("L", "ssd6", "b"),
                ("A", "ssd6", "ssd6", "cd4", "cd4"), ("Z",),
            )),
        ),
    ),
    "flowChartCollate": (
        (),
        (("ir", "*/ w 3 4"), ("ib", "*/ h 3 4"),),
        (
            ("norm", True, (2, 2), (
                ("M", "0", "0"), ("L", "2", "0"), ("L", "1", "1"), ("L", "2", "2"),
                ("L", "0", "2"), ("L", "1", "1"), ("Z",),
            )),
        ),
    ),
    "flowChartConnector": (
        (),
        (
            ("idx", "cos wd2 2700000"), ("idy", "sin hd2 2700000"), ("il", "+- hc 0 idx"),
            ("ir", "+- hc idx 0"), ("it", "+- vc 0 idy"), ("ib", "+- vc idy 0"),
        ),
        (
            ("norm", True, None, (
                ("M", "l", "vc"), ("A", "wd2", "hd2", "cd2", "cd4"),
                ("A", "wd2", "hd2", "3cd4", "cd4"), ("A", "wd2", "hd2", "0", "cd4"),
                ("A", "wd2", "hd2", "cd4", "cd4"), ("Z",),
            )),
        ),
    ),
    "flowChartDecision": (
        (),
        (("ir", "*/ w 3 4"), ("ib", "*/ h 3 4"),),
        (
            ("norm", True, (2, 2), (
                ("M", "0", "1"), ("L", "1", "0"), ("L", "2", "1"), ("L", "1", "2"), ("Z",),
            )),
        ),
    ),
    "flowChartExtract": (
        (),
        (("x2", "*/ w 3 4"),),
        (
            ("norm", True, (2, 2), (
                ("M", "0", "2"), ("L", "1", "0"), ("L", "2", "2"), ("Z",),
            )),
        ),
    ),
    "flowChartInputOutput": (
        (),
        (("x3", "*/ w 2 5"), ("x4", "*/ w 3 5"), ("x5", "*/ w 4 5"), ("x6", "*/ w 9 10"),),
        (
            ("norm", True, (5, 5), (
                ("M", "0", "5"), ("L", "1", "0"), ("L", "5", "0"), ("L", "4", "5"), ("Z",),
            )),
        ),
    ),
    "flowChartInternalStorage": (
        (),
        (),
        (
            ("norm", False, (1, 1), (
                ("M", "0", "0"), ("L", "1", "0"), ("L", "1", "1"), ("L", "0", "1"), ("Z",),
            )),
            ("none", True, (8, 8), (
                ("M", "1", "0"), ("L", "1", "8"), ("M", "0", "1"), ("L", "8", "1"),
            )),
            ("none", True, (1, 1), (
                ("M", "0", "0"), ("L", "1", "0"), ("L", "1", "1"), ("L", "0", "1"), ("Z",),
            )),
        ),
    ),
    "flowChartManualInput": (
        (),
        (),
        (
            ("norm", True, (5, 5), (
                ("M", "0", "1"), ("L", "5", "0"), ("L", "5", "5"), ("L", "0", "5"), ("Z",),
            )),
        ),
    ),
    "flowChartManualOperation": (
        (),
        (("x3", "*/ w 4 5"), ("x4", "*/ w 9 10"),),
        (
            ("norm", True, (5, 5), (
                ("M", "0", "0"), ("L", "5", "0"), ("L", "4", "5"), ("L", "1", "5"), ("Z",),
            )),
        ),
    ),
    "flowChartMerge": (
        (),
        (("x2", "*/ w 3 4"),),
        (
            ("norm", True, (2, 2), (
                ("M", "0", "0"), ("L", "2", "0"), ("L", "1", "2"), ("Z",),
            )),
        ),
    ),
    "flowChartOffpageConnector": (
        (),
        (("y1", "*/ h 4 5"),),
        (
            ("norm", True, (10, 10), (
                ("M", "0", "0"), ("L", "10", "0"), ("L", "10", "8"), ("L", "5", "10"),
                ("L", "0", "8"), ("Z",),
            )),
        ),
    ),
    "flowChartPredefinedProcess": (
        (),
        (("x2", "*/ w 7 8"),),
        (
            ("norm", False, (1, 1), (
                ("M", "0", "0"), ("L", "1", "0"), ("L", "1", "1"), ("L", "0", "1"), ("Z",),
            )),
            ("none", True, (8, 8), (
                ("M", "1", "0"), ("L", "1", "8"), ("M", "7", "0"), ("L", "7", "8"),
            )),
            ("none", True, (1, 1), (
                ("M", "0", "0"), ("L", "1", "0"), ("L", "1", "1"), ("L", "0", "1"), ("Z",),
            )),
        ),
    ),
    "flowChartPreparation": (
        (),
        (("x2", "*/ w 4 5"),),
        (
            ("norm", True, (10, 10), (
                ("M", "0", "5"), ("L", "2", "0"), ("L", "8", "0"), ("L", "10", "5"),
                ("L", "8", "10"), ("L", "2", "10"), ("Z",),
            )),
        ),
    ),
    "flowChartProcess": (
        (),
        (),
        (
            ("norm", True, (1, 1), (
                ("M", "0", "0"), ("L", "1", "0"), ("L", "1", "1"), ("L", "0", "1"), ("Z",),
            )),
        ),
    ),
    "flowChartPunchedCard": (
        (),
        (),
        (
            ("norm", True, (5, 5), (
                ("M", "0", "1"), ("L", "1", "0"), ("L", "5", "0"), ("L", "5", "5"),
                ("L", "0", "5"), ("Z",),
            )),
        ),
    ),
    "flowChartSort": (
        (),
        (("ir", "*/ w 3 4"), ("ib", "*/ h 3 4"),),
        (
            ("norm", False, (2, 2), (
                ("M", "0", "1"), ("L", "1", "0"), ("L", "2", "1"), ("L", "1", "2"), ("Z",),
            )),
            ("none", True, (2, 2), (
                ("M", "0", "1"), ("L", "2", "1"),
            )),
            ("none", True, (2, 2), (
                ("M", "0", "1"), ("L", "1", "0"), ("L", "2", "1"), ("L", "1", "2"), ("Z",),
            )),
        ),
    ),
    "homePlate": (
        (("adj", 50000),),
        (
            ("maxAdj", "*/ 100000 w ss"), ("a", "pin 0 adj maxAdj"), ("dx1", "*/ ss a 100000"),
            ("x1", "+- r 0 dx1"), ("ir", "+/ x1 r 2"), ("x2", "*/ x1 1 2"),
        ),
        (
            ("norm", True, None, (
                ("M", "l", "t"), ("L", "x1", "t"), ("L", "r", "vc"), ("L", "x1", "b"),
                ("L", "l", "b"), ("Z",),
            )),
        ),
    ),
    "leftBrace": (
        (("adj1", 8333), ("adj2", 50000),),
        (
            ("a2", "pin 0 adj2 100000"), ("q1", "+- 100000 0 a2"), ("q2", "min q1 a2"),
            ("q3", "*/ q2 1 2"), ("maxAdj1", "*/ q3 h ss"), ("a1", "pin 0 adj1 maxAdj1"),
            ("y1", "*/ ss a1 100000"), ("y3", "*/ h a2 100000"), ("y4", "+- y3 y1 0"),
            ("dx1", "cos wd2 2700000"), ("dy1", "sin y1 2700000"), ("il", "+- r 0 dx1"),
            ("it", "+- y1 0 dy1"), ("ib", "+- b dy1 y1"),
        ),
        (
            ("norm", False, None, (
                ("M", "r", "b"), ("A", "wd2", "y1", "cd4", "cd4"), ("L", "hc", "y4"),
                ("A", "wd2", "y1", "0", "-5400000"), ("A", "wd2", "y1", "cd4", "-5400000"),
                ("L", "hc", "y1"), ("A", "wd2", "y1", "cd2", "cd4"), ("Z",),
            )),
            ("none", True, None, (
                ("M", "r", "b"), ("A", "wd2", "y1", "cd4", "cd4"), ("L", "hc", "y4"),
                ("A", "wd2", "y1", "0", "-5400000"), ("A", "wd2", "y1", "cd4", "-5400000"),
                ("L", "hc", "y1"), ("A", "wd2", "y1", "cd2", "cd4"),
            )),
        ),
    ),
    "line": (
        (),
        (),
        (
            ("norm", True, None, (
                ("M", "l", "t"), ("L", "r", "b"),
            )),
        ),
    ),
    "rect": (
        (),
        (),
        (
            ("norm", True, None, (
                ("M", "l", "t"), ("L", "r", "t"), ("L", "r", "b"), ("L", "l", "b"), ("Z",),
            )),
        ),
    ),
    "rightBrace": (
        (("adj1", 8333), ("adj2", 50000),),
        (
            ("a2", "pin 0 adj2 100000"), ("q1", "+- 100000 0 a2"), ("q2", "min q1 a2"),
            ("q3", "*/ q2 1 2"), ("maxAdj1", "*/ q3 h ss"), ("a1", "pin 0 adj1 maxAdj1"),
            ("y1", "*/ ss a1 100000"), ("y3", "*/ h a2 100000"), ("y2", "+- y3 0 y1"),
            ("y4", "+- b 0 y1"), ("dx1", "cos wd2 2700000"), ("dy1", "sin y1 2700000"),
            ("ir", "+- l dx1 0"), ("it", "+- y1 0 dy1"), ("ib", "+- b dy1 y1"),
        ),
        (
            ("norm", False, None, (
                ("M", "l", "t"), ("A", "wd2", "y1", "3cd4", "cd4"), ("L", "hc", "y2"),
                ("A", "wd2", "y1", "cd2", "-5400000"), ("A", "wd2", "y1", "3cd4", "-5400000"),
                ("L", "hc", "y4"), ("A", "wd2", "y1", "0", "cd4"), ("Z",),
            )),
            ("none", True, None, (
                ("M", "l", "t"), ("A", "wd2", "y1", "3cd4", "cd4"), ("L", "hc", "y2"),
                ("A", "wd2", "y1", "cd2", "-5400000"), ("A", "wd2", "y1", "3cd4", "-5400000"),
                ("L", "hc", "y4"), ("A", "wd2", "y1", "0", "cd4"),
            )),
        ),
    ),
    "round1Rect": (
        (("adj", 16667),),
        (
            ("a", "pin 0 adj 50000"), ("dx1", "*/ ss a 100000"), ("x1", "+- r 0 dx1"),
            ("idx", "*/ dx1 29289 100000"), ("ir", "+- r 0 idx"),
        ),
        (
            ("norm", True, None, (
                ("M", "l", "t"), ("L", "x1", "t"), ("A", "dx1", "dx1", "3cd4", "cd4"),
                ("L", "r", "b"), ("L", "l", "b"), ("Z",),
            )),
        ),
    ),
    "round2SameRect": (
        (("adj1", 16667), ("adj2", 0),),
        (
            ("a1", "pin 0 adj1 50000"), ("a2", "pin 0 adj2 50000"), ("tx1", "*/ ss a1 100000"),
            ("tx2", "+- r 0 tx1"), ("bx1", "*/ ss a2 100000"), ("bx2", "+- r 0 bx1"),
            ("by1", "+- b 0 bx1"), ("d", "+- tx1 0 bx1"), ("tdx", "*/ tx1 29289 100000"),
            ("bdx", "*/ bx1 29289 100000"), ("il", "?: d tdx bdx"), ("ir", "+- r 0 il"),
            ("ib", "+- b 0 bdx"),
        ),
        (
            ("norm", True, None, (
                ("M", "tx1", "t"), ("L", "tx2", "t"), ("A", "tx1", "tx1", "3cd4", "cd4"),
                ("L", "r", "by1"), ("A", "bx1", "bx1", "0", "cd4"), ("L", "bx1", "b"),
                ("A", "bx1", "bx1", "cd4", "cd4"), ("L", "l", "tx1"),
                ("A", "tx1", "tx1", "cd2", "cd4"), ("Z",),
            )),
        ),
    ),
    "roundRect": (
        (("adj", 16667),),
        (
            ("a", "pin 0 adj 50000"), ("x1", "*/ ss a 100000"), ("x2", "+- r 0 x1"),
            ("y2", "+- b 0 x1"), ("il", "*/ x1 29289 100000"), ("ir", "+- r 0 il"),
            ("ib", "+- b 0 il"),
        ),
        (
            ("norm", True, None, (
                ("M", "l", "x1"), ("A", "x1", "x1", "cd2", "cd4"), ("L", "x2", "t"),
                ("A", "x1", "x1", "3cd4", "cd4"), ("L", "r", "y2"),
                ("A", "x1", "x1", "0", "cd4"), ("L", "x1", "b"),
                ("A", "x1", "x1", "cd4", "cd4"), ("Z",),
            )),
        ),
    ),
    "rtTriangle": (
        (),
        (("it", "*/ h 7 12"), ("ir", "*/ w 7 12"), ("ib", "*/ h 11 12"),),
        (
            ("norm", True, None, (
                ("M", "l", "b"), ("L", "l", "t"), ("L", "r", "b"), ("Z",),
            )),
        ),
    ),
    "straightConnector1": (
        (),
        (),
        (
            ("none", True, None, (
                ("M", "l", "t"), ("L", "r", "b"),
            )),
        ),
    ),
    "wedgeEllipseCallout": (
        (("adj1", -20833), ("adj2", 62500),),
        (
            ("dxPos", "*/ w adj1 100000"), ("dyPos", "*/ h adj2 100000"),
            ("xPos", "+- hc dxPos 0"), ("yPos", "+- vc dyPos 0"), ("sdx", "*/ dxPos h 1"),
            ("sdy", "*/ dyPos w 1"), ("pang", "at2 sdx sdy"), ("stAng", "+- pang 660000 0"),
            ("enAng", "+- pang 0 660000"), ("dx1", "cos wd2 stAng"), ("dy1", "sin hd2 stAng"),
            ("x1", "+- hc dx1 0"), ("y1", "+- vc dy1 0"), ("dx2", "cos wd2 enAng"),
            ("dy2", "sin hd2 enAng"), ("x2", "+- hc dx2 0"), ("y2", "+- vc dy2 0"),
            ("stAng1", "at2 dx1 dy1"), ("enAng1", "at2 dx2 dy2"),
            ("swAng1", "+- enAng1 0 stAng1"), ("swAng2", "+- swAng1 21600000 0"),
            ("swAng", "?: swAng1 swAng1 swAng2"), ("idx", "cos wd2 2700000"),
            ("idy", "sin hd2 2700000"), ("il", "+- hc 0 idx"), ("ir", "+- hc idx 0"),
            ("it", "+- vc 0 idy"), ("ib", "+- vc idy 0"),
        ),
        (
            ("norm", True, None, (
                ("M", "xPos", "yPos"), ("L", "x1", "y1"),
                ("A", "wd2", "hd2", "stAng1", "swAng"), ("Z",),
            )),
        ),
    ),
    "upArrow": (
        (("adj1", 50000), ("adj2", 50000),),
        (
            ("maxAdj2", "*/ 100000 h ss"), ("a1", "pin 0 adj1 100000"),
            ("a2", "pin 0 adj2 maxAdj2"), ("dy2", "*/ ss a2 100000"), ("y2", "+- t dy2 0"),
            ("dx1", "*/ w a1 200000"), ("x1", "+- hc 0 dx1"), ("x2", "+- hc dx1 0"),
            ("dy1", "*/ x1 dy2 wd2"), ("y1", "+- y2 0 dy1"),
        ),
        (
            ("norm", True, None, (
                ("M", "l", "y2"), ("L", "hc", "t"), ("L", "r", "y2"), ("L", "x2", "y2"),
                ("L", "x2", "b"), ("L", "x1", "b"), ("L", "x1", "y2"), ("Z",),
            )),
        ),
    ),
}

#: Every preset ``ST_ShapeType`` names, from the specification: :data:`PRESET_SPECS` and
#: :data:`OTHER_PRESET_SPECS`, which share no name.
PRESETS: dict = {**PRESET_SPECS, **OTHER_PRESET_SPECS}
