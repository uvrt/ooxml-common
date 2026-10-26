# Contributing

## Running the tests

```sh
pip install -e '.[dev]'
python -m pytest -q
ruff check .
mypy
```

CI's build job runs `ruff check .` and `mypy` at the versions the `dev` extra pins; both
read their settings from pyproject.toml. A finding is fixed, not silenced: a `# noqa` or a
`# type: ignore[code]` only on its line and with the reason next to it.

Tests that need the OFL font files (`pptx2svg-fonts`, from a pptx2svg checkout) or fonts
installed by Microsoft Office skip with a reason when they are absent; CI runs without
them. The oracle measurements behind the tables (PowerPoint and Word output) are taken on
a local machine with Office, in pptx2svg and docx2svg, never on CI.

## The goldens

`tests/test_goldens.py` holds what this package produces from the made-up inputs under
`tests/fixtures/` -- chart layouts, shape trees, scenes, preset geometry, metafiles -- byte
for byte, in `tests/golden/` (`tests/goldens.py` says how). A golden is a photograph of
this package's own output, not a statement that it is right. After a change that is meant
to change the output:

```sh
python -m pytest tests/test_goldens.py --update-goldens
```

rewrites the files and skips rather than passes; read the diff before committing it, and
say in the commit which change the new bytes are. A failed comparison writes the new output
to `tests/golden-diffs/` (ignored). Every fixture names its source in its manifest
(`tests/fixtures/*.json`); only made-up inputs go there.

Coverage: `python -m coverage run -m pytest -q && python -m coverage report` (CI fails one
leg under the floor in `.github/workflows/ci.yml`). Set `COVERAGE_CORE=sysmon` on Python
3.12 and later; it is several times faster.

## What never goes in the repository

- Microsoft font files, in any form. Measurements of them are facts; the files are not ours.
- Office output: PDFs, rasters or SVGs exported by PowerPoint or Word.
- Third-party documents.

## Changes

Open a pull request against `main`; CI must pass. CI also runs pptx2svg's and docx2svg's
suites, at their `main`, against the change (the `downstream` job). A change a renderer
must follow is red there until it is merged with the renderer's matching pull request
right after it; say so on the pull request. Keep the package standard-library only at
runtime and free of imports from its consumers (`tests/test_independence.py`). Add a
line to [CHANGELOG.md](CHANGELOG.md) when you bump the version: CI's `build` job checks
that `pyproject.toml`'s version is the one its top section names, and `__version__` the
same (`tools/check_version.py`). Each version that reaches `main` is tagged `v<version>`
on that commit by the tag workflow (`.github/workflows/tag.yml`).

## Names the siblings import

`tests/test_public_api.py` imports every name a sibling imports from here, and
[docs/used-by.md](docs/used-by.md) lists the same names, so renaming or removing one fails
this repository's CI instead of a sibling's. To rename one, keep the old name as an alias
for one release, with a comment saying who it is kept for, and move the sibling over; a
sibling that starts importing a name adds it to both. Siblings import no name that starts
with an underscore: give it a public name first.
