"""Parts kept as their compressed ZIP entries (ooxml_common.zipparts): read whole or
streamed, from any offset, checked as zipfile checks them -- and more strictly."""

import copy
import io
import os
import pickle
import random
import struct
import threading
import zipfile
import zlib

import pytest

from ooxml_common import zipparts
from ooxml_common import zipparts as zparts
from ooxml_common.opc import OpcPackage
from ooxml_common.zipparts import PartError, PartReader, PartStore, ZipPart, read_parts


def _zip(parts: dict, method=zipfile.ZIP_DEFLATED, directories=()) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", method) as archive:
        for name in directories:
            archive.writestr(name, b"")
        for name, data in parts.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _text(size: int, seed: int = 1) -> bytes:
    """Made-up XML rows that compress about as a sheet does."""
    rng = random.Random(seed)
    out = bytearray(b'<?xml version="1.0"?><rows>')
    n = 0
    while len(out) < size:
        n += 1
        out += b'<row r="%d"><c r="A%d" s="2"><v>%d</v></c></row>' % (n, n, rng.randrange(10 ** 6))
    return bytes(out[:size])


SIZES = [0, 1, 100, 70_000, 300_000]


@pytest.mark.parametrize("method", [zipfile.ZIP_DEFLATED, zipfile.ZIP_STORED])
@pytest.mark.parametrize("size", SIZES)
def test_a_part_reads_as_zipfile_reads_it(method, size):
    data = _zip({"xl/part.xml": _text(size)}, method)
    entries, parts = read_parts(data)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        expected = archive.read("xl/part.xml")
    part = parts.stored("xl/part.xml")
    assert isinstance(part, ZipPart) and part.size == size == parts.size("xl/part.xml")
    assert parts["xl/part.xml"] == expected == part.read() == b"".join(part.chunks())
    assert part.open().read() == expected
    assert [e.filename for e in entries] == ["xl/part.xml"]


@pytest.mark.parametrize("method", [zipfile.ZIP_DEFLATED, zipfile.ZIP_STORED])
def test_a_part_streams_from_any_offset(method, monkeypatch):
    monkeypatch.setattr(zipparts, "CHUNK", 4096)
    monkeypatch.setattr(zipparts, "SEEK_SPACING", 50_000)
    whole = _text(400_000)
    part = read_parts(_zip({"p.xml": whole}, method))[1].stored("p.xml")
    for offset in (0, 1, 4095, 4096, 123_457, 399_999, 400_000, 500_000):
        assert part.open(offset).read() == whole[offset:]
    # Once a reader from the start has read it all, later readers start from its notes.
    assert b"".join(part.chunks()) == whole
    if method == zipfile.ZIP_DEFLATED:
        assert part._seeks is not None and len(part._seeks) >= 7
    calls = []
    original = PartReader._more

    def counted(self):
        calls.append(1)
        return original(self)

    monkeypatch.setattr(PartReader, "_more", counted)
    for offset in (1, 49_999, 50_000, 150_001, 399_999, 400_000):
        calls.clear()
        reader = part.open(offset)
        if method == zipfile.ZIP_DEFLATED:   # began at the last note before it
            assert len(calls) <= 50_000 // 4096 + 2
        got = bytearray()
        while True:   # read in odd sizes, as a parser does
            piece = reader.read(777)
            if not piece:
                break
            got += piece
        assert bytes(got) == whole[offset:]


def test_readinto_and_read_sizes():
    whole = _text(10_000)
    reader = read_parts(_zip({"p.xml": whole}))[1].open("p.xml")
    buffer = bytearray(300)
    assert reader.readinto(buffer) == 300 and bytes(buffer) == whole[:300]
    assert reader.read(0) == b"" and reader.read(5) == whole[300:305]
    assert reader.read() == whole[305:] and reader.read(10) == b""
    assert reader.readable()


def _with_header(data: bytes, name: str, **fields) -> bytes:
    """``data`` with the named entry's central directory record changed (CRC, size)."""
    out = bytearray(data)
    at = data.find(b"PK\x01\x02")
    while at >= 0:
        size = struct.unpack_from("<H", data, at + 28)[0]
        if data[at + 46:at + 46 + size] == name.encode():
            if "crc" in fields:
                struct.pack_into("<L", out, at + 16, fields["crc"])
            if "size" in fields:
                struct.pack_into("<L", out, at + 24, fields["size"])
        at = data.find(b"PK\x01\x02", at + 4)
    return bytes(out)


@pytest.mark.parametrize("method", [zipfile.ZIP_DEFLATED, zipfile.ZIP_STORED])
def test_a_bad_crc_is_refused_when_a_read_completes(method):
    whole = _text(100_000)
    data = _with_header(_zip({"p.xml": whole}, method), "p.xml", crc=zlib.crc32(whole) ^ 1)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        with pytest.raises(zipfile.BadZipFile):
            archive.read("p.xml")
    part = read_parts(data)[1].stored("p.xml")   # opening reads no data
    with pytest.raises(PartError, match="CRC"):
        part.read()
    with pytest.raises(PartError, match="CRC"):
        part.open().read()
    reader = part.open()
    assert reader.read(1000) == whole[:1000]   # a read that stops early checks nothing
    assert isinstance(PartError("x"), zipfile.BadZipFile)


def test_a_part_that_expands_past_its_declared_size_is_refused_without_being_held(monkeypatch):
    """A bomb whose entry understates its size: the inflater is bounded by the declared
    size, so neither a whole read nor a stream makes more than a piece past it."""
    whole = b"\0" * 5_000_000
    data = _with_header(_zip({"p.bin": whole}), "p.bin", size=1000)
    part = read_parts(data)[1].stored("p.bin")
    assert part.size == 1000
    with pytest.raises(PartError, match="past its declared"):
        part.read()
    monkeypatch.setattr(zipparts, "CHUNK", 4096)
    reader = part.open()
    with pytest.raises(PartError, match="past its declared"):
        while reader.read(4096):
            assert reader._out <= 1000 + 4096


def test_a_part_shorter_than_declared_is_refused():
    whole = _text(50_000)
    data = _with_header(_zip({"p.xml": whole}), "p.xml", size=60_000)
    part = read_parts(data)[1].stored("p.xml")
    with pytest.raises(PartError, match="of a declared 60000"):
        part.read()
    with pytest.raises(PartError, match="of a declared 60000"):
        part.open().read()


def test_data_that_does_not_inflate_is_refused():
    whole = _text(50_000)
    data = bytearray(_zip({"p.xml": whole}))
    start = 30 + len(b"p.xml")
    for k in range(start + 10, start + 40):
        data[k] ^= 0xFF
    part = read_parts(bytes(data))[1].stored("p.xml")
    with pytest.raises(PartError):
        part.read()
    with pytest.raises(PartError):
        part.open().read()


def test_a_part_whose_data_runs_past_the_file_is_refused_at_open():
    data = _zip({"a.xml": _text(1000), "b.xml": _text(50_000, 2)})
    at = data.rfind(b"PK\x01\x02")    # b.xml's record: its compressed size past the end
    cut = bytearray(data)
    struct.pack_into("<L", cut, at + 20, len(data) * 2)
    with pytest.raises(zipfile.BadZipFile):
        read_parts(bytes(cut))


def test_an_encrypted_entry_is_refused_as_zipfile_refuses_it():
    data = bytearray(_zip({"p.xml": b"<a/>"}))
    at = data.find(b"PK\x01\x02")
    struct.pack_into("<H", data, at + 8, struct.unpack_from("<H", data, at + 8)[0] | 1)
    struct.pack_into("<H", data, 6, struct.unpack_from("<H", data, 6)[0] | 1)
    with zipfile.ZipFile(io.BytesIO(bytes(data))) as archive:
        with pytest.raises(RuntimeError) as expected:
            archive.read(archive.getinfo("p.xml"))
    with pytest.raises(RuntimeError) as got:
        read_parts(bytes(data))
    assert str(got.value) == str(expected.value)


def test_a_name_that_differs_from_its_local_header_is_refused():
    data = bytearray(_zip({"p.xml": b"<a/>"}))
    data[30] = ord("q")   # the local header's name
    with pytest.raises(zipfile.BadZipFile, match="differ"):
        read_parts(bytes(data))


def test_other_methods_are_read_at_once():
    data = _zip({"p.xml": _text(5000)}, zipfile.ZIP_BZIP2)
    entries, parts = read_parts(data)
    assert parts.stored("p.xml") == _text(5000)


def test_entries_names_and_the_last_of_a_name():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("ppt/media/", b"")
        archive.writestr("/ppt/a.xml", b"one")
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            archive.writestr("ppt/a.xml", b"two")
    entries, parts = read_parts(buffer.getvalue(), lambda name: name.lstrip("/"))
    assert [e.filename for e in entries] == ["/ppt/a.xml", "ppt/a.xml"]
    assert list(parts) == ["ppt/a.xml"] and parts["ppt/a.xml"] == b"two"


def test_a_source_is_read_from_bytes_a_path_or_a_file_from_its_start(tmp_path):
    data = _zip({"p.xml": _text(3000)})
    path = tmp_path / "p.zip"
    path.write_bytes(data)
    stream = io.BytesIO(data)
    stream.seek(17)
    for source in (data, bytearray(data), memoryview(data), str(path), path, stream):
        assert read_parts(source)[1]["p.xml"] == _text(3000)
    # Nothing keeps the file: it may go.
    parts = read_parts(str(path))[1]
    os.remove(path)
    assert parts["p.xml"] == _text(3000)


def test_the_store_answers_without_inflating(monkeypatch):
    parts = read_parts(_zip({"a.xml": _text(5000), "b.png": b"\x89PNG" + bytes(300)}))[1]
    inflated = []
    original = ZipPart.read

    def counted(self):
        inflated.append(self.name)
        return original(self)

    monkeypatch.setattr(ZipPart, "read", counted)
    assert "a.xml" in parts and len(parts) == 2 and sorted(parts) == ["a.xml", "b.png"]
    assert parts.size("a.xml") == 5000 and parts.size("nothing") is None
    copied = parts.copy()
    assert copied.stored("a.xml") is parts.stored("a.xml")
    assert copy.deepcopy(parts.stored("a.xml")) is parts.stored("a.xml")
    assert inflated == []
    assert parts["a.xml"] == _text(5000) and inflated == ["a.xml"]
    assert parts.get("a.xml") == _text(5000) and parts.get("none", b"x") == b"x"
    parts["a.xml"] = b"<new/>"     # replaced: bytes from now on, the copy keeps the part
    assert parts.stored("a.xml") == b"<new/>" and parts.size("a.xml") == 6
    assert copied["a.xml"] == _text(5000)
    assert parts.open("a.xml").read() == b"<new/>" and parts.open("nothing") is None
    del parts["b.png"]
    assert list(parts) == ["a.xml"] and parts != copied
    assert dict(copied) == {"a.xml": _text(5000), "b.png": b"\x89PNG" + bytes(300)}


def test_a_part_pickles_with_its_bytes():
    part = read_parts(_zip({"p.xml": _text(20_000)}))[1].stored("p.xml")
    again = pickle.loads(pickle.dumps(part))
    assert again.read() == part.read() and (again.size, again.crc) == (part.size, part.crc)


def test_a_part_is_read_by_threads_at_once(monkeypatch):
    monkeypatch.setattr(zipparts, "CHUNK", 8192)
    monkeypatch.setattr(zipparts, "SEEK_SPACING", 40_000)
    whole = _text(600_000, 5)
    part = read_parts(_zip({"p.xml": whole}))[1].stored("p.xml")
    errors = []

    def work(k):
        try:
            for round_ in range(5):
                offset = (k * 37_003 + round_ * 91_009) % 600_000
                assert part.open(offset).read() == whole[offset:]
                assert part.read() == whole
        except BaseException as exc:   # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(k,)) for k in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []


def test_a_reader_is_a_binary_file_lxml_and_zipfile_take():
    from xml.etree import ElementTree

    whole = _text(30_000)
    reader = read_parts(_zip({"p.xml": whole + b"</rows>"[:0]}))[1].open("p.xml")
    assert isinstance(reader, PartReader) and isinstance(reader, io.RawIOBase)
    with reader:
        assert reader.read(10) == whole[:10]
    assert reader.closed
    xml = b'<?xml version="1.0"?><rows>' + b"<r/>" * 5000 + b"</rows>"
    root = ElementTree.parse(read_parts(_zip({"x.xml": xml}))[1].open("x.xml")).getroot()
    assert len(root) == 5000


def test_a_package_keeps_its_parts_compressed():
    xml = (b'<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/'
           b'content-types"><Default Extension="xml" ContentType="application/xml"/></Types>')
    data = _zip({"[Content_Types].xml": xml, "word/document.xml": _text(80_000)})
    package = OpcPackage.open(data)
    assert isinstance(package.parts, PartStore)
    assert package.part_size("/word/document.xml") == 80_000
    assert package.open_part("word/document.xml").read() == _text(80_000) == package.read(
        "word/document.xml")
    assert package.part_entry("word/document.xml").size == 80_000
    assert package.open_part("nothing") is None and package.part_size("nothing") is None
    assert package.part_entry("nothing") is None
    made = OpcPackage.from_parts({"[Content_Types].xml": xml, "a.xml": b"<a/>"})
    assert made.open_part("a.xml").read() == b"<a/>" and made.part_size("a.xml") == 4
    assert made.part_entry("a.xml") is None and made.open_part("b.xml") is None


def test_an_entry_as_it_was_read_is_kept_for_copying():
    """A part's compressed data and what describes it (method, sizes, CRC-32, the flags
    that describe the data) while it is what was read; nothing once it is replaced."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("a.xml", _text(5000), zipfile.ZIP_DEFLATED, compresslevel=9)
        archive.writestr("b.xml", _text(4000, 3), zipfile.ZIP_BZIP2)
        archive.writestr("c.bin", b"stored", zipfile.ZIP_STORED)
    data = buffer.getvalue()
    parts = read_parts(data)[1]
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = {info.filename: info for info in archive.infolist()}
    for name in ("a.xml", "b.xml", "c.bin"):
        entry = parts.compressed(name)
        info = infos[name]
        assert entry is not None
        assert (entry.method, entry.size, entry.crc, entry.compressed_size) == (
            info.compress_type, info.file_size, info.CRC, info.compress_size)
        assert entry.flags == info.flag_bits & ~0x808
        start = info.header_offset + 30 + len(name.encode()) + len(info.extra)
        assert bytes(entry.compressed) == data[start:start + info.compress_size]
    assert isinstance(parts.compressed("b.xml"), zparts.RawEntry)
    copied = parts.copy()
    parts["b.xml"] = bytes(bytearray(parts["b.xml"]))   # equal bytes, another object: replaced
    parts["a.xml"] = b"<a/>"
    assert parts.compressed("a.xml") is None and parts.compressed("b.xml") is None
    assert copied.compressed("a.xml") is not None and copied.compressed("b.xml") is not None
    assert parts.compressed("nothing") is None
    again = pickle.loads(pickle.dumps(copied.compressed("a.xml")))
    assert again.flags == copied.compressed("a.xml").flags and again.read() == _text(5000)
