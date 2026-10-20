"""The one-time warning for fonts (or the library) on a slow file system
(``ooxml_common.fonts.slowfs``), from a made-up ``/proc/self/mountinfo``."""

from __future__ import annotations

import logging

import pytest

from ooxml_common.fonts import office, slowfs

MOUNTINFO = r"""
22 1 8:1 / / rw,relatime shared:1 - ext4 /dev/sdc rw
60 22 0:52 / /mnt/c rw,noatime - 9p drvfs rw,aname=drvfs;path=C:\;uid=1000
61 22 0:53 / /mnt/wsl1 rw - drvfs D:\ rw
70 22 0:60 / /srv/fonts rw - nfs4 files.example:/fonts rw,vers=4.2
71 22 0:61 / /mnt/azure\040files rw - cifs //acct.example/share rw
72 22 0:62 / /data/bucket rw - fuse.s3fs s3fs rw
73 22 0:63 / /home/user/local rw - fuse.portal portal rw
"""


@pytest.fixture(autouse=True)
def fresh():
    slowfs._reset()
    yield
    slowfs._reset()


def test_mountinfo_is_read_with_its_escapes():
    table = slowfs.mounts(MOUNTINFO)
    assert ("/mnt/azure files", "cifs", "//acct.example/share") in table
    assert table[0] == ("/", "ext4", "/dev/sdc")


@pytest.mark.parametrize("path, kind", [
    ("/mnt/c/Users/me/fonts", "9p"), ("/mnt/wsl1/fonts", "drvfs"), ("/srv/fonts/office", "nfs4"),
    ("/mnt/azure files/f", "cifs"), ("/data/bucket/fonts", "fuse.s3fs"),
])
def test_slow_mounts_are_found_by_the_longest_mount_point(path, kind):
    assert slowfs.slow_mount(path, slowfs.mounts(MOUNTINFO))[1] == kind


@pytest.mark.parametrize("path", ["/usr/share/fonts", "/home/user/local/fonts", "/mnt/cdrom", "/srv/fontsx"])
def test_local_and_unknown_mounts_are_not_slow(path):
    assert slowfs.slow_mount(path, slowfs.mounts(MOUNTINFO)) is None


def test_warned_once_per_folder_with_what_to_do(caplog):
    table = slowfs.mounts(MOUNTINFO)
    with caplog.at_level(logging.WARNING, logger="ooxml_common.fonts"):
        assert slowfs.warn_if_slow(["/mnt/c/fonts", "/usr/share/fonts"], table=table)
        assert not slowfs.warn_if_slow(["/mnt/c/fonts"], table=table)
    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert "/mnt/c/fonts" in message and "9p" in message
    assert "local disk" in message and "OOXML_FONT_DIRS" in message


def test_the_package_is_checked_once(monkeypatch, caplog):
    table = slowfs.mounts("1 0 0:1 / / rw - nfs server:/ rw\n")
    with caplog.at_level(logging.WARNING, logger="ooxml_common.fonts"):
        warned = slowfs.check_package(table)
    assert warned and warned[0][1][1] == "nfs"
    assert "install the environment on the local disk" in caplog.records[0].getMessage()


def test_user_font_dirs_checks_its_folders(monkeypatch):
    seen = []
    monkeypatch.setattr(slowfs, "warn_if_slow", lambda paths, **kw: seen.extend(paths))
    monkeypatch.setattr(slowfs, "check_package", lambda: None)
    office.user_font_dirs(["/somewhere/fonts"])
    assert [str(p) for p in seen] == ["/somewhere/fonts"]


def test_nothing_is_checked_where_there_is_no_mount_table(monkeypatch, caplog):
    monkeypatch.setattr(slowfs, "MOUNTINFO", "/nonexistent/mountinfo")
    with caplog.at_level(logging.WARNING, logger="ooxml_common.fonts"):
        assert slowfs.warn_if_slow(["/mnt/c/fonts"]) == []
    assert not caplog.records
