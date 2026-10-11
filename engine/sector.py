"""Sector screen: many companies side by side, no target (FD-12).

Pure functions over already-loaded CompanyRows (engine/report.py does the
fetching). The point is the first step of a pitch: line up a sector, see who is
cheap or expensive against what, then open one company as a full tearsheet with
the rest of the list as its peers.

FD-12: statistics are over every company in the screen that has a usable value
(FD-6/FD-7 NM rules unchanged). Relative value = company multiple / sector
median - 1. Distance from the 52-week high = price / 52-week high - 1.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.comps import CompanyRow, Stats, summarize
from engine.metrics import ratio
from engine.periods import Figure, missing

# Columns of the screen, in display order. All live in CompanyMetrics.figures except
# the two FD-12 additions, which sector.build adds to each row's figures.
SIZE = ("equity_value", "enterprise_value", "ltm_revenue")
OPERATING = ("revenue_growth_ltm", "ebitda_margin")
VALUATION = ("ev_revenue", "ev_ebitda", "pe")
OTHER = ("net_debt_ebitda", "price_vs_52w_high")
COLUMNS = SIZE + OPERATING + VALUATION + OTHER
RELATIVE = ("ev_revenue", "ev_ebitda", "pe")  # columns that get a premium/discount vs median

LABELS = {
    "equity_value": "Market cap", "enterprise_value": "EV", "ltm_revenue": "LTM revenue",
    "revenue_growth_ltm": "Revenue growth (LTM)", "ebitda_margin": "EBITDA margin (LTM)",
    "ev_revenue": "EV/Revenue", "ev_ebitda": "EV/EBITDA", "pe": "P/E",
    "net_debt_ebitda": "Net debt / EBITDA", "price_vs_52w_high": "vs 52-week high",
}
UNITS = {"equity_value": "USD", "enterprise_value": "USD", "ltm_revenue": "USD",
         "revenue_growth_ltm": "ratio", "ebitda_margin": "ratio", "ev_revenue": "x", "ev_ebitda": "x",
         "pe": "x", "net_debt_ebitda": "x", "price_vs_52w_high": "ratio"}

# Scatter charts a pitch team uses to argue "cheap for its growth / margins".
SCATTERS = (("revenue_growth_ltm", "ev_revenue"), ("ebitda_margin", "ev_ebitda"),
            ("revenue_growth_ltm", "ev_ebitda"))


@dataclass(frozen=True)
class Fit:
    """Least-squares line y = intercept + slope x over companies with both values."""

    x: str
    y: str
    slope: float | None
    intercept: float | None
    r2: float | None
    n: int
    tickers: tuple[str, ...]

    def predict(self, x: float) -> float | None:
        return None if self.slope is None else self.intercept + self.slope * x


@dataclass
class Sector:
    name: str
    rows: list[CompanyRow]  # every company asked for, including ones that failed to load
    stats: dict[str, Stats] = field(default_factory=dict)
    relative: dict[str, dict[str, Figure]] = field(default_factory=dict)  # ticker -> column -> premium
    notes: list[str] = field(default_factory=list)

    @property
    def loaded(self) -> list[CompanyRow]:
        return [r for r in self.rows if r.metrics is not None]

    def rank(self, column: str, descending: bool = True) -> list[tuple[str, float]]:
        vals = [(r.ticker, r.get(column).value) for r in self.loaded if r.get(column).ok]
        return sorted(vals, key=lambda kv: kv[1], reverse=descending)


def price_vs_high(row: CompanyRow) -> Figure:
    """FD-12: price / 52-week high - 1 (0% = at the high, -30% = 30% below it)."""
    price = row.get("price")
    high = row.high_52w or missing("52-week high", "USD/share", "no price history")
    f = ratio("price / 52-week high", price, high, "x", "share price / 52-week high")
    if not f.ok:
        return missing("vs 52-week high", "ratio", f.reason or "n/a", inputs=f.inputs)
    return Figure(name="vs 52-week high", value=f.value - 1, unit="ratio",
                  formula="share price / 52-week high - 1 (FD-12)", as_of=price.as_of, inputs=f.inputs)


def premium(value: Figure, median: float | None, label: str) -> Figure:
    """FD-12: company multiple / sector median - 1."""
    name = f"{label} vs sector median"
    if not value.ok:
        return missing(name, "ratio", f"{label} {'NM' if value.nm else 'n/a'}")
    if median is None or median <= 0:
        return missing(name, "ratio", f"no usable sector median {label}")
    return Figure(name=name, value=value.value / median - 1, unit="ratio", inputs=(value,),
                  formula=f"{label} {value.value:.2f}x / sector median {median:.2f}x - 1 (FD-12)")


def fit(rows: list[CompanyRow], x: str, y: str) -> Fit:
    """Ordinary least squares over usable (non-NM) pairs. Needs 3+ points."""
    pts = [(r.ticker, r.get(x).value, r.get(y).value) for r in rows
           if r.metrics is not None and r.get(x).ok and r.get(y).ok]
    tickers = tuple(t for t, _, _ in pts)
    n = len(pts)
    if n < 3:
        return Fit(x, y, None, None, None, n, tickers)
    xs = [p[1] for p in pts]
    ys = [p[2] for p in pts]
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((v - mx) ** 2 for v in xs)
    if sxx == 0:
        return Fit(x, y, None, None, None, n, tickers)
    sxy = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    slope = sxy / sxx
    intercept = my - slope * mx
    ss_tot = sum((b - my) ** 2 for b in ys)
    ss_res = sum((b - (intercept + slope * a)) ** 2 for a, b in zip(xs, ys))
    r2 = 1 - ss_res / ss_tot if ss_tot else None
    return Fit(x, y, slope, intercept, r2, n, tickers)


def build(name: str, rows: list[CompanyRow]) -> Sector:
    notes, kept, seen = [], [], set()
    for r in rows:
        if r.ticker in seen or (r.metrics is not None and r.name in seen):
            notes.append(f"{r.ticker} duplicates a company already in the list; counted once")
            continue
        seen.update({r.ticker, r.name})
        kept.append(r)
        if r.metrics is not None:
            r.metrics.figures["price_vs_52w_high"] = price_vs_high(r)
    s = Sector(name=name, rows=kept, notes=notes)
    for col in COLUMNS:
        s.stats[col] = summarize(col, s.loaded)
    for r in s.loaded:
        s.relative[r.ticker] = {c: premium(r.get(c), s.stats[c].median, LABELS[c]) for c in RELATIVE}
    for st in s.stats.values():
        notes.extend(n.replace("peer value", "value") for n in st.notes)
    for r in kept:
        if r.metrics is None:
            notes.append(f"{r.ticker}: left out, {r.error}")
    return s


# ---- Phase 4e: screening tools (FD-12, added 2026-10-10) -------------------------------------

WEAK_FIT_R2 = 0.2  # below this the line explains little; residuals are shown but not argued from


def percent_rank(values: list[float], x: float) -> float | None:
    """Share of the other values below x: Excel PERCENTRANK.INC (count below / (n - 1)).

    0% = lowest in the group, 100% = highest; ties share the lower rank. Same
    spreadsheet-reproducible spirit as FD-10 Q11. Needs 2+ values.
    """
    if len(values) < 2:
        return None
    return sum(1 for v in values if v < x) / (len(values) - 1)


def ranks(s: Sector, column: str) -> dict[str, Figure]:
    """Each company's percentile rank within the screen on one column (NM/n/a -> n/a)."""
    vals = [r.get(column).value for r in s.loaded if r.get(column).ok]
    out = {}
    for r in s.loaded:
        f = r.get(column)
        name = f"{LABELS[column]} percentile rank"
        if not f.ok:
            out[r.ticker] = missing(name, "ratio", f"{LABELS[column]} {'NM' if f.nm else 'n/a'}")
            continue
        pr = percent_rank(vals, f.value)
        out[r.ticker] = (missing(name, "ratio", "fewer than 2 usable values") if pr is None else
                         Figure(name=name, value=pr, unit="ratio", inputs=(f,),
                                formula=f"companies below {r.ticker} / ({len(vals)} usable - 1), "
                                        "Excel PERCENTRANK.INC (FD-12)"))
    return out


@dataclass(frozen=True)
class Residual:
    """How far a company sits from the fitted line (FD-12): above = richer, below = cheaper."""

    ticker: str
    actual: float
    fitted: float
    gap: float  # actual - fitted, in the y unit (turns of the multiple)
    gap_pct: float | None  # actual / fitted - 1; None when the fitted value isn't positive


def residuals(rows: list[CompanyRow], x: str, y: str) -> tuple[Fit, list[Residual]]:
    """Gap to the least-squares line for every company in the fit, cheapest (most negative) first.

    This is a screen, not a valuation: it says which multiples look low *given* how
    the market prices growth (or margins) across this group. With R² below 0.2 the
    line explains little and the gaps are mostly noise (WEAK_FIT_R2).
    """
    f = fit(rows, x, y)
    if f.slope is None:
        return f, []
    out = []
    for r in rows:
        if r.ticker not in f.tickers:
            continue
        a, pred = r.get(y).value, f.predict(r.get(x).value)
        out.append(Residual(r.ticker, a, pred, a - pred, a / pred - 1 if pred > 0 else None))
    out.sort(key=lambda z: z.gap)
    return f, out


def filter_tickers(s: Sector, bounds: dict[str, tuple[float | None, float | None]]) -> tuple[list[str], list[str]]:
    """(kept, dropped) tickers for min/max bounds per column, in the column's own unit
    (USD, ratio, x). A company with an NM or n/a value on a bounded column is dropped,
    because it can't be shown to pass; the reason is in its footnotes."""
    kept, dropped = [], []
    for r in s.loaded:
        ok = True
        for col, (lo, hi) in bounds.items():
            if lo is None and hi is None:
                continue
            f = r.get(col)
            if not f.ok or (lo is not None and f.value < lo) or (hi is not None and f.value > hi):
                ok = False
                break
        (kept if ok else dropped).append(r.ticker)
    return kept, dropped


def subset(s: Sector, tickers: list[str], name: str | None = None) -> Sector:
    """The same screen over fewer companies, statistics recomputed (no refetch)."""
    keep = set(tickers)
    return build(name or s.name, [r for r in s.loaded if r.ticker in keep])
