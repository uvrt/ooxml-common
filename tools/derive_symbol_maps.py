#!/usr/bin/env python3
"""Compile what each character of the Microsoft symbol faces *is*, in Unicode.

Symbol, Wingdings, Wingdings 2, Wingdings 3 and Webdings encode pictures, not letters:
a deck's ``<a:buChar char="q"/>`` in Wingdings is a shadowed box, its ``ü`` a check mark.
A renderer without the face draws the letter.  :mod:`ooxml_common.text.symbol_maps` --
written by this script -- says which Unicode character each code (0x20..0xFF, and its
private-use alias U+F020..U+F0FF) stands for, so the renderer can draw that instead
(:mod:`ooxml_common.text.symbol_fonts`).

Two published sources, both from the Unicode Consortium; facts about the encodings only,
no glyph and no font file:

* **Symbol**: Adobe's *Symbol Encoding to Unicode* table, as the Unicode Consortium
  publishes it (``Public/MAPPINGS/VENDORS/ADOBE/symbol.txt``, table version 1.0,
  2011-07-12; "Unicode, Inc. hereby grants the right to freely use the information supplied
  in this file in the creation of products supporting the Unicode Standard").  A code
  with two values takes the first; of the Corporate Use values, the serif and sans copyright,
  registered and trademark signs are taken as the plain signs and the rest left out.
* **Wingdings, Wingdings 2, Wingdings 3, Webdings**: *Updated proposal to add Wingdings
  and Webdings Symbols*, UTC L2/11-344 (Michel Suignard for the Unicode Consortium,
  2011-09-23), the proposal that encoded the four sets in Unicode 7.0.  Its tables give
  each glyph -- ``w-1113`` is Wingdings' code 113 -- a code point and a **character
  name**.  Some code points there are provisional and moved before Unicode 7.0 was
  published, so a glyph is taken by its *name* from the Unicode Character Database this
  Python ships (``unicodedata``), and the proposal's code point is kept only where it
  already bears that name.  A glyph whose name is not in the database (about one in
  eight, nearly all Webdings pictographs renamed on the way to 7.0) is left out.

The proposal is not redistributed here.  Download both and pass them in; their SHA-256
are checked first::

    curl -O https://www.unicode.org/L2/L2011/11344-wingdings.pdf
    curl -O https://www.unicode.org/Public/MAPPINGS/VENDORS/ADOBE/symbol.txt
    python3 tools/derive_symbol_maps.py --proposal 11344-wingdings.pdf --symbol symbol.txt
    python3 tools/derive_symbol_maps.py --check --proposal ... --symbol ...  # exit 1 if stale

Reading the PDF needs PyMuPDF (AGPL; a development tool, never a dependency).  The names
resolve against the running Python's Unicode database, so run it under the Python that
last wrote the module (the header says which) or expect a few more names to resolve.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "src" / "ooxml_common" / "text" / "symbol_maps.py"

PROPOSAL_SHA256 = "e317734036732156f9cc36a8f94f61fa8cf36fe6a4ce9017e998fa2b97e12847"
SYMBOL_SHA256 = "deb78ca840a429311939b9d165890873f71fb23ef223ceeb144a6c6d641a7e52"

#: The proposal's glyph-id prefix for each face (``w-0033`` is Webdings' code 33).
FACES = {"0": "webdings", "1": "wingdings", "2": "wingdings 2", "3": "wingdings 3"}

_ID = re.compile(r"^([0-3])(\d{3})(\s*[-])?$")
_HEX = re.compile(r"^([0-9A-F]{4,5})(?:\s+\S.*)?$")
_NAME = re.compile(r"^[A-Z][A-Z0-9 \-']*$")


def _verified(path: Path, digest: str) -> bytes:
    data = path.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != digest:
        sys.exit(f"{path}: SHA-256 {actual}, expected {digest}")
    return data


def proposal_entries(lines: list[str]) -> dict[str, tuple[list[str], str]]:
    """Glyph id (``"1113"``) -> (code points as written, character name), from the
    proposal's tables as PyMuPDF extracts them: an id line (with the glyph itself, a
    private-use character, after it), one or more code point lines, then the name over
    one or more upper-case lines.  Comments and cross-references follow and are skipped."""
    lines = [line.strip() for line in lines if line.strip()]

    def is_id(k: int):
        match = _ID.match(lines[k])
        if not match or not 33 <= int(match.group(2)) <= 255:
            return None
        if match.group(3) or (k + 1 < len(lines) and _HEX.match(lines[k + 1])):
            return match
        return None

    entries: dict[str, tuple[list[str], str]] = {}
    k = 0
    while k < len(lines):
        match = is_id(k)
        if not match:
            k += 1
            continue
        glyph = match.group(1) + match.group(2)
        j, codes, name = k + 1, [], []
        while j < len(lines) and j < k + 14:
            line = lines[j]
            if name and (not _NAME.match(line) or is_id(j)):
                break
            if not codes and is_id(j):
                break
            hexed = _HEX.match(line)
            if hexed and not name:
                id_like = _ID.match(line)
                if id_like and id_like.group(3):
                    break
                codes.append(hexed.group(1))
                j += 1
                continue
            if codes and _NAME.match(line) and len(line) > 1:
                name.append(line)
                j += 1
                continue
            j += 1
        if codes and name:
            full = "".join(part if part.endswith("-") else part + " " for part in name)
            entries.setdefault(glyph, (codes, re.sub(r"\s+", " ", full).strip()))
        k = max(j, k + 1)
    return entries


#: Misspellings in the proposal's names, corrected before they are looked up.
SPELLING = {"ISOCELES": "ISOSCELES", "TRIANGE": "TRIANGLE", "CARTDRIGE": "CARTRIDGE",
            "DOWNTWARDS": "DOWNWARDS"}


def _resolve(codes: list[str], name: str, by_name: dict[str, int]) -> int | None:
    """The final code point of a proposal entry: its own where that bears ``name``,
    else the one the database gives ``name`` (or a unique name ``name`` begins)."""
    name = " ".join(SPELLING.get(word, word) for word in name.split())
    proposed = int(codes[0], 16)
    actual = unicodedata.name(chr(proposed), "")
    if actual and (actual == name or actual.startswith(name + " ")):
        return proposed
    if name in by_name:
        return by_name[name]
    candidates = [full for full in by_name if full.startswith(name + " ")]
    return by_name[candidates[0]] if len(candidates) == 1 else None


def wingdings_maps(pdf: Path) -> dict[str, dict[int, int]]:
    import pymupdf  # development only; see the module docstring

    document = pymupdf.open(pdf)
    lines = [line for page in document for line in page.get_text().splitlines()]
    entries = proposal_entries(lines)
    by_name: dict[str, int] = {}
    for code_point in range(0x20, 0x110000):
        name = unicodedata.name(chr(code_point), "")
        if name:
            by_name.setdefault(name, code_point)
    maps: dict[str, dict[int, int]] = {face: {} for face in FACES.values()}
    for glyph, (codes, name) in sorted(entries.items()):
        code_point = _resolve(codes, name, by_name)
        if code_point is not None:
            maps[FACES[glyph[0]]][int(glyph[1:])] = code_point
    return maps


def symbol_map(text: str) -> dict[int, int]:
    """Adobe's table, one value per code.  A Corporate Use value (Adobe's serif and sans
    copyright, registered and trademark signs) is taken as the character its name
    describes without the style (``REGISTERED SIGN SERIF`` is U+00AE); the rest of them,
    the pieces of large brackets and radicals, are left out."""
    out: dict[int, int] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        unicode_value, code = int(fields[0], 16), int(fields[1], 16)
        if code in out:
            continue
        if 0xE000 <= unicode_value <= 0xF8FF:
            name = fields[2].lstrip("# ").replace(" SANS SERIF", "").replace(" SERIF", "")
            try:
                unicode_value = ord(unicodedata.lookup(name))
            except KeyError:
                continue
        out[code] = unicode_value
    return out


def render(maps: dict[str, dict[int, int]]) -> str:
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    lines = [
        '"""What each code of the Microsoft symbol faces stands for in Unicode.',
        "",
        "Generated by ``tools/derive_symbol_maps.py`` -- do not edit.  Symbol from Adobe's",
        "Symbol Encoding to Unicode table, Wingdings, Wingdings 2, Wingdings 3 and Webdings",
        "from the Unicode Consortium's proposal that encoded them (UTC L2/11-344), by",
        f"character name against Python {version}'s Unicode {unicodedata.unidata_version}"
        " database.  Facts about",
        "the encodings: no glyph and no font file.  Read through",
        ":mod:`ooxml_common.text.symbol_fonts`, which adds the drawing preferences.",
        '"""',
        "",
        "#: face (lower case) -> {code 0x20..0xFF: Unicode code point}.",
        "MAPS: dict[str, dict[int, int]] = {",
    ]
    for face in ("symbol", "wingdings", "wingdings 2", "wingdings 3", "webdings"):
        lines.append(f"    {face!r}: {{")
        for code, code_point in sorted(maps[face].items()):
            name = unicodedata.name(chr(code_point), "").lower()
            lines.append(f"        0x{code:02X}: 0x{code_point:04X},  # {name}")
        lines.append("    },")
    lines.append("}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--proposal", type=Path, required=True, help="11344-wingdings.pdf")
    parser.add_argument("--symbol", type=Path, required=True, help="Adobe's symbol.txt")
    parser.add_argument("--check", action="store_true", help="exit 1 if the module is stale")
    args = parser.parse_args()

    _verified(args.proposal, PROPOSAL_SHA256)
    symbol_text = _verified(args.symbol, SYMBOL_SHA256).decode("latin-1")
    maps = wingdings_maps(args.proposal)
    maps["symbol"] = symbol_map(symbol_text)
    text = render(maps)
    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != text:
            print(f"{TARGET} is stale; rerun without --check", file=sys.stderr)
            return 1
        return 0
    TARGET.write_text(text, encoding="utf-8")
    counts = ", ".join(f"{face} {len(table)}" for face, table in maps.items())
    print(f"wrote {TARGET}: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
