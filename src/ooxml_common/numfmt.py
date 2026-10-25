"""Number format codes (ECMA-376 Part 1, 18.8.31): one reading of a code, for every library.

A cell, a chart's cache and a data label keep a number with a format code that says how it
is shown: ``#,##0.00``, ``0%``, ``[$-413]d mmmm yyyy``, ``[h]:mm:ss``.  This module reads a
code once -- :func:`sections` cuts it, :func:`tokens` lexes a section, :func:`classify`
says what the section shows -- so that "is this a date?" has one answer wherever it is
asked.  Printing a number is not done here (:func:`ooxml_common.dates.format_serial`
prints a date, :func:`ooxml_common.chart.layout.format_number` a number).

**Sections.**  A code has up to four, cut at a ``;`` that is not quoted (``"a;b"``),
escaped (``\\;``) or the character after a ``_`` or ``*`` (``_;``, ``*;``): positive;
negative; zero; text.  Measured, Excel for Mac 16.106, 2026-10-25: ``0\\;0``, ``0_;0`` and
``0*;0`` showed 46027.5 as ``4602;8``, ``4602 8`` and ``4602;;;...8`` -- one section each.

**Which section decides.**  :func:`classify` and :func:`is_date_code` read the *first*
section unless told another (``section=1`` for a negative number's, ``2`` a zero's): the
first is the one a positive number is shown with, and what Excel itself calls the code.
Measured the same day: under ``0;[Red]d`` and ``0.00E+00;d`` a positive serial showed as a
number (``46028``, ``4,60E+04``) and ``CELL("format")`` answered a number (``F0-``,
``S2``), while the negative serial showed ``####`` -- a date that cannot be shown, its own
section's answer; under ``[>=100]d;0`` the positive serial showed its day (``5``).  A
caller printing one value asks about the section that value is shown with.

**What makes a section a date or a time** (:func:`classify`), outside quoted text, an
escaped character, the character after ``_`` or ``*``, and brackets -- each measured in
Excel (a serial shown as a date or time, 2026-10-25):

* dates: ``d``, ``m`` (a month), ``y``, ``e`` (``[$-411]e`` showed ``8``, the era's
  year; ``e`` alone the year), ``g`` (the era: ``[$-ja-JP]ggge`` showed ``令和8``), ``b``
  (the Buddhist year: ``bbbb`` showed ``2569``) and the Thai letters ``ว`` ``ด`` ``ป``
  (``[$-th-TH]ว/ด/ปปปป`` showed ``5/1/2026``; without the prefix ``๕/๑/๒๕๖๙``);
* times: ``h``, ``s``, ``m`` as minutes (right after an hour or right before a second,
  text between them aside: ``h "x" m`` showed ``12 x 0``, ``m s`` ``0 0``, ``yyyy m``
  ``2026 1``), ``AM/PM``, ``A/P``, the markers ``上午/下午`` (``下午`` alone), and the Thai
  ``ช`` ``น`` ``ท`` (``ช:นน`` showed ``๑๒:๐๐``);
* elapsed time: ``[h]``, ``[mm]``, ``[ss]`` (any repeat, ``[hhh]``) and Thai ``[ช]``,
  alone or not (``[h]`` showed ``1104660``, ``[ss]`` ``3976776000``);
* the system's formats: a first section with ``[$-F800]`` (``[$-x-sysdate]``) is the
  system's long date and one with ``[$-F400]`` (``[$-x-systime]``) its time, whatever
  else it holds (``[$-F800]0.00`` showed ``maandag 5 januari 2026``, ``[$-F400]`` alone
  ``12:00:00``); in a later section, or beside an ``@``, Excel drops the id
  (``0;[$-F800]`` read back as ``0;[$]``, a negative number shown as nothing;
  ``[$-F800]@`` as ``[$]@``, a text), so it is not read there.

``E+``/``E-`` is an exponent, not an era year; ``General`` is the general format and
``@`` the text; ``%`` makes a percent.  A colour (``[Red]``), a condition (``[<100]``)
and a currency or language (``[$€-413]``, ``[$-409]``) do not change the kind.

Standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["DATE_KINDS", "KINDS", "MEASURED", "TOKEN_KINDS", "Classification", "Token", "classify",
           "is_date_code", "sections", "tokens"]

#: Every kind :func:`classify` answers.
KINDS = ("general", "number", "percent", "date", "time", "datetime", "text")

#: The kinds that show a number as a date, a time or both.
DATE_KINDS = ("date", "time", "datetime")

#: Every kind of :class:`Token`.
TOKEN_KINDS = (
    "date",       # a run of one date letter: d, m (a month), y, e, g, b, ว ด ป -- "mmmm"
    "time",       # a run of one time letter: h, s, m (minutes), ช น ท -- "hh"
    "elapsed",    # elapsed time in brackets, without them: "h", "mm", "ss", "ช"
    "ampm",       # "AM/PM", "A/P" (any case) or "上午/下午"
    "digit",      # one digit placeholder: 0, # or ?
    "exponent",   # "E+" or "E-" (any case)
    "percent",    # %
    "general",    # "General" (any case)
    "text",       # @, the text itself
    "quoted",     # a quoted text, without its quotes
    "escaped",    # the character after a backslash
    "pad",        # the character after _, whose width is left blank
    "fill",       # the character after *, repeated to fill the cell
    "color",      # [Red], [Color10]: the bracket's inside
    "condition",  # [<100], [>=0]: the bracket's inside
    "locale",     # [$€-413], [$-409], [$-x-sysdate]: the inside after the $
    "bracket",    # any other bracket ([DBNum1], [ ]): its inside
    "letter",     # a letter that is no token
    "literal",    # any other character, shown as it is
)

#: The colours a bracket names (18.8.31), besides ``[ColorN]``.
_COLORS = frozenset({"black", "blue", "cyan", "green", "magenta", "red", "white", "yellow"})
#: Letters read as dates and as times (lower case), and the Thai ones (18.8.30's th-TH
#: table: ว day, ด month, ป year; ช hour, น minute, ท second).
_DATE_LETTERS = frozenset("dmyegb") | frozenset("วดป")
_TIME_LETTERS = frozenset("hs") | frozenset("ชนท")
_HOURS = frozenset("hช")
_SECONDS = frozenset("sท")
#: AM/PM markers, longest first.
_AMPM = ("AM/PM", "A/P")
_AMPM_EXACT = ("上午/下午",)
#: The system's long date and time format ids (an LCID's low word, as Excel writes
#: ``[$-x-sysdate]`` and ``[$-x-systime]`` back).
_SYSTEM_DATE = 0xF800
_SYSTEM_TIME = 0xF400


@dataclass(frozen=True)
class Token:
    """One piece of a section: ``kind`` (one of :data:`TOKEN_KINDS`) and ``text`` (as the
    code writes it, case kept; a bracket's inside without the brackets)."""

    kind: str
    text: str


@dataclass(frozen=True)
class Classification:
    """What one section shows (:func:`classify`): ``kind`` (one of :data:`KINDS`);
    ``elapsed`` whether its time is elapsed time (``[h]:mm:ss``); ``lcid`` the id of
    its last ``[$...-LCID]`` with a hexadecimal id (``[$-409]`` is ``0x409``), else
    ``None``."""

    kind: str
    elapsed: bool = False
    lcid: int | None = None

    @property
    def is_date(self) -> bool:
        """Whether the section shows a number as a date, a time or both."""
        return self.kind in DATE_KINDS


def sections(code: str) -> list[str]:
    """``code`` cut into its sections (positive; negative; zero; text) at each ``;`` that
    is not quoted, escaped or the character after ``_`` or ``*``."""
    out: list[str] = []
    start, index, length, quoted = 0, 0, len(code), False
    while index < length:
        char = code[index]
        if char == '"':
            quoted = not quoted
        elif not quoted and char in "\\_*":
            index += 1
        elif not quoted and char == ";":
            out.append(code[start:index])
            start = index + 1
        index += 1
    out.append(code[start:])
    return out


def tokens(section: str) -> list[Token]:
    """One section (:func:`sections`) as its :class:`Token` list, in order.  A run of one
    date or time letter is one token (``yyyy``, ``mm``; any case), and each ``m`` run is a
    ``date`` (a month) or a ``time`` (minutes) by the module's rule.  An unclosed quote or
    bracket runs to the end of the section."""
    out: list[Token] = []
    index, length = 0, len(section)
    while index < length:
        char = section[index]
        lower = char.lower()
        if char == '"':
            close = section.find('"', index + 1)
            close = length if close < 0 else close
            out.append(Token("quoted", section[index + 1:close]))
            index = close + 1
        elif char in "\\_*":
            kind = {"\\": "escaped", "_": "pad", "*": "fill"}[char]
            out.append(Token(kind, section[index + 1:index + 2]))
            index += 2
        elif char == "[":
            close = section.find("]", index + 1)
            close = length if close < 0 else close
            out.append(_bracket(section[index + 1:close]))
            index = close + 1
        elif section[index:index + 7].lower() == "general":
            out.append(Token("general", section[index:index + 7]))
            index += 7
        elif any(section[index:index + len(m)].upper() == m for m in _AMPM):
            size = next(len(m) for m in _AMPM if section[index:index + len(m)].upper() == m)
            out.append(Token("ampm", section[index:index + size]))
            index += size
        elif any(section.startswith(m, index) for m in _AMPM_EXACT):
            size = next(len(m) for m in _AMPM_EXACT if section.startswith(m, index))
            out.append(Token("ampm", section[index:index + size]))
            index += size
        elif lower == "e" and section[index + 1:index + 2] in ("+", "-"):
            out.append(Token("exponent", section[index:index + 2]))
            index += 2
        elif lower in _DATE_LETTERS or lower in _TIME_LETTERS:
            end = index
            while end < length and section[end].lower() == lower:
                end += 1
            out.append(Token("time" if lower in _TIME_LETTERS else "date",
                             section[index:end]))
            index = end
        elif char in "0#?":
            out.append(Token("digit", char))
            index += 1
        elif char == "%":
            out.append(Token("percent", char))
            index += 1
        elif char == "@":
            out.append(Token("text", char))
            index += 1
        else:
            out.append(Token("letter" if char.isalpha() else "literal", char))
            index += 1
    return _minutes(out)


def _bracket(inner: str) -> Token:
    low = inner.lower()
    if low and low[0] in "hms" and low == low[0] * len(low):
        return Token("elapsed", inner)
    if inner and inner[0] in _TIME_LETTERS and inner == inner[0] * len(inner):
        return Token("elapsed", inner)
    if inner.startswith("$"):
        return Token("locale", inner[1:])
    if low in _COLORS or (low.startswith("color") and low[5:].isdigit()):
        return Token("color", inner)
    if inner[:1] in ("<", ">", "="):
        return Token("condition", inner)
    return Token("bracket", inner)


def _role(token: Token) -> str | None:
    """``h``, ``s`` or ``m`` for a token an ``m`` run's reading looks at; ``other`` for
    any other date or time token; ``None`` for a token it looks past."""
    if token.kind in ("date", "time", "elapsed"):
        first = token.text[0].lower()
        if first in _HOURS:
            return "h"
        if first in _SECONDS:
            return "s"
        if first == "m" and token.kind != "elapsed":
            return "m"
        return "other"
    return "other" if token.kind == "ampm" else None


def _minutes(found: list[Token]) -> list[Token]:
    """Each ``m`` run as minutes when the date or time token before it is an hour or the
    one after it a second, else as a month."""
    marks = [(position, _role(token)) for position, token in enumerate(found)]
    marks = [(position, role) for position, role in marks if role is not None]
    for at, (position, role) in enumerate(marks):
        if role != "m":
            continue
        before = marks[at - 1][1] if at else None
        after = marks[at + 1][1] if at + 1 < len(marks) else None
        kind = "time" if before == "h" or after == "s" else "date"
        found[position] = Token(kind, found[position].text)
    return found


def _locale_id(text: str) -> int | None:
    """A locale token's id: the hexadecimal part after its last ``-``."""
    if "-" not in text:
        return None
    try:
        return int(text.rpartition("-")[2], 16)
    except ValueError:
        return None


def _system_id(text: str) -> int | None:
    """The system format a locale token names: ``x-sysdate`` and ``x-systime`` (as Excel
    writes them back, ``F800`` and ``F400``), or an id whose low word is one of them."""
    language = text.partition("-")[2].lower()
    if language == "x-sysdate":
        return _SYSTEM_DATE
    if language == "x-systime":
        return _SYSTEM_TIME
    number = _locale_id(text)
    if number is not None and (number & 0xFFFF) in (_SYSTEM_DATE, _SYSTEM_TIME):
        return number & 0xFFFF
    return None


def classify(code: str, section: int | None = None) -> Classification:
    """What a format code shows (:class:`Classification`): its first section's kind, or
    section ``section``'s (0 positive, 1 negative, 2 zero, 3 text; :class:`IndexError`
    for one the code does not have).

    ``datetime`` for a date and a time, ``date``, ``time``; else ``percent`` with a
    ``%``, ``text`` with an ``@`` and no digit placeholder, ``general`` with ``General``
    and no digit placeholder, and ``number`` for anything else (an empty code too).  The
    module's notes say what is a date and a time, as measured."""
    parts = sections(code)
    if section is not None and not 0 <= section < len(parts):
        raise IndexError(f"the code {code!r} has {len(parts)} section(s), not a section "
                         f"{section}; sections count from 0")
    found = tokens(parts[0 if section is None else section])
    has_date = has_time = elapsed = percent = text = general = digits = False
    lcid = None
    systems: set[int | None] = set()
    for token in found:
        kind = token.kind
        if kind == "date":
            has_date = True
        elif kind in ("time", "ampm"):
            has_time = True
        elif kind == "elapsed":
            has_time = elapsed = True
        elif kind == "locale":
            number = _locale_id(token.text)
            if number is not None:
                lcid = number
            if not section:
                systems.add(_system_id(token.text))
        elif kind in ("digit", "exponent"):
            digits = True
        elif kind == "percent":
            percent = True
        elif kind == "text":
            text = True
        elif kind == "general":
            general = True
    if not text:
        # The system's formats, in a first section that is not the text's.
        has_date = has_date or _SYSTEM_DATE in systems
        has_time = has_time or _SYSTEM_TIME in systems
    if has_date and has_time:
        return Classification("datetime", elapsed, lcid)
    if has_date:
        return Classification("date", False, lcid)
    if has_time:
        return Classification("time", elapsed, lcid)
    if percent:
        return Classification("percent", False, lcid)
    if text and not digits:
        return Classification("text", False, lcid)
    if general and not digits:
        return Classification("general", False, lcid)
    return Classification("number", False, lcid)


def is_date_code(code: str | None, section: int | None = None) -> bool:
    """Whether ``code`` shows a number as a date, a time or both: its first section, or
    section ``section`` (:func:`classify`).  ``None``, an empty code, ``General``, ``@``
    and number codes are not."""
    if not isinstance(code, str) or not code:
        return False
    return classify(code, section).is_date


#: Format codes measured in Excel for Mac 16.106 (2026-10-25, region Dutch (Belgium), Dutch
#: interface): ``(code, kind, text)`` -- the code as a workbook's ``numFmt`` gave it, the
#: kind its first section shows, and the text Excel showed the serial 46027.5 (5 January
#: 2026, noon) as.  :func:`classify` answers each kind; the tests hold it to them, and
#: sibling libraries run the same table through their own readings.
MEASURED: tuple[tuple[str, str, str], ...] = (
    ('General', 'general', '46027,5'),
    ('0', 'number', '46028'),
    ('#,##0.00', 'number', '46.027,50'),
    ('0%', 'percent', '4602750%'),
    ('0.00E+00', 'number', '4,60E+04'),
    ('##0.0E+0', 'number', '46,0E+3'),
    ('# ?/?', 'number', '46027 1/2'),
    ('## ??/16', 'number', '46027  8/16'),
    ('@', 'text', '46027,5'),
    ('"Total: "0', 'number', 'Total: 46028'),
    ('0" days"', 'number', '46028 days'),
    ('0\\d', 'number', '46028d'),
    ('0_d', 'number', '46028 '),
    ('0*d', 'number', '46028ddddddd...'),
    ('0_);(0)', 'number', '46028 '),
    ('[Red]0.00;[Blue]-0.00', 'number', '46027,50'),
    ('[<100]0;0.00', 'number', '46027,50'),
    ('0;[Red]d', 'number', '46028'),
    ('0;0;d', 'number', '46028'),
    ('0;-0;;@', 'number', '46028'),
    (';;;', 'number', ''),
    ('[>=100]d;0', 'date', '5'),
    ('yyyy-mm-dd', 'date', '2026-01-05'),
    ('d-mmm-yy', 'date', '5-jan-26'),
    ('mmmm', 'date', 'januari'),
    ('m/d', 'date', '1/5'),
    ('h:mm', 'time', '12:00'),
    ('hh:mm:ss.000', 'time', '12:00:00,000'),
    ('mm:ss', 'time', '00:00'),
    ('ss.00', 'time', '00,00'),
    ('[h]:mm:ss', 'time', '1104660:00:00'),
    ('[mm]:ss', 'time', '66279600:00'),
    ('[ss]', 'time', '3976776000'),
    ('[h]', 'time', '1104660'),
    ('h AM/PM', 'time', '12 PM'),
    ('h:mm a/p', 'time', '12:00 p'),
    ('AM/PM', 'time', 'PM'),
    ('dd/mm/yyyy hh:mm', 'datetime', '05/01/2026 12:00'),
    ('d mmmm "at" h:mm', 'datetime', '5 januari at 12:00'),
    ('hh"h"mm', 'time', '12h00'),
    ('[$-409]mmmm d, yyyy', 'date', 'January 5, 2026'),
    ('[$-413]d mmmm yyyy', 'date', '5 januari 2026'),
    ('[$-10413]d mmmm yyyy', 'date', '5 januari 2026'),
    ('[$-F800]dddd, mmmm dd, yyyy', 'date', 'maandag 5 januari 2026'),
    ('[$-F400]h:mm:ss AM/PM', 'time', '12:00:00'),
    ('[$-x-sysdate]dddd, mmmm dd, yyyy', 'date', 'maandag 5 januari 2026'),
    ('[$-x-systime]h:mm:ss AM/PM', 'time', '12:00:00'),
    ('[$-th-TH]ว/ด/ปปปป', 'date', '5/1/2026'),
    ('ว/ด/ปปปป', 'date', '๕/๑/๒๕๖๙'),
    ('[$-41E]ว/ด/ปปปป', 'date', '5/1/2026'),
    ('ช:นน', 'time', '๑๒:๐๐'),
    ('[$-th-TH]d/m/bbbb', 'date', '5/1/2026'),
    ('d/m/bb', 'date', '5/1/69'),
    ('bbbb', 'date', '2569'),
    ('[$-411]ggge"年"m"月"d"日"', 'date', '令和8年1月5日'),
    ('[$-ja-JP]ggge', 'date', '令和8'),
    ('ggge', 'date', '2026'),
    ('e', 'date', '2026'),
    ('上午/下午h"时"mm"分"', 'time', '下午12时00分'),
    ('[$€-407] #,##0.00', 'number', '€ 46.027,50'),
    ('[$-409]#,##0.00', 'number', '46.027,50'),
    ('"yyyy"0', 'number', 'yyyy46028'),
    ('0.0%;[Red]-0.0%', 'percent', '4602750,0%'),
    ('[Color10]0', 'number', '46028'),
    ('#,##0 \\m', 'number', '46.028 m'),
    ('General;[Red]-General', 'general', '46027,5'),
    ('#,##0;[Red]-#,##0;"-"', 'number', '46.028'),
    ('"Dates"', 'number', 'Dates'),
    ('[DBNum1][$-804]General', 'general', '四万六千○二十七,五'),
    ('0.00E+00;d', 'number', '4,60E+04'),
    ('YYYY-MM-DD', 'date', '2026-01-05'),
    ('H:MM', 'time', '12:00'),
    ('[H]:MM', 'time', '1104660:00'),
    ('[MM]:SS', 'time', '66279600:00'),
    ('h "x" m', 'time', '12 x 0'),
    ('mm "x" ss', 'time', '00 x 00'),
    ('yyyy m', 'date', '2026 1'),
    ('m s', 'time', '0 0'),
    ('[h] m', 'time', '1104660 0'),
    ('[ช]:นน:ทท', 'time', '๑๑๐๔๖๖๐:๐๐:๐๐'),
    ('[$-th-TH]ช:นน', 'time', '12:00'),
    ('"x"@', 'text', '46027,5'),
    ('General "x"', 'general', '46027,5 x'),
    ('#,##0,,"M"', 'number', '0M'),
    ('[Blue][<0]0;0', 'number', '46028'),
    ('[$-x-sysdate]', 'date', 'maandag 5 januari 2026'),
    ('dd/mm/yyyy;@', 'date', '05/01/2026'),
    ('B2yyyy-mm-dd', 'date', '1447-07-17'),
    ('[$-2010000]yyyy/mm/dd', 'date', '٢٠٢٦/٠١/٠٥'),
    ('mmmmm', 'date', 'j'),
    ('ddddd', 'date', 'maandag'),
    ('yyy', 'date', '2026'),
    ('[hhh]:mm', 'time', '1104660:00'),
    ('[$-411]e', 'date', '8'),
    ('上午/下午', 'time', '下午'),
    ('a/p', 'time', 'p'),
    ('[$-F400]', 'time', '12:00:00'),
    ('[$-x-systime]', 'time', '12:00:00'),
    ('[$-F800]0.00', 'date', 'maandag 5 januari 2026'),
    ('0;[$-F800]', 'number', '46028'),
    ('[$-F800]General', 'date', 'maandag 5 januari 2026'),
    ('0;@', 'number', '46028'),
    ('0;0;0;@', 'number', '46028'),
    ('[$-F800]@', 'text', '46027,5'),
    ('AM/PM;0', 'time', 'PM'),
    ('0\\;0', 'number', '4602;8'),
    ('0_;0', 'number', '4602 8'),
    ('"a;b"0', 'number', 'a;b46028'),
)
