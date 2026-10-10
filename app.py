"""Streamlit UI. No finance logic lives here; it only displays engine output.

Run with: streamlit run app.py
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from engine import report as report_mod
from engine.comps import CONTEXT, MULTIPLES, VALUATION_BASES
from engine.periods import Figure
from engine.sec_client import SECConfigError
from engine.sources import fact_rows, formula_tree, other_sources

st.set_page_config(page_title="Tearsheet", layout="wide")

# Reference categorical palette, slots 1-2 (validated light and dark, adjacent pairs).
BLUE, ORANGE, GRAY = "#2a78d6", "#eb6834", "#8a8984"

LABELS = {
    "ev_revenue": "EV/Revenue", "ev_ebitda": "EV/EBITDA", "pe": "P/E",
    "revenue_growth_ltm": "Revenue growth (LTM)", "ebitda_margin": "EBITDA margin",
    "net_debt_ebitda": "Net debt / EBITDA", "equity_value": "Equity value", "enterprise_value": "EV",
}
BASE_LABELS = {"ltm_ebitda": "EBITDA", "ltm_revenue": "Revenue"}

# ---- display formatting (no math beyond unit scaling) ---------------------------------


def fmt(f: Figure | None, unit: str | None = None) -> str:
    if f is None:
        return "n/a"
    if f.value is None:
        return "NM" if f.nm else "n/a"
    u = unit or f.unit
    v = f.value
    sign = "-" if v < 0 else ""
    if u == "USD":
        a = abs(v)
        return f"{sign}${a / 1e9:,.1f}bn" if a >= 1e9 else f"{sign}${a / 1e6:,.0f}m"
    if u == "shares":
        return f"{v / 1e6:,.0f}m"
    if u == "USD/share":
        return f"{sign}${abs(v):,.2f}"
    if u == "x":
        return f"{v:.1f}x"
    if u == "ratio":
        return f"{v:.1%}"
    return f"{v:,.2f}"


def md(text: str) -> str:
    """Escape dollar signs so Streamlit markdown doesn't render "$1 to $2" as LaTeX."""
    return text.replace("$", "\\$")


def show(df: pd.DataFrame, label: str = "", wide: tuple[str, ...] = (), **config) -> None:
    """A table tall enough to show every row, with the row label as a wide first column."""
    df = df.reset_index(names=label) if label is not None else df
    cfg = {label: st.column_config.TextColumn(label, width=290, pinned=True)} if label is not None else {}
    cfg.update({c: st.column_config.TextColumn(c, width="large") for c in wide})
    cfg.update(config)
    st.dataframe(df, hide_index=True, width="stretch", column_config=cfg,
                 height=35 * (len(df) + 1) + 3)


def why(f: Figure | None) -> str:
    if f is None or f.value is not None:
        return ""
    if f.nm and f.raw_value is not None:
        return f"{f.reason} [{f.raw_value:.1f}x]"
    return f.reason or ""


def sources_panel(title: str, figures: dict[str, Figure], cik: int | None, key: str) -> None:
    """The 'sources' expander: pick any number and see exactly where it came from."""
    with st.expander(f"Sources: {title}"):
        names = list(figures)
        choice = st.selectbox("Number", names, key=f"src-{key}")
        f = figures[choice]
        st.code("\n".join(formula_tree(f)), language=None)
        rows = fact_rows(f, cik)
        if rows:
            df = pd.DataFrame(rows)
            st.dataframe(
                df, hide_index=True, width="stretch",
                column_config={
                    "value": st.column_config.NumberColumn("value (USD or shares)", format="%,.0f"),
                    "link": st.column_config.LinkColumn("filing", display_text="open"),
                },
            )
        for s in other_sources(f):
            st.caption(s)
        notes = f.all_notes()
        if notes:
            st.markdown("**Notes and flags**")
            for n in notes:
                st.markdown(md(f"- {n}"))
        if not rows and not other_sources(f):
            st.caption("No source facts (the value is n/a or NM; the reason is shown above).")


@st.cache_data(ttl=3600, show_spinner=False)
def load(target: str, peers: tuple[str, ...]):
    return report_mod.build_report(target, list(peers))


def parse_peers(text: str) -> list[str]:
    seen = []
    for t in text.replace(",", " ").split():
        t = t.strip().upper()
        if t and t not in seen:
            seen.append(t)
    return seen


# ---- page -------------------------------------------------------------------------------

st.title("Tearsheet")
st.caption("Every number comes from SEC EDGAR filings or the market price, computed in code. "
           "Open any \"Sources\" panel to trace a figure back to its filing.")

with st.form("inputs"):
    c1, c2 = st.columns([1, 3])
    target = c1.text_input("Ticker", value=st.session_state.get("target", "")).strip().upper()
    peers_text = c2.text_area(
        "Peers (tickers separated by spaces or commas)",
        value=st.session_state.get("peers_text", ""), height=68,
        help="US 10-K filers only. FD-9: aim for 6-12 peers with a similar business model, "
             "roughly 0.25x-4x the target's market cap.",
    )
    submitted = st.form_submit_button("Build tearsheet", type="primary")

if submitted:
    st.session_state["target"] = target
    st.session_state["peers_text"] = peers_text

target = st.session_state.get("target", "")
if not target:
    st.info("Enter a ticker (and, for comps, a peer list) to build a tearsheet.")
    st.stop()

peers = parse_peers(st.session_state.get("peers_text", ""))
try:
    with st.spinner(f"Pulling SEC filings and prices for {target} and {len(peers)} peer(s)..."):
        rep = load(target, tuple(peers))
except SECConfigError as exc:
    st.error(str(exc))
    st.stop()

t = rep.target
if t.metrics is None:
    st.error(f"{t.ticker}: {t.error}")
    st.stop()

m = t.metrics
F = m.figures

# ---- snapshot -----------------------------------------------------------------------------

st.header(f"{t.name} ({t.ticker})")
fye = f"{t.fiscal_year_end[:2]}/{t.fiscal_year_end[2:]}" if t.fiscal_year_end else "n/a"
st.caption(f"{t.sic_description or 'Industry n/a'} · Fiscal year ends {fye} (month/day) · "
           f"LTM through {m.ltm_end} · Latest filing {t.latest_filing}")

cols = st.columns(6)
tiles = [("Share price", F["price"]), ("Equity value", F["equity_value"]),
         ("Enterprise value", F["enterprise_value"]), ("LTM revenue", F["ltm_revenue"]),
         ("EV/EBITDA (LTM)", F["ev_ebitda"]), ("EBITDA margin (LTM)", F["ebitda_margin"])]
for col, (label, f) in zip(cols, tiles):
    col.metric(label, fmt(f), help=why(f) or f.formula)
if t.low_52w and t.low_52w.ok:
    st.caption(md(f"52-week range {fmt(t.low_52w)} to {fmt(t.high_52w)} · price as of {F['price'].as_of}"))
sources_panel("snapshot", {label: f for label, f in tiles}, t.cik, "snap")

# ---- financial summary (FD-4: last two fiscal years + LTM) ------------------------------

st.subheader("Financial summary")
fy_ends = sorted(m.fiscal_years)
periods = [(f"FY{e.year} (ended {e})", m.fiscal_years[e]) for e in fy_ends]
ltm = {"revenue": F["ltm_revenue"], "operating_income": F["ltm_operating_income"],
       "d_and_a": F["ltm_d_and_a"], "ebitda": F["ltm_ebitda"], "ebitda_margin": F["ebitda_margin"],
       "net_income": F["ltm_net_income"], "sbc": F["ltm_sbc"]}
periods.append((f"LTM ({m.ltm_end})", ltm))
rows = [("Revenue", "revenue"), ("Operating income (EBIT)", "operating_income"), ("D&A", "d_and_a"),
        ("EBITDA (FD-1)", "ebitda"), ("EBITDA margin", "ebitda_margin"), ("Net income", "net_income"),
        ("Stock-based comp (not added back)", "sbc")]
table = pd.DataFrame({p: [fmt(d.get(k)) for _, k in rows] for p, d in periods},
                     index=[r for r, _ in rows])
show(table)
growth = [("Revenue growth, LTM vs prior LTM", F["revenue_growth_ltm"]),
          ("Revenue growth, last fiscal year", F["revenue_growth_fy"])]
st.caption(md(" · ".join(f"{label}: {fmt(f)}" + (f" ({why(f)})" if why(f) else "") for label, f in growth)))

chart_periods = [(p, d) for p, d in periods if d.get("revenue") and d["revenue"].ok]
if chart_periods:
    fig = go.Figure()
    for name, key, color in (("Revenue", "revenue", BLUE), ("EBITDA", "ebitda", ORANGE)):
        xs, ys, texts = [], [], []
        for p, d in chart_periods:
            f = d.get(key)
            xs.append(p.split(" (")[0])
            ys.append(f.value / 1e9 if f and f.ok else None)
            texts.append(fmt(f))
        fig.add_bar(name=name, x=xs, y=ys, marker_color=color, text=texts, textposition="outside",
                    hovertemplate="%{x}<br>" + name + ": %{text}<extra></extra>")
    fig.update_layout(barmode="group", bargap=0.35, bargroupgap=0.08, height=340,
                      margin=dict(l=10, r=10, t=30, b=10), yaxis_title="USD bn",
                      legend=dict(orientation="h", y=1.12, x=0))
    fig.update_traces(marker_line_width=0, cliponaxis=False)
    st.plotly_chart(fig, width="stretch", theme="streamlit")

fin_figs = {f"{label}, {p}": d[k] for p, d in periods for label, k in rows if d.get(k) is not None}
fin_figs.update({label: f for label, f in growth})
sources_panel("financial summary", fin_figs, t.cik, "fin")

# ---- EV bridge (FD-2, FD-3) ----------------------------------------------------------------

st.subheader("Enterprise value bridge")
bridge = [("Share price", F["price"]), ("× Shares outstanding (cover page, FD-3)", F["shares_outstanding"]),
          ("= Equity value", F["equity_value"]), ("+ Total debt incl. finance leases (FD-2)", F["total_debt"]),
          ("+ Preferred stock", F["preferred_stock"]), ("+ Noncontrolling interest", F["noncontrolling_interest"]),
          ("− Cash and equivalents", F["cash"]), ("− Short-term investments", F["short_term_investments"]),
          ("= Enterprise value", F["enterprise_value"]), ("Net debt", F["net_debt"]),
          ("Net debt / LTM EBITDA", F["net_debt_ebitda"])]
show(pd.DataFrame({"value": [fmt(f) for _, f in bridge], "as of": [str(f.as_of or "") for _, f in bridge],
                   "note": [why(f) for _, f in bridge]}, index=[l for l, _ in bridge]), wide=("note",))
chk = F["share_count_check"]
st.caption(md(f"Cross-check: diluted weighted-average shares {fmt(F['diluted_shares'])} vs cover-page "
           f"{fmt(F['shares_outstanding'])} ({fmt(chk)} difference)."
           + (" Flag: more than 3% apart (FD-3)." if chk.notes else "")))
sources_panel("EV bridge", {l: f for l, f in bridge} | {"Diluted shares (cross-check)": F["diluted_shares"]},
              t.cik, "ev")

# ---- comps (FD-5, FD-6, FD-7) ---------------------------------------------------------------

st.subheader("Trading comps")
c = rep.comps
if not c.peers:
    st.info("Add peer tickers above to build the comps table and implied valuation.")
else:
    columns = ["equity_value", "enterprise_value", *MULTIPLES, *CONTEXT]
    body, footnotes = [], []
    for row in [t, *c.peers]:
        name = f"{row.ticker} (target)" if row is t else row.ticker
        if row.metrics is None:
            body.append({"Company": name, "LTM end": "", **{LABELS[k]: "" for k in columns},
                         "Status": row.error})
            footnotes.append(f"{row.ticker}: left out of the comps, {row.error}")
            continue
        line = {"Company": name, "LTM end": str(row.metrics.ltm_end)}
        for k in columns:
            f = row.get(k)
            line[LABELS[k]] = fmt(f)
            if f.value is None and f.reason:
                footnotes.append(f"{row.ticker} {LABELS[k]}: {'NM' if f.nm else 'n/a'}, {why(f)}")
        line["Status"] = ""
        body.append(line)
    for label, attr in (("25th percentile", "p25"), ("Median", "median"), ("Mean", "mean"),
                        ("75th percentile", "p75")):
        line = {"Company": f"Peers: {label}", "LTM end": ""}
        for k in columns:
            s = c.stats.get(k)
            v = getattr(s, attr) if s else None
            unit = "ratio" if k in ("revenue_growth_ltm", "ebitda_margin") else "x"
            line[LABELS[k]] = "" if s is None else ("n/a" if v is None else fmt(Figure("s", v, unit, "")))
        line["Status"] = f"n = {c.stats['ev_ebitda'].n} for EV/EBITDA"
        body.append(line)
    show(pd.DataFrame(body), label=None, Company=st.column_config.TextColumn("Company", width=200, pinned=True),
         Status=st.column_config.TextColumn("Status", width="large"))
    st.caption("Statistics use non-NM peer values only (FD-7); the target is excluded. "
               "NM = negative or zero denominator, a negative multiple, or above 100x (FD-6).")
    if footnotes or c.notes:
        with st.expander(f"Footnotes ({len(footnotes) + len(c.notes)})"):
            for n in c.notes + footnotes:
                st.markdown(md(f"- {n}"))
    comp_figs = {}
    for row in c.peers:
        if row.metrics is not None:
            for k in columns:
                comp_figs[f"{row.ticker}: {LABELS[k]}"] = row.get(k)
    peer_ciks = {r.ticker: r.cik for r in c.peers}
    with st.expander("Sources: comps"):
        if comp_figs:
            choice = st.selectbox("Number", list(comp_figs), key="src-comps")
            f = comp_figs[choice]
            st.code("\n".join(formula_tree(f)), language=None)
            rows_ = fact_rows(f, peer_ciks.get(choice.split(":")[0]))
            if rows_:
                st.dataframe(pd.DataFrame(rows_), hide_index=True, width="stretch",
                             column_config={"link": st.column_config.LinkColumn("filing", display_text="open"),
                                            "value": st.column_config.NumberColumn(format="%,.0f")})
            for s in other_sources(f):
                st.caption(s)
            for n in f.all_notes():
                st.markdown(md(f"- {n}"))

    # ---- implied valuation (FD-8) + football field ------------------------------------------
    st.subheader("Implied valuation (FD-8)")
    imp_rows, imp_figs = [], {}
    for key, r in c.implied.items():
        lo, mid, hi = r.share_price
        imp_rows.append({
            "Method": LABELS[key],
            "Peer 25th-75th": "n/a" if r.low_multiple is None else f"{r.low_multiple:.1f}x - {r.high_multiple:.1f}x",
            "Target LTM metric": f"{BASE_LABELS[VALUATION_BASES[key]]} {fmt(r.target_metric)}",
            "Implied EV": f"{fmt(r.enterprise_value[0])} - {fmt(r.enterprise_value[2])}",
            "Implied price": f"{fmt(lo)} - {fmt(hi)}",
            "At peer median": fmt(mid),
            "Note": r.reason or why(lo) or why(hi),
        })
        for point, i in (("25th pct", 0), ("median", 1), ("75th pct", 2)):
            imp_figs[f"{LABELS[key]} {point}: implied price"] = r.share_price[i]
    show(pd.DataFrame(imp_rows), label=None, Note=st.column_config.TextColumn("Note", width="large"))

    bars = c.football_field()
    usable = [b for b in bars if b["low"] is not None and b["high"] is not None]
    if usable:
        ff = go.Figure()
        price = F["price"].value
        for b in reversed(usable):
            if b["label"] == "Current price":
                continue
            color = GRAY if b["label"] == "52-week range" else BLUE
            ff.add_bar(y=[b["label"]], x=[b["high"] - b["low"]], base=[b["low"]], orientation="h",
                       marker_color=color, marker_line_width=0, width=0.5, showlegend=False,
                       text=[f"${b['low']:,.0f} - ${b['high']:,.0f}"], textposition="outside",
                       hovertemplate=f"{b['label']}: ${b['low']:,.2f} to ${b['high']:,.2f}<extra></extra>")
        if price:
            ff.add_vline(x=price, line_width=2, line_dash="dot", line_color=ORANGE,
                         annotation_text=f"Current ${price:,.2f}", annotation_position="top")
        ff.update_layout(height=80 + 70 * len(usable), margin=dict(l=10, r=40, t=40, b=10),
                         xaxis_title="Share price (USD)", xaxis_tickprefix="$")
        ff.update_traces(cliponaxis=False)
        st.plotly_chart(ff, width="stretch", theme="streamlit")
        st.caption("Blue bars: target's LTM metric × peer 25th-75th percentile multiple, bridged back to "
                   "equity value and divided by cover-page shares. Gray: 52-week trading range.")
    skipped = [b for b in bars if b not in usable]
    for b in skipped:
        st.caption(md(f"{b['label']}: not shown ({b['reason']})"))
    sources_panel("implied valuation", imp_figs, t.cik, "imp")

# ---- every flag in one place -----------------------------------------------------------------

all_notes = []
for f in list(F.values()) + [f for fy in m.fiscal_years.values() for f in fy.values()]:
    for n in f.all_notes():
        if n not in all_notes:
            all_notes.append(n)
if all_notes:
    with st.expander(f"Data notes for {t.ticker} ({len(all_notes)})"):
        for n in all_notes:
            st.markdown(md(f"- {n}"))
