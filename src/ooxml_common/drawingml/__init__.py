"""DrawingML data that does not depend on any document model.

* :mod:`~ooxml_common.drawingml.guides` evaluates shape-guide formulas (``a:gd``);
* :mod:`~ooxml_common.drawingml.preset_specs` is the ECMA-376 preset geometry table;
* :mod:`~ooxml_common.drawingml.pattern` is the 54 ``a:pattFill`` presets.

Drawing any of them -- fills, outlines, the SVG path of a preset -- still happens in the
consumer, because pptx2svg's ``render/fill.py`` and ``render/geometry.py`` take its model's
DrawingML value types.  Lifting those types out is what lets those two modules follow.
"""
