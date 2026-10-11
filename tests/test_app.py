"""Smoke test of the Streamlit page with a fake report (no network).

Checks the page renders every section, shows NM / n/a instead of numbers, and
that a dollar range isn't mangled by Streamlit's LaTeX markdown.
"""

from datetime import date
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from engine import comps, interview, learn
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
    button(app, "Build tearsheet").click().run()
    assert not app.exception
    subheaders = [s.value for s in app.subheader]
    for name in ("Financial summary", "Enterprise value bridge", "Trading comps", "Implied valuation (FD-8)"):
        assert name in subheaders
    metrics = {m.label: m.value for m in app.metric}
    assert metrics["Share price"] == "$100.00" and metrics["EV/EBITDA (LTM)"] == "20.0x"
    captions = " ".join(c.value for c in app.caption)
    assert r"\$80.00 to \$130.00" in captions  # escaped, so it isn't rendered as LaTeX
    assert len(app.get("plotly_chart")) == 3  # financials + DCF tornado + football field
    assert "Discounted cash flow (FD-11)" in subheaders and "Football field" in subheaders
    notes = " ".join(m.value for m in app.markdown)
    assert "F: left out of the comps" in notes and "E EV/EBITDA: NM" in notes
    assert len([e for e in app.expander if e.label.startswith("Sources")]) == 7  # + thesis support
    # Phase 4e: thesis support and the pitch deck download
    assert "Thesis support" in subheaders
    assert any("vs its peers" in m.value for m in app.markdown)
    assert any("Valuation at a glance" in m.value for m in app.markdown)
    labels = [b.label for b in app.get("download_button")]
    assert labels == ["Download pitch deck", "Download Excel", "Download DCF model", "Download tearsheet slides"]
    check = next(e for e in app.expander if e.label.startswith("Peer set check (FD-9)"))
    assert "5 of 5 peers" in check.label  # F failed to load: not counted


def test_dcf_responds_to_edits(app):
    app.text_input[0].set_value("T")
    button(app, "Build tearsheet").click().run()
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
    button(at, "Build tearsheet").click().run()
    assert "not in the SEC ticker list" in at.error[0].value


def fake_sector(name, tickers, **_):
    from engine import sector
    from tests.test_sector import screen
    s = screen()
    s.name = name
    return s


def test_sector_screen_and_deep_dive(monkeypatch):
    monkeypatch.setattr("engine.report.build_report", fake_report)
    monkeypatch.setattr("engine.report.build_sector", fake_sector)
    st.cache_data.clear()
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    at.radio[0].set_value("Sector screen").run()
    assert any("Choose a sector list" in i.value for i in at.info)
    at.selectbox[0].set_value("Semiconductors").run()
    assert "NVDA" in at.text_area[0].value
    button(at, "Build sector screen").click().run()
    assert not at.exception
    assert "Talking points" in [s.value for s in at.subheader]
    assert len(at.get("plotly_chart")) == 2  # scatter + ranking
    assert len(at.get("download_button")) == 2
    assert "Pitch builder" in [s.value for s in at.subheader]
    # percentile-rank view and filters re-slice the loaded screen without refetching
    next(r for r in at.radio if "Values" in r.options).set_value("Percentile rank within the screen").run()
    assert not at.exception
    next(n for n in at.number_input if n.label.startswith("Min LTM revenue growth")).set_value(12.0).run()
    assert not at.exception
    assert any("Filtered out: A, C" in c.value for c in at.caption)
    assert at.header[0].value.endswith("(filtered): 3 companies")
    next(n for n in at.number_input if n.label.startswith("Min LTM revenue growth")).set_value(None).run()
    next(s for s in at.selectbox if s.label == "Company to pitch").set_value("A").run()
    deep = button(at, "Open A with the whole screen as peers")
    deep.click().run()
    assert not at.exception
    assert at.radio[0].value == "Company tearsheet"
    assert at.text_input[0].value == "A" and "B C D E" in at.text_area[0].value
    assert len(at.get("download_button")) == 4 and "Talking points" in [s.value for s in at.subheader]


def test_learn_mode_explains_clicked_cells(app):
    app.text_input[0].set_value("T")
    app.text_area[0].set_value("A B C D E F")
    app.button[0].click().run()
    assert app.toggle(key="learn").value is False  # off by default: experienced users get a clean page
    assert not any(e.label.startswith("Step by step") for e in app.expander)
    app.toggle(key="learn").set_value(True).run()
    assert any(e.label.startswith("Step by step: how this DCF gets to") for e in app.expander)
    clicks = {"fin": ((0, "LTM (2026-06-30)"), "Revenue, LTM (2026-06-30)"),
              "ev": ((8, "value"), "Enterprise value"), "comps": ((0, "EV/EBITDA"), "T: EV/EBITDA"),
              "comps2": ((7, "EV/EBITDA"), "Peers: 25th percentile EV/EBITDA"),
              "implied": ((0, "Implied price"), "Implied price range from EV/EBITDA"),
              "dcf-proj": ((8, "Year 3"), "Unlevered free cash flow, year 3"),
              "dcf-bridge": ((10, "value"), "DCF share price (intrinsic value)"),
              "dcf-wacc": ((1, "value"), "Beta"), "dcf-sens": ((1, "g 2.00%"), "Share price at WACC")}
    for key, (cell, title) in clicks.items():
        app.session_state[f"click-{key.rstrip('2')}"] = {"selection": {"rows": [], "columns": [], "cells": [cell]}}
        app.run()
        assert not app.exception, key
        cards = [m.value for m in app.markdown if m.value.startswith("**") and " · " in m.value]
        assert any(c.startswith(f"**{title}") for c in cards[6:]), (key, cards)  # first 6 are the tile popovers
        if key == "dcf-proj":
            assert any("NOPAT +" in c.value and "NWC build =" in c.value for c in app.code)


def test_learn_mode_off_is_a_clean_page(app):
    app.text_input[0].set_value("T")
    app.button[0].click().run()
    assert not app.exception
    assert not any("Click any number" in c.value for c in app.caption)
    assert not [p for p in app.get("popover")]


def test_learn_page_walks_through_every_chapter(app):
    app.text_input[0].set_value("T")
    app.text_area[0].set_value("A B C D E F")
    app.button[0].click().run()
    app.radio(key="mode").set_value("Learn").run()
    assert not app.exception
    assert app.text_input(key="learn_ticker").value == "T"  # the tearsheet's company is the example
    titles = [ch.title for ch in learn.COURSE]
    for title in titles:
        assert app.radio(key="learn_chapter").value == title
        assert title in [s.value for s in app.subheader]
        app.button(key="learn_next").click().run()
        assert not app.exception, title
    assert "Glossary" in [s.value for s in app.subheader]
    app.radio(key="learn_chapter").set_value(titles[5]).run()  # the DCF: walkthrough + clickable model
    assert any("Year 1:" in c.value for c in app.code)
    app.session_state["click-learn-dcf"] = {"selection": {"rows": [], "columns": [], "cells": [(8, "Year 2")]}}
    app.run()
    assert any(m.value.startswith("**Unlevered free cash flow, year 2") for m in app.markdown)
    app.radio(key="learn_chapter").set_value(titles[6]).run()  # what moves a valuation
    assert any(n.label.startswith("New value") for n in app.number_input)
    app.radio(key="mode").set_value("Company tearsheet").run()
    assert not app.exception and app.toggle(key="learn").value is False


def test_deep_learn_mode_has_tabs_with_hidden_answers(app):
    app.radio(key="mode").set_value("Learn").run()
    app.text_input(key="learn_ticker").set_value("T").run()
    assert not app.tabs  # deep mode is opt-in
    app.toggle(key="learn_deep").set_value(True).run()
    for i, ch in enumerate(learn.COURSE):
        app.radio(key="learn_chapter").set_value(ch.title).run()
        assert not app.exception, ch.title
        sections = interview.DEEP[i]
        assert [t.label for t in app.tabs] == ["Core idea", *[s.title for s in sections]]
        labels = [e.label for e in app.expander]
        for s in sections:
            for n, (q, _) in enumerate(s.questions, 1):
                assert f"Q{n}. {q}" in labels  # every tab has its questions, answers inside a closed expander


def button(at, label):
    return next(b for b in at.button if b.label.startswith(label))


def test_size_band_peers_and_trim(monkeypatch):
    """Pitch builder opens with FD-9 size-band peers; the peer check trims an out-of-band peer."""
    from tests.test_sector import screen

    def sized_report(target, peers, **_):
        rep = fake_report(target, [])
        big = company("BIG", 9, **{**EXTRA, "equity_value": fig("equity value", 10_000.0)})
        rows = [company(p, 10, **EXTRA) for p in peers if p != "BIG"] + ([big] if "BIG" in peers else [])
        rep.comps = comps.build(rep.target, rows)
        return rep

    def sized_sector(name, tickers, **_):
        s = screen()
        s.loaded[1].metrics.figures["equity_value"] = fig("equity value", 10_000.0)  # B is 10x the others
        return sector.build(name, s.loaded)

    from engine import sector
    monkeypatch.setattr("engine.report.build_report", sized_report)
    monkeypatch.setattr("engine.report.build_sector", sized_sector)
    st.cache_data.clear()
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    at.radio[0].set_value("Sector screen").run()
    at.selectbox[0].set_value("Semiconductors").run()
    button(at, "Build sector screen").click().run()
    button(at, "Open A with the 3 size-band peers").click().run()
    assert not at.exception
    assert at.text_area[0].value == "C D E"  # B (10x A's market cap) left out
    at.text_area[0].set_value("C D BIG")
    button(at, "Build tearsheet").click().run()
    trim = button(at, "Keep only the 2 peers in the size band")
    trim.click().run()
    assert not at.exception and at.text_area[0].value == "C D"


def test_sic_peer_suggestions(monkeypatch):
    from engine.peers import Candidate, CandidateList, Revenue

    def fake_sic(ticker, client, limit=12):
        rev = Revenue(500.0, "Revenues", date(2025, 1, 1), date(2025, 12, 31), "0000000001-26-000001")
        return CandidateList("3674", "Semiconductors", 2025, None,
                             [Candidate("PQR", 2, "PQR Corp", rev, 1.25, True)], ["1 of 1 within the band"])
    monkeypatch.setattr("engine.report.build_report", fake_report)
    monkeypatch.setattr("engine.peers.sic_candidates", fake_sic)
    monkeypatch.setattr("engine.sec_client.SECClient.__init__", lambda self, *a, **k: None)
    st.cache_data.clear()
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    at.text_input[0].set_value("T")
    button(at, "Build tearsheet").click().run()
    button(at, "Suggest peers from T's SEC industry code").click().run()
    assert not at.exception
    assert at.text_area[0].value == "PQR"
    assert any(e.label.startswith("SIC peer suggestions") for e in at.expander)
