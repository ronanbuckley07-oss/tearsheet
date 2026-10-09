"""Engine vs the owner's hand-checked values in the SPEC.md validation table.

Live (needs SEC access). Rows left blank are skipped. Tolerance 0.5% (SPEC.md).
A mismatch gets explained, not patched over.
"""

import os
import re
from datetime import date
from pathlib import Path

import pytest

from engine import metrics
from engine.periods import Figure
from engine.sec_client import SECClient
from engine.tickers import get_metadata, lookup
from engine.xbrl import get_series

SPEC = Path(__file__).resolve().parent.parent / "SPEC.md"
TOLERANCE = 0.005
COLUMNS = ["ticker", "period_end", "ltm_revenue", "ltm_ebitda", "total_debt", "cash_plus_sti", "diluted_shares"]


def validation_rows(text: str) -> list[dict]:
    section = text.split("## Validation set", 1)[-1]
    rows = []
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != len(COLUMNS) or cells[0] in ("Ticker", "") or set(cells[0]) <= {"-"}:
            continue
        rows.append(dict(zip(COLUMNS, cells)))
    return rows


def millions(s: str) -> float:
    return float(re.sub(r"[,$\s]", "", s)) * 1e6


ROWS = validation_rows(SPEC.read_text())


def test_table_parser():
    text = "## Validation set\n| Ticker | Period end | a | b | c | d | e |\n|---|---|---|---|---|---|---|\n" \
           "| AAPL | 2026-06-27 | 466,823 | 1 | 2 | 3 | 4 |\n|  |  |  |  |  |  |  |\n"
    rows = validation_rows(text)
    assert rows == [{"ticker": "AAPL", "period_end": "2026-06-27", "ltm_revenue": "466,823",
                     "ltm_ebitda": "1", "total_debt": "2", "cash_plus_sti": "3", "diluted_shares": "4"}]
    assert millions("466,823") == 466_823e6


@pytest.mark.live
@pytest.mark.skipif(os.getenv("RUN_LIVE") != "1", reason="set RUN_LIVE=1 to hit the real SEC API")
@pytest.mark.skipif(not ROWS, reason="validation table in SPEC.md not filled in yet")
@pytest.mark.parametrize("row", ROWS, ids=[r["ticker"] for r in ROWS])
def test_matches_hand_checked_values(row):
    client = SECClient()
    company = lookup(row["ticker"], client)
    meta = get_metadata(company.cik, client)
    end = date.fromisoformat(row["period_end"])
    no_price = Figure(name="share price", value=None, unit="USD/share", formula="n/a", reason="not needed")
    m = metrics.compute(get_series(company.cik, client, meta), end, no_price)
    engine = {
        "ltm_revenue": m["ltm_revenue"].value,
        "ltm_ebitda": m["ltm_ebitda"].value,
        "total_debt": m["total_debt"].value,
        "cash_plus_sti": (m["cash"].value or 0) + (m["short_term_investments"].value or 0),
        "diluted_shares": m["diluted_shares"].value,
    }
    errors = []
    for key, got in engine.items():
        if not row[key]:
            continue
        want = millions(row[key])
        if got is None or abs(got / want - 1) > TOLERANCE:
            shown = "n/a" if got is None else f"{got / 1e6:,.1f}m"
            errors.append(f"{key}: engine {shown} vs hand-checked {want / 1e6:,.1f}m")
    assert not errors, f"{row['ticker']}: " + "; ".join(errors)
