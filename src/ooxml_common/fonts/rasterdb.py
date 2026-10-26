"""The font files a resvg rasterisation of one SVG needs, out of all it is handed.

resvg-py builds a new font database on every call: it opens and parses every file of
every folder it is handed (``font_dirs``) and every file named (``font_files``), only to
draw a slide that names two families.  With an application's font folder of 57 Office
faces, a bundle and two passes per slide that was most of a rasterisation where opening a
file is slow (production measured about half a second per call), and it is work whatever
the file system.  resvg-py 0.5 keeps no database between calls but the system's, so the
way to load less is to hand it less: :func:`needed_font_files` names the files of the
folders and file list that can take part in drawing this SVG, in the order resvg would
have loaded them, and the caller hands those over as ``font_files`` and no folders.

**The answer draws the same pixels**, by how resvg's font database (fontdb 0.24, behind
resvg 0.48 in resvg-py 0.5) chooses a face -- read from its source, not assumed:

* **A run's face** is the best style match among *all* loaded faces filed under the first
  family of its stack that any face is filed under (the stack, then the ``serif``
  family, which resvg appends to every stack); ties go to the first loaded.  So every
  face filed under any name a stack can resolve to is kept -- the stacks' names, the
  generic families' targets, the default family -- and the choice among them, ties
  included, is unchanged: what is kept is kept in the order it was loaded.
* **A character its face lacks** is drawn by the first loaded face (other than the ones
  already tried) that maps it.  So every face that maps a character some candidate face
  of its run may lack is kept, and the first of them is the same face.

Everything else -- a face no name reaches and no missing character needs -- is never
looked at by resvg, and leaving it out changes nothing.  Names are compared without case
(resvg compares them exactly, so this keeps more, never less); a face whose names or
character map this module cannot read is kept; the system's fonts, which resvg-py loads
once per process, are never left out, only read to know which characters their faces
lack.  Where the SVG could name a family some other way -- CSS (a ``<style>`` sheet or a
``style`` attribute naming a font), ``<use>`` (whose copies inherit where they are used),
a picture referenced by path -- or the platform's system fonts are not listed here
(Linux reads fontconfig's), the answer is ``None``: hand over everything, as before.

Header tables only (``name``, ``cmap``); no outline is read and nothing is written.
"""

from __future__ import annotations

import base64
import functools
import os
import re
import struct
import sys
import threading
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Mapping, Sequence

from .office import _cmap_subtable, decode_name

__all__ = ["RESVG_DEFAULT_FAMILIES", "file_stamps", "forget", "load_order", "needed_font_files",
           "parsed_svg", "resvg_system_dirs"]

#: The extensions resvg's font database loads from a folder (fontdb's
#: ``load_fonts_dir``), exactly: no other case is.
_FOLDER_SUFFIXES = frozenset({"ttf", "ttc", "TTF", "TTC", "otf", "otc", "OTF", "OTC"})

#: resvg-py 0.5's defaults for the default family and the generic families, by platform
#: (``svg_to_bytes``'s ``font_family``, ``serif_family``...), where the caller sets none.
RESVG_DEFAULT_FAMILIES: Mapping[str, Mapping[str, str]] = {
    "mac-win": {"font_family": "Times New Roman", "serif_family": "Times New Roman",
                "sans_serif_family": "Arial", "cursive_family": "Comic Sans MS",
                "fantasy_family": "Impact", "monospace_family": "Courier New"},
    "linux": {"font_family": "Liberation Serif", "serif_family": "Liberation Serif",
              "sans_serif_family": "Liberation Sans", "cursive_family": "Comic Neue",
              "fantasy_family": "Anton", "monospace_family": "Liberation Mono"},
    "other": {"font_family": "serif", "serif_family": "serif",
              "sans_serif_family": "sans-serif", "cursive_family": "cursive",
              "fantasy_family": "fantasy", "monospace_family": "monospace"},
}
_GENERIC_OPTION = {"serif": "serif_family", "sans-serif": "sans_serif_family",
                   "cursive": "cursive_family", "fantasy": "fantasy_family",
                   "monospace": "monospace_family"}
#: Becomes a space before resvg shapes a run (usvg's ``trim_text``).
_TO_SPACE = str.maketrans("\r\n\t", "   ")


def _platform_defaults() -> Mapping[str, str]:
    if sys.platform in ("darwin", "win32"):
        return RESVG_DEFAULT_FAMILIES["mac-win"]
    if sys.platform.startswith("linux"):
        return RESVG_DEFAULT_FAMILIES["linux"]
    return RESVG_DEFAULT_FAMILIES["other"]


# --------------------------------------------------------------------------------------
# What the SVG asks for
# --------------------------------------------------------------------------------------

_SVG_NS = "{http://www.w3.org/2000/svg}"
_HREFS = ("href", "{http://www.w3.org/1999/xlink}href")
_RASTER_DATA = re.compile(r"\s*data:image/(png|jpeg|jpg|gif|webp)\b", re.I)
_SVG_DATA = re.compile(r"\s*data:image/svg\+xml\s*(;[^,]*)?,", re.I)


class _Unanswerable(Exception):
    """The SVG may name a family in a way this module does not follow."""


@functools.lru_cache(maxsize=2)
def parsed_svg(svg: str) -> ET.Element:
    """``xml.etree.ElementTree.fromstring(svg)``, kept for the last two documents, so the
    checks a rasterisation runs over one SVG -- pptx2svg's glyph check, then
    :func:`needed_font_files` -- parse it once.  Read it; never change it.  Raises
    :class:`~xml.etree.ElementTree.ParseError` as ``fromstring`` does."""
    return ET.fromstring(svg)


def _stacks(svg: str, depth: int = 0) -> "tuple[bool, dict[str | None, set[str]]]":
    """``(has <text>, {font-family value or None: characters under it})`` over the whole
    document and the SVG pictures it carries as data; every character of every element
    is counted, text or not (more is safe).  Raises :class:`_Unanswerable`."""
    if depth > 4:
        raise _Unanswerable("pictures nested too deep")
    try:
        root = parsed_svg(svg) if depth == 0 else ET.fromstring(svg)
    except ET.ParseError as error:
        raise _Unanswerable(str(error)) from error
    out: dict[str | None, set[str]] = {}
    has_text = False

    def add(stack: str | None, text: str | None) -> None:
        if text:
            out.setdefault(stack, set()).update(text.translate(_TO_SPACE))

    def walk(element: ET.Element, stack: str | None) -> None:
        nonlocal has_text
        tag = element.tag
        local = tag.rpartition("}")[2] if isinstance(tag, str) else ""
        if local in ("style", "use"):
            raise _Unanswerable(f"<{local}>")
        if "font" in element.get("style", ""):
            raise _Unanswerable("a font in a style attribute")
        if local == "text" and (tag == _SVG_NS + "text"):
            has_text = True
        if local == "image":
            for name in _HREFS:
                href = element.get(name)
                if href is not None:
                    _picture(href, depth, out)
        stack = element.get("font-family", stack)
        add(stack, element.text)
        for child in element:
            walk(child, stack)
            add(stack, child.tail)

    walk(root, None)
    return has_text, out


def _picture(href: str, depth: int, out: dict) -> None:
    """Add the stacks of an SVG picture carried as data to ``out``; a raster is nothing
    to read, anything else (a path, an unreadable picture) unanswerable."""
    if _RASTER_DATA.match(href):
        return
    found = _SVG_DATA.match(href)
    if found is None:
        raise _Unanswerable("a picture by reference")
    payload = href[found.end():]
    try:
        if found.group(1) and "base64" in found.group(1).lower():
            text = base64.b64decode(payload).decode("utf-8")
        else:
            text = urllib.parse.unquote(payload)
    except (ValueError, UnicodeDecodeError) as error:
        raise _Unanswerable("an unreadable SVG picture") from error
    _, nested = _stacks(text, depth + 1)
    for stack, chars in nested.items():
        out.setdefault(stack, set()).update(chars)


def _names(value: str | None) -> list[str]:
    """The names in a ``font-family`` value, unquoted, lowercased, in order."""
    if not value:
        return []
    for entity, char in (("&quot;", '"'), ("&apos;", "'"), ("&amp;", "&")):
        value = value.replace(entity, char)
    out = []
    for part in value.split(","):
        name = part.strip()
        if len(name) >= 2 and name[0] == name[-1] and name[0] in "'\"":
            name = name[1:-1].strip()
        if name:
            out.append(name.lower())
    return out


# --------------------------------------------------------------------------------------
# What the files hold, read once per process
# --------------------------------------------------------------------------------------

#: A face this module cannot read: kept, and taken to lack every character.
_UNKNOWN = None


class _FaceInfo:
    """One face: its names (lowercased, ID 1 and ID 16, every record resvg reads) and
    where its character map is, read when first asked for (:func:`_coverage_of`)."""

    __slots__ = ("names", "key")

    def __init__(self, names: frozenset, key: tuple) -> None:
        self.names = names
        self.key = key

    @property
    def strict(self) -> frozenset:
        """What every Unicode subtable maps: what the shaper surely finds."""
        return _coverage_of(*self.key)[0]

    @property
    def loose(self) -> "frozenset | None":
        """What any subtable maps (a symbol subtable's U+F0xx also as U+00xx): what a
        fallback may find; ``None`` where a subtable's format is not read (anything)."""
        return _coverage_of(*self.key)[1]


def _read_at(handle, offset: int, length: int) -> bytes:
    handle.seek(offset)
    data = handle.read(length)
    if len(data) != length:
        raise ValueError("truncated font")
    return data


def _face_tables(handle, offset: int) -> dict:
    tables_count = struct.unpack_from(">H", _read_at(handle, offset + 4, 2))[0]
    directory = _read_at(handle, offset + 12, 16 * tables_count)
    return {directory[16 * i:16 * i + 4]: struct.unpack_from(">II", directory, 16 * i + 8)
            for i in range(tables_count)}


def _offsets(handle) -> tuple:
    head = handle.read(12)
    if head[:4] != b"ttcf":
        return (0,)
    count = struct.unpack_from(">I", head, 8)[0]
    if not 0 < count <= 4096:
        raise ValueError("not a font collection")
    return struct.unpack(f">{count}I", _read_at(handle, 12, 4 * count))


@functools.lru_cache(maxsize=4096)
def _file_faces(path: str, mtime: int, size: int) -> "tuple[_FaceInfo | None, ...] | None":
    """Every face of the file at ``path``, from its ``name`` tables; ``None`` where the
    file cannot be read as fonts (it is kept whole).  Cached on path, modification time
    and size."""
    try:
        with open(path, "rb") as handle:
            return tuple(_face(handle, offset, (path, mtime, size, number))
                         for number, offset in enumerate(_offsets(handle)))
    except (OSError, ValueError, struct.error):
        return None


#: The name records resvg's database reads (fontdb's ``collect_families``): Unicode
#: ones, and Macintosh Roman.
def _read_by_resvg(platform: int, encoding: int) -> bool:
    return platform == 0 or (platform == 3 and encoding in (0, 1, 10)) or (platform, encoding) == (1, 0)


def _face(handle, offset: int, key: tuple) -> "_FaceInfo | None":
    try:
        tables = _face_tables(handle, offset)
        names: set[str] = set()
        if b"name" in tables:
            table = _read_at(handle, *tables[b"name"])
            _, count, storage = struct.unpack_from(">HHH", table, 0)
            for i in range(count):
                platform, encoding, _lang, name_id, length, at = struct.unpack_from(">6H", table, 6 + 12 * i)
                if name_id not in (1, 16) or not _read_by_resvg(platform, encoding):
                    continue
                text = decode_name(platform, encoding, table[storage + at:storage + at + length])
                if text is not None:
                    names.add(text.lower())
                    names.add(text.strip().lower())
        return _FaceInfo(frozenset(names), key)
    except (OSError, ValueError, struct.error, IndexError):
        return _UNKNOWN


@functools.lru_cache(maxsize=1024)
def _coverage_of(path: str, mtime: int, size: int, number: int) -> "tuple[frozenset, frozenset | None]":
    """``(strict, loose)`` character maps of face ``number`` of ``path``
    (:class:`_FaceInfo`); neither is known (nothing, anything) where it cannot be read."""
    try:
        with open(path, "rb") as handle:
            tables = _face_tables(handle, _offsets(handle)[number])
            if b"cmap" not in tables:
                return frozenset(), frozenset()
            return _coverage(_read_at(handle, *tables[b"cmap"]))
    except (OSError, ValueError, struct.error, IndexError):
        return frozenset(), None


def _coverage(table: bytes) -> "tuple[frozenset, frozenset | None]":
    count = struct.unpack_from(">H", table, 2)[0]
    strict: "set[int] | None" = None
    loose: "set[int] | None" = set()
    for i in range(count):
        platform, encoding, at = struct.unpack_from(">HHI", table, 4 + 8 * i)
        fmt = struct.unpack_from(">H", table, at)[0]
        if fmt == 14:
            continue                         # variation sequences, not a character map
        unicode = platform == 0 or (platform == 3 and encoding in (1, 10))
        if fmt not in (0, 4, 6, 12, 13):
            loose = None
            if unicode:
                strict = set()               # cannot say what it maps: assume nothing
            continue
        mapped = set(_cmap_subtable(table, at))
        if unicode:
            strict = mapped if strict is None else strict & mapped
        if loose is not None:
            loose |= mapped
            if platform == 3 and encoding == 0:
                loose |= {code - 0xF000 for code in mapped if 0xF000 <= code <= 0xF0FF}
    return frozenset(strict or ()), (None if loose is None else frozenset(loose))


def _stat(path: str) -> "tuple[str, int, int] | None":
    try:
        stat = os.stat(path)
    except OSError:
        return None                          # nothing there: resvg loads nothing either
    return path, stat.st_mtime_ns, stat.st_size


# --------------------------------------------------------------------------------------
# The order resvg loads files in
# --------------------------------------------------------------------------------------

_LOCK = threading.Lock()
#: folder -> (((folder, st_mtime_ns), ...) of every folder walked,
#: ((file, st_mtime_ns, st_size), ...) in order)
_WALKS: dict[str, tuple[tuple[tuple[str, int], ...], tuple[tuple[str, int, int], ...]]] = {}


def _walk_folder(root: str) -> "tuple[tuple[str, int, int], ...]":
    """The font files resvg's database loads from ``root``, in its order, with their
    modification times and sizes: each folder's entries as the system lists them (no
    sorting), a subfolder walked where it is met, links followed (to their target's
    path), a folder once.  Kept while no folder of it changes its modification time: one
    stat per folder per call, none per file -- on a slow mount a stat is not free."""
    with _LOCK:
        cached = _WALKS.get(root)
    if cached is not None:
        try:
            if all(os.stat(folder).st_mtime_ns == stamp for folder, stamp in cached[0]):
                return cached[1]
        except OSError:
            pass
    stamps: list[tuple[str, int]] = []
    files: list[tuple[str, int, int]] = []
    seen: set[str] = set()

    def visit(folder: str) -> None:
        try:
            stamps.append((folder, os.stat(folder).st_mtime_ns))
            entries = list(os.scandir(folder))
        except OSError:
            return
        for entry in entries:
            try:
                path = entry.path
                if entry.is_symlink():
                    target = os.path.realpath(path)
                    if target in seen or not os.path.exists(target):
                        continue
                    seen.add(target)
                    path = target
                is_dir = os.path.isdir(path) if entry.is_symlink() else entry.is_dir()
                if is_dir:
                    visit(path)
                elif path.rpartition(".")[2] in _FOLDER_SUFFIXES and "." in os.path.basename(path)[1:]:
                    found = _stat(path)
                    if found is not None:
                        files.append(found)
            except OSError:
                continue

    visit(root)
    result = tuple(files)
    with _LOCK:
        _WALKS[root] = (tuple(stamps), result)
    return result


def forget() -> None:
    """Forget every folder walk and every face read
    (:func:`ooxml_common.fonts.office.refresh_font_dirs` calls this)."""
    with _LOCK:
        _WALKS.clear()
    _file_faces.cache_clear()
    _coverage_of.cache_clear()


def load_order(font_files: Sequence[str] = (), font_dirs: Sequence[str] = ()) -> list[str]:
    """Every file resvg loads for ``font_files`` and ``font_dirs`` (after the system's,
    when it reads them), in its order: the files as named, then each folder walked."""
    return [entry[0] for entry in _entries(font_files, font_dirs)]


def file_stamps(font_files: Sequence[str] = (), font_dirs: Sequence[str] = ()
                ) -> "list[tuple[str, int, int]]":
    """:func:`load_order` with each file's modification time (ns) and size:
    ``(path, mtime, size)``, what a cache of rasterisations keys on so that a font file
    changed, added or removed is a new key.  Folders are walked as :func:`load_order`
    walks them (cached while no folder changes)."""
    return _entries(font_files, font_dirs)


def _entries(font_files: Sequence[str], font_dirs: Sequence[str]) -> "list[tuple[str, int, int]]":
    out = [found for found in map(_stat, map(str, font_files)) if found is not None]
    for folder in font_dirs:
        out.extend(_walk_folder(str(folder)))
    return out


def resvg_system_dirs() -> "list[str] | None":
    """The folders resvg's database reads "the system's fonts" from (fontdb's
    ``load_system_fonts``) on this platform, or ``None`` where it asks fontconfig."""
    if sys.platform == "darwin":
        out = ["/Library/Fonts", "/System/Library/Fonts"]
        try:
            out.extend(entry.path for entry in os.scandir("/System/Library/AssetsV2")
                       if entry.name.startswith("com_apple_MobileAsset_Font"))
        except OSError:
            pass
        out.append("/Network/Library/Fonts")
        if os.environ.get("HOME"):
            out.append(os.path.join(os.environ["HOME"], "Library/Fonts"))
        return out
    if sys.platform == "win32":
        root = os.environ.get("SYSTEMROOT")
        out = [os.path.join(root, "Fonts") if root else "C:\\Windows\\Fonts\\"]
        home = os.environ.get("USERPROFILE")
        if home:
            out.append(os.path.join(home, "AppData\\Local\\Microsoft\\Windows\\Fonts"))
            out.append(os.path.join(home, "AppData\\Roaming\\Microsoft\\Windows\\Fonts"))
        return out
    return None


# --------------------------------------------------------------------------------------
# The answer
# --------------------------------------------------------------------------------------

def needed_font_files(
    svg: str,
    *,
    font_files: Sequence[str] = (),
    font_dirs: Sequence[str] = (),
    system_fonts: bool = False,
    families: Mapping[str, str] | None = None,
) -> "list[str] | None":
    """The files of ``font_files`` and ``font_dirs`` resvg needs to draw ``svg`` as it
    would with all of them, in its load order -- to be handed over as ``font_files``,
    with no ``font_dirs`` and ``skip_system_fonts`` as it was -- or ``None`` where this
    cannot be said (the module docstring).

    ``system_fonts`` is whether resvg also loads the system's fonts (not
    ``skip_system_fonts``); ``families`` the resvg options naming the default and generic
    families (``{"sans_serif_family": "Arimo", ...}``) the caller passes, the rest
    resvg-py's defaults.
    """
    try:
        has_text, stacks = _stacks(svg)
    except _Unanswerable:
        return None
    if not has_text:
        return []                            # resvg-py loads no font for an SVG without text
    named = dict(_platform_defaults())
    named.update({key: value for key, value in (families or {}).items() if value})
    default = named["font_family"].lower()
    serif = named["serif_family"].lower()

    def resolvable(value: str | None) -> set[str]:
        names = set()
        for name in _names(value):
            names.add(name)
            option = _GENERIC_OPTION.get(name)
            if option:
                names.add(named[option].lower())
        return names | {default, serif}      # an unparsable stack falls back to the default

    reachable = {value: resolvable(value) for value in stacks}
    wanted = set().union(*reachable.values()) if reachable else {default, serif}

    sources = _entries(font_files, font_dirs)
    system: list[tuple[str, int, int]] = []
    if system_fonts:
        dirs = resvg_system_dirs()
        if dirs is None:
            return None
        system = _entries((), dirs)
    faces: dict[tuple, "tuple[_FaceInfo | None, ...] | None"] = {}
    for entry in dict.fromkeys(sources + system):
        faces[entry] = _file_faces(*entry)

    # Characters some candidate face of their run may lack.
    by_name: dict[str, list] = {}
    unknown = False
    for path, found in faces.items():
        if found is None:
            unknown = True
            continue
        for face in found:
            if face is _UNKNOWN:
                unknown = True
                continue
            for name in face.names & wanted:
                by_name.setdefault(name, []).append(face)
    missing: set[int] = set()
    for value, chars in stacks.items():
        candidates = [face for name in reachable[value] for face in by_name.get(name, ())]
        codes = {ord(char) for char in chars}
        if unknown or not candidates:
            missing |= codes
            continue
        for face in candidates:
            missing |= codes - face.strict
            codes &= face.strict
            if not codes:
                break

    out: list[str] = []
    for entry in dict.fromkeys(sources):
        found = faces[entry]
        if found is None or any(face is _UNKNOWN for face in found):
            out.append(entry[0])
            continue
        known = [face for face in found if face is not None]  # every one, checked above
        if any(face.names & wanted for face in known) or (
                missing and any(face.loose is None or face.loose & missing for face in known)):
            out.append(entry[0])
    return list(dict.fromkeys(out))
