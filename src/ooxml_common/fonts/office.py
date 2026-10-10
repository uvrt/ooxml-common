"""Where Office for Mac finds a face, read in place: one lookup for PowerPoint and Word.

Office draws from three places, and only one of them is a place other programs look:

1. **The application's bundle** -- ``Microsoft PowerPoint.app/Contents/Resources/DFonts``
   (:data:`POWERPOINT_FONTS`) or Word's (:data:`WORD_FONTS`), where Office keeps Aptos,
   Calibri, Cambria, Consolas and some two hundred other faces that macOS does not list;
2. **macOS's own fonts** -- ``/System/Library/Fonts`` (and ``Supplemental``),
   ``/Library/Fonts``, ``~/Library/Fonts`` (:data:`MACOS_FONT_DIRS`);
3. **Office's cloud-font cache** -- ``~/Library/Group Containers/UBF8T346G9.Office/
   FontCache/4/CloudFonts`` (:data:`OFFICE_CLOUD_FONTS`), one folder per family, where
   Office downloads faces on demand: Aptos Display, the heading face of every deck and
   document Office 365 makes, lives only here (:func:`cloud_font_dirs`).

**Which wins is per application, and measured** (:class:`Application`):

* **PowerPoint lays out and draws with its bundle first, then macOS, then the cloud
  cache** (pptx2svg's ``tools/make_face_source_probe.py``).  Of 29 family-and-style pairs
  installed both in macOS and in the bundle, two can be told apart in PowerPoint's PDF,
  and it used the bundle's copy of both: Rockwell (macOS 13.0, the bundle 1.65, every
  advance different) to 0.5--1.5 pt against 21--26 pt, and Symbol (macOS's Unicode Greek,
  the bundle's symbol-encoded) to 0.09 pt against 75.6.
* **Word lays out with macOS's copy and draws with its bundle's** (docx2svg ROADMAP.md
  2.4): Times New Roman's line pitch and Greek kern pairs are macOS's v5.01, the outlines
  in its PDF the bundle's v7.00.  Symbol is the exception (:attr:`Application.prefer_bundle`):
  Word lays it out from its bundle -- a bullet line of ``sample-resume.docx`` is SymbolMT's
  1.2251 em, not the system Symbol's 1.0.  The cloud cache comes last.

No family is in both a bundle and the cloud cache, or in macOS and the cache, so the
cache's place is moot today; it comes last for both.

What is here:

* the locations, :func:`system_font_dirs` (elsewhere than macOS, the usual places) and
  :func:`cloud_font_dirs`, and an application's own folders (:func:`user_font_dirs`:
  given explicitly, or in ``OOXML_FONT_DIRS``), searched before all of them;
* a reader of the font tables a lookup and a layout need, standard library only
  (:class:`Face`: names, style, the ``cmap``, advances, the legacy ``kern`` table);
* a header-only index of every installed face (:class:`HostFace`, :func:`find`), with the
  names and CSS keys resvg's font database files a face under (:func:`css_match`);
* advance tables built from the installed faces, in memory (:func:`metrics`,
  :func:`layout_metrics`): a :class:`~ooxml_common.text.metrics.FontMetrics` with the
  face's legacy ``kern`` pairs, which is what both applications charge for a static face
  (:mod:`ooxml_common.text.kerning`).

**Nothing is copied.**  Files are read where they are installed: a few header tables to
learn a face's names and style, and its advances and kern pairs when a layout needs them.
Only paths and numbers leave this module; no font file enters an SVG, a repository or any
file this library writes.  Where the folders are absent -- another operating system, a Mac
without Office, CI -- every function here answers "nothing found".
"""

from __future__ import annotations

import functools
import os
import struct
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "FONT_DIRS_ENV",
    "MACOS_FONT_DIRS",
    "OFFICE_CLOUD_FONTS",
    "POWERPOINT",
    "POWERPOINT_FONTS",
    "USER",
    "WORD",
    "WORD_FONTS",
    "Application",
    "Face",
    "FontError",
    "HostFace",
    "CSS_STRETCH",
    "cloud_font_dirs",
    "css_match",
    "face_bytes",
    "faces_in",
    "env_font_dirs",
    "find",
    "font_dirs",
    "has_own_table",
    "index",
    "layout_metrics",
    "metrics",
    "metrics_of",
    "refresh_font_dirs",
    "search_dirs",
    "system_font_dirs",
    "user_families",
    "user_font_dirs",
    "user_search_dirs",
    "weight_order",
    "with_subfolders",
]

#: PowerPoint's own fonts, inside the application bundle.
POWERPOINT_FONTS = Path("/Applications/Microsoft PowerPoint.app/Contents/Resources/DFonts")
#: Word's own fonts, inside the application bundle.
WORD_FONTS = Path("/Applications/Microsoft Word.app/Contents/Resources/DFonts")

#: Where Office for Mac keeps the faces it downloads on demand, one folder per family.
OFFICE_CLOUD_FONTS = (
    Path.home() / "Library" / "Group Containers" / "UBF8T346G9.Office" / "FontCache" / "4"
    / "CloudFonts"
)

#: macOS's font folders, in the order its own font list reads them.
MACOS_FONT_DIRS = (
    Path("/System/Library/Fonts"),
    Path("/System/Library/Fonts/Supplemental"),
    Path("/Library/Fonts"),
    Path.home() / "Library" / "Fonts",
)

FONT_SUFFIXES = (".ttf", ".otf", ".ttc")

#: The environment variable naming an application's own font folders, ``os.pathsep``
#: separated (``:`` on macOS and Linux, ``;`` on Windows): read by pptx2svg and docx2svg
#: wherever no ``font_dirs`` is given (:func:`user_font_dirs`).
FONT_DIRS_ENV = "OOXML_FONT_DIRS"

#: The location an application's own folders are filed under (:func:`user_search_dirs`):
#: searched before every other, whatever the application's order.
USER = "user"


@dataclass(frozen=True)
class Application:
    """One Office application's font order, as measured (the module docstring).

    ``layout`` and ``drawing`` are the locations searched, in order, for the copy of a
    face the application lays text out with and the copy it draws: its bundle (named
    after it, ``"powerpoint"`` or ``"word"``), ``"system"`` and ``"cloud"``.
    ``prefer_bundle`` names families (lowercased) laid out from the bundle although an
    earlier location has them.
    """

    name: str
    bundle: Path
    layout: tuple[str, ...]
    drawing: tuple[str, ...]
    prefer_bundle: frozenset = frozenset()

    def order(self, purpose: str = "layout") -> tuple[str, ...]:
        if purpose not in ("layout", "drawing"):
            raise ValueError(f"no font order for {purpose!r}; 'layout' or 'drawing'")
        return self.layout if purpose == "layout" else self.drawing


#: PowerPoint lays out and draws with its bundle first, then macOS, then the cloud cache.
POWERPOINT = Application("powerpoint", POWERPOINT_FONTS, ("powerpoint", "system", "cloud"),
                         ("powerpoint", "system", "cloud"))
#: Word lays out with macOS's copy -- Symbol from its bundle -- and draws with its bundle's.
WORD = Application("word", WORD_FONTS, ("system", "word", "cloud"), ("word", "system", "cloud"),
                   prefer_bundle=frozenset({"symbol"}))


def system_font_dirs() -> tuple[Path, ...]:
    """The operating system's font folders that exist here.

    macOS's are the ones measured against Office.  Elsewhere they are the usual places,
    every folder under them included, so a host face is measured from the same file the
    rasteriser draws it with; no Office runs there to say otherwise.
    """
    if sys.platform == "darwin":
        return tuple(path for path in MACOS_FONT_DIRS if path.is_dir())
    home = Path.home()
    if os.name == "nt":
        windir = Path(os.environ.get("WINDIR", "C:/Windows"))
        roots = [windir / "Fonts", home / "AppData/Local/Microsoft/Windows/Fonts"]
    else:
        roots = [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"),
                 home / ".local/share/fonts", home / ".fonts"]
    out: list[Path] = []
    for root in roots:
        out.extend(_folders_under(root))
    return tuple(out)


def cloud_font_dirs(root: Path | None = None) -> tuple[Path, ...]:
    """The family folders of Office's cloud-font cache (:data:`OFFICE_CLOUD_FONTS`, or
    ``root``), sorted; none where it is absent or unreadable.  Listed once and kept while
    the cache folder's modification time stands (a family Office downloads is a new
    folder in it); :func:`refresh_font_dirs` forgets it."""
    root = Path(root or OFFICE_CLOUD_FONTS)
    try:
        stamp = os.stat(root).st_mtime_ns
    except OSError:
        return ()
    with _CACHE_LOCK:
        cached = _CLOUD_CACHE.get(root)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    try:
        found = tuple(sorted(path for path in root.iterdir() if path.is_dir()))
    except OSError:
        return ()
    with _CACHE_LOCK:
        _CLOUD_CACHE[root] = (stamp, found)
    return found


def env_font_dirs(environ=None) -> tuple[Path, ...]:
    """The folders :data:`FONT_DIRS_ENV` names, in its order (``~`` expanded, empty
    entries skipped); none where it is unset.  ``environ`` is :data:`os.environ` by
    default."""
    value = (os.environ if environ is None else environ).get(FONT_DIRS_ENV, "")
    return tuple(Path(part.strip()).expanduser() for part in value.split(os.pathsep) if part.strip())


def user_font_dirs(font_dirs=None, *, environ=None) -> tuple[Path, ...]:
    """An application's own font folders: ``font_dirs`` when it is given -- a sequence of
    paths, or one path; an empty sequence is "none", and the environment is not read --
    and otherwise :func:`env_font_dirs`.

    **Precedence**: the explicit argument, then :data:`FONT_DIRS_ENV`; whichever applies
    is *added* to the operating system's folders and searched before them, never in
    place of them.  The folders are returned as given; :func:`with_subfolders` lists
    what a one-level index must read."""
    if font_dirs is None:
        return env_font_dirs(environ)
    if isinstance(font_dirs, (str, os.PathLike)):
        font_dirs = [font_dirs]
    return tuple(Path(os.fspath(path)).expanduser() for path in font_dirs)


# --------------------------------------------------------------------------------------
# The folder walks, cached per process
# --------------------------------------------------------------------------------------
#
# Every text measurement asks for the application's folders and the folders under them,
# and a walk reads every entry of every folder (a stat each, where the entry type is not
# in the listing): on a slow mount -- a network share, WSL's 9p -- that was most of an
# agent's run.  So a root's walk is kept, with the modification time of every folder it
# found, and reused while those times stand: one stat per folder, none per file.  A file
# added to or removed from any folder, however deep, changes that folder's time (not its
# parent's -- which is why every folder is checked, not just the root); a new subfolder
# changes its parent's.  Then the root is walked again, and the face index, the font
# bytes and the advance tables read from it (:func:`index`, :func:`read_file`,
# :func:`metrics_of`) are forgotten, so the next measurement sees the folder as it is now.
#
# What a folder's time does not show -- a font file rewritten in place under the same
# name, or a change within the same tick on a file system whose times are coarse (FAT's
# two seconds) -- :func:`refresh_font_dirs` picks up: it forgets every walk and index.
# The cache is keyed by each folder as given, so two sessions with different folders
# never see each other's faces.

_CACHE_LOCK = threading.Lock()
#: root -> (((folder, st_mtime_ns), ...) for the root and every folder under it, the folders)
_WALK_CACHE: dict[Path, tuple[tuple[tuple[Path, int], ...], tuple[Path, ...]]] = {}
#: cloud cache root -> (st_mtime_ns, its family folders)
_CLOUD_CACHE: dict[Path, tuple[int, tuple[Path, ...]]] = {}


def _walk(root: Path) -> tuple[Path, ...]:
    """``root`` and every folder under it, sorted after the root -- as ``root.rglob("*")``
    filtered by ``is_dir()`` lists them (a link to a folder is listed, not descended) --
    from one listing per folder, the entry types the listing gives."""
    found: list[Path] = []
    pending = [root]
    while pending:
        folder = pending.pop()
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    try:
                        if not entry.is_dir():
                            continue
                        path = Path(entry.path)
                        found.append(path)
                        if not entry.is_symlink():
                            pending.append(path)
                    except OSError:
                        continue
        except OSError:
            continue
    return (root, *sorted(found))


def _stamps(folders) -> tuple[tuple[Path, int], ...] | None:
    """``(folder, st_mtime_ns)`` for each of ``folders``; ``None`` if one cannot be read."""
    try:
        return tuple((folder, os.stat(folder).st_mtime_ns) for folder in folders)
    except OSError:
        return None


def _still(stamps) -> bool:
    try:
        return all(os.stat(folder).st_mtime_ns == stamp for folder, stamp in stamps)
    except OSError:
        return False


def _folders_under(root) -> tuple[Path, ...]:
    """``root`` and every folder under it (:func:`_walk`), from the cache while no folder
    of it has changed; none where ``root`` is not a folder."""
    root = Path(root)
    with _CACHE_LOCK:
        cached = _WALK_CACHE.get(root)
    if cached is not None and _still(cached[0]):
        return cached[1]
    if not root.is_dir():
        with _CACHE_LOCK:
            _WALK_CACHE.pop(root, None)
        return ()
    folders = _walk(root)
    stamps = _stamps(folders)
    with _CACHE_LOCK:
        if stamps is not None:
            _WALK_CACHE[root] = (stamps, folders)
        else:
            _WALK_CACHE.pop(root, None)
    if cached is not None:
        _forget_faces()      # a folder changed: what was read from it may have too
    return folders


def _forget_faces() -> None:
    index.cache_clear()
    read_file.cache_clear()
    metrics_of.cache_clear()


def refresh_font_dirs() -> None:
    """Forget every cached folder walk, cloud-cache listing, face index, font file and
    advance table, so the next lookup reads the folders afresh.

    Not needed for a font added to or removed from an application's folder or one under
    it: a folder whose modification time changed is walked and indexed again by itself
    (one stat per folder per lookup).  It is for what a folder's time does not show -- a
    file rewritten in place under the same name, a change on a file system with coarse
    times, a system folder on macOS (indexed once per process, as before)."""
    with _CACHE_LOCK:
        _WALK_CACHE.clear()
        _CLOUD_CACHE.clear()
    _forget_faces()


def with_subfolders(dirs) -> tuple[Path, ...]:
    """Every folder in ``dirs`` that exists, each followed by the folders under it,
    sorted -- what a rasteriser reads when it is handed a folder (resvg's font database
    walks it), for an index that reads one level at a time.  Each folder once.

    Cached per process for each folder of ``dirs``, and checked with one stat per folder
    (not per file) on every call: a font added anywhere under a folder is seen by the next
    call (the cache notes above :func:`refresh_font_dirs`)."""
    out: list[Path] = []
    seen: set[Path] = set()
    for directory in dirs:
        for path in _folders_under(directory):
            if path not in seen:
                seen.add(path)
                out.append(path)
    return tuple(out)


def user_search_dirs(font_dirs=None) -> tuple[tuple[str, Path], ...]:
    """``(location, folder)`` for the application's own folders (:func:`user_font_dirs`)
    and the folders under them, filed under :data:`USER` -- the head of every
    :func:`search_dirs`, and what a lookup of the application's faces alone passes to
    :func:`find` as ``dirs``."""
    return tuple((USER, path) for path in with_subfolders(user_font_dirs(font_dirs)))


def font_dirs(application: Application = WORD, purpose: str = "layout") -> tuple[Path, ...]:
    """Every folder ``application`` searches for ``purpose``, in its order, macOS's four
    whether or not they exist -- the flat list a per-style lookup walks
    (docx2svg's ``installed_index``)."""
    places = {"system": MACOS_FONT_DIRS, application.name: (application.bundle,), "cloud": cloud_font_dirs()}
    return tuple(path for location in application.order(purpose) for path in places[location])


def search_dirs(application: Application = POWERPOINT, purpose: str = "layout", *,
                font_dirs=None) -> tuple[tuple[str, Path], ...]:
    """``(location, folder)`` for every folder that exists, in ``application``'s order,
    after the application's own (:func:`user_search_dirs` of ``font_dirs``: given, or
    :data:`FONT_DIRS_ENV`)."""
    places = {
        application.name: ((application.bundle,) if application.bundle.is_dir() else ()),
        "system": system_font_dirs(),
        "cloud": cloud_font_dirs(),
    }
    return user_search_dirs(font_dirs) + tuple(
        (location, path) for location in application.order(purpose) for path in places[location])


# --------------------------------------------------------------------------------------
# The font tables, standard library only
# --------------------------------------------------------------------------------------


class FontError(Exception):
    """A font file could not be read."""


def font_offsets(data: bytes) -> list[int]:
    """The offset of every font in a file: one, or each of a collection's."""
    if data[:4] == b"ttcf":
        count = struct.unpack_from(">I", data, 8)[0]
        return list(struct.unpack_from(f">{count}I", data, 12))
    return [0]


def table_directory(data: bytes, offset: int) -> dict[bytes, tuple[int, int]]:
    """``tag -> (offset, length)`` of the font at ``offset`` in ``data``."""
    if len(data) < offset + 12:
        raise FontError("too short for an offset table")
    count = struct.unpack_from(">H", data, offset + 4)[0]
    out: dict[bytes, tuple[int, int]] = {}
    for i in range(count):
        entry = offset + 12 + 16 * i
        tag = data[entry:entry + 4]
        table_offset, length = struct.unpack_from(">II", data, entry + 8)
        out[tag] = (table_offset, length)
    return out


def decode_name(platform: int, encoding: int, raw: bytes) -> str | None:
    """A name record as ``fontTools``' ``toUnicode`` reads it, or ``None`` where that
    would fail."""
    try:
        if platform == 0 or (platform == 3 and encoding in (0, 1, 10)):
            return raw.decode("utf-16-be")
        if platform == 1 and encoding == 0:
            return raw.decode("mac_roman")
        if platform == 3 and encoding == 2:
            return raw.decode("shift_jis")
        if platform == 3 and encoding == 3:
            return raw.decode("gb2312")
        if platform == 3 and encoding == 4:
            return raw.decode("big5")
        if platform == 3 and encoding == 5:
            return raw.decode("euc_kr")
        if platform == 3 and encoding == 6:
            return raw.decode("johab")
    except (UnicodeDecodeError, LookupError):
        return None
    return None


def name_records(table: bytes) -> list[tuple[int, int, int, int, str]]:
    """``[(platform, encoding, language, name ID, text)]`` of every decodable record."""
    if len(table) < 6:
        return []
    _, count, storage = struct.unpack_from(">HHH", table, 0)
    out = []
    for i in range(count):
        if 6 + 12 * i + 12 > len(table):
            break
        platform, encoding, language, name_id, length, offset = struct.unpack_from(">6H", table, 6 + 12 * i)
        text = decode_name(platform, encoding, table[storage + offset:storage + offset + length])
        if text is not None:
            out.append((platform, encoding, language, name_id, text))
    return out


def _cmap_subtable(table: bytes, offset: int) -> dict[int, int]:
    fmt = struct.unpack_from(">H", table, offset)[0]
    out: dict[int, int] = {}
    if fmt == 0:
        for code, glyph in enumerate(table[offset + 6:offset + 262]):
            if glyph:
                out[code] = glyph
    elif fmt == 4:
        segments = struct.unpack_from(">H", table, offset + 6)[0] // 2
        ends = struct.unpack_from(f">{segments}H", table, offset + 14)
        starts_at = offset + 16 + 2 * segments
        starts = struct.unpack_from(f">{segments}H", table, starts_at)
        deltas = struct.unpack_from(f">{segments}h", table, starts_at + 2 * segments)
        ranges_at = starts_at + 4 * segments
        ranges = struct.unpack_from(f">{segments}H", table, ranges_at)
        for k in range(segments):
            start, end, delta, range_offset = starts[k], ends[k], deltas[k], ranges[k]
            if start == 0xFFFF:
                continue
            for code in range(start, end + 1):
                if range_offset == 0:
                    glyph = (code + delta) & 0xFFFF
                else:
                    at = ranges_at + 2 * k + range_offset + 2 * (code - start)
                    if at + 2 > len(table):
                        continue
                    glyph = struct.unpack_from(">H", table, at)[0]
                    if glyph:
                        glyph = (glyph + delta) & 0xFFFF
                if glyph:
                    out[code] = glyph
    elif fmt == 6:
        first, count = struct.unpack_from(">HH", table, offset + 6)
        for i, glyph in enumerate(struct.unpack_from(f">{count}H", table, offset + 10)):
            if glyph:
                out[first + i] = glyph
    elif fmt in (12, 13):
        groups = struct.unpack_from(">I", table, offset + 12)[0]
        for i in range(groups):
            start, end, glyph = struct.unpack_from(">III", table, offset + 16 + 12 * i)
            for code in range(start, end + 1):
                value = glyph if fmt == 13 else glyph + (code - start)
                if value:
                    out[code] = value
    return out


#: ``fontTools``' ``getBestCmap`` order.
_CMAP_PREFERENCE = ((3, 10), (0, 6), (0, 4), (3, 1), (0, 3), (0, 2), (0, 1), (0, 0))


def read_cmap(table: bytes) -> dict[int, int]:
    """Code point -> glyph id: the best Unicode subtable (``fontTools``' choice), then a
    symbol font's (3, 0) subtable under it -- Wingdings and Symbol map their glyphs at
    U+F0xx there, which is what a Word list label's ``w:lvlText`` names."""
    count = struct.unpack_from(">H", table, 2)[0]
    subtables: dict[tuple[int, int], int] = {}
    for i in range(count):
        platform, encoding, offset = struct.unpack_from(">HHI", table, 4 + 8 * i)
        subtables.setdefault((platform, encoding), offset)
    out: dict[int, int] = {}
    for key in _CMAP_PREFERENCE:
        if key in subtables:
            out = _cmap_subtable(table, subtables[key])
            break
    if (3, 0) in subtables:
        for code, glyph in _cmap_subtable(table, subtables[(3, 0)]).items():
            out.setdefault(code, glyph)
    return out


def read_legacy_kern(table: bytes) -> dict[tuple[int, int], int]:
    """The legacy ``kern`` table's horizontal format 0 pairs, glyph id to glyph id, the
    first subtable's value winning -- the table PowerPoint and Word charge for a static
    face (:mod:`ooxml_common.text.kerning`)."""
    out: dict[tuple[int, int], int] = {}
    if len(table) < 4:
        return out
    version = struct.unpack_from(">H", table, 0)[0]
    try:
        if version == 0:
            count = struct.unpack_from(">H", table, 2)[0]
            at = 4
            for _ in range(count):
                _, length, coverage = struct.unpack_from(">HHH", table, at)
                if coverage >> 8 == 0:
                    pairs = struct.unpack_from(">H", table, at + 6)[0]
                    for i in range(pairs):
                        left, right, value = struct.unpack_from(">HHh", table, at + 14 + 6 * i)
                        out.setdefault((left, right), value)
                at += length
        else:
            # Apple's version 1.0 header: a 32-bit version and a 32-bit count.
            count = struct.unpack_from(">I", table, 4)[0]
            at = 8
            for _ in range(count):
                length, coverage = struct.unpack_from(">IH", table, at)
                if coverage & 0xFF == 0:
                    pairs = struct.unpack_from(">H", table, at + 8)[0]
                    for i in range(pairs):
                        left, right, value = struct.unpack_from(">HHh", table, at + 16 + 6 * i)
                        out.setdefault((left, right), value)
                at += length
    except struct.error:
        # A subtable whose length field overflowed past what is there: keep what was read.
        pass
    return out


_STYLES = {"Regular", "Bold", "Italic", "Bold Italic"}


class Face:
    """One font, read lazily from its file's bytes: names, style, the CSS keys a
    rasteriser matches, the ``cmap``, advances and legacy kern pairs."""

    def __init__(self, data: bytes, offset: int = 0, *, source: str = "") -> None:
        self.source = source
        self.offset = offset
        self._data = data
        self._tables = table_directory(data, offset)

    @property
    def data(self) -> bytes:
        """The bytes of the file the face is in."""
        return self._data

    def table(self, tag: bytes) -> bytes | None:
        found = self._tables.get(tag)
        if found is None:
            return None
        offset, length = found
        return self._data[offset:offset + length]

    @functools.cached_property
    def units_per_em(self) -> int:
        return struct.unpack_from(">H", self.table(b"head"), 18)[0]

    @functools.cached_property
    def names(self) -> list[tuple[int, str]]:
        """``[(name ID, text)]`` of every decodable record."""
        table = self.table(b"name")
        return [(record[3], record[4]) for record in name_records(table)] if table else []

    @functools.cached_property
    def style(self) -> tuple[bool, bool]:
        """``(bold, italic)``: ``OS/2`` fsSelection's bold and italic bits, or
        ``head.macStyle``'s."""
        os2 = self.table(b"OS/2")
        selection = struct.unpack_from(">H", os2, 62)[0] if os2 and len(os2) >= 64 else 0
        mac_style = struct.unpack_from(">H", self.table(b"head"), 44)[0]
        return bool(selection & 0x20 or mac_style & 1), bool(selection & 0x01 or mac_style & 2)

    @functools.cached_property
    def variable(self) -> bool:
        """Whether the face is a variable one (it has an ``fvar`` table)."""
        return b"fvar" in self._tables

    @functools.cached_property
    def rasteriser_families(self) -> tuple[str, ...]:
        """The family names a rasteriser that files faces as resvg's font database does
        finds this face by: its typographic family (name ID 16) where it has one, and then
        *only* that, else its family (name ID 1) -- every language's record.  The first is
        the English one (Windows US English, then Macintosh English), as that database
        lists it first."""
        table = self.table(b"name")
        records = name_records(table) if table else []
        name_id = 16 if any(record[3] == 16 for record in records) else 1
        chosen = [record for record in records if record[3] == name_id]
        chosen.sort(key=lambda r: (0 if (r[0], r[2]) == (3, 0x409) else 1 if (r[0], r[2]) == (1, 0) else 2))
        out: list[str] = []
        for record in chosen:
            if record[4] not in out:
                out.append(record[4])
        return tuple(out)

    @functools.cached_property
    def css(self) -> tuple[int, int, str]:
        """``(usWeightClass, usWidthClass, style)`` as resvg's database reads them: ``OS/2``
        alone, the style ``italic`` or ``oblique`` from ``fsSelection``'s bits 0 and 9."""
        os2 = self.table(b"OS/2")
        if os2 is None or len(os2) < 64:
            return 400, 5, "normal"
        weight, width = struct.unpack_from(">HH", os2, 4)
        selection = struct.unpack_from(">H", os2, 62)[0]
        style = "italic" if selection & 0x01 else "oblique" if selection & 0x200 else "normal"
        return weight, width if 1 <= width <= 9 else 5, style

    def reachable_as(self, family: str) -> bool:
        """Whether a rasteriser that files faces by their typographic family (name ID 16)
        when they have one finds this face by ``family``."""
        typographic = {text for name_id, text in self.names if name_id == 16}
        return not typographic or family in typographic

    def families(self) -> set[str]:
        """The family names Word may ask for this face by (name ID 1, and 16 where the
        typographic subfamily is one of the four styles, or absent)."""
        subfamily = {text for name_id, text in self.names if name_id == 17}
        typographic = not subfamily or bool(subfamily & _STYLES)
        return {text for name_id, text in self.names if name_id == 1 or (name_id == 16 and typographic)}

    @functools.cached_property
    def cmap(self) -> dict[int, int]:
        table = self.table(b"cmap")
        return read_cmap(table) if table else {}

    @functools.cached_property
    def advances(self) -> tuple[int, ...]:
        """Every glyph's advance, by glyph id up to ``numberOfHMetrics``."""
        count = struct.unpack_from(">H", self.table(b"hhea"), 34)[0]
        return struct.unpack_from(f">{2 * count}H", self.table(b"hmtx"), 0)[0::2]

    @functools.cached_property
    def legacy_kern(self) -> dict[tuple[int, int], int]:
        table = self.table(b"kern")
        return read_legacy_kern(table) if table else {}

    def glyph(self, char: str) -> int | None:
        return self.cmap.get(ord(char))

    def advance(self, char: str) -> int | None:
        glyph = self.glyph(char)
        if glyph is None:
            return None
        advances = self.advances
        return advances[glyph] if glyph < len(advances) else advances[-1]

    def kern(self, left: str, right: str) -> int:
        """The legacy ``kern`` table's adjustment for two characters, font units."""
        a, b = self.glyph(left), self.glyph(right)
        if a is None or b is None:
            return 0
        return self.legacy_kern.get((a, b), 0)


@functools.lru_cache(maxsize=None)
def read_file(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


def faces_of(path: Path) -> list[tuple[int, Face]]:
    """Every face in ``path`` (one, or each of a collection's), with its number; none if
    the file cannot be read."""
    try:
        data = read_file(str(path))
        return [(number, Face(data, offset, source=str(path))) for number, offset in enumerate(font_offsets(data))]
    except (OSError, struct.error, FontError):
        return []


# --------------------------------------------------------------------------------------
# What a rasteriser draws for a CSS font query (resvg's font database)
# --------------------------------------------------------------------------------------

#: CSS ``font-stretch`` for ``OS/2.usWidthClass`` 1-9.
CSS_STRETCH = ("ultra-condensed", "extra-condensed", "condensed", "semi-condensed", "normal", "semi-expanded",
               "expanded", "extra-expanded", "ultra-expanded")


def weight_order(desired: int, weights) -> list[int]:
    """CSS Fonts 3 (5.2, step 4d), as resvg's font database applies it: the weights
    tried for ``desired``, best first."""
    available = sorted(set(weights))
    if 400 <= desired <= 500:
        return ([w for w in available if desired <= w <= 500] + [w for w in reversed(available) if w < desired]
                + [w for w in available if w > 500])
    if desired < 400:
        return [w for w in reversed(available) if w <= desired] + [w for w in available if w > desired]
    return [w for w in available if w >= desired] + [w for w in reversed(available) if w < desired]


def css_match(faces: list, stretch: int, style: str, weight: int) -> list:
    """The faces CSS font matching ends with, for ``(usWidthClass, style, weight)``
    among ``faces`` (each with a ``css`` key, :attr:`Face.css`): one, or several that tie
    -- which one a rasteriser then draws is its load order, not anything an SVG can say."""
    if not faces:
        return []
    widths = sorted({face.css[1] for face in faces})
    if stretch in widths:
        chosen_width = stretch
    elif stretch <= 5:
        narrower = [w for w in reversed(widths) if w < stretch]
        chosen_width = narrower[0] if narrower else [w for w in widths if w > stretch][0]
    else:
        wider = [w for w in widths if w > stretch]
        chosen_width = wider[0] if wider else [w for w in reversed(widths) if w < stretch][0]
    faces = [face for face in faces if face.css[1] == chosen_width]
    order = {"italic": ("italic", "oblique", "normal"), "oblique": ("oblique", "italic", "normal"),
             "normal": ("normal", "oblique", "italic")}[style]
    present = {face.css[2] for face in faces}
    chosen_style = next(s for s in order if s in present)
    faces = [face for face in faces if face.css[2] == chosen_style]
    chosen_weight = weight_order(weight, [face.css[0] for face in faces])[0]
    return [face for face in faces if face.css[0] == chosen_weight]


# --------------------------------------------------------------------------------------
# The header-only index: every installed face by the family a document names
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class HostFace:
    """One installed face: where it is, what a document calls it, what a rasteriser does."""

    path: str
    #: Its index in a collection (``.ttc``), 0 for a single font.
    number: int
    location: str
    #: Name ID 1 in every language, normalised (:func:`~ooxml_common.text.fontmap.family_key`):
    #: the four-style family a document spells.
    families: frozenset
    #: What resvg's font database files the face under: name ID 16 where the face has
    #: one, else name ID 1 -- every language's, lowercased.
    rasteriser_families: frozenset
    bold: bool
    italic: bool
    #: ``(usWeightClass, usWidthClass, "normal" | "italic" | "oblique")``, as resvg matches.
    css: tuple
    #: Whether the face is a variable one (an ``fvar`` table).
    variable: bool = False
    #: Name ID 16, in English, normalised, where it is not also one of :attr:`families`:
    #: the typographic family a document may spell instead.  PowerPoint finds a face by
    #: it -- variable Noto Sans JP's name ID 1 is "Noto Sans JP Thin" -- but only after
    #: every face whose name ID 1 matches (:func:`find`), and never by a Japanese one
    #: (:func:`find`).
    typographic: frozenset = frozenset()
    #: ``OS/2`` PANOSE, the ten bytes (empty where the face has none): what PowerPoint
    #: reads to choose a Japanese face for a run that names none it can use
    #: (:func:`ooxml_common.text.fontmap.japanese_fallback`).
    panose: tuple = ()


def _read_at(handle, offset: int, length: int) -> bytes:
    handle.seek(offset)
    return handle.read(length)


def faces_in(path: Path, location: str) -> list[HostFace]:
    """Every face in ``path``, from its header tables alone; none if it is unreadable."""
    from ..text.fontmap import family_key

    out: list[HostFace] = []
    try:
        with open(path, "rb") as handle:
            head = handle.read(12)
            if head[:4] == b"ttcf":
                count = struct.unpack_from(">I", head, 8)[0]
                offsets = list(struct.unpack(f">{count}I", handle.read(4 * count)))
            else:
                offsets = [0]
            for number, offset in enumerate(offsets):
                header = _read_at(handle, offset, 12)
                tables_count = struct.unpack_from(">H", header, 4)[0]
                directory = _read_at(handle, offset + 12, 16 * tables_count)
                tables = {}
                for i in range(tables_count):
                    tag = directory[16 * i:16 * i + 4]
                    table_offset, length = struct.unpack_from(">II", directory, 16 * i + 8)
                    tables[tag] = (table_offset, length)
                if b"name" not in tables:
                    continue
                names: dict[int, list[str]] = {}
                english16: list[str] = []
                for platform, _encoding, language, name_id, text in name_records(_read_at(handle, *tables[b"name"])):
                    if name_id in (1, 16) and text.strip() and text.strip() not in names.setdefault(name_id, []):
                        names[name_id].append(text.strip())
                    if name_id == 16 and text.strip() and _english(platform, language):
                        english16.append(text.strip())
                os2 = _read_at(handle, *tables[b"OS/2"]) if b"OS/2" in tables else b""
                head_table = _read_at(handle, *tables[b"head"]) if b"head" in tables else b""
                weight, width, selection = 400, 5, 0
                if len(os2) >= 64:
                    weight, width = struct.unpack_from(">HH", os2, 4)
                    selection = struct.unpack_from(">H", os2, 62)[0]
                mac_style = struct.unpack_from(">H", head_table, 44)[0] if len(head_table) >= 46 else 0
                family = names.get(1, [])
                if not family:
                    continue
                rasteriser = names.get(16) or family
                style = "italic" if selection & 0x01 else "oblique" if selection & 0x200 else "normal"
                keys = frozenset(family_key(name) for name in family)
                out.append(HostFace(
                    path=str(path),
                    number=number,
                    location=location,
                    families=keys,
                    rasteriser_families=frozenset(name.lower() for name in rasteriser),
                    bold=bool(selection & 0x20 or mac_style & 1),
                    italic=bool(selection & 0x01 or mac_style & 2),
                    css=(weight, width if 1 <= width <= 9 else 5, style),
                    variable=b"fvar" in tables,
                    typographic=frozenset(family_key(name) for name in english16) - keys,
                    panose=tuple(os2[32:42]) if len(os2) >= 42 else (),
                ))
    except (OSError, struct.error, ValueError):
        return out
    return out


def _english(platform: int, language: int) -> bool:
    """Whether a name record is an English one: Unicode's (no language), Macintosh
    English, or a Windows English locale (primary language 0x09)."""
    return platform == 0 or (platform == 1 and language == 0) or (platform == 3 and language & 0x3FF == 0x09)


@functools.lru_cache(maxsize=None)
def index(dirs: tuple[tuple[str, Path], ...]) -> dict[str, dict[str, list[HostFace]]]:
    """``family key -> location -> faces``, every folder in ``dirs`` read once."""
    out: dict[str, dict[str, list[HostFace]]] = {}
    for location, directory in dirs:
        try:
            paths = sorted(directory.iterdir())
        except OSError:
            continue
        for path in paths:
            if path.suffix.lower() not in FONT_SUFFIXES:
                continue
            for face in faces_in(path, location):
                for family in face.families | face.typographic:
                    out.setdefault(family, {}).setdefault(location, []).append(face)
    return out


def user_families(font_dirs=None) -> frozenset:
    """Family keys (:func:`~ooxml_common.text.fontmap.family_key`) of every face in the
    application's own folders (:func:`user_search_dirs`), by name ID 1 or English name ID
    16: what a renderer draws from them, and a font report counts as supplied."""
    dirs = user_search_dirs(font_dirs)
    return frozenset(index(dirs)) if dirs else frozenset()


def find(family: str | None, application: Application = POWERPOINT, purpose: str = "layout", *,
         dirs: tuple[tuple[str, Path], ...] | None = None) -> tuple[HostFace, ...]:
    """The faces of ``family`` ``application`` would use here for ``purpose``: every style
    of it in the first location that has the family (:attr:`Application.layout` or
    ``drawing``; a :attr:`~Application.prefer_bundle` family's bundle first), the first copy
    of each style winning.  The application's own folders (:data:`USER`) come before
    every location.  ``dirs`` is :func:`search_dirs`' answer by default.  Empty where
    nothing installed answers to the name.

    **Which names find a face** is measured in PowerPoint for Mac (pptx2svg's
    ``tools/make_font_resolution_probe.py``, its ``names`` deck): a run's ``<a:ea>``
    naming an installed face, and the face PowerPoint's PDF draws it in.

    * **Name ID 1, in every language.**  ``ヒラギノ角ゴシック W3`` and ``Hiragino Sans W3``
      both draw HiraginoSans-W3 (macOS's folder); ``ＭＳ Ｐゴシック`` and ``MS PGothic``
      MS-PGothic, ``游明朝 Demibold`` and ``Yu Mincho Demibold`` YuMincho-Demibold
      (PowerPoint's bundle); ``黒体-繁`` STHeitiTC-Light.
    * **Name ID 16 in English, not in Japanese.**  ``Hiragino Sans``, ``Hiragino Mincho
      ProN``, ``Hiragino Maru Gothic ProN`` and ``Noto Sans JP`` (name ID 1 "Noto Sans JP
      Thin") are found; ``ヒラギノ角ゴシック``, ``ヒラギノ明朝 ProN`` and ``ヒラギノ丸ゴ ProN``,
      the same faces' Japanese name ID 16, are not -- PowerPoint draws MS Gothic for them,
      as for a face that is not installed.

    One measured exception is not explained by the name records: ``Hiragino Kaku Gothic
    ProN`` (and its ``ヒラギノ角ゴ ProN W3``) is not found, although its records have the
    same shape as Hiragino Sans's, while ``Hiragino Kaku Gothic ProN W3`` is.  This lookup
    finds it, and the one family is left at that.
    """
    if not family or family.startswith("+"):
        return ()
    from ..text.fontmap import family_key

    key = family_key(family)
    found = index(dirs if dirs is not None else search_dirs(application, purpose)).get(key)
    if not found:
        return ()
    order = application.order(purpose)
    if key in application.prefer_bundle:
        order = (application.name,) + tuple(location for location in order if location != application.name)
    for location in (USER, *order):
        faces = found.get(location)
        if faces:
            # A face whose name ID 1 is the family wins over one found by its name ID 16
            # alone: "Aptos" is Aptos, not Aptos Light, Aptos Black and the rest, whose
            # typographic family it also is.  Among the latter, the weight nearest the
            # style's (400, or 700 for bold) -- Noto Sans JP is one variable face.
            own = [face for face in faces if key in face.families]
            if not own:
                faces = sorted(faces, key=lambda f: abs(f.css[0] - (700 if f.bold else 400)))
            chosen: dict[tuple[bool, bool], HostFace] = {}
            for face in own or faces:
                chosen.setdefault((face.bold, face.italic), face)
            return tuple(chosen.values())
    return ()


# --------------------------------------------------------------------------------------
# Advance tables, for the layout
# --------------------------------------------------------------------------------------

#: The tables a layout needs from a face; the outlines are never read.
_LAYOUT_TABLES = (b"head", b"hhea", b"maxp", b"hmtx", b"cmap", b"OS/2", b"name", b"kern", b"fvar")


def face_bytes(face: HostFace) -> bytes:
    """The tables of ``face`` that measurement reads, as a font in memory only -- the
    outlines left behind, a collection member's tables gathered the way a single font
    holds them.  Never written anywhere."""
    from .sfnt import write_sfnt

    with open(face.path, "rb") as handle:
        head = handle.read(12)
        offset = 0
        if head[:4] == b"ttcf":
            offset = struct.unpack(">I", _read_at(handle, 12 + 4 * face.number, 4))[0]
        count = struct.unpack_from(">H", _read_at(handle, offset + 4, 2))[0]
        directory = _read_at(handle, offset + 12, 16 * count)
        tables = []
        for i in range(count):
            tag = directory[16 * i:16 * i + 4]
            if tag in _LAYOUT_TABLES:
                table_offset, length = struct.unpack_from(">II", directory, 16 * i + 8)
                tables.append((tag, _read_at(handle, table_offset, length)))
    return write_sfnt(tables)


@functools.lru_cache(maxsize=64)
def metrics_of(faces: tuple[HostFace, ...]):
    """A :class:`~ooxml_common.text.metrics.FontMetrics` built from installed ``faces``
    (:func:`~ooxml_common.fonts.embedded.metrics_from_faces`): their advances and legacy
    ``kern`` pairs."""
    from .embedded import metrics_from_faces

    return metrics_from_faces({(face.bold, face.italic): face_bytes(face) for face in faces})


def metrics(family: str | None, application: Application = POWERPOINT, *,
            dirs: tuple[tuple[str, Path], ...] | None = None):
    """A :class:`~ooxml_common.text.metrics.FontMetrics` built from the installed faces of
    ``family`` ``application`` lays it out with (:func:`find`, over ``dirs`` when given:
    :func:`user_search_dirs` for the application's own faces alone), or ``None`` where
    there are none or they cannot be read."""
    faces = find(family, application, dirs=dirs)
    if not faces:
        return None
    try:
        return metrics_of(faces)
    except Exception:  # noqa: BLE001 -- an unreadable face is one we do not have
        return None


def has_own_table(family: str) -> bool:
    """Whether the generated tables measure ``family`` with its own advance widths: a
    table of the very face (Aptos, Cambria), or a clone verified to the same widths
    (Calibri -> Carlito).  Those stay as they are -- they were measured against
    PowerPoint, kern pairs included.  A family reached only by stripping a weight word
    ("Aptos Light" -> Aptos), or measured from another face (Aptos Narrow, Yu Gothic), or
    not at all, is better measured from the installed face where there is one."""
    from ..text.fontmap import family_key, substitution_for

    row = substitution_for(family)
    if row is None or family_key(row.office) != family_key(family):
        return False
    return row.metric_compatible or family_key(row.metrics) == family_key(family)


def layout_metrics(families, application: Application = POWERPOINT, *, measure=None) -> dict:
    """``family key -> FontMetrics`` from the installed faces, for every family in
    ``families`` that this machine has and the generated tables do not measure as itself
    (:func:`has_own_table`): what :class:`~ooxml_common.text.measure.DefaultTextMeasurer`
    takes as ``extra_metrics``.  ``measure`` builds one family's table (:func:`metrics`
    for ``application`` by default)."""
    from ..text.fontmap import family_key

    measure = measure or (lambda family: metrics(family, application))
    out = {}
    for family in families:
        if not family or has_own_table(family):
            continue
        found = measure(family)
        if found is not None:
            out[family_key(family)] = found
    return out
