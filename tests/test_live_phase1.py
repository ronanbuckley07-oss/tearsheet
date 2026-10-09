"""Phase 1 checks against real SEC data. Opt-in: RUN_LIVE=1 pytest -m live

AAPL (Sept FYE, 52/53-week year), MSFT (June FYE), GOOGL (December FYE, three
share classes). Expected revenues are as reported in each company's FY2024 10-K.

Fiscal year end is checked by month only: for 52/53-week filers the SEC's
fiscalYearEnd moves with the latest year (Apple: 0928 for FY2024, 0926 for FY2025).
"""

import os
from datetime import date

import pytest

from engine.sec_client import SECClient
from engine.tickers import get_metadata, lookup
from engine.xbrl import PeriodType, get_series

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.getenv("RUN_LIVE") != "1", reason="set RUN_LIVE=1 to hit the real SEC API"),
]

CASES = [
    # ticker, cik, fiscal year end month, FY2024 period end, FY2024 revenue (USD)
    ("AAPL", 320193, 9, date(2024, 9, 28), 391_035_000_000),
    ("MSFT", 789019, 6, date(2024, 6, 30), 245_122_000_000),
    ("GOOGL", 1652044, 12, date(2024, 12, 31), 350_018_000_000),
]

CORE = ["revenue", "operating_income", "d_and_a", "net_income", "cash",
        "diluted_shares_weighted", "shares_outstanding_cover"]


@pytest.fixture(scope="module")
def client():
    return SECClient()


@pytest.fixture(scope="module")
def data(client):
    out = {}
    for ticker, *_ in CASES:
        company = lookup(ticker, client)
        meta = get_metadata(company.cik, client)
        out[ticker] = (company, meta, get_series(company.cik, client, meta))
    return out


@pytest.mark.parametrize("ticker,cik,fye,fy24_end,fy24_rev", CASES)
def test_company(data, ticker, cik, fye, fy24_end, fy24_rev):
    company, meta, series = data[ticker]
    assert company.cik == cik
    assert meta.fiscal_year_end_month == fye and meta.in_scope

    for m in CORE:
        assert series[m], f"{ticker} {m} empty: {series[m].notes}"

    fy24 = [f for f in series["revenue"].of_type(PeriodType.ANNUAL) if f.end == fy24_end]
    assert len(fy24) == 1, f"{ticker}: expected one FY2024 revenue fact"
    assert fy24[0].value == fy24_rev
    assert fy24[0].source.form.startswith("10-K")

    for s in series.values():
        for f in s.facts:
            assert f.source.accession and f.source.filed and f.source.tag


def test_googl_share_classes_summed(data):
    _, _, series = data["GOOGL"]
    latest = series["shares_outstanding_cover"].latest()
    assert latest.note and "share classes" in latest.note


def test_googl_cover_shares_match_balance_sheet_scale(data):
    # Cover count is a later date than the balance sheet, so only a sanity band.
    _, _, series = data["GOOGL"]
    latest = series["shares_outstanding_cover"].latest()
    assert len(latest.sources) == 3  # Class A, B, C
    assert 11e9 < latest.value < 13.5e9


def test_msft_finance_leases_found(data):
    # MSFT tags only the total finance lease liability, not the current/noncurrent split.
    _, _, series = data["MSFT"]
    assert series["finance_lease_total"]
    assert not series["finance_lease_current"]


def test_googl_fy2025_d_and_a_is_depreciation_only(data):
    # FD-10 Q1: Alphabet's FY2025 cash flow shows depreciation only.
    _, _, series = data["GOOGL"]
    fy25 = series["d_and_a"].get(date(2025, 1, 1), date(2025, 12, 31))
    assert fy25.value == 21_136_000_000 and fy25.tag == "Depreciation"
