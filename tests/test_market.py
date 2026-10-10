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


def test_risk_free_reads_latest_ten_year():
    from engine.market import risk_free_from_csv
    csv_text = ('Date,"1 Mo","10 Yr","30 Yr"\n'
                "10/09/2026,4.13,5.24,5.60\n10/08/2026,4.14,5.22,5.60\n")
    f = risk_free_from_csv(csv_text)
    assert f.value == pytest.approx(0.0524) and str(f.as_of) == "2026-10-09" and "Treasury" in f.source


def test_beta_is_covariance_over_variance_and_drops_current_month():
    from datetime import date

    from engine.market import beta_from_prices
    idx = pd.date_range("2023-01-01", periods=31, freq="MS")
    market = pd.Series([100 * 1.01 ** i * (1.02 if i % 2 else 0.99) for i in range(31)], index=idx)
    stock = market ** 2 / 100  # roughly 2x the market's % moves
    # A wild final (partial) month that must be ignored:
    stock.iloc[-1] = stock.iloc[-2] * 5
    f = beta_from_prices("X", stock, market, today=date(2025, 7, 15))
    rets = pd.concat({"s": stock, "m": market}, axis=1).iloc[:-1].pct_change().dropna()
    assert f.value == pytest.approx(rets["s"].cov(rets["m"]) / rets["m"].var())
    assert 1.9 < f.value < 2.2 and "29 monthly returns" in f.formula


def test_beta_needs_two_years():
    from datetime import date

    from engine.market import beta_from_prices
    idx = pd.date_range("2025-01-01", periods=12, freq="MS")
    s = pd.Series(range(100, 112), index=idx, dtype=float)
    f = beta_from_prices("X", s, s, today=date(2026, 10, 1))
    assert f.value is None and "need 24" in f.reason
