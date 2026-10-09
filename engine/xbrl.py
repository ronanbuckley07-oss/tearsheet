"""Turn the SEC companyfacts JSON into clean, sourced time series per metric.

companyfacts (https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json)
lists every XBRL fact a company has filed, grouped by taxonomy -> tag -> unit.
Each row looks like:

    {"start": "2023-10-01", "end": "2024-09-28", "val": 391035000000,
     "accn": "0000320193-24-000123", "fy": 2024, "fp": "FY",
     "form": "10-K", "filed": "2024-11-01", "frame": "CY2024"}

The same number shows up many times: a 10-K repeats the prior two years as
comparatives, and each 10-Q repeats last year's quarter. This module:

1. Keeps only 10-K / 10-Q facts (and their amendments), in the expected unit.
2. Dedupes by (tag, start, end), keeping the most recently filed value so
   restatements win, and records the accession number of the value used.
3. Resolves each metric's tag fallback chain per period, not per company:
   for every period, the first tag in the chain that has a value is used.
   (Companies switch tags over time, e.g. revenue around ASC 606 in 2018.)
4. Labels each period by length: annual, quarter, 6- or 9-month YTD, instant.

No finance math happens here (no LTM, no totals, no EV). That is periods.py
and metrics.py in Phase 2.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from engine.sec_client import SECClient
from engine.tickers import cik10

COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"

# Amendments are included so a restated value (filed later) can win the dedupe.
# 10-KT (transition-period reports) and 8-K/S-1 facts are excluded.
ALLOWED_FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A"}


class PeriodType(str, Enum):
    INSTANT = "instant"
    QUARTER = "quarter"
    YTD_6M = "ytd_6m"
    YTD_9M = "ytd_9m"
    ANNUAL = "annual"
    OTHER = "other"


# Day-count windows. Many companies use 52/53-week years, so a "year" is 364
# or 371 days and a quarter is 91 or 98 days; the windows allow for that.
_PERIOD_WINDOWS = [
    (PeriodType.QUARTER, 80, 100),
    (PeriodType.YTD_6M, 172, 192),
    (PeriodType.YTD_9M, 262, 285),
    (PeriodType.ANNUAL, 350, 380),
]


def classify_period(start: date | None, end: date) -> PeriodType:
    if start is None:
        return PeriodType.INSTANT
    days = (end - start).days + 1
    for ptype, lo, hi in _PERIOD_WINDOWS:
        if lo <= days <= hi:
            return ptype
    return PeriodType.OTHER


@dataclass(frozen=True)
class Source:
    """Where one reported value came from (CLAUDE.md rule 2)."""

    taxonomy: str
    tag: str
    form: str
    accession: str
    filed: date
    start: date | None
    end: date
    fy: int | None
    fp: str | None

    def filing_url(self, cik: int) -> str:
        return (
            f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
            f"{self.accession.replace('-', '')}/{self.accession}-index.htm"
        )


@dataclass(frozen=True)
class Fact:
    metric: str
    value: float
    unit: str
    start: date | None
    end: date
    period_type: PeriodType
    sources: tuple[Source, ...]  # one, or several when the value is a sum (e.g. D&A, share classes)
    restated: bool = False  # True if an earlier filing reported a different value for this period
    note: str | None = None

    @property
    def source(self) -> Source:
        return self.sources[0]

    @property
    def tag(self) -> str:
        return "+".join(s.tag for s in self.sources) if len(self.sources) > 1 else self.source.tag

    @property
    def days(self) -> int | None:
        return None if self.start is None else (self.end - self.start).days + 1


@dataclass
class MetricSeries:
    metric: str
    facts: list[Fact] = field(default_factory=list)  # sorted by (end, start)
    notes: list[str] = field(default_factory=list)  # data problems worth showing the owner

    def of_type(self, ptype: PeriodType) -> list[Fact]:
        return [f for f in self.facts if f.period_type == ptype]

    def latest(self, ptype: PeriodType | None = None) -> Fact | None:
        facts = self.facts if ptype is None else self.of_type(ptype)
        return facts[-1] if facts else None

    def get(self, start: date | None, end: date) -> Fact | None:
        return next((f for f in self.facts if f.start == start and f.end == end), None)

    def __bool__(self) -> bool:
        return bool(self.facts)


@dataclass(frozen=True)
class MetricDef:
    name: str
    tags: tuple[str, ...]  # fallback chain, in priority order
    unit: str = "USD"
    instant: bool = False
    taxonomy: str = "us-gaap"
    # Used only for periods where no tag in the chain has a value. Every tag
    # must be present for that period; a partial sum is not used.
    composite: tuple[str, ...] = ()
    sum_share_classes: bool = False


# Starting chains from SPEC.md. Debt components are kept as separate series on
# purpose: totalling them (and avoiding double counting LongTermDebt with its
# current portion) is a Phase 2 decision under FD-2, and the owner should see
# each component.
METRICS: dict[str, MetricDef] = {
    m.name: m
    for m in [
        # Income statement / cash flow (durations)
        MetricDef(
            "revenue",
            (
                "RevenueFromContractWithCustomerExcludingAssessedTax",
                "Revenues",
                "SalesRevenueNet",
                "RevenueFromContractWithCustomerIncludingAssessedTax",
            ),
        ),
        MetricDef("operating_income", ("OperatingIncomeLoss",)),
        MetricDef(
            "d_and_a",
            (
                "DepreciationDepletionAndAmortization",
                "DepreciationAndAmortization",
                "DepreciationAmortizationAndAccretionNet",
            ),
            composite=("Depreciation", "AmortizationOfIntangibleAssets"),
        ),
        MetricDef("net_income", ("NetIncomeLoss",)),
        MetricDef("operating_cash_flow", ("NetCashProvidedByUsedInOperatingActivities",)),
        MetricDef("capex", ("PaymentsToAcquirePropertyPlantAndEquipment",)),
        MetricDef("sbc", ("ShareBasedCompensation",)),
        MetricDef(
            "diluted_shares_weighted",
            ("WeightedAverageNumberOfDilutedSharesOutstanding",),
            unit="shares",
        ),
        # Balance sheet (instants)
        MetricDef("cash", ("CashAndCashEquivalentsAtCarryingValue",), instant=True),
        MetricDef(
            "short_term_investments",
            (
                "ShortTermInvestments",
                "MarketableSecuritiesCurrent",
                "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
            ),
            instant=True,
        ),
        MetricDef("debt_long_term_current", ("LongTermDebtCurrent",), instant=True),
        MetricDef("debt_long_term_noncurrent", ("LongTermDebtNoncurrent",), instant=True),
        MetricDef("debt_long_term_total", ("LongTermDebt",), instant=True),
        MetricDef("debt_short_term_borrowings", ("ShortTermBorrowings",), instant=True),
        MetricDef("debt_commercial_paper", ("CommercialPaper",), instant=True),
        MetricDef("finance_lease_current", ("FinanceLeaseLiabilityCurrent",), instant=True),
        MetricDef("finance_lease_noncurrent", ("FinanceLeaseLiabilityNoncurrent",), instant=True),
        MetricDef("noncontrolling_interest", ("MinorityInterest",), instant=True),
        MetricDef("preferred_stock", ("PreferredStockValue",), instant=True),
        # Cover page (dei). Reported per share class for multi-class companies.
        MetricDef(
            "shares_outstanding_cover",
            ("EntityCommonStockSharesOutstanding",),
            unit="shares",
            instant=True,
            taxonomy="dei",
            sum_share_classes=True,
        ),
    ]
}


# ---- fetching -----------------------------------------------------------------


def get_company_facts(cik: int | str, client: SECClient) -> dict:
    return client.get_json(COMPANYFACTS_URL.format(cik10=cik10(cik)))


# ---- extraction ---------------------------------------------------------------


def extract_all(companyfacts: dict) -> dict[str, MetricSeries]:
    return {name: extract_metric(companyfacts, mdef) for name, mdef in METRICS.items()}


def extract_metric(companyfacts: dict, mdef: MetricDef | str) -> MetricSeries:
    if isinstance(mdef, str):
        mdef = METRICS[mdef]
    series = MetricSeries(metric=mdef.name)

    # Per tag: deduped facts keyed by (start, end).
    by_tag: dict[str, dict[tuple, Fact]] = {}
    for tag in mdef.tags + mdef.composite:
        by_tag[tag] = _tag_facts(companyfacts, mdef, tag, series.notes)

    # Per period, the first tag in the chain that has a value wins (SPEC.md).
    periods = set()
    for tag in mdef.tags:
        periods |= by_tag[tag].keys()
    chosen: dict[tuple, Fact] = {}
    for key in periods:
        for tag in mdef.tags:
            if key in by_tag[tag]:
                chosen[key] = by_tag[tag][key]
                break

    if mdef.composite:
        comp_periods = set.intersection(*(set(by_tag[t]) for t in mdef.composite))
        partial = set().union(*(set(by_tag[t]) for t in mdef.composite)) - comp_periods
        for key in comp_periods - chosen.keys():
            parts = [by_tag[t][key] for t in mdef.composite]
            chosen[key] = Fact(
                metric=mdef.name,
                value=sum(p.value for p in parts),
                unit=mdef.unit,
                start=key[0],
                end=key[1],
                period_type=parts[0].period_type,
                sources=tuple(p.source for p in parts),
                restated=any(p.restated for p in parts),
                note=f"Sum of {' + '.join(mdef.composite)} (no single D&A tag reported)",
            )
        missing_partial = partial - chosen.keys()
        if missing_partial:
            series.notes.append(
                f"{len(missing_partial)} period(s) report only part of "
                f"{' + '.join(mdef.composite)}; left as missing rather than summing a partial figure"
            )

    series.facts = sorted(chosen.values(), key=lambda f: (f.end, f.start or date.min))
    if not series.facts:
        series.notes.append(f"No {mdef.unit} values found for tags: {', '.join(mdef.tags)}")
    return series


def _tag_facts(companyfacts: dict, mdef: MetricDef, tag: str, notes: list[str]) -> dict[tuple, Fact]:
    node = companyfacts.get("facts", {}).get(mdef.taxonomy, {}).get(tag)
    if not node:
        return {}
    units = node.get("units", {})
    rows = units.get(mdef.unit)
    if rows is None:
        if units:
            notes.append(
                f"{tag} is reported only in {', '.join(units)}, not {mdef.unit}; ignored (v1 is USD only)"
            )
        return {}

    rows = [r for r in rows if r.get("form") in ALLOWED_FORMS]
    if mdef.instant:
        rows = [r for r in rows if "start" not in r]
    else:
        rows = [r for r in rows if "start" in r]

    if mdef.sum_share_classes:
        rows = _sum_share_classes(rows, tag, notes)

    # Dedupe by (start, end): most recently filed wins (restatements), ties
    # broken by accession number (later accession = later submission).
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        grouped[(_d(r.get("start")), _d(r["end"]))].append(r)

    out: dict[tuple, Fact] = {}
    for (start, end), group in grouped.items():
        group.sort(key=lambda r: (r["filed"], r["accn"]))
        best = group[-1]
        restated = len({r["val"] for r in group}) > 1
        out[(start, end)] = Fact(
            metric=mdef.name,
            value=float(best["val"]),
            unit=mdef.unit,
            start=start,
            end=end,
            period_type=classify_period(start, end),
            sources=(_source(mdef, tag, best),),
            restated=restated,
            note=best.get("_note"),
        )
    return out


def _sum_share_classes(rows: list[dict], tag: str, notes: list[str]) -> list[dict]:
    """Combine per-class cover-page share counts filed in the same document.

    companyfacts drops the share-class dimension, so a company with Class A and
    Class B stock shows two rows with the same accession and date. Those are
    summed (FD-3: cover-page shares summed across share classes). Exact
    duplicate rows (same value) are treated as one fact, not two classes.
    """
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        grouped[(r["accn"], r["end"])].append(r)
    out = []
    for (accn, end), group in grouped.items():
        distinct = {r["val"]: r for r in group}
        if len(distinct) == 1:
            out.append(group[0])
            continue
        vals = sorted(distinct)
        base = dict(group[0])
        base["val"] = sum(vals)
        base["_note"] = f"Sum of {len(vals)} share classes: " + ", ".join(f"{v:,.0f}" for v in vals)
        out.append(base)
    multi = sum(1 for g in grouped.values() if len({r["val"] for r in g}) > 1)
    if multi:
        notes.append(f"{tag}: {multi} filing(s) report multiple share classes; classes summed")
    return out


def _source(mdef: MetricDef, tag: str, r: dict) -> Source:
    return Source(
        taxonomy=mdef.taxonomy,
        tag=tag,
        form=r["form"],
        accession=r["accn"],
        filed=_d(r["filed"]),
        start=_d(r.get("start")),
        end=_d(r["end"]),
        fy=r.get("fy"),
        fp=r.get("fp"),
    )


def _d(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None
