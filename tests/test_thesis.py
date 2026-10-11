"""Thesis support (engine/thesis.py, FD-16) on hand-built companies.

Peers' EV/EBITDA 8, 10, 12, 14: 25th 9.5x, median 11x, 75th 12.5x (QUARTILE.INC).
Peers' revenue growth 5%, 10%, 15%, 20%: 25th 8.75%, 75th 16.25%; max 20%.
Peers' EBITDA margin 20%, 30%, 40%, 50%: 25th 27.5%, 75th 42.5%; min 20%.

Target T: EV/EBITDA 20x (above the 75th: richer -> short; rank 4 of 4 below it -> 4 / (5 - 1) = 100%),
growth 30% (above every peer -> stronger, long, and an "outside every peer" warning),
margin 26% (below the 25th but inside the peer range -> weaker, short, IQR warning),
net debt / EBITDA 3.0x vs peers 0.2x (more levered -> short), EV/Revenue 10x like every peer (in line).

Valuation (price 100): EV/EBITDA comps 92.50 / 107.50 / 122.50 (tests/test_comps.py), so mid upside
107.5 / 100 - 1 = +7.5%; a DCF at 80 is -20%: the methods disagree.
"""

from datetime import date

import pytest

from engine import comps, dcf, thesis
from engine.periods import Figure
from engine.report import Report
from tests.test_comps import company, fig
from tests.test_dcf import assumptions, base
from tests.test_dcf import company as dcf_company


def build():
    peers = []
    for tk, m, g, mg in (("A", 8, .05, .20), ("B", 14, .10, .30), ("C", 10, .15, .40), ("D", 12, .20, .50)):
        peers.append(company(tk, m, revenue_growth_ltm=fig("g", g, "ratio"), ebitda_margin=fig("m", mg, "ratio"),
                             equity_value=fig("equity value", 1000.0)))
    t = company("T", 20, revenue_growth_ltm=fig("g", .30, "ratio"), ebitda_margin=fig("m", .26, "ratio"),
                net_debt_ebitda=fig("nd", 3.0, "x"))
    return comps.build(t, peers)


def test_scorecard_readings():
    sc = thesis.scorecard(build())
    by = {r.column: r for r in sc.rows}
    ev = by["ev_ebitda"]
    assert (ev.stats.p25, ev.stats.p75) == (pytest.approx(9.5), pytest.approx(12.5))
    assert (ev.reading, ev.signal, ev.rank.value) == ("richer", "short", 1.0)
    assert ev.position == "above the peer 75th percentile"
    assert (by["revenue_growth_ltm"].reading, by["revenue_growth_ltm"].signal) == ("stronger", "long")
    assert (by["ebitda_margin"].reading, by["ebitda_margin"].signal) == ("weaker", "short")
    assert by["ebitda_margin"].rank.value == pytest.approx(1 / 4)  # only A (20%) below 26%
    assert (by["net_debt_ebitda"].reading, by["net_debt_ebitda"].signal) == ("more levered", "short")
    assert (by["ev_revenue"].reading, by["ev_revenue"].signal) == ("in line", "neutral")
    tally = sc.tally()
    assert tally["long"] == ["Revenue growth (LTM)"] and "EV/EBITDA" in tally["short"]


def test_cheap_multiple_reads_long():
    c = build()
    c.target.metrics.figures["ev_ebitda"] = fig("EV/EBITDA", 7.0, "x")
    ev = next(r for r in thesis.scorecard(c).rows if r.column == "ev_ebitda")
    assert (ev.reading, ev.signal, ev.rank.value) == ("cheaper", "long", 0.0)


def test_nm_target_metric_is_na_with_reason():
    c = build()
    c.target.metrics.figures["ev_ebitda"] = Figure("EV/EBITDA", None, "x", "", nm=True, reason="EBITDA negative")
    ev = next(r for r in thesis.scorecard(c).rows if r.column == "ev_ebitda")
    assert ev.signal == "n/a" and "target EV/EBITDA NM" in ev.rank.reason


def test_comparability_warnings():
    w = thesis.scorecard(build()).warnings
    assert any("revenue growth of 30.0% is outside every peer's (5.0% to 20.0%)" in x for x in w)
    assert any("EBITDA margin of 26.0% is outside the peer interquartile range (27.5% to 42.5%)" in x for x in w)


def test_valuation_summary_upside_and_disagreement():
    c = build()
    res = type("R", (), {"share_price": fig("DCF share price", 80.0, "USD/share"), "reason": None})()
    vs = thesis.valuation_summary(c, res, {"low": 70.0, "high": 90.0, "reason": None})
    by = {m.method.split(" (")[0]: m for m in vs.methods}
    ev = by["Comps: EV/EBITDA"]
    assert ev.mid.value == pytest.approx(107.5) and ev.upside_mid.value == pytest.approx(0.075)
    assert ev.upside_low.value == pytest.approx(-0.075) and "/ current price $100.00 - 1" in ev.upside_mid.formula
    d = by["DCF"]
    assert d.upside_mid.value == pytest.approx(-0.2) and d.low.value == 70.0 and d.upside_high.value == pytest.approx(-0.1)
    wk = by["52-week trading range"]
    assert wk.upside_low.value == pytest.approx(-0.2) and wk.upside_mid.value is None  # no midpoint by design
    assert vs.notes and "disagree" in vs.notes[0] and "DCF" in vs.notes[0]


def test_upside_na_when_price_missing():
    f = thesis.upside(fig("x", 50.0, "USD/share"), Figure("share price", None, "USD/share", "", reason="429"), "u")
    assert f.value is None and "share price n/a" in f.reason


def test_build_extras_runs_dcf_parts_only_with_assumptions():
    c = build()
    m = dcf_company()
    m.figures.update({k: v for k, v in c.target.metrics.figures.items() if k not in m.figures})
    c.target.metrics = m
    rep = Report(target=c.target, comps=c, dcf_base=base())
    x = thesis.build_extras(rep)
    assert x.drivers is None and x.scorecard is not None
    assert [f.in_band for f in x.size_fits] == [True] * 4  # 1,000 / 800 = 1.25x
    assert all(mth.method != "DCF (WACC ±1%, g ±0.5%)" for mth in x.valuation.methods)
    x = thesis.build_extras(rep, assumptions())
    assert x.drivers and any(mth.method.startswith("DCF") for mth in x.valuation.methods)
