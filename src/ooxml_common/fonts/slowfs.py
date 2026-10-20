"""A one-time warning when fonts, or this library, are read from a slow file system.

Rasterising opens a face's file again for every run of text it shapes, and the font
folders are walked and their headers read for every measurement that misses the caches.
On the local disk an open is a few microseconds; on WSL's mounts of Windows drives
(``/mnt/c``: 9p, or WSL 1's drvfs) and on network file systems (NFS, SMB/CIFS, a FUSE
network mount such as an Azure Files or S3 volume) every open crosses to another machine
or the Windows host, and a slide that rasterises in a fraction of a second on the local
disk takes seconds.  Nothing in the output says so, so the first time a folder in use is
on one, a warning on the ``ooxml_common.fonts`` logger says which folder, what file
system, and what to do: keep the fonts on the local disk (bake them into the image, or
copy them into the container's or WSL's own file system at start) and point
``OOXML_FONT_DIRS`` / ``font_dirs`` there.

Linux only, from ``/proc/self/mountinfo`` (the mount a path is on is the longest mount
point it is under); elsewhere, or where that file cannot be read, nothing is checked.
Once per process per folder; checking costs a dictionary lookup after the first time.
Standard library only.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from typing import Iterable

__all__ = ["SLOW_TYPES", "check_package", "mounts", "slow_mount", "warn_if_slow"]

logger = logging.getLogger("ooxml_common.fonts")

#: File system types where every file open crosses to another machine or to a Windows
#: host: WSL's mounts of Windows drives (9p in WSL 2, drvfs in WSL 1), and network file
#: systems.  ``fuse.*`` types are FUSE mounts, named by the program serving them.
SLOW_TYPES = {
    "9p": "WSL's mount of a Windows drive (9p)",
    "drvfs": "WSL's mount of a Windows drive (drvfs)",
    "nfs": "a network file system (NFS)",
    "nfs4": "a network file system (NFS)",
    "cifs": "a network file system (SMB/CIFS)",
    "smb3": "a network file system (SMB)",
    "smbfs": "a network file system (SMB)",
    "afs": "a network file system (AFS)",
    "ceph": "a network file system (CephFS)",
    "glusterfs": "a network file system (GlusterFS)",
    "lustre": "a network file system (Lustre)",
    "davfs": "a network file system (WebDAV)",
    "fuse.sshfs": "a network file system (SSHFS)",
    "fuse.rclone": "a network file system (rclone)",
    "fuse.s3fs": "a network file system (s3fs)",
    "fuse.goofys": "a network file system (goofys)",
    "fuse.gcsfuse": "a network file system (Cloud Storage FUSE)",
    "fuse.blobfuse": "a network file system (BlobFuse)",
    "fuse.blobfuse2": "a network file system (BlobFuse)",
    "fuse.juicefs": "a network file system (JuiceFS)",
    "fuse.glusterfs": "a network file system (GlusterFS)",
    "fuse.ceph-fuse": "a network file system (CephFS)",
    "fuse.davfs2": "a network file system (WebDAV)",
    "fuse.grpcfuse": "a host folder shared into a container (Docker Desktop)",
}

MOUNTINFO = "/proc/self/mountinfo"

_LOCK = threading.Lock()
#: Folders checked already (each warned about at most once), and the mount table.
_CHECKED: set = set()
_MOUNTS: "list[tuple[str, str, str]] | None" = None
_PACKAGE_CHECKED = False


def _unescape(field: str) -> str:
    """A mountinfo path field: spaces, tabs, newlines and backslashes are octal escapes."""
    if "\\" not in field:
        return field
    out, i = [], 0
    while i < len(field):
        digits = field[i + 1:i + 4]
        if field[i] == "\\" and len(digits) == 3 and digits.isdigit():
            out.append(chr(int(field[i + 1:i + 4], 8)))
            i += 4
        else:
            out.append(field[i])
            i += 1
    return "".join(out)


def mounts(text: str) -> "list[tuple[str, str, str]]":
    """``(mount point, file system type, source)`` of every line of a mountinfo file's
    ``text`` (proc(5)): fields 5 and, after the ``-`` separator, the first two."""
    out = []
    for line in text.splitlines():
        fields = line.split()
        if "-" not in fields[6:]:
            continue
        dash = fields.index("-", 6)
        if len(fields) < dash + 3 or len(fields) < 5:
            continue
        out.append((_unescape(fields[4]), fields[dash + 1], _unescape(fields[dash + 2])))
    return out


def _mount_table() -> "list[tuple[str, str, str]]":
    global _MOUNTS
    if _MOUNTS is None:
        table: list = []
        if sys.platform.startswith("linux"):
            try:
                with open(MOUNTINFO, encoding="utf-8", errors="surrogateescape") as handle:
                    table = mounts(handle.read())
            except OSError:
                table = []
        _MOUNTS = table
    return _MOUNTS


def slow_mount(path: str, table: "Iterable[tuple[str, str, str]]") -> "tuple[str, str, str] | None":
    """The mount ``path`` is on -- the longest mount point it is under -- when its type is
    one of :data:`SLOW_TYPES`; else ``None``."""
    best = None
    for point, kind, source in table:
        if path == point or path.startswith(point.rstrip("/") + "/") or point == "/":
            if best is None or len(point) > len(best[0]):
                best = (point, kind, source)
    if best is not None and best[1] in SLOW_TYPES:
        return best
    return None


def warn_if_slow(paths: Iterable, *, what: str = "font folder",
                 table: "Iterable[tuple[str, str, str]] | None" = None) -> list:
    """Warn once per process per path in ``paths`` that is on a slow file system
    (:data:`SLOW_TYPES`); return the ``(path, mount)`` pairs warned about now.  ``table``
    is a mount table (:func:`mounts`) in place of this process's own; without one,
    nothing is checked off Linux."""
    fresh = []
    with _LOCK:
        for path in paths:
            key = (what, os.fspath(path))
            if key not in _CHECKED:
                _CHECKED.add(key)
                fresh.append(key[1])
    if not fresh:
        return []
    if table is None:
        with _LOCK:
            table = _mount_table()
    if not table:
        return []
    warned = []
    for path in fresh:
        try:
            # Mount points are POSIX paths; elsewhere (a table given by a test) as given.
            real = os.path.realpath(path) if os.sep == "/" else path.replace("\\", "/")
        except (OSError, ValueError):
            continue
        found = slow_mount(real, table)
        if found is None:
            continue
        point, kind, source = found
        warned.append((path, found))
        logger.warning(
            "%s %s is on %s (%s, %s mounted at %s): every font file opened there crosses "
            "to the other side, which makes measuring and rasterising slow -- seconds a slide. "
            "Keep it on the local disk: copy the fonts into this machine's, container's or WSL's "
            "own file system (bake them into the image, or copy them to a local folder at start) "
            "and point OOXML_FONT_DIRS or font_dirs there.%s",
            what, path, SLOW_TYPES[kind], kind, source, point,
            " For the library itself, install the environment on the local disk too."
            if what == "package" else "")
    return warned


def check_package(table: "Iterable[tuple[str, str, str]] | None" = None) -> list:
    """:func:`warn_if_slow` for where this library is installed and for the
    ``pptx2svg-fonts`` bundle, once per process."""
    global _PACKAGE_CHECKED
    with _LOCK:
        if _PACKAGE_CHECKED and table is None:
            return []
        _PACKAGE_CHECKED = True
    from . import bundle_dir

    package = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    warned = warn_if_slow([package], what="package", table=table)
    bundle = bundle_dir()
    if bundle is not None:
        warned += warn_if_slow([str(bundle)], what="font bundle", table=table)
    return warned


def _reset() -> None:
    """Forget what was checked and the mount table (for tests)."""
    global _MOUNTS, _PACKAGE_CHECKED
    with _LOCK:
        _CHECKED.clear()
        _MOUNTS = None
        _PACKAGE_CHECKED = False
