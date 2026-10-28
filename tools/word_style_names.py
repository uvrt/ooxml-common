#!/usr/bin/env python3
"""Measure Word's display names of its built-in styles, and its list separator, in one
interface language: ``src/ooxml_common/stylenames.json`` (:mod:`ooxml_common.stylenames`).

Word for Mac is started with the language and region given (``open -a "Microsoft Word"
--args -AppleLanguages (fr) -AppleLocale fr_FR``), opening a made-up empty document so it
shows no document gallery.  An AppleScript then makes a new document and, for every style
in it, reads ``name local``, ``built in`` and ``style type``, and gives the style a font size
of its own (30.5 pt for the first, half a point more for each next); it reads ``get
international information list separator`` and saves the document.  The saved
``styles.xml`` says, by each style's size, which stored name (``w:name``) every display
name belongs to.  Every document is closed without saving its changes, whatever happens.

    python3 tools/word_style_names.py fr fr_FR [nl nl_NL ...]
    python3 tools/word_style_names.py --saved answer.txt saved.docx nl nl_BE

(``--saved``: a run's answer and saved document kept from an earlier run of the same
script, read again.)

Word is one instance per machine.  Like the docx2svg and docx-agent oracles this takes the
machine-wide lock (``word-oracle.lock`` in the Office group container, waiting for it), and
refuses to start while Word runs.  Word replaces ``Normal.dotm`` when it starts in another
language; the template is read before the launch and written back after Word quits, and
the renamed copy Word leaves of it removed.  macOS only; standard library only.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import subprocess
import sys
import time
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src" / "ooxml_common" / "stylenames.json"
APP = "/Applications/Microsoft Word.app"
GROUP = Path.home() / "Library" / "Group Containers" / "UBF8T346G9.Office"
LOCK = GROUP / "word-oracle.lock"
STAGE = GROUP / "ooxml-common-oracle"
TEMPLATES = GROUP / "User Content.localized" / "Templates.localized"
NORMAL = TEMPLATES / "Normal.dotm"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
#: The first style's font size and the step, in points.
FIRST, STEP = 30.5, 0.5

SCRIPT = """on run argv
	set outPath to item 1 of argv
	tell application "Microsoft Word"
		set res to ""
		try
			make new document
			set d to active document
			set n to count of Word styles of d
			set res to "SEP" & tab & (get international information list separator) & linefeed
			repeat with i from 1 to n
				set s to Word style i of d
				set sized to "-"
				try
					set font size of font object of s to (30 + i * 0.5)
					set sized to "ok"
				end try
				set res to res & i & tab & (built in of s) & tab & ((style type of s) as text) & tab & sized & tab & (name local of s) & linefeed
			end repeat
			save as d file name outPath file format format document
			close d saving no
		on error e
			repeat while (count of documents) > 0
				close document 1 saving no
			end repeat
			return res & "ERROR" & tab & e
		end try
		return res
	end tell
end run"""

CLOSE_ALL = ('tell application "Microsoft Word"\nrepeat while (count of documents) > 0\n'
             'close document 1 saving no\nend repeat\nend tell')

#: The empty document Word is started with: without one it shows its document gallery,
#: which no script can close and which keeps Word from quitting.
EMPTY = {
    "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns='
    '"http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" '
    'ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" '
    'ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/'
    'vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
    "_rels/.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns='
    '"http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type='
    '"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="word/document.xml"/></Relationships>',
    "word/document.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w='
    '"http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p/></w:body></w:document>',
}


def running() -> bool:
    return subprocess.run(["pgrep", "-x", "Microsoft Word"], capture_output=True).returncode == 0


def osa(script: str, *args: object, timeout: int = 120) -> tuple[int, str, str]:
    done = subprocess.run(["osascript", "-e", script, *map(str, args)], capture_output=True, text=True,
                          timeout=timeout)
    return done.returncode, done.stdout.strip(), done.stderr.strip()


def quit_word() -> bool:
    for _ in range(3):
        with contextlib.suppress(subprocess.TimeoutExpired):
            osa(CLOSE_ALL, timeout=60)
            osa('tell application "Microsoft Word" to quit saving no', timeout=60)
        for _ in range(100):
            if not running():
                return True
            time.sleep(0.3)
    return False


@contextlib.contextmanager
def word(language: str, region: str):
    """Word started in ``language`` / ``region`` under the machine-wide lock; quit after,
    ``Normal.dotm`` as it was."""
    STAGE.mkdir(parents=True, exist_ok=True)
    handle = open(LOCK, "a+")
    fcntl.flock(handle, fcntl.LOCK_EX)
    try:
        if running():
            raise SystemExit("Word is running: quit it first (it may be someone's)")
        saved = NORMAL.read_bytes() if NORMAL.exists() else None
        before = set(TEMPLATES.iterdir()) if TEMPLATES.exists() else set()
        first = STAGE / "start.docx"
        with zipfile.ZipFile(first, "w") as package:
            for name, text in EMPTY.items():
                package.writestr(name, text)
        try:
            subprocess.run(["open", "-g", "-a", APP, str(first), "--args", "-AppleLanguages", f"({language})",
                            "-AppleLocale", region], check=True)
            for _ in range(120):
                with contextlib.suppress(subprocess.TimeoutExpired):
                    if running() and osa('tell application "Microsoft Word" to get version', timeout=20)[0] == 0:
                        break
                time.sleep(1)
            time.sleep(3)
            osa(CLOSE_ALL, timeout=60)
            yield
        finally:
            quitted = quit_word()
            if saved is not None and (not NORMAL.exists() or NORMAL.read_bytes() != saved):
                NORMAL.write_bytes(saved)
            for path in set(TEMPLATES.iterdir()) - before:
                if path.name.startswith("Normal.dotm") and saved is not None and path.read_bytes() == saved:
                    path.unlink()
            first.unlink(missing_ok=True)
            if not quitted:
                raise SystemExit("Word did not quit: a prompt may be open in it")
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def measure(language: str, region: str) -> dict:
    out = STAGE / f"style-names-{language}.docx"
    out.unlink(missing_ok=True)
    with word(language, region):
        code, text, error = osa(SCRIPT, out, timeout=900)
    if code or "ERROR\t" in text or not out.exists():
        raise SystemExit(f"{language}: Word gave no answer: {error or text[-300:]}")
    saved = zipfile.ZipFile(out).read("word/styles.xml")
    out.unlink()
    return read(language, region, text, saved)


def read(language: str, region: str, text: str, styles_xml: bytes) -> dict:
    """One language's entry from the script's answer and the saved ``styles.xml``."""
    styles = ET.fromstring(styles_xml)
    by_size: dict[int, list[tuple[str, str]]] = {}
    for style in styles.iter(W + "style"):
        size = style.find(f"{W}rPr/{W}sz")
        if size is not None:
            by_size.setdefault(int(size.get(W + "val")), []).append(
                (style.find(W + "name").get(W + "val"), style.get(W + "type")))
    separator, names, unplaced = None, {}, []
    kinds = {"paragraph": "paragraph", "linked": "paragraph", "paragraph only": "paragraph",
             "character": "character", "table": "table"}
    for line in text.splitlines():
        cells = line.split("\t")
        if cells[0] == "SEP":
            separator = cells[1]
            continue
        if len(cells) < 5 or not cells[0].isdigit() or cells[1] != "true":
            continue
        kind = cells[2].replace("style type ", "")
        if kind not in kinds:
            continue                                       # list styles: no field names one
        index, local = int(cells[0]), cells[4]
        found = [entry for entry in by_size.get(round((FIRST - STEP + index * STEP) * 2), [])
                 if entry[1] == kinds[kind]]
        if not found:
            # Word kept the style's own size (the HTML character styles): not placed.
            unplaced.append(local)
            continue
        if len(found) > 1:
            raise SystemExit(f"{language}: style {index} ({local}) has {len(found)} stored names")
        names[found[0][0]] = local
    if not separator:
        raise SystemExit(f"{language}: no list separator")
    return {"region": region.replace("_", "-"), "list_separator": separator,
            "names": dict(sorted(names.items(), key=lambda item: item[0].casefold())),
            "not_placed": sorted(unplaced)}


def main(argv: list[str]) -> None:
    saved = None
    if argv[:1] == ["--saved"]:
        # A run kept from before: the script's answer and the document it saved.
        answer, document, argv = Path(argv[1]), Path(argv[2]), argv[3:]
        saved = (answer.read_text(encoding="utf-8"), zipfile.ZipFile(document).read("word/styles.xml"))
    if len(argv) < 2 or len(argv) % 2 or (saved and len(argv) != 2):
        raise SystemExit(__doc__)
    data = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    data.setdefault("measured", {})
    data.setdefault("languages", {})
    version = subprocess.run(["defaults", "read", f"{APP}/Contents/Info", "CFBundleShortVersionString"],
                             capture_output=True, text=True).stdout.strip()
    for language, region in zip(argv[::2], argv[1::2]):
        data["languages"][language] = read(language, region, *saved) if saved else measure(language, region)
        data["measured"][language] = f"Word {version} for Mac, {time.strftime('%Y-%m-%d')}"
        print(language, data["languages"][language]["list_separator"], len(data["languages"][language]["names"]))
    data["languages"] = dict(sorted(data["languages"].items()))
    data["measured"] = dict(sorted(data["measured"].items()))
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:])
