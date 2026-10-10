"""An application's own font folders: given explicitly, or in ``OOXML_FONT_DIRS``.

The precedence both renderers follow: an explicit ``font_dirs`` (even an empty one), else
the environment variable, else nothing -- and whichever applies is searched before the
operating system's folders, added to them, never in their place.  The face is an OFL face
of the ``pptx2svg-fonts`` bundle, copied to a temporary folder; the tests that need it skip
without the bundle.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from ooxml_common.fonts import bundle_dir, office
from ooxml_common.fonts.check import check_families

BUNDLE = bundle_dir()
needs_bundle = pytest.mark.skipif(BUNDLE is None, reason="the pptx2svg-fonts bundle is not installed")


@pytest.fixture
def places(monkeypatch, tmp_path):
    """Empty system folders and cloud cache, no PowerPoint bundle, no environment variable."""
    roots = {name: tmp_path / name for name in ("system", "cloud", "app")}
    for root in roots.values():
        root.mkdir()
    monkeypatch.setattr(office, "OFFICE_CLOUD_FONTS", roots["cloud"])
    monkeypatch.setattr(office, "system_font_dirs", lambda: (roots["system"],))
    monkeypatch.delenv(office.FONT_DIRS_ENV, raising=False)
    return roots


def _app(bundle: Path) -> office.Application:
    template = office.POWERPOINT
    return office.Application(template.name, bundle, template.layout, template.drawing)


def test_the_environment_variable_is_a_path_list(monkeypatch, tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    monkeypatch.setenv(office.FONT_DIRS_ENV, os.pathsep.join([str(first), "", f" {second} "]))
    assert office.FONT_DIRS_ENV == "OOXML_FONT_DIRS"
    assert office.env_font_dirs() == (first, second)
    assert office.user_font_dirs() == (first, second)
    monkeypatch.delenv(office.FONT_DIRS_ENV)
    assert office.env_font_dirs() == ()
    assert office.env_font_dirs({office.FONT_DIRS_ENV: str(first)}) == (first,)


def test_an_explicit_argument_wins_over_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv(office.FONT_DIRS_ENV, str(tmp_path / "env"))
    assert office.user_font_dirs([tmp_path / "given"]) == (tmp_path / "given",)
    assert office.user_font_dirs(str(tmp_path / "one")) == (tmp_path / "one",)
    # An empty sequence is "none", not "read the environment".
    assert office.user_font_dirs([]) == ()


def test_subfolders_are_read_as_a_rasteriser_reads_them(tmp_path):
    (tmp_path / "fonts" / "licensed" / "deep").mkdir(parents=True)
    found = office.with_subfolders([tmp_path / "fonts", tmp_path / "absent", tmp_path / "fonts"])
    assert found == (tmp_path / "fonts", tmp_path / "fonts" / "licensed",
                     tmp_path / "fonts" / "licensed" / "deep")


@needs_bundle
def test_a_face_in_the_applications_folder_is_found_first(places, monkeypatch):
    app = _app(places["system"] / "no-bundle")
    shutil.copyfile(BUNDLE / "Cousine-Regular.ttf", places["app"] / "Cousine-Regular.ttf")
    shutil.copyfile(BUNDLE / "Cousine-Bold.ttf", places["system"] / "Cousine-Bold.ttf")

    # Not configured: only the system's copy.
    assert {face.location for face in office.find("Cousine", app)} == {"system"}

    # Given explicitly: the application's folder heads the search, and the system's
    # folders stay in it (the bold is still found there).
    dirs = office.search_dirs(app, font_dirs=[places["app"]])
    assert dirs[0] == (office.USER, places["app"])
    assert ("system", places["system"]) in dirs
    faces = office.find("Cousine", app, dirs=dirs)
    assert [face.location for face in faces] == [office.USER]
    assert office.metrics("Cousine", app, dirs=office.user_search_dirs([places["app"]])) is not None

    # From the environment, the same.
    monkeypatch.setenv(office.FONT_DIRS_ENV, str(places["app"]))
    assert office.search_dirs(app)[0] == (office.USER, places["app"])
    assert [face.location for face in office.find("Cousine", app)] == [office.USER]
    assert "cousine" in office.user_families()
    assert office.user_families([]) == frozenset()


@needs_bundle
def test_a_supplied_face_reports_exact(places):
    shutil.copyfile(BUNDLE / "Lato-Regular.ttf", places["app"] / "Lato-Regular.ttf")
    supplied = office.user_families([places["app"]])
    report = check_families(["Some Licensed Face", "Lato"], supplied=supplied | {"some licensed face"})
    verdicts = {face.requested: (face.verdict, face.reason) for face in report.faces}
    assert verdicts["Some Licensed Face"] == ("exact", "drawn with the face the application supplied (font_dirs)")
    assert verdicts["Lato"][0] == "exact"
