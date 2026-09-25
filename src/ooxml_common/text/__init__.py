"""Font metrics and text measurement.

Line breaking stays with each consumer for now; see :mod:`ooxml_common`.
"""

from .fontmap import DEFAULT_FONT_MAPPING, create_font_mapping, font_family_value
from .measure import DefaultTextMeasurer, FontToolsTextMeasurer, TextMeasurer, is_cjk

__all__ = [
    "DEFAULT_FONT_MAPPING",
    "DefaultTextMeasurer",
    "FontToolsTextMeasurer",
    "TextMeasurer",
    "create_font_mapping",
    "font_family_value",
    "is_cjk",
]
