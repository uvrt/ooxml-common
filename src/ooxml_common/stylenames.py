"""Word's built-in style names in the languages Word speaks, and a field's style name found
by them: :func:`find_style`, :func:`list_separator`.

A field that names a style -- a table of contents' ``\\t "Kop 2;1"``, ``STYLEREF "Titel"``
-- names it as the Word that wrote it shows it.  ``styles.xml`` stores a built-in style
under its English name (``heading 2``), whatever the language, and Word matches the
field's name against its interface's display names: measured (round 21), Dutch Word lists
a ``\\t "Kop 2;1"`` heading and not a ``\\t "Heading 2;1"`` one, English Word the reverse.
So a Dutch, French or German document's fields name built-in styles in that language.

**What is measured** (:data:`NAMES`, ``stylenames.json``).  For each language listed,
Word 16.106 for Mac was started with that interface language and region
(``-AppleLanguages (fr) -AppleLocale fr_FR``) and asked, through AppleScript, for the
``name local`` of every built-in style of a new document; each style was given a font size
of its own and the document saved, so the size in the saved ``styles.xml`` says which
stored (``w:name``) name each display name belongs to.  List styles (no run properties)
are not in the table: no field names one.  The list separator Word splits a ``\\t`` list
on is its region's (:data:`LIST_SEPARATORS`), measured by Word's ``list separator`` and by
a ``\\t`` field updated in that Word.  ``tools/word_style_names.py`` measures a language;
nothing here was taken from any other source.

**How a name is found** (:func:`find_style`).  A Word in another language than the
document's cannot be known from the file, so a name is accepted in the document's
language and in English: first a style's stored name or one of its aliases, then the
built-in style the document language displays under that name, then the one English Word
displays under it -- without regard to case, and trimmed where the field's Word trims.

Standard library only.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from types import MappingProxyType
from typing import Mapping, TypeVar

__all__ = ["LIST_SEPARATORS", "NAMES", "builtin_names", "find_style", "list_separator", "measured_language"]

K = TypeVar("K")


@lru_cache(maxsize=1)
def _data() -> dict:
    text = resources.files("ooxml_common").joinpath("stylenames.json").read_text(encoding="utf-8")
    return json.loads(text)


def _languages() -> dict:
    return _data()["languages"]


#: Per measured language (``en``, ``nl``, ``fr``...): each built-in style's stored name
#: (``styles.xml``'s ``w:name``, ``heading 2``) -> the name Word in that language shows
#: (``Kop 2``).
NAMES: Mapping[str, Mapping[str, str]] = MappingProxyType(
    {language: MappingProxyType(dict(entry["names"])) for language, entry in _languages().items()})

#: Per measured language: the list separator of the region it was measured in (``nl``:
#: ``;``, ``en``: ``,``), which a ``\\t`` list is split on.
LIST_SEPARATORS: Mapping[str, str] = MappingProxyType(
    {language: entry["list_separator"] for language, entry in _languages().items()})


def measured_language(language: str | None) -> str | None:
    """The measured language a BCP 47 tag (``nl-BE``, ``fr_FR``, ``de``) falls under -- its
    primary subtag, lower case -- or ``None`` when that language was not measured."""
    if not language:
        return None
    primary = language.replace("_", "-").split("-", 1)[0].lower()
    return primary if primary in NAMES else None


def builtin_names(language: str | None) -> Mapping[str, str]:
    """Stored name -> display name of every built-in style in ``language`` (a tag;
    ``nl-NL`` is ``nl``); empty for a language not measured."""
    found = measured_language(language)
    return NAMES[found] if found else MappingProxyType({})


def list_separator(language: str | None, default: str = ",") -> str:
    """The list separator Word splits a field's list on in ``language``'s region, as
    measured; ``default`` for a language not measured."""
    found = measured_language(language)
    return LIST_SEPARATORS[found] if found else default


@lru_cache(maxsize=32)
def _reverse(language: str) -> dict[str, str]:
    """Display name (folded) -> stored name (folded), for a measured language."""
    return {display.strip().casefold(): stored.casefold() for stored, display in NAMES[language].items()}


def find_style(name: str, styles: Mapping[str, K], language: str | None = None, *, trim: bool = True) -> K | None:
    """The style a field names: ``name`` as the field gives it, ``styles`` each style's
    stored name -- and each of its aliases -- mapped to what the caller wants back (its id),
    ``language`` the document's (a BCP 47 tag; ``None``: English only).

    In order: a stored name or alias; the built-in style ``language``'s Word shows as
    ``name``; the one English Word shows as ``name``.  Case-insensitive; ``trim`` -- the
    name taken without the spaces round it -- is the field's to say, since Word does not
    read every field alike (measured, round 21: ``TOC \\t`` trims its names, ``STYLEREF``
    does not, and ``" Chapter title "`` there is Word's error).  ``None`` when nothing
    matches."""
    wanted = (name.strip() if trim else name).casefold()
    if not wanted.strip():
        return None
    stored = {key.strip().casefold(): value for key, value in reversed(list(styles.items()))}
    if wanted in stored:
        return stored[wanted]
    for language_key in dict.fromkeys(filter(None, (measured_language(language), "en"))):
        builtin = _reverse(language_key).get(wanted)
        if builtin is not None and builtin in stored:
            return stored[builtin]
    return None
