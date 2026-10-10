"""Sector screen and data fallbacks on real data. Opt-in: RUN_LIVE=1 pytest -m live"""

import os

import pytest

from engine.presets import SECTORS
from engine.report import build_sector

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.getenv("RUN_LIVE") != "1", reason="set RUN_LIVE=1 to hit the real SEC API"),
]


@pytest.mark.parametrize("name", list(SECTORS))
def test_every_preset_loads(name):
    s = build_sector(name, list(SECTORS[name]))
    failed = {r.ticker: r.error for r in s.rows if r.metrics is None}
    assert not failed, failed
    assert s.stats["ev_revenue"].n >= len(SECTORS[name]) - 2


def test_fallbacks_on_known_cases():
    s = build_sector("check", ["LLY", "PG", "PEP", "V"])
    by = {r.ticker: r for r in s.loaded}
    # Lilly reports no operating income line (FD-10 Q15).
    assert by["LLY"].get("ltm_operating_income").ok
    # P&G tags balance-sheet cash only with the restricted-cash total (FD-10 Q14).
    assert by["PG"].get("cash").ok and any("FD-10 Q14" in n for n in by["PG"].get("cash").all_notes())
    # PepsiCo's 36-week YTD.
    assert by["PEP"].get("ltm_ebitda").ok
    # Visa: share classes and a 2010 undimensioned cover count.
    assert by["V"].get("shares_outstanding").as_of.year >= 2026
