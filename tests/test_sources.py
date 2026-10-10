"""The rows behind every "Sources" panel (CLAUDE.md rule 2)."""

from datetime import date

from engine.metrics import combine
from engine.periods import Figure, ltm
from engine.sources import fact_rows, formula_tree, other_sources
from tests.test_periods import rev


def test_ltm_rows_show_every_filing_with_sign():
    f = ltm(rev(), date(2026, 6, 27))
    rows = fact_rows(f, 320193)
    assert [(r[""], r["value"]) for r in rows] == [("+", 1200), ("+", 1000), ("−", 850)]
    assert rows[0]["accession"] == "A-25-10K" and rows[0]["form"] == "10-K"
    assert rows[1]["period"] == "2025-09-28 to 2026-06-27"
    assert rows[0]["link"].startswith("https://www.sec.gov/") and "320193" in rows[0]["link"]


def test_computed_figure_walks_its_inputs():
    f = ltm(rev(), date(2026, 6, 27))
    total = combine("double", [(1, f), (1, f)], "USD", "test")
    assert len(fact_rows(total, None)) == 3  # same facts, listed once
    assert fact_rows(total, None)[0]["link"] == ""


def test_price_source_listed_once():
    price = Figure("share price", 100.0, "USD/share", "close on 2026-10-08", source="Yahoo Finance")
    equity = Figure("equity value", 1000.0, "USD", "price x shares", inputs=(price, price))
    assert other_sources(equity) == ["share price: Yahoo Finance (close on 2026-10-08)"]


def test_formula_tree_indents_inputs_and_shows_nm():
    child = Figure("LTM EBITDA", -5.0, "USD", "EBIT + D&A")
    nm = Figure("EV/EBITDA", None, "x", "EV / LTM EBITDA", inputs=(child,), nm=True, reason="negative EBITDA")
    lines = formula_tree(nm)
    assert lines[0] == "EV/EBITDA = NM [x]: EV / LTM EBITDA (negative EBITDA)"
    assert lines[1].startswith("  LTM EBITDA = -5 [USD]")


def test_facts_under_a_product_inside_a_sum_are_listed():
    shares = ltm(rev(), date(2026, 6, 27))  # stands in for any figure with facts
    product = Figure("equity value", 1.0, "USD", "price x shares", inputs=(shares,))
    cash = ltm(rev(), date(2025, 9, 27))
    ev = combine("EV", [(1, product), (-1, cash)], "USD", "test")
    signs = [r[""] for r in fact_rows(ev, None)]
    assert signs == ["−", "+", "+", "−"]  # cash (subtracted), then the 3 LTM facts via the product
