"""EBITDA, EV bridge, multiples, margins, growth (per FINANCE_DECISIONS.md).

Inputs are the xbrl.py series for one company, the period dates to use, and a
share price figure from market.py. Every output is a periods.Figure, so each
number carries its formula, its inputs, and the filings behind it.

Judgment calls not yet in FINANCE_DECISIONS.md are tagged "FD-10 Q4".."Q8"
and are logged there for the owner's decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from engine import periods
from engine.periods import Figure, missing
from engine.xbrl import MetricSeries, PeriodType

NM_MULTIPLE_CAP = 100.0  # FD-6: multiples above 100x shown as NM, kept in a footnote
SHARE_COUNT_TOLERANCE = 0.03  # FD-3: flag cover vs diluted shares differing by >3%


@dataclass
class CompanyMetrics:
    ltm_end: date
    fiscal_year_ends: list[date]
    figures: dict[str, Figure] = field(default_factory=dict)  # LTM and point-in-time figures
    fiscal_years: dict[date, dict[str, Figure]] = field(default_factory=dict)

    def __getitem__(self, name: str) -> Figure:
        return self.figures[name]


# ---- small arithmetic helpers that keep provenance ------------------------------


def combine(name: str, parts: list[tuple[int, Figure]], unit: str, formula: str,
            as_of: date | None = None, notes: tuple[str, ...] = ()) -> Figure:
    """Signed sum of figures. n/a if any part is n/a."""
    bad = [p for _, p in parts if not p.ok]
    inputs = tuple(p for _, p in parts)
    if bad:
        return missing(
            name, unit,
            "; ".join(f"{p.name} n/a ({p.reason})" for p in bad),
            as_of=as_of, inputs=inputs, notes=notes,
        )
    facts = tuple((s * fs, f) for s, p in parts for fs, f in p.facts)
    return Figure(
        name=name, value=sum(s * p.value for s, p in parts), unit=unit, formula=formula,
        as_of=as_of, facts=facts, inputs=inputs, notes=notes,
    )


def ratio(name: str, num: Figure, den: Figure, unit: str, formula: str,
          multiple: bool = False, positive_den: bool = False, notes: tuple[str, ...] = ()) -> Figure:
    """num / den. For valuation multiples (multiple=True) FD-6 NM rules apply.

    positive_den: NM when the denominator is negative, without the other
    multiple rules (net debt / EBITDA can be negative for a net-cash company).
    """
    inputs = (num, den)
    for f in inputs:
        if not f.ok:
            return missing(name, unit, f"{f.name} n/a ({f.reason})", inputs=inputs, notes=notes)
    if den.value == 0 or ((multiple or positive_den) and den.value < 0):
        # FD-6: negative or zero denominator -> NM
        return Figure(name=name, value=None, unit=unit, formula=formula, inputs=inputs, nm=True,
                      reason=f"{den.name} is {'zero' if den.value == 0 else 'negative'}", notes=notes)
    value = num.value / den.value
    if multiple and value < 0:
        # FD-10 Q7: a negative multiple (negative EV or equity) is shown as NM.
        return Figure(name=name, value=None, unit=unit, formula=formula, inputs=inputs, nm=True,
                      raw_value=value, reason=f"{num.name} is negative", notes=notes)
    if multiple and value > NM_MULTIPLE_CAP:
        # FD-6: above 100x -> NM, value kept for the footnote
        return Figure(name=name, value=None, unit=unit, formula=formula, inputs=inputs, nm=True,
                      raw_value=value, reason=f"above {NM_MULTIPLE_CAP:.0f}x ({value:.1f}x)", notes=notes)
    return Figure(name=name, value=value, unit=unit, formula=formula, inputs=inputs, notes=notes)


def growth(name: str, current: Figure, prior: Figure, formula: str) -> Figure:
    inputs = (current, prior)
    for f in inputs:
        if not f.ok:
            return missing(name, "ratio", f"{f.name} n/a ({f.reason})", inputs=inputs)
    if prior.value <= 0:
        return Figure(name=name, value=None, unit="ratio", formula=formula, inputs=inputs, nm=True,
                      reason=f"prior period {prior.name} is not positive")
    return Figure(name=name, value=current.value / prior.value - 1, unit="ratio",
                  formula=formula, inputs=inputs)


def _renamed(f: Figure, name: str) -> Figure:
    return Figure(**{**f.__dict__, "name": name})


# ---- debt (FD-2) ------------------------------------------------------------------


def _optional_balance(series: MetricSeries, end: date, fy_end: date | None) -> Figure:
    """A balance that is legitimately absent for many companies.

    FD-10 Q4: if the company doesn't report the item at all at this date (no
    commercial paper, no preferred stock...), treat it as zero and say so.
    """
    f = periods.balance_at(series, end, fy_end)
    if f.ok:
        return f
    dropped = _dropped([series], end, fy_end, series.metric)
    if dropped is not None:
        return dropped
    return Figure(name=series.metric, value=0.0, unit="USD", formula="not reported -> 0",
                  as_of=end, notes=(f"{series.metric}: {f.reason}; treated as 0 (FD-10 Q4)",))


def _dropped(group: list[MetricSeries], end: date, fy_end: date | None, name: str,
             hint: str = "") -> Figure | None:
    """n/a when an item was reported (non-zero) after the latest 10-K but not at ``end``.

    That pattern means the company stopped using the standard tag, not that the
    item went away (CoreWeave moved its debt to company-specific tags in its
    June 2026 10-Q). Treating it as 0 would silently drop a real liability
    (CLAUDE.md rule 3), so FD-10 Q4's "treat as 0" doesn't apply.
    """
    recent = [
        f for s in group for f in s.facts
        if f.start is None and f.end < end and (fy_end is None or f.end > fy_end) and f.value
    ]
    if not recent:
        return None
    last = max(recent, key=lambda f: f.end)
    return missing(
        name, "USD",
        f"{last.metric} was {last.value / 1e6:,.0f}m at {last.end} but isn't reported at {end}; "
        f"the latest filing likely uses company-specific tags{hint}",
        as_of=end,
    )


def _company_specific_debt(cs: MetricSeries | None, end: date) -> Figure | None:
    """FD-10 Q9: with no standard debt tags at ``end``, sum the company's own debt lines.

    Refused (None, so the caller shows n/a) if one tag name is a prefix of
    another (e.g. RecourseDebt and RecourseDebtCurrent): that usually means a
    total plus its parts, and summing would double count.
    """
    facts = [f for f in (cs.facts if cs else []) if f.end == end]
    if not facts:
        return None
    names = [f.tag.split(":")[-1] for f in facts]
    if any(a != b and b.startswith(a) for a in names for b in names):
        return None
    listed = ", ".join(f"{f.tag} {f.value / 1e6:,.0f}m" for f in facts)
    return Figure(
        name="long_term_debt", value=sum(f.value for f in facts), unit="USD",
        formula="sum of the company's own debt lines (FD-10 Q9)", as_of=end,
        facts=tuple((1, f) for f in facts),
        notes=(f"No standard debt tags at {end}; summed company-specific debt lines: {listed} (FD-10 Q9)",),
    )


def _company_debt_hint(series: dict[str, MetricSeries]) -> str:
    cs = series.get("debt_company_specific")
    if not cs or not cs.facts:
        return ""
    return " (" + ", ".join(f"{f.tag} {f.value / 1e6:,.0f}m" for f in cs.facts) + ")"


def total_debt(series: dict[str, MetricSeries], end: date, fy_end: date | None) -> Figure:
    """FD-2: total debt incl. finance leases, excl. operating leases.

    Components, avoiding the classic double count (LongTermDebt usually
    already includes the current portion):
      long-term debt  = LongTermDebtCurrent + LongTermDebtNoncurrent when both
                        are reported (balance sheet face), else LongTermDebt.
      short-term      = ShortTermBorrowings + CommercialPaper.
      finance leases  = current + noncurrent when both are reported, else the
                        FinanceLeaseLiability total (Microsoft tags only that).
    """
    bal = lambda m: periods.balance_at(series[m], end, fy_end)  # noqa: E731
    notes: list[str] = []

    cur, noncur, ltd_total = bal("debt_long_term_current"), bal("debt_long_term_noncurrent"), bal("debt_long_term_total")
    if cur.ok and noncur.ok:
        ltd = combine("long_term_debt", [(1, cur), (1, noncur)], "USD",
                      "LongTermDebtCurrent + LongTermDebtNoncurrent", as_of=end)
        if ltd_total.ok and ltd_total.as_of == end and ltd.value:
            diff = ltd_total.value / ltd.value - 1
            if abs(diff) > 0.01:
                notes.append(
                    f"LongTermDebt tag ({ltd_total.value:,.0f}) differs from current + noncurrent "
                    f"({ltd.value:,.0f}) by {diff:+.1%}; the balance sheet lines are used"
                )
    elif ltd_total.ok and (ltd_total.as_of == end or not _dropped(
            [series["debt_long_term_current"], series["debt_long_term_noncurrent"]], end, fy_end, "x")):
        # A 10-K-date LongTermDebt (FD-10 Q3) is only used if the split wasn't
        # reported after it; otherwise it would be a stale stand-in.
        ltd = _renamed(ltd_total, "long_term_debt")
        notes.append("Long-term debt from the LongTermDebt total (current/noncurrent split not reported)")
    elif noncur.ok or cur.ok:
        # FD-10 Q4: the half that isn't reported is treated as zero.
        have = noncur if noncur.ok else cur
        ltd = _renamed(have, "long_term_debt")
        notes.append(f"Only {have.name} reported at {end}; the other part treated as 0 (FD-10 Q4)")
    else:
        ltd = _company_specific_debt(series.get("debt_company_specific"), end) or _dropped(
            [series[m] for m in ("debt_long_term_current", "debt_long_term_noncurrent", "debt_long_term_total")],
            end, fy_end, "long_term_debt", _company_debt_hint(series),
        ) or Figure(name="long_term_debt", value=0.0, unit="USD", formula="not reported -> 0", as_of=end,
                    notes=(f"No long-term debt reported at {end}; treated as 0 (FD-10 Q4)",))

    stb = _optional_balance(series["debt_short_term_borrowings"], end, fy_end)
    cp = _optional_balance(series["debt_commercial_paper"], end, fy_end)
    if stb.value and cp.value:
        notes.append("Both ShortTermBorrowings and CommercialPaper reported; check the first doesn't include the second (FD-10 Q5)")

    fl_cur, fl_non, fl_tot = (bal(m) for m in ("finance_lease_current", "finance_lease_noncurrent", "finance_lease_total"))
    if fl_cur.ok and fl_non.ok:
        fl = combine("finance_leases", [(1, fl_cur), (1, fl_non)], "USD",
                     "FinanceLeaseLiabilityCurrent + FinanceLeaseLiabilityNoncurrent", as_of=fl_cur.as_of)
    elif fl_tot.ok:
        fl = _renamed(fl_tot, "finance_leases")
    elif fl_cur.ok or fl_non.ok:
        have = fl_cur if fl_cur.ok else fl_non
        fl = _renamed(have, "finance_leases")
        notes.append(f"Only {have.name} reported; the other part treated as 0 (FD-10 Q4)")
    else:
        fl = _dropped(
            [series[m] for m in ("finance_lease_current", "finance_lease_noncurrent", "finance_lease_total")],
            end, fy_end, "finance_leases",
        ) or Figure(name="finance_leases", value=0.0, unit="USD", formula="not reported -> 0", as_of=end,
                    notes=(f"No finance lease liability reported at or before {end}; treated as 0 (FD-10 Q4)",))

    return combine(
        "total_debt", [(1, ltd), (1, stb), (1, cp), (1, fl)], "USD",
        "long-term debt + short-term borrowings + commercial paper + finance leases (FD-2)",
        as_of=end, notes=tuple(notes),
    )


# ---- the whole company -------------------------------------------------------------


def compute(series: dict[str, MetricSeries], ltm_end: date, price: Figure) -> CompanyMetrics:
    """All Phase 2 figures for one company.

    ``ltm_end`` is the period end of the latest 10-K or 10-Q. ``price`` is a
    USD/share Figure from market.py (or a missing Figure with a reason).
    """
    fy_ends = periods.latest_fiscal_year_ends(series["revenue"], ltm_end, n=3)
    fy_end = fy_ends[0] if fy_ends else None
    out = CompanyMetrics(ltm_end=ltm_end, fiscal_year_ends=fy_ends[:2])
    F = out.figures

    # -- income statement, LTM (FD-4) and last two fiscal years
    for m in ("revenue", "operating_income", "d_and_a", "net_income", "sbc"):
        F[f"ltm_{m}"] = _renamed(periods.ltm(series[m], ltm_end), f"LTM {m}")
    F["ltm_ebitda"] = ebitda(F["ltm_operating_income"], F["ltm_d_and_a"], "LTM EBITDA")
    for end in fy_ends[:2]:
        fy = {m: periods.fiscal_year(series[m], end)
              for m in ("revenue", "operating_income", "d_and_a", "net_income", "sbc")}
        fy["ebitda"] = ebitda(fy["operating_income"], fy["d_and_a"], f"FY{end.year} EBITDA")
        fy["ebitda_margin"] = ratio("EBITDA margin", fy["ebitda"], fy["revenue"], "ratio", "EBITDA / revenue")
        out.fiscal_years[end] = fy

    # -- growth (FD-5): LTM vs prior LTM, and last fiscal year vs the one before
    prior_end = periods.prior_ltm_end(series["revenue"], ltm_end)
    prior_rev = (_renamed(periods.ltm(series["revenue"], prior_end), "prior LTM revenue") if prior_end
                 else missing("prior LTM revenue", "USD", "no comparable period one year earlier"))
    F["prior_ltm_revenue"] = prior_rev
    F["revenue_growth_ltm"] = growth("revenue growth (LTM)", F["ltm_revenue"], prior_rev,
                                     "LTM revenue / prior LTM revenue - 1")
    if len(fy_ends) >= 2:
        F["revenue_growth_fy"] = growth(
            f"revenue growth (FY{fy_ends[0].year})",
            periods.fiscal_year(series["revenue"], fy_ends[0]),
            periods.fiscal_year(series["revenue"], fy_ends[1]),
            "last fiscal year revenue / prior fiscal year revenue - 1",
        )
    else:
        F["revenue_growth_fy"] = missing("revenue growth (FY)", "ratio", "fewer than two fiscal years reported")

    # -- margins (FD-5)
    F["ebitda_margin"] = ratio("EBITDA margin (LTM)", F["ltm_ebitda"], F["ltm_revenue"], "ratio",
                               "LTM EBITDA / LTM revenue")

    # -- balance sheet at the LTM date (FD-2)
    F["total_debt"] = total_debt(series, ltm_end, fy_end)
    F["cash"] = periods.balance_at(series["cash"], ltm_end, fy_end)
    F["short_term_investments"] = _optional_balance(series["short_term_investments"], ltm_end, fy_end)
    F["preferred_stock"] = _optional_balance(series["preferred_stock"], ltm_end, fy_end)
    F["noncontrolling_interest"] = _optional_balance(series["noncontrolling_interest"], ltm_end, fy_end)
    F["net_debt"] = combine(
        "net debt", [(1, F["total_debt"]), (-1, F["cash"]), (-1, F["short_term_investments"])], "USD",
        "total debt - cash - short-term investments (FD-2: restricted cash excluded)", as_of=ltm_end,
    )

    # -- shares (FD-3)
    F["shares_outstanding"] = shares_outstanding(series["shares_outstanding_cover"])
    F["diluted_shares"] = diluted_shares(series["diluted_shares_weighted"], ltm_end)
    F["share_count_check"] = share_check(F["shares_outstanding"], F["diluted_shares"])

    # -- equity value and EV (FD-2, FD-3)
    F["price"] = price
    F["equity_value"] = equity_value(price, F["shares_outstanding"])
    F["enterprise_value"] = combine(
        "enterprise value",
        [(1, F["equity_value"]), (1, F["total_debt"]), (1, F["preferred_stock"]),
         (1, F["noncontrolling_interest"]), (-1, F["cash"]), (-1, F["short_term_investments"])],
        "USD",
        "equity value + total debt + preferred + noncontrolling interest - cash - short-term investments (FD-2)",
        as_of=ltm_end,
    )

    # -- multiples (FD-5, FD-6)
    F["ev_revenue"] = ratio("EV/Revenue", F["enterprise_value"], F["ltm_revenue"], "x",
                            "enterprise value / LTM revenue", multiple=True)
    F["ev_ebitda"] = ratio("EV/EBITDA", F["enterprise_value"], F["ltm_ebitda"], "x",
                           "enterprise value / LTM EBITDA", multiple=True)
    # FD-10 Q6: P/E = equity value / LTM net income (same FD-3 share count as EV).
    F["pe"] = ratio("P/E", F["equity_value"], F["ltm_net_income"], "x",
                    "equity value / LTM net income", multiple=True)
    F["net_debt_ebitda"] = ratio("Net debt / EBITDA", F["net_debt"], F["ltm_ebitda"], "x",
                                 "net debt / LTM EBITDA (negative = net cash)", positive_den=True)
    return out


def ebitda(ebit: Figure, d_and_a: Figure, name: str) -> Figure:
    # FD-1: EBITDA = reported operating income + D&A from the cash flow statement.
    # SBC is shown separately and NOT added back.
    return combine(name, [(1, ebit), (1, d_and_a)], "USD", "operating income + D&A (FD-1)",
                   as_of=ebit.as_of)


def shares_outstanding(series: MetricSeries) -> Figure:
    """FD-3: latest cover-page shares outstanding, summed across classes."""
    f = series.latest()
    if f is None:
        return missing("shares outstanding", "shares", "; ".join(series.notes) or "not reported")
    return Figure(
        name="shares outstanding", value=f.value, unit="shares",
        formula=f"cover-page shares outstanding as of {f.end} (FD-3)", as_of=f.end,
        facts=((1, f),), notes=tuple(periods._fact_notes([(1, f)])),
    )


def diluted_shares(series: MetricSeries, end: date) -> Figure:
    """Diluted weighted-average shares for the latest period ending at ``end``.

    The shortest period wins (the latest quarter), since it is the most current
    average. FD-3 uses this only as a cross-check.
    """
    at_end = [f for f in series.facts if f.end == end]
    if not at_end:
        return missing("diluted weighted-average shares", "shares", f"not reported for a period ending {end}")
    f = min(at_end, key=lambda f: f.days or 0)
    return Figure(
        name="diluted weighted-average shares", value=f.value, unit="shares",
        formula=f"diluted weighted-average shares, {f.start}..{f.end}", as_of=f.end, start=f.start,
        facts=((1, f),),
    )


def share_check(cover: Figure, diluted: Figure) -> Figure:
    """FD-3: flag when cover-page and diluted shares differ by more than 3%."""
    if not (cover.ok and diluted.ok):
        return missing("share count check", "ratio", "needs both cover-page and diluted shares",
                       inputs=(cover, diluted))
    diff = diluted.value / cover.value - 1
    notes = ()
    if abs(diff) > SHARE_COUNT_TOLERANCE:
        notes = (f"Diluted weighted-average shares differ from cover-page shares by {diff:+.1%} "
                 f"(more than {SHARE_COUNT_TOLERANCE:.0%}); check which should drive the math (FD-3)",)
    return Figure(name="share count check", value=diff, unit="ratio",
                  formula="diluted weighted-average / cover-page shares - 1", inputs=(cover, diluted),
                  notes=notes)


def equity_value(price: Figure, shares: Figure) -> Figure:
    inputs = (price, shares)
    for f in inputs:
        if not f.ok:
            return missing("equity value", "USD", f"{f.name} n/a ({f.reason})", inputs=inputs)
    return Figure(name="equity value", value=price.value * shares.value, unit="USD",
                  formula="share price x cover-page shares outstanding (FD-3)",
                  as_of=price.as_of, inputs=inputs)
