"""DCF (FD-11) on a hand-built company.

Company: LTM revenue 1,000, equity value 800, total debt 200, cash 50, 10 shares.
Assumptions: revenue +10% a year, EBIT margin 20%, D&A 5% and capex 5% of revenue,
NWC 10% of revenue, tax 25%, risk-free 4%, beta 1.0, ERP 5%, pre-tax cost of debt 5%,
terminal growth 2%.

By hand:
  cost of equity = 4% + 1.0 x 5% = 9%
  WACC = 80% x 9% + 20% x 5% x (1 - 25%) = 7.2% + 0.75% = 7.95%
  Year 1: revenue 1,100; EBIT 220; tax 55; D&A 55; capex 55; NWC up 10% x 100 = 10
          UFCF = 220 - 55 + 55 - 55 - 10 = 155
  Years 2-5 UFCF: 170.5, 187.55, 206.305, 226.9355 (each 10% higher)
  PV of UFCF at 7.95% = 745.71
  Terminal value = 226.9355 x 1.02 / (7.95% - 2%) = 3,890.32; PV = 3,890.32 / 1.0795^5 = 2,653.83
  EV = 3,399.54; equity = EV - 200 + 50 = 3,249.54; price = 324.95
  Year-5 EBITDA = 25% x 1,610.51 = 402.63, so the implied exit multiple = 3,890.32 / 402.63 = 9.66x
  Exit cross-check at a 12x peer median: EV = 745.71 + 12 x 402.63 / 1.0795^5 -> price 389.16,
  and that terminal value implies perpetual growth of 3.11%.
"""

from datetime import date

import pytest

from engine import dcf
from engine.metrics import CompanyMetrics
from engine.periods import Figure, missing

END = date(2026, 6, 30)


def fig(name, value, unit="USD", **kw):
    return Figure(name=name, value=value, unit=unit, formula="test", **kw)


def company(**overrides):
    F = {
        "ltm_revenue": fig("LTM revenue", 1000.0),
        "revenue_growth_ltm": fig("revenue growth (LTM)", 0.10, "ratio"),
        "revenue_growth_fy": fig("revenue growth (FY)", 0.08, "ratio"),
        "equity_value": fig("equity value", 800.0),
        "total_debt": fig("total_debt", 200.0),
        "preferred_stock": fig("preferred_stock", 0.0),
        "noncontrolling_interest": fig("noncontrolling_interest", 0.0),
        "cash": fig("cash", 50.0),
        "short_term_investments": fig("short_term_investments", 0.0),
        "shares_outstanding": fig("shares", 10.0, "shares"),
    }
    F.update(overrides)
    return CompanyMetrics(ltm_end=END, fiscal_year_ends=[], figures=F)


ASSUME = {**{k: 0.10 for k in dcf.GROWTH_KEYS}, "ebit_margin": 0.20, "da_pct": 0.05, "capex_pct": 0.05,
          "nwc_pct": 0.10, "tax_rate": 0.25, "risk_free": 0.04, "beta": 1.0, "erp": 0.05,
          "cost_of_debt": 0.05, "terminal_growth": 0.02}


def assumptions(**changes):
    return {k: Figure(dcf.LABELS[k], v, dcf.UNITS[k], "test") for k, v in {**ASSUME, **changes}.items()}


def base(peer_median=12.0):
    b = dcf.Base(ltm_end=END, years=[], ltm_interest=fig("interest", 10.0),
                 risk_free=fig("rf", 0.04, "ratio"), beta=fig("beta", 1.0, "x"))
    if peer_median is not None:
        b.peer_median_ev_ebitda = fig("peer median EV/EBITDA", peer_median, "x")
    return b


def test_wacc_by_hand():
    w, ke = dcf.wacc(assumptions(), company())
    assert ke.value == pytest.approx(0.09) and w.value == pytest.approx(0.0795)


def test_projection_by_hand():
    years = dcf.project(assumptions(), 1000.0, 0.0795, mid_year=False)
    y1 = years[0]
    assert (y1.revenue, y1.ebit, y1.taxes, y1.d_and_a, y1.capex) == pytest.approx((1100, 220, 55, 55, 55))
    assert y1.nwc_change == pytest.approx(10) and y1.ufcf == pytest.approx(155)
    assert [y.ufcf for y in years] == pytest.approx([155, 170.5, 187.55, 206.305, 226.9355])


def test_valuation_by_hand():
    r = dcf.run(assumptions(), company(), base())
    assert r.pv_fcf.value == pytest.approx(745.71, abs=0.01)
    assert r.terminal_value.value == pytest.approx(3890.32, abs=0.01)
    assert r.pv_terminal.value == pytest.approx(2653.83, abs=0.01)
    assert r.enterprise_value.value == pytest.approx(3399.54, abs=0.01)
    assert r.share_price.value == pytest.approx(324.95, abs=0.01)
    assert r.implied_exit_multiple == pytest.approx(9.66, abs=0.01)
    assert r.exit_price.value == pytest.approx(389.16, abs=0.01)
    assert r.implied_growth_from_exit == pytest.approx(0.0311, abs=0.0001)


def test_mid_year_discounts_half_a_year_less():
    end = dcf.run(assumptions(), company(), base())
    mid = dcf.run(assumptions(), company(), base(), mid_year=True)
    assert mid.years[0].period == 0.5 and mid.share_price.value > end.share_price.value
    assert mid.pv_terminal.value == pytest.approx(3890.32 / 1.0795 ** 4.5, abs=0.01)


def test_operating_loss_pays_no_tax():
    y1 = dcf.project(assumptions(ebit_margin=-0.10), 1000.0, 0.08, False)[0]
    assert y1.taxes == 0 and y1.ebit == pytest.approx(-110)


def test_growth_at_or_above_wacc_is_nm():
    r = dcf.run(assumptions(terminal_growth=0.08), company(), base())
    assert r.share_price.value is None and "not above terminal growth" in r.reason


def test_negative_final_year_cash_flow_is_nm():
    r = dcf.run(assumptions(ebit_margin=-0.20), company(), base())
    assert r.share_price.value is None and "negative" in r.reason


def test_missing_assumption_makes_dcf_na_with_reason():
    a = assumptions()
    a["beta"] = missing("Beta", "x", "price history unavailable")
    r = dcf.run(a, company(), base())
    assert r.share_price.value is None and "Beta n/a" in r.reason


def test_no_debt_means_wacc_is_cost_of_equity():
    w, _ = dcf.wacc(assumptions(cost_of_debt=0.0), company(total_debt=fig("total_debt", 0.0)))
    assert w.value == pytest.approx(0.09)


def test_sensitivity_grid_center_is_base_case():
    ws, gs, grid = dcf.sensitivity(assumptions(), company(), base(), False)
    assert ws[2] == pytest.approx(0.0795) and gs[2] == pytest.approx(0.02)
    assert grid[2][2].value == pytest.approx(324.95, abs=0.01)
    assert grid[0][4].value > grid[2][2].value > grid[4][0].value  # low WACC + high g is worth most


def test_football_bar_spans_corners():
    bar = dcf.football_bar(assumptions(), company(), base(), False)
    hi = dcf.run(assumptions(terminal_growth=0.025), company(), base(), wacc_override=0.0695).share_price.value
    assert bar["high"] == pytest.approx(hi) and bar["low"] < 324.95 < bar["high"]


# ---- defaults from history ----------------------------------------------------------


def year(end, revenue, ebit, da, capex, tax, pretax, nwc):
    return dcf.FiscalYear(end, fig("revenue", revenue), fig("EBIT", ebit), fig("D&A", da), fig("capex", capex),
                          fig("tax", tax), fig("pretax", pretax), fig("NWC", nwc))


def history_base():
    b = base()
    b.years = [year(date(2025, 12, 31), 900, 180, 45, 50, 40, 170, 90),
               year(date(2024, 12, 31), 800, 140, 40, 40, 30, 130, 96),
               year(date(2023, 12, 31), 700, 100, 35, 30, 20, 100, 84)]
    return b


def test_defaults_use_three_year_totals():
    a = dcf.default_assumptions(history_base(), company())
    assert a["ebit_margin"].value == pytest.approx(420 / 2400)  # (180+140+100) / (900+800+700)
    assert a["capex_pct"].value == pytest.approx(120 / 2400)
    assert a["tax_rate"].value == pytest.approx(90 / 400)
    assert a["nwc_pct"].value == pytest.approx((90 / 900 + 96 / 800 + 84 / 700) / 3)
    assert "FY2023-FY2025" in a["ebit_margin"].formula


def test_growth_fades_to_terminal():
    a = dcf.default_assumptions(history_base(), company())
    g = [a[k].value for k in dcf.GROWTH_KEYS]
    assert g == pytest.approx([0.10, 0.08125, 0.0625, 0.04375, 0.025])


def test_cost_of_debt_is_interest_over_debt():
    a = dcf.default_assumptions(history_base(), company())
    assert a["cost_of_debt"].value == pytest.approx(10 / 200)


def test_unusable_tax_rate_falls_back_to_statutory_with_note():
    b = history_base()
    b.years = [year(date(2025, 12, 31), 900, 180, 45, 50, 40, -10, 90)]  # tax on a pretax loss
    a = dcf.default_assumptions(b, company())
    assert a["tax_rate"].value == 0.21 and "21%" in a["tax_rate"].formula
    assert any("statutory" in n for n in a["tax_rate"].notes)


def test_edited_assumption_records_default():
    a = dcf.default_assumptions(history_base(), company())
    e = dcf.edited("ebit_margin", 0.30, a["ebit_margin"])
    assert e.value == 0.30 and "default was 17.50%" in e.formula


def test_beta_default_is_adjusted_toward_one():
    b = history_base()
    b.beta = fig("beta", 1.6, "x")
    a = dcf.default_assumptions(b, company())
    assert a["beta"].value == pytest.approx(0.67 * 1.6 + 0.33) and "adjusted" in a["beta"].formula


def test_sanity_notes_flag_heavy_capex_and_terminal_weight():
    r = dcf.run(assumptions(capex_pct=0.10), company(), base(), steady_state=False)
    assert any("Capex" in n and "2.0x D&A" in n for n in r.notes)
    assert dcf.run(assumptions(), company(), base()).notes == []


def test_steady_state_terminal_year_caps_capex_at_d_and_a():
    # Capex 10% of revenue vs D&A 5%. Year 5: revenue 1,610.51, NOPAT 241.58, D&A 80.53,
    # capex 161.05, NWC increase 14.64.
    #   steady state: 241.58 + 80.53 - 80.53 - 14.64 = 226.94 (capex set to D&A)
    #   as projected: 241.58 + 80.53 - 161.05 - 14.64 = 146.41
    on = dcf.run(assumptions(capex_pct=0.10), company(), base())
    off = dcf.run(assumptions(capex_pct=0.10), company(), base(), steady_state=False)
    assert on.terminal_fcf.value == pytest.approx(226.9355, abs=0.001)
    assert off.terminal_fcf.value == pytest.approx(146.41, abs=0.01)
    assert on.years[-1].capex == off.years[-1].capex  # only the terminal year changes
    assert on.share_price.value > off.share_price.value


def test_steady_state_leaves_capex_below_d_and_a_alone():
    # Amortization-heavy companies (capex < D&A) keep their projected capex.
    on = dcf.run(assumptions(capex_pct=0.02), company(), base())
    off = dcf.run(assumptions(capex_pct=0.02), company(), base(), steady_state=False)
    assert on.share_price.value == pytest.approx(off.share_price.value)
