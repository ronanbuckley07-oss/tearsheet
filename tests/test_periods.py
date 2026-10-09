"""LTM, fiscal-year and balance-date logic on small hand-built series."""

from datetime import date

from engine.periods import balance_at, fiscal_year, latest_fiscal_year_ends, ltm, prior_ltm_end
from engine.xbrl import extract_metric
from tests.test_xbrl import facts, row

# A September fiscal year company (52/53-week dates like Apple's).
# FY2024: 2023-10-01..2024-09-28 = 1000, FY2025: 2024-09-29..2025-09-27 = 1200
# 9M FY2025: 2024-09-29..2025-06-28 = 850, 9M FY2026: 2025-09-28..2026-06-27 = 1000
# 9M FY2024: 2023-10-01..2024-06-29 = 700
REVENUE = facts({"Revenues": [
    row(1000, "2024-09-28", "2023-10-01", filed="2024-11-01"),
    row(1200, "2025-09-27", "2024-09-29", filed="2025-10-31", accn="A-25-10K"),
    row(700, "2024-06-29", "2023-10-01", form="10-Q", filed="2024-08-01"),
    row(850, "2025-06-28", "2024-09-29", form="10-Q", filed="2025-08-01"),
    row(1000, "2026-06-27", "2025-09-28", form="10-Q", filed="2026-07-31", accn="A-26-10Q"),
    # Q3 alone also reported; must not be mistaken for the YTD
    row(330, "2026-06-27", "2026-03-29", form="10-Q", filed="2026-07-31"),
]})


def rev():
    return extract_metric(REVENUE, "revenue")


def test_ltm_from_10q_is_fy_plus_ytd_minus_prior_ytd():
    f = ltm(rev(), date(2026, 6, 27))
    assert f.value == 1200 + 1000 - 850
    signs = [(s, x.value) for s, x in f.facts]
    assert signs == [(1, 1200), (1, 1000), (-1, 850)]
    assert f.start == date(2025, 6, 29) and f.as_of == date(2026, 6, 27)
    assert "prior YTD" in f.formula


def test_ltm_at_fiscal_year_end_is_the_fiscal_year():
    f = ltm(rev(), date(2025, 9, 27))
    assert f.value == 1200 and len(f.facts) == 1
    assert "10-K" in f.formula


def test_ltm_missing_prior_ytd_is_na_with_reason():
    s = extract_metric(facts({"Revenues": [
        row(1200, "2025-09-27", "2024-09-29"),
        row(1000, "2026-06-27", "2025-09-28", form="10-Q"),
    ]}), "revenue")
    f = ltm(s, date(2026, 6, 27))
    assert f.value is None and "prior-year" in f.reason


def test_ltm_missing_ytd_is_na_not_stale_fiscal_year():
    # Rule 3: never substitute the last fiscal year for LTM silently.
    s = extract_metric(facts({"Revenues": [row(1200, "2025-09-27", "2024-09-29")]}), "revenue")
    f = ltm(s, date(2026, 6, 27))
    assert f.value is None and "year-to-date" in f.reason


def test_ltm_q1_uses_quarter_as_ytd():
    s = extract_metric(facts({"Revenues": [
        row(1200, "2025-12-31", "2025-01-01"),
        row(300, "2026-03-31", "2026-01-01", form="10-Q"),
        row(250, "2025-03-31", "2025-01-01", form="10-Q"),
    ]}), "revenue")
    assert ltm(s, date(2026, 3, 31)).value == 1250


def test_prior_ltm_end():
    assert prior_ltm_end(rev(), date(2026, 6, 27)) == date(2025, 6, 28)
    assert prior_ltm_end(rev(), date(2025, 9, 27)) == date(2024, 9, 28)


def test_prior_ltm_value():
    assert ltm(rev(), date(2025, 6, 28)).value == 1000 + 850 - 700


def test_fiscal_years_only_from_10k():
    ends = latest_fiscal_year_ends(rev(), date(2026, 6, 27))
    assert ends == [date(2025, 9, 27), date(2024, 9, 28)]
    assert fiscal_year(rev(), date(2025, 9, 27)).value == 1200
    assert fiscal_year(rev(), date(2023, 9, 30)).value is None


def test_ltm_flags_mixed_tags():
    s = extract_metric(facts({
        "Revenues": [row(1200, "2025-12-31", "2025-01-01")],
        "RevenueFromContractWithCustomerExcludingAssessedTax": [
            row(300, "2026-03-31", "2026-01-01", form="10-Q"),
            row(250, "2025-03-31", "2025-01-01", form="10-Q"),
        ],
    }), "revenue")
    f = ltm(s, date(2026, 3, 31))
    assert any("different tags" in n for n in f.notes)


# ---- balance sheet ---------------------------------------------------------------

CASH = facts({"CashAndCashEquivalentsAtCarryingValue": [
    row(50, "2025-09-27"), row(60, "2026-06-27", form="10-Q"),
]})


def test_balance_exact_date():
    s = extract_metric(CASH, "cash")
    assert balance_at(s, date(2026, 6, 27), date(2025, 9, 27)).value == 60


def test_balance_annual_only_item_uses_latest_10k_flagged():
    # FD-10 Q3
    s = extract_metric(facts({"FinanceLeaseLiabilityCurrent": [row(538, "2025-09-27")]}), "finance_lease_current")
    f = balance_at(s, date(2026, 6, 27), date(2025, 9, 27))
    assert f.value == 538 and f.as_of == date(2025, 9, 27)
    assert any("FD-10 Q3" in n for n in f.notes)


def test_balance_older_than_latest_10k_is_na():
    s = extract_metric(facts({"ShortTermBorrowings": [row(0, "2018-06-30")]}), "debt_short_term_borrowings")
    f = balance_at(s, date(2026, 6, 30), date(2026, 6, 30))
    assert f.value is None and "2018-06-30" in f.reason


def test_balance_from_10q_not_used_as_annual_fallback():
    s = extract_metric(facts({"CashAndCashEquivalentsAtCarryingValue": [
        row(40, "2026-03-28", form="10-Q")]}), "cash")
    assert balance_at(s, date(2026, 6, 27), date(2025, 9, 27)).value is None
