"""Dates kept as numbers: a serial in a date format code printed as Office shows it.

A chart (or a cell) keeps a date as its serial number in the 1900 date system -- 2026-01-05
is ``46027`` -- with a number format code that says how it is shown:
``[$-413]d\\ mmmm\\ yyyy`` is ``5 januari 2026``.  :func:`format_serial` prints one, for a
renderer to draw; :func:`is_date_code` says whether a code is a date code at all.

**What is measured.**  PowerPoint and Word for Mac (2026-10-16) drew a column chart's date
categories -- serials in a ``c:numCache`` whose ``c:formatCode`` is the code -- as
``5 januari 2026`` (``[$-413]d\\ mmmm\\ yyyy``), ``5 Jan 2026`` and ``15 Mär 2026``
(``[$-407]d\\ mmm\\ yyyy``) and ``05/01/2026`` (``[$-409]dd/mm/yyyy``).  The month and day
names (:data:`NAMES`) are the ones Excel for Mac showed under ``[$-LCID]mmmm``, ``mmm``,
``dddd`` and ``ddd`` for each listed locale, the same day; ``mmmmm`` is the full name's
first letter.  Not taken from any other source.

**Which language names a date.**  The code's ``[$-LCID]`` prefix (or its ``[$-ll-CC]``
spelling) when :data:`LCIDS` lists it: the prefix changes the names only, never the
order or the separators (measured in Excel, in every region tried).  A code without a
prefix -- or with one this does not list -- is named in the caller's
:attr:`~ooxml_common.locales.Locale.language`, standing for the application's interface
language: measured, Excel's unprefixed codes and PowerPoint's date axis took their month
names from the interface language (Dutch ``mrt``) whatever the region.  A language with no
measured names falls back to en-US's, as a date field with no table does in pptx2svg;
:func:`names_language` says which was used.

**Separators are written as the code has them.**  Office shows a ``/`` in a stored code as
the *viewer's* date separator (measured, switching the macOS region: ``dd/mm/yyyy`` read
``02-03-2026`` in a Dutch (Netherlands) region, ``02.03.2026`` in a German one and
``02/03/2026`` in English (UK), French, Spanish, Italian and Dutch (Belgium) ones; a ``-``
stays ``-`` everywhere).  :class:`~ooxml_common.locales.Locale` has no date separator --
its numbers take its separators, and a renderer's date fields take their language's own
patterns -- so a ``/`` is printed as ``/``: what an English (United States) viewer, the
default locale's, sees, and the region the measurements above drew ``05/01/2026`` in.

**What is not formatted** (:func:`format_serial` returns ``None``, and the caller keeps
the number as it printed it before): a code with a time in it (``h``, ``s``, ``AM/PM``,
``[h]``) or a letter that is no date token, a negative serial, ``0`` and ``60`` (the
1900 system's day before 1 January and its 29 February 1900, which never was), a serial
past 31 December 9999.  A run of letters Office reads but this does not (``ddddd``,
``mmmmmm``, ``y``, ``yyy``) is not guessed at either.

Standard library only; nothing here reads the operating system's locale.
"""

from __future__ import annotations

import datetime as _dt
import math
from types import MappingProxyType
from typing import Mapping, NamedTuple

from .locales import EN_US, Locale, canonical_language

__all__ = ["LCIDS", "NAMES", "DateNames", "date_of_serial", "format_serial", "is_date_code",
           "language_of_code", "names_language"]


class DateNames(NamedTuple):
    """A locale's month names and abbreviations (January first) and day names and
    abbreviations (Monday first, as Python's ``date.weekday()`` counts)."""

    months: tuple[str, ...]
    short_months: tuple[str, ...]
    days: tuple[str, ...]
    short_days: tuple[str, ...]


def _names(months: str, short_months: str, days: str, short_days: str) -> DateNames:
    return DateNames(tuple(months.split()), tuple(short_months.split()), tuple(days.split()),
                     tuple(short_days.split()))


# Measured on Excel for Mac, 2026-10-16: each name as Excel showed it under [$-LCID]mmmm,
# mmm, dddd and ddd.  The same table as ooxml-edit's ``ooxml_edit.dates.NAMES``, which this
# package may not import; ``tests/test_dates.py`` checks the two agree where both are
# installed.
_ENGLISH = _names(
    "January February March April May June July August September October November December",
    "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec",
    "Monday Tuesday Wednesday Thursday Friday Saturday Sunday",
    "Mon Tue Wed Thu Fri Sat Sun")
_DUTCH = _names(
    "januari februari maart april mei juni juli augustus september oktober november december",
    "jan feb mrt apr mei jun jul aug sep okt nov dec",
    "maandag dinsdag woensdag donderdag vrijdag zaterdag zondag",
    "ma di wo do vr za zo")
_GERMAN = _names(
    "Januar Februar März April Mai Juni Juli August September Oktober November Dezember",
    "Jan Feb Mär Apr Mai Jun Jul Aug Sep Okt Nov Dez",
    "Montag Dienstag Mittwoch Donnerstag Freitag Samstag Sonntag",
    "Mo Di Mi Do Fr Sa So")
_FRENCH = _names(
    "janvier février mars avril mai juin juillet août septembre octobre novembre décembre",
    "janv. févr. mars avr. mai juin juil. août sept. oct. nov. déc.",
    "lundi mardi mercredi jeudi vendredi samedi dimanche",
    "lun. mar. mer. jeu. ven. sam. dim.")
_SPANISH = _names(
    "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre",
    "ene. feb. mar. abr. may. jun. jul. ago. sep. oct. nov. dic.",
    "lunes martes miércoles jueves viernes sábado domingo",
    "lu. ma. mi. ju. vi. sá. do.")
_ITALIAN = _names(
    "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre "
    "dicembre",
    "gen feb mar apr mag giu lug ago set ott nov dic",
    "lunedì martedì mercoledì giovedì venerdì sabato domenica",
    "lun mar mer gio ven sab dom")

#: Month and day names per language tag, measured on Excel for Mac, 2026-10-16.
NAMES: Mapping[str, DateNames] = MappingProxyType({
    "en-US": _ENGLISH, "en-GB": _ENGLISH, "nl-NL": _DUTCH, "nl-BE": _DUTCH,
    "de-DE": _GERMAN, "fr-FR": _FRENCH, "es-ES": _SPANISH, "it-IT": _ITALIAN,
})

#: The locale id of a code's ``[$-LCID]`` prefix, per language tag: each accepted and
#: honoured (names in that language) by Excel for Mac, 2026-10-16.
LCIDS: Mapping[str, int] = MappingProxyType({
    "en-US": 0x409, "en-GB": 0x809, "nl-NL": 0x413, "nl-BE": 0x813,
    "de-DE": 0x407, "fr-FR": 0x40C, "es-ES": 0xC0A, "it-IT": 0x410,
})
_LANGUAGE_OF_LCID = {lcid: tag for tag, lcid in LCIDS.items()}

#: The 1900 date system's day 0, for every serial from 61 (1 March 1900) on, and the
#: day before its serial 1 (1 January 1900) below 60: the system counts a 29 February 1900
#: as day 60 (ECMA-376 Part 1, 18.17.4.1).  The 1904 system counts from 1 January 1904.
_EPOCH_1900 = _dt.date(1899, 12, 30)
_EPOCH_1900_EARLY = _dt.date(1899, 12, 31)
_EPOCH_1904 = _dt.date(1904, 1, 1)
_LAST = _dt.date(9999, 12, 31)

#: Letters that make a code a time, which :func:`format_serial` does not print.
_TIME_LETTERS = frozenset("hs")


def _sections(code: str) -> list[str]:
    """``code`` cut at its unquoted, unescaped ``;``."""
    out, start, index, quoted = [], 0, 0, False
    while index < len(code):
        char = code[index]
        if char == '"':
            quoted = not quoted
        elif char == "\\" and not quoted:
            index += 1
        elif char == ";" and not quoted:
            out.append(code[start:index])
            start = index + 1
        index += 1
    out.append(code[start:])
    return out


def _tokens(section: str) -> list[tuple[str, str]]:
    """A date section as ``(kind, text)``: ``token`` (``d``, ``mmmm`` ..., lower case),
    ``literal``, ``locale`` (a bracket's language part: ``413`` or ``nl-NL``), ``time``
    and ``other`` (a letter that is no date token, or a bracket this does not read)."""
    out: list[tuple[str, str]] = []
    index, length = 0, len(section)
    while index < length:
        char = section[index]
        lower = char.lower()
        if char == '"':
            close = section.find('"', index + 1)
            close = length if close < 0 else close
            out.append(("literal", section[index + 1:close]))
            index = close + 1
        elif char == "\\":
            out.append(("literal", section[index + 1:index + 2]))
            index += 2
        elif char == "_":
            # Padding the width of the next character: a space is the nearest thing.
            out.append(("literal", " "))
            index += 2
        elif char == "*":
            index += 2
        elif char == "[":
            close = section.find("]", index)
            close = length if close < 0 else close
            inner = section[index + 1:close]
            if inner.startswith("$"):
                symbol, _, language = inner[1:].partition("-")
                if symbol:
                    out.append(("literal", symbol))
                if language:
                    out.append(("locale", language))
            elif inner and inner.lower() == inner[0].lower() * len(inner) and inner[0].lower() in "hms":
                # Elapsed time: [h], [mm], [ss].
                out.append(("time", inner))
            elif not (inner.isalpha() or inner.lower().startswith("color")):
                # A condition ([<100]) or a bracket this does not know.
                out.append(("other", inner))
            # Else a colour ([Red], [Color10]): the text's own colour, not its words.
            index = close + 1
        elif section[index:index + 5].upper() == "AM/PM" or section[index:index + 3].upper() == "A/P":
            out.append(("time", section[index:index + 5]))
            index += 5 if section[index:index + 5].upper() == "AM/PM" else 3
        elif lower in "dmy":
            end = index
            while end < length and section[end].lower() == lower:
                end += 1
            out.append(("token", section[index:end].lower()))
            index = end
        elif lower in _TIME_LETTERS:
            out.append(("time", char))
            index += 1
        elif char.isalpha() or char in "@0#?%":
            out.append(("other", char))
            index += 1
        else:
            out.append(("literal", char))
            index += 1
    return out


#: The runs of letters printed, by kind: day, month, year.
_PRINTED = frozenset({"d", "dd", "ddd", "dddd", "m", "mm", "mmm", "mmmm", "mmmmm", "yy", "yyyy"})


def is_date_code(format_code: str | None) -> bool:
    """Whether ``format_code`` shows a number as a date or a time: a day, month, year,
    hour or second token outside quotes in any section.  ``General``, ``@`` and number
    codes are not."""
    if not format_code or format_code in ("General", "@"):
        return False
    return any(kind in ("token", "time") for section in _sections(format_code)
               for kind, _ in _tokens(section))


def language_of_code(format_code: str | None) -> str | None:
    """The language tag a code's ``[$-LCID]`` (or ``[$-ll-CC]``) prefix names, when
    :data:`LCIDS` lists it; ``None`` without a prefix or for one not listed.  An LCID's
    upper bits (a calendar, ``[$-10413]``) are ignored."""
    for section in _sections(format_code or ""):
        for kind, text in _tokens(section):
            if kind != "locale":
                continue
            try:
                return _LANGUAGE_OF_LCID.get(int(text, 16) & 0xFFFF)
            except ValueError:
                pass
            try:
                tag = canonical_language(text)
            except ValueError:
                return None
            return tag if tag in LCIDS else None
    return None


def names_language(format_code: str | None, locale: Locale = EN_US) -> str:
    """The language whose :data:`NAMES` a code's month and day names are printed in: its
    prefix's (:func:`language_of_code`), else ``locale``'s when it has measured names,
    else en-US (see the module's notes)."""
    stated = language_of_code(format_code)
    if stated is not None:
        return stated
    return locale.language if locale.language in NAMES else EN_US.language


def date_of_serial(value: float, *, date1904: bool = False) -> _dt.date | None:
    """The day a serial names, its time of day dropped: in the 1900 date system unless
    ``date1904`` (``c:date1904``, the 1904 system).  ``None`` for a serial that names no
    day: negative, not finite, the 1900 system's 0 and 60, past 9999-12-31."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    if value < 0:
        return None
    whole = math.floor(value)
    if date1904:
        epoch = _EPOCH_1904
    elif whole >= 61:
        epoch = _EPOCH_1900
    elif 1 <= whole <= 59:
        epoch = _EPOCH_1900_EARLY
    else:
        return None
    if whole > (_LAST - epoch).days:
        return None
    return epoch + _dt.timedelta(days=whole)


def format_serial(value: float, format_code: str | None, locale: Locale = EN_US, *,
                  date1904: bool = False) -> str | None:
    """``value``, a date's serial, as ``format_code`` shows it: day, month and year
    tokens with the names of :func:`names_language`, every other character as the code
    writes it (a quoted text, an escaped character, ``/``, ``-``, ``.``, a space).
    ``None`` where this does not print it -- a code that is no date, has a time in it, or
    a token not read, and a serial that names no day (see the module's notes) -- for the
    caller to print the number as before."""
    if not is_date_code(format_code):
        return None
    day = date_of_serial(value, date1904=date1904)
    if day is None:
        return None
    sections = _sections(format_code)
    # Positive; negative; zero; text.  A day is never negative here, and only 1904's
    # serial 0 is zero.
    section = sections[2] if value == 0 and len(sections) > 2 else sections[0]
    tokens = _tokens(section)
    if not tokens or any(kind in ("time", "other") for kind, _ in tokens):
        return None
    if any(kind == "token" and text not in _PRINTED for kind, text in tokens):
        return None
    if not any(kind == "token" for kind, _ in tokens):
        return None
    names = NAMES[names_language(format_code, locale)]
    out: list[str] = []
    for kind, text in tokens:
        if kind == "literal":
            out.append(text)
        elif kind != "token":
            continue
        elif text == "d":
            out.append(str(day.day))
        elif text == "dd":
            out.append(f"{day.day:02d}")
        elif text == "ddd":
            out.append(names.short_days[day.weekday()])
        elif text == "dddd":
            out.append(names.days[day.weekday()])
        elif text == "m":
            out.append(str(day.month))
        elif text == "mm":
            out.append(f"{day.month:02d}")
        elif text == "mmm":
            out.append(names.short_months[day.month - 1])
        elif text == "mmmm":
            out.append(names.months[day.month - 1])
        elif text == "mmmmm":
            out.append(names.months[day.month - 1][0])
        elif text == "yy":
            out.append(f"{day.year % 100:02d}")
        else:
            out.append(f"{day.year:04d}")
    return "".join(out)
