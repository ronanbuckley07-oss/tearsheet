"""Plain-English talking points for a pitch, built only from computed figures.

No LLM: every sentence is a template filled with numbers the engine already
produced (CLAUDE.md rule 1), and a sentence is skipped when a number it needs is
n/a or NM. The output is meant to be pasted into speaker notes or a slide, then
checked against the tables it summarizes.
"""

from __future__ import annotations

from engine.comps import Comps, CompanyRow
from engine.periods import Figure
from engine.sector import LABELS, WEAK_FIT_R2, Sector, fit, residuals


def _x(v: float) -> str:
    return f"{v:.1f}x"


def _pct(v: float) -> str:
    return f"{v:.0%}" if abs(v) >= 0.095 else f"{v:.1%}"


def _usd(v: float) -> str:
    a = abs(v)
    s = f"${a / 1e12:,.2f}tn" if a >= 1e12 else f"${a / 1e9:,.1f}bn" if a >= 1e9 else f"${a / 1e6:,.0f}m"
    return ("-" if v < 0 else "") + s


def _vs(value: float, median: float) -> str:
    """'a 23% premium to' / 'a 12% discount to' / 'in line with'."""
    d = value / median - 1
    if abs(d) < 0.05:
        return "in line with"
    return f"a {abs(d):.0%} {'premium' if d > 0 else 'discount'} to"


def company_points(t: CompanyRow, c: Comps, dcf_price: Figure | None = None) -> list[str]:
    if t.metrics is None:
        return []
    F = t.metrics.figures
    out = []
    rev, g, mgn = F["ltm_revenue"], F["revenue_growth_ltm"], F["ebitda_margin"]
    if rev.ok:
        line = f"{t.name} generated {_usd(rev.value)} of revenue in the twelve months to {t.metrics.ltm_end}"
        if g.ok:
            line += f", {'up' if g.value >= 0 else 'down'} {_pct(abs(g.value))} year on year"
        if mgn.ok:
            line += f", at a {_pct(mgn.value)} EBITDA margin"
        out.append(line + ".")
    for key in ("revenue_growth_ltm", "ebitda_margin"):
        s, f = c.stats.get(key), F[key]
        if s and s.median is not None and f.ok and s.n >= 3:
            word = "faster than" if key == "revenue_growth_ltm" else "above"
            if f.value < s.median:
                word = "slower than" if key == "revenue_growth_ltm" else "below"
            out.append(f"{LABELS[key].split(' (')[0]} of {_pct(f.value)} is {word} the peer median of "
                       f"{_pct(s.median)} ({s.n} peers).")
    for key in ("ev_ebitda", "ev_revenue", "pe"):
        s, f = c.stats.get(key), F[key]
        if s and s.median is not None and f.ok:
            out.append(f"Trades at {_x(f.value)} LTM {LABELS[key]}, {_vs(f.value, s.median)} the peer median "
                       f"of {_x(s.median)} (peer range {_x(s.p25)}-{_x(s.p75)}, 25th-75th percentile).")
            break
    price = F["price"]
    r = c.implied.get("ev_ebitda")
    if r and price.ok and all(p.ok for p in r.share_price):
        lo, mid, hi = (p.value for p in r.share_price)
        out.append(f"Peer EV/EBITDA multiples imply {_usd_px(lo)}-{_usd_px(hi)} per share (median {_usd_px(mid)}), "
                   f"{_updown(mid, price.value)} the current {_usd_px(price.value)}.")
    if dcf_price is not None and dcf_price.ok and price.ok:
        out.append(f"The DCF on the app's assumptions gives {_usd_px(dcf_price.value)} per share, "
                   f"{_updown(dcf_price.value, price.value)} the current price.")
    nd = F["net_debt_ebitda"]
    if nd.ok:
        out.append("Net cash balance sheet (more cash and short-term investments than debt)." if nd.value < 0
                   else f"Net debt is {_x(nd.value)} LTM EBITDA.")
    if t.high_52w is not None and t.high_52w.ok and price.ok:
        d = price.value / t.high_52w.value - 1
        out.append(f"The stock is {_pct(abs(d))} below its 52-week high." if d < -0.005
                   else "The stock is at its 52-week high.")
    return out


def sector_points(s: Sector) -> list[str]:
    out = []
    loaded = s.loaded
    if not loaded:
        return out
    n = len(loaded)
    caps = [r.get("equity_value").value for r in loaded if r.get("equity_value").ok]
    if caps:
        out.append(f"{s.name}: {n} companies, combined market cap {_usd(sum(caps))}.")
    for key in ("ev_ebitda", "ev_revenue"):
        st = s.stats[key]
        if st.median is not None:
            ranked = s.rank(key, descending=False)
            out.append(f"Median LTM {LABELS[key]} is {_x(st.median)} (25th-75th percentile {_x(st.p25)}-"
                       f"{_x(st.p75)}, n = {st.n}); cheapest {ranked[0][0]} at {_x(ranked[0][1])}, "
                       f"richest {ranked[-1][0]} at {_x(ranked[-1][1])}.")
    for key, word in (("revenue_growth_ltm", "revenue growth"), ("ebitda_margin", "EBITDA margin")):
        st = s.stats[key]
        if st.median is not None:
            top = s.rank(key)[0]
            out.append(f"Median LTM {word} is {_pct(st.median)}; highest is {top[0]} at {_pct(top[1])}.")
    f = fit(loaded, "revenue_growth_ltm", "ev_revenue")
    if f.r2 is not None and f.n >= 5:
        strength = "strongly" if f.r2 >= 0.5 else "loosely" if f.r2 >= 0.2 else "barely"
        out.append(f"Valuation tracks growth {strength} here: EV/Revenue vs revenue growth has R² = {f.r2:.2f} "
                   f"across {f.n} companies (each +10 points of growth ≈ {f.slope * 0.1:+.1f}x EV/Revenue).")
    if f.r2 is not None and f.r2 >= WEAK_FIT_R2 and f.n >= 5:
        _, res = residuals(loaded, "revenue_growth_ltm", "ev_revenue")
        low = res[0]
        if low.gap < 0:
            out.append(f"Furthest below the line (cheapest for its growth): {low.ticker} at {_x(low.actual)} "
                       f"EV/Revenue, where the line predicts {_x(low.fitted)}.")
    off = [(t, v) for t, v in s.rank("price_vs_52w_high", descending=False)]
    if off:
        t, v = off[0]
        if v < -0.005:
            out.append(f"Furthest below its 52-week high: {t}, {_pct(abs(v))} below.")
    return out


def _usd_px(v: float) -> str:
    return f"${v:,.2f}"


def _updown(v: float, price: float) -> str:
    d = v / price - 1
    return f"{abs(d):.0%} {'above' if d > 0 else 'below'}" if abs(d) >= 0.005 else "in line with"
