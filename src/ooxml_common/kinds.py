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

**What the bytes are** (:func:`package_kind`, :func:`identify_package`): the kind a file's
*content* declares, whatever it is called -- for a host that receives an upload and must
send it to the right library before opening it::

    from ooxml_common.kinds import identify_package, package_kind

    package_kind(upload)                   # "xlsx", "docm"...; None when it is no kind here
    found = identify_package(upload)       # .kind, .reason, .legacy, .content_type
    if found.kind is None:
        print(found.reason)                # "an Excel 97-2003 workbook (.xls), a compound file..."

It reads the ZIP's central directory and two small parts -- ``_rels/.rels`` for the main
part and ``[Content_Types].xml`` for its type (ECMA-376 Part 2, 10.1.2 and 9.3) -- never the
rest, inside the limits the libraries open packages with (:data:`IDENTIFY_LIMITS`).  What is
not a package is named by its first bytes: a compound file by the streams it holds
(:mod:`ooxml_common.cfb`: ``.xls``, ``.doc``, ``.ppt``, an encrypted package), a BIFF2-4
``.xls``, an XML spreadsheet or document of Office 2003, PDF, RTF and OpenDocument.
"""

from __future__ import annotations

import io
import os
import posixpath
import re
import zipfile
from dataclasses import dataclass
from typing import BinaryIO

from .cfb import CFB_SIGNATURE, compound_file_names

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


# -- what the bytes are --------------------------------------------------------------------------


@dataclass(frozen=True)
class IdentifyLimits:
    """The limits :func:`identify_package` reads within: the file's size, the ZIP's entries
    (both ooxml-edit's ``Limits`` defaults, which every library opens a package with), and
    the two parts it reads, each by its declared size and expansion."""

    max_package_bytes: int = 50 * 1024 * 1024
    max_parts: int = 2000
    #: ``[Content_Types].xml`` and ``_rels/.rels``, uncompressed, each.
    max_part_bytes: int = 1024 * 1024
    #: Either part may expand at most this many times its stored size.
    max_compression_ratio: int = 200


#: The limits by default.
IDENTIFY_LIMITS = IdentifyLimits()

#: Main part content types of packages that are no kind here, with what to call them.
OTHER_PACKAGES: dict[str, str] = {
    "application/vnd.ms-excel.sheet.binary.macroEnabled.main":
        "an Excel binary workbook (.xlsb)",
    "application/vnd.ms-excel.addin.macroEnabled.main+xml": "an Excel add-in (.xlam)",
    _OOXML + "presentationml.slideshow.main+xml": "a PowerPoint slide show (.ppsx)",
    "application/vnd.ms-powerpoint.slideshow.macroEnabled.main+xml":
        "a macro-enabled PowerPoint slide show (.ppsm)",
    "application/vnd.ms-powerpoint.addin.macroEnabled.main+xml": "a PowerPoint add-in (.ppam)",
}

#: What a file is when it is no package, by its compound file's streams or its first bytes:
#: each value is the :attr:`Identified.legacy` name and the reason given.
LEGACY: dict[str, tuple[str, str]] = {
    "xls": ("xls", "an Excel 97-2003 workbook (.xls), a compound file with a Workbook stream "
                   "([MS-XLS] 2.1.2): save it as .xlsx"),
    "biff": ("xls", "an Excel 2.x-4.x workbook (.xls), a BIFF file ([MS-XLS] 2.4.21): save "
                    "it as .xlsx"),
    "doc": ("doc", "a Word 97-2003 document (.doc), a compound file with a WordDocument "
                   "stream ([MS-DOC] 2.1.1): save it as .docx"),
    "ppt": ("ppt", "a PowerPoint 97-2003 presentation (.ppt), a compound file with a "
                   "PowerPoint Document stream ([MS-PPT] 2.1.1): save it as .pptx"),
    "encrypted": ("encrypted", "an encrypted (password-protected) Office file, a compound file "
                               "with an EncryptedPackage stream ([MS-OFFCRYPTO] 2.3.4.4): "
                               "remove the password and save it again"),
    "compound": ("compound", "a compound file ([MS-CFB]) that holds no Office document"),
    "xml2003": ("xml2003", "an XML file of Office 2003 (an XML spreadsheet or document), not "
                           "a package: save it as an Office Open XML file"),
    "pdf": ("pdf", "a PDF file, not an Office package"),
    "rtf": ("rtf", "an RTF document, not an Office package: save it as .docx"),
    "odf": ("odf", "an OpenDocument file, not an Office Open XML package"),
}


@dataclass(frozen=True)
class Identified:
    """What :func:`identify_package` found.  ``kind`` a :data:`KINDS` name, or ``None``;
    then ``reason`` says what the input is instead, or why it cannot be told, and names
    nothing of its content but part names and content types.  ``legacy`` names a format
    recognised that is not a package (``"xls"``, ``"doc"``, ``"ppt"``, ``"encrypted"``,
    ``"xml2003"``, ``"pdf"``, ``"rtf"``, ``"odf"``, ``"compound"``); ``content_type`` is the
    main part's, when one was found; ``limit`` is true when a limit stopped the reading."""

    kind: str | None
    reason: str | None = None
    content_type: str | None = None
    main_part: str | None = None
    legacy: str | None = None
    limit: bool = False

    def __bool__(self) -> bool:
        return self.kind is not None


_REL_MAIN = ("http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
             "http://purl.oclc.org/ooxml/officeDocument/relationships/officeDocument")
_BIFF_BOF = (b"\x09\x00", b"\x09\x02", b"\x09\x04")
_DOCTYPE = re.compile(rb"<!DOCTYPE|<!ENTITY", re.IGNORECASE)
_XML2003 = (b"urn:schemas-microsoft-com:office:spreadsheet",
            b"http://schemas.microsoft.com/office/word/2003/wordml")


def package_kind(source: "bytes | bytearray | memoryview | str | os.PathLike[str] | BinaryIO",
                 limits: IdentifyLimits = IDENTIFY_LIMITS) -> str | None:
    """The kind (``"xlsx"``, ``"dotm"``...) the package's main part declares, read from
    the bytes, a path or a binary file; ``None`` for anything else
    (:func:`identify_package` says why)."""
    return identify_package(source, limits).kind


def identify_package(source: "bytes | bytearray | memoryview | str | os.PathLike[str] | BinaryIO",
                     limits: IdentifyLimits = IDENTIFY_LIMITS) -> Identified:
    """What ``source`` is (see the module): its kind, or ``None`` with the reason.

    A path is never read past its ZIP directory and the two parts; a file object is read
    from where it stands and put back there when it can seek.  A file over
    ``limits.max_package_bytes`` is refused unread.  Nothing raises for what the input
    holds; a ``TypeError`` for a source that is none of these."""
    if isinstance(source, (bytes, bytearray, memoryview)):
        data = bytes(source)
        if len(data) > limits.max_package_bytes:
            return _over(f"{len(data)} bytes; at most {limits.max_package_bytes}")
        return _identify(data, io.BytesIO(data), limits)
    if isinstance(source, (str, os.PathLike)):
        size = os.stat(source).st_size
        if size > limits.max_package_bytes:
            return _over(f"{size} bytes; at most {limits.max_package_bytes}")
        with open(source, "rb") as handle:
            return _identify(handle.read(8192), handle, limits)
    if hasattr(source, "read"):
        start = None
        try:
            start = source.tell() if source.seekable() else None
        except (AttributeError, OSError):
            start = None
        try:
            data = source.read(limits.max_package_bytes + 1)
        finally:
            if start is not None:
                source.seek(start)
        if not isinstance(data, bytes):
            raise TypeError("a file opened in binary mode is needed")
        if len(data) > limits.max_package_bytes:
            return _over(f"over {limits.max_package_bytes} bytes")
        return _identify(data, io.BytesIO(data), limits)
    raise TypeError(f"cannot identify {type(source).__name__}: give bytes, a path or a "
                    "binary file")


def _over(detail: str) -> Identified:
    return Identified(None, f"over the size limit: {detail}", limit=True)


def _legacy(key: str) -> Identified:
    name, reason = LEGACY[key]
    return Identified(None, reason, legacy=name)


def _identify(head: bytes, stream: BinaryIO, limits: IdentifyLimits) -> Identified:
    if not head:
        return Identified(None, "an empty file")
    if head.startswith(CFB_SIGNATURE):
        return _compound(head, stream, limits)
    if head[:2] in _BIFF_BOF:
        return _legacy("biff")
    if head.startswith(b"%PDF-"):
        return _legacy("pdf")
    if head.startswith(b"{\\rtf"):
        return _legacy("rtf")
    if not head.startswith(b"PK"):
        text = head.lstrip(b"\xef\xbb\xbf \t\r\n")
        if text.startswith(b"<") and any(marker in head for marker in _XML2003):
            return _legacy("xml2003")
        return Identified(None, "neither a ZIP package nor a compound file")
    try:
        with zipfile.ZipFile(stream) as archive:
            return _package(archive, limits)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, ValueError, EOFError, OSError) as exc:
        return Identified(None, f"a ZIP whose directory cannot be read ({type(exc).__name__})")


def _compound(head: bytes, stream: BinaryIO, limits: IdentifyLimits) -> Identified:
    stream.seek(0)
    data = stream.read(limits.max_package_bytes + 1)
    try:
        names = compound_file_names(data)
    except ValueError as exc:
        return Identified(None, f"a compound file whose directory cannot be read ({exc})",
                          legacy="compound")
    if "EncryptedPackage" in names:
        return _legacy("encrypted")
    if "Workbook" in names or "Book" in names:
        return _legacy("xls")
    if "WordDocument" in names:
        return _legacy("doc")
    if "PowerPoint Document" in names:
        return _legacy("ppt")
    return _legacy("compound")


def _package(archive: zipfile.ZipFile, limits: IdentifyLimits) -> Identified:
    infos = archive.infolist()
    if len(infos) > limits.max_parts:
        return Identified(None, f"over the part limit: {len(infos)} entries; at most "
                          f"{limits.max_parts}", limit=True)
    by_name: dict[str, zipfile.ZipInfo] = {}
    for info in infos:
        by_name.setdefault(info.filename.lstrip("/").lower(), info)
    if "mimetype" in by_name and "[content_types].xml" not in by_name:
        return _legacy("odf")
    types_info = by_name.get("[content_types].xml")
    if types_info is None:
        return Identified(None, "a ZIP with no [Content_Types].xml: not an Office package")
    types, problem = _read_small(archive, types_info, limits)
    if types is None:
        return Identified(None, f"[Content_Types].xml {problem}", limit="limit" in problem)
    defaults, overrides = _content_types(types)
    if defaults is None:
        return Identified(None, "[Content_Types].xml cannot be read as XML")
    main = None
    rels_info = by_name.get("_rels/.rels")
    if rels_info is not None:
        rels, problem = _read_small(archive, rels_info, limits)
        if rels is None:
            return Identified(None, f"_rels/.rels {problem}", limit="limit" in problem)
        main = _main_part(rels)
    if main is None:
        found = [(part, ct) for part, ct in overrides.items()
                 if ct in _BY_CONTENT_TYPE or ct in OTHER_PACKAGES]
        if len(found) != 1:
            return Identified(None, "a package with no main part (no officeDocument "
                              "relationship in _rels/.rels)")
        main = found[0][0]
    content_type = overrides.get(main.lower())
    if content_type is None:
        content_type = defaults.get(posixpath.splitext(main)[1][1:].lower())
    if content_type is None:
        return Identified(None, f"the main part {main} has no content type", main_part=main)
    content_type = content_type.split(";")[0].strip()
    kind = kind_of(content_type)
    if kind is not None:
        return Identified(kind, content_type=content_type, main_part=main)
    what = OTHER_PACKAGES.get(content_type)
    reason = f"{what}, which no library here opens" if what else \
        f"a package whose main part is of no kind here ({content_type})"
    return Identified(None, reason, content_type=content_type, main_part=main)


def _read_small(archive: zipfile.ZipFile, info: zipfile.ZipInfo,
                limits: IdentifyLimits) -> tuple[bytes | None, str]:
    if info.file_size > limits.max_part_bytes:
        return None, f"is over the size limit ({info.file_size} bytes; at most " \
                     f"{limits.max_part_bytes})"
    if info.file_size > 1024 and info.file_size > limits.max_compression_ratio * max(
            info.compress_size, 1):
        return None, "is over the expansion limit"
    try:
        with archive.open(info) as handle:
            data = handle.read(limits.max_part_bytes + 1)
    except Exception as exc:  # a damaged entry: BadZipFile, zlib.error, an unknown method...
        return None, f"cannot be read ({type(exc).__name__})"
    if len(data) > limits.max_part_bytes:
        return None, "is over the size limit"
    return data, ""


def _parse(data: bytes):
    # No document type declaration in either part (ECMA-376 Part 2 forbids DTDs, 8.1.4):
    # one is refused before parsing, so no entity is ever expanded.
    if _DOCTYPE.search(data):
        return None
    from xml.etree import ElementTree

    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return None


def _local(tag) -> str:
    return tag.rpartition("}")[2] if isinstance(tag, str) else ""


def _content_types(data: bytes) -> tuple[dict[str, str] | None, dict[str, str]]:
    root = _parse(data)
    if root is None or _local(root.tag) != "Types":
        return None, {}
    defaults: dict[str, str] = {}
    overrides: dict[str, str] = {}
    for node in root:
        name = _local(node.tag)
        content_type = node.get("ContentType")
        if not content_type:
            continue
        if name == "Default" and node.get("Extension"):
            defaults[node.get("Extension", "").lower()] = content_type
        elif name == "Override" and node.get("PartName"):
            overrides[node.get("PartName", "").lstrip("/").lower()] = content_type
    return defaults, overrides


def _main_part(data: bytes) -> str | None:
    root = _parse(data)
    if root is None:
        return None
    for node in root:
        if _local(node.tag) == "Relationship" and node.get("Type") in _REL_MAIN \
                and node.get("TargetMode") != "External":
            target = (node.get("Target") or "").strip()
            if target:
                return posixpath.normpath(target.lstrip("/"))
    return None


__all__ = ["EXTENSION_KINDS", "IDENTIFY_LIMITS", "Identified", "IdentifyLimits", "KINDS",
           "KindMismatch", "LEGACY", "MAIN_CONTENT_TYPES", "OTHER_PACKAGES", "PackageKind",
           "REL_VBA_PROJECT", "identify_package", "kind_for", "kind_like", "kind_mismatch",
           "kind_of", "main_content_type", "package_kind"]
