"""What a file's bytes are: the package kind its main part declares, or why it is none
(production round 44, R63a: a host routing an upload to the right library)."""

from __future__ import annotations

import io
import struct
import zipfile

import pytest

from ooxml_common.cfb import compound_file_names
from ooxml_common.kinds import (IDENTIFY_LIMITS, KINDS, IdentifyLimits, identify_package,
                                package_kind)

REL_MAIN = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
CT = "application/vnd.openxmlformats-officedocument."


def package(main: str = "xl/workbook.xml", content_type: str = CT + "spreadsheetml.sheet.main+xml",
            *, rels: bool = True, extra: dict | None = None, types: bytes | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", types if types is not None else (
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
            'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
            f'<Override PartName="/{main}" ContentType="{content_type}"/></Types>'))
        if rels:
            archive.writestr("_rels/.rels", (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                f'relationships"><Relationship Id="rId1" Type="{REL_MAIN}" Target="{main}"/>'
                '</Relationships>'))
        archive.writestr(main, "<x/>")
        for name, data in (extra or {}).items():
            archive.writestr(name, data)
    return buffer.getvalue()


def compound_file(names) -> bytes:
    """A minimal compound file ([MS-CFB] 2.2): 512-byte sectors, one FAT sector and a
    directory holding a root entry and an empty stream per name."""
    entries = [("Root Entry", 5)] + [(name, 2) for name in names]
    directory_sectors = -(-len(entries) // 4)
    header = bytearray(512)
    header[0:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    struct.pack_into("<HHHHH", header, 0x18, 0x3E, 3, 0xFFFE, 9, 6)
    struct.pack_into("<IIIIIIII", header, 0x2C, 1, 1, 0, 4096, 0xFFFFFFFE, 0, 0xFFFFFFFE, 0)
    struct.pack_into("<109I", header, 0x4C, 0, *([0xFFFFFFFF] * 108))
    fat = [0xFFFFFFFD] + [n + 1 for n in range(1, directory_sectors)] + [0xFFFFFFFE]
    fat += [0xFFFFFFFF] * (128 - len(fat))
    directory = bytearray(512 * directory_sectors)
    for index, (name, kind) in enumerate(entries):
        encoded = name.encode("utf-16-le") + b"\x00\x00"
        directory[index * 128:index * 128 + len(encoded)] = encoded
        struct.pack_into("<HB", directory, index * 128 + 0x40, len(encoded), kind)
    return bytes(header) + struct.pack("<128I", *fat) + bytes(directory)


@pytest.mark.parametrize("name", sorted(KINDS))
def test_every_kind_is_told_by_its_main_part(name):
    kind = KINDS[name]
    main = {"word": "word/document.xml", "powerpoint": "ppt/presentation.xml",
            "excel": "xl/workbook.xml"}[kind.application]
    found = identify_package(package(main, kind.content_type))
    assert found.kind == name and bool(found) and found.reason is None
    assert found.main_part == main and found.content_type == kind.content_type
    assert package_kind(package(main, kind.content_type)) == name


def test_bytes_a_path_and_a_file_object_alike(tmp_path):
    data = package()
    path = tmp_path / "book.bin"           # the extension says nothing: the content does
    path.write_bytes(data)
    assert package_kind(path) == package_kind(str(path)) == package_kind(data) == "xlsx"
    assert package_kind(bytearray(data)) == package_kind(memoryview(data)) == "xlsx"
    handle = io.BytesIO(b"xx" + data)
    handle.seek(2)
    assert package_kind(handle) == "xlsx"
    assert handle.tell() == 2              # put back where it stood
    with pytest.raises(TypeError):
        identify_package(12)


def test_the_main_part_is_the_one_the_package_relationship_names():
    # a content type for the main part given by a Default, and a ./ target
    types = ('<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             f'<Default Extension="xml" ContentType="{CT}wordprocessingml.document.main+xml"/>'
             '</Types>').encode()
    data = package("word/document.xml", types=types)
    assert package_kind(data) == "docx"
    # no _rels/.rels: the one main type among the overrides
    assert package_kind(package(rels=False)) == "xlsx"


def test_legacy_binary_files_are_named():
    xls = identify_package(compound_file(["Workbook"]))
    assert xls.kind is None and xls.legacy == "xls" and ".xls" in xls.reason
    assert identify_package(compound_file(["Book"])).legacy == "xls"           # BIFF5
    assert identify_package(b"\x09\x04\x06\x00" + bytes(20)).legacy == "xls"   # BIFF4
    doc = identify_package(compound_file(["WordDocument", "1Table"]))
    assert doc.legacy == "doc" and ".doc" in doc.reason and "WordDocument" in doc.reason
    ppt = identify_package(compound_file(["PowerPoint Document"]))
    assert ppt.legacy == "ppt" and ".ppt" in ppt.reason
    encrypted = identify_package(compound_file(["EncryptedInfo", "EncryptedPackage"]))
    assert encrypted.legacy == "encrypted" and "password" in encrypted.reason
    other = identify_package(compound_file(["Something"]))
    assert other.legacy == "compound"
    damaged = identify_package(compound_file(["Workbook"])[:600])
    assert damaged.kind is None and "cannot be read" in damaged.reason
    assert compound_file_names(compound_file(["Workbook"])) >= {"Root Entry", "Workbook"}


def test_other_files_are_named_by_their_first_bytes():
    assert identify_package(b"").reason == "an empty file"
    assert identify_package(b"%PDF-1.7\n...").legacy == "pdf"
    assert identify_package(b"{\\rtf1\\ansi ...}").legacy == "rtf"
    xml = (b'<?xml version="1.0"?><Workbook xmlns="urn:schemas-microsoft-com:office:'
           b'spreadsheet"/>')
    assert identify_package(xml).legacy == "xml2003"
    assert identify_package(b"Item,Count\nBolts,4\n").reason == \
        "neither a ZIP package nor a compound file"
    odf = io.BytesIO()
    with zipfile.ZipFile(odf, "w") as archive:
        archive.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet")
    assert identify_package(odf.getvalue()).legacy == "odf"


def test_packages_of_no_kind_here():
    xlsb = identify_package(package("xl/workbook.bin",
                                    "application/vnd.ms-excel.sheet.binary.macroEnabled.main"))
    assert xlsb.kind is None and ".xlsb" in xlsb.reason
    show = identify_package(package("ppt/presentation.xml",
                                    CT + "presentationml.slideshow.main+xml"))
    assert show.kind is None and ".ppsx" in show.reason
    odd = identify_package(package(content_type="application/x-made-up+xml"))
    assert odd.kind is None and "application/x-made-up+xml" in odd.reason
    plain = io.BytesIO()
    with zipfile.ZipFile(plain, "w") as archive:
        archive.writestr("notes.txt", "hello")
    assert "no [Content_Types].xml" in identify_package(plain.getvalue()).reason
    assert "cannot be read" in identify_package(b"PK\x03\x04" + bytes(40)).reason
    assert "cannot be read as XML" in identify_package(package(types=b"<Types")).reason


def test_no_entity_is_expanded():
    types = (b'<?xml version="1.0"?><!DOCTYPE Types [<!ENTITY a "aaaaaaaaaa">]>'
             b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             b'<Default Extension="xml" ContentType="&a;"/></Types>')
    found = identify_package(package(types=types))
    assert found.kind is None and "cannot be read as XML" in found.reason


def test_the_limits_hold():
    data = package()
    small = IdentifyLimits(max_package_bytes=len(data) - 1)
    over = identify_package(data, small)
    assert over.kind is None and over.limit and "size limit" in over.reason
    many = package(extra={f"x/{n}.xml": "<x/>" for n in range(10)})
    assert identify_package(many, IdentifyLimits(max_parts=5)).limit
    big = package(types=b"<Types>" + b" " * 5000 + b"</Types>")
    found = identify_package(big, IdentifyLimits(max_part_bytes=4096))
    assert found.limit and "[Content_Types].xml is over the size limit" in found.reason
    bomb = package(types=b"<Types>" + b" " * 300_000 + b"</Types>")
    found = identify_package(bomb)
    assert found.limit and "expansion" in found.reason
    assert IDENTIFY_LIMITS.max_package_bytes == 50 * 1024 * 1024
    assert IDENTIFY_LIMITS.max_parts == 2000


def test_a_file_over_the_limit_is_not_read(tmp_path):
    path = tmp_path / "big.xlsx"
    path.write_bytes(package())
    assert identify_package(path, IdentifyLimits(max_package_bytes=10)).limit
    handle = io.BytesIO(package())
    assert identify_package(handle, IdentifyLimits(max_package_bytes=10)).limit
