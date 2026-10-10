"""The folder walks behind every lookup in an application's font folders, cached per process.

A walk is kept with the modification time of every folder it found and reused while those
stand: one stat per folder per lookup, none per file, no listing.  A font added to a
folder at any depth is seen by the next lookup; ``refresh_font_dirs()`` forgets everything.
The faces are name-table-only fonts written here: only the index reads them.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path

import pytest

from ooxml_common.fonts import office
from ooxml_common.fonts.sfnt import write_sfnt


def _face(family: str) -> bytes:
    raw = family.encode("utf-16-be")
    name = struct.pack(">HHH", 0, 1, 18) + struct.pack(">HHHHHH", 3, 1, 0x409, 1, len(raw), 0) + raw
    return write_sfnt([(b"name", name)])


def _bump(folder: Path) -> None:
    """Move a folder's time on by a second, so the test does not hang on a file system's
    time resolution (the change itself is what a real addition makes)."""
    stamp = os.stat(folder).st_mtime_ns + 1_000_000_000
    os.utime(folder, ns=(stamp, stamp))


@pytest.fixture(autouse=True)
def fresh():
    office.refresh_font_dirs()
    yield
    office.refresh_font_dirs()


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "fonts"
    for path in ("a", "a/deep", "b"):
        (root / path).mkdir(parents=True)
    (root / "a" / "deep" / "First.ttf").write_bytes(_face("First Face"))
    return root


def _rglob(root: Path) -> tuple[Path, ...]:
    """What the walk replaced: ``rglob("*")`` filtered by ``is_dir()``."""
    return (root, *sorted(path for path in root.rglob("*") if path.is_dir()))


def test_the_walk_lists_what_rglob_listed(tree):
    (tree / "b" / "x" / "y").mkdir(parents=True)
    (tree / "b" / "file.ttf").write_bytes(b"\0")
    assert office.with_subfolders([tree]) == _rglob(tree)


@pytest.mark.skipif(os.name == "nt", reason="folder links need privileges on Windows")
def test_a_linked_folder_is_listed_not_descended(tree, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "inner").mkdir(parents=True)
    (tree / "link").symlink_to(elsewhere, target_is_directory=True)
    found = office.with_subfolders([tree])
    assert tree / "link" in found and tree / "link" / "inner" not in found
    assert found == _rglob(tree)


def test_a_cached_walk_stats_each_folder_and_lists_none(tree, monkeypatch):
    first = office.with_subfolders([tree])
    calls = {"stat": 0, "scandir": 0}
    real_stat, real_scandir = os.stat, os.scandir

    def stat(*args, **kwargs):
        calls["stat"] += 1
        return real_stat(*args, **kwargs)

    def scandir(*args, **kwargs):
        calls["scandir"] += 1
        return real_scandir(*args, **kwargs)

    monkeypatch.setattr(os, "stat", stat)
    monkeypatch.setattr(os, "scandir", scandir)
    assert office.with_subfolders([tree]) == first
    assert calls == {"stat": len(first), "scandir": 0}


def test_a_font_added_to_a_nested_folder_is_found_next_time(tree):
    assert office.user_families([tree]) == frozenset({"first face"})
    # A nested folder's time changes, its parents' do not: every folder is checked.
    (tree / "a" / "deep" / "Second.ttf").write_bytes(_face("Second Face"))
    _bump(tree / "a" / "deep")
    assert office.user_families([tree]) == frozenset({"first face", "second face"})


def test_a_new_subfolder_is_walked(tree):
    office.with_subfolders([tree])
    (tree / "b" / "new").mkdir()
    (tree / "b" / "new" / "Third.ttf").write_bytes(_face("Third Face"))
    _bump(tree / "b")
    assert tree / "b" / "new" in office.with_subfolders([tree])
    assert "third face" in office.user_families([tree])


def test_a_removed_folder_is_dropped(tree):
    office.with_subfolders([tree])
    (tree / "a" / "deep" / "First.ttf").unlink()
    (tree / "a" / "deep").rmdir()
    _bump(tree / "a")
    assert tree / "a" / "deep" not in office.with_subfolders([tree])
    assert office.user_families([tree]) == frozenset()


def test_refresh_reads_a_file_rewritten_in_place(tree):
    face = tree / "a" / "deep" / "First.ttf"
    assert office.user_families([tree]) == frozenset({"first face"})
    stamps = {path: os.stat(path).st_mtime_ns for path in office.with_subfolders([tree])}
    face.write_bytes(_face("Renamed Face"))
    for path, stamp in stamps.items():          # the folder times say nothing changed
        os.utime(path, ns=(stamp, stamp))
    assert office.user_families([tree]) == frozenset({"first face"})
    office.refresh_font_dirs()
    assert office.user_families([tree]) == frozenset({"renamed face"})


def test_each_session_sees_its_own_folders(tmp_path):
    for name in ("one", "two"):
        (tmp_path / name).mkdir()
        (tmp_path / name / f"{name}.ttf").write_bytes(_face(f"Face {name}"))
    assert office.user_families([tmp_path / "one"]) == frozenset({"face one"})
    assert office.user_families([tmp_path / "two"]) == frozenset({"face two"})
    assert office.user_families([tmp_path / "one"]) == frozenset({"face one"})
    assert office.user_families([]) == frozenset()


def test_an_absent_folder_is_none_until_it_exists(tmp_path):
    assert office.with_subfolders([tmp_path / "later"]) == ()
    (tmp_path / "later").mkdir()
    assert office.with_subfolders([tmp_path / "later"]) == (tmp_path / "later",)


def test_the_cloud_listing_follows_the_cache_folder(tmp_path):
    (tmp_path / "Aptos Display").mkdir()
    assert office.cloud_font_dirs(tmp_path) == (tmp_path / "Aptos Display",)
    (tmp_path / "Aptos Serif").mkdir()
    _bump(tmp_path)
    assert office.cloud_font_dirs(tmp_path) == (tmp_path / "Aptos Display", tmp_path / "Aptos Serif")
