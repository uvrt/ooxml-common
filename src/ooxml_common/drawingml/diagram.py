"""SmartArt: finding the laid-out drawing an application cached for a diagram.

A SmartArt diagram is authored as *data* -- a node tree plus a layout algorithm -- and
laying it out is a diagram engine.  It is also work the application has already done:
every time it saves, it writes the fully positioned result into a separate drawing part
(``dsp:drawing/dsp:spTree``), which is plain DrawingML -- a shape tree that
:func:`~ooxml_common.drawingml.read_tree.parse_shape_tree` reads as it reads a slide's.
So drawing SmartArt is finding that part, and this module finds it, for a slide's
``p:graphicFrame`` and a Word document's ``w:drawing`` alike: both name the diagram's
parts through the same ``dgm:relIds``.

Moved from pptx2svg's ``resolve/view.py``, where it was measured on 46 real decks written
by PowerPoint 12.0 to 16.0 (pptx2svg ROADMAP.md, Phase 2).  The functions take an
:class:`~ooxml_common.opc.OpcPackage` (or anything with its ``related_part``,
``related_parts_of_type``, ``first_related_part``, ``has_part`` and ``read_xml``) and the
part the frame sits in.
"""

from __future__ import annotations

from ..xmlutil import attr, child, descendants
from . import scene as m
from .read import parse_group_transforms

#: Relationship type from a SmartArt data-model part to its cached DrawingML rendering.
#: Two spellings exist for the same relationship -- Microsoft's own and the ISO/IEC
#: transitional one that ``purl.oclc.org`` hosts -- and which one appears depends on
#: which Office version and which save format wrote the file, so both are accepted.
DIAGRAM_DRAWING_REL_TYPES = (
    "http://schemas.microsoft.com/office/2007/relationships/diagramDrawing",
    "http://purl.oclc.org/ooxml/officeDocument/relationships/diagramDrawing",
)

#: Why a SmartArt frame can come out blank through no fault of the file.  The application
#: caches a laid-out DrawingML copy of every diagram, and reading that cache is the whole
#: of this SmartArt support: the layout algorithms in ``dgm:layoutDef`` are a diagram
#: engine and a project in their own right.  Office 2007 did not always write the cache,
#: and later versions sometimes write an empty one, so a perfectly valid file can carry a
#: diagram nothing here can draw.
NO_CACHED_DRAWING = (
    "has no cached DrawingML rendering.  PowerPoint caches a laid-out copy of every "
    "diagram and that copy is what we draw; Office 2007 did not always write one.  "
    "Laying the diagram out from its layout definition is not implemented, so the frame "
    "is left empty"
)


def diagram_drawing_part(package, owner: str, data_part: str) -> str | None:
    """Find the cached DrawingML rendering that belongs to one diagram.

    ``owner`` is the part the frame sits in (a slide, a Word document's body, header or
    footer) and ``data_part`` the data model its ``dgm:relIds@r:dm`` names.

    This is not where the obvious reading of the schema puts it.  ``dgm:relIds`` on the
    graphic frame names four parts -- data model, layout, quick style, colours -- and
    conspicuously not the drawing, because the cached drawing was added to the format
    after ``relIds`` was specified.  Microsoft keyed it through an extension instead::

        owner rels --r:dm--------------> ppt/diagrams/data1.xml
            data1.xml dgm:extLst/dsp:dataModelExt@relId = "rId6"
                                                 |
        owner rels --rId6 (diagramDrawing)-------+--> ppt/diagrams/drawing1.xml

    So the relationship id is written in the *data* part but resolved against the
    *owner's* relationships.  Every one of the 46 real PowerPoint decks checked that has
    a cached drawing at all does it this way, and none of them has a
    ``ppt/diagrams/_rels/data1.xml.rels`` for it to hang off.

    Two fallbacks follow, in decreasing confidence:

    * the data part's own relationships, which is what the ISO/transitional layout would
      imply and what an independent producer might reasonably write;
    * failing that, a diagram-drawing relationship on the owning part -- but only when
      there is exactly one, since a part with two SmartArt frames offers no way to tell
      which drawing belongs to which frame without the ``relId`` above.
    """
    relationship_id = data_model_drawing_rel_id(package, data_part)
    if relationship_id is not None:
        target = package.related_part(owner, relationship_id)
        if target is not None and package.has_part(target):
            return target

    for rel_type in DIAGRAM_DRAWING_REL_TYPES:
        target = package.first_related_part(data_part, rel_type)
        if target is not None and package.has_part(target):
            return target

    candidates = [
        target
        for rel_type in DIAGRAM_DRAWING_REL_TYPES
        for target in package.related_parts_of_type(owner, rel_type)
        if package.has_part(target)
    ]
    return candidates[0] if len(candidates) == 1 else None


def data_model_drawing_rel_id(package, data_part: str) -> str | None:
    """``dsp:dataModelExt@relId`` out of the data model part, if it carries one."""
    try:
        data_model = package.read_xml(data_part)
    except Exception:
        return None
    if data_model is None:
        return None
    for node in descendants(data_model, "dataModelExt"):
        relationship_id = attr(node, "relId")
        if relationship_id:
            return relationship_id
    return None


def diagram_child_transform(sp_tree, frame: m.Transform) -> m.Transform:
    """The coordinate space the cached diagram shapes were laid out in.

    PowerPoint writes ``dsp:spTree/dsp:grpSpPr/a:xfrm`` with ``chOff``/``chExt`` matching
    the graphic frame, so the normal group mapping scales the diagram into the frame.
    When the ``xfrm`` is absent -- some writers omit it -- the shapes are in a space whose
    origin is the frame's top-left and whose extent is the frame's, which is what this
    falls back to.  Note that it is *not* ``replace(frame)``: a group with no ``chOff``
    has children in absolute slide coordinates, whereas a diagram's are always relative
    to its own origin.
    """
    _, inner = parse_group_transforms(child(sp_tree, "grpSpPr"))
    if inner is None or not inner.width or not inner.height:
        return m.Transform(
            offset_x=0,
            offset_y=0,
            extent_width=frame.extent_width,
            extent_height=frame.extent_height,
        )
    return m.Transform(
        offset_x=inner.offset_x,
        offset_y=inner.offset_y,
        extent_width=inner.width,
        extent_height=inner.height,
    )
