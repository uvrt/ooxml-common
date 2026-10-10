"""``a:fld`` is read with its type, so a renderer can evaluate it (pptx2svg's
``resolve/fields.py``) rather than draw the text cached in the file."""

from __future__ import annotations

from xml.etree.ElementTree import fromstring

from ooxml_common.drawingml.read_text import parse_paragraph

A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'


def test_a_field_carries_its_type_and_its_cached_text():
    paragraph = parse_paragraph(fromstring(
        f'<a:p {A}><a:fld id="{{B6F15528-21DE-4FAA-801E-634DDDAF4B2B}}" type="slidenum">'
        '<a:rPr lang="en-US"/><a:t>‹#›</a:t></a:fld>'
        '<a:r><a:t> | </a:t></a:r><a:br/>'
        '<a:fld id="{C0A1E2D3-0000-4000-8000-000000000001}" type="datetime1"><a:t>1/1/2020</a:t>'
        "</a:fld></a:p>"
    ))
    assert [(run.text, run.field_type) for run in paragraph.runs] == [
        ("‹#›", "slidenum"), (" | ", None), ("\n", None), ("1/1/2020", "datetime1"),
    ]
    assert paragraph.runs[0].properties.lang == "en-US"
