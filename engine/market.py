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


# ---- DCF market inputs (FD-11) ---------------------------------------------------------

TREASURY_URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
                "daily-treasury-rates.csv/{year}/all?type=daily_treasury_yield_curve"
                "&field_tdr_date_value={year}&page&_format=csv")
TREASURY_SOURCE = "U.S. Treasury daily par yield curve rates (home.treasury.gov)"
BETA_INDEX = "^GSPC"  # S&P 500
BETA_MONTHS = 60
MIN_BETA_MONTHS = 24


def get_risk_free(today: date | None = None) -> Figure:
    """Latest 10-year Treasury par yield. Falls back to last year's file in early January."""
    import requests

    today = today or date.today()
    for year in (today.year, today.year - 1):
        try:
            resp = requests.get(TREASURY_URL.format(year=year), timeout=40,
                                headers={"User-Agent": "Mozilla/5.0 (Tearsheet)"})
            resp.raise_for_status()
        except Exception as exc:
            return missing("risk-free rate", "ratio", f"Treasury yield download failed: {type(exc).__name__}")
        f = risk_free_from_csv(resp.text, TREASURY_URL.format(year=year))
        if f.ok:
            return f
    return f


def risk_free_from_csv(text: str, url: str = "") -> Figure:
    """Parse Treasury's yield-curve CSV (newest row first) into the 10-year yield (pure, testable)."""
    import csv
    import io
    from datetime import datetime

    rows = list(csv.DictReader(io.StringIO(text)))
    for r in rows:
        v = (r.get("10 Yr") or "").strip()
        if not v:
            continue
        day = datetime.strptime(r["Date"], "%m/%d/%Y").date()
        return Figure(name="risk-free rate (10-year Treasury)", value=float(v) / 100, unit="ratio",
                      formula=f"10-year Treasury par yield on {day}", as_of=day,
                      source=f"{TREASURY_SOURCE}, {url}" if url else TREASURY_SOURCE)
    return missing("risk-free rate", "ratio", "no 10-year yield in the Treasury file")


def get_beta(ticker: str, today: date | None = None) -> Figure:
    try:
        import yfinance as yf

        stock = yf.Ticker(ticker).history(period="6y", interval="1mo", auto_adjust=True)["Close"]
        index = yf.Ticker(BETA_INDEX).history(period="6y", interval="1mo", auto_adjust=True)["Close"]
    except Exception as exc:
        return missing("beta", "x", f"{SOURCE} lookup failed: {type(exc).__name__}: {exc}")
    return beta_from_prices(ticker, stock, index, today or date.today())


def beta_from_prices(ticker: str, stock, index, today: date) -> Figure:
    """Raw (unadjusted) beta: slope of the stock's monthly returns on the S&P 500's.

    beta = covariance(stock, index) / variance(index), over the last 60 complete
    months. The current month is dropped because its "close" is just today's price.
    Prices are dividend-adjusted (auto_adjust), so returns include dividends.
    """
    import pandas as pd

    df = pd.concat({"s": stock, "m": index}, axis=1).dropna()
    df.index = [pd.Timestamp(i).date() for i in df.index]
    df = df[[not (d.year == today.year and d.month == today.month) for d in df.index]]
    df = df.iloc[-(BETA_MONTHS + 1):]
    rets = df.pct_change().dropna()
    n = len(rets)
    if n < MIN_BETA_MONTHS:
        return missing("beta", "x", f"only {n} months of {ticker} price history; need {MIN_BETA_MONTHS}")
    beta = rets["s"].cov(rets["m"]) / rets["m"].var()
    first, last = rets.index[0], rets.index[-1]
    return Figure(
        name="beta", value=float(beta), unit="x",
        formula=f"raw beta of {n} monthly returns vs the S&P 500, {first:%b %Y} to {last:%b %Y} (FD-11)",
        as_of=last, source=f"{SOURCE}, monthly adjusted closes of {ticker} and {BETA_INDEX}",
    )
