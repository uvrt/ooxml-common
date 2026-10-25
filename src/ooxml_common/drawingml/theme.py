"""The Office theme a new document gets: its colours and its font scheme.

What PowerPoint and Word write into the theme of a new blank file, which pptx-agent and
docx-agent write the same way when they make one from nothing.  Measured, not copied from
a template: PowerPoint for Mac 16 made a new blank presentation through its AppleScript
(``make new presentation``), Word 16.106 for Mac a new blank document (``make new
document``); each was saved and its ``theme1.xml`` read back.  The two agree on all of it
but one face (:data:`WORD_SCRIPT_FONTS`).

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

__all__ = [
    "APTOS_PANOSE", "OFFICE_MAJOR_FONT", "OFFICE_MINOR_FONT", "OFFICE_THEME_COLORS",
    "POWERPOINT_SCRIPT_FONTS", "WORD_SCRIPT_FONTS",
]
