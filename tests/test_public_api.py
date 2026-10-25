"""The names the sibling repositories import from ooxml-common: renaming one fails here.

Siblings' CI installs ooxml-common from ``main``, so a rename that breaks one shows only at
its next run, not on the pull request that made it.  ``USED_BY`` is that surface, each name
with the siblings that import it (in their ``src``, ``tests`` and ``tools``);
docs/used-by.md documents it, and ``test_the_documented_names_are_these`` holds the two to
the same names.

A sibling that starts importing a name: add it here and there.  Renaming one: keep the old
name as an alias for one release, with a comment saying who it is kept for (``OLD_NAMES``),
and move the sibling to the new one.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

DOC = Path(__file__).resolve().parent.parent / "docs/used-by.md"
SECTION = None

#: module -> {name: the siblings that import it}.
USED_BY: dict[str, dict[str, str]] = {
    "ooxml_common.chart.layout": {
        "CHART_TEXT_BODY": "docx2svg",
        "ChartBuilder": "docx2svg",
        "ChartStyle": "docx2svg",
        "DEFAULT_CHART_FONT_PT": "pptx-agent",
        "EMU_PER_POINT": "docx2svg",
        "accent_colors": "docx2svg",
        "default_font_size": "docx2svg",
        "drawable_plots": "docx2svg",
        "powerpoint_auto_title_size": "pptx-agent",
        "title_states_no_font": "pptx-agent",
    },
    "ooxml_common.chart.read": {
        "AXIS_ELEMENTS": "docx2svg, pptx-agent",
        "parse_chart_space": "docx2svg, pptx-agent",
    },
    "ooxml_common.chart.rules": {
        "WORD": "docx2svg",
    },
    "ooxml_common.dates": {
        "DateNames": "ooxml-edit",
        "LANGUAGES": "ooxml-edit",
        "LCIDS": "ooxml-edit",
        "NAMES": "ooxml-edit",
        "names_tag": "ooxml-edit",
    },
    "ooxml_common.drawingml": {
        "preset_specs": "pptx2svg",
    },
    "ooxml_common.drawingml.color": {
        "ColorContext": "pptx-agent, pptx2svg",
        "ColorRules": "pptx2svg",
        "DEFAULT_COLOR_MAP": "pptx-agent",
        "POWERPOINT": "pptx2svg",
        "WORD": "docx2svg, pptx2svg",
        "apply_transforms": "docx2svg",
        "apply_transforms_linear": "docx2svg",
        "build_effective_color_map": "pptx2svg",
        "resolve_color": "pptx-agent, pptx2svg",
    },
    "ooxml_common.drawingml.context": {
        "RenderContext": "docx2svg, pptx-agent",
    },
    "ooxml_common.drawingml.diagram": {
        "DIAGRAM_DRAWING_REL_TYPES": "pptx2svg",
        "NO_CACHED_DRAWING": "pptx2svg",
        "diagram_child_transform": "docx2svg, pptx2svg",
        "diagram_drawing_part": "docx2svg, pptx2svg",
    },
    "ooxml_common.drawingml.effect": {
        "render_effects": "docx2svg",
    },
    "ooxml_common.drawingml.elements": {
        "UNIFORM_SCALE_TOLERANCE": "pptx2svg",
        "render_element": "docx2svg, pptx2svg",
        "render_group": "pptx2svg",
        "swaps_group_axes": "pptx2svg",
    },
    "ooxml_common.drawingml.fill": {
        "ShapeFrame": "docx2svg",
        "render_arrowheads": "docx2svg",
        "render_fill_attrs": "docx2svg",
        "render_outline_attrs": "docx2svg",
    },
    "ooxml_common.drawingml.geometry": {
        "path_ends": "docx2svg",
        "preset_path_data": "docx2svg",
        "spec_path_data": "docx2svg",
        "text_rect": "docx2svg, pptx2svg",
        "trim_path": "docx2svg",
    },
    "ooxml_common.drawingml.model": {
        "ArrowEndpoint": "pptx2svg",
        "ArrowSize": "pptx2svg",
        "ArrowType": "pptx2svg",
        "BiLevelEffect": "pptx2svg",
        "BlipEffects": "pptx2svg",
        "BlurEffect": "pptx2svg",
        "ClrChangeEffect": "pptx2svg",
        "ColorScheme": "pptx2svg",
        "ColorTransform": "docx2svg, pptx2svg",
        "ColorTransformKind": "pptx2svg",
        "CompoundLineType": "pptx2svg",
        "CustomGeometry": "pptx2svg",
        "CustomGeometryPath": "pptx2svg",
        "DashStyle": "pptx2svg",
        "DuotoneEffect": "pptx2svg",
        "EffectList": "docx2svg, pptx2svg",
        "Fill": "pptx2svg",
        "Geometry": "pptx2svg",
        "Glow": "docx2svg, pptx2svg",
        "GradientFill": "docx2svg, pptx2svg",
        "GradientStop": "docx2svg, pptx2svg",
        "ImageFill": "pptx2svg",
        "ImageFillTile": "pptx2svg",
        "ImageMimeType": "pptx2svg",
        "InnerShadow": "docx2svg, pptx2svg",
        "LineCap": "pptx2svg",
        "LineJoin": "pptx2svg",
        "LumEffect": "pptx2svg",
        "NoFill": "docx2svg, pptx2svg",
        "OuterShadow": "docx2svg, pptx2svg",
        "Outline": "docx2svg, pptx2svg",
        "PatternFill": "docx2svg, pptx2svg",
        "PresetGeometry": "pptx2svg",
        "RectangleAlignment": "pptx2svg",
        "ResolvedColor": "docx2svg, pptx2svg",
        "SchemeColor": "docx2svg, pptx2svg",
        "SoftEdge": "docx2svg, pptx2svg",
        "SolidFill": "docx2svg, pptx2svg",
        "SourceColor": "pptx2svg",
        "SrcRect": "pptx2svg",
        "SrgbColor": "docx2svg, pptx2svg",
        "StretchFillRect": "pptx2svg",
        "SystemColor": "pptx2svg",
        "TileInfo": "pptx2svg",
        "Transform": "pptx2svg",
    },
    "ooxml_common.drawingml.presets": {
        "PRESETS": "docx-agent",
    },
    "ooxml_common.drawingml.read": {
        "parse_color": "pptx2svg",
        "parse_color_node": "pptx-agent",
        "parse_color_scheme": "pptx-agent",
        "parse_effect_list": "docx2svg",
        "parse_fill": "docx2svg",
        "parse_format_scheme": "docx2svg",
        "parse_geometry_spec": "docx2svg, pptx2svg",
        "parse_line": "docx2svg",
        "parse_relative_rect": "docx2svg",
        "parse_shape_style": "docx2svg",
        "parse_text_rect": "docx2svg, pptx2svg",
    },
    "ooxml_common.drawingml.read_text": {
        "parse_text_body": "pptx-agent",
    },
    "ooxml_common.drawingml.read_tree": {
        "parse_shape_tree": "docx2svg",
    },
    "ooxml_common.drawingml.rules": {
        "POWERPOINT": "pptx-agent, pptx2svg",
        "WORD": "docx2svg",
    },
    "ooxml_common.drawingml.scene": {
        "AutoNumBullet": "pptx2svg",
        "AutoNumScheme": "pptx2svg",
        "BlipBullet": "pptx2svg",
        "BodyProperties": "docx2svg, pptx2svg",
        "BulletType": "pptx2svg",
        "CellBorders": "pptx2svg",
        "CharBullet": "pptx2svg",
        "Chart3DView": "pptx2svg",
        "ChartAxisScale": "pptx2svg",
        "ChartData": "pptx2svg",
        "ChartElement": "docx2svg, pptx2svg",
        "ChartSeries": "pptx2svg",
        "ConnectorElement": "docx2svg, pptx2svg",
        "CustomGeometry": "docx2svg",
        "Geometry": "docx2svg",
        "GradientFill": "docx2svg",
        "GroupElement": "docx2svg, pptx2svg",
        "Hyperlink": "pptx2svg",
        "ImageElement": "pptx2svg",
        "NoBullet": "pptx2svg",
        "NoFill": "docx2svg",
        "Outline": "docx2svg",
        "Paragraph": "docx2svg, pptx2svg",
        "ParagraphProperties": "docx2svg, pptx2svg",
        "PercentSpacing": "docx2svg, pptx2svg",
        "PointsSpacing": "pptx2svg",
        "PresetGeometry": "docx2svg",
        "ResolvedColor": "docx2svg",
        "RunProperties": "docx2svg, pptx2svg",
        "ShapeElement": "docx2svg, pptx2svg",
        "SlideElement": "pptx2svg",
        "SolidFill": "docx2svg",
        "SpacingValue": "pptx2svg",
        "TabStop": "pptx2svg",
        "TableCell": "pptx2svg",
        "TableColumn": "pptx2svg",
        "TableData": "pptx2svg",
        "TableElement": "pptx2svg",
        "TableRow": "pptx2svg",
        "TextBody": "docx2svg, pptx2svg",
        "TextOutline": "pptx2svg",
        "TextRun": "docx2svg, pptx2svg",
        "TextVerticalType": "pptx2svg",
        "Transform": "docx2svg",
    },
    "ooxml_common.drawingml.source": {
        "SchemeColor": "docx2svg",
        "SourceBlipEffects": "pptx2svg",
        "SourceCustomGeometry": "docx2svg, pptx2svg",
        "SourceEffectList": "pptx2svg",
        "SourceFill": "pptx2svg",
        "SourceFormatScheme": "pptx2svg",
        "SourceGeometry": "pptx2svg",
        "SourceGlow": "pptx2svg",
        "SourceGradientFill": "docx2svg, pptx2svg",
        "SourceGradientStop": "pptx2svg",
        "SourceGroupFill": "docx2svg, pptx2svg",
        "SourceImageFill": "pptx2svg",
        "SourceImageFillTile": "pptx2svg",
        "SourceInnerShadow": "pptx2svg",
        "SourceNoFill": "docx2svg, pptx2svg",
        "SourceOuterShadow": "pptx2svg",
        "SourceOutline": "docx2svg, pptx2svg",
        "SourcePatternFill": "docx2svg, pptx2svg",
        "SourcePresetGeometry": "pptx2svg",
        "SourceShapeStyle": "pptx2svg",
        "SourceSoftEdge": "pptx2svg",
        "SourceSolidFill": "docx2svg, pptx2svg",
        "SourceStyleReference": "pptx2svg",
        "SourceTransform": "docx2svg, pptx2svg",
    },
    "ooxml_common.drawingml.source_tree": {
        "SourceBlipBullet": "docx2svg, pptx2svg",
        "SourceBulletType": "pptx2svg",
        "SourceColorMap": "pptx2svg",
        "SourceConnector": "docx2svg, pptx2svg",
        "SourceGroup": "docx2svg, pptx2svg",
        "SourceImage": "pptx2svg",
        "SourceParagraph": "pptx2svg",
        "SourceParagraphProperties": "docx2svg, pptx2svg",
        "SourcePlaceholder": "pptx2svg",
        "SourceRunProperties": "docx2svg, pptx2svg",
        "SourceShape": "docx2svg, pptx2svg",
        "SourceShapeNode": "pptx2svg",
        "SourceTable": "pptx2svg",
        "SourceTableCell": "pptx2svg",
        "SourceTableRow": "pptx2svg",
        "SourceTextBody": "docx2svg, pptx2svg",
        "SourceTextBodyProperties": "docx2svg, pptx2svg",
        "SourceTextRun": "pptx2svg",
        "SourceTextStyle": "pptx2svg",
        "SourceUnsupported": "pptx2svg",
    },
    "ooxml_common.drawingml.svg": {
        "Defs": "docx2svg",
        "num": "docx2svg",
    },
    "ooxml_common.drawingml.table_styles": {
        "BUILTIN_TABLE_STYLES": "pptx-agent, pptx2svg",
        "builtin_regions": "pptx2svg",
        "builtin_text_colors": "pptx-agent",
        "color_parts": "pptx2svg",
        "themed_style_xml": "pptx2svg",
    },
    "ooxml_common.drawingml.text_chain": {
        "DEFAULT_TEXT_STYLE": "pptx-agent, pptx2svg",
        "FONT_REF": "pptx-agent, pptx2svg",
        "LAYOUT": "pptx-agent, pptx2svg",
        "LIST_STYLE": "pptx-agent, pptx2svg",
        "MASTER": "pptx-agent, pptx2svg",
        "NOTHING": "pptx-agent",
        "PARAGRAPH": "pptx-agent",
        "PLACEHOLDER": "pptx2svg",
        "RUN": "pptx-agent",
        "TABLE_STYLE": "pptx-agent, pptx2svg",
        "default_paragraph_fallback": "pptx2svg",
        "holder_kind": "pptx2svg",
        "inherited_layers": "pptx-agent, pptx2svg",
        "master_text_style": "pptx-agent",
        "source_name": "pptx-agent",
    },
    "ooxml_common.drawingml.theme": {
        "APTOS_PANOSE": "docx-agent, pptx-agent",
        "OFFICE_BACKGROUND_GRADIENT": "docx-agent, pptx-agent",
        "OFFICE_FILL_GRADIENTS": "docx-agent, pptx-agent",
        "OFFICE_MAJOR_FONT": "docx-agent, pptx-agent",
        "OFFICE_MINOR_FONT": "docx-agent, pptx-agent",
        "OFFICE_THEME_COLORS": "docx-agent, pptx-agent",
        "POWERPOINT_LINE_WIDTHS": "pptx-agent",
        "POWERPOINT_SCRIPT_FONTS": "pptx-agent",
        "WORD_LINE_WIDTHS": "docx-agent",
        "WORD_SCRIPT_FONTS": "docx-agent",
    },
    "ooxml_common.drawingml.textmeasure": {
        "MeasuredLine": "pptx-agent",
        "MeasuredParagraph": "pptx-agent",
        "TextBodyMeasure": "pptx-agent",
        "measure_shape_text": "pptx-agent",
        "measure_text_body": "pptx-agent",
    },
    "ooxml_common.fonts": {
        "BUNDLED_FAMILIES": "pptx2svg",
        "bundle_dir": "docx-agent, docx2svg, pptx-agent, pptx2svg",
    },
    "ooxml_common.fonts.check": {
        "FaceStatus": "pptx2svg",
        "FontReport": "pptx2svg",
        "VERDICTS": "pptx2svg",
        "check_families": "pptx2svg",
    },
    "ooxml_common.fonts.embedded": {
        "decoded_faces": "pptx-agent",
        "forget_decoded": "pptx-agent",
        "remember_decoded": "pptx-agent",
    },
    "ooxml_common.fonts.eot": {
        "decode_eot": "pptx2svg",
        "read_eot_header": "pptx2svg",
    },
    "ooxml_common.fonts.office": {
        "CSS_STRETCH": "docx2svg",
        "FONT_DIRS_ENV": "docx-agent, docx2svg, pptx-agent, pptx2svg",
        "FONT_SUFFIXES": "docx2svg, pptx2svg",
        "Face": "docx2svg, pptx2svg",
        "FontError": "docx2svg",
        "HostFace": "pptx2svg",
        "MACOS_FONT_DIRS": "pptx2svg",
        "OFFICE_CLOUD_FONTS": "docx2svg, pptx2svg",
        "POWERPOINT": "pptx2svg",
        "POWERPOINT_FONTS": "pptx2svg",
        "WORD": "docx2svg",
        "WORD_FONTS": "docx2svg",
        "cloud_font_dirs": "docx2svg, pptx2svg",
        "css_match": "docx2svg",
        "decode_name": "docx2svg",
        "face_bytes": "pptx2svg",
        "faces_in": "pptx2svg",
        "find": "pptx2svg",
        "font_dirs": "docx2svg",
        "font_offsets": "docx2svg, pptx2svg",
        "has_own_table": "pptx2svg",
        "index": "pptx2svg",
        "layout_metrics": "pptx2svg",
        "metrics_of": "pptx2svg",
        "name_records": "docx2svg",
        "read_cmap": "docx2svg, pptx2svg",
        "read_file": "docx2svg, pptx2svg",
        "read_legacy_kern": "docx2svg",
        "system_font_dirs": "docx2svg, pptx2svg",
        "table_directory": "docx2svg",
        "user_families": "pptx2svg",
        "user_font_dirs": "docx-agent, docx2svg, pptx-agent, pptx2svg",
        "user_search_dirs": "pptx2svg",
        "weight_order": "docx2svg",
        "with_subfolders": "docx2svg",
    },
    "ooxml_common.fonts.rasterdb": {
        "file_stamps": "docx-agent, docx2svg, pptx-agent, pptx2svg",
        "load_order": "docx2svg, pptx2svg",
        "needed_font_files": "docx2svg, pptx2svg",
        "parsed_svg": "pptx2svg",
        "resvg_system_dirs": "docx-agent, pptx-agent",
    },
    "ooxml_common.fonts.sfnt": {
        "read_tables": "docx2svg, pptx2svg",
        "relabel": "docx-agent, docx2svg, pptx-agent, pptx2svg",
        "write_sfnt": "docx2svg, pptx2svg",
    },
    "ooxml_common.icc": {
        "SRGB_COLORANTS": "pptx2svg",
        "ToSRGB": "pptx2svg",
        "is_srgb": "pptx2svg",
        "parse": "pptx2svg",
    },
    "ooxml_common.imagemeta": {
        "icc_profile": "pptx2svg",
        "pixels_and_density": "docx-agent, docx2svg",
    },
    "ooxml_common.kinds": {
        "KINDS": "docx-agent, pptx-agent, xlsx-agent",
        "MAIN_CONTENT_TYPES": "docx-agent",
        "REL_VBA_PROJECT": "docx-agent, xlsx-agent",
        "kind_for": "docx-agent, pptx-agent, xlsx-agent",
        "kind_mismatch": "docx-agent, pptx-agent, xlsx-agent",
        "kind_of": "xlsx-agent",
        "main_content_type": "xlsx-agent",
    },
    "ooxml_common.locales": {
        "DATE_ORDERS": "xlsx-agent",
        "EN_US": "docx-agent, docx2svg, ooxml-edit, pptx-agent, pptx2svg, xlsx-agent",
        "Locale": "docx-agent, docx2svg, ooxml-edit, pptx-agent, pptx2svg, xlsx-agent",
    },
    "ooxml_common.metafile": {
        "inline_metafile_images": "docx2svg, pptx2svg",
        "metafile_to_svg": "docx2svg, pptx2svg",
    },
    "ooxml_common.metafile.dib": {
        "BI_ALPHABITFIELDS": "pptx2svg",
        "BI_BITFIELDS": "pptx2svg",
        "BI_JPEG": "pptx2svg",
        "BI_PNG": "pptx2svg",
        "BI_RGB": "pptx2svg",
        "BI_RLE4": "pptx2svg",
        "BI_RLE8": "pptx2svg",
        "DecodedImage": "pptx2svg",
        "DecodedPixels": "pptx2svg",
        "MAX_PIXELS": "pptx2svg",
        "PNG_COMPRESS_LEVEL": "pptx2svg",
        "decode_dib": "pptx2svg",
        "dib_to_image": "pptx2svg",
        "encode_png": "pptx2svg",
        "split_packed_dib": "pptx2svg",
    },
    "ooxml_common.numfmt": {
        "DATE_KINDS": "ooxml-edit, xlsx-agent",
        "MEASURED": "ooxml-edit, xlsx-agent",
        "classify": "xlsx-agent",
        "is_date_code": "ooxml-edit",
    },
    "ooxml_common.opc": {
        "CONTENT_TYPES_PART": "docx2svg, ooxml-edit",
        "OpcPackage": "docx2svg",
        "REL_CHART": "ooxml-edit",
        "REL_HYPERLINK": "docx2svg",
        "REL_IMAGE": "docx2svg, ooxml-edit",
        "REL_OFFICE_DOCUMENT": "docx2svg, ooxml-edit",
        "REL_THEME": "docx2svg",
        "Relationship": "docx2svg",
        "normalize_part_path": "docx2svg, ooxml-edit",
        "rels_path_for": "docx2svg",
    },
    "ooxml_common.svgimage": {
        "natural_size": "pptx2svg",
        "with_pixel_size": "pptx-agent",
        "with_pixel_sized_images": "pptx2svg",
    },
    "ooxml_common.text": {
        "kerning": "pptx2svg",
        "metrics": "pptx2svg",
    },
    "ooxml_common.text.fontmap": {
        "JAPANESE_GOTHIC": "pptx2svg",
        "SUBSTITUTIONS": "docx2svg",
        "covers_east_asian": "pptx2svg",
        "family_key": "pptx2svg",
        "generic_family": "docx2svg, pptx2svg",
        "japanese_fallback": "pptx2svg",
        "metrics_fallback_font": "pptx2svg",
        "metrics_for": "docx2svg",
        "substitution_for": "docx2svg",
    },
    "ooxml_common.text.measure": {
        "DefaultTextMeasurer": "docx2svg, pptx-agent",
        "font_kern_units": "docx2svg",
    },
    "ooxml_common.text.metrics": {
        "METRICS": "docx2svg",
    },
    "ooxml_common.text.recorded_symbol_faces": {
        "ADVANCES": "docx2svg",
        "DECORATIONS": "docx2svg",
        "METRICS": "docx2svg",
    },
    "ooxml_common.text.symbol_fonts": {
        "recorded_font_metrics": "pptx2svg",
        "symbol_face": "pptx2svg",
        "to_unicode": "docx2svg",
        "translate": "pptx2svg",
    },
    "ooxml_common.units": {
        "EMU_PER_POINT": "ooxml-edit",
        "PX_PER_PT": "pptx-agent",
        "emu_to_px": "pptx-agent",
        "px_to_emu": "pptx-agent",
    },
    "ooxml_common.xmlutil": {
        "NS_R": "ooxml-edit",
        "attr": "docx2svg",
        "child": "docx2svg, pptx-agent",
        "children": "docx2svg",
        "descendants": "docx2svg",
        "element_child": "docx2svg",
        "element_children": "docx2svg",
        "local_name": "docx2svg, pptx-agent",
        "parse_xml": "docx2svg",
    },
}

#: (module, old underscore name) -> the public name; aliases kept for one release.
OLD_NAMES: dict[tuple[str, str], str] = {
    ("ooxml_common.fonts.sfnt", "_directory"): "read_tables",
    ("ooxml_common.imagemeta", "_pixels_and_density"): "pixels_and_density",
    ("ooxml_common.text.measure", "_font_kern_units"): "font_kern_units",
}


def _used() -> list[tuple[str, str]]:
    return [(module, name) for module, names in USED_BY.items() for name in names]


@pytest.mark.parametrize(("module", "name"), _used())
def test_a_name_a_sibling_imports_is_there(module, name):
    owner = importlib.import_module(module)
    if hasattr(owner, name):
        return
    try:
        importlib.import_module(f"{module}.{name}")     # a submodule not imported yet
    except ImportError:
        pytest.fail(f"{module}.{name} is gone, and {USED_BY[module][name]} import it: keep the "
                    "old name as an alias for one release and move them to the new one")


def test_siblings_import_no_private_name():
    private = [f"{module}.{name}" for module, name in _used() if name.startswith("_")]
    assert not private, f"give these a public name (keep the old one as an alias): {private}"


def test_an_old_name_is_the_public_one():
    for (module, old), new in OLD_NAMES.items():
        owner = importlib.import_module(module)
        assert getattr(owner, old) is getattr(owner, new), f"{module}.{old} is not {new}"
        assert new in USED_BY.get(module, {}), f"{module}.{new} is missing from USED_BY"


def _documented() -> set[tuple[str, str]]:
    lines = DOC.read_text(encoding="utf-8").splitlines()
    if SECTION is not None:
        start, depth = lines.index(SECTION) + 1, len(SECTION) - len(SECTION.lstrip("#"))
        end = next((i for i in range(start, len(lines)) if lines[i].startswith("#")
                    and len(lines[i]) - len(lines[i].lstrip("#")) <= depth), len(lines))
        lines = lines[start:end]
    found = set()
    for line in lines:
        if line.startswith("- `"):
            module, *names = re.findall(r"`([^`]+)`", line)
            found.update((module, name) for name in names)
    return found


def test_the_documented_names_are_these():
    documented, used = _documented(), set(_used())
    assert not used - documented, f"add to {DOC.name}: {sorted(used - documented)}"
    extra = sorted(documented - used)
    assert not extra, f"add to USED_BY, or take out of {DOC.name}: {extra}"
