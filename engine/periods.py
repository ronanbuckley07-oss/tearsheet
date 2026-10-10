"""Fiscal years, LTM, and balance-sheet-date values from xbrl.py series.

Every result is a ``Figure``: a value (or None with a reason), the formula
used, and the signed XBRL facts it was built from, so the UI can show exactly
which filings were combined (CLAUDE.md rule 2).

LTM (SPEC.md, FD-4):
    If the latest filing is a 10-K, LTM is that fiscal year.
    Otherwise LTM = latest fiscal year + current YTD - prior-year same YTD.
    Example: Apple at the June 2026 10-Q (nine months into FY2026):
        FY2025 (Sep 2024 - Sep 2025)
      + 9M FY2026 (Sep 2025 - Jun 2026)
      - 9M FY2025 (Sep 2024 - Jun 2025)
      = the twelve months Jul 2025 - Jun 2026.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from engine.xbrl import Fact, MetricSeries, PeriodType

YTD_TYPES = (PeriodType.QUARTER, PeriodType.YTD_6M, PeriodType.YTD_9M)


@dataclass(frozen=True)
class Figure:
    """One number in the report and how it was produced.

    ``value`` is None when the figure is n/a or NM; ``reason`` then says why.
    ``facts`` are the XBRL leaves as (sign, Fact): +1 added, -1 subtracted.
    ``inputs`` are the Figures this one was computed from, for drill-down.
    ``source`` describes a non-XBRL leaf (e.g. the share price).
    """

    name: str
    value: float | None
    unit: str  # "USD", "shares", "USD/share", "x", "ratio"
    formula: str
    as_of: date | None = None
    start: date | None = None
    facts: tuple[tuple[int, Fact], ...] = ()
    inputs: tuple["Figure", ...] = ()
    notes: tuple[str, ...] = ()
    reason: str | None = None
    nm: bool = False  # True when the value exists but is not meaningful (FD-6)
    raw_value: float | None = None  # the computed number behind an NM, for footnotes
    source: str | None = None

    @property
    def ok(self) -> bool:
        return self.value is not None

    def all_notes(self) -> list[str]:
        """This figure's notes plus every input's, without duplicates."""
        out: list[str] = []
        for n in self.notes:
            if n not in out:
                out.append(n)
        for i in self.inputs:
            for n in i.all_notes():
                if n not in out:
                    out.append(n)
        return out


def missing(name: str, unit: str, reason: str, as_of: date | None = None, **kw) -> Figure:
    return Figure(name=name, value=None, unit=unit, formula="n/a", as_of=as_of, reason=reason, **kw)


def _fact_notes(facts: list[tuple[int, Fact]]) -> list[str]:
    notes = []
    for _, f in facts:
        period = f"{f.start}..{f.end}" if f.start else f"{f.end}"
        if f.note:
            notes.append(f"{f.metric} {period}: {f.note}")
        if f.tag == "ProfitLoss":
            notes.append(f"{f.metric} {period}: ProfitLoss used (NetIncomeLoss not reported); "
                         "includes any noncontrolling interests' share")
        if f.restated:
            notes.append(f"{f.metric} {period}: restated; latest filed value used ({f.source.accession})")
    tags = {f.tag for _, f in facts}
    if len(tags) > 1:
        notes.append(
            f"{facts[0][1].metric}: combines periods reported under different tags "
            f"({', '.join(sorted(tags))}); definitions may differ slightly"
        )
    return notes


# ---- fiscal years -------------------------------------------------------------


def fiscal_year_facts(series: MetricSeries) -> list[Fact]:
    """Full-year facts from 10-K filings, most recent first."""
    facts = [
        f for f in series.of_type(PeriodType.ANNUAL)
        if all(s.form.startswith("10-K") for s in f.sources)
    ]
    return sorted(facts, key=lambda f: f.end, reverse=True)


def fiscal_year(series: MetricSeries, end: date) -> Figure:
    f = next((f for f in fiscal_year_facts(series) if f.end == end), None)
    if f is None:
        return missing(series.metric, _unit(series), f"no 10-K value for the fiscal year ending {end}", as_of=end)
    return Figure(
        name=series.metric,
        value=f.value,
        unit=f.unit,
        formula=f"fiscal year {f.start} to {f.end}",
        as_of=f.end,
        start=f.start,
        facts=((1, f),),
        notes=tuple(_fact_notes([(1, f)])),
    )


def latest_fiscal_year_ends(series: MetricSeries, on_or_before: date, n: int = 2) -> list[date]:
    ends: list[date] = []
    for f in fiscal_year_facts(series):
        if f.end <= on_or_before and f.end not in ends:
            ends.append(f.end)
    return ends[:n]


# ---- LTM ------------------------------------------------------------------------


def ltm(series: MetricSeries, end: date) -> Figure:
    """Last twelve months ending ``end`` (a 10-K or 10-Q period end)."""
    unit = _unit(series)
    name = series.metric

    fys = [f for f in fiscal_year_facts(series) if f.end <= end]
    if fys and fys[0].end == end:
        f = fys[0]
        return Figure(
            name=name, value=f.value, unit=f.unit,
            formula=f"LTM = fiscal year {f.start} to {f.end} (latest filing is the 10-K)",
            as_of=end, start=f.start, facts=((1, f),), notes=tuple(_fact_notes([(1, f)])),
        )
    if not fys:
        return missing(name, unit, f"no fiscal-year value ending on or before {end}", as_of=end)

    fy = fys[0]
    ytd = _find(series, start=fy.end + timedelta(days=1), end=end, types=YTD_TYPES)
    if ytd is None:
        return missing(
            name, unit,
            f"no year-to-date value from {fy.end + timedelta(days=1)} to {end}; "
            "can't build LTM without it",
            as_of=end,
        )
    prior = _prior_year_ytd(series, fy, ytd)
    if prior is None:
        return missing(
            name, unit,
            f"no prior-year {ytd.period_type.value} value starting {fy.start}; can't build LTM",
            as_of=end,
        )
    parts = [(1, fy), (1, ytd), (-1, prior)]
    return Figure(
        name=name,
        value=fy.value + ytd.value - prior.value,
        unit=unit,
        formula=(
            f"LTM = FY {fy.start}..{fy.end} + YTD {ytd.start}..{ytd.end} "
            f"- prior YTD {prior.start}..{prior.end}"
        ),
        as_of=end,
        start=prior.end + timedelta(days=1),
        facts=tuple(parts),
        notes=tuple(_fact_notes(parts)),
    )


def prior_ltm_end(series: MetricSeries, end: date) -> date | None:
    """The period end one year before ``end``, for LTM-over-LTM growth."""
    fys = [f for f in fiscal_year_facts(series) if f.end <= end]
    if not fys:
        return None
    if fys[0].end == end:
        return fys[1].end if len(fys) > 1 else None
    ytd = _find(series, start=fys[0].end + timedelta(days=1), end=end, types=YTD_TYPES)
    prior = _prior_year_ytd(series, fys[0], ytd) if ytd else None
    return prior.end if prior else None


def _prior_year_ytd(series: MetricSeries, fy: Fact, ytd: Fact) -> Fact | None:
    candidates = [
        f for f in series.facts
        if f.start == fy.start and f.period_type == ytd.period_type and f.end < fy.end
    ]
    if not candidates:
        return None
    target = ytd.end - timedelta(days=364)
    return min(candidates, key=lambda f: abs((f.end - target).days))


def _find(series: MetricSeries, start: date, end: date, types) -> Fact | None:
    return next(
        (f for f in series.facts if f.start == start and f.end == end and f.period_type in types),
        None,
    )


# ---- balance sheet -------------------------------------------------------------


def balance_at(series: MetricSeries, end: date, latest_fy_end: date | None) -> Figure:
    """Instant value at ``end``.

    FD-10 Q3: if the item isn't reported at ``end`` but was in the latest
    10-K (some items are disclosed annually only, e.g. Apple's finance leases),
    use the 10-K value and flag its date. Anything older is n/a with a reason.
    """
    unit = _unit(series)
    exact = series.get(None, end)
    if exact is not None:
        return Figure(
            name=series.metric, value=exact.value, unit=exact.unit,
            formula=f"balance at {end}", as_of=end, facts=((1, exact),),
            notes=tuple(_fact_notes([(1, exact)])),
        )
    earlier = [f for f in series.facts if f.end < end]
    if not earlier:
        return missing(series.metric, unit, f"not reported at {end}", as_of=end)
    last = earlier[-1]
    if latest_fy_end is not None and last.end == latest_fy_end and last.source.form.startswith("10-K"):
        return Figure(
            name=series.metric, value=last.value, unit=last.unit,
            formula=f"balance at {last.end} (latest 10-K; not reported at {end})",
            as_of=last.end, facts=((1, last),),
            notes=(f"{series.metric}: not in the {end} filing; using the {last.end} 10-K value (FD-10 Q3)",)
            + tuple(_fact_notes([(1, last)])),
        )
    return missing(series.metric, unit, f"not reported at {end} (last reported {last.end})", as_of=end)


def _unit(series: MetricSeries) -> str:
    return series.facts[0].unit if series.facts else "USD"
