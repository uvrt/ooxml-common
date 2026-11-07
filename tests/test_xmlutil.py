"""The XML helpers' contracts, on trees that hold comments and processing instructions.

:func:`~ooxml_common.xmlutil.parse_xml` drops both, but a caller may hand over a tree that
keeps them: lxml's, or ElementTree's with a parser built with ``insert_comments`` and
``insert_pis``.  There a comment's tag is a function, not a string.
"""

from __future__ import annotations

from xml.etree.ElementTree import TreeBuilder, XMLParser, fromstring

import pytest

from ooxml_common import xmlutil
from ooxml_common.xmlutil import child, children, element_child, element_children, local_name, parse_xml

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML = (f'<w:p xmlns:w="{W}"><!-- a note --><w:pPr/><?mark here?><w:r><w:t>one</w:t></w:r>'
       '<!-- another --><w:r><w:t>two</w:t></w:r></w:p>')


def _with_comments(text: str):
    return fromstring(text, XMLParser(target=TreeBuilder(insert_comments=True, insert_pis=True)))


def test_element_children_skip_comments_and_processing_instructions():
    paragraph = _with_comments(XML)
    assert len(list(paragraph)) == 6
    assert [node.tag.rsplit("}", 1)[-1] for node in element_children(paragraph)] == ["pPr", "r", "r"]
    assert [node.find(f"{{{W}}}t").text for node in element_children(paragraph, "r")] == ["one", "two"]
    assert element_child(paragraph, "r") is element_children(paragraph, "r")[0]
    assert element_child(paragraph, "pPr") is not None and element_child(paragraph, "tbl") is None


def test_on_a_parsed_tree_they_are_children_and_child():
    paragraph = parse_xml(XML)
    assert element_children(paragraph) == children(paragraph)
    assert element_children(paragraph, "r") == children(paragraph, "r")
    assert element_child(paragraph, "r") is child(paragraph, "r")
    assert element_child(paragraph, "pPr") is child(paragraph, "pPr")


def test_nothing_gives_nothing():
    assert element_children(None) == [] and element_children(None, "r") == []
    assert element_child(None, "r") is None
    assert element_children(parse_xml(f'<w:p xmlns:w="{W}"/>')) == []


def test_children_return_a_list():
    found = element_children(parse_xml(XML), "r")
    assert isinstance(found, list) and isinstance(element_children(parse_xml(XML)), list)


# -- a tag's local name, kept once found (round 39) ---------------------------------------------
def test_a_tag_s_local_name_whatever_its_namespace_form():
    assert local_name("{http://schemas.openxmlformats.org/drawingml/2006/main}sp") == "sp"
    assert local_name("a:sp") == "sp"
    assert local_name("sp") == "sp"
    assert local_name("{urn:x}a:b") == "a:b"   # a URI's own colons are not a prefix's
    assert local_name("") == ""
    # Asked again: the same, from what was kept.
    assert local_name("{urn:x}a:b") == "a:b" and local_name("a:sp") == "sp"


def test_past_the_limit_names_are_still_found_and_nothing_more_is_kept(monkeypatch):
    monkeypatch.setattr(xmlutil, "_LOCAL_NAMES", {})
    monkeypatch.setattr(xmlutil, "LOCAL_NAMES", 3)
    names = [local_name(f"{{urn:limit}}n{k}") for k in range(10)]
    assert names == [f"n{k}" for k in range(10)]
    assert len(xmlutil._LOCAL_NAMES) == 3


def test_a_tag_that_is_not_a_string_fails_as_it_did():
    with pytest.raises(AttributeError):
        local_name(None)  # type: ignore[arg-type]
