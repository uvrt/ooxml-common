"""The shared regional settings (:mod:`ooxml_common.locales`) and the chart numbers that
take them.

The Dutch locale below is built here as a caller would build it; the package lists only
the default.  Its chart readings are the ones measured on PowerPoint and Word 16 for Mac
on a Dutch machine (see :func:`ooxml_common.chart.layout.format_number`).
"""

from __future__ import annotations

import dataclasses
import pathlib
import pickle
import re
import xml.etree.ElementTree as ET

import pytest

import ooxml_common
from ooxml_common.chart.layout import ChartBuilder, ChartStyle, default_font_size, drawable_plots, format_number
from ooxml_common.chart.read import parse_chart_space
from ooxml_common.drawingml import scene as m
from ooxml_common.locales import (
    DATE_ORDERS,
    EN_US,
    KNOWN_LOCALES,
    Locale,
    canonical_language,
    locale_for,
)

DUTCH = Locale(decimal_separator=",", thousands_separator=".", date_order="dmy",
               language="nl-NL", list_separator=";")


# -- the type ----------------------------------------------------------------------------


def test_the_default_is_a_fixed_english_united_states():
    assert Locale() == EN_US
    assert (EN_US.decimal_separator, EN_US.thousands_separator, EN_US.date_order,
            EN_US.language, EN_US.list_separator) == (".", ",", "mdy", "en-US", ",")
    assert EN_US.primary_language == "en"


def test_a_locale_is_frozen_hashable_and_comparable():
    with pytest.raises(dataclasses.FrozenInstanceError):
        EN_US.decimal_separator = ","  # type: ignore[misc]
    same = Locale(decimal_separator=",", thousands_separator=".", date_order="dmy",
                  language="nl-nl", list_separator=";")
    assert same == DUTCH and hash(same) == hash(DUTCH)
    assert len({EN_US, Locale(), DUTCH, same}) == 2


def test_a_locale_survives_pickling_into_a_worker():
    for locale in (EN_US, DUTCH):
        assert pickle.loads(pickle.dumps(locale)) == locale


def test_a_variant_is_built_with_replace_and_validated_again():
    swiss = dataclasses.replace(EN_US, thousands_separator="'", language="de-CH", date_order="dmy")
    assert swiss.language == "de-CH" and swiss.decimal_separator == "."
    with pytest.raises(ValueError):
        dataclasses.replace(EN_US, thousands_separator=".")


@pytest.mark.parametrize("tag, expected", [
    ("en-US", "en-US"),
    ("EN-us", "en-US"),
    ("nl_be", "nl-BE"),
    ("zh-hant-tw", "zh-Hant-TW"),
    ("es-419", "es-419"),
    ("de", "de"),
    ("sl-IT-nedis", "sl-IT-nedis"),
])
def test_a_language_is_kept_in_bcp_47_case(tag, expected):
    assert canonical_language(tag) == expected
    assert Locale(language=tag).language == expected


@pytest.mark.parametrize("tag", ["", "e", "english", "en-", "en-USA1", "en US", "x-private", None, 1033])
def test_a_language_that_is_not_a_tag_is_refused(tag):
    with pytest.raises(ValueError):
        Locale(language=tag)  # type: ignore[arg-type]


@pytest.mark.parametrize("changes", [
    {"decimal_separator": ""},
    {"decimal_separator": ".."},
    {"decimal_separator": "a"},
    {"decimal_separator": "1"},
    {"decimal_separator": " "},
    {"decimal_separator": None},
    {"thousands_separator": "."},          # the decimal separator
    {"thousands_separator": "k"},
    {"list_separator": "."},               # the decimal separator
    {"list_separator": ";;"},
    {"date_order": "dym"},
    {"date_order": "DMY"},
    {"date_order": None},
])
def test_an_impossible_setting_is_refused(changes):
    with pytest.raises(ValueError):
        Locale(**changes)


def test_grouping_may_be_a_space_or_an_apostrophe():
    for grouping in (" ", " ", " ", "'"):
        assert Locale(decimal_separator=",", thousands_separator=grouping,
                      list_separator=";").thousands_separator == grouping
    assert DATE_ORDERS == ("dmy", "mdy", "ymd")


def test_number_text_swaps_both_separators_at_once():
    assert EN_US.number_text("1,234,567.89") == "1,234,567.89"
    assert DUTCH.number_text("1,234,567.89") == "1.234.567,89"
    assert dataclasses.replace(DUTCH, thousands_separator=" ").number_text("1,234.5") == "1 234,5"


# -- lookup by tag -----------------------------------------------------------------------


def test_only_the_default_is_listed():
    assert dict(KNOWN_LOCALES) == {"en-US": EN_US}
    with pytest.raises(TypeError):
        KNOWN_LOCALES["nl-NL"] = DUTCH  # type: ignore[index]


def test_locale_for_finds_a_listed_tag_in_any_case_and_guesses_nothing():
    assert locale_for("en-us") is EN_US
    with pytest.raises(LookupError):
        locale_for("en-GB")              # not another region's
    with pytest.raises(LookupError):
        locale_for("nl-NL")
    assert locale_for("NL_nl", known={"nl-NL": DUTCH}) is DUTCH
    with pytest.raises(ValueError):
        locale_for("not a tag")


def test_nothing_in_the_package_reads_the_machines_locale():
    """The same file renders the same on any server: no ``locale`` module, no
    ``strftime`` (whose names follow the process's ``LC_TIME``)."""
    root = pathlib.Path(ooxml_common.__file__).parent
    pattern = re.compile(r"^\s*(?:import\s+locale\b|from\s+locale\s+import)|\.strftime\(|getdefaultlocale|setlocale",
                         re.MULTILINE)
    offenders = [str(path.relative_to(root)) for path in root.rglob("*.py")
                 if pattern.search(path.read_text(encoding="utf-8"))]
    assert offenders == []


# -- chart numbers -----------------------------------------------------------------------


@pytest.mark.parametrize("value, code, english, dutch", [
    # Measured, PowerPoint and Word 16 for Mac on a Dutch machine (the Dutch column).
    (12.4, '"€"#,##0.0"m"', "€12.4m", "€12,4m"),
    (7.1, "#,##0.00_);(#,##0.00)", "7.10 ", "7,10 "),
    (5.2, "[$€-413] #,##0.0", "€ 5.2", "€ 5,2"),
    (20.0, '"€"0"m"', "€20m", "€20m"),
    # The same rule carried to grouping, General, percent and exponent.
    (1234567.0, "#,##0", "1,234,567", "1.234.567"),
    (1234567.0, '#,##0.0,,"M"', "1.2M", "1,2M"),
    (2.5, None, "2.5", "2,5"),
    (2.5, "General", "2.5", "2,5"),
    (0.125, "0.0%", "12.5%", "12,5%"),
    (12345.0, "0.00E+00", "1.23E+04", "1,23E+04"),
    (-1234.5, "#,##0.0;(#,##0.0)", "(1,234.5)", "(1.234,5)"),
    # The format's own text keeps its characters.
    (3.5, '"Total, net." 0.0', "Total, net. 3.5", "Total, net. 3,5"),
])
def test_format_number_prints_the_number_in_the_locales_separators(value, code, english, dutch):
    assert format_number(value, code) == english
    assert format_number(value, code, EN_US) == english
    assert format_number(value, code, DUTCH) == dutch


C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _scatter_xml() -> str:
    return f"""<c:chartSpace xmlns:c="{C}" xmlns:a="{A}"><c:chart><c:autoTitleDeleted val="1"/>
  <c:plotArea><c:scatterChart><c:scatterStyle val="lineMarker"/><c:varyColors val="0"/>
    <c:ser><c:idx val="0"/><c:order val="0"/>
      <c:dLbls><c:numFmt formatCode="0.00" sourceLinked="0"/><c:showLegendKey val="0"/><c:showVal val="1"/>
        <c:showCatName val="0"/><c:showSerName val="0"/><c:showPercent val="0"/><c:showBubbleSize val="0"/></c:dLbls>
      <c:xVal><c:numRef><c:numCache><c:formatCode>General</c:formatCode><c:ptCount val="2"/>
        <c:pt idx="0"><c:v>1.5</c:v></c:pt><c:pt idx="1"><c:v>2.5</c:v></c:pt></c:numCache></c:numRef></c:xVal>
      <c:yVal><c:numRef><c:numCache><c:formatCode>General</c:formatCode><c:ptCount val="2"/>
        <c:pt idx="0"><c:v>1.25</c:v></c:pt><c:pt idx="1"><c:v>3.75</c:v></c:pt></c:numCache></c:numRef></c:yVal>
    </c:ser><c:axId val="1"/><c:axId val="2"/></c:scatterChart>
    <c:valAx><c:axId val="1"/><c:delete val="0"/><c:axPos val="b"/><c:numFmt formatCode="0.0" sourceLinked="0"/>
      <c:majorTickMark val="none"/><c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/><c:crossAx val="2"/></c:valAx>
    <c:valAx><c:axId val="2"/><c:delete val="0"/><c:axPos val="l"/><c:numFmt formatCode="0.0" sourceLinked="0"/>
      <c:majorTickMark val="none"/><c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/><c:crossAx val="1"/></c:valAx>
  </c:plotArea></c:chart></c:chartSpace>"""


def _build(locale: Locale | None):
    source = parse_chart_space(ET.fromstring(_scatter_xml()))
    plots = drawable_plots(source)
    extra = {} if locale is None else {"locale": locale}
    builder = ChartBuilder(
        source, plots[0], width_pt=480, height_pt=300,
        style=ChartStyle(font_family="Arial", font_size=default_font_size(source),
                         color=m.ResolvedColor(hex="#000000"), accents=[m.ResolvedColor(hex="#1F4E79")]),
        resolve_fill=lambda fill: None, resolve_outline=lambda outline: None,
        resolve_text=lambda rich, text, size, align: None, plots=plots, **extra,
    )
    children, data = builder.build()
    texts = [run.text for child in children
             if isinstance(child, m.ShapeElement) and child.text_body
             for paragraph in child.text_body.paragraphs for run in paragraph.runs]
    return builder, texts, data


def test_a_chart_builder_prints_its_labels_in_its_locale_and_keeps_its_data_invariant():
    builder, english, data = _build(None)
    assert builder.locale is EN_US
    assert "1.25" in english and "3.75" in english       # data labels
    assert any(re.fullmatch(r"\d+\.\d", text) for text in english)   # a tick label
    assert _build(EN_US)[1] == english

    _, dutch, dutch_data = _build(DUTCH)
    assert "1,25" in dutch and "3,75" in dutch
    assert [text.replace(",", ".") for text in dutch] == english
    # What the chart plots is data, not a label: the same in every locale.
    assert dutch_data == data
    assert data.series[0].categories == ["1.5", "2.5"]
