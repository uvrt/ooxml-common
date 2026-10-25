"""The Office theme a new document gets: its colours, its font scheme and its format scheme.

What PowerPoint and Word write into the theme of a new blank file, which pptx-agent and
docx-agent write the same way when they make one from nothing.  Measured, not copied from
a template: PowerPoint for Mac 16 made a new blank presentation through its AppleScript
(``make new presentation``), Word 16.106 for Mac a new blank document (``make new
document``); each was saved and its ``theme1.xml`` read back.  The two agree on all of it
but one face (:data:`WORD_SCRIPT_FONTS`) and the line widths.

Moved here from the two agents' ``edit/blank.py`` (review, S3), which held a copy each.
Standard library only.
"""

from __future__ import annotations

#: The Office theme's colours (Office 2023 onwards), in ``a:clrScheme`` order: name ->
#: sRGB hex, or ``sys:<system colour>:<lastClr>`` for the two written as ``a:sysClr``.
OFFICE_THEME_COLORS: tuple[tuple[str, str], ...] = (
    ("dk1", "sys:windowText:000000"), ("lt1", "sys:window:FFFFFF"),
    ("dk2", "0E2841"), ("lt2", "E8E8E8"),
    ("accent1", "156082"), ("accent2", "E97132"), ("accent3", "196B24"),
    ("accent4", "0F9ED5"), ("accent5", "A02B93"), ("accent6", "4EA72E"),
    ("hlink", "467886"), ("folHlink", "96607D"),
)

#: The font scheme's Latin faces: headings (``a:majorFont``) and body (``a:minorFont``).
OFFICE_MAJOR_FONT, OFFICE_MINOR_FONT = "Aptos Display", "Aptos"
#: The ``panose`` both Latin faces are written with.
APTOS_PANOSE = "02110004020202020204"

#: Per-script fallback faces of PowerPoint's Office font scheme, in the order it writes
#: them (``a:font script=...``): script -> (major, minor).
POWERPOINT_SCRIPT_FONTS: tuple[tuple[str, str, str], ...] = (
    ("Jpan", "游ゴシック Light", "游ゴシック"), ("Hang", "맑은 고딕", "맑은 고딕"),
    ("Hans", "等线 Light", "等线"), ("Hant", "新細明體", "新細明體"),
    ("Arab", "Times New Roman", "Arial"), ("Hebr", "Times New Roman", "Arial"),
    ("Thai", "Angsana New", "Cordia New"), ("Ethi", "Nyala", "Nyala"),
    ("Beng", "Vrinda", "Vrinda"), ("Gujr", "Shruti", "Shruti"),
    ("Khmr", "MoolBoran", "DaunPenh"), ("Knda", "Tunga", "Tunga"),
    ("Guru", "Raavi", "Raavi"), ("Cans", "Euphemia", "Euphemia"),
    ("Cher", "Plantagenet Cherokee", "Plantagenet Cherokee"),
    ("Yiii", "Microsoft Yi Baiti", "Microsoft Yi Baiti"),
    ("Tibt", "Microsoft Himalaya", "Microsoft Himalaya"), ("Thaa", "MV Boli", "MV Boli"),
    ("Deva", "Mangal", "Mangal"), ("Telu", "Gautami", "Gautami"), ("Taml", "Latha", "Latha"),
    ("Syrc", "Estrangelo Edessa", "Estrangelo Edessa"), ("Orya", "Kalinga", "Kalinga"),
    ("Mlym", "Kartika", "Kartika"), ("Laoo", "DokChampa", "DokChampa"),
    ("Sinh", "Iskoola Pota", "Iskoola Pota"), ("Mong", "Mongolian Baiti", "Mongolian Baiti"),
    ("Viet", "Times New Roman", "Arial"), ("Uigh", "Microsoft Uighur", "Microsoft Uighur"),
    ("Geor", "Sylfaen", "Sylfaen"), ("Armn", "Arial", "Arial"),
    ("Bugi", "Leelawadee UI", "Leelawadee UI"),
    ("Bopo", "Microsoft JhengHei", "Microsoft JhengHei"),
    ("Java", "Javanese Text", "Javanese Text"), ("Lisu", "Segoe UI", "Segoe UI"),
    ("Mymr", "Myanmar Text", "Myanmar Text"), ("Nkoo", "Ebrima", "Ebrima"),
    ("Olck", "Nirmala UI", "Nirmala UI"), ("Osma", "Ebrima", "Ebrima"),
    ("Phag", "Phagspa", "Phagspa"), ("Syrn", "Estrangelo Edessa", "Estrangelo Edessa"),
    ("Syrj", "Estrangelo Edessa", "Estrangelo Edessa"),
    ("Syre", "Estrangelo Edessa", "Estrangelo Edessa"), ("Sora", "Nirmala UI", "Nirmala UI"),
    ("Tale", "Microsoft Tai Le", "Microsoft Tai Le"),
    ("Talu", "Microsoft New Tai Lue", "Microsoft New Tai Lue"), ("Tfng", "Ebrima", "Ebrima"),
)

#: Word's: PowerPoint's but for the Japanese body face, 游明朝 (Yu Mincho) where
#: PowerPoint writes 游ゴシック (Yu Gothic).
WORD_SCRIPT_FONTS: tuple[tuple[str, str, str], ...] = tuple(
    (script, major, "游明朝" if script == "Jpan" else minor)
    for script, major, minor in POWERPOINT_SCRIPT_FONTS
)

#: The format scheme's two gradient fills (``a:fillStyleLst``, after its solid ``phClr``)
#: and its gradient background (``a:bgFillStyleLst``, the last of three): each stop's
#: ``(position, modifiers)``, the stop ``phClr`` with each ``(modifier, value)`` in order.
OFFICE_FILL_GRADIENTS: tuple[tuple[tuple[int, tuple[tuple[str, int], ...]], ...], ...] = (
    ((0, (("lumMod", 110000), ("satMod", 105000), ("tint", 67000))),
     (50000, (("lumMod", 105000), ("satMod", 103000), ("tint", 73000))),
     (100000, (("lumMod", 105000), ("satMod", 109000), ("tint", 81000)))),
    ((0, (("satMod", 103000), ("lumMod", 102000), ("tint", 94000))),
     (50000, (("satMod", 110000), ("lumMod", 100000), ("shade", 100000))),
     (100000, (("lumMod", 99000), ("satMod", 120000), ("shade", 78000)))),
)
OFFICE_BACKGROUND_GRADIENT: tuple[tuple[int, tuple[tuple[str, int], ...]], ...] = (
    (0, (("tint", 93000), ("satMod", 150000), ("shade", 98000), ("lumMod", 102000))),
    (50000, (("tint", 98000), ("satMod", 130000), ("shade", 90000), ("lumMod", 103000))),
    (100000, (("shade", 63000), ("satMod", 120000))),
)

#: The widths of the format scheme's three line styles (``a:lnStyleLst``), EMU: the two
#: applications differ here, PowerPoint's a step wider.
POWERPOINT_LINE_WIDTHS: tuple[int, int, int] = (12700, 19050, 25400)
WORD_LINE_WIDTHS: tuple[int, int, int] = (6350, 12700, 19050)

__all__ = [
    "APTOS_PANOSE", "OFFICE_BACKGROUND_GRADIENT", "OFFICE_FILL_GRADIENTS", "OFFICE_MAJOR_FONT",
    "OFFICE_MINOR_FONT", "OFFICE_THEME_COLORS", "POWERPOINT_LINE_WIDTHS",
    "POWERPOINT_SCRIPT_FONTS", "WORD_LINE_WIDTHS", "WORD_SCRIPT_FONTS",
]
