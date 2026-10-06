"""What kind of package a file extension names, and the main part's content type it needs.

An Office package says what it is twice: in its file name's extension, and in the content
type ``[Content_Types].xml`` declares for its main part.  The applications open a file only
when the two agree.  A template opened and saved under a document's name keeps the
template's content type unless the writer changes it, and is then refused -- measured in
Word (docx-agent's ``tests/test_oracle_trial.py``: every mismatch refused, the ``.docm``
form taking the macro-enabled type, as Word's own Save As writes it) and in PowerPoint
(pptx-agent's template tests: a ``.pptx`` declaring a template, a ``.potx`` declaring a
presentation, refused outright with no offer to repair).

These are the facts of ECMA-376 and of Office's macro-enabled extensions, shared by every
editor that writes a package: which extension names which kind, whether that kind is a
template and whether it may carry a VBA project, and the main part's content type for it.
Changing the content type in a package is an editor's job -- ooxml-edit's
``OpcPackage.declare_content_type`` -- and is not here::

    from ooxml_common.kinds import kind_for, main_content_type, kind_mismatch

    kind = kind_for("summary.docx")                      # "docx"
    wanted = main_content_type(kind)                     # ...wordprocessingml.document.main+xml
    problem = kind_mismatch(declared_main_type, "summary.docx")
    if problem is not None:
        print(problem)                                   # a .docx whose main part is a .dotx's ...

``.ppsx``/``.ppsm`` (a slide show), ``.xlam``/``.ppam`` (add-ins) and ``.xlsb`` (binary) are
not here: none is a document or a template, and no editor here writes one.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

_OOXML = "application/vnd.openxmlformats-officedocument."

#: The relationship from a macro-enabled package's main part to its VBA project, the same in
#: every format.  A kind that is not :attr:`PackageKind.macro_enabled` may not carry one.
REL_VBA_PROJECT = "http://schemas.microsoft.com/office/2006/relationships/vbaProject"


@dataclass(frozen=True)
class PackageKind:
    """One kind of package: ``name`` (``"docx"``, ``"potm"``...), the ``application`` that
    opens it (``"word"``, ``"powerpoint"`` or ``"excel"``), whether it is a ``template``
    and whether it is ``macro_enabled``, and the ``content_type`` its main part declares."""

    name: str
    application: str
    template: bool
    macro_enabled: bool
    content_type: str

    @property
    def extension(self) -> str:
        """``".docx"`` and so on: the kind's name is its extension."""
        return "." + self.name


#: Every kind, by name; each kind's name is its extension without the dot.
KINDS: dict[str, PackageKind] = {kind.name: kind for kind in (
    PackageKind("docx", "word", False, False, _OOXML + "wordprocessingml.document.main+xml"),
    PackageKind("docm", "word", False, True, "application/vnd.ms-word.document.macroEnabled.main+xml"),
    PackageKind("dotx", "word", True, False, _OOXML + "wordprocessingml.template.main+xml"),
    PackageKind("dotm", "word", True, True,
                "application/vnd.ms-word.template.macroEnabledTemplate.main+xml"),
    PackageKind("pptx", "powerpoint", False, False, _OOXML + "presentationml.presentation.main+xml"),
    PackageKind("pptm", "powerpoint", False, True,
                "application/vnd.ms-powerpoint.presentation.macroEnabled.main+xml"),
    PackageKind("potx", "powerpoint", True, False, _OOXML + "presentationml.template.main+xml"),
    PackageKind("potm", "powerpoint", True, True,
                "application/vnd.ms-powerpoint.template.macroEnabled.main+xml"),
    PackageKind("xlsx", "excel", False, False, _OOXML + "spreadsheetml.sheet.main+xml"),
    PackageKind("xlsm", "excel", False, True, "application/vnd.ms-excel.sheet.macroEnabled.main+xml"),
    PackageKind("xltx", "excel", True, False, _OOXML + "spreadsheetml.template.main+xml"),
    PackageKind("xltm", "excel", True, True, "application/vnd.ms-excel.template.macroEnabled.main+xml"),
)}

#: Extension (lower case, with the dot) -> kind name.
EXTENSION_KINDS: dict[str, str] = {kind.extension: name for name, kind in KINDS.items()}

#: Kind name -> its main part's content type.
MAIN_CONTENT_TYPES: dict[str, str] = {name: kind.content_type for name, kind in KINDS.items()}

_BY_CONTENT_TYPE = {kind.content_type: name for name, kind in KINDS.items()}


def kind_for(target, application: str | None = None) -> str | None:
    """The kind a path's extension names (``"docx"``, ``"potx"``...), case aside; ``None``
    for another extension, or for a target that is not a path (bytes, a file object).

    With ``application`` (``"word"``, ``"powerpoint"``, ``"excel"``) only that
    application's kinds count: ``kind_for("book.xlsx", "word")`` is ``None``."""
    if not isinstance(target, (str, os.PathLike)):
        return None
    name = EXTENSION_KINDS.get(os.path.splitext(os.fspath(target))[1].lower())
    if name is None or (application is not None and KINDS[name].application != application):
        return None
    return name


def kind_of(content_type: str | None) -> str | None:
    """The kind whose main part declares ``content_type``; ``None`` for any other type."""
    return _BY_CONTENT_TYPE.get(content_type or "")


def main_content_type(kind: str) -> str:
    """The main part's content type for a kind name (``"dotm"``) or a path whose extension
    names one; ``KeyError`` otherwise."""
    name = kind if kind in KINDS else kind_for(kind)
    if name is None:
        raise KeyError(kind)
    return KINDS[name].content_type


def kind_like(kind: str, *, template: bool | None = None, macro_enabled: bool | None = None) -> str:
    """The kind of the same application as ``kind`` with ``template`` and ``macro_enabled``
    as given (``None`` keeps ``kind``'s): ``kind_like("docm", template=True)`` is
    ``"dotm"``."""
    base = KINDS[kind]
    want_template = base.template if template is None else template
    want_macros = base.macro_enabled if macro_enabled is None else macro_enabled
    for name, other in KINDS.items():
        if other.application == base.application and other.template == want_template \
                and other.macro_enabled == want_macros:
            return name
    raise KeyError(kind)  # pragma: no cover -- every application has all four


@dataclass(frozen=True)
class KindMismatch:
    """A main part's content type that ``target``'s extension does not take.

    ``expected`` is the kind the extension names and ``expected_type`` its content type;
    ``actual`` is the kind the declared ``content_type`` belongs to, or ``None`` when it is
    no kind's (another application's type is a kind, of that application)."""

    target: str
    expected: str
    actual: str | None
    content_type: str | None

    @property
    def expected_type(self) -> str:
        return KINDS[self.expected].content_type

    @property
    def application_differs(self) -> bool:
        """The declared type is another application's, or none at all."""
        return self.actual is None or KINDS[self.actual].application != KINDS[self.expected].application

    @property
    def template_differs(self) -> bool:
        """One is a template and the other is not (a type of no kind counts as no template)."""
        return (self.actual is not None and KINDS[self.actual].template) != KINDS[self.expected].template

    @property
    def macros_differ(self) -> bool:
        """One is macro-enabled and the other is not (a type of no kind counts as neither)."""
        return (self.actual is not None and KINDS[self.actual].macro_enabled) \
            != KINDS[self.expected].macro_enabled

    @property
    def macros_forbidden(self) -> bool:
        """The package is macro-enabled and the extension's kind may carry no macros."""
        return self.macros_differ and not KINDS[self.expected].macro_enabled

    def __str__(self) -> str:
        if self.actual is None:
            what = f"of no kind's type ({self.content_type})"
        else:
            what = f"a .{self.actual}'s ({self.content_type})"
        return f"a .{self.expected} file whose main part is {what}; a .{self.expected} needs {self.expected_type}"


def kind_mismatch(content_type: str | None, target) -> KindMismatch | None:
    """How a main part declaring ``content_type`` disagrees with the kind ``target``'s
    extension names, or ``None`` when it does not -- or when ``target`` names no kind (bytes,
    a file object, another extension), which has nothing to disagree with."""
    expected = kind_for(target)
    if expected is None:
        return None
    if content_type == KINDS[expected].content_type:
        return None
    return KindMismatch(os.fspath(target), expected, kind_of(content_type), content_type)


__all__ = ["EXTENSION_KINDS", "KINDS", "KindMismatch", "MAIN_CONTENT_TYPES", "PackageKind",
           "REL_VBA_PROJECT", "kind_for", "kind_like", "kind_mismatch", "kind_of", "main_content_type"]
