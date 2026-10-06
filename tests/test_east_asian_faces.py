"""PowerPoint's choice of face for a run's Japanese, as measured with pptx2svg's
``tools/make_font_resolution_probe.py`` (its ``tests/fixtures/font-resolution-probe.json``
holds the observations; the PANOSE values here are read from the installed faces)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from ooxml_common.drawingml.read_text import parse_run_properties
from ooxml_common.text.fontmap import (
    JAPANESE_GOTHIC,
    JAPANESE_MINCHO,
    japanese_fallback,
    panose_is_sans,
    theme_east_asian,
)

#: ``OS/2`` PANOSE (first four bytes) of the Latin faces probed, and what PowerPoint drew
#: a run's kana in over each.
PROBED = [
    ("Calibri", (2, 15, 5, 2), JAPANESE_GOTHIC),
    ("Arial", (2, 11, 6, 4), JAPANESE_GOTHIC),
    ("Aptos", (2, 11, 0, 4), JAPANESE_GOTHIC),
    ("Lato 2.015", (2, 15, 5, 2), JAPANESE_GOTHIC),
    ("Impact", (2, 11, 8, 6), JAPANESE_GOTHIC),
    ("Century Gothic", (2, 11, 5, 2), JAPANESE_GOTHIC),
    ("Times New Roman", (2, 2, 6, 3), JAPANESE_MINCHO),
    ("Cambria", (2, 4, 5, 3), JAPANESE_MINCHO),
    ("Rockwell", (2, 6, 6, 3), JAPANESE_MINCHO),
    ("Courier New", (2, 7, 3, 9), JAPANESE_MINCHO),
    ("Consolas", (2, 11, 6, 9), JAPANESE_MINCHO),
    ("Menlo", (2, 11, 6, 9), JAPANESE_MINCHO),
    ("Helvetica Neue", (2, 0, 5, 3), JAPANESE_MINCHO),
    ("Comic Sans MS", (3, 15, 9, 2), JAPANESE_MINCHO),
    ("Raleway 4.026", (0, 0, 0, 0), JAPANESE_MINCHO),
]


@pytest.mark.parametrize("face, panose, drawn", PROBED, ids=[row[0] for row in PROBED])
def test_the_latin_faces_panose_picks_gothic_or_mincho(face, panose, drawn):
    assert japanese_fallback(panose + (0,) * 6) == drawn


def test_a_face_that_is_not_installed_falls_back_to_gothic():
    assert japanese_fallback(None) == JAPANESE_GOTHIC
    assert not panose_is_sans(()) and not panose_is_sans(None)


def test_the_jpan_entry_is_plus_mn_ea_for_japanese_text_only():
    assert theme_east_asian("", "游ゴシック", "en-US") is None
    assert theme_east_asian("", "游ゴシック", None) is None
    assert theme_east_asian("", "游ゴシック", "ja-JP") == "游ゴシック"
    assert theme_east_asian("", "游ゴシック", "ja") == "游ゴシック"
    assert theme_east_asian("游ゴシック", "ＭＳ Ｐゴシック", "en-US") == "游ゴシック"
    assert theme_east_asian("游ゴシック", "ＭＳ Ｐゴシック", "ja-JP") == "ＭＳ Ｐゴシック"
    assert theme_east_asian("游ゴシック", "", "ja-JP") == "游ゴシック"
    assert theme_east_asian("", "游ゴシック", "en-US", "ja-JP") == "游ゴシック"
    assert theme_east_asian("", "游ゴシック", "ko-KR", "ja-JP") is None


def test_a_runs_language_is_read():
    a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    properties = parse_run_properties(ET.fromstring(f'<a:rPr xmlns:a="{a}" lang="ja"/>'))
    assert properties is not None and properties.lang == "ja"
    assert parse_run_properties(ET.fromstring(f'<a:rPr xmlns:a="{a}" sz="1200"/>')).lang is None
    assert parse_run_properties(ET.fromstring(f'<a:rPr xmlns:a="{a}" altLang="ja-JP"/>')).alt_lang == "ja-JP"


def test_powerpoint_strokes_bold_japanese_in_a_face_with_no_bold_cut():
    """``bold-sizes``: PowerPoint fills and strokes the regular outline (0.12 pt + 2% of
    the size); Word's rules keep asking for ``font-weight="bold"``."""
    from ooxml_common.drawingml import scene as m
    from ooxml_common.drawingml.context import RenderContext
    from ooxml_common.drawingml.rules import WORD
    from ooxml_common.drawingml.textbody import _style_attrs
    from ooxml_common.units import PX_PER_PT

    run = m.RunProperties(font_size=24, font_family="Calibri", font_family_ea="MS Gothic", bold=True)
    powerpoint = _style_attrs(run, 1.0, ["MS Gothic", "Calibri"], RenderContext(), east_asian=True)
    assert 'font-weight="bold"' not in powerpoint
    assert f'stroke-width="{round(0.6 * PX_PER_PT, 3):g}"' in powerpoint
    assert 'font-weight="bold"' in _style_attrs(run, 1.0, ["MS Gothic"], RenderContext(rules=WORD), east_asian=True)
    # A face with a bold cut of its own is asked for bold, and Latin text is never stroked.
    noto = m.RunProperties(font_size=24, font_family="Calibri", font_family_ea="Noto Sans JP", bold=True)
    assert 'font-weight="bold"' in _style_attrs(noto, 1.0, ["Noto Sans JP"], RenderContext(), east_asian=True)
    assert "stroke" not in _style_attrs(run, 1.0, ["Calibri"], RenderContext())
