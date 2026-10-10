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
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from enum import Enum

import re
import xml.etree.ElementTree as ET

from engine.sec_client import SECClient, SECError
from engine.tickers import CompanyMetadata, Filing, cik10, get_metadata

# A cover-page share count this much older than the latest filing's period end is
# re-read from that filing (FD-3 wants the latest count).
STALE_COVER_DAYS = 200

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
# PepsiCo's 12/12/12/16-week quarters make its half year 168 days and its
# nine months 252, so the YTD windows reach down that far.
_PERIOD_WINDOWS = [
    (PeriodType.QUARTER, 80, 100),
    (PeriodType.YTD_6M, 165, 192),
    (PeriodType.YTD_9M, 248, 285),
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
    # Tried before ``composite`` (same all-parts-present rule). AMD and Marvell
    # show cash-flow D&A as OtherDepreciationAndAmortization (D&A excluding
    # acquired intangibles) plus AmortizationOfIntangibleAssets; FD-1 wants the
    # cash flow statement, so this beats the depreciation note figure.
    pre_composite: tuple[str, ...] = ()
    # Used alone for periods where the composite is incomplete but this tag is
    # reported (FD-10 Q1: D&A = depreciation when amortization isn't broken out).
    last_resort: str | None = None
    sum_share_classes: bool = False
    # A note attached to every value taken from one of these tags (a fallback worth flagging).
    tag_notes: tuple[tuple[str, str], ...] = ()


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
            pre_composite=("OtherDepreciationAndAmortization", "AmortizationOfIntangibleAssets"),
            composite=("Depreciation", "AmortizationOfIntangibleAssets"),
            last_resort="Depreciation",
        ),
        # ProfitLoss (consolidated, incl. noncontrolling interests) only when
        # NetIncomeLoss isn't reported for the period: Broadcom switched in FY2025.
        MetricDef("net_income", ("NetIncomeLoss", "ProfitLoss")),
        MetricDef("operating_cash_flow", ("NetCashProvidedByUsedInOperatingActivities",)),
        # NVIDIA and Qualcomm tag capex as PaymentsToAcquireProductiveAssets
        # ("purchases of property and equipment and intangible assets").
        MetricDef("capex", ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets")),
        # DCF inputs (FD-11): tax rate, cost of debt.
        MetricDef("income_tax", ("IncomeTaxExpenseBenefit",)),
        MetricDef(
            "pretax_income",
            (
                "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
            ),
        ),
        MetricDef(
            "interest_expense",
            ("InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt", "InterestAndDebtExpense"),
        ),
        # FD-10 Q15 fallback for filers with no operating income line (Lilly).
        MetricDef("nonoperating_income", ("NonoperatingIncomeExpense",)),
        MetricDef("sbc", ("ShareBasedCompensation",)),
        MetricDef(
            "diluted_shares_weighted",
            ("WeightedAverageNumberOfDilutedSharesOutstanding",),
            unit="shares",
        ),
        # Balance sheet (instants)
        # FD-10 Q14: some filers (P&G, Target, Starbucks, Chevron) tag the balance-sheet
        # cash line only with the cash-flow total that includes restricted cash. Used
        # only when the plain tag is missing for the date, and flagged in metrics.py.
        MetricDef("cash", ("CashAndCashEquivalentsAtCarryingValue", "Cash",
                           "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"), instant=True,
                  tag_notes=(("CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
                              "balance-sheet cash is tagged only with the total that includes restricted cash, "
                              "so any restricted cash is included (FD-10 Q14)"),)),
        # Working capital for the DCF (FD-11).
        MetricDef("current_assets", ("AssetsCurrent",), instant=True),
        MetricDef("current_liabilities", ("LiabilitiesCurrent",), instant=True),
        MetricDef(
            "short_term_investments",
            (
                "ShortTermInvestments",
                "MarketableSecuritiesCurrent",
                "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
                "DebtSecuritiesCurrent",  # NVIDIA from FY2027 ("Marketable debt securities")
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
        # Some filers (e.g. MSFT) tag only the total, not the current/noncurrent
        # split. Kept separate so Phase 2 can avoid adding it on top of the split.
        MetricDef("finance_lease_total", ("FinanceLeaseLiability",), instant=True),
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


def get_series(
    cik: int | str, client: SECClient, meta: CompanyMetadata | None = None
) -> dict[str, MetricSeries]:
    """All metrics for a company, with the cover-share and operating-income fallbacks applied."""
    meta = meta or get_metadata(cik, client)
    facts = add_unprocessed_filing(get_company_facts(cik, client), cik, meta, client)
    series = extract_all(facts)
    fill_operating_income(series)
    cover, latest = series["shares_outstanding_cover"], meta.latest("10-K", "10-Q")
    stale = (cover and latest and latest.report_date
             and cover.latest().end < latest.report_date - timedelta(days=STALE_COVER_DAYS))
    if not cover or stale:
        # Visa's last undimensioned cover count in companyfacts is from 2010; since then
        # it tags each share class separately, which companyfacts drops.
        fill_cover_shares_from_filing(cover, cik, meta, client)
    filing = meta.latest("10-K", "10-Q")
    if filing and filing.report_date and not any(
        series[m].get(None, filing.report_date)
        for m in ("debt_long_term_current", "debt_long_term_noncurrent", "debt_long_term_total")
    ):
        series["debt_company_specific"] = company_specific_debt(cik, filing, client)
    return series


# ---- filings companyfacts hasn't caught up with ------------------------------
#
# companyfacts is rebuilt by the SEC on its own schedule, and for some filers it
# runs a quarter behind (Visa's July 2026 10-Q was still missing in October). The
# filing's own XBRL instance has the same facts, so when the latest 10-K/10-Q's
# accession number appears nowhere in companyfacts, its non-dimensional facts are
# read from the instance and added in companyfacts' shape. Each one carries a
# note saying so; the tag, form, accession and dates are the filing's own.

INSTANCE_NOTE = "read from the filing's XBRL instance (SEC companyfacts didn't include this filing yet)"
_UNIT_MEASURES = {"iso4217:USD": "USD", "shares": "shares", "xbrli:shares": "shares"}


def add_unprocessed_filing(companyfacts: dict, cik: int | str, meta: CompanyMetadata,
                           client: SECClient) -> dict:
    filing = meta.latest("10-K", "10-Q")
    if filing is None or _has_accession(companyfacts, filing.accession):
        return companyfacts
    url = instance_url(cik, filing)
    if url is None:
        return companyfacts
    try:
        rows = instance_rows(client.get_text(url), filing)
    except (SECError, ET.ParseError):
        return companyfacts
    return merge_rows(companyfacts, rows)


def _has_accession(companyfacts: dict, accession: str) -> bool:
    for tags in companyfacts.get("facts", {}).values():
        for node in tags.values():
            for rows in node.get("units", {}).values():
                if any(r.get("accn") == accession for r in rows):
                    return True
    return False


def instance_rows(xml_text: str, filing: Filing) -> dict[str, dict[str, dict[str, list[dict]]]]:
    """taxonomy -> tag -> unit -> companyfacts-style rows, for non-dimensional facts."""
    root = ET.fromstring(xml_text)
    contexts: dict[str, tuple[str | None, str]] = {}
    for ctx in root.iter(f"{_XBRLI}context"):
        if any(m.tag.endswith("explicitMember") or m.tag.endswith("typedMember") for m in ctx.iter()):
            continue  # companyfacts drops dimensional facts too
        p = ctx.find(f"{_XBRLI}period")
        if p is None:
            continue
        inst, start, end = (p.find(f"{_XBRLI}{k}") for k in ("instant", "startDate", "endDate"))
        if inst is not None and inst.text:
            contexts[ctx.get("id")] = (None, inst.text.strip())
        elif start is not None and end is not None and start.text and end.text:
            contexts[ctx.get("id")] = (start.text.strip(), end.text.strip())
    units = {}
    for u in root.iter(f"{_XBRLI}unit"):
        measures = [m.text.strip() for m in u.iter(f"{_XBRLI}measure") if m.text]
        if len(measures) == 1 and measures[0] in _UNIT_MEASURES:
            units[u.get("id")] = _UNIT_MEASURES[measures[0]]
    ns_tax = {"fasb.org/us-gaap": "us-gaap", "xbrl.sec.gov/dei": "dei"}
    fy = fp = None
    for el in root:
        if el.tag.endswith("}DocumentFiscalYearFocus") and el.text:
            fy = int(el.text.strip()[:4]) if el.text.strip()[:4].isdigit() else None
        elif el.tag.endswith("}DocumentFiscalPeriodFocus") and el.text:
            fp = el.text.strip()
    out: dict = {}
    for el in root:
        ns, _, local = el.tag.rpartition("}")
        tax = next((t for k, t in ns_tax.items() if k in ns), None)
        ctx = contexts.get(el.get("contextRef"))
        unit = units.get(el.get("unitRef"))
        if tax is None or ctx is None or unit is None or not el.text:
            continue
        try:
            val = float(el.text.strip())
        except ValueError:
            continue
        row = {"end": ctx[1], "val": val, "accn": filing.accession, "fy": fy, "fp": fp,
               "form": filing.form, "filed": filing.filing_date.isoformat(), "_note": INSTANCE_NOTE}
        if ctx[0]:
            row["start"] = ctx[0]
        bucket = out.setdefault(tax, {}).setdefault(local, {}).setdefault(unit, [])
        if row not in bucket:
            bucket.append(row)
    return out


def merge_rows(companyfacts: dict, rows: dict) -> dict:
    """A copy of companyfacts with ``rows`` appended (the cached JSON is left untouched)."""
    facts = {tax: dict(tags) for tax, tags in companyfacts.get("facts", {}).items()}
    for tax, tags in rows.items():
        dest = facts.setdefault(tax, {})
        for tag, by_unit in tags.items():
            node = dest.get(tag, {})
            units = dict(node.get("units", {}))
            for unit, new in by_unit.items():
                units[unit] = list(units.get(unit, [])) + new
            dest[tag] = {**node, "units": units}
    return {**companyfacts, "facts": facts}


# ---- operating income when there is no operating income line ----------------

EBIT_FALLBACK_NOTES = {
    "interest": ("no operating income line reported: EBIT = pre-tax income + interest expense "
                 "(FD-10 Q15; includes other non-operating income and expense)"),
    "nonoperating": ("no operating income line reported: EBIT = pre-tax income - non-operating income "
                     "(expense), net (FD-10 Q15)"),
}


def fill_operating_income(series: dict[str, MetricSeries]) -> None:
    """FD-10 Q15: pharma, energy and some industrials (Lilly, J&J, Chevron, Deere, KLA)
    don't report an operating income subtotal. For periods with no OperatingIncomeLoss:
    EBIT = pre-tax income + interest expense when both are reported for the period;
    otherwise pre-tax income - non-operating income (expense), net, when that is."""
    op, pretax = series["operating_income"], series["pretax_income"]
    interest, nonop = series["interest_expense"], series.get("nonoperating_income", MetricSeries("x"))
    have = {(f.start, f.end) for f in op.facts}
    added = 0
    for f in pretax.facts:
        if (f.start, f.end) in have:
            continue
        i, n = interest.get(f.start, f.end), nonop.get(f.start, f.end)
        if i is not None:
            value, other, how = f.value + i.value, i, "interest"
        elif n is not None:
            value, other, how = f.value - n.value, n, "nonoperating"
        else:
            continue
        op.facts.append(Fact(
            metric="operating_income", value=value, unit="USD", start=f.start, end=f.end,
            period_type=f.period_type, sources=f.sources + other.sources, restated=f.restated or other.restated,
            note=EBIT_FALLBACK_NOTES[how] + (f"; {f.note}" if f.note else ""),
        ))
        added += 1
    if added:
        op.facts.sort(key=lambda x: (x.end, x.start or date.min))
        op.notes.append(f"{added} period(s) with no operating income line use the FD-10 Q15 fallback")


# ---- company-specific debt tags (information only) ----------------------------
#
# Some filers put their debt under their own tags (CoreWeave: crwv:RecourseDebtCurrent,
# ...), which companyfacts doesn't carry. These are listed so a missing debt figure
# can say what the company reports instead. They are NOT added to total debt:
# which of them to sum is a judgment the owner hasn't made yet.

_DEBT_WORDS = re.compile(r"(Debt|Borrowing|NotesPayable|LoansPayable|CreditFacilit)")
_NOT_BALANCE = re.compile(
    r"(Maturit|Interest|Discount|Issuance|FairValue|Repay|Proceeds|Payment|Covenant|Expense|"
    r"Securities|Extinguish|Conversion|Converted|Rate|Term(?!Debt)|Gain|Loss|TextBlock|Policy|Table)"
)


def company_specific_debt(cik: int | str, filing: Filing, client: SECClient) -> MetricSeries:
    series = MetricSeries(metric="debt_company_specific")
    url = instance_url(cik, filing)
    if url is None:
        return series
    try:
        found = parse_company_debt(client.get_text(url), filing.report_date)
    except (SECError, ET.ParseError):
        return series
    for tag, value in found:
        series.facts.append(Fact(
            metric="debt_company_specific", value=value, unit="USD", start=None, end=filing.report_date,
            period_type=PeriodType.INSTANT,
            sources=(Source(taxonomy=tag.split(":")[0], tag=tag, form=filing.form, accession=filing.accession,
                            filed=filing.filing_date, start=None, end=filing.report_date, fy=None, fp=None),),
        ))
    return series


def parse_company_debt(xml_text: str, end: date) -> list[tuple[str, float]]:
    """Non-dimensional USD facts at ``end`` in the company's own namespace that look like debt."""
    root = ET.fromstring(xml_text)
    plain_at_end = set()
    for ctx in root.iter(f"{_XBRLI}context"):
        instant = ctx.find(f"{_XBRLI}period/{_XBRLI}instant")
        has_dims = any(m.tag.endswith("explicitMember") or m.tag.endswith("typedMember") for m in ctx.iter())
        if instant is not None and instant.text and _d(instant.text.strip()) == end and not has_dims:
            plain_at_end.add(ctx.get("id"))
    prefixes = {uri: p for p, uri in _namespaces(xml_text).items()}
    out = []
    for el in root:
        ns, _, local = el.tag.rpartition("}")
        ns = ns.lstrip("{")
        if any(std in ns for std in ("fasb.org", "xbrl.sec.gov", "xbrl.org")):
            continue
        if el.get("contextRef") not in plain_at_end or not el.text:
            continue
        if _DEBT_WORDS.search(local) and not _NOT_BALANCE.search(local):
            try:
                out.append((f"{prefixes.get(ns, 'custom')}:{local}", float(el.text.strip())))
            except ValueError:
                continue
    return sorted(set(out))


def _namespaces(xml_text: str) -> dict[str, str]:
    return dict(re.findall(r'xmlns:([\w-]+)="([^"]+)"', xml_text[:20000]))


# ---- extraction ---------------------------------------------------------------


def extract_all(companyfacts: dict) -> dict[str, MetricSeries]:
    return {name: extract_metric(companyfacts, mdef) for name, mdef in METRICS.items()}


def extract_metric(companyfacts: dict, mdef: MetricDef | str) -> MetricSeries:
    if isinstance(mdef, str):
        mdef = METRICS[mdef]
    series = MetricSeries(metric=mdef.name)

    # Per tag: deduped facts keyed by (start, end).
    by_tag: dict[str, dict[tuple, Fact]] = {}
    for tag in dict.fromkeys(mdef.tags + mdef.pre_composite + mdef.composite):
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
        for combo in (mdef.pre_composite, mdef.composite):
            if not combo:
                continue
            for key in set.intersection(*(set(by_tag[t]) for t in combo)) - chosen.keys():
                parts = [by_tag[t][key] for t in combo]
                chosen[key] = Fact(
                    metric=mdef.name,
                    value=sum(p.value for p in parts),
                    unit=mdef.unit,
                    start=key[0],
                    end=key[1],
                    period_type=parts[0].period_type,
                    sources=tuple(p.source for p in parts),
                    restated=any(p.restated for p in parts),
                    note=f"Sum of {' + '.join(combo)} (no single D&A tag reported)",
                )
        comp_periods = set.intersection(*(set(by_tag[t]) for t in mdef.composite))
        partial = set().union(*(set(by_tag[t]) for t in mdef.composite)) - comp_periods
        if mdef.last_resort:
            # FD-10 Q1: e.g. Alphabet's cash flow statement shows depreciation
            # only; intangible amortization sits in "other" and has no tag.
            alone = [t for t in mdef.composite if t != mdef.last_resort]
            for key in (partial - chosen.keys()) & by_tag[mdef.last_resort].keys():
                base = by_tag[mdef.last_resort][key]
                chosen[key] = Fact(
                    metric=mdef.name,
                    value=base.value,
                    unit=mdef.unit,
                    start=base.start,
                    end=base.end,
                    period_type=base.period_type,
                    sources=base.sources,
                    restated=base.restated,
                    note=(
                        f"{mdef.last_resort} only: {' / '.join(alone)} not reported for this "
                        "period, so it may understate (FD-10 Q1)"
                    ),
                )
        missing_partial = partial - chosen.keys()
        if missing_partial:
            series.notes.append(
                f"{len(missing_partial)} period(s) report only part of "
                f"{' + '.join(mdef.composite)}; left as missing rather than summing a partial figure"
            )

    if mdef.tag_notes:
        flags = dict(mdef.tag_notes)
        for key, f in chosen.items():
            if f.tag in flags:
                chosen[key] = replace(f, note="; ".join(n for n in (flags[f.tag], f.note) if n))
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


# ---- cover-page shares from the filing itself -------------------------------
#
# companyfacts drops any fact that carries a dimension. Companies with several
# share classes (e.g. Alphabet: Class A, B, C) tag their cover-page share count
# per class, so companyfacts has no EntityCommonStockSharesOutstanding for them
# at all. For those, read the per-class counts straight from the latest 10-K or
# 10-Q's XBRL instance and sum them (FD-3: cover-page shares summed across
# share classes).

_XBRLI = "{http://www.xbrl.org/2003/instance}"
_COVER_SHARES = "EntityCommonStockSharesOutstanding"


def instance_url(cik: int | str, filing: Filing) -> str | None:
    """URL of the XBRL instance SEC extracts from an inline-XBRL filing."""
    doc = filing.primary_document
    if not doc.endswith(".htm"):
        return None
    return (
        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
        f"{filing.accession.replace('-', '')}/{doc[:-4]}_htm.xml"
    )


def parse_cover_shares(xml_text: str) -> list[tuple[str | None, float, date]]:
    """(share class member or None, shares, as-of date) for each cover-page fact."""
    root = ET.fromstring(xml_text)
    contexts: dict[str, tuple[str | None, date | None]] = {}
    for ctx in root.iter(f"{_XBRLI}context"):
        instant = ctx.find(f"{_XBRLI}period/{_XBRLI}instant")
        members = [m.text.strip() for m in ctx.iter() if m.tag.endswith("explicitMember") and m.text]
        contexts[ctx.get("id")] = (
            "+".join(members) or None,
            _d(instant.text.strip()) if instant is not None and instant.text else None,
        )
    out = []
    for el in root:
        ns, _, local = el.tag.rpartition("}")
        if local != _COVER_SHARES or "xbrl.sec.gov/dei" not in ns or not el.text:
            continue
        member, as_of = contexts.get(el.get("contextRef"), (None, None))
        if as_of is not None:
            out.append((member, float(el.text.strip()), as_of))
    return out


def fill_cover_shares_from_filing(
    series: MetricSeries, cik: int | str, meta: CompanyMetadata, client: SECClient
) -> None:
    filing = meta.latest("10-K", "10-Q")
    url = instance_url(cik, filing) if filing else None
    if url is None:
        series.notes.append("Cover-page shares not in companyfacts and no inline-XBRL 10-K/10-Q to read them from")
        return
    try:
        facts = parse_cover_shares(client.get_text(url))
    except (SECError, ET.ParseError) as exc:
        series.notes.append(f"Cover-page shares not in companyfacts; reading {url} failed: {exc}")
        return
    if not facts:
        series.notes.append(f"Cover-page shares not in companyfacts or in {url}")
        return

    # Exact duplicates (same class, same value) count once.
    distinct = {(m, v, d) for m, v, d in facts}
    dates = {d for _, _, d in distinct}
    if len(dates) > 1:
        series.notes.append(
            f"Cover-page share classes in {filing.accession} have different as-of dates "
            f"({', '.join(sorted(map(str, dates)))}); not summed"
        )
        return
    as_of = dates.pop()
    parts = sorted(distinct, key=lambda x: x[0] or "")
    sources = tuple(
        Source(
            taxonomy="dei",
            tag=_COVER_SHARES,
            form=filing.form,
            accession=filing.accession,
            filed=filing.filing_date,
            start=None,
            end=as_of,
            fy=None,
            fp=None,
        )
        for _ in parts
    )
    label = ", ".join(f"{(m or 'all').split(':')[-1]} {v:,.0f}" for m, v, _ in parts)
    series.facts = [
        Fact(
            metric=series.metric,
            value=sum(v for _, v, _ in parts),
            unit="shares",
            start=None,
            end=as_of,
            period_type=PeriodType.INSTANT,
            sources=sources[:1] if len(parts) == 1 else sources,
            note=(
                f"Sum of {len(parts)} share classes: {label} "
                if len(parts) > 1 else f"{label} "
            ) + "(read from the filing's XBRL instance; companyfacts omits per-class cover facts)",
        )
    ]
    series.notes = [n for n in series.notes if not n.startswith("No shares values found")]
    series.notes.append("Cover-page shares taken from the latest filing's XBRL instance (only that filing)")
