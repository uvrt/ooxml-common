"""What makes this package shareable, held as tests rather than as a hope.

Two promises: nothing here imports either consumer, and nothing here needs anything but
the standard library at runtime.  Both are easy to break by accident -- one convenient
``from pptx2svg import ...`` in a moved module would turn a shared package back into a
PowerPoint renderer's internals -- and neither would fail any other test.
"""

from __future__ import annotations

import ast
import importlib
import pkgutil
import sys
from pathlib import Path

import pytest

import ooxml_common

PACKAGE_DIR = Path(ooxml_common.__file__).resolve().parent
SOURCES = sorted(PACKAGE_DIR.rglob("*.py"))

#: Imported lazily inside a function, only when the caller asked for that capability,
#: and each behind an extra: ``[measure]``.
OPTIONAL = {"fontTools"}


def _imports(path: Path) -> list[tuple[str, int]]:
    """Every absolute module an import statement in ``path`` names, with its level."""
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.extend((alias.name, 0) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.append((node.module or "", node.level))
    return found


def test_the_package_has_the_modules_it_claims():
    names = {module.name for module in pkgutil.walk_packages([str(PACKAGE_DIR)], "ooxml_common.")}
    assert {
        "ooxml_common.opc",
        "ooxml_common.xmlutil",
        "ooxml_common.units",
        "ooxml_common.fonts",
        "ooxml_common.fonts.check",
        "ooxml_common.fonts.embedded",
        "ooxml_common.fonts.eot",
        "ooxml_common.fonts.mtx",
        "ooxml_common.fonts.sfnt",
        "ooxml_common.text",
        "ooxml_common.text.fontmap",
        "ooxml_common.text.kerning",
        "ooxml_common.text.measure",
        "ooxml_common.text.metrics",
        "ooxml_common.drawingml",
        "ooxml_common.drawingml.guides",
        "ooxml_common.drawingml.pattern",
        "ooxml_common.drawingml.preset_specs",
    } <= names


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: str(p.relative_to(PACKAGE_DIR)))
def test_no_module_imports_a_consumer(path):
    for module, level in _imports(path):
        if level:
            continue
        top = module.split(".")[0]
        assert top not in {"pptx2svg", "docx2svg", "pptx_agent"}, f"{path.name} imports {module}"


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: str(p.relative_to(PACKAGE_DIR)))
def test_every_runtime_import_is_the_standard_library(path):
    for module, level in _imports(path):
        if level or not module:
            continue
        top = module.split(".")[0]
        if top in ("ooxml_common", "__future__") or top in OPTIONAL:
            continue
        assert top in sys.stdlib_module_names, f"{path.name} imports {module}"


def test_every_module_imports_without_a_consumer_installed(monkeypatch):
    """Importing everything here must not reach for a consumer, even indirectly."""
    for blocked in ("pptx2svg", "docx2svg"):
        monkeypatch.setitem(sys.modules, blocked, None)  # `import pptx2svg` now raises
    for module in pkgutil.walk_packages([str(PACKAGE_DIR)], "ooxml_common."):
        importlib.import_module(module.name)


def test_no_font_file_is_in_the_package():
    """The tables are measurements; the files they were measured from are not ours."""
    for suffix in ("*.ttf", "*.ttc", "*.otf", "*.woff", "*.woff2", "*.eot"):
        assert not list(PACKAGE_DIR.rglob(suffix))
