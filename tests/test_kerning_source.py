"""Which kern pairs a line is laid out with: the OpenType feature, or the legacy table.

The measurements are :mod:`ooxml_common.text.kerning`'s: PowerPoint charges a static
face's legacy ``kern`` table and a variable face's ``GPOS``; Word, where a run kerns, the
legacy table alone.  The tables carry both; a :class:`KerningSource` picks.
"""

from __future__ import annotations

import pytest

from ooxml_common.drawingml import rules
from ooxml_common.drawingml.context import RenderContext
from ooxml_common.text import kerning
from ooxml_common.text.kerning import KernPairs, KerningSource
from ooxml_common.text.measure import DefaultTextMeasurer, FontToolsTextMeasurer
from ooxml_common.text.metrics import METRICS
from ooxml_common.units import PX_PER_PT


def test_each_application_has_its_measured_source():
    assert rules.POWERPOINT.kerning == kerning.POWERPOINT == KerningSource("legacy", "feature")
    assert rules.WORD.kerning == kerning.WORD == KerningSource("legacy", "none")
    # The shared default stays the feature: a rule or measurer that names none.
    assert rules.DrawingRules("x", rules.POWERPOINT.color).kerning == kerning.FEATURE
    assert DefaultTextMeasurer().kerning == kerning.FEATURE
    with pytest.raises(ValueError):
        KerningSource("gpos")


def test_a_context_without_a_measurer_charges_its_rules_pairs():
    assert RenderContext().measurer.kerning == kerning.POWERPOINT
    assert RenderContext(rules=rules.WORD).measurer.kerning == kerning.WORD
    own = DefaultTextMeasurer()
    assert RenderContext(measurer=own).measurer is own


def test_pass_at_18_pt_is_as_wide_as_powerpoint_draws_it():
    """pptx-agent's wrap-boundary probe: PowerPoint put Aptos's "Pass" down at pen
    advances of 9.770, 9.627 and 8.744 pt -- ``Pa`` kerned (in both tables), ``ss`` not
    (in ``GPOS`` alone, -33/2048 em, 0.290 pt at 18 pt)."""
    def advance(text: str, source: KerningSource) -> float:
        measurer = DefaultTextMeasurer(kerning=source)
        whole = measurer.measure_text_width(text, 18, False, "Aptos")
        return (whole - measurer.measure_text_width(text[-1], 18, False, "Aptos")) / PX_PER_PT

    drawn = (9.770, 9.627, 8.744)
    legacy = (advance("Pa", kerning.POWERPOINT), advance("Pas", kerning.POWERPOINT) - advance("Pa", kerning.POWERPOINT),
              advance("Pass", kerning.POWERPOINT) - advance("Pas", kerning.POWERPOINT))
    # PowerPoint places each glyph to about 0.05 pt of the face's advance (the probe's
    # finding), so the advances agree to that; the ``ss`` join, the question, to 0.01.
    assert legacy == pytest.approx(drawn, abs=0.07)
    assert legacy[2] == pytest.approx(drawn[2], abs=0.01)
    feature = advance("Pass", kerning.FEATURE) - advance("Pas", kerning.FEATURE)
    assert feature == pytest.approx(8.744 - 33 / 2048 * 18, abs=0.01)
    assert DefaultTextMeasurer(kerning=kerning.NONE).kern_between("Pa", "ss", 18, False, "Aptos") == 0.0


@pytest.mark.parametrize("key", ["Aptos", "Aptos Display", "Cambria"])
def test_an_office_face_s_legacy_table_is_a_subset_of_its_feature(key):
    """Where the entry is the Office face itself, every legacy pair is a ``GPOS`` pair of
    the same value (Aptos: 4,185 of 20,290) -- the subset relation the module docstring
    states, and why the two applications draw a pair both hold identically."""
    metrics = METRICS[key]
    legacy, feature = metrics.legacy_kerning, metrics.kerning
    for bold in (False, True):
        left = legacy.bold_left if bold and legacy.bold_left else legacy.left
        right = legacy.bold_right if bold and legacy.bold_right else legacy.right
        checked = 0
        for first in "".join(left):
            for second in "".join(right):
                value = legacy.adjustment(first, second, bold)
                if value:
                    assert feature.adjustment(first, second, bold) == value, (first, second)
                    checked += 1
        assert checked > 1000


def test_the_clones_carry_their_office_face_s_legacy_pairs():
    """Carlito, Arimo and Tinos have no legacy table of their own; their entries carry
    Calibri's, Arial's and Times New Roman's, as their line gaps are those faces'."""
    for key in ("Carlito", "Arimo", "Tinos", "Cambria", "Aptos", "Aptos Display"):
        assert METRICS[key].legacy_kerning is kerning.LEGACY_KERNING[key]
    assert METRICS["Arimo"].legacy_kerning.adjustment("A", "V") == METRICS["Arimo"].kerning.adjustment("A", "V") != 0
    # Lato, Raleway and Caladea are drawn static and have no legacy table: not kerned.
    for key in ("Lato", "Raleway", "Caladea", "Cousine"):
        assert METRICS[key].legacy_kerning is None and not METRICS[key].variable
        assert METRICS[key].kern_table(kerning.POWERPOINT) is None


def test_a_variable_face_is_kerned_from_gpos_by_powerpoint_and_not_by_word():
    """Noto Sans JP is a variable face: PowerPoint drew its kana pairs (``すヘ`` -90/1000 em)
    from ``GPOS``; Word drew them unkerned."""
    noto = METRICS["Noto Sans JP"]
    assert noto.variable and noto.legacy_kerning is None
    assert noto.kern_table(kerning.POWERPOINT) is noto.kerning
    assert noto.kern_table(kerning.WORD) is None
    pair = DefaultTextMeasurer(kerning=kerning.POWERPOINT).kern_between("す", "ヘ", 24, False, None, "Noto Sans JP")
    assert pair == pytest.approx(-90 / 1000 * 24 * PX_PER_PT)
    assert DefaultTextMeasurer(kerning=kerning.WORD).kern_between("す", "ヘ", 24, False, None, "Noto Sans JP") == 0


def test_kern_pairs_built_at_run_time():
    pairs = KernPairs({"AV": -80, "To": -40}, {"AV": -60})
    assert pairs.adjustment("A", "V") == -80 and pairs.adjustment("A", "V", True) == -60
    # A bold table, where there is one, answers for bold whole, as KernTable's does.
    assert pairs.adjustment("T", "o", True) == 0 and pairs.adjustment("T", "o") == -40
    assert KernPairs({"To": -40}).adjustment("T", "o", True) == -40
    assert pairs.adjustment("V", "A") == 0


def test_fonttools_measurer_follows_the_source():
    """The real file's tables: Carlito has ``GPOS`` pairs and no legacy table, so the
    legacy source does not kern it at all."""
    pytest.importorskip("fontTools")
    from ooxml_common.fonts import bundle_dir

    bundle = bundle_dir()
    if bundle is None:
        pytest.skip("the pptx2svg-fonts bundle is not installed")
    paths = {"Carlito": str(bundle / "Carlito-Regular.ttf")}
    feature = FontToolsTextMeasurer(paths).kern_between("T", "e", 20, False, "Carlito")
    legacy = FontToolsTextMeasurer(paths, kerning=kerning.POWERPOINT).kern_between("T", "e", 20, False, "Carlito")
    assert feature < 0 and legacy == 0
