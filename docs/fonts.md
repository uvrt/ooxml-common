# Font files

Back to the [README](../README.md).

The `[fonts]` extra is the **`pptx2svg-fonts`** distribution: the OFL-licensed font
files the metric tables were measured from. It keeps its name and its home in the
pptx2svg repository (`packages/pptx2svg-fonts`) because renaming a distribution is
disruptive and `ooxml_common.fonts` finds it by import name alone, so where it lives
changes nothing here. It is not on PyPI either; install it from a pptx2svg checkout:

```sh
pip install -e ../pptx2svg/packages/pptx2svg-fonts
```

The tests that need the files skip with a reason when it is absent.

No Microsoft font file enters this repository in any form. The tables record
measurements of those designs, which are facts; the files are not ours to redistribute.
`ooxml_common.fonts.office` reads installed faces where they are, in memory, and only
numbers and paths leave it.

## An application's own font folders

An application that keeps licensed faces in a folder of its own -- not one the
operating system searches -- names it to both renderers in one of two ways:

- **explicitly**, `font_dirs=[...]` (pptx2svg's and docx2svg's `ConvertOptions`, their
  PNG functions and `--font-dir`; `Toolbox(font_dirs=...)` in the agent tool layer);
- **in the environment**, `OOXML_FONT_DIRS`: folders separated by `os.pathsep` (`:` on
  macOS and Linux, `;` on Windows).

Precedence: the explicit argument, else `OOXML_FONT_DIRS`, else none. An explicit empty
list means none: the variable is not read. Whichever applies is **added** to the
operating system's folders and searched **before** them; nothing is taken away. Folders
under a named folder are read too, as a rasteriser reads them.

`ooxml_common.fonts.office` resolves it for both renderers: `user_font_dirs()` (the
precedence), `with_subfolders()`, `user_search_dirs()` (filed as the `user` location,
which `find()` searches before every other) and `user_families()`; `search_dirs()` and
`find()` include the folders by default. `check_families(supplied=...)` grades a face
from them `exact`. As with every installed face, the files are read where they are; none
is copied.
