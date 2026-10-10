import os

import pandas as pd
import pytest

from engine.market import get_quote, quote_from_history


def history():
    idx = pd.to_datetime(["2025-10-10", "2026-03-02", "2026-10-09"]).tz_localize("America/New_York")
    return pd.DataFrame({"High": [210.0, 350.5, 340.0], "Low": [200.0, 300.0, 180.25],
                         "Close": [205.0, 320.0, 336.64]}, index=idx)


def test_quote_uses_last_close_and_52w_extremes():
    q = quote_from_history("AAPL", history(), "USD")
    assert q.price.value == 336.64 and str(q.price.as_of) == "2026-10-09"
    assert q.high_52w.value == 350.5 and q.low_52w.value == 180.25
    assert "Yahoo Finance" in q.price.source


def test_empty_history_is_na():
    q = quote_from_history("ZZZZ", history().iloc[0:0], "USD")
    assert q.price.value is None and "no price history" in q.price.reason


def test_non_usd_is_na():
    q = quote_from_history("SHOP", history(), "CAD")
    assert q.price.value is None and "USD only" in q.price.reason


@pytest.mark.live
@pytest.mark.skipif(os.getenv("RUN_LIVE") != "1", reason="set RUN_LIVE=1 to hit Yahoo Finance")
def test_live_quote():
    q = get_quote("MSFT")
    assert q.price.value and q.low_52w.value <= q.price.value <= q.high_52w.value


def test_trailing_nan_row_ignored():
    h = history()
    h.loc[pd.Timestamp("2026-10-10", tz="America/New_York")] = [float("nan")] * 3
    q = quote_from_history("AAPL", h, "USD")
    assert q.price.value == 336.64 and str(q.price.as_of) == "2026-10-09"
