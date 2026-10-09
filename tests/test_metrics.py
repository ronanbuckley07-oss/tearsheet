"""EBITDA, EV bridge, multiples on a hand-built company with hand-computed answers.

Company X, fiscal year = calendar year, latest filing the FY2025 10-K.
  FY2025: revenue 1000, operating income 200, D&A 50, net income 120, SBC 30
  FY2024: revenue  800, operating income 150, D&A 40, net income  90
  Balance sheet at 2025-12-31:
    cash 100, short-term investments 50
    long-term debt: current 20 + noncurrent 280 (LongTermDebt tag = 300, must not be added again)
    commercial paper 10, finance leases 5 + 15, noncontrolling interest 25, no preferred
  Cover shares 100 (as of 2026-01-31); diluted weighted average 104
  Price $30

By hand:
  EBITDA          = 200 + 50                                   = 250
  total debt      = 20 + 280 + 0 (no ST borrowings) + 10 + 5 + 15 = 330
  equity value    = 30 x 100                                   = 3000
  EV              = 3000 + 330 + 0 + 25 - 100 - 50             = 3205
  EV/Revenue      = 3205 / 1000                                = 3.205x
  EV/EBITDA       = 3205 / 250                                 = 12.82x
  P/E             = 3000 / 120                                 = 25.0x
  net debt        = 330 - 100 - 50                             = 180
  net debt/EBITDA = 180 / 250                                  = 0.72x
  EBITDA margin   = 250 / 1000                                 = 25%
  revenue growth  = 1000 / 800 - 1                             = 25%
"""

from datetime import date

import pytest

from engine import metrics
from engine.periods import Figure, missing
from engine.xbrl import extract_all
from tests.test_xbrl import facts, row

END = date(2025, 12, 31)


def fy(val, year):
    return row(val, f"{year}-12-31", f"{year}-01-01")


def company(overrides=None, drop=()):
    us_gaap = {
        "Revenues": [fy(1000, 2025), fy(800, 2024)],
        "OperatingIncomeLoss": [fy(200, 2025), fy(150, 2024)],
        "DepreciationDepletionAndAmortization": [fy(50, 2025), fy(40, 2024)],
        "NetIncomeLoss": [fy(120, 2025), fy(90, 2024)],
        "ShareBasedCompensation": [fy(30, 2025), fy(25, 2024)],
        "CashAndCashEquivalentsAtCarryingValue": [row(100, "2025-12-31")],
        "ShortTermInvestments": [row(50, "2025-12-31")],
        "LongTermDebtCurrent": [row(20, "2025-12-31")],
        "LongTermDebtNoncurrent": [row(280, "2025-12-31")],
        "LongTermDebt": [row(300, "2025-12-31")],
        "CommercialPaper": [row(10, "2025-12-31")],
        "FinanceLeaseLiabilityCurrent": [row(5, "2025-12-31")],
        "FinanceLeaseLiabilityNoncurrent": [row(15, "2025-12-31")],
        "MinorityInterest": [row(25, "2025-12-31")],
    }
    us_gaap.update(overrides or {})
    for k in drop:
        us_gaap.pop(k)
    cf = facts(us_gaap, dei={"EntityCommonStockSharesOutstanding": [row(100, "2026-01-31")]}, unit="USD")
    # share tags use the "shares" unit
    cf["facts"]["dei"]["EntityCommonStockSharesOutstanding"]["units"] = {
        "shares": [row(100, "2026-01-31")]}
    cf["facts"]["us-gaap"]["WeightedAverageNumberOfDilutedSharesOutstanding"] = {
        "units": {"shares": [fy(104, 2025)]}}
    return extract_all(cf)


PRICE = Figure(name="share price", value=30.0, unit="USD/share", formula="test", as_of=date(2026, 2, 1),
               source="test")


@pytest.fixture
def m():
    return metrics.compute(company(), END, PRICE)


def test_ebitda_fd1_no_sbc_addback(m):
    assert m["ltm_ebitda"].value == 250
    assert m["ltm_sbc"].value == 30  # shown separately


def test_total_debt_no_double_count(m):
    d = m["total_debt"]
    assert d.value == 330
    assert {f.tag for _, f in d.facts} == {
        "LongTermDebtCurrent", "LongTermDebtNoncurrent", "CommercialPaper",
        "FinanceLeaseLiabilityCurrent", "FinanceLeaseLiabilityNoncurrent"}


def test_ev_bridge(m):
    assert m["equity_value"].value == 3000
    assert m["enterprise_value"].value == 3205
    signs = {f.tag: s for s, f in m["enterprise_value"].facts}
    assert signs["CashAndCashEquivalentsAtCarryingValue"] == -1
    assert signs["ShortTermInvestments"] == -1
    assert signs["MinorityInterest"] == 1


def test_multiples(m):
    assert m["ev_revenue"].value == pytest.approx(3.205)
    assert m["ev_ebitda"].value == pytest.approx(12.82)
    assert m["pe"].value == pytest.approx(25.0)
    assert m["net_debt"].value == 180
    assert m["net_debt_ebitda"].value == pytest.approx(0.72)


def test_margin_and_growth(m):
    assert m["ebitda_margin"].value == pytest.approx(0.25)
    assert m["revenue_growth_fy"].value == pytest.approx(0.25)
    assert m["revenue_growth_ltm"].value == pytest.approx(0.25)


def test_fiscal_years(m):
    assert m.fiscal_year_ends == [date(2025, 12, 31), date(2024, 12, 31)]
    fy24 = m.fiscal_years[date(2024, 12, 31)]
    assert fy24["ebitda"].value == 190
    assert fy24["ebitda_margin"].value == pytest.approx(190 / 800)


def test_share_check_flags_over_3pct(m):
    c = m["share_count_check"]
    assert c.value == pytest.approx(0.04)
    assert any("FD-3" in n for n in c.notes)


def test_missing_preferred_treated_as_zero_and_flagged(m):
    p = m["preferred_stock"]
    assert p.value == 0 and any("FD-10 Q4" in n for n in p.notes)


def test_long_term_debt_total_used_when_no_split():
    m = metrics.compute(company(drop=("LongTermDebtCurrent", "LongTermDebtNoncurrent")), END, PRICE)
    assert m["total_debt"].value == 300 + 10 + 20
    assert any("LongTermDebt total" in n for n in m["total_debt"].notes)


def test_finance_lease_total_used_when_no_split():
    m = metrics.compute(company(
        overrides={"FinanceLeaseLiability": [row(66, "2025-12-31")]},
        drop=("FinanceLeaseLiabilityCurrent", "FinanceLeaseLiabilityNoncurrent")), END, PRICE)
    assert m["total_debt"].value == 300 + 10 + 66


def test_finance_lease_split_preferred_over_total():
    m = metrics.compute(company(overrides={"FinanceLeaseLiability": [row(20, "2025-12-31")]}), END, PRICE)
    assert m["total_debt"].value == 330  # not 350


def test_missing_cash_makes_ev_na_not_zero():
    m = metrics.compute(company(drop=("CashAndCashEquivalentsAtCarryingValue",)), END, PRICE)
    assert m["enterprise_value"].value is None
    assert "cash" in m["enterprise_value"].reason


def test_missing_price_makes_valuation_na():
    m = metrics.compute(company(), END, missing("share price", "USD/share", "lookup failed"))
    for k in ("equity_value", "enterprise_value", "ev_ebitda", "pe"):
        assert m[k].value is None and "lookup failed" in m[k].reason
    assert m["ltm_ebitda"].value == 250  # operating figures unaffected


# ---- FD-6 NM rules ---------------------------------------------------------------


def fig(v, name="x"):
    return Figure(name=name, value=v, unit="USD", formula="test")


def test_negative_denominator_nm():
    r = metrics.ratio("EV/EBITDA", fig(100, "EV"), fig(-5, "EBITDA"), "x", "", multiple=True)
    assert r.value is None and r.nm and "negative" in r.reason


def test_zero_denominator_nm():
    r = metrics.ratio("EV/EBITDA", fig(100), fig(0, "EBITDA"), "x", "", multiple=True)
    assert r.value is None and r.nm and "zero" in r.reason


def test_above_100x_nm_keeps_value():
    r = metrics.ratio("P/E", fig(1010), fig(10), "x", "", multiple=True)
    assert r.value is None and r.nm and r.raw_value == pytest.approx(101)


def test_exactly_100x_is_shown():
    assert metrics.ratio("P/E", fig(1000), fig(10), "x", "", multiple=True).value == 100


def test_negative_ev_multiple_nm():
    # FD-10 Q7
    r = metrics.ratio("EV/Revenue", fig(-50, "EV"), fig(10), "x", "", multiple=True)
    assert r.value is None and r.nm


def test_net_cash_leverage_is_meaningful_but_negative_ebitda_is_not():
    ok = metrics.ratio("ND/EBITDA", fig(-100), fig(50), "x", "", positive_den=True)
    assert ok.value == -2
    bad = metrics.ratio("ND/EBITDA", fig(100), fig(-50), "x", "", positive_den=True)
    assert bad.value is None and bad.nm


def test_growth_from_negative_base_nm():
    g = metrics.growth("g", fig(10), fig(-5), "")
    assert g.value is None and g.nm


# ---- dropped tags: reported after the 10-K, missing now -> n/a, not 0 -------------


def test_debt_tag_dropped_after_10k_is_na_not_zero():
    # CoreWeave pattern: LTD tagged in the Q1 10-Q, company-specific tags in Q2.
    m = metrics.compute(company(overrides={
        "LongTermDebtCurrent": [row(20, "2025-12-31"), row(25, "2026-03-31", form="10-Q")],
        "LongTermDebtNoncurrent": [row(280, "2025-12-31"), row(300, "2026-03-31", form="10-Q")],
        "LongTermDebt": [row(300, "2025-12-31")],
    }), date(2026, 6, 30), PRICE)
    d = m["total_debt"]
    assert d.value is None and "company-specific tags" in d.reason
    assert m["enterprise_value"].value is None


def test_item_never_reported_still_zero():
    m = metrics.compute(company(), END, PRICE)
    assert m["preferred_stock"].value == 0


def test_optional_item_dropped_after_10k_is_na():
    m = metrics.compute(company(overrides={
        "MinorityInterest": [row(25, "2025-12-31"), row(30, "2026-03-31", form="10-Q")],
    }), date(2026, 6, 30), PRICE)
    assert m["noncontrolling_interest"].value is None


def _with_company_debt(m_series, tags):
    from engine.xbrl import Fact, MetricSeries, PeriodType, Source
    cs = MetricSeries(metric="debt_company_specific")
    for tag, v in tags:
        cs.facts.append(Fact(metric="debt_company_specific", value=v, unit="USD", start=None,
                             end=date(2026, 6, 30), period_type=PeriodType.INSTANT,
                             sources=(Source("crwv", tag, "10-Q", "X-26-1", date(2026, 8, 12), None,
                                             date(2026, 6, 30), None, None),)))
    m_series["debt_company_specific"] = cs
    return m_series


DROPPED = {
    "LongTermDebtCurrent": [row(20, "2025-12-31"), row(25, "2026-03-31", form="10-Q")],
    "LongTermDebtNoncurrent": [row(280, "2025-12-31"), row(300, "2026-03-31", form="10-Q")],
}


def test_company_specific_debt_summed_and_flagged():
    # FD-10 Q9
    s = _with_company_debt(company(overrides=DROPPED, drop=("LongTermDebt",)),
                           [("crwv:RecourseDebtCurrent", 60), ("crwv:RecourseDebtNonCurrent", 250)])
    d = metrics.compute(s, date(2026, 6, 30), PRICE)["total_debt"]
    assert d.value == 60 + 250 + 10 + 20  # + commercial paper + finance leases (10-K values, FD-10 Q3)
    assert any("FD-10 Q9" in n for n in d.all_notes())


def test_company_specific_debt_total_plus_parts_refused():
    s = _with_company_debt(company(overrides=DROPPED, drop=("LongTermDebt",)),
                           [("crwv:RecourseDebt", 310), ("crwv:RecourseDebtCurrent", 60)])
    assert metrics.compute(s, date(2026, 6, 30), PRICE)["total_debt"].value is None
