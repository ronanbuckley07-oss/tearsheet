"""Unlevered discounted cash flow (FD-11).

The idea in one line: a business is worth the cash it will generate for all of
its investors (debt and equity), discounted back at the return those investors
require (WACC). Then the FD-2 bridge turns that enterprise value into a share
price, exactly as FD-8 does for comps.

    Unlevered free cash flow (UFCF) = EBIT x (1 - tax rate) + D&A - capex - increase in NWC
    WACC = E/(D+E) x cost of equity + D/(D+E) x cost of debt x (1 - tax rate)
    cost of equity (CAPM) = risk-free rate + beta x equity risk premium
    terminal value (perpetuity growth) = UFCF year 5 x (1 + g) / (WACC - g)
    EV = sum of discounted UFCF + discounted terminal value

Historical figures come from 10-Ks like the rest of the app. The forecast is
made of *assumptions*: each one starts from the company's own history (or a
stated convention) and the user can change it. Every assumption is a Figure
whose formula says where its value came from, so the Sources panel can show
it, and an edited value says "entered by user".

Stock-based comp stays inside EBIT as a real expense (FD-1), so it is not
added back to free cash flow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from engine import periods
from engine.comps import equity_from_ev, price_from_equity
from engine.metrics import CompanyMetrics, combine
from engine.periods import Figure, missing
from engine.xbrl import MetricSeries

YEARS = 5
HISTORY_YEARS = 3
# FD-11 conventions (editable in the UI):
TERMINAL_GROWTH = 0.025  # long-run nominal growth, roughly inflation plus a little real growth
EQUITY_RISK_PREMIUM = 0.05
BETA_RAW_WEIGHT = 0.67  # adjusted beta = 0.67 x raw + 0.33
STATUTORY_TAX = 0.21  # US federal rate, used only when the effective rate is unusable
TAX_RANGE = (0.0, 0.5)
# Sensitivity grid (FD-11): steps around the base WACC and terminal growth.
WACC_STEPS = (-0.01, -0.005, 0.0, 0.005, 0.01)
GROWTH_STEPS = (-0.01, -0.005, 0.0, 0.005, 0.01)
FOOTBALL_GROWTH_STEPS = (-0.005, 0.0, 0.005)  # bar = WACC +/-1%, g +/-0.5%

# Assumption keys, in the order the UI shows them.
GROWTH_KEYS = tuple(f"growth_{i}" for i in range(1, YEARS + 1))
OPERATING_KEYS = ("ebit_margin", "da_pct", "capex_pct", "nwc_pct", "tax_rate")
WACC_KEYS = ("risk_free", "beta", "erp", "cost_of_debt")
LABELS = {
    **{k: f"Revenue growth, year {i}" for i, k in enumerate(GROWTH_KEYS, 1)},
    "ebit_margin": "EBIT margin", "da_pct": "D&A % of revenue", "capex_pct": "Capex % of revenue",
    "nwc_pct": "Net working capital % of revenue", "tax_rate": "Tax rate",
    "risk_free": "Risk-free rate", "beta": "Beta", "erp": "Equity risk premium",
    "cost_of_debt": "Pre-tax cost of debt", "terminal_growth": "Terminal growth rate",
}
UNITS = {k: ("x" if k == "beta" else "ratio") for k in LABELS}


# ---- what the DCF reads from filings and markets ---------------------------------------


@dataclass
class FiscalYear:
    end: date
    revenue: Figure
    ebit: Figure
    d_and_a: Figure
    capex: Figure
    income_tax: Figure
    pretax_income: Figure
    nwc: Figure


@dataclass
class Base:
    ltm_end: date
    years: list[FiscalYear]  # most recent first, up to HISTORY_YEARS
    ltm_interest: Figure
    risk_free: Figure
    beta: Figure
    peer_median_ev_ebitda: Figure | None = None
    notes: list[str] = field(default_factory=list)


def build_base(series: dict[str, MetricSeries], m: CompanyMetrics, risk_free: Figure, beta: Figure) -> Base:
    ends = periods.latest_fiscal_year_ends(series["revenue"], m.ltm_end, n=HISTORY_YEARS)
    years = []
    for end in ends:
        fy = {k: periods.fiscal_year(series[k], end)
              for k in ("revenue", "operating_income", "d_and_a", "capex", "income_tax", "pretax_income")}
        years.append(FiscalYear(end, fy["revenue"], fy["operating_income"], fy["d_and_a"], fy["capex"],
                                fy["income_tax"], fy["pretax_income"], net_working_capital(series, end)))
    return Base(ltm_end=m.ltm_end, years=years,
                ltm_interest=periods.ltm(series["interest_expense"], m.ltm_end),
                risk_free=risk_free, beta=beta)


def net_working_capital(series: dict[str, MetricSeries], end: date) -> Figure:
    """Operating NWC at a fiscal year end (FD-11).

    NWC = (current assets - cash - short-term investments)
        - (current liabilities - current debt - short-term borrowings - commercial paper
           - current finance leases)
    Cash and debt are taken out because the DCF values them separately in the
    EV bridge. A current debt item the company doesn't report counts as 0 (FD-10 Q4).
    """
    def bal(key: str, optional: bool) -> Figure:
        f = periods.balance_at(series[key], end, None)
        if not f.ok and optional:
            return Figure(name=key, value=0.0, unit="USD", formula="not reported -> 0", as_of=end)
        return f

    parts = [(1, bal("current_assets", False)), (-1, bal("cash", False)),
             (-1, bal("short_term_investments", True)), (-1, bal("current_liabilities", False)),
             (1, bal("debt_long_term_current", True)), (1, bal("debt_short_term_borrowings", True)),
             (1, bal("debt_commercial_paper", True)), (1, bal("finance_lease_current", True))]
    return combine("net working capital", parts, "USD",
                   "(current assets - cash - short-term investments) - (current liabilities - current debt "
                   "- short-term borrowings - commercial paper - current finance leases) (FD-11)", as_of=end)


# ---- default assumptions ---------------------------------------------------------------


def _assumption(key: str, value: float | None, formula: str, inputs=(), reason: str | None = None,
                notes: tuple[str, ...] = ()) -> Figure:
    if value is None:
        return missing(LABELS[key], UNITS[key], reason or "no data", inputs=tuple(inputs), notes=notes)
    return Figure(name=LABELS[key], value=value, unit=UNITS[key], formula=formula,
                  inputs=tuple(inputs), notes=notes)


def _ratio_of_sums(key: str, base: Base, num: str, den: str, what: str) -> Figure:
    """Total of ``num`` over total of ``den`` across the fiscal years where both exist."""
    used = [y for y in base.years if getattr(y, num).ok and getattr(y, den).ok]
    if not used:
        return _assumption(key, None, "", reason=f"no fiscal year with both {num} and {den} reported; enter it")
    n = sum(getattr(y, num).value for y in used)
    d = sum(getattr(y, den).value for y in used)
    if d == 0:
        return _assumption(key, None, "", reason=f"{den} totals 0; enter it")
    span = f"FY{used[-1].end.year}-FY{used[0].end.year}" if len(used) > 1 else f"FY{used[0].end.year}"
    notes = () if len(used) == HISTORY_YEARS else (
        f"{LABELS[key]}: based on {len(used)} fiscal year(s), not {HISTORY_YEARS}",)
    return _assumption(key, n / d, f"{len(used)}-year total {what}, {span} 10-Ks (FD-11)",
                       inputs=[getattr(y, a) for y in used for a in (num, den)], notes=notes)


def default_assumptions(base: Base, m: CompanyMetrics) -> dict[str, Figure]:
    F = m.figures
    a: dict[str, Figure] = {}

    # Terminal growth first: the revenue growth path fades toward it.
    a["terminal_growth"] = _assumption("terminal_growth", TERMINAL_GROWTH,
                                       "FD-11 convention: long-run nominal growth")
    g1 = F["revenue_growth_ltm"]
    if not g1.ok:
        g1 = F["revenue_growth_fy"]
    if g1.ok:
        # Year 1 = latest growth; straight-line fade to terminal growth by year 5.
        for i, k in enumerate(GROWTH_KEYS):
            v = g1.value + (TERMINAL_GROWTH - g1.value) * i / (YEARS - 1)
            a[k] = _assumption(k, v, f"{g1.name} {g1.value:.1%} fading in a straight line to "
                                     f"{TERMINAL_GROWTH:.1%} by year {YEARS} (FD-11)", inputs=[g1])
    else:
        for k in GROWTH_KEYS:
            a[k] = _assumption(k, None, "", reason=f"no historical growth ({g1.reason}); enter it", inputs=[g1])

    a["ebit_margin"] = _ratio_of_sums("ebit_margin", base, "ebit", "revenue", "EBIT / total revenue")
    a["da_pct"] = _ratio_of_sums("da_pct", base, "d_and_a", "revenue", "D&A / total revenue")
    a["capex_pct"] = _ratio_of_sums("capex_pct", base, "capex", "revenue", "capex / total revenue")

    nwc = [(y.nwc, y.revenue) for y in base.years if y.nwc.ok and y.revenue.ok and y.revenue.value]
    if nwc:
        v = sum(n.value / r.value for n, r in nwc) / len(nwc)
        a["nwc_pct"] = _assumption("nwc_pct", v, f"average of NWC / revenue at {len(nwc)} fiscal year ends (FD-11)",
                                   inputs=[f for pair in nwc for f in pair])
    else:
        a["nwc_pct"] = _assumption("nwc_pct", None, "", reason="NWC not available at any fiscal year end; enter it",
                                   inputs=[y.nwc for y in base.years])

    tax = _ratio_of_sums("tax_rate", base, "income_tax", "pretax_income", "tax expense / pretax income")
    lo, hi = TAX_RANGE
    if not tax.ok or not lo <= tax.value <= hi:
        why = tax.reason if not tax.ok else f"effective rate {tax.value:.1%} is outside {lo:.0%}-{hi:.0%}"
        tax = _assumption("tax_rate", STATUTORY_TAX, "21% US federal statutory rate (FD-11 fallback)",
                          inputs=tax.inputs, notes=(f"Tax rate: {why}; using the 21% statutory rate",))
    a["tax_rate"] = tax

    a["risk_free"] = _assumption("risk_free", base.risk_free.value, base.risk_free.formula,
                                 inputs=[base.risk_free], reason=f"{base.risk_free.reason}; enter it")
    # Adjusted beta (the Bloomberg / Blume convention): betas drift toward 1 over
    # time, so the forecast beta is pulled two-thirds raw, one-third toward 1.
    raw = base.beta
    a["beta"] = _assumption("beta", None if raw.value is None else BETA_RAW_WEIGHT * raw.value + 1 - BETA_RAW_WEIGHT,
                            f"adjusted beta = {BETA_RAW_WEIGHT:.2f} x raw {raw.value or 0:.2f} + {1 - BETA_RAW_WEIGHT:.2f} "
                            "(Bloomberg/Blume convention, FD-11)", inputs=[raw], reason=f"{raw.reason}; enter it")
    a["erp"] = _assumption("erp", EQUITY_RISK_PREMIUM, "FD-11 convention (editable judgment input)")

    debt, interest = F["total_debt"], base.ltm_interest
    if debt.ok and debt.value == 0:
        a["cost_of_debt"] = _assumption("cost_of_debt", 0.0, "no debt, so debt has 0 weight in WACC",
                                        inputs=[debt])
    elif debt.ok and interest.ok and interest.value > 0:
        a["cost_of_debt"] = _assumption("cost_of_debt", interest.value / debt.value,
                                        "LTM interest expense / total debt at the LTM date (FD-11)",
                                        inputs=[interest, debt])
    else:
        why = (f"total debt n/a ({debt.reason})" if not debt.ok else
               "the filings don't report interest expense for the last twelve months")
        a["cost_of_debt"] = _assumption("cost_of_debt", None, "", inputs=[debt, interest],
                                        reason=f"{why}; enter it (for example the yield on the company's bonds)")
    return a


def edited(key: str, value: float, default: Figure) -> Figure:
    """An assumption the user changed in the UI."""
    was = "n/a" if default.value is None else (
        f"{default.value:.2f}" if UNITS[key] == "x" else f"{default.value:.2%}")
    return Figure(name=LABELS[key], value=value, unit=UNITS[key],
                  formula=f"entered by user (default was {was})", inputs=(default,))


# ---- the model --------------------------------------------------------------------------


@dataclass
class Year:
    n: int
    revenue: float
    growth: float
    ebit: float
    taxes: float
    nopat: float
    d_and_a: float
    capex: float
    nwc_change: float
    ufcf: float
    period: float  # discount period in years (n, or n - 0.5 mid-year)
    discount_factor: float
    pv: float


@dataclass
class Result:
    years: list[Year]
    wacc: Figure
    cost_of_equity: Figure
    terminal_value: Figure
    pv_terminal: Figure
    pv_fcf: Figure
    enterprise_value: Figure
    equity_value: Figure
    share_price: Figure
    tv_share_of_ev: float | None
    implied_exit_multiple: float | None  # TV / year-5 EBITDA
    exit_price: Figure  # cross-check: peer median EV/EBITDA x year-5 EBITDA
    implied_growth_from_exit: float | None
    reason: str | None = None  # why the whole DCF is n/a
    notes: list[str] = field(default_factory=list)  # sanity flags on the assumptions


def wacc(a: dict[str, Figure], m: CompanyMetrics) -> tuple[Figure, Figure]:
    """(WACC, cost of equity). Weights: market equity value (FD-3) and total debt (FD-2)."""
    rf, beta, erp = a["risk_free"], a["beta"], a["erp"]
    for f in (rf, beta, erp):
        if not f.ok:
            na = missing("cost of equity", "ratio", f"{f.name} n/a ({f.reason})")
            return missing("WACC", "ratio", na.reason, inputs=(na,)), na
    ke = Figure(name="cost of equity", value=rf.value + beta.value * erp.value, unit="ratio",
                formula=f"CAPM: risk-free {rf.value:.2%} + beta {beta.value:.2f} x ERP {erp.value:.2%}",
                inputs=(rf, beta, erp))
    E, D, kd, t = m.figures["equity_value"], m.figures["total_debt"], a["cost_of_debt"], a["tax_rate"]
    for f in (E, D, t):
        if not f.ok:
            return missing("WACC", "ratio", f"{f.name} n/a ({f.reason})", inputs=(ke, f)), ke
    if D.value > 0 and not kd.ok:
        return missing("WACC", "ratio", f"{kd.name} n/a ({kd.reason})", inputs=(ke, kd)), ke
    we = E.value / (E.value + D.value)
    kd_v = kd.value if kd.ok else 0.0
    w = we * ke.value + (1 - we) * kd_v * (1 - t.value)
    return Figure(
        name="WACC", value=w, unit="ratio",
        formula=(f"{we:.1%} equity x {ke.value:.2%} + {1 - we:.1%} debt x {kd_v:.2%} x (1 - {t.value:.1%} tax) "
                 "(weights: market equity value, total debt)"),
        inputs=(ke, E, D, kd, t)), ke


def project(a: dict[str, Figure], revenue0: float, w: float, mid_year: bool) -> list[Year]:
    v = {k: f.value for k, f in a.items()}
    years, prev = [], revenue0
    for n, gk in enumerate(GROWTH_KEYS, 1):
        rev = prev * (1 + v[gk])
        ebit = rev * v["ebit_margin"]
        taxes = max(ebit, 0.0) * v["tax_rate"]  # no tax credit on an operating loss (no NOL modeling)
        da, capex = rev * v["da_pct"], rev * v["capex_pct"]
        dnwc = (rev - prev) * v["nwc_pct"]  # NWC stays at a fixed % of revenue
        ufcf = ebit - taxes + da - capex - dnwc
        period = n - 0.5 if mid_year else float(n)
        df = 1 / (1 + w) ** period
        years.append(Year(n, rev, v[gk], ebit, taxes, ebit - taxes, da, capex, dnwc, ufcf, period, df, ufcf * df))
        prev = rev
    return years


def run(a: dict[str, Figure], m: CompanyMetrics, base: Base, mid_year: bool = False,
        wacc_override: float | None = None, growth_override: float | None = None) -> Result:
    F = m.figures
    w_fig, ke = wacc(a, m)
    if wacc_override is not None:
        w_fig = Figure("WACC", wacc_override, "ratio", "sensitivity case", inputs=(w_fig,))
    g_fig = a["terminal_growth"]
    if growth_override is not None:
        g_fig = Figure(LABELS["terminal_growth"], growth_override, "ratio", "sensitivity case", inputs=(g_fig,))

    def na(reason: str) -> Result:
        def x(name, unit="USD"):
            return missing(name, unit, reason)
        return Result([], w_fig, ke, x("terminal value"), x("PV of terminal value"), x("PV of free cash flows"),
                      x("DCF enterprise value"), x("DCF equity value"), x("DCF share price", "USD/share"),
                      None, None, x("exit-multiple share price", "USD/share"), None, reason=reason)

    needed = [*GROWTH_KEYS, *OPERATING_KEYS]
    bad = [a[k] for k in needed if not a[k].ok] + [f for f in (w_fig, g_fig, F["ltm_revenue"]) if not f.ok]
    if bad:
        return na("; ".join(f"{f.name} n/a ({f.reason})" for f in bad))
    w, g = w_fig.value, g_fig.value
    if w <= g:
        return na(f"WACC {w:.2%} is not above terminal growth {g:.2%}; the perpetuity formula breaks (NM)")

    rev0 = F["ltm_revenue"]
    years = project(a, rev0.value, w, mid_year)
    last = years[-1]
    assumptions = tuple(a[k] for k in needed)
    pv_fcf = Figure("PV of free cash flows", sum(y.pv for y in years), "USD",
                    f"sum of {YEARS} years of UFCF, each / (1 + WACC)^period"
                    + (" (mid-year convention)" if mid_year else " (end-of-year discounting)"),
                    inputs=(rev0, w_fig, *assumptions))
    # Mid-year: the perpetuity's cash also arrives through the year, so it is
    # discounted from year 4.5 (the Rosenbaum & Pearl convention).
    tv_period = YEARS - 0.5 if mid_year else float(YEARS)
    if last.ufcf <= 0:
        return na(f"year-{YEARS} free cash flow is negative ({last.ufcf / 1e9:,.1f}bn); "
                  "a perpetuity of it isn't a valuation (NM)")
    tv = Figure("terminal value", last.ufcf * (1 + g) / (w - g), "USD",
                f"UFCF year {YEARS} x (1 + {g:.2%}) / (WACC {w:.2%} - {g:.2%})", inputs=(w_fig, g_fig))
    pv_tv = Figure("PV of terminal value", tv.value / (1 + w) ** tv_period, "USD",
                   f"terminal value / (1 + WACC)^{tv_period:g}", inputs=(tv,))
    ev = Figure("DCF enterprise value", pv_fcf.value + pv_tv.value, "USD",
                "PV of free cash flows + PV of terminal value", as_of=m.ltm_end, inputs=(pv_fcf, pv_tv))
    eq = equity_from_ev(ev, m, "DCF equity value")
    px = price_from_equity(eq, m, "DCF share price")

    ebitda5 = last.ebit + last.d_and_a
    implied_mult = tv.value / ebitda5 if ebitda5 > 0 else None
    exit_px, implied_g = _exit_cross_check(base, m, years, w, ebitda5)
    return Result(years, w_fig, ke, tv, pv_tv, pv_fcf, ev, eq, px, pv_tv.value / ev.value, implied_mult,
                  exit_px, implied_g, notes=sanity_notes(a, pv_tv.value / ev.value))


def sanity_notes(a: dict[str, Figure], tv_share: float) -> list[str]:
    """Flags for assumptions that usually deserve a second look. They change nothing."""
    v = {k: f.value for k, f in a.items()}
    notes = []
    if v["da_pct"] > 0 and v["capex_pct"] > 1.5 * v["da_pct"]:
        notes.append(
            f"Capex ({v['capex_pct']:.1%} of revenue) is {v['capex_pct'] / v['da_pct']:.1f}x D&A "
            f"({v['da_pct']:.1%}). The terminal value assumes that spending continues forever while growth "
            "is only the terminal rate; in a steady state capex usually sits close to D&A. If today's capex is "
            "a temporary build-out, lower it.")
    if abs(v["nwc_pct"]) > 0.5:
        notes.append(f"Net working capital is {v['nwc_pct']:.0%} of revenue, which is unusual. Check whether "
                     "current liabilities hold debt the filing doesn't tag as debt.")
    if tv_share > 0.85:
        notes.append(f"{tv_share:.0%} of the value comes from the terminal value, so the answer rests mostly "
                     "on WACC and terminal growth.")
    return notes


def _exit_cross_check(base: Base, m: CompanyMetrics, years: list[Year], w: float, ebitda5: float):
    """Terminal value from the peer median EV/EBITDA instead of perpetuity growth."""
    mult = base.peer_median_ev_ebitda
    if mult is None or not mult.ok:
        return missing("exit-multiple share price", "USD/share", "no peer median EV/EBITDA"), None
    if ebitda5 <= 0:
        return missing("exit-multiple share price", "USD/share", f"year-{YEARS} EBITDA is not positive"), None
    tv = mult.value * ebitda5
    ev = Figure("DCF EV (exit multiple)", sum(y.pv for y in years) + tv / (1 + w) ** YEARS, "USD",
                f"PV of free cash flows + peer median {mult.value:.1f}x x year-{YEARS} EBITDA / (1 + WACC)^{YEARS}",
                inputs=(mult,))
    px = price_from_equity(equity_from_ev(ev, m, "DCF equity value (exit multiple)"), m,
                           "DCF share price (exit multiple)")
    u = years[-1].ufcf
    implied_g = (tv * w - u) / (tv + u)  # solves tv = u(1+g)/(w-g) for g
    return px, implied_g


def sensitivity(a: dict[str, Figure], m: CompanyMetrics, base: Base, mid_year: bool,
                wacc_steps=WACC_STEPS, growth_steps=GROWTH_STEPS) -> tuple[list[float], list[float], list[list]]:
    """Share price for each (WACC, terminal growth) pair: rows are WACC, columns growth."""
    w0, _ = wacc(a, m)
    g0 = a["terminal_growth"]
    if not w0.ok or not g0.ok:
        return [], [], []
    ws = [w0.value + s for s in wacc_steps]
    gs = [g0.value + s for s in growth_steps]
    grid = [[run(a, m, base, mid_year, wacc_override=w, growth_override=g).share_price for g in gs] for w in ws]
    return ws, gs, grid


def football_bar(a: dict[str, Figure], m: CompanyMetrics, base: Base, mid_year: bool) -> dict:
    """FD-11: the DCF bar spans WACC +/-1% and terminal growth +/-0.5%."""
    label = "DCF (WACC ±1%, g ±0.5%)"
    _, _, grid = sensitivity(a, m, base, mid_year, wacc_steps=(-0.01, 0.0, 0.01),
                             growth_steps=FOOTBALL_GROWTH_STEPS)
    vals = [f.value for row in grid for f in row if f.ok]
    if len(vals) < 9:
        reason = next((f.reason for row in grid for f in row if not f.ok), "DCF n/a")
        return {"label": label, "low": None, "high": None, "reason": reason}
    return {"label": label, "low": min(vals), "high": max(vals), "reason": None}
