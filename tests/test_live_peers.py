"""SIC-code peer search on real SEC data (FD-15). SEC only, no prices. Opt-in: RUN_LIVE=1 pytest -m live"""

import os

import pytest

from engine import peers
from engine.sec_client import SECClient

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.getenv("RUN_LIVE") != "1", reason="set RUN_LIVE=1 to hit the real SEC API"),
]


def test_trucking_list_from_sic_code():
    out = peers.sic_sector("4213", SECClient(), year=2025)
    # J.B. Hunt and Old Dominion tag only the "including assessed tax" revenue line.
    assert {"KNX", "JBHT", "ODFL", "SAIA"} <= set(out.tickers)
    assert all(c.revenue.accession for c in out.candidates)


def test_semiconductor_candidates_flag_mis_scaled_revenue():
    out = peers.sic_candidates("NVDA", SECClient(), year=2025, limit=8)
    assert out.sic == "3674" and "AVGO" in out.tickers and "NVDA" not in out.tickers
    assert out.candidates[0].in_band  # in-band names come first
    assert any("TYGO" in n for n in out.notes)  # Tigo's 10-K tags $103.5m once as $103.5bn
