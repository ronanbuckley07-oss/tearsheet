"""Peer table, summary statistics, implied valuation range.

Pure functions over already-computed CompanyMetrics (engine/report.py does the
fetching). Every output is a periods.Figure or built from them, so the UI can
show how each number was produced.

FD-7: stats over non-NM peer values only; the median is the headline.
FD-8: target LTM metric x peer 25th-75th percentile multiple = implied EV,
      then the FD-2 bridge in reverse to equity value, / FD-3 shares = price.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean, median

from engine.metrics import CompanyMetrics, combine
from engine.periods import Figure, missing

# FD-5: valuation multiples, then the context columns that make them readable.
MULTIPLES = ("ev_revenue", "ev_ebitda", "pe")
CONTEXT = ("revenue_growth_ltm", "ebitda_margin", "net_debt_ebitda")
# FD-8: which multiples drive the implied valuation, and the target metric each applies to.
VALUATION_BASES = {"ev_ebitda": "ltm_ebitda", "ev_revenue": "ltm_revenue"}
FEW_PEERS = 4  # FD-9 aims for 6-12; below this the quartiles rest on very few points


@dataclass
class CompanyRow:
    """One line in the comps table. ``metrics`` is None when the company couldn't load."""

    ticker: str
    name: str
    metrics: CompanyMetrics | None
    high_52w: Figure | None = None
    low_52w: Figure | None = None
    error: str | None = None  # why the whole row is unusable (not found, foreign filer...)

    def get(self, key: str) -> Figure:
        if self.metrics is None:
            return missing(key, "x", self.error or "no data")
        return self.metrics.figures[key]


@dataclass(frozen=True)
class Stats:
    """FD-7 summary statistics for one column over the peers."""

    column: str
    n: int
    median: float | None
    mean: float | None
    p25: float | None
    p75: float | None
    included: tuple[str, ...]  # tickers used
    excluded: tuple[tuple[str, str], ...]  # (ticker, reason): NM or n/a
    notes: tuple[str, ...] = ()


@dataclass
class ImpliedRange:
    """FD-8 implied valuation from one multiple."""

    multiple: str
    target_metric: Figure
    low_multiple: float | None  # peer 25th percentile
    mid_multiple: float | None  # peer median (shown, not a bar end)
    high_multiple: float | None  # peer 75th percentile
    enterprise_value: tuple[Figure, Figure, Figure]  # low, mid, high
    equity_value: tuple[Figure, Figure, Figure]
    share_price: tuple[Figure, Figure, Figure]
    reason: str | None = None  # why the whole range is n/a


@dataclass
class Comps:
    target: CompanyRow
    peers: list[CompanyRow]
    stats: dict[str, Stats] = field(default_factory=dict)
    implied: dict[str, ImpliedRange] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def football_field(self) -> list[dict]:
        """Bars for the Phase 4 chart: implied price ranges, 52-week range, current price."""
        bars = []
        for key, r in self.implied.items():
            lo, _, hi = r.share_price
            bars.append({"label": f"{_LABEL[key]} (25th-75th pct)", "low": lo.value, "high": hi.value,
                         "reason": r.reason or lo.reason or hi.reason})
        t = self.target
        bars.append({"label": "52-week range",
                     "low": t.low_52w.value if t.low_52w else None,
                     "high": t.high_52w.value if t.high_52w else None,
                     "reason": None if t.low_52w and t.low_52w.ok else "52-week range n/a"})
        price = t.get("price")
        bars.append({"label": "Current price", "low": price.value, "high": price.value, "reason": price.reason})
        return bars


_LABEL = {"ev_revenue": "EV/Revenue", "ev_ebitda": "EV/EBITDA", "pe": "P/E",
          "revenue_growth_ltm": "Revenue growth (LTM)", "ebitda_margin": "EBITDA margin",
          "net_debt_ebitda": "Net debt / EBITDA"}


# ---- statistics (FD-7) ----------------------------------------------------------------


def percentile(values: list[float], q: float) -> float:
    """Linear interpolation between closest ranks, same as Excel PERCENTILE.INC
    (and numpy's default), so the owner can reproduce it in a spreadsheet.
    FD-10 Q11."""
    xs = sorted(values)
    if not xs:
        raise ValueError("no values")
    pos = (len(xs) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def summarize(column: str, peers: list[CompanyRow]) -> Stats:
    included, values, excluded = [], [], []
    for p in peers:
        f = p.get(column)
        if f.ok:
            included.append(p.ticker)
            values.append(f.value)
        else:
            excluded.append((p.ticker, ("NM: " if f.nm else "n/a: ") + (f.reason or "")))
    notes = []
    if values and len(values) < FEW_PEERS:
        notes.append(f"{_LABEL.get(column, column)}: only {len(values)} usable peer value(s); "
                     "quartiles rest on very few points (FD-9 aims for 6-12 peers)")
    if not values:
        return Stats(column, 0, None, None, None, None, (), tuple(excluded),
                     (f"{_LABEL.get(column, column)}: no usable peer values",))
    return Stats(
        column=column, n=len(values), median=median(values), mean=mean(values),
        p25=percentile(values, 0.25), p75=percentile(values, 0.75),
        included=tuple(included), excluded=tuple(excluded), notes=tuple(notes),
    )


# ---- implied valuation (FD-8) -------------------------------------------------------------


def implied_range(key: str, target: CompanyMetrics, stats: Stats) -> ImpliedRange:
    metric = target.figures[VALUATION_BASES[key]]
    label = _LABEL[key]

    def na(reason: str) -> ImpliedRange:
        blank = tuple(missing(f"implied {n} ({label})", u, reason) for n, u in
                      (("EV", "USD"), ("EV", "USD"), ("EV", "USD")))
        eq = tuple(missing(f"implied equity value ({label})", "USD", reason) for _ in range(3))
        px = tuple(missing(f"implied share price ({label})", "USD/share", reason) for _ in range(3))
        return ImpliedRange(key, metric, stats.p25, stats.median, stats.p75, blank, eq, px, reason=reason)

    if stats.n == 0:
        return na(f"no usable peer {label} multiples")
    if not metric.ok:
        return na(f"target {metric.name} n/a ({metric.reason})")
    if metric.value <= 0:
        # FD-6 logic applied in reverse: a multiple of a negative metric is not a valuation.
        return na(f"target {metric.name} is not positive; {label} can't value it")

    evs, eqs, pxs = [], [], []
    for point, mult in (("25th pct", stats.p25), ("median", stats.median), ("75th pct", stats.p75)):
        ev = Figure(
            name=f"implied EV ({label}, {point})", value=mult * metric.value, unit="USD",
            formula=f"peer {point} {label} {mult:.2f}x x target {metric.name}",
            as_of=metric.as_of, inputs=(metric,),
        )
        eq = equity_from_ev(ev, target, f"implied equity value ({label}, {point})")
        px = price_from_equity(eq, target, f"implied share price ({label}, {point})")
        evs.append(ev), eqs.append(eq), pxs.append(px)
    return ImpliedRange(key, metric, stats.p25, stats.median, stats.p75, tuple(evs), tuple(eqs), tuple(pxs))


def equity_from_ev(ev: Figure, t: CompanyMetrics, name: str) -> Figure:
    """FD-8: the FD-2 bridge in reverse.

    Equity value = EV - total debt - preferred - noncontrolling interest
                   + cash + short-term investments
    """
    F = t.figures
    return combine(
        name,
        [(1, ev), (-1, F["total_debt"]), (-1, F["preferred_stock"]),
         (-1, F["noncontrolling_interest"]), (1, F["cash"]), (1, F["short_term_investments"])],
        "USD",
        "implied EV - total debt - preferred - noncontrolling interest + cash + short-term investments (FD-8)",
        as_of=t.ltm_end,
    )


def price_from_equity(eq: Figure, t: CompanyMetrics, name: str) -> Figure:
    """FD-8: equity value / FD-3 cover-page shares."""
    shares = t.figures["shares_outstanding"]
    inputs = (eq, shares)
    for f in inputs:
        if not f.ok:
            return missing(name, "USD/share", f"{f.name} n/a ({f.reason})", inputs=inputs)
    if eq.value <= 0:
        return Figure(name=name, value=None, unit="USD/share", formula="implied equity / shares (FD-8)",
                      inputs=inputs, nm=True, raw_value=eq.value / shares.value,
                      reason="implied equity value is negative (debt exceeds implied EV)")
    return Figure(name=name, value=eq.value / shares.value, unit="USD/share",
                  formula="implied equity value / cover-page shares outstanding (FD-8, FD-3)",
                  inputs=inputs)


# ---- the whole table ---------------------------------------------------------------------


def build(target: CompanyRow, peers: list[CompanyRow]) -> Comps:
    notes = []
    kept = []
    seen = set()
    for p in peers:
        if p.ticker == target.ticker:
            notes.append(f"{p.ticker} is the target; left out of its own peer statistics")
            continue
        if p.ticker in seen or (p.metrics is not None and p.name in seen):
            notes.append(f"{p.ticker} duplicates a company already in the list; counted once")
            continue
        seen.update({p.ticker, p.name})
        kept.append(p)
    c = Comps(target=target, peers=kept, notes=notes)
    for col in MULTIPLES + CONTEXT:
        c.stats[col] = summarize(col, kept)
    if target.metrics is not None:
        for key in VALUATION_BASES:
            c.implied[key] = implied_range(key, target.metrics, c.stats[key])
    else:
        notes.append(f"Target {target.ticker} couldn't load ({target.error}); no implied valuation")
    for s in c.stats.values():
        notes.extend(s.notes)
    return c
