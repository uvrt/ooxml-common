"""DrawingML: its value types, and drawing them as SVG.

Data, needing no document model:

* :mod:`~ooxml_common.drawingml.model` -- the value types: colour choices and resolved
  colours, fills, outlines, effects, transforms, geometry and picture tiling;
* :mod:`~ooxml_common.drawingml.guides` evaluates shape-guide formulas (``a:gd``);
* :mod:`~ooxml_common.drawingml.preset_specs` is the ECMA-376 preset geometry pptx2svg
  draws from the specification, and :mod:`~ooxml_common.drawingml.presets` the rest --
  its ``PRESETS`` is every name ``ST_ShapeType`` allows;
* :mod:`~ooxml_common.drawingml.pattern` is the 54 ``a:pattFill`` presets, measured.

Drawing, moved from pptx2svg with their history:

* :mod:`~ooxml_common.drawingml.color` resolves a colour choice against a theme and a
  colour map, with every transform, under :class:`~ooxml_common.drawingml.color.ColorRules`
  where Word and PowerPoint measurably differ;
* :mod:`~ooxml_common.drawingml.geometry` draws a geometry -- as pptx2svg's one SVG
  element per shape, or as path data per ``a:path`` from the complete table;
* :mod:`~ooxml_common.drawingml.fill` gives fills, outlines and arrowheads as SVG
  attributes, registering gradients, patterns and markers on an
  :class:`~ooxml_common.drawingml.svg.SvgDefs`;
* :mod:`~ooxml_common.drawingml.effect` gives shadows, glow, soft edges and picture
  effects as SVG filters.

And the scene drawn with them, moved from pptx2svg with the charts that lower to it:

* :mod:`~ooxml_common.drawingml.scene` -- resolved text bodies, shapes, connectors,
  pictures, groups, tables and charts; :mod:`~ooxml_common.drawingml.source_tree` -- a
  shape tree and its text as the XML states them;
* :mod:`~ooxml_common.drawingml.read_tree` and :mod:`~ooxml_common.drawingml.read_text`
  read them, and :mod:`~ooxml_common.drawingml.diagram` finds SmartArt's cached drawing;
* :mod:`~ooxml_common.drawingml.elements`, :mod:`~ooxml_common.drawingml.shape` and
  :mod:`~ooxml_common.drawingml.textbody` draw them through a
  :class:`~ooxml_common.drawingml.context.RenderContext`, breaking lines with
  :mod:`~ooxml_common.drawingml.wrap`.

Each consumer keeps its own document layout and its own inheritance; the values, the
scene and their drawing are here.
"""
