"""Phase 1 checks against real SEC data. Opt-in: RUN_LIVE=1 pytest -m live

AAPL (Sept FYE, 52/53-week year), MSFT (June FYE), GOOGL (December FYE, three
share classes). Expected revenues are as reported in each company's FY2024 10-K.
"""

import os
from datetime import date

import pytest

from engine.sec_client import SECClient
from engine.tickers import get_metadata, lookup
from engine.xbrl import PeriodType, extract_all, get_company_facts

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.getenv("RUN_LIVE") != "1", reason="set RUN_LIVE=1 to hit the real SEC API"),
]

CASES = [
    # ticker, cik, fiscal year end, FY2024 period end, FY2024 revenue (USD)
    ("AAPL", 320193, "0928", date(2024, 9, 28), 391_035_000_000),
    ("MSFT", 789019, "0630", date(2024, 6, 30), 245_122_000_000),
    ("GOOGL", 1652044, "1231", date(2024, 12, 31), 350_018_000_000),
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
        out[ticker] = (company, get_metadata(company.cik, client),
                       extract_all(get_company_facts(company.cik, client)))
    return out


@pytest.mark.parametrize("ticker,cik,fye,fy24_end,fy24_rev", CASES)
def test_company(data, ticker, cik, fye, fy24_end, fy24_rev):
    company, meta, series = data[ticker]
    assert company.cik == cik
    assert meta.fiscal_year_end == fye and meta.in_scope

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
