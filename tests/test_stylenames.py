"""Word's built-in style names per language (``stylenames.json``, measured by
``tools/word_style_names.py``) and a field's style name found by them."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ooxml_common import stylenames
from ooxml_common.stylenames import LIST_SEPARATORS, NAMES, builtin_names, find_style, list_separator

DATA = Path(stylenames.__file__).with_name("stylenames.json")
#: A document's styles as a caller passes them: stored name (or alias) -> style id.
STYLES = {"Normal": "Normal", "heading 2": "Heading2", "Title": "Title", "Section title": "Sectiontitle",
          "Kop 2": "CustomKop", "Chapter": "Sectiontitle"}


def test_every_language_measured_has_names_and_a_separator():
    data = json.loads(DATA.read_text(encoding="utf-8"))
    assert set(data["languages"]) == set(data["measured"]) == set(NAMES) == set(LIST_SEPARATORS)
    assert {"en", "nl", "fr", "de", "es", "it"} <= set(NAMES)
    for language, names in NAMES.items():
        assert "heading 2" in names and "Normal" in names, language
        assert len(LIST_SEPARATORS[language]) == 1


def test_english_word_shows_the_stored_names_capitalised():
    assert NAMES["en"]["heading 2"] == "Heading 2"
    assert NAMES["en"]["Normal"] == "Normal"


def test_a_language_is_its_primary_subtag():
    assert builtin_names("nl-BE") is NAMES["nl"]
    assert builtin_names("fr_FR") is NAMES["fr"]
    assert dict(builtin_names("xx-YY")) == {}
    assert builtin_names(None) == {}
    assert list_separator("en-GB") == LIST_SEPARATORS["en"]
    assert list_separator("xx", ";") == ";"


def test_a_stored_name_or_alias_comes_first():
    assert find_style("Section title", STYLES) == "Sectiontitle"
    assert find_style("  section TITLE ", STYLES) == "Sectiontitle"     # trimmed, any case
    assert find_style("chapter", STYLES, "nl-NL") == "Sectiontitle"      # an alias
    # A custom style named as Dutch Word shows heading 2 is that style, not the built-in.
    assert find_style("Kop 2", STYLES, "nl-NL") == "CustomKop"


def test_a_built_in_by_the_document_language_and_by_english():
    styles = {k: v for k, v in STYLES.items() if k != "Kop 2"}
    dutch = NAMES["nl"]["heading 2"]
    assert find_style(dutch, styles, "nl-NL") == "Heading2"
    assert find_style(dutch.upper(), styles, "nl") == "Heading2"
    assert find_style("Heading 2", styles, "nl-NL") == "Heading2"         # English too
    assert find_style(dutch, styles, "en-US") is None                     # not another language's
    assert find_style(dutch, styles) is None
    assert find_style(NAMES["fr"]["heading 2"], styles, "fr-FR") == "Heading2"


def test_a_built_in_the_document_does_not_define_is_not_found():
    assert find_style("Heading 3", STYLES, "en-US") is None
    assert find_style("No such style", STYLES, "nl-NL") is None
    assert find_style("   ", STYLES, "nl-NL") is None


@pytest.mark.parametrize("language", sorted(NAMES))
def test_every_display_name_finds_its_style(language):
    styles = {stored: stored for stored in NAMES[language]}
    shown = {}
    for stored, display in NAMES[language].items():
        shown.setdefault(display.casefold(), stored)
    for stored, display in NAMES[language].items():
        assert find_style(display, styles, language) == shown[display.casefold()]


def test_a_field_that_does_not_trim():
    # STYLEREF (measured, round 21 lane C): " Chapter title " is no style's name.
    assert find_style(" Section title ", STYLES, trim=False) is None
    assert find_style("SECTION TITLE", STYLES, trim=False) == "Sectiontitle"
    assert find_style(NAMES["nl"]["heading 2"], {"heading 2": "Heading2"}, "nl-BE", trim=False) == "Heading2"
