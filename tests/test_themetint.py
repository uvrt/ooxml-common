"""Word's theme colour tint and shade (:mod:`ooxml_common.themetint`) against the colours
Word drew for made-up swatches (``tests/fixtures/word-theme-tints.json``)."""

from __future__ import annotations

import json
from pathlib import Path

from ooxml_common.themetint import word_theme_tint

OBSERVED = json.loads((Path(__file__).parent / "fixtures" / "word-theme-tints.json").read_text())["swatches"]


def test_every_swatch_is_words_to_the_level():
    wrong = [(s, word_theme_tint(s["base"], s["tint"], s["shade"])) for s in OBSERVED
             if word_theme_tint(s["base"], s["tint"], s["shade"]) != s["word"]]
    assert len(OBSERVED) == 586 and wrong == []


def test_the_ends_and_the_order():
    assert word_theme_tint("E97132", "FF") == "E97132"           # FF: the colour itself
    assert word_theme_tint("#e97132", shade="FF") == "E97132"
    assert word_theme_tint("E97132") == "E97132"
    assert word_theme_tint("E97132", "00") == "FFFFFF"
    assert word_theme_tint("E97132", shade="00") == "000000"
    assert word_theme_tint("156082", "99", "BF") == word_theme_tint("156082", "99")   # the tint counts
    assert word_theme_tint("156082", "zz", "BF") == word_theme_tint("156082", shade="BF")


def test_greys_round_down():
    assert word_theme_tint("E8E8E8", shade="60") == "575757"      # 232 * 96 / 255 = 87.3
    assert word_theme_tint("000000", "BF") == "404040"
    assert word_theme_tint("FFFFFF", shade="AF") == "AFAFAF"
