"""The regional settings a document is drawn and edited in: :class:`Locale`.

Office takes some of what it shows from the machine it runs on rather than from the file:
the decimal and thousands separators of a chart's number format (a comma for the decimal
on a Dutch Mac), the order of day and month in a date, the list separator, the language
of the words it writes itself.  A document does not state them.  A renderer or an editor
that read them from *its* machine would draw the same file differently on every server,
so nothing here does: the caller says which locale a conversion or an edit session is in,
per user or per client, and without one it is :data:`EN_US`, always.

**What is and is not measured.**  :data:`EN_US` is the default because a fixed default is
needed, not because its values were measured here.  Its date order (``mdy``) agrees with
the en-US date field formats pptx2svg measured on PowerPoint (``M/d/yy``); its separators
(``.`` and ``,``) are what :func:`ooxml_common.chart.layout.format_number` has always
written, so a caller that passes no locale gets the output it got before.  Other locales
are the caller's to build -- ``Locale(decimal_separator=",", thousands_separator=".",
date_order="dmy", language="nl-NL", list_separator=";")`` -- since what Office does in
each one is measured from Office, one locale at a time, and not copied from a table.
:data:`KNOWN_LOCALES` and :func:`locale_for` are the place measured locales go.

Standard library only; this module never reads the operating system's locale.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

__all__ = ["DATE_ORDERS", "EN_US", "KNOWN_LOCALES", "Locale", "canonical_language", "locale_for"]

#: The orders of day, month and year :attr:`Locale.date_order` takes.
DATE_ORDERS = ("dmy", "mdy", "ymd")

# A BCP 47 language tag without extensions or private use: a language (2 or 3 letters),
# then an optional script (4 letters), region (2 letters or 3 digits) and variants.
_TAG = re.compile(
    r"(?P<language>[A-Za-z]{2,3})"
    r"(?:-(?P<script>[A-Za-z]{4}))?"
    r"(?:-(?P<region>[A-Za-z]{2}|[0-9]{3}))?"
    r"(?P<variants>(?:-(?:[A-Za-z0-9]{5,8}|[0-9][A-Za-z0-9]{3}))*)"
)


def canonical_language(tag: str) -> str:
    """``tag`` in BCP 47's conventional case -- ``en-US``, ``zh-Hant-TW``, ``es-419`` --
    with ``_`` read as ``-`` (``nl_be`` is ``nl-BE``).  Raises :class:`ValueError` for
    anything that is not a language, an optional script, region and variants."""
    if not isinstance(tag, str):
        raise ValueError(f"language is a BCP 47 tag such as 'en-US', not {tag!r}")
    match = _TAG.fullmatch(tag.replace("_", "-"))
    if match is None:
        raise ValueError(f"language is a BCP 47 tag such as 'en-US', not {tag!r}")
    parts = [match["language"].lower()]
    if match["script"]:
        parts.append(match["script"].title())
    if match["region"]:
        parts.append(match["region"].upper())
    parts.extend(variant.lower() for variant in match["variants"].split("-") if variant)
    return "-".join(parts)


def _separator(name: str, value: object) -> str:
    if not isinstance(value, str) or len(value) != 1 or value.isalnum():
        raise ValueError(f"{name} is one character, not a letter or digit: {value!r}")
    return value


@dataclass(frozen=True)
class Locale:
    """The regional settings Office takes from its machine, as a value: frozen, hashable,
    validated on construction, and safe to pickle into a worker process.

    * ``decimal_separator`` -- the character between a number's whole part and its
      decimals (``.``; ``,`` in much of Europe).  Not whitespace.
    * ``thousands_separator`` -- the character that groups a number's whole part in
      threes where its format asks for grouping (``,``; ``.``, a space or a no-break space
      elsewhere).  Not the decimal separator.
    * ``date_order`` -- the order of day, month and year in a numeric date: one of
      :data:`DATE_ORDERS`.
    * ``language`` -- a BCP 47 tag (``en-US``), kept in its conventional case: the
      language of the words the application writes itself and of the date names.
    * ``list_separator`` -- the character that separates the items of a list, a formula's
      arguments among them (``,``; ``;`` where the decimal separator is a comma).  Not
      the decimal separator.

    Build a variant with :func:`dataclasses.replace`.
    """

    decimal_separator: str = "."
    thousands_separator: str = ","
    date_order: str = "mdy"
    language: str = "en-US"
    list_separator: str = ","

    def __post_init__(self) -> None:
        decimal = _separator("decimal_separator", self.decimal_separator)
        if decimal.isspace():
            raise ValueError(f"decimal_separator is not whitespace: {decimal!r}")
        if _separator("thousands_separator", self.thousands_separator) == decimal:
            raise ValueError("thousands_separator is not the decimal_separator")
        if _separator("list_separator", self.list_separator) == decimal:
            raise ValueError("list_separator is not the decimal_separator")
        if self.date_order not in DATE_ORDERS:
            raise ValueError(f"date_order is one of {DATE_ORDERS}, not {self.date_order!r}")
        object.__setattr__(self, "language", canonical_language(self.language))

    @property
    def primary_language(self) -> str:
        """The language subtag alone: ``en`` of ``en-US``."""
        return self.language.split("-", 1)[0]

    def number_text(self, text: str) -> str:
        """A number written with ``.`` for the decimal and ``,`` for the thousands -- as
        Python's own formatting writes it -- rewritten with this locale's separators:
        ``1,234.5`` is ``1.234,5`` with a decimal comma.  Only the number: text round it
        (a currency symbol, a quoted word) is not the caller's to pass through here."""
        if self.decimal_separator == "." and self.thousands_separator == ",":
            return text
        return text.translate({ord("."): self.decimal_separator, ord(","): self.thousands_separator})


#: The default locale of every conversion and edit that is not given one: English
#: (United States).  The default, not a measurement -- see the module's notes.
EN_US = Locale()

#: The locales known by their language tag, for :func:`locale_for`.  Only the default:
#: what Office does in any other locale is measured before it is listed here.
KNOWN_LOCALES: Mapping[str, Locale] = MappingProxyType({EN_US.language: EN_US})


def locale_for(language: str, known: Mapping[str, Locale] | None = None) -> Locale:
    """The locale listed for a language tag, compared in canonical case (``en-us`` is
    ``en-US``): in ``known`` when given -- an application's own table, keyed by tag --
    else in :data:`KNOWN_LOCALES`.  Raises :class:`LookupError` for a tag with no locale,
    rather than guessing one from another region or from the machine."""
    wanted = canonical_language(language)
    table = KNOWN_LOCALES if known is None else known
    for tag, locale in table.items():
        if canonical_language(tag) == wanted:
            return locale
    raise LookupError(
        f"no locale is listed for {wanted!r}; build one with "
        "ooxml_common.locales.Locale(decimal_separator=..., thousands_separator=..., "
        "date_order=..., language=..., list_separator=...)"
    )
