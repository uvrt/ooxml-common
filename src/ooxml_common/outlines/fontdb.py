"""The face resvg draws a run in, and the face it falls back to for a character, for
the fonts it is handed -- its font database (fontdb 0.24) and usvg's default font
resolver (resvg 0.48), read from their source.

* **Loading.**  resvg-py loads the system's fonts first (unless told to skip them), then
  the ``font_files`` in order, then each of the ``font_dirs`` walked; every face of a
  collection is a face.  A face is filed under its typographic family (name ID 16) where
  it has one, else its family (name ID 1), every language's record
  (:attr:`ooxml_common.fonts.office.Face.rasteriser_families`), with its ``OS/2``
  weight, width and italic or oblique bit.
* **A run's face.**  The run's ``font-family`` names, the generic keywords pointed at
  the families resvg was given, and then ``serif``'s family: the first name any face is
  filed under -- compared exactly -- and among its faces the CSS best match for the
  run's weight, stretch and style, the first loaded of a tie
  (:func:`ooxml_common.fonts.office.css_match`).
* **A character the face lacks.**  The first loaded face, other than those already
  tried, that maps the character and has the base face's style, weight or stretch (the
  resolver's condition, which skips only a face that differs in all three).

:class:`FontSetup` is what a rasterisation is handed; :class:`Database` answers for it.
Faces are read from their header tables (``name``, ``OS/2``), character maps only when a
fallback is looked for, outlines only for a face that draws.
"""

from __future__ import annotations

import os
import struct
import sys
import threading
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from ..fonts.office import css_match, decode_name
from ..fonts.rasterdb import RESVG_DEFAULT_FAMILIES, _entries, resvg_system_dirs
from .face import OutlineFace, load_face

__all__ = ["Database", "FontSetup", "HeaderFace"]


@dataclass(frozen=True)
class FontSetup:
    """The fonts one resvg call is handed: ``font_files``, ``font_dirs``, whether it
    loads the system's fonts, and ``families`` -- its options naming the default and
    generic families (``{"sans_serif_family": "Carlito"}``; resvg-py's defaults for the
    rest)."""

    font_files: tuple[str, ...] = ()
    font_dirs: tuple[str, ...] = ()
    system_fonts: bool = True
    families: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @classmethod
    def of(cls, font_files: Sequence[str] = (), font_dirs: Sequence[str] = (), system_fonts: bool = True,
           families: Mapping[str, str] | None = None) -> "FontSetup":
        return cls(tuple(str(p) for p in font_files or ()), tuple(str(p) for p in font_dirs or ()),
                   bool(system_fonts), tuple(sorted((k, v) for k, v in (families or {}).items() if v)))


def _read_by_resvg(platform: int, encoding: int) -> bool:
    return platform == 0 or (platform == 3 and encoding in (0, 1, 10)) or (platform, encoding) == (1, 0)


class HeaderFace:
    """One loaded face, from its headers: names, CSS keys; its character map read when
    first asked for."""

    __slots__ = ("path", "number", "stamp", "names", "css", "_face", "_lock")

    def __init__(self, path: str, number: int, stamp: tuple[int, int], names: tuple[str, ...],
                 css: tuple[int, int, str]) -> None:
        self.path, self.number, self.stamp, self.names, self.css = path, number, stamp, names, css
        self._face: OutlineFace | None | bool = False
        self._lock = threading.Lock()

    def face(self) -> OutlineFace | None:
        with self._lock:
            if self._face is False:
                self._face = load_face(self.path, self.number, self.stamp)
            return self._face  # type: ignore[return-value]

    def has_char(self, code: int) -> bool:
        face = self.face()
        return face is not None and face.has_char(code)

    def __repr__(self) -> str:
        return f"HeaderFace({self.path!r}, {self.number}, {self.names[:1]}, {self.css})"


_HEADERS: dict[tuple[str, int, int], tuple[HeaderFace, ...]] = {}
_HEADERS_LOCK = threading.Lock()


def _read_at(handle, offset: int, length: int) -> bytes:
    handle.seek(offset)
    data = handle.read(length)
    if len(data) != length:
        raise ValueError("truncated font")
    return data


def _file_faces(path: str, mtime: int, size: int) -> tuple[HeaderFace, ...]:
    key = (path, mtime, size)
    with _HEADERS_LOCK:
        found = _HEADERS.get(key)
    if found is not None:
        return found
    out: list[HeaderFace] = []
    try:
        with open(path, "rb") as handle:
            head = handle.read(12)
            if head[:4] == b"ttcf":
                count = struct.unpack_from(">I", head, 8)[0]
                offsets = struct.unpack(f">{count}I", _read_at(handle, 12, 4 * count))
            else:
                offsets = (0,)
            for number, offset in enumerate(offsets):
                try:
                    tables_count = struct.unpack_from(">H", _read_at(handle, offset + 4, 2))[0]
                    directory = _read_at(handle, offset + 12, 16 * tables_count)
                    tables = {directory[16 * i:16 * i + 4]: struct.unpack_from(">II", directory, 16 * i + 8)
                              for i in range(tables_count)}
                    records: list[tuple[int, int, int, str]] = []
                    if b"name" in tables:
                        table = _read_at(handle, *tables[b"name"])
                        _, n, storage = struct.unpack_from(">HHH", table, 0)
                        for i in range(n):
                            platform, encoding, language, name_id, length, at = struct.unpack_from(
                                ">6H", table, 6 + 12 * i)
                            if name_id not in (1, 16) or not _read_by_resvg(platform, encoding):
                                continue
                            text = decode_name(platform, encoding, table[storage + at:storage + at + length])
                            if text:
                                records.append((platform, language, name_id, text))
                    name_id = 16 if any(r[2] == 16 for r in records) else 1
                    chosen = [r for r in records if r[2] == name_id]
                    chosen.sort(key=lambda r: 0 if (r[0], r[1]) == (3, 0x409) else 1 if (r[0], r[1]) == (1, 0) else 2)
                    names: list[str] = []
                    for r in chosen:
                        if r[3] not in names:
                            names.append(r[3])
                    weight, width, style = 400, 5, "normal"
                    if b"OS/2" in tables:
                        os2 = _read_at(handle, *tables[b"OS/2"])
                        if len(os2) >= 64:
                            weight, width = struct.unpack_from(">HH", os2, 4)
                            selection = struct.unpack_from(">H", os2, 62)[0]
                            style = "italic" if selection & 0x01 else "oblique" if selection & 0x200 else "normal"
                            width = width if 1 <= width <= 9 else 5
                    out.append(HeaderFace(path, number, (mtime, size), tuple(names), (weight, width, style)))
                except (ValueError, struct.error, OSError):
                    continue
    except (OSError, ValueError, struct.error):
        pass
    result = tuple(out)
    with _HEADERS_LOCK:
        _HEADERS[key] = result
    return result


def _platform_defaults() -> Mapping[str, str]:
    if sys.platform in ("darwin", "win32"):
        return RESVG_DEFAULT_FAMILIES["mac-win"]
    if sys.platform.startswith("linux"):
        return RESVG_DEFAULT_FAMILIES["linux"]
    return RESVG_DEFAULT_FAMILIES["other"]


def _linux_system_dirs() -> list[str]:
    home = os.environ.get("HOME", "")
    return [d for d in ("/usr/share/fonts", "/usr/local/share/fonts",
                        os.path.join(home, ".fonts") if home else "",
                        os.path.join(home, ".local/share/fonts") if home else "") if d]


_GENERIC = {"serif": "serif_family", "sans-serif": "sans_serif_family", "cursive": "cursive_family",
            "fantasy": "fantasy_family", "monospace": "monospace_family"}


def parse_families(value: str | None) -> list[tuple[str, bool]]:
    """A ``font-family`` value as svgtypes parses it: ``[(name, generic)]``, quotes
    removed, an unquoted name's words joined by single spaces."""
    out: list[tuple[str, bool]] = []
    if not value:
        return out
    for part in value.split(","):
        name = part.strip()
        if len(name) >= 2 and name[0] == name[-1] and name[0] in "'\"":
            out.append((name[1:-1], False))
            continue
        name = " ".join(name.split())
        if not name:
            continue
        out.append((name, name in _GENERIC))
    return out


class Database:
    """resvg's font database for one :class:`FontSetup`."""

    def __init__(self, setup: FontSetup) -> None:
        self.setup = setup
        entries = []
        if setup.system_fonts:
            dirs = resvg_system_dirs()
            entries.extend(_entries((), dirs if dirs is not None else _linux_system_dirs()))
        entries.extend(_entries(setup.font_files, ()))
        entries.extend(_entries((), setup.font_dirs))
        self.faces: list[HeaderFace] = []
        for entry in entries:
            self.faces.extend(_file_faces(*entry))
        self.index = {id(face): n for n, face in enumerate(self.faces)}
        self.by_name: dict[str, list[HeaderFace]] = {}
        for face in self.faces:
            for name in face.names:
                self.by_name.setdefault(name, []).append(face)
        families = dict(_platform_defaults())
        families.update(dict(setup.families))
        self.families = families
        self._queries: dict[tuple, HeaderFace | None] = {}
        self._fallbacks: dict[tuple, HeaderFace | None] = {}

    def query(self, family: str | None, weight: int, stretch: int, style: str) -> HeaderFace | None:
        """The face a run asking for ``family`` (a ``font-family`` value) is drawn in."""
        key = (family, weight, stretch, style)
        if key in self._queries:
            return self._queries[key]
        names = parse_families(family)
        if not names:
            names = [(self.families["font_family"], False)]
        names.append(("serif", True))
        chosen = None
        for name, generic in names:
            actual = self.families[_GENERIC[name]] if generic else name
            candidates = self.by_name.get(actual)
            if candidates:
                matched = css_match(candidates, stretch, style, weight)
                chosen = matched[0] if matched else None
                break
        self._queries[key] = chosen
        return chosen

    def fallback(self, code: int, used: Sequence[HeaderFace]) -> HeaderFace | None:
        """The face the resolver falls back to for character ``code``, ``used`` the faces
        already tried (the run's first)."""
        key = (code, tuple(id(face) for face in used))
        if key in self._fallbacks:
            return self._fallbacks[key]
        base = used[0]
        found = None
        excluded = {id(face) for face in used}
        for face in self.faces:
            if id(face) in excluded:
                continue
            if face.css[2] != base.css[2] and face.css[0] != base.css[0] and face.css[1] != base.css[1]:
                continue
            if face.has_char(code):
                found = face
                break
        self._fallbacks[key] = found
        return found


_DATABASES: dict[tuple, Database] = {}
_DATABASES_LOCK = threading.Lock()


def database(setup: FontSetup) -> Database:
    """The :class:`Database` of ``setup``, kept while its files' stamps hold."""
    stamp = (setup, tuple(_entries(setup.font_files, setup.font_dirs)))
    with _DATABASES_LOCK:
        found = _DATABASES.get(stamp)
        if found is None:
            if len(_DATABASES) > 16:
                _DATABASES.clear()
            found = _DATABASES[stamp] = Database(setup)
    return found
