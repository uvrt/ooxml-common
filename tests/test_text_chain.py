"""The text chain: which layers a run's inherited properties come from (measured, round 15)."""

from ooxml_common.drawingml import text_chain as tc


def test_a_shape_skips_the_masters_other_style():
    assert tc.inherited_layers(None) == ("list style", "style fontRef", "defaultTextStyle")
    assert tc.layers(None)[:2] == ("run", "paragraph")
    assert not tc.default_paragraph_fallback(tc.holder_kind(None))


def test_placeholders_and_cells_keep_their_master_style():
    assert tc.inherited_layers("title") == ("list style", "layout", "master", "master titleStyle",
                                            "defaultTextStyle")
    assert tc.inherited_layers("subTitle")[3] == "master bodyStyle"
    assert tc.inherited_layers("sldNum")[3] == "master otherStyle"
    # an untyped placeholder is a body one
    assert tc.inherited_layers(None, placeholder=True)[3] == "master bodyStyle"
    assert tc.inherited_layers(None, table_cell=True) == ("list style", "table style",
                                                          "master otherStyle", "defaultTextStyle")
    assert tc.default_paragraph_fallback(tc.PLACEHOLDER)
    assert tc.default_paragraph_fallback(tc.TABLE_CELL)


def test_source_names_and_first_stated():
    assert tc.source_name("defaultTextStyle", 0) == "defaultTextStyle lvl1"
    assert tc.source_name("master bodyStyle", 1) == "master bodyStyle lvl2"
    assert tc.source_name("style fontRef", 3) == "style fontRef"
    assert tc.source_name("run") == "run"
    assert tc.first_stated([("run", None), ("defaultTextStyle", "FFFFFF")]) == ("FFFFFF",
                                                                                "defaultTextStyle")
    assert tc.first_stated([("run", None)]) == (None, "default")
