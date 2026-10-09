"""Phase 2 smoke test on real data. Opt-in: RUN_LIVE=1 pytest -m live"""

import os

import pytest

from engine import market, metrics
from engine.sec_client import SECClient
from engine.tickers import get_metadata, lookup
from engine.xbrl import get_series

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.getenv("RUN_LIVE") != "1", reason="set RUN_LIVE=1 to hit the real SEC API"),
]


@pytest.mark.parametrize("ticker", ["AAPL", "MSFT", "GOOGL"])
def test_full_metrics(ticker):
    client = SECClient()
    company = lookup(ticker, client)
    meta = get_metadata(company.cik, client)
    last = meta.latest("10-K", "10-Q")
    m = metrics.compute(get_series(company.cik, client, meta), last.report_date,
                        market.get_quote(ticker).price)
    for k in ("ltm_revenue", "ltm_ebitda", "ltm_net_income", "total_debt", "cash",
              "enterprise_value", "ev_revenue", "ev_ebitda", "pe"):
        assert m[k].ok, f"{ticker} {k}: {m[k].reason}"
    assert m["ltm_revenue"].as_of == last.report_date
    assert 0 < m["ebitda_margin"].value < 1
    assert len(m.fiscal_year_ends) == 2
