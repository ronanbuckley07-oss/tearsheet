"""Learn mode: what every number means, and what moves when an input changes (FD-14).

No LLM (CLAUDE.md rule 1). Every explanation is a fixed template:

  * ``CONCEPTS`` holds the general meaning of each kind of number, what drives it
    and what it feeds. That text is the same for every company.
  * ``explain()`` fills a concept with one company's actual figures, so the reader
    sees "NVDA's EV is 38x its EBITDA" rather than a textbook sentence.
  * The impact functions (``ripple``, ``tornado``, ``nudge``) rerun the real DCF
    engine with one input changed, so every "if this moves, that moves" number
    is computed, not described.

Nothing here changes a valuation. It only reads figures the engine already built
and reruns ``dcf.run`` on copies of the assumptions.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from engine import dcf
from engine.metrics import CompanyMetrics
from engine.periods import Figure
from engine.pitch import _usd

# FD-14: the standard nudge used everywhere in learn mode, so every bar and every
# "if you raise it" line reads in the same unit.
PCT_STEP = 0.01  # one percentage point for every % assumption
BETA_STEP = 0.10
TERMINAL_STEP = 0.005  # terminal growth moves in half points, as in the sensitivity table


# ---- formatting -----------------------------------------------------------------------


def money(v: float | None) -> str:
    """Like the tearsheet's $bn format, with one more decimal under $100bn so the walked-through
    arithmetic visibly adds up."""
    if v is None:
        return "n/a"
    a = abs(v)
    if 1e9 <= a < 1e11:
        return ("-" if v < 0 else "") + f"${a / 1e9:,.2f}bn"
    return _usd(v)


def pct(v: float | None, places: int = 1) -> str:
    return "n/a" if v is None else f"{v:.{places}%}"


def mult(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.1f}x"


def per_share(v: float | None) -> str:
    return "n/a" if v is None else ("-" if v < 0 else "") + f"${abs(v):,.2f}"


def value_text(f: Figure | None) -> str:
    if f is None:
        return "n/a"
    if f.value is None:
        return "NM" if f.nm else "n/a"
    return {"USD": money, "USD/share": per_share, "x": (lambda v: f"{v:.2f}" if f.name == "Beta" else mult(v)),
            "ratio": pct, "shares": lambda v: f"{v / 1e6:,.0f}m shares"}.get(f.unit, lambda v: f"{v:,.4g}")(f.value)


def signed(v: float, unit: str) -> str:
    sign = "+" if v >= 0 else "-"
    if unit == "USD":
        return sign + money(abs(v))
    if unit == "USD/share":
        return f"{sign}${abs(v):,.2f}"
    if unit == "ratio":
        return f"{sign}{abs(v) * 100:.2f}pp"
    if unit == "x":
        return f"{sign}{abs(v):.1f}x"
    return f"{sign}{abs(v):,.4g}"


# ---- the concepts -----------------------------------------------------------------------


@dataclass(frozen=True)
class Concept:
    title: str
    what: str  # what the number is, in plain words
    drivers: str  # what makes it go up or down
    feeds: str  # what it changes downstream


C = Concept
CONCEPTS: dict[str, Concept] = {
    # market and the EV bridge
    "price": C("Share price",
               "What one share last traded for on the stock market. It is the market's running vote on what the "
               "company is worth per share.",
               "News, earnings, interest rates and sentiment. Nothing in the filings sets it.",
               "Price x shares = equity value (market cap), which feeds enterprise value and every market multiple "
               "(EV/Revenue, EV/EBITDA, P/E). A higher price makes the company look more expensive against peers."),
    "shares_outstanding": C("Shares outstanding",
                            "How many shares exist, taken from the cover page of the latest 10-K or 10-Q (FD-3).",
                            "Buybacks reduce it; stock issuance, option exercises and stock comp increase it.",
                            "Divides every equity value into a per-share value. Fewer shares means each one owns more "
                            "of the same business, so per-share values rise."),
    "equity_value": C("Equity value (market cap)",
                      "What the market says all the shares are worth together: share price x shares outstanding.",
                      "The share price and the share count.",
                      "Starting point of the EV bridge, the numerator of P/E, and the equity weight in WACC."),
    "total_debt": C("Total debt",
                    "Everything the company has borrowed: bonds, loans, commercial paper and finance leases (FD-2). "
                    "Operating leases are left out.",
                    "New borrowing raises it; repayments lower it.",
                    "Added in the EV bridge (a buyer of the whole company takes on the debt). In a DCF or comps "
                    "valuation it is subtracted on the way from EV to equity, so more debt means less value per share. "
                    "It is also the debt weight in WACC."),
    "cash": C("Cash and equivalents",
              "Cash on the balance sheet at the latest quarter end.",
              "Cash generated by the business, minus capex, buybacks, dividends, acquisitions and debt repayment.",
              "Subtracted in the EV bridge (a buyer gets it back), and added back when going from EV to equity."),
    "short_term_investments": C("Short-term investments",
                                "Marketable securities the company could turn into cash quickly. Treated like cash.",
                                "Treasury decisions: moving cash into and out of short-dated securities.",
                                "Subtracted in the EV bridge alongside cash."),
    "preferred_stock": C("Preferred stock",
                         "A claim that ranks ahead of common shareholders. Most tech companies have none.",
                         "Issuance or redemption of preferred shares.",
                         "Added to EV and subtracted when going from EV to common equity."),
    "noncontrolling_interest": C("Noncontrolling interest",
                                 "The slice of subsidiaries the company consolidates but doesn't fully own.",
                                 "Partial acquisitions or selling stakes in subsidiaries.",
                                 "Added to EV because the company's revenue and EBITDA include 100% of those "
                                 "subsidiaries; subtracted again on the way back to common equity."),
    "enterprise_value": C("Enterprise value (EV)",
                          "The price of the whole operating business, whoever financed it: equity value + debt + "
                          "preferred + noncontrolling interest - cash - short-term investments (FD-2).",
                          "The share price (through equity value), borrowing and cash balances.",
                          "Numerator of EV/Revenue and EV/EBITDA. Because EV covers debt and equity holders, it is "
                          "matched with profit before interest (EBITDA), not net income."),
    "net_debt": C("Net debt",
                  "Debt minus cash and short-term investments. Negative means the company holds more cash than debt "
                  "(a net cash position).",
                  "Borrowing, repayment and cash build-up.",
                  "Net debt / EBITDA (leverage), and the gap between EV and equity value."),
    "net_debt_ebitda": C("Net debt / EBITDA (leverage)",
                         "Roughly how many years of EBITDA it would take to pay off the net debt. Under 1x is light; "
                         "above 3-4x is heavily levered. Negative means net cash.",
                         "More debt or less cash raises it; higher EBITDA lowers it.",
                         "Lenders and rating agencies watch it. In comps it explains why two companies at the same "
                         "EV/EBITDA can carry very different equity risk."),
    # income statement
    "revenue": C("Revenue",
                 "Total sales in the period, before any costs.",
                 "Volume sold x price, new products, acquisitions, currency.",
                 "Everything else scales off it: margins divide by it, EV/Revenue values it, and every DCF line "
                 "(EBIT, D&A, capex, working capital) is forecast as a % of it."),
    "revenue_growth": C("Revenue growth",
                        "How much revenue rose versus the same period a year earlier.",
                        "Demand, pricing, market share, acquisitions, and the base effect of the prior year.",
                        "Investors pay higher multiples for faster growth, and the DCF's year-1 growth starts from "
                        "this number (FD-11)."),
    "operating_income": C("Operating income (EBIT)",
                          "Profit from running the business: revenue minus cost of goods, R&D, sales and admin, "
                          "and D&A. Before interest and taxes. Stock comp stays in as a real cost (FD-1).",
                          "Revenue growth and cost control (operating leverage).",
                          "EBIT + D&A = EBITDA. In the DCF, EBIT x (1 - tax) = NOPAT, the start of free cash flow."),
    "d_and_a": C("D&A (depreciation and amortization)",
                 "The accounting charge that spreads the cost of equipment, buildings and acquired intangibles over "
                 "their lives. No cash leaves the company when it's booked.",
                 "Past capex and acquisitions: the more a company has invested, the bigger its D&A.",
                 "Added back to EBIT to get EBITDA, and added back in free cash flow because it isn't cash."),
    "ebitda": C("EBITDA",
                "Earnings before interest, taxes, depreciation and amortization = operating income + D&A (FD-1). "
                "A rough proxy for the cash the operations throw off before investment, taxes and financing.",
                "Revenue and operating costs.",
                "The most-used valuation base in banking: EV/EBITDA, leverage (net debt / EBITDA), and the "
                "comps-implied valuation."),
    "ebitda_margin": C("EBITDA margin",
                       "EBITDA as a share of revenue: cents of EBITDA per dollar of sales.",
                       "Pricing power, cost structure, mix, scale.",
                       "Higher margins usually earn higher multiples. With revenue, it sets EBITDA, which the "
                       "comps valuation multiplies."),
    "net_income": C("Net income",
                    "Profit left for shareholders after every cost, interest and taxes.",
                    "Operating profit, interest cost, tax rate, one-off gains and losses.",
                    "Denominator of P/E. Not used in the DCF, which works from EBIT so financing doesn't count twice."),
    "sbc": C("Stock-based compensation",
             "Pay given to employees in shares or options. Non-cash, but it dilutes shareholders.",
             "Hiring, share price (grants are sized in dollars) and pay policy.",
             "Kept inside EBIT and EBITDA as a real expense and not added back (FD-1), so the multiples here are "
             "stricter than the 'adjusted' figures many companies report."),
    # multiples
    "ev_revenue": C("EV/Revenue",
                    "Enterprise value divided by LTM revenue: what the market pays per dollar of sales.",
                    "The share price (through EV) and revenue. High-growth or high-margin businesses trade higher.",
                    "Used to value companies with little or negative EBITDA. Peer quartiles x the target's revenue "
                    "give the EV/Revenue implied valuation (FD-8)."),
    "ev_ebitda": C("EV/EBITDA",
                   "Enterprise value divided by LTM EBITDA: how many years of today's EBITDA a buyer of the whole "
                   "business is paying for. The workhorse multiple in banking.",
                   "The share price (through EV), debt and cash, and EBITDA. Growth and margins justify a higher one.",
                   "Peer quartiles x the target's EBITDA give the main implied valuation range (FD-8), and the peer "
                   "median is the DCF's exit-multiple cross-check."),
    "pe": C("P/E",
            "Equity value divided by net income (the same as price / earnings per share): what shareholders pay "
            "per dollar of profit.",
            "Share price and net income; interest and taxes affect it, unlike EV multiples.",
            "Shown for context. It is not used for the implied range because leverage distorts it."),
    "price_vs_52w_high": C("Distance from the 52-week high",
                           "Current price versus the highest price in the past year.",
                           "Recent share price moves.",
                           "A quick read on momentum: a stock far below its high may be out of favour, or cheap."),
    "share_count_check": C("Share count cross-check",
                           "Cover-page shares versus diluted weighted-average shares from the income statement. "
                           "A gap above 3% gets flagged (FD-3).",
                           "Buybacks, issuance or a big option overhang between the two dates.",
                           "Nothing is recomputed; it tells you how much to trust the per-share numbers."),
    "diluted_shares": C("Diluted weighted-average shares",
                        "The average share count over the period, including options and RSUs that would convert.",
                        "Buybacks, issuance, and how far in the money options are.",
                        "Only used as a cross-check on the cover-page count (FD-3)."),
    # comps statistics and implied valuation
    "peer_stat": C("Peer statistic",
                   "A summary of the peer column: 25th percentile, median, mean or 75th percentile. Only usable "
                   "(non-NM) peer values count and the target is left out (FD-7).",
                   "Which peers you include. One outlier moves the mean a lot and the median little, which is why "
                   "the median is the headline.",
                   "The 25th-75th range sets the implied valuation bars; the median sets the midpoint."),
    "implied": C("Implied valuation (comps)",
                 "What the target would be worth if it traded like its peers: target LTM metric x peer multiple = "
                 "implied EV, then minus debt, plus cash = implied equity value, divided by shares (FD-8).",
                 "The peer multiples (which peers you pick) and the target's own EBITDA or revenue.",
                 "The comps bars on the football field."),
    # DCF assumptions
    "growth": C("Revenue growth (forecast)",
                "How fast revenue grows each forecast year. By default year 1 is the latest actual growth and it "
                "fades in a straight line to the terminal rate by year 5 (FD-11).",
                "Your view of the market, share gains and pricing.",
                "Revenue in that year and every year after, so EBIT, D&A, capex and the working-capital build all "
                "scale with it. It also changes the terminal value, which grows from year 5. It doesn't touch WACC."),
    "ebit_margin": C("EBIT margin (forecast)",
                     "Operating profit per dollar of revenue in each forecast year. Default: 3-year historical "
                     "total EBIT / total revenue (FD-11).",
                     "Pricing, cost discipline, scale benefits, competition.",
                     "EBIT in every year, so taxes, NOPAT and free cash flow; and the terminal value through year 5."),
    "da_pct": C("D&A % of revenue",
                "Depreciation and amortization as a share of revenue. Default: 3-year historical ratio.",
                "How capital-heavy the business is.",
                "D&A is already inside EBIT, so on its own it only changes EBITDA (and the implied exit multiple). "
                "It also caps terminal-year capex under the steady-state toggle."),
    "capex_pct": C("Capex % of revenue",
                   "Spending on property and equipment, as a share of revenue. Default: 3-year historical ratio.",
                   "Expansion plans (data centers, fabs, stores) versus maintenance.",
                   "Subtracted from free cash flow every year. With steady state on, the terminal year uses capex = "
                   "D&A, so capex mainly moves the five forecast years."),
    "nwc_pct": C("Net working capital % of revenue",
                 "Operating working capital (receivables + inventory - payables and other operating liabilities) "
                 "as a share of revenue. Default: average of the last 3 fiscal year ends (FD-11).",
                 "Payment terms with customers and suppliers, inventory levels.",
                 "Growing companies tie up this % of each new dollar of revenue, so the increase in NWC is a cash "
                 "outflow. A higher % lowers free cash flow more the faster the company grows."),
    "tax_rate": C("Tax rate",
                  "Tax on operating profit. Default: 3-year effective rate from the filings, or the 21% statutory "
                  "rate if that is unusable (FD-11).",
                  "Where profits are earned, tax credits, legislation.",
                  "Taxes on EBIT (so NOPAT and free cash flow), and the after-tax cost of debt in WACC: interest is "
                  "tax-deductible, so a higher rate makes debt slightly cheaper."),
    "risk_free": C("Risk-free rate",
                   "The yield on the 10-year US Treasury: what an investor earns with no default risk.",
                   "Fed policy, inflation expectations, the bond market.",
                   "The base of the cost of equity (CAPM), so WACC and every discount factor. Higher rates mean "
                   "future cash is worth less today."),
    "beta": C("Beta",
              "How much the stock moves with the market. 1.0 = moves with it; 1.5 = 50% bigger swings. The DCF uses "
              "adjusted beta: 0.67 x raw + 0.33 (FD-11).",
              "How cyclical the business is and how levered it is.",
              "Cost of equity = risk-free + beta x equity risk premium, then WACC. A higher beta means a higher "
              "required return and a lower value."),
    "erp": C("Equity risk premium",
             "The extra return investors demand for owning stocks over Treasuries. 5% is a common banking convention "
             "(FD-11).",
             "Market-wide risk appetite. It is a judgment input, not a measured one.",
             "Multiplied by beta in the cost of equity, so it scales the whole equity part of WACC."),
    "cost_of_debt": C("Pre-tax cost of debt",
                      "The interest rate the company pays on its debt. Default: LTM interest expense / total debt.",
                      "Credit quality and the level of interest rates.",
                      "The debt part of WACC, after tax. It only matters as much as debt's weight in the capital "
                      "structure, which for most large tech companies is small."),
    "terminal_growth": C("Terminal growth rate",
                         "How fast free cash flow grows every year after year 5, forever. Usually set near long-run "
                         "inflation plus a little real growth (2.5% default, FD-11). It must stay below WACC.",
                         "Long-run economic growth; no company outgrows the economy forever.",
                         "The terminal value, which is usually most of the DCF's value, so small changes move the "
                         "answer a lot."),
    # DCF outputs
    "cost_of_equity": C("Cost of equity",
                        "The return shareholders require, from CAPM: risk-free + beta x equity risk premium.",
                        "Interest rates, beta, the equity risk premium.",
                        "The equity part of WACC."),
    "wacc": C("WACC (weighted average cost of capital)",
              "The blended return debt and equity holders require, weighted by how much of each the company has "
              "(market equity value and total debt). It is the discount rate for unlevered free cash flow.",
              "Cost of equity, after-tax cost of debt, and the debt/equity mix.",
              "Every discount factor and the terminal value's denominator (WACC - g). Higher WACC = lower value."),
    "revenue_f": C("Forecast revenue",
                   "Revenue in a forecast year: the previous year's revenue x (1 + that year's growth).",
                   "The growth assumptions.",
                   "EBIT, D&A, capex and the NWC build are all a % of it."),
    "ebit_f": C("Forecast EBIT", "Revenue x EBIT margin.", "Revenue and the EBIT margin.",
                "Taxes and NOPAT."),
    "taxes_f": C("Taxes on EBIT",
                 "EBIT x tax rate. The DCF taxes operating profit as if the company had no debt (unlevered); the "
                 "benefit of interest deductions is in WACC instead. No tax credit is given on a loss.",
                 "EBIT and the tax rate.", "NOPAT."),
    "nopat": C("NOPAT (net operating profit after tax)", "EBIT - taxes on EBIT.",
               "Revenue, margin and tax rate.", "The first line of unlevered free cash flow."),
    "d_and_a_f": C("Forecast D&A", "Revenue x D&A %. Added back because it isn't a cash cost.",
                   "Revenue and D&A %.", "Free cash flow (added back) and year-5 EBITDA."),
    "capex_f": C("Forecast capex", "Revenue x capex %. A real cash outflow for new equipment and buildings.",
                 "Revenue and capex %.", "Free cash flow (subtracted)."),
    "nwc_change": C("Increase in net working capital",
                    "Extra cash tied up in working capital as revenue grows: (this year's revenue - last year's) x "
                    "NWC %.",
                    "Revenue growth and NWC %.", "Free cash flow (subtracted)."),
    "ufcf": C("Unlevered free cash flow (UFCF)",
              "Cash the business produces for all investors after paying taxes and reinvesting: NOPAT + D&A - "
              "capex - increase in NWC.",
              "Every operating assumption.", "Its present value counts toward EV; year 5 seeds the terminal value."),
    "period": C("Discount period",
                "How many years from today the cash arrives. End-of-year: 1, 2, 3...; mid-year convention: 0.5, "
                "1.5, 2.5... because cash comes in through the year.",
                "The mid-year toggle.", "The discount factor."),
    "discount_factor": C("Discount factor",
                         "What $1 received in that year is worth today: 1 / (1 + WACC)^period.",
                         "WACC and the discount period.", "PV of that year's free cash flow."),
    "pv": C("Present value of free cash flow", "That year's UFCF x its discount factor.",
            "UFCF and WACC.", "Summed into the PV of free cash flows, part of EV."),
    "terminal_fcf": C("Terminal-year free cash flow",
                      "The cash flow the perpetuity grows from: year-5 UFCF, with capex set equal to D&A when "
                      "steady state is on and year-5 capex is above D&A (FD-11).",
                      "Year-5 operations and the steady-state toggle.", "The terminal value."),
    "terminal_value": C("Terminal value",
                        "The value, at the end of year 5, of every cash flow after year 5: terminal FCF x (1 + g) / "
                        "(WACC - g). This is the Gordon growth (perpetuity) formula.",
                        "Year-5 cash flow, WACC and terminal growth. As g approaches WACC it explodes.",
                        "Discounted back to today it is usually the biggest part of EV."),
    "pv_terminal": C("PV of terminal value", "Terminal value / (1 + WACC)^5 (4.5 under mid-year).",
                     "Terminal value and WACC.", "Enterprise value."),
    "pv_fcf": C("PV of free cash flows", "The five discounted forecast cash flows added up.",
                "Every operating assumption and WACC.", "Enterprise value."),
    "dcf_ev": C("DCF enterprise value", "PV of free cash flows + PV of terminal value.",
                "Every assumption.", "Minus debt, plus cash = DCF equity value."),
    "dcf_equity": C("DCF equity value",
                    "DCF EV - debt - preferred - noncontrolling interest + cash + short-term investments: the part of "
                    "the business that belongs to shareholders.",
                    "DCF EV and the balance sheet.", "Divided by shares = DCF share price."),
    "dcf_price": C("DCF share price (intrinsic value)",
                   "DCF equity value / shares outstanding. If it is above the current price, the model says the stock "
                   "is undervalued on these assumptions.",
                   "Every assumption, the balance sheet and the share count.",
                   "The DCF bar on the football field and the upside vs the current price."),
    "tv_share": C("Terminal value % of EV",
                  "How much of the DCF value comes from after year 5. Over ~75% means the answer rests mainly on "
                  "WACC and terminal growth, not on the five forecast years.",
                  "Growth, WACC and terminal growth.", "How much to trust the DCF: higher = more fragile."),
    "implied_exit": C("Implied exit multiple",
                      "Terminal value / year-5 EBITDA: the EV/EBITDA a buyer would pay in year 5 if the perpetuity "
                      "is right. Compare it with today's peer multiples.",
                      "Terminal growth, WACC, and the year-5 cash conversion.",
                      "A sanity check: an implied multiple far above peers means the terminal assumptions are "
                      "generous."),
    "sensitivity": C("Sensitivity table",
                     "The DCF share price rerun at every combination of WACC (rows) and terminal growth (columns), "
                     "with every other assumption held fixed.",
                     "WACC and terminal growth.", "The DCF bar on the football field uses the corners at WACC ±1% "
                                                   "and g ±0.5%."),
    "upside": C("Upside vs current price", "DCF share price / current share price - 1.",
                "Every DCF assumption, and the share price.", "The pitch: buy if positive enough, sell if negative."),
}


# ---- explanations -----------------------------------------------------------------------


@dataclass
class Explanation:
    title: str
    value: str
    what: str
    here: list[str] = field(default_factory=list)  # this company's numbers, in sentences
    calc: str | None = None  # the formula with this company's numbers
    drivers: str = ""
    feeds: str = ""
    impact: list[str] = field(default_factory=list)  # computed "if this moves..." lines
    figure: Figure | None = None  # for the sources table
    cik: int | None = None  # whose filings the sources link to, when not the page's target


@dataclass
class Context:
    """What the templates may cite: one company's figures, plus the DCF when it ran."""

    name: str
    ticker: str
    m: CompanyMetrics
    peer_stats: dict = field(default_factory=dict)  # comps.Stats by column
    dcf: object | None = None  # DcfContext


def explain(key: str, fig: Figure | None, ctx: Context, title: str | None = None) -> Explanation:
    c = CONCEPTS[key]
    e = Explanation(title=title or c.title, value=value_text(fig), what=c.what, drivers=c.drivers,
                    feeds=c.feeds, figure=fig)
    if fig is not None:
        if fig.ok:
            e.calc = None if fig.formula in ("test", "") else fig.formula
        else:
            e.here.append(f"This number is {'NM (not meaningful)' if fig.nm else 'n/a'} for {ctx.ticker}: "
                          f"{fig.reason}.")
    extra = _HERE.get(key)
    if extra and (fig is None or fig.ok):
        try:
            extra(e, fig, ctx)
        except (TypeError, ZeroDivisionError, KeyError, AttributeError):
            pass  # a template that can't be filled is skipped, never guessed (rule 3)
    return e


def _f(ctx: Context, key: str) -> float | None:
    f = ctx.m.figures.get(key)
    return f.value if f is not None and f.ok else None


def _peer(ctx: Context, key: str, value: float, fmt, relative: bool = True) -> str | None:
    s = ctx.peer_stats.get(key)
    if not s or s.median is None:
        return None
    if relative and value > 0 and s.median > 0:
        d = value / s.median - 1
        rel = "in line with" if abs(d) < 0.05 else f"{abs(d):.0%} {'above' if d > 0 else 'below'}"
        return f"Peer median is {fmt(s.median)} ({s.n} peers), so {ctx.ticker} is {rel} it."
    # A % gap is meaningless across zero (net cash vs net debt), so state the plain difference.
    d = value - s.median
    return (f"Peer median is {fmt(s.median)} ({s.n} peers); {ctx.ticker} is {fmt(abs(d))} "
            f"{'higher' if d > 0 else 'lower'}.")


def _price(e, f, ctx):
    sh, eq, ev, ebitda = (_f(ctx, k) for k in ("shares_outstanding", "equity_value", "enterprise_value",
                                                "ltm_ebitda"))
    e.here.append(f"{ctx.ticker} at {per_share(f.value)} x {sh / 1e6:,.0f}m shares = {money(eq)} of equity value.")
    if ev and ebitda and ebitda > 0:
        e.impact.append(f"If the price rose 10% (to {per_share(f.value * 1.1)}), equity value and EV would each rise "
                        f"by {money(0.1 * eq)}, taking EV/EBITDA from {mult(ev / ebitda)} to "
                        f"{mult((ev + 0.1 * eq) / ebitda)}. The business didn't change; it just got more expensive.")


def _shares(e, f, ctx):
    eq = _f(ctx, "equity_value")
    e.here.append(f"{ctx.ticker} has {f.value / 1e6:,.0f}m shares outstanding.")
    d = ctx.dcf
    if d and d.result.share_price.ok:
        px = d.result.share_price.value
        e.impact.append(f"A 2% buyback (2% fewer shares) would lift the DCF value per share from {per_share(px)} to "
                        f"{per_share(px / 0.98)}: the same equity value split across fewer shares.")
    elif eq:
        e.impact.append("A 2% buyback leaves the business unchanged but raises every per-share value by about 2%.")


def _bridge_item(sign: int):
    def fill(e, f, ctx):
        sh = _f(ctx, "shares_outstanding")
        e.here.append(f"{ctx.ticker} reports {money(f.value)} as of {f.as_of}.")
        if sh:
            word = "lowers" if sign < 0 else "raises"
            e.impact.append(f"Every extra $1bn here {word} the DCF and comps-implied value per share by "
                            f"{per_share(1e9 / sh)} ($1bn / {sh / 1e6:,.0f}m shares): EV comes from the business, "
                            "so the claim comes straight out of (or goes into) the shareholders' slice.")
    return fill


def _ev(e, f, ctx):
    eq, debt, cash, sti = (_f(ctx, k) for k in ("equity_value", "total_debt", "cash", "short_term_investments"))
    if eq is not None and debt is not None and cash is not None:
        e.here.append(f"{ctx.ticker}: {money(eq)} equity + {money(debt)} debt - {money(cash)} cash"
                      + (f" - {money(sti)} short-term investments" if sti else "") + f" (plus any preferred and "
                      f"noncontrolling interest) = {money(f.value)}.")
        if f.value and eq:
            e.here.append(f"EV is {f.value / eq:.2f}x equity value: "
                          + ("the company holds more cash than debt." if f.value < eq else
                             "debt makes the whole business cost more than the shares alone."))


def _net_debt(e, f, ctx):
    e.here.append(f"{ctx.ticker} has net {'cash' if f.value < 0 else 'debt'} of {money(abs(f.value))}.")


def _leverage(e, f, ctx):
    if f.value < 0:
        e.here.append(f"{ctx.ticker} holds net cash worth {abs(f.value):.1f} years of EBITDA, so it has no net "
                      "leverage.")
    else:
        e.here.append(f"{ctx.ticker}'s net debt is {f.value:.1f} years of EBITDA.")
    line = _peer(ctx, "net_debt_ebitda", f.value, mult, relative=False)
    if line:
        e.here.append(line)


def _revenue(e, f, ctx):
    e.here.append(f"{ctx.ticker} booked {money(f.value)} of revenue in this period.")
    mgn, evr = _f(ctx, "ebitda_margin"), _f(ctx, "ev_revenue")
    if f.name.startswith("LTM") and evr:
        e.here.append(f"The market values each dollar of it at {mult(evr)} (EV/Revenue).")
    if mgn:
        e.impact.append(f"At {ctx.ticker}'s {pct(mgn)} EBITDA margin, every extra $1bn of revenue brings about "
                        f"{money(1e9 * mgn)} of EBITDA.")


def _growth(e, f, ctx):
    e.here.append(f"{ctx.ticker}'s revenue {'grew' if f.value >= 0 else 'shrank'} {pct(abs(f.value))}.")
    line = _peer(ctx, "revenue_growth_ltm", f.value, pct)
    if line:
        e.here.append(line)


def _ebit(e, f, ctx):
    rev = _f(ctx, "ltm_revenue")
    if f.name.startswith("LTM") and rev:
        e.here.append(f"{ctx.ticker} keeps {pct(f.value / rev)} of revenue as operating profit (EBIT margin).")


def _ebitda(e, f, ctx):
    ev, sh = _f(ctx, "enterprise_value"), _f(ctx, "shares_outstanding")
    if f.name.startswith("LTM") and ev and f.value > 0:
        e.here.append(f"{ctx.ticker}'s EV of {money(ev)} is {mult(ev / f.value)} this EBITDA.")
        s = ctx.peer_stats.get("ev_ebitda")
        if s and s.median and sh:
            e.impact.append(f"At the peer median {mult(s.median)} EV/EBITDA, each extra $1bn of EBITDA adds "
                            f"{money(s.median * 1e9)} of implied EV, or {per_share(s.median * 1e9 / sh)} per share.")


def _margin(e, f, ctx):
    e.here.append(f"{ctx.ticker} turns each $1.00 of revenue into ${f.value:.2f} of EBITDA.")
    line = _peer(ctx, "ebitda_margin", f.value, pct)
    if line:
        e.here.append(line)
    rev, sh = _f(ctx, "ltm_revenue"), _f(ctx, "shares_outstanding")
    s = ctx.peer_stats.get("ev_ebitda")
    if rev and s and s.median and sh:
        add = rev * 0.01
        e.impact.append(f"One more point of margin = {money(add)} more EBITDA on today's revenue; at the peer "
                        f"median {mult(s.median)} that's {money(add * s.median)} of implied EV, "
                        f"{per_share(add * s.median / sh)} per share.")


def _multiple(key: str, base_key: str):
    def fill(e, f, ctx):
        base = _f(ctx, base_key)
        what = {"ev_ebitda": "years of EBITDA", "ev_revenue": "dollars per $1 of revenue",
                "pe": "dollars per $1 of net income"}[key]
        e.here.append(f"{ctx.ticker} trades at {mult(f.value)}: {f.value:.1f} {what}.")
        line = _peer(ctx, key, f.value, mult)
        if line:
            e.here.append(line)
        sh = _f(ctx, "shares_outstanding")
        if base and sh and key != "pe":
            what_ = "LTM EBITDA" if base_key == "ltm_ebitda" else "LTM revenue"
            e.impact.append(f"Each 1.0x turn on this multiple is worth {money(base)} of EV ({what_} x 1), or "
                            f"{per_share(base / sh)} per share.")
    return fill


def _sbc(e, f, ctx):
    rev = _f(ctx, "ltm_revenue")
    if f.name.startswith("LTM") and rev:
        e.here.append(f"{ctx.ticker} paid {money(f.value)} in stock, {pct(f.value / rev)} of revenue. Adding it back "
                      "would make EBITDA look that much bigger.")


_HERE = {
    "price": _price, "shares_outstanding": _shares, "enterprise_value": _ev, "net_debt": _net_debt,
    "net_debt_ebitda": _leverage, "total_debt": _bridge_item(-1), "cash": _bridge_item(1),
    "short_term_investments": _bridge_item(1), "preferred_stock": _bridge_item(-1),
    "noncontrolling_interest": _bridge_item(-1), "revenue": _revenue, "revenue_growth": _growth,
    "operating_income": _ebit, "ebitda": _ebitda, "ebitda_margin": _margin, "sbc": _sbc,
    "ev_ebitda": _multiple("ev_ebitda", "ltm_ebitda"), "ev_revenue": _multiple("ev_revenue", "ltm_revenue"),
    "pe": _multiple("pe", "ltm_net_income"),
}

# Figure keys in CompanyMetrics -> concept.
FIGURE_CONCEPT = {
    "price": "price", "shares_outstanding": "shares_outstanding", "equity_value": "equity_value",
    "total_debt": "total_debt", "cash": "cash", "short_term_investments": "short_term_investments",
    "preferred_stock": "preferred_stock", "noncontrolling_interest": "noncontrolling_interest",
    "enterprise_value": "enterprise_value", "net_debt": "net_debt", "net_debt_ebitda": "net_debt_ebitda",
    "ltm_revenue": "revenue", "revenue": "revenue", "revenue_growth_ltm": "revenue_growth",
    "revenue_growth_fy": "revenue_growth", "ltm_operating_income": "operating_income",
    "operating_income": "operating_income", "ltm_d_and_a": "d_and_a", "d_and_a": "d_and_a",
    "ltm_ebitda": "ebitda", "ebitda": "ebitda", "ebitda_margin": "ebitda_margin",
    "ltm_net_income": "net_income", "net_income": "net_income", "ltm_sbc": "sbc", "sbc": "sbc",
    "ev_revenue": "ev_revenue", "ev_ebitda": "ev_ebitda", "pe": "pe", "price_vs_52w_high": "price_vs_52w_high",
    "share_count_check": "share_count_check", "diluted_shares": "diluted_shares",
}


RATIOS = {"ev_revenue", "ev_ebitda", "pe", "ebitda_margin", "net_debt_ebitda", "revenue_growth_ltm",
          "revenue_growth_fy"}


def explain_figure(key: str, fig: Figure | None, ctx: Context, title: str | None = None) -> Explanation:
    e = explain(FIGURE_CONCEPT.get(key, key), fig, ctx, title)
    # Ratios: show the division with this company's numbers, not just the formula's words.
    if key in RATIOS and fig is not None and fig.ok and len(fig.inputs) == 2 and all(i.ok for i in fig.inputs):
        a, b = fig.inputs
        tail = " - 1" if key.startswith("revenue_growth") else ""
        e.calc = f"{fig.formula}\n{value_text(a)} / {value_text(b)}{tail} = {value_text(fig)}"
    return e


def explain_peer_stat(column: str, stat_name: str, value: float | None, stats, ctx: Context,
                      label: str) -> Explanation:
    c = CONCEPTS["peer_stat"]
    unit = "ratio" if column in ("revenue_growth_ltm", "ebitda_margin") else "x"
    shown = pct(value) if unit == "ratio" else mult(value)
    e = Explanation(f"Peers: {stat_name} {label}", shown, c.what, drivers=c.drivers, feeds=c.feeds)
    if stats is not None:
        e.here.append(f"Computed over {stats.n} peer(s): {', '.join(stats.included) or 'none'}.")
        for t, why in stats.excluded:
            e.here.append(f"Left out: {t} ({why}).")
    own = _f(ctx, column)
    if own is not None and value:
        e.here.append(f"{ctx.ticker} itself is at {pct(own) if unit == 'ratio' else mult(own)}.")
    return e


def explain_implied(r, point: int, ctx: Context, label: str) -> Explanation:
    """One implied-valuation line (FD-8) with this company's arithmetic."""
    c = CONCEPTS["implied"]
    names = ("25th percentile", "median", "75th percentile")
    px = r.share_price[point]
    e = Explanation(f"Implied price from {label}, peer {names[point]}", value_text(px), c.what,
                    drivers=c.drivers, feeds=c.feeds, figure=px)
    if r.reason:
        e.here.append(f"n/a: {r.reason}.")
        return e
    mults = (r.low_multiple, r.mid_multiple, r.high_multiple)
    ev, eq = r.enterprise_value[point], r.equity_value[point]
    sh = _f(ctx, "shares_outstanding")
    e.here.append(f"Peer {names[point]} {mult(mults[point])} x {ctx.ticker}'s {r.target_metric.name} "
                  f"{money(r.target_metric.value)} = implied EV {value_text(ev)}.")
    e.here.append(f"Minus debt, plus cash (the EV bridge in reverse) = equity {value_text(eq)}; / "
                  f"{(sh or 0) / 1e6:,.0f}m shares = {value_text(px)}.")
    price = _f(ctx, "price")
    if px.ok and price:
        e.here.append(f"That is {px.value / price - 1:+.0%} versus the current {per_share(price)}.")
    if sh:
        e.impact.append(f"Each 1.0x on the peer multiple moves this by {per_share(r.target_metric.value / sh)} per "
                        "share. Swapping one peer in or out can shift the quartiles by more than that.")
    return e


# ---- DCF: context, cell explanations, walkthrough ----------------------------------------


@dataclass
class DcfContext:
    result: object  # dcf.Result
    assumptions: dict[str, Figure]
    defaults: dict[str, Figure]
    m: CompanyMetrics
    base: object  # dcf.Base
    mid_year: bool
    steady: bool


def assumption_concept(key: str) -> str:
    return "growth" if key in dcf.GROWTH_KEYS else key


def explain_assumption(key: str, d: DcfContext, ctx: Context) -> Explanation:
    f = d.assumptions[key]
    e = explain(assumption_concept(key), f, ctx, title=dcf.LABELS[key])
    default = d.defaults.get(key)
    if default is not None and default is not f and default.ok:
        e.here.append(f"You changed it; the default was {value_text(default)} ({default.formula}).")
    if key == "cost_of_debt":
        E, D = _f(ctx, "equity_value"), _f(ctx, "total_debt")
        if E and D is not None:
            e.here.append(f"Debt is {D / (D + E):.1%} of {ctx.ticker}'s capital (market values), so this rate has "
                          f"{D / (D + E):.1%} weight in WACC.")
    if key == "beta" and f.ok:
        e.here.append(f"A beta of {f.value:.2f} means that when the market moves 1%, {ctx.ticker} has tended to move "
                      f"about {f.value:.2f}%.")
    if key in dcf.GROWTH_KEYS and f.ok:
        i = dcf.GROWTH_KEYS.index(key)
        y = d.result.years[i] if d.result.years else None
        if y:
            e.here.append(f"Year {i + 1} revenue = prior year x (1 + {pct(f.value)}) = {money(y.revenue)}.")
    e.impact.extend(nudge(d, key))
    return e


def nudge(d: DcfContext, key: str) -> list[str]:
    """'Raise it one step and this happens', computed by rerunning the DCF."""
    f = d.assumptions[key]
    if not f.ok or not d.result.share_price.ok:
        return []
    step = step_for(key)
    lines = []
    for sgn in (1, -1):
        after = run_with(d, {key: f.value + sgn * step})
        if after.share_price.ok:
            lines.append(f"{'Raise' if sgn > 0 else 'Lower'} it {step_text(key)} (to {value_text(replace(f, value=f.value + sgn * step))}): "
                         f"EV {money(d.result.enterprise_value.value)} → {money(after.enterprise_value.value)}, "
                         f"share price {per_share(d.result.share_price.value)} → {per_share(after.share_price.value)} "
                         f"({after.share_price.value / d.result.share_price.value - 1:+.1%}).")
        else:
            lines.append(f"{'Raise' if sgn > 0 else 'Lower'} it {step_text(key)}: the DCF stops working "
                         f"({after.reason}).")
    return lines


def step_for(key: str) -> float:
    return BETA_STEP if key == "beta" else TERMINAL_STEP if key == "terminal_growth" else PCT_STEP


def step_text(key: str) -> str:
    return f"by {BETA_STEP:.2f}" if key == "beta" else f"by {step_for(key) * 100:g} point" + (
        "" if step_for(key) * 100 == 1 else "s")


def run_with(d: DcfContext, changes: dict[str, float]):
    a = dict(d.assumptions)
    for k, v in changes.items():
        a[k] = Figure(dcf.LABELS[k], v, dcf.UNITS[k], "learn-mode scenario", inputs=(d.assumptions[k],))
    return dcf.run(a, d.m, d.base, d.mid_year, steady_state=d.steady)


# Rows of the DCF projection table -> (concept, Year attribute).
DCF_ROWS = {
    "Revenue": ("revenue_f", "revenue"), "Growth": ("growth", "growth"), "EBIT": ("ebit_f", "ebit"),
    "− Taxes on EBIT": ("taxes_f", "taxes"), "= NOPAT": ("nopat", "nopat"), "+ D&A": ("d_and_a_f", "d_and_a"),
    "− Capex": ("capex_f", "capex"), "− Increase in NWC": ("nwc_change", "nwc_change"),
    "= Unlevered free cash flow": ("ufcf", "ufcf"), "Discount period (years)": ("period", "period"),
    "Discount factor": ("discount_factor", "discount_factor"), "PV of free cash flow": ("pv", "pv"),
}


def explain_dcf_cell(row: str, col: str, d: DcfContext, ctx: Context) -> Explanation | None:
    """One cell of the DCF projection table, with that year's arithmetic."""
    if row not in DCF_ROWS:
        return None
    concept, attr = DCF_ROWS[row]
    c = CONCEPTS[concept]
    res, a = d.result, d.assumptions
    v = {k: f.value for k, f in a.items()}
    if col == "LTM (base)" or col == "":
        F = ctx.m.figures
        key = {"Revenue": "ltm_revenue", "Growth": "revenue_growth_ltm", "EBIT": "ltm_operating_income",
               "+ D&A": "ltm_d_and_a"}.get(row)
        if key is None:
            return Explanation(row, "", c.what, drivers=c.drivers, feeds=c.feeds)
        e = explain_figure(key, F.get(key), ctx, f"{row}, last twelve months")
        e.here.insert(0, "This is actual history (year 0). The forecast starts from it.")
        return e
    if col == "Terminal year":
        t = res.terminal_fcf
        e = explain("terminal_fcf", t, ctx)
        y5 = res.years[-1]
        e.here.append(f"Year-5 NOPAT {money(y5.nopat)} + D&A {money(y5.d_and_a)} - capex "
                      f"{money(y5.nopat + y5.d_and_a - y5.nwc_change - t.value)} - NWC build {money(y5.nwc_change)} = "
                      f"{money(t.value)}.")
        return e
    n = int(col.split()[-1])
    y = res.years[n - 1]
    prev_rev = res.years[n - 2].revenue if n > 1 else ctx.m.figures["ltm_revenue"].value
    val = getattr(y, attr)
    shown = {"growth": pct(val), "period": f"{val:g} years", "discount_factor": f"{val:.3f}"}.get(attr, money(val))
    e = Explanation(f"{row.lstrip('−+= ')}, year {n}", shown, c.what, drivers=c.drivers, feeds=c.feeds)
    calc = {
        "revenue": f"{money(prev_rev)} x (1 + {pct(y.growth)}) = {money(y.revenue)}",
        "growth": f"assumption: {a[dcf.GROWTH_KEYS[n - 1]].formula}",
        "ebit": f"{money(y.revenue)} revenue x {pct(v['ebit_margin'])} EBIT margin = {money(y.ebit)}",
        "taxes": f"{money(max(y.ebit, 0))} EBIT x {pct(v['tax_rate'])} tax = {money(y.taxes)}",
        "nopat": f"{money(y.ebit)} EBIT - {money(y.taxes)} taxes = {money(y.nopat)}",
        "d_and_a": f"{money(y.revenue)} x {pct(v['da_pct'])} = {money(y.d_and_a)}",
        "capex": f"{money(y.revenue)} x {pct(v['capex_pct'])} = {money(y.capex)}",
        "nwc_change": f"({money(y.revenue)} - {money(prev_rev)}) new revenue x {pct(v['nwc_pct'])} NWC = "
                      f"{money(y.nwc_change)}",
        "ufcf": f"{money(y.nopat)} NOPAT + {money(y.d_and_a)} D&A - {money(y.capex)} capex - "
                f"{money(y.nwc_change)} NWC build = {money(y.ufcf)}",
        "period": f"{'mid-year: ' + str(n) + ' - 0.5' if d.mid_year else 'end of year ' + str(n)} = {y.period:g}",
        "discount_factor": f"1 / (1 + {pct(res.wacc.value, 2)})^{y.period:g} = {y.discount_factor:.3f}",
        "pv": f"{money(y.ufcf)} x {y.discount_factor:.3f} = {money(y.pv)}",
    }[attr]
    e.calc = calc
    if attr == "discount_factor":
        e.here.append(f"$1.00 of cash in year {n} is worth ${y.discount_factor:.2f} today at a "
                      f"{pct(res.wacc.value, 2)} WACC.")
    if attr == "ufcf" and y.nopat:
        e.here.append(f"{ctx.ticker} converts {y.ufcf / y.nopat:.0%} of its after-tax operating profit into free "
                      "cash in this year; the rest is reinvested.")
    if attr == "pv" and res.enterprise_value.ok:
        e.here.append(f"This year contributes {y.pv / res.enterprise_value.value:.1%} of the DCF enterprise value.")
    return e


def explain_dcf_output(key: str, d: DcfContext, ctx: Context) -> Explanation:
    res = d.result
    figs = {"cost_of_equity": res.cost_of_equity, "wacc": res.wacc, "terminal_value": res.terminal_value,
            "pv_terminal": res.pv_terminal, "pv_fcf": res.pv_fcf, "dcf_ev": res.enterprise_value,
            "dcf_equity": res.equity_value, "dcf_price": res.share_price, "terminal_fcf": res.terminal_fcf}
    f = figs.get(key)
    e = explain(key, f, ctx)
    price = _f(ctx, "price")
    if key == "tv_share" and res.tv_share_of_ev is not None:
        e.value = f"{res.tv_share_of_ev:.0%}"
        e.here.append(f"{money(res.pv_terminal.value)} of {ctx.ticker}'s {money(res.enterprise_value.value)} DCF EV "
                      "comes from after year 5.")
    if key == "implied_exit" and res.implied_exit_multiple is not None:
        e.value = mult(res.implied_exit_multiple)
        s = ctx.peer_stats.get("ev_ebitda")
        if s and s.median:
            e.here.append(f"Today's peer median EV/EBITDA is {mult(s.median)}; the perpetuity implies "
                          f"{mult(res.implied_exit_multiple)} in year 5.")
    if key == "upside" and price and res.share_price.ok:
        e.value = f"{res.share_price.value / price - 1:+.1%}"
        e.calc = f"{per_share(res.share_price.value)} / {per_share(price)} - 1"
    if key == "dcf_price" and price and res.share_price.ok:
        e.here.append(f"Current price {per_share(price)}, so the model says {res.share_price.value / price - 1:+.1%}.")
    if key == "wacc" and res.wacc.ok:
        e.impact.append(_wacc_impact(d))
    if key == "terminal_value" and res.terminal_value.ok:
        e.impact.extend(nudge(d, "terminal_growth"))
    return e


def _wacc_impact(d: DcfContext) -> str:
    res = d.result
    up = dcf.run(d.assumptions, d.m, d.base, d.mid_year, wacc_override=res.wacc.value + PCT_STEP,
                 steady_state=d.steady)
    if not up.share_price.ok:
        return f"At 1 point higher WACC the DCF is n/a ({up.reason})."
    return (f"One point higher WACC ({pct(res.wacc.value + PCT_STEP, 2)}): share price "
            f"{per_share(res.share_price.value)} → {per_share(up.share_price.value)} "
            f"({up.share_price.value / res.share_price.value - 1:+.1%}).")


@dataclass
class Step:
    title: str
    text: str
    math: list[str] = field(default_factory=list)


def walkthrough(d: DcfContext, ctx: Context) -> list[Step]:
    """The whole DCF, start to finish, in this company's numbers."""
    res, a, F = d.result, d.assumptions, ctx.m.figures
    if res.reason or not res.years:
        return [Step("The DCF can't run yet", f"Reason: {res.reason}. Fill in the missing assumption(s) above and "
                                              "the walkthrough will appear.")]
    v = {k: f.value for k, f in a.items()}
    y1, y5 = res.years[0], res.years[-1]
    rev0 = F["ltm_revenue"].value
    E, D = F["equity_value"].value, F["total_debt"].value
    we = E / (E + D)
    steps = [
        Step("1. Start from what the company sells today",
             f"{ctx.name} had {money(rev0)} of revenue in the twelve months to {ctx.m.ltm_end}. That is year 0; "
             "everything else is forecast from it.",
             [f"LTM revenue = {money(rev0)}"]),
        Step("2. Forecast revenue for five years",
             f"Growth starts at {pct(v['growth_1'])} in year 1 and moves to {pct(v['growth_5'])} by year 5. "
             "By default it starts at the latest actual growth and fades in a straight line to the terminal "
             "rate, because fast growth rarely lasts.",
             [f"Year {y.n}: {money(res.years[i - 1].revenue if i else rev0)} x (1 + {pct(y.growth)}) = "
              f"{money(y.revenue)}" for i, y in enumerate(res.years)]),
        Step("3. Operating profit (EBIT)",
             f"Each year's EBIT is revenue x the EBIT margin ({pct(v['ebit_margin'])}). The default is the "
             "company's own 3-year margin.",
             [f"Year 1: {money(y1.revenue)} x {pct(v['ebit_margin'])} = {money(y1.ebit)}",
              f"Year 5: {money(y5.revenue)} x {pct(v['ebit_margin'])} = {money(y5.ebit)}"]),
        Step("4. Tax it as if there were no debt (NOPAT)",
             f"Tax at {pct(v['tax_rate'])} on EBIT, not on pretax income. This is 'unlevered': interest is "
             "ignored here because the cost of debt is already in WACC, and the debt itself is subtracted at "
             "the end. Counting it in both places would double-count it.",
             [f"Year 1: {money(y1.ebit)} - {money(y1.taxes)} tax = NOPAT {money(y1.nopat)}"]),
        Step("5. Turn profit into free cash flow",
             "Add back D&A (a non-cash charge), subtract capex (cash spent on equipment) and the increase in "
             f"working capital (cash tied up as the company grows, {pct(v['nwc_pct'])} of each new dollar of "
             "revenue). What's left is unlevered free cash flow: cash available to every investor.",
             [f"Year {y.n}: {money(y.nopat)} + {money(y.d_and_a)} - {money(y.capex)} - {money(y.nwc_change)} = "
              f"{money(y.ufcf)}" for y in res.years]),
        Step("6. Work out the discount rate (WACC)",
             "Cash later is worth less than cash now, and investors want paying for risk. Shareholders' required "
             "return comes from CAPM; lenders' is the interest rate, after tax because interest is deductible. "
             f"Weighted by market values: {we:.1%} equity, {1 - we:.1%} debt.",
             [f"Cost of equity = {pct(v['risk_free'], 2)} risk-free + {v['beta']:.2f} beta x {pct(v['erp'], 2)} ERP "
              f"= {pct(res.cost_of_equity.value, 2)}",
              f"WACC = {we:.1%} x {pct(res.cost_of_equity.value, 2)} + {1 - we:.1%} x {pct(v['cost_of_debt'], 2)} "
              f"x (1 - {pct(v['tax_rate'])}) = {pct(res.wacc.value, 2)}"]),
        Step("7. Discount each year's cash flow to today",
             "Divide each cash flow by (1 + WACC) raised to the number of years until it arrives"
             + (" (mid-year convention: cash arrives through the year, so year 1 is 0.5 years away)."
                if d.mid_year else "."),
             [f"Year {y.n}: {money(y.ufcf)} x {y.discount_factor:.3f} = {money(y.pv)}" for y in res.years]
             + [f"Sum = PV of free cash flows {money(res.pv_fcf.value)}"]),
        Step("8. Value everything after year 5 (terminal value)",
             f"The company doesn't stop in year 5. Assume its cash flow grows {pct(v['terminal_growth'])} a year "
             "forever and use the perpetuity formula. "
             + ("Capex is set equal to D&A in this terminal year (steady state, FD-11). "
                if res.terminal_fcf.formula.startswith(f"year-{dcf.YEARS} NOPAT") else ""),
             [f"Terminal value = {money(res.terminal_fcf.value)} x (1 + {pct(v['terminal_growth'])}) / "
              f"({pct(res.wacc.value, 2)} - {pct(v['terminal_growth'])}) = {money(res.terminal_value.value)}",
              f"PV of terminal value = {money(res.terminal_value.value)} / (1 + {pct(res.wacc.value, 2)})^"
              f"{dcf.YEARS - 0.5 if d.mid_year else dcf.YEARS:g} = {money(res.pv_terminal.value)}"]),
        Step("9. Add them up: enterprise value",
             f"{res.tv_share_of_ev:.0%} of the value comes from the terminal value"
             + (", which is high: the answer rests mostly on WACC and terminal growth." if res.tv_share_of_ev > 0.75
                else "."),
             [f"EV = {money(res.pv_fcf.value)} + {money(res.pv_terminal.value)} = "
              f"{money(res.enterprise_value.value)}"]
             + ([f"Implied exit multiple = terminal value / year-5 EBITDA = {mult(res.implied_exit_multiple)}"]
                if res.implied_exit_multiple else [])),
        Step("10. From enterprise value to equity value",
             "EV belongs to everyone who funded the business. Pay off the lenders (and any preferred or minority "
             "holders) and hand the cash back to shareholders: what's left belongs to shareholders.",
             [f"Equity = {money(res.enterprise_value.value)} - {money(D)} debt - preferred/NCI + "
              f"{money(F['cash'].value)} cash + short-term investments = {value_text(res.equity_value)}"]),
        Step("11. Per share, and the verdict",
             "Divide by shares outstanding and compare with the market price.",
             [f"{value_text(res.equity_value)} / {F['shares_outstanding'].value / 1e6:,.0f}m shares = "
              f"{value_text(res.share_price)}"]
             + ([f"Current price {per_share(F['price'].value)}: "
                 f"{res.share_price.value / F['price'].value - 1:+.1%} upside"]
                if F["price"].ok and res.share_price.ok else [])),
    ]
    bars = tornado(d)
    if len(bars) >= 2:
        top = bars[:2]
        steps.append(Step("12. Know what the answer depends on",
                          f"The two inputs that move {ctx.ticker}'s value most are {top[0].label.lower()} and "
                          f"{top[1].label.lower()} (see the tornado chart). Those are the numbers to defend in "
                          "an interview, and the ones the sensitivity table stresses.",
                          [f"{b.label} {b.step}: {per_share(b.low)} to {per_share(b.high)}" for b in top]))
    return steps


# ---- impact: ripple and tornado ----------------------------------------------------------


@dataclass
class RippleRow:
    line: str
    unit: str
    before: float | None
    after: float | None

    @property
    def change(self) -> float | None:
        if self.before is None or self.after is None:
            return None
        return self.after - self.before

    @property
    def unchanged(self) -> bool:
        tol = {"USD": 5e5, "USD/share": 0.005, "ratio": 5e-5, "x": 0.05}.get(self.unit, 1e-9)
        return self.change is not None and abs(self.change) < tol

    @property
    def change_pct(self) -> float | None:
        if self.change is None or not self.before or self.unit == "ratio":
            return None
        return self.change / abs(self.before)


def ripple(before, after, m: CompanyMetrics) -> list[RippleRow]:
    """Every downstream line of the DCF, before and after a change."""
    price = m.figures["price"].value if m.figures["price"].ok else None

    def y5(r, attr):
        return getattr(r.years[-1], attr) if r.years else None

    def val(f):
        return f.value if f is not None and f.ok else None

    def up(r):
        return r.share_price.value / price - 1 if price and r.share_price.ok else None

    def rows(r):
        return [
            ("Year-5 revenue", "USD", y5(r, "revenue")), ("Year-5 EBIT", "USD", y5(r, "ebit")),
            ("Year-5 free cash flow", "USD", y5(r, "ufcf")), ("Cost of equity", "ratio", val(r.cost_of_equity)),
            ("WACC", "ratio", val(r.wacc)), ("PV of free cash flows (years 1-5)", "USD", val(r.pv_fcf)),
            ("Terminal value", "USD", val(r.terminal_value)), ("PV of terminal value", "USD", val(r.pv_terminal)),
            ("Enterprise value", "USD", val(r.enterprise_value)), ("Equity value", "USD", val(r.equity_value)),
            ("Share price", "USD/share", val(r.share_price)), ("Upside vs current price", "ratio", up(r)),
            ("Terminal value % of EV", "ratio", r.tv_share_of_ev), ("Implied exit multiple", "x",
                                                                    r.implied_exit_multiple),
        ]
    return [RippleRow(lab, u, b, a) for (lab, u, b), (_, _, a) in zip(rows(before), rows(after))]


def changed_keys(d: DcfContext) -> list[str]:
    return [k for k, f in d.assumptions.items() if d.defaults.get(k) is not None and f is not d.defaults[k]]


def defaults_result(d: DcfContext):
    return dcf.run(d.defaults, d.m, d.base, d.mid_year, steady_state=d.steady)


@dataclass
class Bar:
    label: str
    step: str
    low: float | None  # share price with the input lowered
    high: float | None  # share price with the input raised

    @property
    def swing(self) -> float:
        if self.low is None or self.high is None:
            return float("inf")
        return abs(self.high - self.low)


TORNADO = (("Revenue growth (all 5 years)", tuple(dcf.GROWTH_KEYS)), ("EBIT margin", ("ebit_margin",)),
           ("Capex % of revenue", ("capex_pct",)), ("NWC % of revenue", ("nwc_pct",)),
           ("Tax rate", ("tax_rate",)), ("Risk-free rate", ("risk_free",)), ("Beta", ("beta",)),
           ("Equity risk premium", ("erp",)), ("Pre-tax cost of debt", ("cost_of_debt",)),
           ("Terminal growth", ("terminal_growth",)))


def tornado(d: DcfContext) -> list[Bar]:
    """Share price with each input moved down and up one step (FD-14), biggest swing first.

    Inputs whose change breaks the DCF (e.g. WACC falls below g) show as an
    unbounded swing and sort first, which is itself the lesson.
    """
    if not d.result.share_price.ok:
        return []
    out = []
    for label, keys in TORNADO:
        if not all(d.assumptions[k].ok for k in keys):
            continue
        step = step_for(keys[0])
        prices = []
        for sgn in (-1, 1):
            r = run_with(d, {k: d.assumptions[k].value + sgn * step for k in keys})
            prices.append(r.share_price.value if r.share_price.ok else None)
        out.append(Bar(label, f"±{step_text(keys[0])[3:]}", prices[0], prices[1]))
    out.sort(key=lambda b: b.swing, reverse=True)
    return out


CHAINS = {
    "growth": "Revenue growth → revenue in every later year → EBIT, D&A, capex and the NWC build (all % of "
              "revenue) → free cash flow → PV of cash flows, and a bigger year 5 → terminal value → EV → equity "
              "→ share price. WACC is unchanged.",
    "ebit_margin": "EBIT margin → EBIT → taxes and NOPAT → free cash flow every year → terminal value → EV → "
                   "share price.",
    "da_pct": "D&A % → D&A added back, but EBIT already includes it, so free cash flow barely moves. It changes "
              "year-5 EBITDA (the implied exit multiple) and the steady-state capex cap.",
    "capex_pct": "Capex % → cash spent each forecast year → free cash flow → PV of cash flows. With steady state "
                 "on, terminal capex is capped at D&A, so the terminal value is mostly shielded.",
    "nwc_pct": "NWC % → cash tied up per new dollar of revenue → free cash flow (more so the faster it grows) → "
               "EV → share price.",
    "tax_rate": "Tax rate → taxes on EBIT → NOPAT → free cash flow, and → after-tax cost of debt → WACC. The first "
                "effect is far bigger for most companies.",
    "risk_free": "Risk-free rate → cost of equity (and, in reality, cost of debt) → WACC → every discount factor "
                 "and the terminal value denominator → EV → share price. Cash flows are unchanged.",
    "beta": "Beta → cost of equity (beta x ERP) → WACC → discounting → EV → share price.",
    "erp": "ERP → cost of equity (beta x ERP) → WACC → discounting → EV → share price.",
    "cost_of_debt": "Cost of debt → after-tax cost of debt, weighted by debt's share of capital → WACC → "
                    "discounting. Small for companies with little debt.",
    "terminal_growth": "Terminal growth → terminal value (numerator up, denominator WACC - g down) → PV of "
                       "terminal value → EV → share price. The five forecast years are unchanged.",
}


def chain(key: str) -> str:
    return CHAINS[assumption_concept(key)]
