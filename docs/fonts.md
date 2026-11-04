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

**Keep them on the local disk.** Rasterising opens a face's file again for every run of
text it shapes. On WSL's mount of a Windows drive (`/mnt/c`: 9p, or WSL 1's drvfs) or a
network file system (NFS, SMB/CIFS, a FUSE network mount such as an Azure Files or S3
volume) each open crosses to the Windows host or another machine, and a slide that
rasterises in a fraction of a second on the local disk takes seconds. So the first time a folder in use is on one (and once for where
the library itself is installed, and the font bundle), a warning on the
`ooxml_common.fonts` logger names the folder, the file system and what to do: copy the
fonts into the machine's, container's or WSL's own file system -- bake them into the image,
or copy them to a local folder at start -- and point `OOXML_FONT_DIRS` / `font_dirs` there
(`ooxml_common.fonts.slowfs`; Linux only, from `/proc/self/mountinfo`; once per process
per folder).

## What the rasteriser is handed

resvg-py builds a new font database on every call from every file it is handed, so both
renderers hand it only the files an SVG can use: `ooxml_common.fonts.rasterdb`'s
`needed_font_files()` -- the faces filed under any name a run can resolve to, and the
faces that map a character some candidate face lacks, in resvg's load order. It draws
the same pixels as handing everything over (the module docstring has the reasoning, from
resvg's own matching and fallback), and answers `None` -- everything, as before -- where
an SVG could name a face some other way (CSS, `<use>`, a picture by reference) or the
system's fonts come from fontconfig. Nothing is copied: the files are named where they are.

## Text as outlines

`ooxml_common.outlines.outline_text(svg, fonts)` writes every `<text>` of an SVG as the
paths of its glyphs, so the SVG needs no font where it is viewed: a browser that cannot
be sent a face (its licence does not allow serving it as a web font) still draws the
page as the PNG draws it. The renderers call it for `ConvertOptions(text="outlines")`;
`fonts` is the `FontSetup` a rasterisation is handed (files, folders, whether the
system's fonts are loaded, the generic families), or a function giving it per
`font-family` value for a page drawn in passes.

**The PNG's faces, shaping and positions.** It follows resvg 0.48 (resvg-py 0.5), read
from its source: resvg's font database -- the system's fonts, then the files, then the
folders, each face under its typographic family, the CSS best match of the first family
of a stack any face answers to -- and usvg's fallback to the first loaded face that maps a
character the face lacks; harfrust's shaping (the default features: ligatures, contextual
alternates, kerning from `GPOS` or the legacy `kern` table, mark positioning; a variable
face at the weight, width and optical size asked for); usvg's layout (text chunks at each
positioned character, `text-anchor`, `dx`/`dy`, `baseline-shift`, `letter-spacing`,
`word-spacing`, `textLength`, underline and line-through from the face's own metrics);
TrueType outlines, components and `gvar` variations, and CFF. Rasterised with resvg, an
outlined page draws the pixels the text draws: over the pptx2svg and docx2svg corpora the
largest difference is an anti-aliased edge pixel or two (pptx2svg's and docx2svg's
CHANGELOGs have the numbers).

**What stays text**, reported as a `KeptText` with why: right-to-left and complex-script
text (Arabic, Hebrew, the Indic scripts, Thai...), a face whose glyphs are pictures (an
emoji face: `COLR`, `sbix`, `CBDT`, `SVG`) or `CFF2` outlines, a span no loaded face
answers to, `textPath`, `rotate`, vertical writing, small caps, and an SVG with a
`<style>` sheet. Text no face has a glyph for is drawn as the face's missing-glyph box,
as resvg draws it (`Outlined.missing`).

**Size.** A glyph is defined once per face, glyph and instance, in font units, and every
use of it is a reference (`<use>`) scaled by its run's size: repeated letters cost a
reference each. A run with a stroke, a translucent fill or a paint server is one path, as
resvg draws it. A page's outlines are still larger than its text -- a glyph outline is a
few hundred bytes -- and every page carries its own definitions.

**Selectable text.** `selectable=True` (`ConvertOptions(selectable_text=True)`) keeps
each text after its outlines, transparent (`fill-opacity` and `stroke-opacity` 0, marked
`data-text-layer`), so a viewer can select, search and copy it; the outlines are
`aria-hidden`. A browser lays that text out with its own fonts, so a selection follows
the drawn glyphs only approximately.

**What goes into the SVG: glyph shapes, not fonts.** The outlines are the shapes of the
glyphs the page uses, as paths; no font file, and no table of one (no character map, no
hinting, no kerning), is copied into the SVG, and the text cannot be set again in that
face from it. Whether a face's licence allows its glyphs to be shown as outlines in a
document is the licence's question, as it is for a PDF that draws them; this package
does not answer it.
