# Contributing

## Running the tests

```sh
pip install -e '.[dev]'
python -m pytest -q
```

Tests that need the OFL font files (`pptx2svg-fonts`, from a pptx2svg checkout) or fonts
installed by Microsoft Office skip with a reason when they are absent; CI runs without
them. The oracle measurements behind the tables (PowerPoint and Word output) are taken on
a local machine with Office, in pptx2svg and docx2svg, never on CI.

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
line to [CHANGELOG.md](CHANGELOG.md) when you bump the version.

## Names the siblings import

`tests/test_public_api.py` imports every name a sibling imports from here, and
[docs/used-by.md](docs/used-by.md) lists the same names, so renaming or removing one fails
this repository's CI instead of a sibling's. To rename one, keep the old name as an alias
for one release, with a comment saying who it is kept for, and move the sibling over; a
sibling that starts importing a name adds it to both. Siblings import no name that starts
with an underscore: give it a public name first.
