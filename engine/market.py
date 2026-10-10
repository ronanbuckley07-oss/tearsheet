"""Share price via yfinance, isolated here so the source can be swapped.

yfinance is unofficial (it scrapes Yahoo Finance) and occasionally breaks.
Nothing outside this module imports it. Everything returns periods.Figure, so
a failed lookup is an n/a with a reason, never a guessed price.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from engine.periods import Figure, missing

SOURCE = "Yahoo Finance via yfinance"


@dataclass(frozen=True)
class Quote:
    price: Figure  # latest daily close, USD/share
    high_52w: Figure  # highest intraday high over the past year
    low_52w: Figure  # lowest intraday low over the past year


def get_quote(ticker: str) -> Quote:
    try:
        import yfinance as yf

        t = yf.Ticker(ticker)
        hist = t.history(period="1y", auto_adjust=False)
        currency = (t.fast_info or {}).get("currency")
    except Exception as exc:  # network, parsing, Yahoo changes
        return _all_missing(f"{SOURCE} lookup failed: {type(exc).__name__}: {exc}")
    return quote_from_history(ticker, hist, currency)


def quote_from_history(ticker: str, hist, currency: str | None) -> Quote:
    """Build a Quote from a yfinance daily history DataFrame (pure, testable)."""
    if hist is not None:
        # Yahoo sometimes returns a row for today with no prices yet.
        hist = hist.dropna(subset=["Close", "High", "Low"])
    if hist is None or len(hist) == 0:
        return _all_missing(f"{SOURCE} returned no price history for {ticker}")
    if currency and currency != "USD":
        return _all_missing(f"{ticker} trades in {currency}; v1 is USD only")
    last_day: date = hist.index[-1].date()
    first_day: date = hist.index[0].date()
    src = f"{SOURCE}, {ticker} daily history {first_day}..{last_day}"
    close = float(hist["Close"].iloc[-1])
    return Quote(
        price=Figure(name="share price", value=close, unit="USD/share",
                     formula=f"closing price on {last_day}", as_of=last_day, source=src),
        high_52w=Figure(name="52-week high", value=float(hist["High"].max()), unit="USD/share",
                        formula="highest intraday high in the past year", as_of=last_day, source=src),
        low_52w=Figure(name="52-week low", value=float(hist["Low"].min()), unit="USD/share",
                       formula="lowest intraday low in the past year", as_of=last_day, source=src),
    )


def _all_missing(reason: str) -> Quote:
    return Quote(
        price=missing("share price", "USD/share", reason),
        high_52w=missing("52-week high", "USD/share", reason),
        low_52w=missing("52-week low", "USD/share", reason),
    )
