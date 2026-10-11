"""Thesis support for a pitch, built only from computed figures (Phase 4e, FD-16).

A judge's first questions are "where does this company sit against its peers?",
"how much upside, on which method?" and "why should the peers' multiple apply?".
This module answers each from numbers the engine already produced:

- ``scorecard``: the target against the peer distribution on growth, margin,
  leverage and the multiples, with the target's percentile rank and a reading
  (FD-16: outside the peer interquartile range = notable; inside = in line).
- ``comparability``: warnings when the target's growth or margin sits outside
  the peers' range, i.e. when the peers' multiples may not transfer to it.
- ``valuation_summary``: each method's implied price range vs the current price,
  as upside/downside Figures, and a flag when the methods point opposite ways.

No LLM and no new finance inputs: every value is a Figure with a formula, and
anything that needs an NM or n/a input is itself n/a with the reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine import dcf as dcf_mod
from engine import learn, peers
from engine.comps import Comps, CompanyRow, Stats
from engine.periods import Figure, missing
from engine.sector import LABELS, percent_rank

# FD-16: which way is "better" for a long. Higher growth and margin are stronger
# fundamentals; lower multiples are cheaper; lower leverage is safer. None = context
# only (distance from the 52-week high can be read as value or as momentum).
DIRECTION = {
    "revenue_growth_ltm": "higher", "ebitda_margin": "higher", "net_debt_ebitda": "lower",
    "ev_ebitda": "lower", "ev_revenue": "lower", "pe": "lower",
}
SCORE_ROWS = ("revenue_growth_ltm", "ebitda_margin", "net_debt_ebitda", "ev_ebitda", "ev_revenue", "pe")
FUNDAMENTALS = ("revenue_growth_ltm", "ebitda_margin", "net_debt_ebitda")
MULTIPLES = ("ev_ebitda", "ev_revenue", "pe")


@dataclass(frozen=True)
class Score:
    column: str
    label: str
    target: Figure
    stats: Stats
    rank: Figure  # target's percentile rank among peers + target (PERCENTRANK.INC)
    position: str  # "above the 75th percentile" / "within the interquartile range" / ...
    reading: str  # "stronger" / "weaker" / "cheaper" / "richer" / "safer" / "more levered" / "in line" / "n/a"
    signal: str  # "long", "short", "neutral" or "n/a" (FD-16)


def _reading(column: str, side: int) -> tuple[str, str]:
    """side: +1 above the 75th percentile, -1 below the 25th, 0 inside."""
    if side == 0:
        return "in line", "neutral"
    good = (side > 0) == (DIRECTION[column] == "higher")
    if column in MULTIPLES:
        return ("cheaper" if good else "richer"), ("long" if good else "short")
    if column == "net_debt_ebitda":
        return ("less levered" if good else "more levered"), ("long" if good else "short")
    return ("stronger" if good else "weaker"), ("long" if good else "short")


def score(column: str, target: CompanyRow, peers: list[CompanyRow], stats: Stats) -> Score:
    label = LABELS[column]
    f = target.get(column)
    na_rank = missing(f"{label} percentile rank", "ratio", "")
    if not f.ok:
        why = f"target {label} {'NM' if f.nm else 'n/a'}"
        return Score(column, label, f, stats, missing(na_rank.name, "ratio", why), "n/a", "n/a", "n/a")
    if stats.n < 2 or stats.p25 is None:
        why = f"{stats.n} usable peer value(s)"
        return Score(column, label, f, stats, missing(na_rank.name, "ratio", why), "n/a", "n/a", "n/a")
    vals = [p.get(column).value for p in peers if p.get(column).ok] + [f.value]
    pr = percent_rank(vals, f.value)
    rank = Figure(name=na_rank.name, value=pr, unit="ratio", inputs=(f,),
                  formula=f"peers below the target / ({len(vals)} values incl. target - 1), "
                          "Excel PERCENTRANK.INC (FD-16)")
    side = 1 if f.value > stats.p75 else -1 if f.value < stats.p25 else 0
    position = {1: "above the peer 75th percentile", -1: "below the peer 25th percentile",
                0: "within the peer interquartile range"}[side]
    reading, signal = _reading(column, side)
    return Score(column, label, f, stats, rank, position, reading, signal)


@dataclass
class Scorecard:
    target: str
    rows: list[Score]
    warnings: list[str] = field(default_factory=list)

    def tally(self) -> dict[str, list[str]]:
        """Labels by signal, e.g. {"long": ["EV/EBITDA"], "short": ["Revenue growth (LTM)"], ...}."""
        out: dict[str, list[str]] = {"long": [], "short": [], "neutral": [], "n/a": []}
        for r in self.rows:
            out[r.signal].append(r.label)
        return out


def scorecard(c: Comps) -> Scorecard:
    t = c.target
    peers = [p for p in c.peers if p.metrics is not None]
    rows = [score(col, t, peers, c.stats[col]) for col in SCORE_ROWS if col in c.stats]
    return Scorecard(t.ticker, rows, comparability(t, c))


def comparability(t: CompanyRow, c: Comps) -> list[str]:
    """FD-16: the target's growth or margin outside every peer's (or the peer IQR), the
    case where applying the peers' multiples needs defending."""
    out = []
    for col in ("revenue_growth_ltm", "ebitda_margin"):
        f, st = t.get(col), c.stats.get(col)
        if not f.ok or st is None or st.n < 3 or st.p25 is None:
            continue
        vals = [p.get(col).value for p in c.peers if p.get(col).ok]
        lo, hi = min(vals), max(vals)
        word = {"revenue_growth_ltm": "revenue growth", "ebitda_margin": "EBITDA margin"}[col]
        if f.value < lo or f.value > hi:
            out.append(f"{t.ticker}'s {word} of {f.value:.1%} is outside every peer's ({lo:.1%} to {hi:.1%}). "
                       "The peers' multiples price a different business; expect to defend why they apply.")
        elif f.value < st.p25 or f.value > st.p75:
            out.append(f"{t.ticker}'s {word} of {f.value:.1%} is outside the peer interquartile range "
                       f"({st.p25:.1%} to {st.p75:.1%}), so the peer median multiple may over- or understate it.")
    return out


# ---- valuation summary -------------------------------------------------------------------------


@dataclass(frozen=True)
class MethodRange:
    method: str
    low: Figure
    mid: Figure  # peer median (comps), base case (DCF); n/a for the 52-week range
    high: Figure
    upside_low: Figure  # low / current price - 1
    upside_mid: Figure
    upside_high: Figure
    reason: str | None = None


@dataclass
class ValuationSummary:
    price: Figure
    methods: list[MethodRange]
    notes: list[str] = field(default_factory=list)


def upside(value: Figure, price: Figure, name: str) -> Figure:
    """value / current price - 1."""
    if not value.ok:
        return missing(name, "ratio", f"{value.name} {'NM' if value.nm else 'n/a'}"
                                      + (f" ({value.reason})" if value.reason else ""))
    if not price.ok or price.value <= 0:
        return missing(name, "ratio", f"share price n/a ({price.reason})")
    return Figure(name=name, value=value.value / price.value - 1, unit="ratio", inputs=(value, price),
                  formula=f"{value.name} ${value.value:,.2f} / current price ${price.value:,.2f} - 1 (FD-16)")


def _method(label: str, lo: Figure, mid: Figure, hi: Figure, price: Figure, reason: str | None = None) -> MethodRange:
    return MethodRange(label, lo, mid, hi, upside(lo, price, f"{label}: low vs current"),
                       upside(mid, price, f"{label}: mid vs current"),
                       upside(hi, price, f"{label}: high vs current"), reason)


_COMP_NAMES = {"ev_ebitda": "Comps: EV/EBITDA (peer 25th-75th)", "ev_revenue": "Comps: EV/Revenue (peer 25th-75th)"}


def valuation_summary(c: Comps, dcf_result=None, dcf_bar: dict | None = None) -> ValuationSummary:
    """Every method's implied price vs the current price (FD-8 comps, FD-11 DCF, 52-week range)."""
    t = c.target
    price = t.get("price")
    methods = []
    for key, r in c.implied.items():
        lo, mid, hi = r.share_price
        methods.append(_method(_COMP_NAMES.get(key, key), lo, mid, hi, price, r.reason))
    if dcf_result is not None and dcf_bar is not None:
        bar_lo = _bar_fig("DCF low (WACC +1%, g -0.5%)", dcf_bar.get("low"), dcf_bar.get("reason"))
        bar_hi = _bar_fig("DCF high (WACC -1%, g +0.5%)", dcf_bar.get("high"), dcf_bar.get("reason"))
        methods.append(_method("DCF (WACC ±1%, g ±0.5%)", bar_lo, dcf_result.share_price, bar_hi, price,
                               dcf_result.reason))
    if t.low_52w is not None and t.high_52w is not None:
        methods.append(_method("52-week trading range", t.low_52w, missing("52-week midpoint", "USD/share",
                                                                             "not a valuation; range only"),
                               t.high_52w, price))
    out = ValuationSummary(price, methods)
    # FD-16: flag methods whose midpoints sit on opposite sides of the price; a judge will ask which to trust.
    valued = [m for m in methods if m.upside_mid.ok]
    ups = [m.method for m in valued if m.upside_mid.value > 0]
    downs = [m.method for m in valued if m.upside_mid.value < 0]
    if ups and downs:
        out.notes.append("The methods disagree: " + ", ".join(ups) + " above the current price; "
                         + ", ".join(downs) + " below it. Be ready to say which you trust and why "
                         "(peer set, growth gap, DCF assumptions).")
    return out


def _bar_fig(name: str, v: float | None, reason: str | None) -> Figure:
    if v is None:
        return missing(name, "USD/share", reason or "n/a")
    return Figure(name=name, value=v, unit="USD/share", formula="corner of the DCF sensitivity grid (FD-11)")


# ---- everything a pitch needs, in one call -----------------------------------------------------


@dataclass
class PitchExtras:
    """Phase 4e thesis support for the exports (FD-9 size check, FD-14 tornado, FD-16)."""

    scorecard: Scorecard | None = None
    valuation: ValuationSummary | None = None
    drivers: list | None = None  # list[learn.Bar]: the tearsheet's "what moves the value" tornado (FD-14)
    size_fits: list | None = None  # list[peers.SizeFit]


def build_extras(rep, assumptions: dict[str, Figure] | None = None, mid_year: bool = False,
                 steady_state: bool = True) -> PitchExtras:
    """Scorecard, valuation summary, DCF tornado and the peer size check for a Report.

    ``assumptions`` are the DCF assumptions on screen (the user's edits); without
    them the DCF parts are left out rather than run on defaults the user never saw.
    """
    c, m, base = rep.comps, rep.target.metrics, rep.dcf_base
    if m is None:
        return PitchExtras()
    res = bar = drivers = None
    if assumptions is not None and base is not None:
        res = dcf_mod.run(assumptions, m, base, mid_year, steady_state=steady_state)
        if not res.reason:
            bar = dcf_mod.football_bar(assumptions, m, base, mid_year, steady_state=steady_state)
            # The same tornado the tearsheet draws (FD-14 steps), so the deck and the page agree.
            drivers = learn.tornado(learn.DcfContext(res, assumptions, assumptions, m, base, mid_year, steady_state))
    return PitchExtras(
        scorecard=scorecard(c) if c.peers else None,
        valuation=valuation_summary(c, res, bar),
        drivers=drivers,
        size_fits=peers.size_check(rep.target, [p for p in c.peers if p.metrics is not None]) if c.peers else None,
    )
