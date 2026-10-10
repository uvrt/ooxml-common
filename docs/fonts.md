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

**Cached per process.** A folder and the folders under it are walked once; each later
lookup checks the modification time of every folder the walk found -- one stat per
folder, none per file, no listing -- and walks again only when one changed. Adding or
removing a font at any depth changes that folder's time (not its parent's, which is why
every folder is checked, not only the one named); a new subfolder changes its parent's.
A changed folder also drops the face index, font bytes and advance tables read from it, so
the next measurement sees the folder as it is. What a folder's time cannot show -- a font
file rewritten in place under the same name, a change within one tick of a file system
with coarse times (FAT's two seconds) -- `refresh_font_dirs()` picks up: it forgets every
walk, listing and index, the operating system's folders included (on macOS these are
indexed once per process). The cache is keyed by each folder as given, so callers with
different folders -- two agent sessions -- never see each other's faces. Office's
cloud-font cache is listed once and kept while its folder's time stands; the operating
system's folders elsewhere than macOS are walked and checked as an application's are.
