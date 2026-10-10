"""Phase 3 on real data. Opt-in: RUN_LIVE=1 pytest -m live"""

import os

import pytest

from engine.report import build_report

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.getenv("RUN_LIVE") != "1", reason="set RUN_LIVE=1 to hit the real SEC API"),
]


def test_nvda_comps():
    r = build_report("NVDA", ["AVGO", "AMD", "QCOM", "TXN", "TSM"])
    tsm = next(p for p in r.comps.peers if p.ticker == "TSM")
    assert tsm.metrics is None and "20-F" in tsm.error
    assert r.comps.stats["ev_revenue"].n == 4
    for key in ("ev_ebitda", "ev_revenue"):
        lo, mid, hi = r.comps.implied[key].share_price
        assert lo.ok and hi.ok and lo.value <= mid.value <= hi.value
