"""The package kinds: extension, main content type, template and macro flags."""

from __future__ import annotations

from pathlib import Path

import pytest

from ooxml_common.kinds import (
    EXTENSION_KINDS,
    KINDS,
    MAIN_CONTENT_TYPES,
    kind_for,
    kind_like,
    kind_mismatch,
    kind_of,
    main_content_type,
)

WML = "application/vnd.openxmlformats-officedocument.wordprocessingml."
PML = "application/vnd.openxmlformats-officedocument.presentationml."


def test_every_application_has_a_document_a_template_and_their_macro_forms():
    for application in ("word", "powerpoint", "excel"):
        flags = {(k.template, k.macro_enabled) for k in KINDS.values() if k.application == application}
        assert flags == {(False, False), (False, True), (True, False), (True, True)}
    assert len(set(MAIN_CONTENT_TYPES.values())) == len(KINDS) == 12
    assert EXTENSION_KINDS[".dotm"] == "dotm" and KINDS["dotm"].extension == ".dotm"


def test_the_content_types_the_editors_write():
    assert MAIN_CONTENT_TYPES["docx"] == WML + "document.main+xml"
    assert MAIN_CONTENT_TYPES["dotx"] == WML + "template.main+xml"
    assert MAIN_CONTENT_TYPES["docm"] == "application/vnd.ms-word.document.macroEnabled.main+xml"
    assert MAIN_CONTENT_TYPES["dotm"] == "application/vnd.ms-word.template.macroEnabledTemplate.main+xml"
    assert MAIN_CONTENT_TYPES["pptx"] == PML + "presentation.main+xml"
    assert MAIN_CONTENT_TYPES["potx"] == PML + "template.main+xml"
    assert MAIN_CONTENT_TYPES["pptm"] == "application/vnd.ms-powerpoint.presentation.macroEnabled.main+xml"
    assert MAIN_CONTENT_TYPES["potm"] == "application/vnd.ms-powerpoint.template.macroEnabled.main+xml"
    assert MAIN_CONTENT_TYPES["xlsx"].endswith("spreadsheetml.sheet.main+xml")


@pytest.mark.parametrize("target,kind", [
    ("report.docx", "docx"), ("REPORT.DOTM", "dotm"), (Path("a/b.potx"), "potx"), ("x.xltm", "xltm"),
    ("notes.txt", None), ("noextension", None), (b"PK...", None), (None, None),
])
def test_kind_for(target, kind):
    assert kind_for(target) == kind


def test_kind_for_one_application():
    assert kind_for("book.xlsx", "word") is None
    assert kind_for("deck.pptm", "powerpoint") == "pptm"


def test_kind_of_and_main_content_type_and_kind_like():
    assert kind_of(WML + "template.main+xml") == "dotx"
    assert kind_of("application/xml") is None and kind_of(None) is None
    assert main_content_type("potx") == PML + "template.main+xml"
    assert main_content_type("out.docm") == MAIN_CONTENT_TYPES["docm"]
    with pytest.raises(KeyError):
        main_content_type("out.txt")
    assert kind_like("docm", template=True) == "dotm"
    assert kind_like("potx", template=False, macro_enabled=True) == "pptm"
    assert kind_like("xlsx") == "xlsx"


def test_no_mismatch_when_the_types_agree_or_there_is_no_kind_to_disagree_with():
    assert kind_mismatch(MAIN_CONTENT_TYPES["docx"], "a.docx") is None
    assert kind_mismatch(MAIN_CONTENT_TYPES["dotx"], "a.zip") is None
    assert kind_mismatch(MAIN_CONTENT_TYPES["dotx"], b"bytes") is None


def test_a_template_saved_as_a_document():
    problem = kind_mismatch(MAIN_CONTENT_TYPES["dotx"], "summary.docx")
    assert (problem.expected, problem.actual) == ("docx", "dotx")
    assert problem.template_differs and not problem.macros_differ and not problem.application_differs
    assert problem.expected_type == MAIN_CONTENT_TYPES["docx"]
    assert str(problem).startswith("a .docx file whose main part is a .dotx's")


def test_macros_in_a_kind_that_takes_none_and_none_in_one_that_does():
    problem = kind_mismatch(MAIN_CONTENT_TYPES["pptm"], "deck.potx")
    assert problem.template_differs and problem.macros_differ and problem.macros_forbidden
    problem = kind_mismatch(MAIN_CONTENT_TYPES["pptx"], "deck.pptm")
    assert problem.macros_differ and not problem.macros_forbidden and not problem.template_differs


def test_another_applications_type_or_none():
    problem = kind_mismatch(MAIN_CONTENT_TYPES["pptx"], "a.docx")
    assert problem.application_differs and problem.actual == "pptx"
    problem = kind_mismatch("application/xml", "a.docx")
    assert problem.actual is None and problem.application_differs
    assert not problem.template_differs and not problem.macros_differ
    assert "of no kind's type (application/xml)" in str(problem)
