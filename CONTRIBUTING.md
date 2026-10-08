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

Open a pull request against `main`; CI must pass. Keep the package standard-library only
at runtime and free of imports from its consumers (`tests/test_independence.py`). Add a
line to [CHANGELOG.md](CHANGELOG.md) when you bump the version.
