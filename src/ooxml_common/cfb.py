"""The names in a compound file's directory ([MS-CFB]), read without reading any stream.

Office's binary formats (``.xls``, ``.doc``, ``.ppt``) and an encrypted OOXML package are
compound files: a small FAT file system in one file.  What a compound file holds is told by
the names of its streams -- a ``Workbook`` (or BIFF5's ``Book``) stream is an Excel 97-2003
workbook ([MS-XLS] 2.1.2), ``WordDocument`` a Word 97-2003 document ([MS-DOC] 2.1.1),
``PowerPoint Document`` a PowerPoint 97-2003 presentation ([MS-PPT] 2.1.1), and an
``EncryptedPackage`` stream an OOXML package encrypted with a password ([MS-OFFCRYPTO]
2.3.4.4) -- so :func:`compound_file_names` walks the header, the FAT and the directory
chain, bounded by the file's own size, and nothing else.
"""

from __future__ import annotations

import struct

#: [MS-CFB] 2.2: the compound file header's signature.
CFB_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

_FREE = 0xFFFFFFFF
_END_OF_CHAIN = 0xFFFFFFFE


def compound_file_names(data: bytes) -> set[str]:
    """The names of the storages and streams in a compound file's directory ([MS-CFB] 2.2,
    2.3, 2.6).  ``ValueError`` when the header or the sector chains do not hold together."""
    if len(data) < 512 or not data.startswith(CFB_SIGNATURE):
        raise ValueError("no compound file header")
    shift = struct.unpack_from("<H", data, 0x1E)[0]
    if shift not in (9, 12):
        raise ValueError("an unknown sector size")
    size = 1 << shift
    sectors = max((len(data) - size) // size, 0)

    def sector(number: int) -> bytes:
        if number >= sectors:
            raise ValueError("a sector past the end of the file")
        start = (number + 1) * size
        return data[start:start + size]

    # The FAT's own sectors: the header's 109 DIFAT entries, then the DIFAT chain.
    fat_count, first_directory = struct.unpack_from("<II", data, 0x2C)
    next_difat, difat_count = struct.unpack_from("<II", data, 0x44)
    fat_sectors = [n for n in struct.unpack_from("<109I", data, 0x4C) if n != _FREE]
    per_sector = size // 4
    for _ in range(min(difat_count, sectors)):
        if next_difat in (_END_OF_CHAIN, _FREE):
            break
        entries = struct.unpack(f"<{per_sector}I", sector(next_difat))
        fat_sectors.extend(n for n in entries[:-1] if n != _FREE)
        next_difat = entries[-1]
    fat_sectors = fat_sectors[:fat_count] if fat_count else fat_sectors
    fat: list[int] = []
    for number in fat_sectors:
        fat.extend(struct.unpack(f"<{per_sector}I", sector(number)))

    names: set[str] = set()
    number, seen = first_directory, 0
    while number != _END_OF_CHAIN:
        seen += 1
        if seen > sectors or number >= len(fat):
            raise ValueError("a broken directory chain")
        block = sector(number)
        for offset in range(0, size, 128):
            length, kind = struct.unpack_from("<HB", block, offset + 0x40)
            if kind in (1, 2, 5) and 2 <= length <= 64:
                names.add(block[offset:offset + length - 2].decode("utf-16-le", "replace"))
        number = fat[number]
    return names


__all__ = ["CFB_SIGNATURE", "compound_file_names"]
