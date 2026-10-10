"""DCF (FD-11) on real data. Opt-in: RUN_LIVE=1 pytest -m live"""

import os

import pytest

from engine import dcf
from engine.report import build_report

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.getenv("RUN_LIVE") != "1", reason="set RUN_LIVE=1 to hit the real SEC API"),
]


def test_nvda_dcf_runs_from_filings_and_markets():
    r = build_report("NVDA", ["AMD", "AVGO", "QCOM"])
    b, m = r.dcf_base, r.target.metrics
    assert len(b.years) == 3 and all(y.capex.ok and y.nwc.ok for y in b.years)
    assert 0 < b.risk_free.value < 0.15 and b.beta.ok and b.peer_median_ev_ebitda.ok
    a = dcf.default_assumptions(b, m)
    assert all(f.ok for f in a.values()), {k: f.reason for k, f in a.items() if not f.ok}
    res = dcf.run(a, m, b)
    assert res.reason is None and res.share_price.value > 0 and res.exit_price.ok


def test_apple_cost_of_debt_is_na_not_guessed():
    # Apple stopped tagging interest expense in FY2023 (rule 3: say so, don't fill it).
    r = build_report("AAPL", [])
    a = dcf.default_assumptions(r.dcf_base, r.target.metrics)
    assert a["cost_of_debt"].value is None and "enter it" in a["cost_of_debt"].reason
