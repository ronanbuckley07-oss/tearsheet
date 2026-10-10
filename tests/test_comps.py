"""Comps stats (FD-7) and implied valuation (FD-8) on hand-built companies.

Target T: LTM EBITDA 100, LTM revenue 400, total debt 50, preferred 0,
noncontrolling interest 5, cash 20, short-term investments 10, 10 shares.
Peers' EV/EBITDA: 8, 10, 12, 14 (plus one NM and one that failed to load).

By hand (Excel PERCENTILE.INC):
  25th = 8 + 0.75 x (10 - 8)  = 9.5x     median = 11x     75th = 12 + 0.25 x (14 - 12) = 12.5x
  implied EV       = 9.5 x 100 = 950       11 x 100 = 1,100      12.5 x 100 = 1,250
  implied equity   = EV - 50 - 0 - 5 + 20 + 10 = EV - 25  ->  925 / 1,075 / 1,225
  implied price    = equity / 10            ->  92.50 / 107.50 / 122.50
"""

from datetime import date

import pytest

from engine import comps
from engine.comps import CompanyRow, percentile
from engine.metrics import CompanyMetrics
from engine.periods import Figure, missing

END = date(2026, 6, 30)


def fig(name, value, unit="USD", **kw):
    return Figure(name=name, value=value, unit=unit, formula="test", **kw)


def company(ticker, ev_ebitda=None, ev_revenue=10.0, pe=20.0, **overrides):
    F = {
        "ltm_ebitda": fig("LTM EBITDA", 100.0),
        "ltm_revenue": fig("LTM revenue", 400.0),
        "total_debt": fig("total_debt", 50.0),
        "preferred_stock": fig("preferred_stock", 0.0),
        "noncontrolling_interest": fig("noncontrolling_interest", 5.0),
        "cash": fig("cash", 20.0),
        "short_term_investments": fig("short_term_investments", 10.0),
        "shares_outstanding": fig("shares outstanding", 10.0, "shares"),
        "price": fig("share price", 100.0, "USD/share"),
        "ev_ebitda": fig("EV/EBITDA", ev_ebitda, "x") if ev_ebitda is not None
        else Figure(name="EV/EBITDA", value=None, unit="x", formula="", nm=True, reason="LTM EBITDA is negative"),
        "ev_revenue": fig("EV/Revenue", ev_revenue, "x"),
        "pe": fig("P/E", pe, "x"),
        "revenue_growth_ltm": fig("growth", 0.1, "ratio"),
        "ebitda_margin": fig("margin", 0.25, "ratio"),
        "net_debt_ebitda": fig("ND/EBITDA", 0.2, "x"),
    }
    F.update(overrides)
    return CompanyRow(ticker, f"{ticker} Inc", CompanyMetrics(ltm_end=END, fiscal_year_ends=[], figures=F),
                      high_52w=fig("52-week high", 130.0, "USD/share"),
                      low_52w=fig("52-week low", 80.0, "USD/share"))


PEERS = [company("A", 8), company("B", 14), company("C", 10), company("D", 12),
         company("E", None), CompanyRow("F", "F", None, error="not in the SEC ticker list")]


@pytest.fixture
def c():
    return comps.build(company("T", 20), PEERS)


def test_percentile_matches_excel_inc():
    assert percentile([8, 10, 12, 14], 0.25) == pytest.approx(9.5)
    assert percentile([8, 10, 12, 14], 0.75) == pytest.approx(12.5)
    assert percentile([5], 0.25) == 5
    assert percentile([1, 2, 3, 4, 5], 0.5) == 3


def test_stats_only_over_usable_values(c):
    s = c.stats["ev_ebitda"]
    assert s.n == 4 and s.included == ("A", "B", "C", "D")
    assert (s.p25, s.median, s.p75) == (pytest.approx(9.5), 11, pytest.approx(12.5))
    assert s.mean == 11
    excluded = dict(s.excluded)
    assert excluded["E"].startswith("NM") and excluded["F"].startswith("n/a")


def test_implied_ev_ebitda_range(c):
    r = c.implied["ev_ebitda"]
    assert [f.value for f in r.enterprise_value] == pytest.approx([950, 1100, 1250])
    assert [f.value for f in r.equity_value] == pytest.approx([925, 1075, 1225])
    assert [f.value for f in r.share_price] == pytest.approx([92.5, 107.5, 122.5])
    assert "FD-8" in r.equity_value[0].formula and "FD-8" in r.share_price[0].formula


def test_implied_ev_revenue_uses_revenue(c):
    r = c.implied["ev_revenue"]  # every peer at 10x revenue
    assert r.share_price[1].value == pytest.approx((10 * 400 - 25) / 10)


def test_target_and_duplicates_left_out_of_peer_stats():
    c = comps.build(company("T", 20), [company("T", 20), company("A", 8), company("A", 8)])
    assert c.stats["ev_ebitda"].included == ("A",)
    assert any("target" in n for n in c.notes) and any("duplicates" in n for n in c.notes)


def test_few_peers_flagged():
    c = comps.build(company("T", 20), [company("A", 8), company("B", 9)])
    assert any("only 2 usable" in n for n in c.notes)


def test_negative_target_ebitda_no_ev_ebitda_valuation():
    t = company("T", None, ltm_ebitda=fig("LTM EBITDA", -40.0))
    r = comps.build(t, PEERS).implied["ev_ebitda"]
    assert r.reason and "not positive" in r.reason
    assert all(f.value is None for f in r.share_price)


def test_negative_implied_equity_is_nm():
    t = company("T", 20, total_debt=fig("total_debt", 5000.0))
    lo = comps.build(t, PEERS).implied["ev_ebitda"].share_price[0]
    assert lo.value is None and lo.nm and "negative" in lo.reason


def test_missing_target_cash_makes_implied_price_na():
    t = company("T", 20, cash=missing("cash", "USD", "not reported at 2026-06-30"))
    lo = comps.build(t, PEERS).implied["ev_ebitda"].share_price[0]
    assert lo.value is None and "cash" in lo.reason


def test_no_usable_peers():
    r = comps.build(company("T", 20), [company("E", None)]).implied["ev_ebitda"]
    assert r.reason == "no usable peer EV/EBITDA multiples"


def test_football_field(c):
    bars = {b["label"]: b for b in c.football_field()}
    assert bars["EV/EBITDA (25th-75th pct)"]["low"] == pytest.approx(92.5)
    assert bars["52-week range"]["high"] == 130
    assert bars["Current price"]["low"] == 100
