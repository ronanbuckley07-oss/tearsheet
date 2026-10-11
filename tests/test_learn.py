"""Learn mode (FD-14): templates are filled with the company's own numbers, and every
"if this changes" number is a rerun of the real DCF."""

from datetime import date

import pytest

from engine import dcf, learn
from engine.periods import Figure
from tests.test_dcf import assumptions, base, company, fig


M = 1e6  # the test_dcf company in $m, so the templates print "$155m"


def ctx_and_dcf(**changes):
    scaled = {k: fig(f.name, f.value * M, f.unit) for k, f in company().figures.items()
              if f.unit in ("USD", "shares")}
    m = company(**scaled, price=fig("price", 100.0, "USD/share"), ltm_ebitda=fig("LTM EBITDA", 250.0 * M),
                enterprise_value=fig("EV", 950.0 * M), ev_ebitda=fig("EV/EBITDA", 3.8, "x"),
                ebitda_margin=fig("EBITDA margin", 0.25, "ratio"))
    defaults = assumptions()
    a = dict(defaults)
    a.update({k: v for k, v in assumptions(**changes).items() if k in changes})
    res = dcf.run(a, m, base(), mid_year=False)
    d = learn.DcfContext(res, a, defaults, m, base(), False, True)
    return learn.Context("Hand Co", "HC", m, dcf=d), d


def test_every_concept_is_complete():
    for key, c in learn.CONCEPTS.items():
        assert c.title and c.what and c.drivers and c.feeds, key
    for k in [*dcf.GROWTH_KEYS, *dcf.OPERATING_KEYS, *dcf.WACC_KEYS, "terminal_growth"]:
        assert learn.assumption_concept(k) in learn.CONCEPTS
        assert learn.chain(k)
    for concept, _ in learn.DCF_ROWS.values():
        assert concept in learn.CONCEPTS
    assert set(learn.FIGURE_CONCEPT.values()) <= set(learn.CONCEPTS)


def test_figure_explanations_use_the_company_numbers():
    ctx, _ = ctx_and_dcf()
    e = learn.explain_figure("price", ctx.m.figures["price"], ctx, "Share price")
    assert e.value == "$100.00"
    assert any("10m shares" in h and "$800m of equity value" in h for h in e.here)
    margin = learn.explain_figure("ebitda_margin", ctx.m.figures["ebitda_margin"], ctx)
    assert any("$0.25 of EBITDA" in h for h in margin.here)


def test_na_figure_says_why_and_skips_templates():
    ctx, _ = ctx_and_dcf()
    f = Figure("EV/EBITDA", None, "x", "n/a", reason="EBITDA is negative", nm=True)
    e = learn.explain_figure("ev_ebitda", f, ctx)
    assert e.value == "NM" and "EBITDA is negative" in e.here[0] and not e.impact


def test_dcf_cell_shows_that_years_arithmetic():
    ctx, d = ctx_and_dcf()
    # Year 1 by hand (test_dcf): NOPAT 165, D&A 55, capex 55, NWC 10 -> UFCF 155.
    e = learn.explain_dcf_cell("= Unlevered free cash flow", "Year 1", d, ctx)
    assert e.calc == "$165m NOPAT + $55m D&A - $55m capex - $10m NWC build = $155m"
    rev = learn.explain_dcf_cell("Revenue", "Year 2", d, ctx)
    assert rev.calc == "$1.10bn x (1 + 10.0%) = $1.21bn"
    df = learn.explain_dcf_cell("Discount factor", "Year 1", d, ctx)
    assert df.calc == "1 / (1 + 7.95%)^1 = 0.926"
    for row in learn.DCF_ROWS:
        for col in ["LTM (base)", *[f"Year {i}" for i in range(1, 6)], "Terminal year"]:
            assert learn.explain_dcf_cell(row, col, d, ctx) is not None


def test_nudge_is_a_rerun_of_the_dcf():
    ctx, d = ctx_and_dcf()
    lines = learn.nudge(d, "ebit_margin")
    up = dcf.run(assumptions(ebit_margin=0.21), d.m, d.base, False).share_price.value
    assert f"${up:,.2f}" in lines[0] and lines[0].startswith("Raise it by 1 point")


def test_tornado_sorted_by_swing_and_matches_reruns():
    _, d = ctx_and_dcf()
    bars = learn.tornado(d)
    assert [b.swing for b in bars] == sorted((b.swing for b in bars), reverse=True)
    g = next(b for b in bars if b.label == "Terminal growth")
    hi = dcf.run(assumptions(terminal_growth=0.025), d.m, d.base, False).share_price.value
    assert g.high == pytest.approx(hi) and g.step == "±0.5 points"
    growth = next(b for b in bars if b.label.startswith("Revenue growth"))
    all_up = dcf.run(assumptions(**{k: 0.11 for k in dcf.GROWTH_KEYS}), d.m, d.base, False).share_price.value
    assert growth.high == pytest.approx(all_up)


def test_ripple_against_defaults():
    _, d = ctx_and_dcf(ebit_margin=0.30)
    assert learn.changed_keys(d) == ["ebit_margin"]
    rows = {r.line: r for r in learn.ripple(learn.defaults_result(d), d.result, d.m)}
    assert rows["WACC"].change == pytest.approx(0)  # margin doesn't touch the discount rate
    assert rows["Share price"].before == pytest.approx(324.95, abs=0.01)  # by hand in test_dcf
    assert rows["Share price"].after > rows["Share price"].before
    assert rows["Year-5 revenue"].change == pytest.approx(0)


def test_walkthrough_numbers_match_the_model():
    ctx, d = ctx_and_dcf()
    steps = learn.walkthrough(d, ctx)
    assert len(steps) == 12
    text = "\n".join(s.text + "\n" + "\n".join(s.math) for s in steps)
    assert "Year 1: $165m + $55m - $55m - $10m = $155m" in text
    assert "= 9.00%" in text and "= 7.95%" in text  # cost of equity and WACC by hand
    assert "$324.95" in text


def test_walkthrough_when_dcf_cannot_run():
    ctx, d = ctx_and_dcf(terminal_growth=0.09)
    assert d.result.reason and learn.walkthrough(d, ctx)[0].title == "The DCF can't run yet"
    assert learn.tornado(d) == []


def test_cost_of_debt_shows_its_wacc_weight():
    ctx, d = ctx_and_dcf()
    e = learn.explain_assumption("cost_of_debt", d, ctx)
    assert any("20.0% of HC's capital" in h for h in e.here)
