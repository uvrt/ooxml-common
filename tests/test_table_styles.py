"""PowerPoint's built-in table styles (``drawingml.table_styles``) and the Office theme of a
new file (``drawingml.theme``): the catalogues and what their readers give."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from ooxml_common.drawingml import table_styles, theme

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def test_there_are_74_styles_with_their_own_names():
    styles = table_styles.BUILTIN_TABLE_STYLES
    assert len(styles) == 74
    assert len({spec["name"] for spec in styles.values()}) == 74
    assert all(guid == guid.upper() for guid in styles)
    assert set(table_styles.MEASURED_BORDERS) <= set(styles)
    assert set(table_styles.THEMED_STYLES) <= set(styles)


def test_every_region_is_one_of_a_table_styles_regions():
    for spec in table_styles.BUILTIN_TABLE_STYLES.values():
        assert set(spec) - {"name"} <= set(table_styles.REGIONS)


def test_a_name_is_found_in_any_case():
    assert table_styles.builtin_name("{5c22544a-7ee6-4342-b048-85bdc9fd1c3a}") == (
        "Medium Style 2 - Accent 1")
    assert table_styles.builtin_name("{00000000-0000-0000-0000-000000000000}") is None
    assert table_styles.builtin_name(None) is None


def test_color_parts_read_a_compact_expression():
    assert table_styles.color_parts("dk1") == ("dk1", ())
    assert table_styles.color_parts("accent1/tint40") == ("accent1", (("tint", 40000),))
    assert table_styles.color_parts("dk1/alpha20/x") == ("dk1", (("alpha", 20000),))


def test_regions_carry_the_measured_borders_in_draw_order():
    light_2 = "{69012ECD-51FC-41F1-AA8D-1B2483CD663E}"      # Light Style 2 - Accent 1
    regions = table_styles.builtin_regions(light_2)
    assert list(regions) == [r for r in table_styles.REGIONS if r in regions]
    assert regions["band1V"]["borders"] == {"left": (1.0, "accent1"),
                                            "right": (1.0, "accent1")}
    # The catalogue's own border wins over a measured one on the same side.
    assert regions["wholeTbl"]["borders"]["top"] == (1.0, "accent1")
    assert table_styles.builtin_regions("{00000000-0000-0000-0000-000000000000}") is None


def test_a_themed_style_is_xml_with_its_accent():
    guid = "{775DCB02-9BB8-47FD-8907-85C794F793BA}"          # Themed Style 1 - Accent 4
    root = ET.fromstring(table_styles.themed_style_xml(guid))
    assert root.tag == f"{A}tblStyle"
    assert root.get("styleName") == "Themed Style 1 - Accent 4"
    fill = root.find(f"{A}tblBg/{A}fillRef/{A}schemeClr")
    assert fill.get("val") == "accent4"
    assert "{accent}" not in table_styles.themed_style_xml(guid)
    assert table_styles.themed_style_xml("{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}") is None


def test_text_colours_of_a_measured_and_a_themed_style():
    medium_2 = "{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}"
    assert table_styles.builtin_text_colors(medium_2) == {
        "wholeTbl": ("dk1", ()), "lastCol": ("lt1", ()), "firstCol": ("lt1", ()),
        "lastRow": ("lt1", ()), "firstRow": ("lt1", ())}
    themed_2 = "{D113A9D2-9D6B-4929-AA2D-F23B5EE8CBE7}"      # Themed Style 2 - Accent 1
    assert table_styles.builtin_text_colors(themed_2) == {"wholeTbl": ("lt1", ())}
    assert table_styles.builtin_text_colors("{00000000-0000-0000-0000-000000000000}") is None


def test_every_style_has_a_text_colour_for_the_whole_table():
    for guid in table_styles.BUILTIN_TABLE_STYLES:
        assert "wholeTbl" in table_styles.builtin_text_colors(guid), guid


def test_the_office_theme():
    names = [name for name, _ in theme.OFFICE_THEME_COLORS]
    assert names == ["dk1", "lt1", "dk2", "lt2", "accent1", "accent2", "accent3",
                     "accent4", "accent5", "accent6", "hlink", "folHlink"]
    assert (theme.OFFICE_MAJOR_FONT, theme.OFFICE_MINOR_FONT) == ("Aptos Display", "Aptos")


def test_word_and_powerpoint_differ_in_the_japanese_body_face_only():
    word, powerpoint = theme.WORD_SCRIPT_FONTS, theme.POWERPOINT_SCRIPT_FONTS
    assert len(word) == len(powerpoint) == 47
    assert len({script for script, _, _ in powerpoint}) == 47
    differ = [(w, p) for w, p in zip(word, powerpoint) if w != p]
    assert differ == [(("Jpan", "游ゴシック Light", "游明朝"),
                       ("Jpan", "游ゴシック Light", "游ゴシック"))]
