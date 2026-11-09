"""A package's parts kept as their compressed ZIP entries until they are needed.

An opened package held every part inflated, so a workbook whose sheet is 534 MB of XML in
a 70 MB file took more than a gigabyte before a cell was read.  Here each part stays the
compressed bytes its entry holds (a :class:`ZipPart`: a view of the file's bytes, never a
file handle -- the file may change or vanish once it is read), and is inflated when it is
read:

* :meth:`ZipPart.read` -- the whole part, as reading the ZIP gave it, inflated again at
  each call (nothing is cached: a caller that needs it often keeps it);
* :meth:`ZipPart.open` -- a binary file over the inflated bytes, inflated a piece at a
  time as it is read (a parser fed from it never holds the part whole), from the start or
  from any offset.

Either way what comes out is checked as :mod:`zipfile` checks it, and more strictly: never
more bytes than the entry declares (the inflater is bounded, so a part that expands past
its size is refused before it is held -- a package's limits are checked against the
declared sizes, :func:`ooxml_edit.tools.limits.check_package`), not fewer, and the CRC-32
of the whole part once a read reaches its end (:class:`PartError`, a
:class:`zipfile.BadZipFile`).  Stored and deflated entries are kept compressed -- every
Office package uses those two; any other method is read at once, as before.

:class:`PartStore` is the mapping of part path to bytes a package keeps: a value is a
:class:`ZipPart` until a part is replaced with bytes, and a lookup gives bytes either way.
:func:`read_parts` reads a ZIP into one, with the entries it was written with.

A :class:`ZipPart` is immutable and may be read from several threads at once: each read
and each reader has its own inflater.
"""

from __future__ import annotations

import io
import os
import struct
import zipfile
import zlib
from collections.abc import Iterator, MutableMapping
from typing import BinaryIO, Union

#: How many inflated bytes a reader makes at a time.
CHUNK = 1 << 16
#: How many compressed bytes are given to the inflater at a time.
_FEED = 1 << 16
#: A reader that inflates a part from its start notes where it is about every this many
#: inflated bytes (more apart in a part over 64 times as large), so that a later reader
#: started at an offset (:meth:`ZipPart.open`) inflates from the last note before it
#: rather than from the start.  A note is the inflater's state: some 40 KB.
SEEK_SPACING = 16 << 20
_SEEK_NOTES = 64

_LOCAL_HEADER = struct.Struct("<4s5H3L2H")


class PartError(zipfile.BadZipFile):
    """A part whose compressed data does not give what its ZIP entry declares: more or
    fewer bytes than its size, data that does not inflate, or another CRC-32."""


class ZipPart:
    """One ZIP entry's compressed bytes and what the entry declares of them: the part's
    ``name`` (as the archive spells it), its inflated ``size``, its ``crc`` and its
    compression ``method`` (:data:`zipfile.ZIP_STORED` or :data:`zipfile.ZIP_DEFLATED`)."""

    __slots__ = ("name", "size", "crc", "method", "_data", "_seeks")

    def __init__(self, name: str, data: "bytes | memoryview", method: int, size: int,
                 crc: int) -> None:
        if method not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise ValueError(f"compression method {method} is not kept compressed")
        self.name = name
        self._data = data if isinstance(data, memoryview) else memoryview(data)
        self.method = method
        self.size = size
        self.crc = crc
        #: The notes a reader from the start left (``(compressed offset, inflated offset,
        #: inflater, crc so far)``), once one reached the end and found the part whole.
        self._seeks: "tuple | None" = None

    @property
    def compressed_size(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return f"ZipPart({self.name!r}, {self.size} bytes, {len(self._data)} compressed)"

    # A part is immutable: copies are the part, and a pickle carries its bytes.
    def __copy__(self) -> "ZipPart":
        return self

    def __deepcopy__(self, memo) -> "ZipPart":
        return self

    def __reduce__(self):
        return (ZipPart, (self.name, bytes(self._data), self.method, self.size, self.crc))

    def read(self) -> bytes:
        """The whole part, inflated and checked (:class:`PartError`)."""
        data = self._data
        if self.method == zipfile.ZIP_STORED:
            if len(data) < self.size:
                raise PartError(f"{self.name}: {len(data)} bytes stored of {self.size}")
            out = bytes(data[:self.size])
        else:
            inflater = zlib.decompressobj(-15)
            try:
                # At most one byte more than declared: a part that would expand past its
                # size is refused without being held.
                out = inflater.decompress(data, self.size + 1)
            except zlib.error:
                raise PartError(f"{self.name}: its data does not inflate") from None
            if len(out) > self.size:
                raise PartError(f"{self.name}: inflates past its declared {self.size} bytes")
            if len(out) < self.size:
                raise PartError(f"{self.name}: inflates to {len(out)} bytes of a declared "
                                f"{self.size}")
        if zlib.crc32(out) != self.crc:
            raise PartError(f"{self.name}: bad CRC-32")
        return out

    def open(self, offset: int = 0) -> "PartReader":
        """A binary file over the part's inflated bytes from ``offset`` on, inflated a
        piece at a time as it is read (:class:`PartReader`)."""
        return PartReader(self, offset)

    def chunks(self, offset: int = 0) -> Iterator[bytes]:
        """The inflated bytes from ``offset`` on, a piece at a time (up to :data:`CHUNK`
        each), checked as :meth:`read` checks them once the last is given."""
        with self.open(offset) as reader:
            while True:
                piece = reader.read1()
                if not piece:
                    return
                yield piece


class PartReader(io.RawIOBase):
    """A :class:`ZipPart`'s inflated bytes as a binary file, read forward.  Reading to the
    end checks the size and, for a reader started at the start or at a note, the CRC-32
    (:class:`PartError`); a reader closed earlier checks what it inflated against the size
    only."""

    def __init__(self, part: ZipPart, offset: int = 0) -> None:
        super().__init__()
        if offset < 0:
            raise ValueError("a negative offset")
        self._part = part
        self._stored = part.method == zipfile.ZIP_STORED
        self._in = 0           # compressed bytes given to the inflater
        self._out = 0          # inflated bytes made
        self._crc: "int | None" = 0
        self._inflater = None if self._stored else zlib.decompressobj(-15)
        self._done = False
        self._piece = b""
        self._at = 0
        #: Notes taken on the way, for the part once this reader finds it whole.
        self._notes: "list | None" = None
        self._next_note = 0
        self._spacing = max(SEEK_SPACING, part.size // _SEEK_NOTES)
        if offset and not self._stored and part._seeks:
            note = None
            for candidate in part._seeks:
                if candidate[1] > offset:
                    break
                note = candidate
            if note is not None:
                self._in, self._out, inflater, self._crc = note
                self._inflater = inflater.copy()
        if not self._stored and self._in == 0 and part._seeks is None:
            self._notes = []
            self._next_note = self._spacing
        if self._stored:
            self._out = self._in = min(offset, part.size)
            self._crc = None if offset else 0
        self._skip(offset - self._out)

    def readable(self) -> bool:
        return True

    def _more(self) -> bytes:
        """The next inflated piece; ``b""`` at the end, where the part is checked."""
        if self._done:
            return b""
        part = self._part
        if self._stored:
            view = part._data[self._in:min(part.size, self._in + CHUNK)]
            if not view and self._in < part.size:
                raise PartError(f"{part.name}: {len(part._data)} bytes stored of {part.size}")
            out = bytes(view)
            self._in += len(out)
        else:
            out = self._inflate()
        if not out:
            self._finish()
            return b""
        self._out += len(out)
        if self._out > part.size:
            raise PartError(f"{part.name}: inflates past its declared {part.size} bytes")
        if self._crc is not None:
            self._crc = zlib.crc32(out, self._crc)
        return out

    def _inflate(self) -> bytes:
        inflater, data = self._inflater, self._part._data
        assert inflater is not None
        notes = self._notes
        if notes is not None and self._out >= self._next_note and len(notes) < _SEEK_NOTES:
            notes.append((self._in, self._out, inflater.copy(), self._crc))
            self._next_note = self._out + self._spacing
        given: "bytes | memoryview"
        while not inflater.eof:
            tail = inflater.unconsumed_tail
            if tail:
                given = tail
            elif self._in < len(data):
                given = data[self._in:self._in + _FEED]
                self._in += len(given)
            else:
                given = b""
            try:
                out = inflater.decompress(given, CHUNK)
            except zlib.error:
                raise PartError(f"{self._part.name}: its data does not inflate") from None
            if out:
                return out
            if not given:
                break
        return b""

    def _finish(self) -> None:
        part = self._part
        self._done = True
        if self._out != part.size:
            raise PartError(f"{part.name}: inflates to {self._out} bytes of a declared "
                            f"{part.size}")
        if self._crc is not None and self._crc != part.crc:
            raise PartError(f"{part.name}: bad CRC-32")
        if self._notes is not None and part._seeks is None and self._crc is not None:
            part._seeks = tuple(self._notes)
        self._notes = None

    def _skip(self, count: int) -> None:
        while count > 0:
            piece = self._more()
            if not piece:
                return
            if len(piece) > count:
                self._piece, self._at = piece, count
                return
            count -= len(piece)

    def read1(self, size: int = -1) -> bytes:
        """At most ``size`` bytes (any number when negative), from one inflated piece:
        ``b""`` only at the end."""
        if self._at >= len(self._piece):
            self._piece, self._at = self._more(), 0
            if not self._piece:
                return b""
        piece, at = self._piece, self._at
        if (size is None or size < 0 or at + size >= len(piece)):
            self._piece, self._at = b"", 0
            return piece if at == 0 else piece[at:]
        self._at = at + size
        return piece[at:at + size]

    def read(self, size: "int | None" = -1) -> bytes:
        if size is None or size < 0:
            return self.readall()
        if size == 0:
            return b""
        return self.read1(size)

    def readall(self) -> bytes:
        pieces: list[bytes] = []
        while True:
            piece = self.read1()
            if not piece:
                return b"".join(pieces)
            pieces.append(piece)

    def readinto(self, buffer) -> int:
        view = memoryview(buffer).cast("B")
        piece = self.read1(len(view))
        view[:len(piece)] = piece
        return len(piece)


#: A part as a :class:`PartStore` keeps it.
Stored = Union[ZipPart, bytes]


class PartStore(MutableMapping):
    """Part path -> bytes, each part kept as its :class:`ZipPart` until it is replaced:
    a lookup inflates it (not kept), :meth:`open` streams it, :meth:`size` and
    :meth:`stored` answer without inflating.  Assigning bytes (or a :class:`ZipPart`)
    replaces a part; :meth:`copy` shares the parts, compressed or not."""

    __slots__ = ("_items",)

    def __init__(self, items=None) -> None:
        self._items: dict[str, Stored] = dict(items) if items else {}

    def __getitem__(self, path: str) -> bytes:
        value = self._items[path]
        return value.read() if isinstance(value, ZipPart) else value

    def get(self, path, default=None):
        value = self._items.get(path, default)
        return value.read() if isinstance(value, ZipPart) else value

    def __setitem__(self, path: str, value: Stored) -> None:
        self._items[path] = value

    def __delitem__(self, path: str) -> None:
        del self._items[path]

    def __contains__(self, path: object) -> bool:
        return path in self._items

    def __iter__(self) -> Iterator[str]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __repr__(self) -> str:
        return f"PartStore({len(self._items)} parts)"

    def stored(self, path: str) -> "Stored | None":
        """The part as kept -- its :class:`ZipPart`, or its bytes -- without inflating it."""
        return self._items.get(path)

    def size(self, path: str) -> "int | None":
        """The part's size in bytes, without inflating it; ``None`` for no such part."""
        value = self._items.get(path)
        if value is None:
            return None
        return value.size if isinstance(value, ZipPart) else len(value)

    def open(self, path: str, offset: int = 0) -> "BinaryIO | None":
        """A binary file over the part's bytes from ``offset`` on, inflated a piece at a
        time when it is still compressed; ``None`` for no such part."""
        value = self._items.get(path)
        if value is None:
            return None
        if isinstance(value, ZipPart):
            return value.open(offset)  # type: ignore[return-value]
        stream = io.BytesIO(value)
        stream.seek(offset)
        return stream

    def copy(self) -> "PartStore":
        return PartStore(self._items)


def read_parts(source: "str | os.PathLike[str] | bytes | BinaryIO", normalize=None
               ) -> "tuple[list[zipfile.ZipInfo], PartStore]":
    """A ZIP's file entries (directories left out) and its parts, each kept compressed: by
    the entry's name, or by ``normalize(name)`` when given (the last entry of a name
    wins, as reading each in turn into a dict did).

    ``source`` is read whole into memory (a path, bytes or a binary file, read from its
    start) and nothing keeps a handle on it.  Every entry is checked as :mod:`zipfile`
    checks one it is asked to read -- its local header, its name, overlaps, encryption --
    and a part that is neither stored nor deflated is read at once; the data of the
    others is checked as it is read (:class:`ZipPart`)."""
    if isinstance(source, (bytes, bytearray, memoryview)):
        data = bytes(source)
    elif isinstance(source, (str, os.PathLike)):
        with open(os.fspath(source), "rb") as handle:
            data = handle.read()
    else:
        if hasattr(source, "seek"):
            source.seek(0)
        data = source.read()
        if not isinstance(data, bytes):
            data = bytes(data)
    view = memoryview(data)
    parts = PartStore()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = [info for info in archive.infolist() if not info.is_dir()]
        for info in entries:
            name = normalize(info.filename) if normalize is not None else info.filename
            if info.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED) \
                    and not info.flag_bits & 0x1:
                # Opening it checks the entry as a read does, without inflating anything.
                archive.open(info).close()
                header = _LOCAL_HEADER.unpack_from(data, info.header_offset)
                start = info.header_offset + _LOCAL_HEADER.size + header[9] + header[10]
                end = start + info.compress_size
                if end > len(data):
                    raise zipfile.BadZipFile(f"{info.filename}: its data is cut short")
                parts[name] = ZipPart(info.filename, view[start:end], info.compress_type,
                                      info.file_size, info.CRC)
            else:
                parts[name] = archive.read(info)
    return entries, parts
