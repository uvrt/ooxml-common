"""Module caches read and written from several threads at once.

With the GIL off (Python 3.15t) a cache's check-then-use steps interleave with another
thread's eviction or clear: the embedded-font LRU raised ``KeyError`` between its get and
its move, and the picture caches raised it reading back an entry another thread had just
cleared.  Each test here runs eight threads over more keys than the cache holds, so it
evicts constantly, for at most about a second, and expects no error and the right answer
every time.  On the old code under 3.15t these failed within that time; under a GIL build
they pass either way, and quickly.
"""

from __future__ import annotations

import base64
import threading
import time

from ooxml_common.fonts import embedded
from ooxml_common.metafile import inline_metafile_images
from ooxml_common.metafile.gdi import MARKER
from ooxml_common.svgimage import with_pixel_sized_images

THREADS = 8
SECONDS = 1.0
CALLS = 20_000


def hammer(call, keys: int) -> list[str]:
    """Run ``call(key)`` from :data:`THREADS` threads over ``keys`` keys, each thread
    starting at a different key, until :data:`CALLS` calls each or :data:`SECONDS`; the
    errors raised, as text."""
    errors: list[str] = []
    start = threading.Barrier(THREADS)

    def run(seed: int) -> None:
        start.wait()
        deadline = time.monotonic() + SECONDS
        for k in range(CALLS):
            if k % 32 == 0 and time.monotonic() > deadline:
                return
            try:
                call((seed * 5 + k) % keys)
            except Exception as error:  # noqa: BLE001 -- any error is the failure
                errors.append(repr(error))
                return

    threads = [threading.Thread(target=run, args=(seed,)) for seed in range(THREADS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return errors


def test_embedded_font_cache_from_threads(monkeypatch):
    monkeypatch.setattr(embedded, "_decode_cache", embedded.OrderedDict())
    # The cache, not the decoder, is under test: decoding is made instant.
    monkeypatch.setattr(embedded, "decode_eot", lambda payload: b"font:" + payload)
    keys = embedded._DECODE_CACHE_SIZE + 2
    payloads = [b"payload %d" % k for k in range(keys)]

    def call(key: int) -> None:
        assert embedded._decode(payloads[key]) == b"font:" + payloads[key]
        if key == 0:
            embedded.decoded_faces()
        elif key == 1:
            embedded.remember_decoded({b"d" * 32: b"handed"})

    assert hammer(call, keys) == []
    assert len(embedded._decode_cache) <= embedded._DECODE_CACHE_SIZE


def _picture(width: int, marked: bool = False) -> str:
    mark = f' {MARKER}="1"' if marked else ""
    inner = (f'<svg xmlns="http://www.w3.org/2000/svg"{mark} width="{width}" height="10">'
             f'<rect width="{width}" height="10"/></svg>').encode()
    return base64.b64encode(inner).decode("ascii")


def test_svg_picture_cache_from_threads():
    pages = [f'<svg><image href="data:image/svg+xml;base64,{_picture(k + 1)}"/></svg>'
             for k in range(70)]
    expected = [with_pixel_sized_images(page) for page in pages]

    def call(key: int) -> None:
        assert with_pixel_sized_images(pages[key]) == expected[key]

    assert hammer(call, len(pages)) == []


def test_inline_metafile_cache_from_threads():
    pages = [f'<svg><image href="data:image/svg+xml;base64,{_picture(k + 1, marked=k % 2 == 0)}"'
             f' width="10" height="10"/></svg>' for k in range(70)]
    expected = [inline_metafile_images(page) for page in pages]

    def call(key: int) -> None:
        assert inline_metafile_images(pages[key]) == expected[key]

    assert hammer(call, len(pages)) == []
