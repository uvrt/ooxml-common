# What the siblings import

Back to the [README](../README.md).

pptx2svg, docx2svg, the agents (pptx-agent, docx-agent, xlsx-agent) and ooxml-edit (its
code, from 0.64.0, and its tests) import these names from ooxml-common, in their `src`, `tests` and `tools`. They are its
surface across repositories: their CI installs ooxml-common from `main`, so renaming or
removing one breaks a sibling at its next run, not on the pull request that made the
change. `tests/test_public_api.py` lists the same names, each with the siblings that use
it, and fails when one is gone -- or when this page and that list disagree.

To rename one, keep the old name as an alias for one release, with a comment saying who it
is kept for, and move the sibling to the new name. A sibling that starts importing a name
adds it here and to the test.

Each line is a module, then which siblings import what from it.

- `ooxml_common.chart.layout` -- docx2svg: `CHART_TEXT_BODY`, `ChartBuilder`, `ChartStyle`, `EMU_PER_POINT`, `accent_colors`, `default_font_size`, `drawable_plots`; pptx-agent: `DEFAULT_CHART_FONT_PT`, `powerpoint_auto_title_size`, `title_states_no_font`
- `ooxml_common.chart.read` -- docx2svg, pptx-agent: `AXIS_ELEMENTS`, `parse_chart_space`
- `ooxml_common.chart.rules` -- docx2svg: `WORD`
- `ooxml_common.dates` -- ooxml-edit: `DateNames`, `LANGUAGES`, `LCIDS`, `NAMES`, `names_tag`
- `ooxml_common.drawingml` -- pptx2svg: `preset_specs`
- `ooxml_common.drawingml.color` -- docx2svg, pptx2svg: `WORD`; pptx-agent, pptx2svg: `ColorContext`, `resolve_color`; docx2svg: `apply_transforms`, `apply_transforms_linear`; pptx-agent: `DEFAULT_COLOR_MAP`; pptx2svg: `ColorRules`, `POWERPOINT`, `build_effective_color_map`
- `ooxml_common.drawingml.context` -- docx2svg, pptx-agent: `RenderContext`
- `ooxml_common.drawingml.diagram` -- docx2svg, pptx2svg: `diagram_child_transform`, `diagram_drawing_part`; pptx2svg: `DIAGRAM_DRAWING_REL_TYPES`, `NO_CACHED_DRAWING`
- `ooxml_common.drawingml.effect` -- docx2svg: `render_effects`
- `ooxml_common.drawingml.elements` -- docx2svg, pptx2svg: `render_element`; pptx2svg: `UNIFORM_SCALE_TOLERANCE`, `render_group`, `swaps_group_axes`
- `ooxml_common.drawingml.fill` -- docx2svg: `ShapeFrame`, `render_arrowheads`, `render_fill_attrs`, `render_outline_attrs`
- `ooxml_common.drawingml.geometry` -- docx2svg, pptx2svg: `text_rect`; docx2svg: `path_ends`, `preset_path_data`, `spec_path_data`, `trim_path`
- `ooxml_common.drawingml.model` -- docx2svg, pptx2svg: `ColorTransform`, `EffectList`, `Glow`, `GradientFill`, `GradientStop`, `InnerShadow`, `NoFill`, `OuterShadow`, `Outline`, `PatternFill`, `ResolvedColor`, `SchemeColor`, `SoftEdge`, `SolidFill`, `SrgbColor`; pptx2svg: `ArrowEndpoint`, `ArrowSize`, `ArrowType`, `BiLevelEffect`, `BlipEffects`, `BlurEffect`, `ClrChangeEffect`, `ColorScheme`, `ColorTransformKind`, `CompoundLineType`, `CustomGeometry`, `CustomGeometryPath`, `DashStyle`, `DuotoneEffect`, `Fill`, `Geometry`, `ImageFill`, `ImageFillTile`, `ImageMimeType`, `LineCap`, `LineJoin`, `LumEffect`, `PresetGeometry`, `RectangleAlignment`, `SourceColor`, `SrcRect`, `StretchFillRect`, `SystemColor`, `TileInfo`, `Transform`
- `ooxml_common.drawingml.presets` -- docx-agent: `PRESETS`
- `ooxml_common.drawingml.read` -- docx2svg, pptx2svg: `parse_geometry_spec`, `parse_text_rect`; docx2svg: `parse_effect_list`, `parse_fill`, `parse_format_scheme`, `parse_line`, `parse_relative_rect`, `parse_shape_style`; pptx-agent: `parse_color_node`, `parse_color_scheme`; pptx2svg: `parse_color`
- `ooxml_common.drawingml.read_text` -- pptx-agent: `parse_text_body`
- `ooxml_common.drawingml.read_tree` -- docx2svg: `parse_shape_tree`
- `ooxml_common.drawingml.rules` -- pptx-agent, pptx2svg: `POWERPOINT`; docx2svg: `WORD`
- `ooxml_common.drawingml.scene` -- docx2svg, pptx2svg: `BodyProperties`, `ChartElement`, `ConnectorElement`, `GroupElement`, `Paragraph`, `ParagraphProperties`, `PercentSpacing`, `RunProperties`, `ShapeElement`, `TextBody`, `TextRun`; docx2svg: `CustomGeometry`, `Geometry`, `GradientFill`, `NoFill`, `Outline`, `PresetGeometry`, `ResolvedColor`, `SolidFill`, `Transform`; pptx2svg: `AutoNumBullet`, `AutoNumScheme`, `BlipBullet`, `BulletType`, `CellBorders`, `CharBullet`, `Chart3DView`, `ChartAxisScale`, `ChartData`, `ChartSeries`, `Hyperlink`, `ImageElement`, `NoBullet`, `PointsSpacing`, `SlideElement`, `SpacingValue`, `TabStop`, `TableCell`, `TableColumn`, `TableData`, `TableElement`, `TableRow`, `TextOutline`, `TextVerticalType`
- `ooxml_common.drawingml.source` -- docx2svg, pptx2svg: `SourceCustomGeometry`, `SourceGradientFill`, `SourceGroupFill`, `SourceNoFill`, `SourceOutline`, `SourcePatternFill`, `SourceSolidFill`, `SourceTransform`; docx2svg: `SchemeColor`; pptx2svg: `SourceBlipEffects`, `SourceEffectList`, `SourceFill`, `SourceFormatScheme`, `SourceGeometry`, `SourceGlow`, `SourceGradientStop`, `SourceImageFill`, `SourceImageFillTile`, `SourceInnerShadow`, `SourceOuterShadow`, `SourcePresetGeometry`, `SourceShapeStyle`, `SourceSoftEdge`, `SourceStyleReference`
- `ooxml_common.drawingml.source_tree` -- docx2svg, pptx2svg: `SourceBlipBullet`, `SourceConnector`, `SourceGroup`, `SourceParagraphProperties`, `SourceRunProperties`, `SourceShape`, `SourceTextBody`, `SourceTextBodyProperties`; pptx2svg: `SourceBulletType`, `SourceColorMap`, `SourceImage`, `SourceParagraph`, `SourcePlaceholder`, `SourceShapeNode`, `SourceTable`, `SourceTableCell`, `SourceTableRow`, `SourceTextRun`, `SourceTextStyle`, `SourceUnsupported`
- `ooxml_common.drawingml.svg` -- docx2svg: `Defs`, `num`
- `ooxml_common.drawingml.table_styles` -- pptx-agent, pptx2svg: `BUILTIN_TABLE_STYLES`; pptx-agent: `builtin_text_colors`; pptx2svg: `builtin_regions`, `color_parts`, `themed_style_xml`
- `ooxml_common.drawingml.text_chain` -- pptx-agent, pptx2svg: `DEFAULT_TEXT_STYLE`, `FONT_REF`, `LAYOUT`, `LIST_STYLE`, `MASTER`, `TABLE_STYLE`, `inherited_layers`; pptx-agent: `NOTHING`, `PARAGRAPH`, `RUN`, `master_text_style`, `source_name`; pptx2svg: `PLACEHOLDER`, `default_paragraph_fallback`, `holder_kind`
- `ooxml_common.drawingml.theme` -- docx-agent, pptx-agent: `APTOS_PANOSE`, `OFFICE_BACKGROUND_GRADIENT`, `OFFICE_FILL_GRADIENTS`, `OFFICE_MAJOR_FONT`, `OFFICE_MINOR_FONT`, `OFFICE_THEME_COLORS`; docx-agent: `WORD_LINE_WIDTHS`, `WORD_SCRIPT_FONTS`; pptx-agent: `POWERPOINT_LINE_WIDTHS`, `POWERPOINT_SCRIPT_FONTS`
- `ooxml_common.drawingml.textmeasure` -- pptx-agent: `MeasuredLine`, `MeasuredParagraph`, `TextBodyMeasure`, `measure_shape_text`, `measure_text_body`
- `ooxml_common.fonts` -- docx-agent, docx2svg, pptx-agent, pptx2svg: `bundle_dir`; pptx2svg: `BUNDLED_FAMILIES`
- `ooxml_common.fonts.check` -- pptx2svg: `FaceStatus`, `FontReport`, `VERDICTS`, `check_families`
- `ooxml_common.fonts.embedded` -- pptx-agent: `decoded_faces`, `forget_decoded`, `remember_decoded`
- `ooxml_common.fonts.eot` -- pptx2svg: `decode_eot`, `read_eot_header`
- `ooxml_common.fonts.office` -- docx-agent, docx2svg, pptx-agent, pptx2svg: `FONT_DIRS_ENV`, `user_font_dirs`; docx2svg, pptx2svg: `FONT_SUFFIXES`, `Face`, `OFFICE_CLOUD_FONTS`, `cloud_font_dirs`, `font_offsets`, `read_cmap`, `read_file`, `system_font_dirs`; docx2svg: `CSS_STRETCH`, `FontError`, `WORD`, `WORD_FONTS`, `css_match`, `decode_name`, `font_dirs`, `name_records`, `read_legacy_kern`, `table_directory`, `weight_order`, `with_subfolders`; pptx2svg: `HostFace`, `MACOS_FONT_DIRS`, `POWERPOINT`, `POWERPOINT_FONTS`, `face_bytes`, `faces_in`, `find`, `has_own_table`, `index`, `layout_metrics`, `metrics_of`, `user_families`, `user_search_dirs`
- `ooxml_common.fonts.rasterdb` -- docx-agent, docx2svg, pptx-agent, pptx2svg: `file_stamps`; docx-agent, pptx-agent: `resvg_system_dirs`; docx2svg, pptx2svg: `load_order`, `needed_font_files`; pptx2svg: `parsed_svg`
- `ooxml_common.fonts.sfnt` -- docx-agent, docx2svg, pptx-agent, pptx2svg: `relabel`; docx2svg, pptx2svg: `read_tables`, `write_sfnt`
- `ooxml_common.icc` -- pptx2svg: `SRGB_COLORANTS`, `ToSRGB`, `is_srgb`, `parse`
- `ooxml_common.imagemeta` -- docx-agent, docx2svg: `pixels_and_density`; pptx2svg: `icc_profile`
- `ooxml_common.kinds` -- docx-agent, pptx-agent, xlsx-agent: `KINDS`, `kind_for`, `kind_mismatch`; docx-agent, xlsx-agent: `REL_VBA_PROJECT`; docx-agent: `MAIN_CONTENT_TYPES`; xlsx-agent: `kind_of`, `main_content_type`
- `ooxml_common.locales` -- docx-agent, docx2svg, ooxml-edit, pptx-agent, pptx2svg, xlsx-agent: `EN_US`, `Locale`; xlsx-agent: `DATE_ORDERS`
- `ooxml_common.metafile` -- docx2svg, pptx2svg: `inline_metafile_images`, `metafile_to_svg`
- `ooxml_common.metafile.dib` -- pptx2svg: `BI_ALPHABITFIELDS`, `BI_BITFIELDS`, `BI_JPEG`, `BI_PNG`, `BI_RGB`, `BI_RLE4`, `BI_RLE8`, `DecodedImage`, `DecodedPixels`, `MAX_PIXELS`, `PNG_COMPRESS_LEVEL`, `decode_dib`, `dib_to_image`, `encode_png`, `split_packed_dib`
- `ooxml_common.numfmt` -- ooxml-edit, xlsx-agent: `DATE_KINDS`, `MEASURED`; ooxml-edit: `is_date_code`; xlsx-agent: `classify`
- `ooxml_common.opc` -- docx2svg: `OpcPackage`; ooxml-edit: `CONTENT_TYPES_PART`, `REL_CHART`, `REL_IMAGE`, `REL_OFFICE_DOCUMENT`, `normalize_part_path`
- `ooxml_common.svgimage` -- pptx-agent: `with_pixel_size`; pptx2svg: `natural_size`, `with_pixel_sized_images`
- `ooxml_common.text` -- pptx2svg: `kerning`, `metrics`
- `ooxml_common.text.fontmap` -- docx2svg, pptx2svg: `generic_family`; docx2svg: `SUBSTITUTIONS`, `metrics_for`, `substitution_for`; pptx2svg: `JAPANESE_GOTHIC`, `covers_east_asian`, `family_key`, `japanese_fallback`, `metrics_fallback_font`
- `ooxml_common.text.measure` -- docx2svg, pptx-agent: `DefaultTextMeasurer`; docx2svg: `font_kern_units`
- `ooxml_common.text.metrics` -- docx2svg: `METRICS`
- `ooxml_common.text.recorded_symbol_faces` -- docx2svg: `ADVANCES`, `DECORATIONS`, `METRICS`
- `ooxml_common.text.symbol_fonts` -- docx2svg: `to_unicode`; pptx2svg: `recorded_font_metrics`, `symbol_face`, `translate`
- `ooxml_common.units` -- ooxml-edit: `EMU_PER_POINT`; pptx-agent: `PX_PER_PT`, `emu_to_px`, `px_to_emu`
- `ooxml_common.xmlutil` -- docx2svg, pptx-agent: `child`, `local_name`; docx2svg: `attr`, `children`; ooxml-edit: `NS_R`
