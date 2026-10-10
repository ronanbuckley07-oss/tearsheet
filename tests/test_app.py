"""Smoke test of the Streamlit page with a fake report (no network).

Checks the page renders every section, shows NM / n/a instead of numbers, and
that a dollar range isn't mangled by Streamlit's LaTeX markdown.
"""

from datetime import date
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from engine import comps
from engine.comps import CompanyRow
from engine.periods import Figure
from engine.report import Report
from tests.test_comps import company, fig
from tests.test_dcf import company as dcf_company, history_base

APP = str(Path(__file__).resolve().parent.parent / "app.py")

EXTRA = {
    "price": fig("share price", 100.0, "USD/share", as_of=date(2026, 10, 8), source="Yahoo Finance"),
    "equity_value": fig("equity value", 1000.0),
    "enterprise_value": fig("enterprise value", 1025.0),
    "ltm_operating_income": fig("LTM operating income", 80.0),
    "ltm_d_and_a": fig("LTM D&A", 20.0),
    "ltm_net_income": fig("LTM net income", 50.0),
    "ltm_sbc": fig("LTM SBC", 5.0),
    "revenue_growth_fy": fig("growth", 0.08, "ratio"),
    "net_debt": fig("net debt", 20.0),
    "diluted_shares": fig("diluted shares", 10.1, "shares"),
    "share_count_check": fig("check", 0.01, "ratio"),
}


def fake_report(target, peers, **_):
    t = company("T", 20, **EXTRA)
    t.metrics.fiscal_years[date(2025, 12, 31)] = {"revenue": fig("revenue", 350.0), "ebitda": fig("EBITDA", 90.0)}
    t = CompanyRow(t.ticker, "Target Co", t.metrics, high_52w=t.high_52w, low_52w=t.low_52w,
                   cik=1, sic_description="Widgets", fiscal_year_end="1231",
                   latest_filing="10-Q 0000000001-26-000001 (period end 2026-06-30)")
    peers = [company(p, m, **EXTRA) for p, m in (("A", 8), ("B", 14), ("C", 10), ("D", 12), ("E", None))]
    peers.append(CompanyRow("F", "F", None, error="files 20-F/40-F (foreign filer); v1 covers 10-K filers only"))
    t.metrics.figures.update({k: v for k, v in dcf_company().figures.items() if k not in t.metrics.figures})
    return Report(target=t, comps=comps.build(t, peers), dcf_base=history_base())


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr("engine.report.build_report", fake_report)
    st.cache_data.clear()
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    return at


def test_empty_page_asks_for_ticker(app):
    assert not app.exception
    assert any("Enter a ticker" in i.value for i in app.info)


def test_full_page_renders(app):
    app.text_input[0].set_value("T")
    app.text_area[0].set_value("A B C D E F")
    app.button[0].click().run()
    assert not app.exception
    subheaders = [s.value for s in app.subheader]
    for name in ("Financial summary", "Enterprise value bridge", "Trading comps", "Implied valuation (FD-8)"):
        assert name in subheaders
    metrics = {m.label: m.value for m in app.metric}
    assert metrics["Share price"] == "$100.00" and metrics["EV/EBITDA (LTM)"] == "20.0x"
    captions = " ".join(c.value for c in app.caption)
    assert r"\$80.00 to \$130.00" in captions  # escaped, so it isn't rendered as LaTeX
    assert len(app.get("plotly_chart")) == 2  # financials + football field
    assert "Discounted cash flow (FD-11)" in subheaders and "Football field" in subheaders
    notes = " ".join(m.value for m in app.markdown)
    assert "F: left out of the comps" in notes and "E EV/EBITDA: NM" in notes
    assert len([e for e in app.expander if e.label.startswith("Sources")]) == 6


def test_dcf_responds_to_edits(app):
    app.text_input[0].set_value("T")
    app.button[0].click().run()
    price = {m.label: m.value for m in app.metric}["DCF share price"]
    margin = next(n for n in app.number_input if n.label == "EBIT margin (%)")
    assert margin.value == 17.5  # 3-year total EBIT / revenue from history_base()
    margin.set_value(30.0).run()
    assert not app.exception
    assert {m.label: m.value for m in app.metric}["DCF share price"] != price
    g = next(n for n in app.number_input if n.label == "Terminal growth rate (%)")
    g.set_value(50.0).run()
    assert any("not above terminal growth" in w.value for w in app.warning)


def test_missing_target_shows_error(monkeypatch):
    def bad(target, peers, **_):
        row = CompanyRow("ZZZZ", "ZZZZ", None, error="not in the SEC ticker list")
        return Report(target=row, comps=comps.build(row, []))
    monkeypatch.setattr("engine.report.build_report", bad)
    st.cache_data.clear()
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    at.text_input[0].set_value("ZZZZ")
    at.button[0].click().run()
    assert "not in the SEC ticker list" in at.error[0].value
