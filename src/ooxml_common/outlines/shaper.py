"""Shaping a left-to-right run as harfrust (HarfBuzz's Rust port, behind resvg) shapes
it with its default features, for the scripts this package outlines.

What it does: characters to glyphs through the face's character map (a missing space
drawn with the space glyph at HarfBuzz's fallback widths), then the ``GSUB`` lookups of
``ccmp``, ``locl``, ``rlig``, ``calt``, ``clig``, ``liga`` and ``rclt`` (single,
multiple, ligature, contextual and chaining substitutions), then advances (``hmtx`` at
the instance), then the ``GPOS`` lookups of ``kern``, ``mark``, ``mkmk``, ``dist``,
``abvm`` and ``blwm`` (single, pair, mark-to-base, mark-to-ligature, mark-to-mark,
contextual and chaining positioning, with variation deltas) -- or, for a face whose
``GPOS`` has no ``kern`` feature, its legacy ``kern`` table -- marks zeroed by their
``GDEF`` class, and default-ignorable characters hidden (the space glyph at no width).
Lookups run in their index order over the whole run, each skipping the glyphs its flags
say to.

What it does not: right-to-left runs and the scripts HarfBuzz gives a shaper of their
own (Arabic, the Indic scripts, Thai, Khmer, Myanmar...) -- :func:`shapeable` says no,
and the caller keeps the text as text.  Nor cursive attachment, contextual alternates
of a reverse chaining lookup, or Unicode normalisation.
"""

from __future__ import annotations

import struct
import unicodedata
from dataclasses import dataclass, field
from typing import Sequence

from .face import OutlineFace

__all__ = ["Glyph", "shape", "shapeable"]

_GSUB_FEATURES = (b"rvrn", b"ccmp", b"locl", b"rlig", b"ltra", b"ltrm", b"calt", b"clig", b"liga", b"rclt")
_GPOS_FEATURES = (b"kern", b"mark", b"mkmk", b"dist", b"abvm", b"blwm", b"curs")


@dataclass
class Glyph:
    """One shaped glyph: its id, the byte offset of its cluster in the run's UTF-8, and
    its advance and offsets in font units."""

    id: int
    cluster: int
    x_advance: int = 0
    x_offset: int = 0
    y_offset: int = 0
    #: GDEF class (1 base, 2 ligature, 3 mark, 4 component), or 0.
    klass: int = 0
    lig_components: int = 1
    #: Attached to the glyph this many places before (mark positioning).
    attach: int = 0
    codepoint: int = 0
    extras: dict = field(default_factory=dict)


# --------------------------------------------------------------------------------------
# Which runs this module shapes as harfrust does
# --------------------------------------------------------------------------------------

def _complex(code: int) -> bool:
    """Characters of scripts HarfBuzz shapes with a shaper of their own, or that are
    written right to left."""
    return (
        0x0590 <= code <= 0x08FF          # Hebrew, Arabic, Syriac, Thaana, NKo, ...
        or 0x0900 <= code <= 0x0DFF       # Indic
        or 0x0E00 <= code <= 0x0EFF       # Thai, Lao
        or 0x0F00 <= code <= 0x109F       # Tibetan, Myanmar
        or 0x1700 <= code <= 0x18AF       # Philippine scripts, Khmer, Mongolian
        or 0x1900 <= code <= 0x1CFF       # Limbu .. Vedic
        or 0x200E <= code <= 0x200F       # directional marks
        or 0x202A <= code <= 0x202E
        or 0x2066 <= code <= 0x2069
        or 0xA800 <= code <= 0xABFF       # Syloti Nagri .. Meetei Mayek
        or 0xFB1D <= code <= 0xFDFF       # Hebrew and Arabic presentation forms
        or 0xFE70 <= code <= 0xFEFF and code != 0xFEFF
        or 0x10800 <= code <= 0x10FFF     # right-to-left historic scripts
        or 0x11000 <= code <= 0x11FFF     # Brahmi and other Indic historic scripts
        or 0x1E800 <= code <= 0x1EFFF
    )


def shapeable(text: str) -> bool:
    """Whether :func:`shape` shapes ``text`` as harfrust would."""
    return not any(_complex(ord(char)) for char in text)


def _script_tags(text: str) -> tuple[bytes, ...]:
    """The OpenType script tags HarfBuzz tries for the first character of ``text`` with
    a script of its own (``guess_segment_properties``)."""
    for char in text:
        code = ord(char)
        cat = unicodedata.category(char)
        if cat[0] in "ZPSNC" or cat in ("Lm", "Mn", "Me", "Mc"):
            if not (0x3040 <= code <= 0x30FF):  # kana marks are Lm but have a script
                continue
        if code < 0x0250 or 0x1E00 <= code <= 0x1EFF or 0x2C60 <= code <= 0x2C7F or 0xA720 <= code <= 0xA7FF \
                or 0xFF21 <= code <= 0xFF5A:
            return (b"latn",)
        if 0x0370 <= code <= 0x03FF or 0x1F00 <= code <= 0x1FFF:
            return (b"grek",)
        if 0x0400 <= code <= 0x052F:
            return (b"cyrl",)
        if 0x3040 <= code <= 0x30FF or 0x31F0 <= code <= 0x31FF or 0xFF66 <= code <= 0xFF9F:
            return (b"kana",)
        if 0xAC00 <= code <= 0xD7AF or 0x1100 <= code <= 0x11FF or 0x3130 <= code <= 0x318F:
            return (b"hang",)
        if 0x2E80 <= code <= 0x2FDF or 0x3400 <= code <= 0x9FFF or 0xF900 <= code <= 0xFAFF or code >= 0x20000:
            return (b"hani",)
        if 0x0530 <= code <= 0x058F:
            return (b"armn",)
        if 0x10A0 <= code <= 0x10FF:
            return (b"geor",)
        return ()
    return ()


# --------------------------------------------------------------------------------------
# Layout tables
# --------------------------------------------------------------------------------------

def _coverage(data: bytes, at: int) -> dict[int, int]:
    fmt = struct.unpack_from(">H", data, at)[0]
    out: dict[int, int] = {}
    if fmt == 1:
        count = struct.unpack_from(">H", data, at + 2)[0]
        for i, glyph in enumerate(struct.unpack_from(f">{count}H", data, at + 4)):
            out[glyph] = i
    elif fmt == 2:
        count = struct.unpack_from(">H", data, at + 2)[0]
        for i in range(count):
            start, end, index = struct.unpack_from(">HHH", data, at + 4 + 6 * i)
            for glyph in range(start, end + 1):
                out[glyph] = index + glyph - start
    return out


def _class_def(data: bytes, at: int) -> dict[int, int]:
    fmt = struct.unpack_from(">H", data, at)[0]
    out: dict[int, int] = {}
    if fmt == 1:
        start, count = struct.unpack_from(">HH", data, at + 2)
        for i, value in enumerate(struct.unpack_from(f">{count}H", data, at + 6)):
            if value:
                out[start + i] = value
    elif fmt == 2:
        count = struct.unpack_from(">H", data, at + 2)[0]
        for i in range(count):
            start, end, value = struct.unpack_from(">HHH", data, at + 4 + 6 * i)
            if value:
                for glyph in range(start, end + 1):
                    out[glyph] = value
    return out


class _Gdef:
    def __init__(self, face: OutlineFace) -> None:
        self.classes: dict[int, int] | None = None
        self.mark_classes: dict[int, int] = {}
        self.mark_sets: list[set[int]] = []
        data = face.table(b"GDEF")
        if not data:
            return
        major, minor, class_at, _attach, _lig, mark_at = struct.unpack_from(">HHHHHH", data, 0)
        if class_at:
            self.classes = _class_def(data, class_at)
        if mark_at:
            self.mark_classes = _class_def(data, mark_at)
        if (major, minor) >= (1, 2) and len(data) >= 14:
            sets_at = struct.unpack_from(">H", data, 12)[0]
            if sets_at:
                count = struct.unpack_from(">H", data, sets_at + 2)[0]
                for i in range(count):
                    offset = struct.unpack_from(">I", data, sets_at + 4 + 4 * i)[0]
                    self.mark_sets.append(set(_coverage(data, sets_at + offset)))


def _is_mark_char(code: int) -> bool:
    return unicodedata.category(chr(code)) in ("Mn", "Me", "Mc")


class _Table:
    """A GSUB or GPOS table: its lookups for a script, default language, and features."""

    def __init__(self, face: OutlineFace, tag: bytes) -> None:
        self.data = face.table(tag) or b""
        self.ok = len(self.data) >= 10
        self._coverages: dict[int, dict[int, int]] = {}
        self._classes: dict[int, dict[int, int]] = {}
        if not self.ok:
            return
        self.script_at, self.feature_at, self.lookup_at = struct.unpack_from(">HHH", self.data, 4)

    def coverage(self, at: int) -> dict[int, int]:
        found = self._coverages.get(at)
        if found is None:
            found = self._coverages[at] = _coverage(self.data, at)
        return found

    def class_def(self, at: int) -> dict[int, int]:
        found = self._classes.get(at)
        if found is None:
            found = self._classes[at] = _class_def(self.data, at)
        return found

    def _lang_sys(self, scripts: tuple[bytes, ...]) -> int | None:
        data = self.data
        at = self.script_at
        count = struct.unpack_from(">H", data, at)[0]
        found: dict[bytes, int] = {}
        for i in range(count):
            tag = data[at + 2 + 6 * i:at + 6 + 6 * i]
            found[tag] = at + struct.unpack_from(">H", data, at + 6 + 6 * i)[0]
        for tag in (*scripts, b"DFLT", b"dflt", b"latn"):
            if tag in found:
                script = found[tag]
                default = struct.unpack_from(">H", data, script)[0]
                return script + default if default else None
        return None

    def feature_tags(self) -> set[bytes]:
        if not self.ok:
            return set()
        at = self.feature_at
        count = struct.unpack_from(">H", self.data, at)[0]
        return {self.data[at + 2 + 6 * i:at + 6 + 6 * i] for i in range(count)}

    def first_glyphs(self, index: int) -> "set[int] | frozenset[int] | None":
        """The glyphs lookup ``index`` can start at (its subtables' first coverage), or
        ``None`` where that is not read: a lookup is skipped where no glyph is among them."""
        cache = self.__dict__.setdefault("_first", {})
        if index in cache:
            return cache[index]
        kind, _flag, subtables, _set = self.lookup(index)
        data = self.data
        found: set[int] | None = set()
        try:
            for at in subtables:
                fmt = struct.unpack_from(">H", data, at)[0]
                contextual = (kind in (5, 6) and self.is_gsub) or (kind in (7, 8) and not self.is_gsub)
                if contextual and fmt == 3:
                    if kind in (6, 8):
                        back = struct.unpack_from(">H", data, at + 2)[0]
                        pos = at + 4 + 2 * back
                        count = struct.unpack_from(">H", data, pos)[0]
                        offset = struct.unpack_from(">H", data, pos + 2)[0] if count else 0
                    else:
                        count = struct.unpack_from(">H", data, at + 2)[0]
                        offset = struct.unpack_from(">H", data, at + 6)[0] if count else 0
                    if not offset:
                        found = None
                        break
                    found.update(self.coverage(at + offset))  # type: ignore[union-attr]
                elif (self.is_gsub and kind in (1, 2, 3, 4, 5, 6)) or (not self.is_gsub and kind in (1, 2, 4, 5, 6, 7, 8)):
                    found.update(self.coverage(at + struct.unpack_from(">H", data, at + 2)[0]))  # type: ignore[union-attr]
                else:
                    found = None
                    break
        except struct.error:
            found = None
        result = frozenset(found) if found is not None else None
        cache[index] = result
        return result

    def lookups(self, scripts: tuple[bytes, ...], features: Sequence[bytes]) -> list[int]:
        if not self.ok:
            return []
        cache = self.__dict__.setdefault("_lookup_lists", {})
        key = (scripts, tuple(features))
        if key not in cache:
            cache[key] = self._lookups(scripts, features)
        return cache[key]

    def _lookups(self, scripts: tuple[bytes, ...], features: Sequence[bytes]) -> list[int]:
        lang = self._lang_sys(scripts)
        if lang is None:
            return []
        data = self.data
        required, count = struct.unpack_from(">HH", data, lang + 2)
        indices = list(struct.unpack_from(f">{count}H", data, lang + 6))
        if required != 0xFFFF:
            indices.append(required)
        wanted = set(features)
        out: set[int] = set()
        feature_count = struct.unpack_from(">H", data, self.feature_at)[0]
        for index in indices:
            if index >= feature_count:
                continue
            record = self.feature_at + 2 + 6 * index
            tag = data[record:record + 4]
            if tag not in wanted and index != required:
                continue
            feature = self.feature_at + struct.unpack_from(">H", data, record + 4)[0]
            lookup_count = struct.unpack_from(">H", data, feature + 2)[0]
            out.update(struct.unpack_from(f">{lookup_count}H", data, feature + 4))
        return sorted(out)

    def lookup(self, index: int) -> tuple[int, int, list[int], int | None]:
        """``(type, flag, subtable offsets, mark filtering set)``, extensions resolved."""
        data = self.data
        count = struct.unpack_from(">H", data, self.lookup_at)[0]
        if index >= count:
            return 0, 0, [], None
        at = self.lookup_at + struct.unpack_from(">H", data, self.lookup_at + 2 + 2 * index)[0]
        kind, flag, sub_count = struct.unpack_from(">HHH", data, at)
        subtables = [at + o for o in struct.unpack_from(f">{sub_count}H", data, at + 6)]
        mark_set = struct.unpack_from(">H", data, at + 6 + 2 * sub_count)[0] if flag & 0x10 else None
        extension = 7 if self.is_gsub else 9
        if kind != extension:
            return kind, flag, subtables, mark_set
        resolved = []
        for sub in subtables:
            kind, offset = struct.unpack_from(">HI", data, sub + 2)
            resolved.append(sub + offset)
        return kind, flag, resolved, mark_set

    is_gsub = True


class _Context:
    """One run being shaped through one table's lookups."""

    def __init__(self, face: OutlineFace, table: _Table, gdef: _Gdef, glyphs: list[Glyph],
                 coords: tuple[float, ...]) -> None:
        self.face, self.table, self.gdef, self.glyphs, self.coords = face, table, gdef, glyphs, coords
        self.flag = 0
        self.mark_set: set[int] | None = None
        self.depth = 0

    # -- skipping -------------------------------------------------------------------------

    def skip(self, glyph: Glyph) -> bool:
        # A default-ignorable character is passed over in matching, as HarfBuzz does
        # (a zero-width joiner or non-joiner only when positioning).
        if _default_ignorable(glyph.codepoint) and (
                not self.table.is_gsub or glyph.codepoint not in (0x200C, 0x200D)):
            return True
        flag = self.flag
        klass = glyph.klass
        if flag & 2 and klass == 1:
            return True
        if flag & 4 and klass == 2:
            return True
        if klass == 3:
            if flag & 8:
                return True
            if self.mark_set is not None and glyph.id not in self.mark_set:
                return True
            attach_type = flag >> 8
            if attach_type and self.gdef.mark_classes.get(glyph.id, 0) != attach_type:
                return True
        return False

    def next_index(self, i: int) -> int:
        i += 1
        while i < len(self.glyphs) and self.skip(self.glyphs[i]):
            i += 1
        return i

    def prev_index(self, i: int) -> int:
        i -= 1
        while i >= 0 and self.skip(self.glyphs[i]):
            i -= 1
        return i

    def set_lookup(self, flag: int, mark_set: int | None) -> None:
        self.flag = flag
        self.mark_set = (self.gdef.mark_sets[mark_set] if mark_set is not None and
                         mark_set < len(self.gdef.mark_sets) else None)

    # -- running ----------------------------------------------------------------------------

    def run_lookup(self, index: int) -> None:
        kind, flag, subtables, mark_set = self.table.lookup(index)
        first = self.table.first_glyphs(index)
        if first is not None and not any(g.id in first for g in self.glyphs):
            return
        self.set_lookup(flag, mark_set)
        i = 0
        while i < len(self.glyphs):
            if (first is not None and self.glyphs[i].id not in first) or self.skip(self.glyphs[i]):
                i += 1
                continue
            applied = None
            for sub in subtables:
                applied = self.apply(kind, sub, i)
                if applied is not None:
                    break
            i = applied if applied is not None else i + 1

    def apply_at(self, index: int, i: int) -> bool:
        """A nested lookup (from a context) applied at glyph ``i``."""
        if self.depth > 6:
            return False
        kind, flag, subtables, mark_set = self.table.lookup(index)
        saved = (self.flag, self.mark_set)
        self.set_lookup(flag, mark_set)
        self.depth += 1
        try:
            for sub in subtables:
                if self.apply(kind, sub, i) is not None:
                    return True
            return False
        finally:
            self.depth -= 1
            self.flag, self.mark_set = saved

    def apply(self, kind: int, at: int, i: int) -> int | None:  # pragma: no cover - overridden
        raise NotImplementedError

    # -- contexts (GSUB 5/6, GPOS 7/8) --------------------------------------------------

    def _match(self, i: int, sequence: Sequence[int], test) -> list[int] | None:
        """Indices of the input glyphs from ``i`` (the first already matched) for the rest
        of ``sequence``, or ``None``."""
        out = [i]
        j = i
        for value in sequence:
            j = self.next_index(j)
            if j >= len(self.glyphs) or not test(self.glyphs[j].id, value):
                return None
            out.append(j)
        return out

    def _back(self, i: int, sequence: Sequence[int], test) -> bool:
        j = i
        for value in sequence:
            j = self.prev_index(j)
            if j < 0 or not test(self.glyphs[j].id, value):
                return False
        return True

    def _ahead(self, last: int, sequence: Sequence[int], test) -> bool:
        j = last
        for value in sequence:
            j = self.next_index(j)
            if j >= len(self.glyphs) or not test(self.glyphs[j].id, value):
                return False
        return True

    def _apply_records(self, positions: list[int], records: Sequence[tuple[int, int]]) -> int:
        end = positions[-1] + 1
        before = len(self.glyphs)
        for sequence_index, lookup in records:
            if sequence_index < len(positions):
                self.apply_at(lookup, positions[sequence_index])
                grown = len(self.glyphs) - before
                if grown:
                    # A substitution changed the length: later positions move with it.
                    positions = [p if p <= positions[sequence_index] else p + grown for p in positions]
                    end += grown
                    before = len(self.glyphs)
        return max(end, positions[0] + 1)

    def context(self, at: int, i: int, chained: bool) -> int | None:
        data = self.table.data
        fmt = struct.unpack_from(">H", data, at)[0]
        glyph = self.glyphs[i].id
        if fmt == 1:
            coverage = self.table.coverage(at + struct.unpack_from(">H", data, at + 2)[0])
            index = coverage.get(glyph)
            if index is None:
                return None
            set_count = struct.unpack_from(">H", data, at + 4)[0]
            if index >= set_count:
                return None
            set_offset = struct.unpack_from(">H", data, at + 6 + 2 * index)[0]
            if not set_offset:
                return None
            rule_set = at + set_offset
            same = lambda g, v: g == v  # noqa: E731
            for rule in self._rules(rule_set, chained):
                result = self._try_rule(i, rule, same, same, same)
                if result is not None:
                    return result
            return None
        if fmt == 2:
            if chained:
                cov, back_at, input_at, ahead_at, set_count = struct.unpack_from(">HHHHH", data, at + 2)
                sets_at = at + 12
                back_classes = self.table.class_def(at + back_at) if back_at else {}
                ahead_classes = self.table.class_def(at + ahead_at) if ahead_at else {}
            else:
                cov, input_at, set_count = struct.unpack_from(">HHH", data, at + 2)
                sets_at = at + 8
                back_classes = ahead_classes = {}
            if glyph not in self.table.coverage(at + cov):
                return None
            input_classes = self.table.class_def(at + input_at) if input_at else {}
            klass = input_classes.get(glyph, 0)
            if klass >= set_count:
                return None
            set_offset = struct.unpack_from(">H", data, sets_at + 2 * klass)[0]
            if not set_offset:
                return None
            for rule in self._rules(at + set_offset, chained):
                result = self._try_rule(
                    i, rule,
                    lambda g, v: back_classes.get(g, 0) == v,
                    lambda g, v: input_classes.get(g, 0) == v,
                    lambda g, v: ahead_classes.get(g, 0) == v)
                if result is not None:
                    return result
            return None
        if fmt == 3:
            pos = at + 2
            if chained:
                back_count = struct.unpack_from(">H", data, pos)[0]
                back = [at + o for o in struct.unpack_from(f">{back_count}H", data, pos + 2)]
                pos += 2 + 2 * back_count
                input_count = struct.unpack_from(">H", data, pos)[0]
                inputs = [at + o for o in struct.unpack_from(f">{input_count}H", data, pos + 2)]
                pos += 2 + 2 * input_count
                ahead_count = struct.unpack_from(">H", data, pos)[0]
                ahead = [at + o for o in struct.unpack_from(f">{ahead_count}H", data, pos + 2)]
                pos += 2 + 2 * ahead_count
                record_count = struct.unpack_from(">H", data, pos)[0]
                pos += 2
            else:
                input_count, record_count = struct.unpack_from(">HH", data, pos)
                inputs = [at + o for o in struct.unpack_from(f">{input_count}H", data, pos + 4)]
                pos += 4 + 2 * input_count
                back, ahead = [], []
            records = [struct.unpack_from(">HH", data, pos + 4 * k) for k in range(record_count)]
            if not inputs or glyph not in self.table.coverage(inputs[0]):
                return None
            covered = lambda g, v: g in self.table.coverage(v)  # noqa: E731
            return self._try_rule(i, (back, inputs[1:], ahead, records), covered, covered, covered)
        return None

    def _rules(self, rule_set: int, chained: bool):
        data = self.table.data
        count = struct.unpack_from(">H", data, rule_set)[0]
        for k in range(count):
            rule = rule_set + struct.unpack_from(">H", data, rule_set + 2 + 2 * k)[0]
            pos = rule
            if chained:
                back_count = struct.unpack_from(">H", data, pos)[0]
                back = struct.unpack_from(f">{back_count}H", data, pos + 2)
                pos += 2 + 2 * back_count
                input_count = struct.unpack_from(">H", data, pos)[0]
                inputs = struct.unpack_from(f">{max(input_count - 1, 0)}H", data, pos + 2)
                pos += 2 + 2 * max(input_count - 1, 0)
                ahead_count = struct.unpack_from(">H", data, pos)[0]
                ahead = struct.unpack_from(f">{ahead_count}H", data, pos + 2)
                pos += 2 + 2 * ahead_count
                record_count = struct.unpack_from(">H", data, pos)[0]
                pos += 2
            else:
                input_count, record_count = struct.unpack_from(">HH", data, pos)
                inputs = struct.unpack_from(f">{max(input_count - 1, 0)}H", data, pos + 4)
                pos += 4 + 2 * max(input_count - 1, 0)
                back, ahead = (), ()
            records = [struct.unpack_from(">HH", data, pos + 4 * j) for j in range(record_count)]
            yield back, inputs, ahead, records

    def _try_rule(self, i: int, rule, back_test, input_test, ahead_test) -> int | None:
        back, inputs, ahead, records = rule
        positions = self._match(i, inputs, input_test)
        if positions is None:
            return None
        if not self._back(i, back, back_test) or not self._ahead(positions[-1], ahead, ahead_test):
            return None
        return self._apply_records(positions, records)


class _Substitute(_Context):
    def apply(self, kind: int, at: int, i: int) -> int | None:
        data = self.table.data
        glyph = self.glyphs[i]
        if kind == 1:
            fmt, cov = struct.unpack_from(">HH", data, at)
            index = self.table.coverage(at + cov).get(glyph.id)
            if index is None:
                return None
            if fmt == 1:
                glyph.id = (glyph.id + struct.unpack_from(">h", data, at + 4)[0]) & 0xFFFF
            else:
                glyph.id = struct.unpack_from(">H", data, at + 6 + 2 * index)[0]
            self._classify(glyph)
            return i + 1
        if kind == 2:
            _fmt, cov, count = struct.unpack_from(">HHH", data, at)
            index = self.table.coverage(at + cov).get(glyph.id)
            if index is None or index >= count:
                return None
            sequence = at + struct.unpack_from(">H", data, at + 6 + 2 * index)[0]
            n = struct.unpack_from(">H", data, sequence)[0]
            ids = struct.unpack_from(f">{n}H", data, sequence + 2)
            if not ids:
                del self.glyphs[i]
                return i
            new = [Glyph(gid, glyph.cluster, codepoint=glyph.codepoint) for gid in ids]
            for g in new:
                self._classify(g)
            self.glyphs[i:i + 1] = new
            return i + len(new)
        if kind == 4:
            _fmt, cov, count = struct.unpack_from(">HHH", data, at)
            index = self.table.coverage(at + cov).get(glyph.id)
            if index is None or index >= count:
                return None
            lig_set = at + struct.unpack_from(">H", data, at + 6 + 2 * index)[0]
            lig_count = struct.unpack_from(">H", data, lig_set)[0]
            for k in range(lig_count):
                lig = lig_set + struct.unpack_from(">H", data, lig_set + 2 + 2 * k)[0]
                result, components = struct.unpack_from(">HH", data, lig)
                rest = struct.unpack_from(f">{components - 1}H", data, lig + 4)
                positions = self._match(i, rest, lambda g, v: g == v)
                if positions is None:
                    continue
                cluster = min(self.glyphs[p].cluster for p in positions)
                last = positions[-1]
                # Glyphs skipped between the components (marks) keep their place after it.
                skipped = [self.glyphs[p] for p in range(i, last + 1) if p not in positions]
                ligature = Glyph(result, cluster, codepoint=glyph.codepoint, lig_components=components)
                self._classify(ligature)
                for g in self.glyphs[i:last + 1]:
                    g.cluster = cluster
                self.glyphs[i:last + 1] = [ligature] + skipped
                return i + 1
            return None
        if kind == 5:
            return self.context(at, i, chained=False)
        if kind == 6:
            return self.context(at, i, chained=True)
        return None

    def _classify(self, glyph: Glyph) -> None:
        if self.gdef.classes is not None:
            glyph.klass = self.gdef.classes.get(glyph.id, 0)


class _Position(_Context):
    def value(self, at: int, fmt: int, base: int) -> tuple[list[float], int]:
        """A ValueRecord: ``[x placement, y placement, x advance, y advance]`` and its size."""
        data = self.table.data
        values = [0.0, 0.0, 0.0, 0.0]
        pos = at
        for bit in range(4):
            if fmt & (1 << bit):
                values[bit] = struct.unpack_from(">h", data, pos)[0]
                pos += 2
        for bit in range(4, 8):
            if fmt & (1 << bit):
                device = struct.unpack_from(">H", data, pos)[0]
                pos += 2
                if device and self.coords:
                    values[bit - 4] += self._device(base + device)
        return values, pos - at

    def _device(self, at: int) -> float:
        data = self.table.data
        outer, inner, fmt = struct.unpack_from(">HHH", data, at)
        if fmt != 0x8000:
            return 0.0
        store = self.face.gdef_store
        return store.delta(outer, inner, self.coords) if store is not None else 0.0

    @staticmethod
    def _value_size(fmt: int) -> int:
        return 2 * bin(fmt & 0xFF).count("1")

    def _adjust(self, glyph: Glyph, values: list[float]) -> None:
        glyph.x_offset += round(values[0])
        glyph.y_offset += round(values[1])
        glyph.x_advance += round(values[2])

    def apply(self, kind: int, at: int, i: int) -> int | None:
        data = self.table.data
        glyph = self.glyphs[i]
        if kind == 1:
            fmt, cov, value_format = struct.unpack_from(">HHH", data, at)
            index = self.table.coverage(at + cov).get(glyph.id)
            if index is None:
                return None
            if fmt == 1:
                values, _ = self.value(at + 6, value_format, at)
            else:
                values, _ = self.value(at + 8 + index * self._value_size(value_format), value_format, at)
            self._adjust(glyph, values)
            return i + 1
        if kind == 2:
            fmt, cov, f1, f2 = struct.unpack_from(">HHHH", data, at)
            index = self.table.coverage(at + cov).get(glyph.id)
            if index is None:
                return None
            j = self.next_index(i)
            if j >= len(self.glyphs):
                return None
            second = self.glyphs[j]
            size1, size2 = self._value_size(f1), self._value_size(f2)
            if fmt == 1:
                set_count = struct.unpack_from(">H", data, at + 8)[0]
                if index >= set_count:
                    return None
                pair_set = at + struct.unpack_from(">H", data, at + 10 + 2 * index)[0]
                count = struct.unpack_from(">H", data, pair_set)[0]
                record = 2 + size1 + size2
                lo, hi = 0, count - 1
                found = None
                while lo <= hi:
                    mid = (lo + hi) // 2
                    gid = struct.unpack_from(">H", data, pair_set + 2 + mid * record)[0]
                    if gid == second.id:
                        found = pair_set + 2 + mid * record + 2
                        break
                    if gid < second.id:
                        lo = mid + 1
                    else:
                        hi = mid - 1
                if found is None:
                    return None
                v1, _ = self.value(found, f1, pair_set)
                v2, _ = self.value(found + size1, f2, pair_set)
            else:
                class1_at, class2_at, count1, count2 = struct.unpack_from(">HHHH", data, at + 8)
                c1 = self.table.class_def(at + class1_at).get(glyph.id, 0)
                c2 = self.table.class_def(at + class2_at).get(second.id, 0)
                if c1 >= count1 or c2 >= count2:
                    return None
                record = at + 16 + (c1 * count2 + c2) * (size1 + size2)
                v1, _ = self.value(record, f1, at)
                v2, _ = self.value(record + size1, f2, at)
            self._adjust(glyph, v1)
            self._adjust(second, v2)
            return j + 1 if f2 else j
        if kind in (4, 6, 5):
            return self._mark(kind, at, i)
        if kind == 7:
            return self.context(at, i, chained=False)
        if kind == 8:
            return self.context(at, i, chained=True)
        return None

    def _anchor(self, at: int) -> tuple[float, float]:
        data = self.table.data
        fmt, x, y = struct.unpack_from(">Hhh", data, at)
        x, y = float(x), float(y)
        if fmt == 3 and self.coords:
            dx, dy = struct.unpack_from(">HH", data, at + 6)
            if dx:
                x += self._device(at + dx)
            if dy:
                y += self._device(at + dy)
        return x, y

    def _mark(self, kind: int, at: int, i: int) -> int | None:
        data = self.table.data
        mark = self.glyphs[i]
        _fmt, mark_cov, base_cov, class_count, marks_at, bases_at = struct.unpack_from(">HHHHHH", data, at)
        mark_index = self.table.coverage(at + mark_cov).get(mark.id)
        if mark_index is None:
            return None
        # The glyph the mark attaches to: the previous base (4), ligature (5) or mark (6).
        j = i - 1
        while j >= 0:
            other = self.glyphs[j]
            if kind == 6:
                if other.klass == 3:
                    break
                return None
            if other.klass != 3:
                break
            j -= 1
        if j < 0:
            return None
        base = self.glyphs[j]
        base_index = self.table.coverage(at + base_cov).get(base.id)
        if base_index is None:
            return None
        marks = at + marks_at
        mark_class, mark_anchor = struct.unpack_from(">HH", data, marks + 2 + 4 * mark_index)
        if mark_class >= class_count:
            return None
        array = at + bases_at
        if kind == 5:
            lig = array + struct.unpack_from(">H", data, array + 2 + 2 * base_index)[0]
            components = struct.unpack_from(">H", data, lig)[0]
            if not components:
                return None
            component = components - 1
            anchor_offset = struct.unpack_from(">H", data, lig + 2 + 2 * (component * class_count + mark_class))[0]
            anchor_base = lig
        else:
            anchor_offset = struct.unpack_from(">H", data, array + 2 + 2 * (base_index * class_count + mark_class))[0]
            anchor_base = array
        if not anchor_offset:
            return None
        bx, by = self._anchor(anchor_base + anchor_offset)
        mx, my = self._anchor(marks + mark_anchor)
        mark.extras["anchor"] = (j, bx - mx, by - my)
        return i + 1


def _finish_marks(glyphs: list[Glyph]) -> None:
    """Place attached marks: offset from their base's pen position."""
    for i, glyph in enumerate(glyphs):
        anchor = glyph.extras.pop("anchor", None)
        if anchor is None:
            continue
        j, dx, dy = anchor
        if not 0 <= j < i:
            continue
        pen = sum(g.x_advance for g in glyphs[j:i])
        glyph.x_offset = round(dx) + glyphs[j].x_offset - pen
        glyph.y_offset = round(dy) + glyphs[j].y_offset


# --------------------------------------------------------------------------------------
# Fallback spaces and default ignorables (HarfBuzz)
# --------------------------------------------------------------------------------------

_SPACES = {0x0020: 0, 0x00A0: 0, 0x2000: 2, 0x2001: 1, 0x2002: 2, 0x2003: 1, 0x2004: 3, 0x2005: 4, 0x2006: 6,
           0x2007: "figure", 0x2008: "punctuation", 0x2009: 5, 0x200A: 16, 0x202F: "narrow", 0x205F: "4/18",
           0x3000: 1}


def _default_ignorable(code: int) -> bool:
    return (code == 0x00AD or code == 0x034F or code == 0x061C or 0x115F <= code <= 0x1160
            or 0x17B4 <= code <= 0x17B5 or 0x180B <= code <= 0x180F or 0x200B <= code <= 0x200F
            or 0x202A <= code <= 0x202E or 0x2060 <= code <= 0x206F or code == 0x3164
            or 0xFE00 <= code <= 0xFE0F or code == 0xFEFF or code == 0xFFA0 or 0xFFF0 <= code <= 0xFFF8
            or 0x1BCA0 <= code <= 0x1BCA3 or 0x1D173 <= code <= 0x1D17A or 0xE0000 <= code <= 0xE0FFF)


# --------------------------------------------------------------------------------------
# Shaping
# --------------------------------------------------------------------------------------

def _tables(face: OutlineFace) -> tuple[_Table, _Table, _Gdef]:
    gsub = getattr(face, "_shaper_gsub", None)
    if gsub is None:
        gsub = _Table(face, b"GSUB")
        gsub.is_gsub = True
        gpos = _Table(face, b"GPOS")
        gpos.is_gsub = False
        gdef = _Gdef(face)
        face._shaper_gsub = gsub  # type: ignore[attr-defined]
        face._shaper_gpos = gpos  # type: ignore[attr-defined]
        face._shaper_gdef = gdef  # type: ignore[attr-defined]
    return face._shaper_gsub, face._shaper_gpos, face._shaper_gdef  # type: ignore[attr-defined]


def _normalised(face: OutlineFace, text: str) -> list[tuple[int, int]]:
    """``(code point, byte offset)`` of ``text`` as HarfBuzz's normaliser leaves it for
    the face: a character the face lacks decomposed where it has the parts, and a base
    with its marks composed where the face has the composed character (the composed one
    at the base's offset)."""
    out: list[tuple[int, int]] = []
    offset = 0
    chars = list(text)
    i = 0
    while i < len(chars):
        char = chars[i]
        size = len(char.encode("utf-8"))
        # A base and the marks after it.
        j = i + 1
        while j < len(chars) and unicodedata.combining(chars[j]):
            j += 1
        if j > i + 1:
            cluster = "".join(chars[i:j])
            composed = unicodedata.normalize("NFC", cluster)
            if composed != cluster and all(face.has_char(ord(c)) for c in composed):
                for c in composed[:1]:
                    out.append((ord(c), offset))
                rest = offset + size
                for c, original in zip(composed[1:], chars[i + 1:j]):
                    out.append((ord(c), rest))
                    rest += len(original.encode("utf-8"))
                offset += len(cluster.encode("utf-8"))
                i = j
                continue
        if not face.has_char(ord(char)):
            parts = unicodedata.normalize("NFD", char)
            if len(parts) > 1 and all(face.has_char(ord(c)) for c in parts):
                out.extend((ord(c), offset) for c in parts)
                offset += size
                i += 1
                continue
        out.append((ord(char), offset))
        offset += size
        i += 1
    return out


def shape(face: OutlineFace, text: str, coords: tuple[float, ...] = (), *, kerning: bool = True) -> list[Glyph]:
    """``text`` (a left-to-right run :func:`shapeable` accepts) as glyphs of ``face`` at
    the instance ``coords``; a character the face lacks is glyph 0."""
    gsub, gpos, gdef = _tables(face)
    glyphs: list[Glyph] = []
    space = face.glyph(0x20)
    for code, offset in _normalised(face, text):
        gid = face.glyph(code)
        g = Glyph(gid, offset, codepoint=code)
        if gid == 0 and code in _SPACES and code != 0x20 and space:
            g.id = space
            g.extras["space"] = _SPACES[code]
        if _is_mark_char(code) and glyphs:
            g.cluster = glyphs[-1].cluster   # a mark continues its base's cluster
        glyphs.append(g)
    for g in glyphs:
        if gdef.classes is not None:
            g.klass = gdef.classes.get(g.id, 0)
        elif _is_mark_char(g.codepoint):
            g.klass = 3
    scripts = _script_tags(text)
    if gsub.ok:
        context = _Substitute(face, gsub, gdef, glyphs, coords)
        for index in gsub.lookups(scripts, _GSUB_FEATURES):
            context.run_lookup(index)
    for g in glyphs:
        g.x_advance = face.advance(g.id, coords)
        kind = g.extras.pop("space", None)
        if kind is not None and kind != 0:
            upem = face.units_per_em
            if isinstance(kind, int):
                g.x_advance = (upem + kind // 2) // kind
            elif kind == "4/18":
                g.x_advance = upem * 4 // 18
            elif kind == "narrow":
                g.x_advance //= 2
            elif kind == "figure":
                for digit in "0123456789":
                    found = face.glyph(ord(digit))
                    if found:
                        g.x_advance = face.advance(found, coords)
                        break
            elif kind == "punctuation":
                for mark in ".,":
                    found = face.glyph(ord(mark))
                    if found:
                        g.x_advance = face.advance(found, coords)
                        break
    gpos_features = [tag for tag in _GPOS_FEATURES if kerning or tag != b"kern"]
    has_gpos_kern = gpos.ok and b"kern" in gpos.feature_tags()
    if gpos.ok:
        positioning = _Position(face, gpos, gdef, glyphs, coords)
        for index in gpos.lookups(scripts, gpos_features):
            positioning.run_lookup(index)
    if kerning and not has_gpos_kern and face.legacy_kern:
        pairs = face.legacy_kern
        previous = None
        for g in glyphs:
            if g.klass == 3 or _default_ignorable(g.codepoint):
                continue
            if previous is not None:
                previous.x_advance += pairs.get((previous.id, g.id), 0)
            previous = g
    for g in glyphs:
        if g.klass == 3:
            g.x_advance = 0
    _finish_marks(glyphs)
    if any(_default_ignorable(g.codepoint) for g in glyphs):
        kept = []
        for g in glyphs:
            if _default_ignorable(g.codepoint) and g.lig_components == 1:
                if not space:
                    continue
                g.id, g.x_advance, g.x_offset, g.y_offset = space, 0, 0, 0
            kept.append(g)
        glyphs[:] = kept
    return glyphs
