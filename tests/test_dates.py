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
                                       powerpoint_auto_title, powerpoint_auto_title_size,
                                       title_states_defaults, title_states_no_font)
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


@pytest.mark.parametrize("code, shown", [
    # What Excel for Mac stored for a region's or a language's prefix, 2026-10-17, and
    # the names it showed there: the language's.
    ("[$-80C]", "lundi 2 mars"), ("[$-100C]", "lundi 2 mars"), ("[$-C]", "lundi 2 mars"),
    ("[$-1809]", "Monday 2 March"), ("[$-9]", "Monday 2 March"), ("[$-7]", "Montag 2 März"),
    ("[$-13]", "maandag 2 maart"),
    # A tag in the code, as a file may have it ([$-en-BE] measured: English).
    ("[$-en-BE]", "Monday 2 March"), ("[$-fr-BE]", "lundi 2 mars"),
    ("[$-de-BE]", "Montag 2 März"), ("[$-de]", "Montag 2 März"),
    # Measured on PowerPoint and Word for Mac, 2026-10-17 (Office's re-saved ids too).
    ("[$-80A]", "lunes 2 marzo"), ("[$-A]", "lunes 2 marzo"), ("[$-es-MX]", "lunes 2 marzo"),
    ("[$-810]", "lunedì 2 marzo"), ("[$-10]", "lunedì 2 marzo"),
    ("[$-it-CH]", "lunedì 2 marzo"),
])
def test_a_regions_prefix_names_the_date_in_its_language(code, shown):
    for locale in (EN_US, DUTCH):
        assert dates.format_serial(46083, code + r"dddd\ d\ mmmm", locale) == shown


@pytest.mark.parametrize("code, shown", [
    ("[$-C0A]", "lu. 2 mar. · mi. 2 sep."),
    ("[$-80A]", "lun. 2 mar. · mié. 2 sep."),
    ("[$-A]", "lun 2 mar · mié 2 set"),
])
def test_spanish_abbreviations_are_each_regions_own(code, shown):
    assert " · ".join(dates.format_serial(value, code + r"ddd\ d\ mmm")
                      for value in (46083, 46267)) == shown


def test_another_spanish_region_is_not_given_es_es_names():
    assert dates.language_of_code("[$-es-AR]mmmm") is None
    assert dates.names_tag("es-AR") is None
    assert dates.format_serial(46083, "[$-es-AR]mmmm", DUTCH) == "maart"   # the locale's


def test_a_regions_prefix_says_which_names_it_took():
    assert dates.language_of_code("[$-80C]mmmm") == "fr-BE"
    assert dates.names_language("[$-80C]mmmm") == "fr-FR"
    assert dates.names_language("[$-en-BE]mmmm", DUTCH) == "en-US"
    assert dates.language_of_code("[$-pt-BR]mmmm") is None       # no measured names
    assert dates.names_tag("de-CH") == "de-DE" and dates.names_tag("ja-JP") is None
    assert all(tag in dates.NAMES for tag in dates.LANGUAGES.values())


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
    # A region of a language with names takes that language's, as a prefix does; a bare
    # [$] (Excel: the machine's language) is the locale's too.
    belgian_french = Locale(language="fr-BE")
    assert dates.format_serial(46083, "dddd d mmmm", belgian_french) == "lundi 2 mars"
    assert dates.format_serial(46083, "[$]mmmm", belgian_french) == "mars"
    assert dates.names_language("mmmm", Locale(language="en-BE")) == "en-US"


# Measured in PowerPoint for Mac's charts, 2026-10-17, under each interface language
# (region Dutch (Belgium)): 5 January, 17 March, 20 May and 31 December 2026.
INTERFACE_DAYS = (46027, 46098, 46162, 46387)


@pytest.mark.parametrize("language, shown", [
    ("fr-FR", "lun. 5 janv · mar. 17 mars · mer. 20 mai · jeu. 31 déc"),
    ("fr-BE", "lun. 5 janv · mar. 17 mars · mer. 20 mai · jeu. 31 déc"),
    ("es-ES", "lun 5 ene · mar 17 mar · mié 20 may · jue 31 dic"),
    ("es-MX", "lun 5 ene · mar 17 mar · mié 20 may · jue 31 dic"),
    ("en-GB", "Mon 5 Jan · Tue 17 Mar · Wed 20 May · Thu 31 Dec"),
    ("de-DE", "Mo 5 Jan · Di 17 Mär · Mi 20 Mai · Do 31 Dez"),
    ("nl-NL", "ma 5 jan · di 17 mrt · wo 20 mei · do 31 dec"),
])
def test_an_unprefixed_code_takes_the_interface_languages_own_names(language, shown):
    locale = Locale(language=language)
    assert " · ".join(dates.format_serial(value, r"ddd\ d\ mmm", locale)
                      for value in INTERFACE_DAYS) == shown


@pytest.mark.parametrize("language, shown", [
    ("fr-FR", "lundi 5 janvier · mardi 17 mars · mercredi 20 mai · jeudi 31 décembre"),
    ("es-MX", "lunes 5 enero · martes 17 marzo · miércoles 20 mayo · jueves 31 diciembre"),
])
def test_an_unprefixed_codes_full_names_are_the_languages(language, shown):
    assert " · ".join(dates.format_serial(value, r"dddd\ d\ mmmm", Locale(language=language))
                      for value in INTERFACE_DAYS) == shown


def test_a_prefix_keeps_its_own_names_under_any_interface_language():
    for language in ("fr-FR", "es-ES", "nl-BE", "en-US"):
        locale = Locale(language=language)
        assert dates.format_serial(46027, r"[$-40C]ddd\ d\ mmm", locale) == "lun. 5 janv."
        assert dates.format_serial(46027, r"[$-80C]d\ mmm", locale) == "5 janv."
        assert dates.format_serial(46027, r"[$-C0A]ddd\ d\ mmm", locale) == "lu. 5 ene."
        assert dates.format_serial(46027, r"[$-80A]ddd\ d\ mmm", locale) == "lun. 5 ene."


# Measured in PowerPoint for Mac's charts and Excel, 2026-10-17, under each interface
# language: the 15th of every month of 2026, and 5 to 11 January 2026.
MONTHS_15TH = [(dt.date(2026, month, 15) - dt.date(1899, 12, 30)).days for month in range(1, 13)]
WEEK = range(46027, 46034)


@pytest.mark.parametrize("language, months, days", [
    ("fr-FR", "janv févr mars avr mai juin juil août sept oct nov déc",
     "lun. mar. mer. jeu. ven. sam. dim."),
    ("es-ES", "ene feb mar abr may jun jul ago sept oct nov dic", "lun mar mié jue vie sáb dom"),
    ("it-IT", "gen feb mar apr mag giu lug ago set ott nov dic", "lun mar mer gio ven sab dom"),
    ("nl-NL", "jan feb mrt apr mei jun jul aug sep okt nov dec", "ma di wo do vr za zo"),
    ("en-GB", "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec", "Mon Tue Wed Thu Fri Sat Sun"),
])
def test_every_unprefixed_month_and_day_as_measured(language, months, days):
    locale = Locale(language=language)
    assert " ".join(dates.format_serial(v, "mmm", locale) for v in MONTHS_15TH) == months
    assert " ".join(dates.format_serial(v, "ddd", locale) for v in WEEK) == days


def test_the_interface_sets_against_the_prefixed_ones():
    french, spanish, italian = (dates.INTERFACE_NAMES[k] for k in ("fr", "es", "it"))
    # French: fr-FR's abbreviated months without their dots, its days (PowerPoint) as is.
    assert french.short_months == tuple(n.removesuffix(".") for n in dates.NAMES["fr-FR"].short_months)
    assert french.short_days == dates.NAMES["fr-FR"].short_days
    assert french.months == dates.NAMES["fr-FR"].months
    # Spanish: neither es-ES's nor [$-A]'s (``set``); full names es-ES's.
    assert spanish.short_months[8] == "sept" and dates.NAMES["es"].short_months[8] == "set"
    assert spanish.short_days == dates.NAMES["es"].short_days
    assert (spanish.months, spanish.days) == (dates.NAMES["es-ES"].months, dates.NAMES["es-ES"].days)
    # Italian: it-IT's own names, listed as measured.
    assert italian == dates.NAMES["it-IT"]
    # A [$-A] prefix keeps its own September under a Spanish interface.
    assert dates.format_serial(46280, "[$-A]mmm", Locale(language="es-ES")) == "set"
    assert dates.format_serial(46280, "mmm", Locale(language="es-AR")) == "sept"
    assert dates.names_language("mmm", Locale(language="fr-CA")) == "fr-FR"
    assert dates.names_language("[$-40C]mmm", Locale(language="es-ES")) == "fr-FR"
    assert dates.date_names("[$-411]mmm", Locale(language="fr-BE")) == french
    # A bare [$] (a re-saved chart's Fallback) is the interface language's, as no prefix.
    assert dates.format_serial(46387, "[$]d mmm", Locale(language="fr-BE")) == "31 déc"


def test_m_d_yy_is_printed_as_written():
    # A known limit: Office shows the viewer's short date here (module notes).
    for language in ("nl-BE", "fr-FR", "en-GB", "es-ES", "it-IT"):
        assert dates.format_serial(46027, "m/d/yy", Locale(language=language)) == "1/5/26"


def test_an_unprefixed_date_axis_in_french_is_drawn_without_the_months_dot():
    texts = {run.text for run in _build(_chart_xml("d mmm"), Locale(language="fr-BE"))[0]}
    assert {"5 janv", "10 févr", "15 mars"} <= texts
    texts = {run.text for run in _build(_chart_xml(r"[$-80C]d\ mmm"), Locale(language="fr-BE"))[0]}
    assert {"5 janv.", "10 févr.", "15 mars"} <= texts


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
    assert dict(dates.LANGUAGES) == dict(getattr(edit, "LANGUAGES", dates.LANGUAGES))
    assert {tag: tuple(names) for tag, names in dates.NAMES.items()} == \
        {tag: tuple(names) for tag, names in edit.NAMES.items()}


@pytest.mark.parametrize("pattern", ["d mmmm yyyy", "dd/mm/yyyy", "ddd d mmm yy", "dddd, mmmmm",
                                     'd "de" mmmm', "yyyy-mm-dd", "m.d.yyyy"])
def test_a_code_ooxml_edit_keeps_prints_what_it_writes(pattern):
    edit = pytest.importorskip("ooxml_edit.dates")
    regions = ["en-BE", "fr-BE", "de-CH", "en-IE", "fr-CH", "it-CH", "nl", "fr", "es", "it"]
    for tag in [*edit.NAMES, *(regions if hasattr(edit, "LANGUAGES") else ())]:
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


MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
C16R2 = "http://schemas.microsoft.com/office/drawing/2015/06/chart"


def _resaved(tag: str, code: str, *, choice: bool = True) -> str:
    """A made-up chart in the shape PowerPoint and Word for Mac re-saved a code with a
    language tag in, 17 October 2026: the cache's code in an ``mc:AlternateContent``
    (a ``c16r2`` Choice's ``formatcode2``, a Fallback ``[$]``), the axis' ``numFmt`` with a
    ``c16r2:formatcode2`` attribute; no ``mc:Ignorable`` on the chart space."""
    xml = _chart_xml("CODE")
    branch = (f'<mc:Choice Requires="c16r2" xmlns:c16r2="{C16R2}">'
              f"<c16r2:formatcode2>[$-{tag}]{code}</c16r2:formatcode2></mc:Choice>"
              if choice else "")
    xml = xml.replace("<c:formatCode>CODE</c:formatCode>",
                      f'<mc:AlternateContent xmlns:mc="{MC}">{branch}<mc:Fallback>'
                      f"<c:formatCode>[$]{code}</c:formatCode></mc:Fallback>"
                      "</mc:AlternateContent>")
    return xml.replace('<c:axPos val="b"/><c:numFmt formatCode="General" sourceLinked="1"/>',
                       f'<c:axPos val="b"/><c:numFmt xmlns:c16r2="{C16R2}" '
                       f'formatCode="[$]{code}" c16r2:formatcode2="[$-{tag}]{code}" '
                       'sourceLinked="1"/>')


@pytest.mark.parametrize("tag, shown", [
    ("en-BE", {"Mon 5 Jan", "Tue 10 Feb", "Sun 15 Mar"}),     # measured: English
    ("de-BE", {"Mo 5 Jan", "Di 10 Feb", "So 15 Mär"}),        # measured: German
])
def test_a_resaved_tag_code_is_drawn_with_the_tags_names(tag, shown):
    code = r"ddd\ d\ mmm"
    source = parse_chart_space(ET.fromstring(_resaved(tag, code)))
    assert source.plots[0].series[0].category_format_code == f"[$-{tag}]{code}"
    assert source.axes[0].number_format == f"[$-{tag}]{code}"
    texts = {run.text for run in _build(_resaved(tag, code), DUTCH)[0]}
    assert shown <= texts and "46027" not in texts


def test_a_resaved_code_without_its_choice_takes_the_fallback_in_the_locale():
    # A bare [$] is the machine's language: the locale's.
    texts = {run.text for run in _build(_resaved("en-BE", "d mmm", choice=False), DUTCH)[0]}
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


# -- a rich title's fonts (round 6, item 11) -------------------------------------------------
# Measured, PowerPoint 16 for Mac's PDF export, 16 October 2026 (oracle-charttitle P1-P7,
# oracle-titlefont S1-S5 and B1-B4), in a deck whose text boxes are Aptos.

MINOR = "+mn-lt"   # what the test's resolver leaves a theme face as


def _rich(rpr: str = '<a:rPr lang="en-US"/>', *, ppr: str = "", lst: str = "", txpr: str = "") -> str:
    return (f'<c:title><c:tx><c:rich><a:bodyPr/><a:lstStyle>{lst}</a:lstStyle><a:p>{ppr}<a:r>{rpr}'
            f'<a:t>Probe</a:t></a:r></a:p></c:rich></c:tx><c:overlay val="0"/>{txpr}</c:title>')


UNSIZED_TXPR = ('<c:txPr><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr/></a:pPr>'
                '<a:endParaRPr lang="en-US"/></a:p></c:txPr>')
FACES = '<a:latin typeface="+mn-lt"/><a:ea typeface="+mn-ea"/><a:cs typeface="+mn-cs"/>'


def _title_runs(xml: str, chart_rules=rules.POWERPOINT):
    runs, _ = _build(xml, chart_rules=chart_rules)
    return [(run.properties.font_family, run.properties.font_size, run.properties.bold)
            for run in runs if run.text == "Probe"]


@pytest.mark.parametrize("wide, txpr", [(None, ""), (800, ""), (2400, ""), (800, UNSIZED_TXPR),
                                        (2400, UNSIZED_TXPR)])
def test_a_title_that_states_no_font_is_arial_18_regular(wide, txpr):
    # P1, P3, P4, P5, P7, S1.
    xml = _chart_xml("General", title=_rich(txpr=txpr), wide=wide)
    assert title_states_no_font(parse_chart_space(ET.fromstring(xml)))
    assert _title_runs(xml) == [("Arial", 18.0, False)]


def test_the_runs_size_stays_and_a_chart_wide_face_does_not_reach_the_title():
    # S4: run sz=2400, no face: ArialMT 24.  S5: chart-wide c:txPr names +mn-lt: ArialMT 18.
    assert _title_runs(_chart_xml("General", title=_rich('<a:rPr lang="en-US" sz="2400"/>'))) == \
        [("Arial", 24.0, False)]
    xml = _chart_xml("General", title=_rich(), wide=2400).replace(
        '<a:defRPr sz="2400"/>', '<a:defRPr sz="2400"><a:latin typeface="+mn-lt"/></a:defRPr>')
    assert _title_runs(xml) == [("Arial", 18.0, False)]


@pytest.mark.parametrize("ppr, rpr, drawn", [
    # B1: a paragraph a:defRPr with a size only: the minor face, bold.
    ('<a:pPr><a:defRPr sz="1862"/></a:pPr>', '<a:rPr lang="en-US" sz="1862"/>', (MINOR, 18.62, True)),
    # S2: +mn-lt and 18.62 on both, no b: bold.
    (f'<a:pPr><a:defRPr sz="1862">{FACES}</a:defRPr></a:pPr>',
     f'<a:rPr lang="en-US" sz="1862">{FACES}</a:rPr>', (MINOR, 18.62, True)),
    # B2: b="0" and +mn-lt: regular.
    (f'<a:pPr><a:defRPr sz="1862" b="0">{FACES}</a:defRPr></a:pPr>',
     f'<a:rPr lang="en-US" sz="1862">{FACES}</a:rPr>', (MINOR, 18.62, False)),
    # B4: b="0" alone on the paragraph: the minor face, regular.
    ('<a:pPr><a:defRPr b="0"/></a:pPr>', '<a:rPr lang="en-US" sz="1862"/>', (MINOR, 18.62, False)),
    # B3: no paragraph defaults, the run names +mn-lt: that face, regular.
    ("", f'<a:rPr lang="en-US" sz="1862">{FACES}</a:rPr>', (MINOR, 18.62, False)),
    # S3: the run names Georgia: Georgia, regular.
    ("", '<a:rPr lang="en-US"><a:latin typeface="Georgia"/></a:rPr>', ("Georgia", 18.0, False)),
])
def test_paragraph_defaults_are_the_minor_face_and_bold_unless_stated(ppr, rpr, drawn):
    xml = _chart_xml("General", title=_rich(rpr, ppr=ppr))
    source = parse_chart_space(ET.fromstring(xml))
    assert title_states_defaults(source) == bool(ppr)
    assert not title_states_no_font(source)
    assert _title_runs(xml) == [drawn]


@pytest.mark.parametrize("title", [
    _rich(lst='<a:lvl1pPr><a:defRPr><a:latin typeface="Georgia"/></a:defRPr></a:lvl1pPr>'),
    _rich(txpr='<c:txPr><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr><a:latin typeface="Georgia"/>'
               '</a:defRPr></a:pPr><a:endParaRPr lang="en-US"/></a:p></c:txPr>'),
    _rich(txpr='<c:txPr><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="1400"/></a:pPr>'
               '<a:endParaRPr lang="en-US"/></a:p></c:txPr>'),
    AUTO,
])
def test_what_is_not_measured_keeps_the_cascade(title):
    xml = _chart_xml("General", title=title, wide=2400)
    source = parse_chart_space(ET.fromstring(xml))
    assert not title_states_no_font(source) and not title_states_defaults(source)
    assert all(face != "Arial" for face, _, _ in _title_runs(xml))


def test_a_stated_weight_stays():
    assert _title_runs(_chart_xml("General", title=_rich('<a:rPr lang="en-US" b="1"/>'))) == \
        [("Arial", 18.0, True)]


def test_words_rich_title_keeps_the_callers_face():
    # Word is not measured: rules.WORD leaves face and weight to the caller (docx2svg's cascade).
    assert rules.WORD.rich_title_fonts is False
    assert _title_runs(_chart_xml("General", title=_rich()), chart_rules=rules.WORD) == \
        [(None, 18.0, False)]
    assert _title_runs(_chart_xml("General", title=_rich('<a:rPr lang="en-US" sz="1862"/>',
                                                         ppr='<a:pPr><a:defRPr sz="1862"/></a:pPr>')),
                       chart_rules=rules.WORD) == [(None, 18.62, False)]
