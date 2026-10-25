"""Dates kept as numbers: a serial in a date format code printed as Office shows it.

A chart (or a cell) keeps a date as its serial number in the 1900 date system -- 2026-01-05
is ``46027`` -- with a number format code that says how it is shown:
``[$-413]d\\ mmmm\\ yyyy`` is ``5 januari 2026``.  :func:`format_serial` prints one, for a
renderer to draw; :func:`is_date_code` (:func:`ooxml_common.numfmt.is_date_code`, the
same function) says whether a code is a date code at all.

**What is measured.**  PowerPoint and Word for Mac (2026-10-16) drew a column chart's date
categories -- serials in a ``c:numCache`` whose ``c:formatCode`` is the code -- as
``5 januari 2026`` (``[$-413]d\\ mmmm\\ yyyy``), ``5 Jan 2026`` and ``15 Mär 2026``
(``[$-407]d\\ mmm\\ yyyy``) and ``05/01/2026`` (``[$-409]dd/mm/yyyy``).  The month and day
names (:data:`NAMES`) are the ones Excel for Mac showed under ``[$-LCID]mmmm``, ``mmm``,
``dddd`` and ``ddd`` for each listed locale, the same day; ``mmmmm`` is the full name's
first letter.  Not taken from any other source.

**Which language names a date.**  The code's ``[$-LCID]`` prefix (or its ``[$-ll-CC]``
spelling) when its names are known: the prefix changes the names only, never the order or
the separators (measured in Excel, in every region tried).  A region shows its language's
names (:data:`LANGUAGES`; measured in Excel for Mac, 2026-10-17: ``[$-80C]`` and
``[$-fr-BE]`` French, ``[$-1809]`` and ``[$-en-BE]`` English, ``[$-9]`` English,
``[$-de-BE]`` German), so a prefix is read when :data:`LCIDS` lists its id or its tag's
language has names.  A code without a prefix -- or with one not read (an id not
measured: ``[$-411]``) -- is named in the caller's
:attr:`~ooxml_common.locales.Locale.language`, or that language's names for a region,
standing for the application's interface language: measured, Excel's unprefixed codes and
PowerPoint's date axis took their month names from the interface language (Dutch ``mrt``)
whatever the region.  A language with no measured names falls back to en-US's, as a date
field with no table does in pptx2svg; :func:`names_language` says which was used.

**An unprefixed code's own names** (:data:`INTERFACE_NAMES`).  Switching Office's interface
language (PowerPoint and Excel for Mac, 2026-10-17, region Dutch (Belgium)) showed that an
unprefixed code does not always take the names its language's prefix gives.  English,
German and Dutch interfaces named 5 January, 17 March, 20 May and 31 December 2026 as
``[$-409]``, ``[$-407]`` and ``[$-413]`` do; fr-FR and fr-BE, es-ES and es-MX each alike:

* French: ``mmm`` ``janv févr mars avr mai juin juil août sept oct nov déc`` -- fr-FR's
  without their dots (``[$-40C]`` and ``[$-80C]`` give ``janv.``, ``févr.``); ``ddd`` in a
  PowerPoint chart ``lun. mar. mer. jeu. ven. sam. dim.``, as ``[$-40C]`` (an Excel cell
  showed ``lun mar mer jeu ven sam dim``: the two differ, and a chart is what is drawn
  here); full names fr-FR's.
* Spanish: ``mmm`` ``ene feb mar abr may jun jul ago sept oct nov dic`` and ``ddd`` ``lun
  mar mié jue vie sáb dom`` -- neither es-ES's (``ene.``, ``lu.``) nor ``[$-A]``'s
  (``set``); full names es-ES's.
* Italian: ``mmm`` ``gen feb mar apr mag giu lug ago set ott nov dic`` and ``ddd`` ``lun
  mar mer gio ven sab dom``, full names it-IT's: it-IT's own names, listed as measured.

Every month (the 15th of each, 2026) and day (5 to 11 January 2026) was measured under
each of those interfaces, the same text in an Excel cell, its PDF and a PowerPoint chart
but for French ``ddd``; English (UK) and Dutch showed their prefixed sets.  A prefix
names as it always does, whatever the interface language (measured the same day).

**A known limit: ``m/d/yy``.**  A chart keeps a date in the workbook's built-in short
date (id 14) -- or in a custom ``m/d/yy`` -- as the code text ``m/d/yy``, and this prints
it as written (``1/5/26``).  Office shows the viewer's short date there, never in that
order: measured in PowerPoint for Mac's charts (cache or axis code, linked or not) and
Excel's id 14 cells, 2026-10-17, region Dutch (Belgium), 5 January 2026 read
``5/01/2026`` under a Dutch, Spanish or Italian interface, ``5/01/26`` under a French one,
``05/01/2026`` under English (UK); and under a Dutch interface Excel's id 14 followed the
region (2026-10-16: ``2/03/2026`` Dutch (Belgium), ``02-03-2026`` Dutch (Netherlands),
``02.03.26`` German, ``3/2/26`` English (United States)).  The pattern depends on the
interface language and the region together, and their combinations are not measured, so
no pattern is substituted.

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

from . import numfmt
from .locales import EN_US, Locale, canonical_language
from .numfmt import is_date_code

__all__ = ["INTERFACE_NAMES", "LANGUAGES", "LCIDS", "NAMES", "DateNames", "date_of_serial", "format_serial",
           "date_names", "is_date_code", "language_of_code", "names_language", "names_tag"]


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
# mmm, dddd and ddd.  ooxml-edit reads this table (``ooxml_edit.dates.NAMES`` re-exports it,
# from ooxml-edit 0.64.0); this package never imports ooxml-edit.
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
# Measured in PowerPoint and Word for Mac, 2026-10-17, under [$-80A] and [$-A] (what Office
# stores for [$-es-MX] and [$-es]): the months and days of es-ES, other abbreviations.
_SPANISH_MEXICO = _SPANISH._replace(
    short_days=tuple("lun. mar. mié. jue. vie. sáb. dom.".split()))
_SPANISH_ANY = _SPANISH._replace(
    short_months=tuple("ene feb mar abr may jun jul ago set oct nov dic".split()),
    short_days=tuple("lun mar mié jue vie sáb dom".split()))
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
    "es-MX": _SPANISH_MEXICO, "es": _SPANISH_ANY,
})

#: The tag in :data:`NAMES` whose names every region of a language shows, by language
#: subtag.  Measured in Excel for Mac, 2026-10-17: en-BE and en-IE named a date as en-US,
#: fr-BE and fr-CH as fr-FR, de-BE and de-CH as de-DE (and nl-BE as nl-NL, 2026-10-16);
#: it-CH ([$-810]) and it ([$-10]) as it-IT, 2026-10-17.  Not Spanish: es-MX and es
#: abbreviate otherwise than es-ES (:data:`NAMES` has each), so another Spanish region is
#: not guessed.  Re-exported as ooxml-edit's ``ooxml_edit.dates.LANGUAGES``.
LANGUAGES: Mapping[str, str] = MappingProxyType({
    "en": "en-US", "nl": "nl-NL", "de": "de-DE", "fr": "fr-FR", "it": "it-IT",
})

#: The locale id of a code's ``[$-LCID]`` prefix, per language tag: each accepted and
#: honoured (names in that language) by Excel for Mac, 2026-10-16; the regional and
#: language-only ones are what Excel for Mac stored for a ``[$-fr-BE]``, ``[$-en]`` ...
#: prefix, 2026-10-17, each showing its language's names.
LCIDS: Mapping[str, int] = MappingProxyType({
    "en-US": 0x409, "en-GB": 0x809, "nl-NL": 0x413, "nl-BE": 0x813,
    "de-DE": 0x407, "fr-FR": 0x40C, "es-ES": 0xC0A, "it-IT": 0x410,
    "en-IE": 0x1809, "fr-BE": 0x80C, "fr-CH": 0x100C,
    "en": 0x9, "nl": 0x13, "de": 0x7, "fr": 0xC,
    # What Office stored for [$-es-MX], [$-it-CH] on re-saving, 2026-10-17; [$-A] and
    # [$-10] honoured (es's and it-IT's names).
    "es-MX": 0x80A, "it-CH": 0x810, "es": 0xA, "it": 0x10,
})
_LANGUAGE_OF_LCID = {lcid: tag for tag, lcid in LCIDS.items()}

# Measured in PowerPoint (charts) and Excel for Mac, 2026-10-17, under each interface
# language, every month and day (module notes).
_FRENCH_INTERFACE = _FRENCH._replace(
    short_months=tuple("janv févr mars avr mai juin juil août sept oct nov déc".split()),
    short_days=tuple("lun. mar. mer. jeu. ven. sam. dim.".split()))   # PowerPoint's
_SPANISH_INTERFACE = _SPANISH._replace(
    short_months=tuple("ene feb mar abr may jun jul ago sept oct nov dic".split()),
    short_days=tuple("lun mar mié jue vie sáb dom".split()))
_ITALIAN_INTERFACE = _names(
    "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre "
    "dicembre",
    "gen feb mar apr mag giu lug ago set ott nov dic",
    "lunedì martedì mercoledì giovedì venerdì sabato domenica",
    "lun mar mer gio ven sab dom")

#: The names an unprefixed code shows under an interface language, by language subtag,
#: where they are not :data:`NAMES`' for that language (see the module's notes):
#: measured in PowerPoint and Excel for Mac, 2026-10-17, fr-FR = fr-BE and es-ES = es-MX.
#: English, German and Dutch interfaces showed their prefixed names and are not listed;
#: Italian's are it-IT's, listed as measured.
INTERFACE_NAMES: Mapping[str, DateNames] = MappingProxyType({
    "fr": _FRENCH_INTERFACE, "es": _SPANISH_INTERFACE, "it": _ITALIAN_INTERFACE,
})


def names_tag(language: str) -> str | None:
    """The tag in :data:`NAMES` whose names ``language`` (a tag in canonical case) shows:
    itself when listed, else its language's (:data:`LANGUAGES`: fr-BE shows fr-FR's);
    ``None`` for a language with no measured names."""
    return language if language in NAMES else LANGUAGES.get(language.split("-", 1)[0])

#: The 1900 date system's day 0, for every serial from 61 (1 March 1900) on, and the
#: day before its serial 1 (1 January 1900) below 60: the system counts a 29 February 1900
#: as day 60 (ECMA-376 Part 1, 18.17.4.1).  The 1904 system counts from 1 January 1904.
_EPOCH_1900 = _dt.date(1899, 12, 30)
_EPOCH_1900_EARLY = _dt.date(1899, 12, 31)
_EPOCH_1904 = _dt.date(1904, 1, 1)
_LAST = _dt.date(9999, 12, 31)

def _tokens(section: str) -> list[tuple[str, str]]:
    """A date section as ``(kind, text)``, read from :func:`ooxml_common.numfmt.tokens`:
    ``token`` (``d``, ``mmmm`` ..., lower case), ``literal`` (a quoted text, an escaped
    character, ``_``'s blank as a space, any other character), ``locale`` (a bracket's
    language part: ``413`` or ``nl-NL``), ``time`` and ``other`` (a letter or placeholder
    that is no date token, or a bracket this does not read).  A colour and ``*``'s fill
    are left out."""
    out: list[tuple[str, str]] = []
    for token in numfmt.tokens(section):
        kind, text = token.kind, token.text
        if kind in ("quoted", "escaped", "literal"):
            out.append(("literal", text))
        elif kind == "pad":
            # Padding the width of the next character: a space is the nearest thing.
            out.append(("literal", " "))
        elif kind == "locale":
            symbol, _, language = text.partition("-")
            if symbol:
                out.append(("literal", symbol))
            if language:
                out.append(("locale", language))
        elif kind in ("date", "time"):
            letter = text[0].lower()
            if letter in "dmy":
                out.append(("token", text.lower()))
            else:
                out.append(("time" if letter in "hs" else "other", text))
        elif kind in ("elapsed", "ampm"):
            out.append(("time", text))
        elif kind == "condition" or (kind == "bracket" and not (
                text.isalpha() or text.lower().startswith("color"))):
            out.append(("other", text))
        elif kind not in ("fill", "color", "bracket"):
            out.append(("other", text))
    return out


#: The runs of letters printed, by kind: day, month, year.
_PRINTED = frozenset({"d", "dd", "ddd", "dddd", "m", "mm", "mmm", "mmmm", "mmmmm", "yy", "yyyy"})


def language_of_code(format_code: str | None) -> str | None:
    """The language tag a code's ``[$-LCID]`` (or ``[$-ll-CC]``) prefix names, when its
    names are known: an id :data:`LCIDS` lists (``[$-80C]`` is fr-BE), a tag whose
    language has names (``[$-en-BE]``); ``None`` without a prefix or for one not read.  An
    LCID's upper bits (a calendar, ``[$-10413]``) are ignored."""
    for section in numfmt.sections(format_code or ""):
        for kind, text in _tokens(section):
            if kind != "locale":
                continue
            try:
                stated = _LANGUAGE_OF_LCID.get(int(text, 16) & 0xFFFF)
            except ValueError:
                stated = None
            if stated is not None:
                return stated
            # A tag; or an id not listed, which reads as no tag either ([$-411]) -- ``de``
            # is both, and the tag wins.
            try:
                tag = canonical_language(text)
            except ValueError:
                return None
            return tag if tag in LCIDS or names_tag(tag) is not None else None
    return None


def names_language(format_code: str | None, locale: Locale = EN_US) -> str:
    """The language a code's month and day names are printed in, a tag in :data:`NAMES`:
    its prefix's (:func:`language_of_code`), else ``locale``'s when it has measured names
    -- a region's being its language's (:func:`names_tag`) -- else en-US (see the
    module's notes).  Without a prefix read the names may be that language's interface
    set (:data:`INTERFACE_NAMES`); :func:`date_names` gives the names themselves."""
    stated = language_of_code(format_code)
    shown = names_tag(stated) if stated is not None else None
    if shown is not None:
        return shown
    return names_tag(locale.language) or EN_US.language


def date_names(format_code: str | None, locale: Locale = EN_US) -> DateNames:
    """The month and day names :func:`format_serial` prints ``format_code`` with: its
    prefix's :data:`NAMES`; without a prefix read, the interface language's -- ``locale``
    standing for it -- from :data:`INTERFACE_NAMES` where listed, else :data:`NAMES`
    (:func:`names_language`)."""
    stated = language_of_code(format_code)
    if stated is None or names_tag(stated) is None:
        interface = INTERFACE_NAMES.get(locale.primary_language)
        if interface is not None:
            return interface
    return NAMES[names_language(format_code, locale)]


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
    tokens with the names of :func:`date_names`, every other character as the code
    writes it (a quoted text, an escaped character, ``/``, ``-``, ``.``, a space).
    ``None`` where this does not print it -- a code that is no date, has a time in it, or
    a token not read, and a serial that names no day (see the module's notes) -- for the
    caller to print the number as before."""
    day = date_of_serial(value, date1904=date1904)
    if day is None or not format_code:
        return None
    sections = numfmt.sections(format_code)
    # Positive; negative; zero; text.  A day is never negative here, and only 1904's
    # serial 0 is zero.
    index = 2 if value == 0 and len(sections) > 2 else 0
    if not is_date_code(format_code, index):
        return None
    tokens = _tokens(sections[index])
    if not tokens or any(kind in ("time", "other") for kind, _ in tokens):
        return None
    if any(kind == "token" and text not in _PRINTED for kind, text in tokens):
        return None
    if not any(kind == "token" for kind, _ in tokens):
        return None
    names = date_names(format_code, locale)
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
