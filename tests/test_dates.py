"""Date serials printed in their format code (``ooxml_common.dates``), on a chart's
categories, and PowerPoint's automatic chart title.

Measured on PowerPoint and Word for Mac, 16 October 2026: date categories kept as serials
46027, 46063 and 46096 (5 January, 10 February and 15 March 2026) under three codes; the
names are Excel's for each listed locale.  The automatic title's sizes are PowerPoint's
PDF export's exact sizes.
"""

from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET

import pytest

from ooxml_common import dates
from ooxml_common.chart import rules
from ooxml_common.chart.layout import (ChartBuilder, ChartStyle, default_font_size, drawable_plots,
                                       powerpoint_auto_title, powerpoint_auto_title_size)
from ooxml_common.chart.read import parse_chart_space
from ooxml_common.drawingml import scene as m
from ooxml_common.locales import EN_US, Locale

C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
SERIALS = (46027, 46063, 46096)
DUTCH = Locale(decimal_separator=",", thousands_separator=".", date_order="dmy",
               language="nl-BE", list_separator=";")


@pytest.mark.parametrize("code, shown", [
    (r"[$-413]d\ mmmm\ yyyy", ["5 januari 2026", "10 februari 2026", "15 maart 2026"]),
    (r"[$-407]d\ mmm\ yyyy", ["5 Jan 2026", "10 Feb 2026", "15 Mär 2026"]),
    ("[$-409]dd/mm/yyyy", ["05/01/2026", "10/02/2026", "15/03/2026"]),
])
def test_the_measured_codes_print_as_office_drew_them(code, shown):
    for locale in (EN_US, DUTCH):
        assert [dates.format_serial(value, code, locale) for value in SERIALS] == shown


def test_a_prefix_names_the_language_and_its_spelling_as_a_tag_too():
    assert dates.language_of_code(r"[$-413]d\ mmmm") == "nl-NL"
    assert dates.language_of_code("[$-nl-NL]d mmmm") == "nl-NL"
    assert dates.language_of_code("[$-10407]d mmmm") == "de-DE"   # a calendar's upper bits
    assert dates.language_of_code("[$-411]d mmmm") is None        # no measured names
    assert dates.language_of_code("d mmmm") is None
    assert dates.format_serial(46083, "[$-nl-NL]d mmmm yyyy") == "2 maart 2026"
    assert [dates.format_serial(46083, f"[$-{lcid:X}]mmmm") for lcid in
            (0x409, 0x809, 0x413, 0x813, 0x407, 0x40C, 0xC0A, 0x410)] == [
        "March", "March", "maart", "maart", "März", "mars", "marzo", "marzo"]


def test_a_code_without_a_prefix_is_named_in_the_locales_language():
    # Excel's unprefixed codes and PowerPoint's date axis took the interface language.
    assert dates.format_serial(46083, "d mmm yyyy") == "2 Mar 2026"
    assert dates.format_serial(46083, "d mmm yyyy", DUTCH) == "2 mrt 2026"
    assert dates.format_serial(46083, "dddd", Locale(language="fr-FR")) == "lundi"
    # A language with no measured names falls back to en-US's, and says which it took.
    japanese = Locale(language="ja-JP")
    assert dates.format_serial(46083, "mmmm", japanese) == "March"
    assert dates.names_language("mmmm", japanese) == "en-US"
    assert dates.names_language("[$-411]mmmm", DUTCH) == "nl-BE"


def test_every_token_and_literal():
    day = 46083   # Monday 2 March 2026
    assert dates.format_serial(day, "d dd ddd dddd") == "2 02 Mon Monday"
    assert dates.format_serial(day, "m mm mmm mmmm mmmmm") == "3 03 Mar March M"
    assert dates.format_serial(day, "yy yyyy") == "26 2026"
    assert dates.format_serial(day, "[$-413]mmmmm") == "m"
    assert dates.format_serial(day, 'd "de" mmmm "de" yyyy', Locale(language="es-ES")) == \
        "2 de marzo de 2026"
    assert dates.format_serial(day, r"d\.m\.yyyy") == "2.3.2026"
    assert dates.format_serial(day, "[Blue]dd-mm-yyyy;@") == "02-03-2026"
    assert dates.format_serial(day, "DD/MM/YYYY") == "02/03/2026"
    assert dates.format_serial(day + 0.75, "d mmm") == "2 Mar"   # the time of day dropped


def test_a_slash_is_written_as_the_code_writes_it():
    # Office shows the viewer's region separator; Locale states none, so `/` stays `/`
    # whatever the number separators are.
    german = Locale(decimal_separator=",", thousands_separator=".", date_order="dmy",
                    language="de-DE", list_separator=";")
    assert dates.format_serial(46083, "dd/mm/yyyy", german) == "02/03/2026"
    assert dates.format_serial(46083, "dd-mm-yyyy", german) == "02-03-2026"


@pytest.mark.parametrize("code", ["h:mm", "d/m/yy h:mm", "[h]:mm", "mm:ss", "d mmm AM/PM",
                                  "ddddd", "mmmmmm", "y", "yyy", "0.00", "General", "@",
                                  "[<100]d mmm", "e"])
def test_what_is_not_printed(code):
    assert dates.format_serial(46083, code) is None


def test_serials_that_name_no_day():
    for value in (-1, 0, 60, 2958466, float("nan"), float("inf")):
        assert dates.date_of_serial(value) is None
    assert dates.date_of_serial(1) == dt.date(1900, 1, 1)
    assert dates.date_of_serial(59) == dt.date(1900, 2, 28)
    assert dates.date_of_serial(61) == dt.date(1900, 3, 1)
    assert dates.date_of_serial(2958465) == dt.date(9999, 12, 31)
    assert dates.date_of_serial(0, date1904=True) == dt.date(1904, 1, 1)
    assert dates.date_of_serial(44565, date1904=True) == dt.date(2026, 1, 5)


def test_is_date_code():
    assert dates.is_date_code(r"[$-413]d\ mmmm\ yyyy")
    assert dates.is_date_code("h:mm")
    for code in (None, "", "General", "@", "0.00", '"d" 0', r"\d0", "[$€-413] #,##0.0"):
        assert not dates.is_date_code(code)


# -- agreement with ooxml-edit's copy -----------------------------------------------------


def test_the_names_agree_with_ooxml_edits():
    edit = pytest.importorskip("ooxml_edit.dates")
    assert dict(dates.LCIDS) == dict(edit.LCIDS)
    assert {tag: tuple(names) for tag, names in dates.NAMES.items()} == \
        {tag: tuple(names) for tag, names in edit.NAMES.items()}


@pytest.mark.parametrize("pattern", ["d mmmm yyyy", "dd/mm/yyyy", "ddd d mmm yy", "dddd, mmmmm",
                                     'd "de" mmmm', "yyyy-mm-dd", "m.d.yyyy"])
def test_a_code_ooxml_edit_keeps_prints_what_it_writes(pattern):
    edit = pytest.importorskip("ooxml_edit.dates")
    for tag in edit.NAMES:
        locale = Locale(language=tag)
        for day in (dt.date(2026, 1, 5), dt.date(2026, 3, 2), dt.date(2026, 12, 25)):
            code = edit.format_code(pattern, locale)
            assert dates.format_serial(edit.serial(day), code) == \
                edit.format_date(day, pattern, locale), (tag, code)


# -- on a chart ---------------------------------------------------------------------------


def _chart_xml(code: str, *, date1904: bool = False, title: str = "", series: int = 1,
               wide: int | None = None, deleted: str | None = None) -> str:
    points = "".join(f'<c:pt idx="{i}"><c:v>{v}</c:v></c:pt>' for i, v in enumerate(SERIALS))
    sers = "".join(f"""
    <c:ser><c:idx val="{n}"/><c:order val="{n}"/>
      <c:tx><c:strRef><c:strCache><c:ptCount val="1"/><c:pt idx="0"><c:v>Series {n}</c:v></c:pt>
        </c:strCache></c:strRef></c:tx>
      <c:cat><c:numRef><c:numCache><c:formatCode>{code}</c:formatCode><c:ptCount val="3"/>{points}
        </c:numCache></c:numRef></c:cat>
      <c:val><c:numRef><c:numCache><c:formatCode>General</c:formatCode><c:ptCount val="3"/>
        <c:pt idx="0"><c:v>3</c:v></c:pt><c:pt idx="1"><c:v>5</c:v></c:pt><c:pt idx="2"><c:v>4</c:v></c:pt>
      </c:numCache></c:numRef></c:val>
    </c:ser>""" for n in range(series))
    txpr = ("" if wide is None else
            f'<c:txPr><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="{wide}"/></a:pPr>'
            '<a:endParaRPr lang="en-US"/></a:p></c:txPr>')
    deleted_xml = "" if deleted is None else f'<c:autoTitleDeleted val="{deleted}"/>'
    return f"""<c:chartSpace xmlns:c="{C}" xmlns:a="{A}"><c:date1904 val="{int(date1904)}"/>
  <c:chart>{title}{deleted_xml}
  <c:plotArea><c:barChart><c:barDir val="col"/><c:grouping val="clustered"/><c:varyColors val="0"/>
    {sers}<c:gapWidth val="80"/><c:axId val="1"/><c:axId val="2"/></c:barChart>
    <c:catAx><c:axId val="1"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/>
      <c:axPos val="b"/><c:numFmt formatCode="General" sourceLinked="1"/><c:majorTickMark val="none"/>
      <c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/><c:crossAx val="2"/></c:catAx>
    <c:valAx><c:axId val="2"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/>
      <c:axPos val="l"/><c:numFmt formatCode="General" sourceLinked="1"/><c:majorTickMark val="out"/>
      <c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/><c:crossAx val="1"/></c:valAx>
  </c:plotArea></c:chart>{txpr}</c:chartSpace>"""


def _text_body(rich, text, size, align):
    """What a caller resolves a title to: each run's stated size, weight and face."""
    if rich is None:
        runs = [m.TextRun(text=text, properties=m.RunProperties(font_size=size))]
    else:
        runs = [m.TextRun(text=run.text, properties=m.RunProperties(
            font_size=run.properties.font_size, bold=bool(run.properties.bold),
            font_family=run.properties.typeface)) for paragraph in rich.paragraphs
            for run in paragraph.runs]
    return m.TextBody(paragraphs=[m.Paragraph(runs=runs, properties=m.ParagraphProperties(alignment=align))])


def _build(xml: str, locale: Locale = EN_US, chart_rules=rules.POWERPOINT):
    source = parse_chart_space(ET.fromstring(xml))
    plots = drawable_plots(source)
    builder = ChartBuilder(
        source, plots[0], width_pt=480, height_pt=300,
        style=ChartStyle(font_family="Arial", font_size=default_font_size(source),
                         color=m.ResolvedColor(hex="#000000"), accents=[m.ResolvedColor(hex="#1F4E79")]),
        resolve_fill=lambda fill: None, resolve_outline=lambda outline: None,
        resolve_text=_text_body, plots=plots, locale=locale, rules=chart_rules,
    )
    children, data = builder.build()
    runs = [run for child in children if isinstance(child, m.ShapeElement) and child.text_body
            for paragraph in child.text_body.paragraphs for run in paragraph.runs]
    return runs, data


@pytest.mark.parametrize("chart_rules", [rules.POWERPOINT, rules.WORD])
def test_a_charts_date_categories_are_drawn_as_dates(chart_rules):
    runs, data = _build(_chart_xml(r"[$-413]d\ mmmm\ yyyy"), chart_rules=chart_rules)
    texts = [run.text for run in runs]
    assert {"5 januari 2026", "10 februari 2026", "15 maart 2026"} <= set(texts)
    assert "46027" not in texts
    # The categories as data stay the reader's invariant text.
    assert data.categories == ["46027", "46063", "46096"]


def test_an_unprefixed_date_axis_takes_the_locales_names():
    texts = {run.text for run in _build(_chart_xml("d mmm"), DUTCH)[0]}
    assert {"5 jan", "10 feb", "15 mrt"} <= texts


def test_date1904_counts_from_1904():
    texts = {run.text for run in _build(_chart_xml("yyyy-mm-dd", date1904=True))[0]}
    assert {"2030-01-06", "2030-02-11", "2030-03-16"} <= texts


# -- PowerPoint's automatic title ---------------------------------------------------------

AUTO = "<c:title><c:overlay val=\"0\"/></c:title>"
AUTO_UNSIZED = ('<c:title><c:overlay val="0"/><c:txPr><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr/>'
                '</a:pPr><a:endParaRPr lang="en-US"/></a:p></c:txPr></c:title>')


@pytest.mark.parametrize("wide, size", [(800, 10.0), (1000, 12.0), (1100, 13.0), (2400, 29.0),
                                        (None, 18.0)])
def test_the_automatic_title_is_1_2_times_the_charts_text_rounded(wide, size):
    for title in (AUTO, AUTO_UNSIZED):   # an unsized title txPr changes nothing
        source = parse_chart_space(ET.fromstring(_chart_xml("General", title=title, wide=wide)))
        assert powerpoint_auto_title_size(source) == size
        runs, data = _build(_chart_xml("General", title=title, wide=wide))
        title_runs = [run for run in runs if run.text == "Series 0"]
        assert [(run.properties.font_size, run.properties.bold, run.properties.font_family)
                for run in title_runs] == [(size, True, "+mn-lt")]
        assert data.title == "Series 0"


def test_a_half_point_rounds_up():
    source = parse_chart_space(ET.fromstring(_chart_xml("General", title=AUTO, wide=1125)))
    assert powerpoint_auto_title_size(source) == 14.0   # 13.5


def test_the_titles_own_text_properties_win():
    title = ('<c:title><c:overlay val="0"/><c:txPr><a:bodyPr/><a:lstStyle/><a:p><a:pPr>'
             '<a:defRPr sz="1400" b="0"><a:latin typeface="Georgia"/></a:defRPr></a:pPr>'
             '<a:endParaRPr lang="en-US"/></a:p></c:txPr></c:title>')
    source = parse_chart_space(ET.fromstring(_chart_xml("General", title=title, wide=2400)))
    body = powerpoint_auto_title(source, "Series 0")
    run = body.paragraphs[0].runs[0]
    assert (run.text, run.properties.font_size, run.properties.bold, run.properties.typeface) == \
        ("Series 0", 14.0, False, "Georgia")


@pytest.mark.parametrize("title, series, deleted", [
    (AUTO, 2, None),     # several series: PowerPoint's own words, not measured
    (AUTO, 1, "1"),      # deleted
    ("", 1, "0"),        # no c:title
])
def test_no_automatic_title_is_drawn(title, series, deleted):
    runs, data = _build(_chart_xml("General", title=title, series=series, deleted=deleted))
    assert data.title is None
    assert not [run for run in runs if run.properties.bold]


def test_a_rich_title_is_unchanged():
    title = ('<c:title><c:tx><c:rich><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="en-US"/>'
             '<a:t>Probe</a:t></a:r></a:p></c:rich></c:tx><c:overlay val="0"/></c:title>')
    runs, data = _build(_chart_xml("General", title=title, wide=2400))
    assert [(run.properties.font_size, run.properties.bold) for run in runs if run.text == "Probe"] == \
        [(18.0, False)]


def test_words_automatic_title_is_left_to_the_caller():
    runs, data = _build(_chart_xml("General", title=AUTO, wide=800), chart_rules=rules.WORD)
    # The caller's resolver gets no rich text and sizes it itself (docx2svg does).
    assert [(run.properties.font_size, run.properties.bold) for run in runs if run.text == "Series 0"] == \
        [(18.0, False)]
