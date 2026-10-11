"""Streamlit UI. No finance logic lives here; it only displays engine output.

Run with: streamlit run app.py
"""

from __future__ import annotations

import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from engine import dcf as dcf_mod
from engine import dcf_workbook, export, learn, market, pitch
from engine import report as report_mod
from engine import sector as sector_mod
from engine.comps import CONTEXT, MULTIPLES, VALUATION_BASES
from engine.periods import Figure, missing
from engine.presets import SECTORS, sector_of
from engine.sec_client import SECConfigError
from engine.sources import fact_rows, formula_tree, other_sources

st.set_page_config(page_title="Tearsheet", layout="wide")

# Hosted deploys keep settings in Streamlit secrets; the engine reads environment variables.
try:
    for _k in ("SEC_USER_NAME", "SEC_CONTACT_EMAIL", "ANTHROPIC_API_KEY"):
        if _k in st.secrets and not os.getenv(_k):
            os.environ[_k] = str(st.secrets[_k])
except Exception:  # no secrets file (local runs use .env)
    pass

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


def learning() -> bool:
    return bool(st.session_state.get("learn", False))


def show(df: pd.DataFrame, label: str = "", wide: tuple[str, ...] = (), explain=None, key: str | None = None,
         cik: int | None = None, clickable: bool | None = None, **config) -> None:
    """A table tall enough to show every row, with the row label as a wide first column.

    In learn mode, a table given ``explain(row_position, row_label, column)`` is clickable:
    clicking a cell shows what that number means, how it was calculated and what it moves.
    """
    labels = list(df.index) if label is not None else [None] * len(df)
    df = df.reset_index(names=label) if label is not None else df
    cfg = {label: st.column_config.TextColumn(label, width=290, pinned=True)} if label is not None else {}
    cfg.update({c: st.column_config.TextColumn(c, width="large") for c in wide})
    cfg.update(config)
    height = 35 * (len(df) + 1) + 3
    if not (explain and key and (learning() if clickable is None else clickable)):
        st.dataframe(df, hide_index=True, width="stretch", column_config=cfg, height=height)
        return
    event = st.dataframe(df, hide_index=True, width="stretch", column_config=cfg, height=height,
                         on_select="rerun", selection_mode="single-cell", key=f"click-{key}")
    cells = event.selection.get("cells", []) if event is not None else []
    if not cells:
        st.caption("Click any number in this table to see what it means and what it moves.")
        return
    row, col = cells[0]
    try:
        e = explain(row, labels[row], col)
    except Exception as exc:  # a teaching card must never take the page down
        e = None
        st.caption(f"No explanation for that cell ({type(exc).__name__}).")
    if e is not None:
        explain_card(e, cik)


def explain_card(e: learn.Explanation, cik: int | None = None, border: bool = True) -> None:
    """One number, explained: meaning, this company's numbers, the math, what moves it, sources."""
    with st.container(border=border):
        st.markdown(md(f"**{e.title}**" + (f" · {e.value}" if e.value else "")))
        st.markdown(md(f"**What it is.** {e.what}"))
        for line in e.here:
            st.markdown(md(f"- {line}"))
        if e.calc:
            st.markdown("**How it's calculated here**")
            st.code(e.calc, language=None, wrap_lines=True)
        if e.drivers:
            st.markdown(md(f"**What moves it.** {e.drivers}"))
        if e.feeds:
            st.markdown(md(f"**What it moves.** {e.feeds}"))
        if e.impact:
            st.markdown("**If it changes**")
            for line in e.impact:
                st.markdown(md(f"- {line}"))
        f = e.figure
        if f is not None and f.ok:
            rows = fact_rows(f, e.cik or cik)
            if rows:
                st.caption(f"Source filings ({len(rows)} XBRL fact(s); full trail in the Sources panel):")
                st.dataframe(pd.DataFrame(rows)[["", "tag", "period", "form", "filed", "link"]], hide_index=True,
                             width="stretch",
                             column_config={"link": st.column_config.LinkColumn("filing", display_text="open")})
            for s in other_sources(f):
                st.caption(md(s))


def tile(col, label: str, value: str, e: learn.Explanation | None, cik: int | None = None, **kw) -> None:
    """A metric tile; in learn mode it gets an Explain button that opens the explanation."""
    col.metric(label, value, **kw)
    if e is not None and learning():
        with col.popover("Explain", icon=":material/school:", width="stretch"):
            explain_card(e, cik, border=False)


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


def ripple_table(rows: list[learn.RippleRow]) -> None:
    def cell(v, unit):
        if v is None:
            return "n/a"
        return fmt(Figure("", v, unit, "")) if unit != "ratio" else f"{v:.1%}"

    def change(r: learn.RippleRow) -> str:
        if r.change is None:
            return ""
        if r.unchanged:
            return "no change"
        out = learn.signed(r.change, r.unit)
        return out + (f" ({r.change_pct:+.1%})" if r.change_pct is not None else "")

    show(pd.DataFrame({"before": [cell(r.before, r.unit) for r in rows],
                       "after": [cell(r.after, r.unit) for r in rows],
                       "change": [change(r) for r in rows]}, index=[r.line for r in rows]))


def impact_section(d: learn.DcfContext, ctx: learn.Context, sandbox: bool | None = None) -> None:
    """How each DCF input moves the value: tornado, a what-if, and the user's own edits vs defaults."""
    st.markdown("**What moves the value**")
    bars = learn.tornado(d)
    usable = [b_ for b_ in bars if b_.low is not None and b_.high is not None]
    base = d.result.share_price.value
    if usable:
        fig = go.Figure()
        labels = [f"{b_.label} ({b_.step})" for b_ in reversed(usable)]
        for name, attr, color in (("Input lowered", "low", ORANGE), ("Input raised", "high", BLUE)):
            vals = [getattr(b_, attr) for b_ in reversed(usable)]
            fig.add_bar(name=name, y=labels, x=[v - base for v in vals], base=base, orientation="h",
                        marker_color=color, marker_line_width=0,
                        text=[f"${v:,.0f}" for v in vals], textposition="outside", cliponaxis=False,
                        hovertemplate="%{y}: $%{text}<extra>" + name + "</extra>")
        fig.add_vline(x=base, line_width=1, line_color=GRAY,
                      annotation_text=f"Base ${base:,.2f}", annotation_position="top")
        fig.update_layout(barmode="overlay", height=90 + 38 * len(usable), margin=dict(l=10, r=50, t=40, b=10),
                          xaxis_title="DCF share price (USD)", xaxis_tickprefix="$",
                          legend=dict(orientation="h", y=-0.15, x=0))
        st.plotly_chart(fig, width="stretch", theme="streamlit")
        st.caption("Each bar reruns the full DCF with one input moved one step down (orange) and up (blue), "
                   "everything else held fixed: 1 percentage point for % inputs, 0.10 for beta, 0.5 points for "
                   "terminal growth (FD-14). Longest bar = the assumption to defend first.")
    for b_ in bars:
        if b_ not in usable:
            st.caption(md(f"{b_.label}: one step breaks the DCF (WACC falls to or below terminal growth, or "
                          "terminal cash flow turns negative), so it isn't drawn."))

    if learning() if sandbox is None else sandbox:
        st.markdown("**Try a change and watch everything move**")
        keys = [*dcf_mod.GROWTH_KEYS, *dcf_mod.OPERATING_KEYS, *dcf_mod.WACC_KEYS, "terminal_growth"]
        c1, c2 = st.columns([2, 1])
        k = c1.selectbox("Input", [k_ for k_ in keys if d.assumptions[k_].ok], key=f"whatif-key-{ctx.ticker}",
                         format_func=lambda k_: dcf_mod.LABELS[k_])
        cur = d.assumptions[k].value
        is_x = dcf_mod.UNITS[k] == "x"
        step = learn.step_for(k)
        new = c2.number_input(f"New value{'' if is_x else ' (%)'}",
                              value=round(cur + step if is_x else (cur + step) * 100, 2),
                              step=0.05 if is_x else 0.25, format="%.2f", key=f"whatif-val-{ctx.ticker}-{k}")
        new_v = new if is_x else new / 100
        after = learn.run_with(d, {k: new_v})
        st.caption(md(f"How it flows: {learn.chain(k)}"))
        if after.reason:
            st.warning(md(f"At that value the DCF stops working: {after.reason}"))
        else:
            ripple_table(learn.ripple(d.result, after, ctx.m))
            st.caption("This is a sandbox: the boxes above keep your current assumptions. Type the value into the "
                       "box above to keep it.")

    changed = learn.changed_keys(d)
    if changed:
        st.markdown("**What your edits did** (your assumptions vs the defaults)")
        st.caption(md("Changed: " + "; ".join(
            f"{dcf_mod.LABELS[k_]} {learn.value_text(d.defaults[k_])} → {learn.value_text(d.assumptions[k_])}"
            for k_ in changed)))
        before = learn.defaults_result(d)
        if before.reason:
            st.caption(md(f"The defaults don't produce a DCF ({before.reason}), so there is nothing to compare."))
        else:
            ripple_table(learn.ripple(before, d.result, ctx.m))


# Market data is cached per ticker, so changing a peer list or opening a company from the
# sector screen only fetches what's new. SEC responses are cached on disk by sec_client.
@st.cache_data(ttl=900, show_spinner=False)
def quote(ticker: str) -> market.Quote:
    return market.get_quote(ticker)


@st.cache_data(ttl=3600, show_spinner=False)
def risk_free() -> Figure:
    return market.get_risk_free()


@st.cache_data(ttl=3600, show_spinner=False)
def beta(ticker: str) -> Figure:
    return market.get_beta(ticker)


@st.cache_data(ttl=3600, show_spinner=False)
def load(target: str, peers: tuple[str, ...]):
    return report_mod.build_report(target, list(peers), get_quote=quote, get_risk_free=risk_free, get_beta=beta)


@st.cache_data(ttl=3600, show_spinner=False)
def load_sector(name: str, tickers: tuple[str, ...]):
    return report_mod.build_sector(name, list(tickers), get_quote=quote)


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

COMPANY, SECTOR, LEARN = "Company tearsheet", "Sector screen", "Learn"
view_col, learn_col = st.columns([3, 1])
mode = view_col.radio("View", [COMPANY, SECTOR, LEARN], horizontal=True, key="mode", label_visibility="collapsed",
                      help="Sector screen: line up a whole sector, find the stock to pitch, then open it as a "
                           "tearsheet with the rest of the sector as peers. Learn: a step-by-step course on "
                           "what every number means and how the DCF works, using a real company.")
if mode != LEARN:
    learn_col.toggle("Click-to-explain", value=False, key="learn",
                     help="Click any cell in a table, or Explain under a headline figure, to see what it means, "
                          "this company's math, and what changes if it moves. Off by default so the page stays "
                          "clean; the Learn view has the full course.")
if learning() and mode != LEARN:
    st.caption("Click-to-explain is on: click any number in a table, or **Explain** under a headline figure. "
               "All explanations are fixed templates filled with this company's computed numbers, not AI text.")


def open_tearsheet(ticker: str, tickers: list[str]) -> None:
    """Sector screen -> company tearsheet, with the rest of the screen as the peer list."""
    st.session_state["mode"] = COMPANY
    st.session_state["target"] = ticker
    st.session_state["peers_text"] = " ".join(t for t in tickers if t != ticker)


def fill_sector_tickers() -> None:
    name = st.session_state.get("sector_preset")
    if name in SECTORS:
        st.session_state["sector_text"] = " ".join(SECTORS[name])


def downloads(col_xlsx, col_pptx, name: str, xlsx: callable, pptx: callable) -> None:
    """Excel and PowerPoint download buttons; files are built only when this runs."""
    try:
        col_xlsx.download_button("Download Excel", xlsx(), file_name=f"{name}.xlsx", width="stretch",
                                 mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                 help="Numbers as numbers ($m), summary rows as Excel formulas, and a Sources sheet.")
        col_pptx.download_button("Download PowerPoint", pptx(), file_name=f"{name}.pptx", width="stretch",
                                 mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                                 help="16:9 slides with editable tables and charts, ready to restyle in your template.")
    except Exception as exc:  # an export bug must never take the page down
        col_xlsx.caption(f"Export failed: {type(exc).__name__}: {exc}")


def pct_or_none(f: Figure, scale: float = 1.0):
    return f.value * scale if f.ok else None


def render_sector() -> None:
    st.markdown("Pick a sector (or type your own list), compare every company side by side, then open the "
                "one you want to pitch as a full tearsheet.")
    st.selectbox("Start from a sector list", ["Custom", *SECTORS], key="sector_preset",
                 on_change=fill_sector_tickers,
                 help="Starter lists of US 10-K filers. Banks, insurers and REITs are left out: EV/EBITDA "
                      "doesn't describe them.")
    with st.form("sector"):
        text = st.text_area("Tickers (spaces or commas)", key="sector_text", height=68,
                            placeholder="e.g. NVDA AMD AVGO QCOM TXN")
        go_ = st.form_submit_button("Build sector screen", type="primary")
    if go_:
        st.session_state["sector_built"] = text
    built = st.session_state.get("sector_built", "")
    tickers = parse_peers(built)
    if not tickers:
        st.info("Choose a sector list or type tickers, then build the screen.")
        st.stop()
    preset = st.session_state.get("sector_preset")
    name = preset if preset in SECTORS and set(tickers) == set(SECTORS[preset]) else "Custom screen"
    try:
        with st.spinner(f"Pulling SEC filings and prices for {len(tickers)} companies..."):
            sec = load_sector(name, tuple(tickers))
    except SECConfigError as exc:
        st.error(str(exc))
        st.stop()
    rows = sec.loaded
    if not rows:
        st.error("None of those tickers loaded. " + " ".join(sec.notes))
        st.stop()

    st.header(f"{sec.name}: {len(rows)} companies")
    dl1, dl2, _ = st.columns([1, 1, 3])
    points = pitch.sector_points(sec)
    slug = sec.name.lower().replace(" ", "-").replace("&", "and")
    downloads(dl1, dl2, f"tearsheet-{slug}", lambda: export.sector_workbook(sec, points),
              lambda: export.sector_deck(sec, points))

    if points:
        st.subheader("Talking points")
        st.caption("Generated from the table below by fixed templates, not by an AI. Check each one before you use it.")
        for p in points:
            st.markdown(md(f"- {p}"))

    # Sortable table: numbers stay numbers so a column header click sorts it.
    st.subheader("Side by side")
    table = []
    for r in rows:
        line = {"Company": r.name, "Ticker": r.ticker, "LTM end": str(r.metrics.ltm_end)}
        for k in sector_mod.COLUMNS:
            f = r.get(k)
            unit = sector_mod.UNITS[k]
            line[sector_mod.LABELS[k]] = (f.value / 1e9 if f.ok else None) if unit == "USD" else \
                pct_or_none(f, 100) if unit == "ratio" else pct_or_none(f)
        for k in sector_mod.RELATIVE:
            line[f"{sector_mod.LABELS[k]} vs median"] = pct_or_none(sec.relative[r.ticker][k], 100)
        table.append(line)
    for label, attr in (("Median", "median"), ("25th percentile", "p25"), ("75th percentile", "p75")):
        line = {"Company": f"Sector: {label}", "Ticker": "", "LTM end": ""}
        for k in sector_mod.COLUMNS:
            v = getattr(sec.stats[k], attr)
            unit = sector_mod.UNITS[k]
            line[sector_mod.LABELS[k]] = None if v is None else v / 1e9 if unit == "USD" else \
                v * 100 if unit == "ratio" else v
        table.append(line)
    cfg = {"Company": st.column_config.TextColumn("Company", width=200, pinned=True)}
    for k in sector_mod.COLUMNS:
        unit, label = sector_mod.UNITS[k], sector_mod.LABELS[k]
        fmt_ = {"USD": "$%,.1fbn", "ratio": "%.1f%%", "x": "%.1fx"}[unit]
        cfg[label] = st.column_config.NumberColumn(label, format=fmt_)
    for k in sector_mod.RELATIVE:
        cfg[f"{sector_mod.LABELS[k]} vs median"] = st.column_config.NumberColumn(
            f"{sector_mod.LABELS[k]} vs median", format="%+.0f%%",
            help="Premium (+) or discount (-) to the sector median (FD-12).")
    by_label = {sector_mod.LABELS[k]: k for k in sector_mod.COLUMNS}
    by_label.update({f"{sector_mod.LABELS[k]} vs median": k for k in sector_mod.RELATIVE})

    def explain_sector(i: int, _label, col: str):
        key = by_label.get(col)
        if i >= len(rows):  # a statistics row
            stat = table[i]["Company"].removeprefix("Sector: ")
            if key is None:
                return None
            c_ = learn.CONCEPTS[learn.FIGURE_CONCEPT[key]]
            e = learn.Explanation(f"Sector {stat}: {sector_mod.LABELS[key]}", "", c_.what, drivers=c_.drivers,
                                  feeds=c_.feeds)
            s_ = sec.stats[key]
            e.here = [f"Over {s_.n} companies with a usable value: {', '.join(s_.included)}."] + [
                f"Left out: {tk} ({why_})." for tk, why_ in s_.excluded]
            return e
        r = rows[i]
        ctx = learn.Context(r.name, r.ticker, r.metrics, peer_stats=sec.stats)
        if key is None:
            return learn.Explanation(f"{r.name} ({r.ticker})", "", "One company in the screen. Click its numbers "
                                     "to see what each means, or open it as a full tearsheet below.")
        e = learn.explain_figure(key, r.get(key), ctx, f"{r.ticker}: {sector_mod.LABELS[key]}")
        e.cik = r.cik
        if col.endswith("vs median"):
            rel = sec.relative[r.ticker][key]
            e.title, e.value = f"{r.ticker}: {col}", "n/a" if not rel.ok else f"{rel.value:+.0%}"
            e.calc = rel.formula if rel.ok else None
            e.here.insert(0, "Premium (+) or discount (-) to the sector median: the company's multiple / the "
                             "median - 1 (FD-12). A discount can mean cheap, or that the market expects less growth "
                             "or lower margins: check those columns before calling it cheap.")
        return e

    show(pd.DataFrame(table), label=None, explain=explain_sector, key="sector-table", **cfg)
    st.caption("Click a column header to sort. None = NM or n/a; every reason is listed under Footnotes. "
               "Statistics use every company with a usable value (FD-12; NM rules as FD-6/FD-7).")
    foot = list(sec.notes)
    for r in rows:
        for k in sector_mod.COLUMNS:
            f = r.get(k)
            if not f.ok and f.reason:
                foot.append(f"{r.ticker} {sector_mod.LABELS[k]}: {'NM' if f.nm else 'n/a'}, {why(f)}")
    if foot:
        with st.expander(f"Footnotes ({len(foot)})"):
            for n in foot:
                st.markdown(md(f"- {n}"))

    # Charts a pitch uses: who is cheap for their growth or margins, and the ranking.
    st.subheader("Charts")
    left, right = st.columns(2)
    with left:
        pairs = {f"{sector_mod.LABELS[y]} vs {sector_mod.LABELS[x]}": (x, y) for x, y in sector_mod.SCATTERS}
        x, y = pairs[st.selectbox("Scatter", list(pairs), key="sector-scatter")]
        fit = sector_mod.fit(rows, x, y)
        pts = [(r.ticker, r.get(x).value, r.get(y).value) for r in rows if r.get(x).ok and r.get(y).ok]
        fig = go.Figure()
        fig.add_scatter(x=[p[1] for p in pts], y=[p[2] for p in pts], text=[p[0] for p in pts],
                        mode="markers+text", textposition="top center", marker=dict(size=11, color=BLUE),
                        hovertemplate="%{text}<br>%{x:.1%}<br>%{y:.1f}x<extra></extra>", showlegend=False)
        if fit.slope is not None:
            xs = [min(p[1] for p in pts), max(p[1] for p in pts)]
            fig.add_scatter(x=xs, y=[fit.predict(v) for v in xs], mode="lines", showlegend=False,
                            line=dict(color=ORANGE, dash="dash"), hoverinfo="skip")
        fig.update_layout(height=420, margin=dict(l=10, r=10, t=30, b=10), xaxis_tickformat=".0%",
                          xaxis_title=sector_mod.LABELS[x], yaxis_title=sector_mod.LABELS[y], yaxis_ticksuffix="x")
        st.plotly_chart(fig, width="stretch", theme="streamlit")
        if fit.r2 is not None:
            st.caption(f"Dashed line: least-squares fit over {fit.n} companies, R² = {fit.r2:.2f}. "
                       "Companies below the line are cheaper than their peers for the same "
                       f"{sector_mod.LABELS[x].lower()}; above it, richer.")
        else:
            st.caption(f"Need at least 3 companies with both values for a fitted line ({fit.n} have them).")
    with right:
        rankable = [k for k in sector_mod.COLUMNS if k not in ("ltm_revenue",)]
        key = st.selectbox("Rank by", rankable, index=rankable.index("ev_ebitda"), key="sector-rank",
                           format_func=lambda k: sector_mod.LABELS[k])
        ranked = sec.rank(key)
        unit = sector_mod.UNITS[key]
        conv = (lambda v: v / 1e9) if unit == "USD" else (lambda v: v)
        texts = [fmt(Figure("", v, unit, "")) for _, v in ranked]
        fig = go.Figure(go.Bar(x=[t for t, _ in ranked], y=[conv(v) for _, v in ranked], marker_color=BLUE,
                               text=texts, textposition="outside", marker_line_width=0, cliponaxis=False,
                               hovertemplate="%{x}: %{text}<extra></extra>"))
        med = sec.stats[key].median
        if med is not None:
            fig.add_hline(y=conv(med), line_dash="dot", line_color=ORANGE,
                          annotation_text=f"median {fmt(Figure('', med, unit, ''))}", annotation_position="top right")
        fig.update_layout(height=420, margin=dict(l=10, r=10, t=30, b=10),
                          yaxis_tickformat=".0%" if unit == "ratio" else None,
                          yaxis_title="USD bn" if unit == "USD" else None)
        st.plotly_chart(fig, width="stretch", theme="streamlit")
        excluded = sec.stats[key].excluded
        if excluded:
            st.caption(md("Not shown (NM or n/a): " + ", ".join(t for t, _ in excluded) + "."))

    with st.expander("Sources: sector screen"):
        figs = {f"{r.ticker}: {sector_mod.LABELS[k]}": (r, r.get(k)) for r in rows for k in sector_mod.COLUMNS}
        choice = st.selectbox("Number", list(figs), key="src-sector")
        r, f = figs[choice]
        st.code("\n".join(formula_tree(f)), language=None)
        facts = fact_rows(f, r.cik)
        if facts:
            st.dataframe(pd.DataFrame(facts), hide_index=True, width="stretch",
                         column_config={"link": st.column_config.LinkColumn("filing", display_text="open"),
                                        "value": st.column_config.NumberColumn(format="%,.0f")})
        for line in other_sources(f):
            st.caption(line)
        for n in f.all_notes():
            st.markdown(md(f"- {n}"))

    st.subheader("Deep dive")
    pick = st.selectbox("Company to pitch", [r.ticker for r in rows], key="sector-pick",
                        format_func=lambda t: f"{t} ({next(r.name for r in rows if r.ticker == t)})")
    st.button(f"Open {pick} as a full tearsheet (rest of the screen as peers)", type="primary",
              on_click=open_tearsheet, args=(pick, [r.ticker for r in rows]))


def show_steps(steps: list[learn.Step]) -> None:
    for step in steps:
        st.markdown(md(f"**{step.title}**  \n{step.text}"))
        if step.math:
            st.code("\n".join(step.math), language=None, wrap_lines=True)


def render_learn() -> None:
    """A course on the tearsheet and the DCF, on its own page, illustrated with a real company."""
    st.header("Learn: how a tearsheet and a DCF work")
    st.markdown("A short course, one chapter at a time. Each chapter explains the idea, then shows it on a real "
                "company's numbers from its SEC filings, then asks the questions an interviewer would. "
                "Nothing here changes your tearsheet.")
    c1, c2 = st.columns([1, 3])
    default = st.session_state.get("target") or "NVDA"
    ticker = c1.text_input("Example company (ticker)", value=default, key="learn_ticker").strip().upper()
    if ticker == st.session_state.get("target") and st.session_state.get("peers_text"):
        peers = parse_peers(st.session_state["peers_text"])
        c2.caption(md(f"Peers: your tearsheet's list ({', '.join(peers)})."))
    else:
        home = sector_of(ticker)
        peers = [p for p in SECTORS.get(home, []) if p != ticker]
        c2.caption(md(f"Peers: the starter list \"{home}\"." if home else
                      "No starter peer list for this ticker, so the comps chapter will be empty. Build its "
                      "tearsheet with peers first, then come back."))

    names = [ch.title for ch in learn.COURSE] + ["Glossary: every term"]
    nav, body = st.columns([1, 3], gap="large")
    pick = nav.radio("Chapter", names, key="learn_chapter")
    i = names.index(pick)

    def go(j: int) -> None:
        st.session_state["learn_chapter"] = names[j]

    with body:
        if i == len(learn.COURSE):
            st.subheader("Glossary")
            for key, c_ in learn.CONCEPTS.items():
                with st.expander(c_.title):
                    st.markdown(md(f"**What it is.** {c_.what}"))
                    st.markdown(md(f"**What moves it.** {c_.drivers}"))
                    st.markdown(md(f"**What it moves.** {c_.feeds}"))
        else:
            ch = learn.COURSE[i]
            st.subheader(ch.title)
            for para in ch.intro:
                st.markdown(md(para))
            if ch.figures or ch.special:
                learn_examples(ch, ticker, peers)
            if ch.questions:
                st.markdown("**Check yourself**")
                for q, a in ch.questions:
                    with st.expander(q):
                        st.markdown(md(a))
        b1, _, b2 = st.columns([1, 2, 1])
        if i > 0:
            b1.button(f"← {names[i - 1]}", on_click=go, args=(i - 1,), width="stretch", key="learn_prev")
        if i < len(names) - 1:
            b2.button(f"{names[i + 1]} →", on_click=go, args=(i + 1,), width="stretch", key="learn_next",
                      type="primary")


def learn_examples(ch: learn.Chapter, ticker: str, peers: list[str]) -> None:
    """The chapter's worked examples, on the example company's real numbers."""
    if not ticker:
        st.info("Type a ticker above to see these ideas on a real company.")
        return
    try:
        with st.spinner(f"Pulling {ticker}'s filings and prices..."):
            rep_ = load(ticker, tuple(peers))
    except SECConfigError as exc:
        st.error(str(exc))
        return
    t_ = rep_.target
    if t_.metrics is None:
        st.warning(f"{ticker}: {t_.error}")
        return
    m_ = t_.metrics
    ctx_ = learn.Context(t_.name, t_.ticker, m_, peer_stats=rep_.comps.stats)
    st.markdown(md(f"**On {t_.name} ({t_.ticker})**, LTM through {m_.ltm_end}:"))
    for n, key in enumerate(ch.figures):
        e = learn.explain_figure(key, m_.figures[key], ctx_)
        with st.expander(f"{e.title}: {e.value}", expanded=n == 0):
            explain_card(e, t_.cik, border=False)
    if ch.special == "comps":
        c_ = rep_.comps
        if not c_.peers:
            st.info("No peers loaded for this company, so there is nothing to compare against.")
            return
        s_ = c_.stats.get("ev_ebitda")
        if s_ and s_.n:
            e = learn.explain_peer_stat("ev_ebitda", "median", s_.median, s_, ctx_, "EV/EBITDA")
            with st.expander(f"Peer EV/EBITDA: median {e.value}", expanded=True):
                explain_card(e, border=False)
        for key, r in c_.implied.items():
            for point, name in ((0, "25th percentile"), (1, "median"), (2, "75th percentile")):
                e = learn.explain_implied(r, point, ctx_, LABELS[key])
                with st.expander(f"{LABELS[key]} at the peer {name}: {e.value}", expanded=key == "ev_ebitda" and
                                 point == 1):
                    explain_card(e, t_.cik, border=False)
        return
    if ch.special in ("dcf", "drivers"):
        b_ = rep_.dcf_base
        if b_ is None:
            st.info("The DCF needs this company's filings, which didn't load.")
            return
        a_ = dcf_mod.default_assumptions(b_, m_)
        res_ = dcf_mod.run(a_, m_, b_, False, steady_state=True)
        d_ = learn.DcfContext(res_, a_, a_, m_, b_, False, True)
        ctx_.dcf = d_
        if ch.special == "dcf":
            show_steps(learn.walkthrough(d_, ctx_))
            if not res_.reason:
                st.markdown("**Click any number in the model to see that cell's arithmetic**")
                years = [f"Year {y.n}" for y in res_.years]
                lines = {row: [getattr(y, attr) for y in res_.years] for row, (_, attr) in learn.DCF_ROWS.items()}
                cell = {"growth": learn.pct, "period": lambda v: f"{v:g}", "discount_factor": lambda v: f"{v:.3f}"}
                table = pd.DataFrame({row: [cell.get(attr, learn.money)(v) for v in lines[row]]
                                      for row, (_, attr) in learn.DCF_ROWS.items()}, index=years).T
                show(table, explain=lambda r, label, col: learn.explain_dcf_cell(label, col, d_, ctx_),
                     key="learn-dcf", cik=t_.cik, clickable=True)
        elif res_.reason:
            st.warning(md(f"The DCF can't run on the defaults: {res_.reason}"))
        else:
            impact_section(d_, ctx_, sandbox=True)


if mode == LEARN:
    render_learn()
    st.stop()

if mode == SECTOR:
    render_sector()
    st.stop()


def fill_peers() -> None:
    name = st.session_state.get("peer_preset")
    if name in SECTORS:
        target_ = st.session_state.get("target", "")
        st.session_state["peers_text"] = " ".join(t for t in SECTORS[name] if t != target_)


st.selectbox("Fill peers from a sector list (optional)", ["Choose a list", *SECTORS], key="peer_preset",
             on_change=fill_peers, help="Replaces the peer box with that sector's tickers. Edit it before building.")

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
ctx = learn.Context(t.name, t.ticker, m, peer_stats=rep.comps.stats)

# ---- snapshot -----------------------------------------------------------------------------

st.header(f"{t.name} ({t.ticker})")
dl_box = st.container()  # Excel / PowerPoint buttons, filled once the DCF below has run
fye = f"{t.fiscal_year_end[:2]}/{t.fiscal_year_end[2:]}" if t.fiscal_year_end else "n/a"
st.caption(f"{t.sic_description or 'Industry n/a'} · Fiscal year ends {fye} (month/day) · "
           f"LTM through {m.ltm_end} · Latest filing {t.latest_filing}")

cols = st.columns(6)
tile_keys = ["price", "equity_value", "enterprise_value", "ltm_revenue", "ev_ebitda", "ebitda_margin"]
tiles = [("Share price", F["price"]), ("Equity value", F["equity_value"]),
         ("Enterprise value", F["enterprise_value"]), ("LTM revenue", F["ltm_revenue"]),
         ("EV/EBITDA (LTM)", F["ev_ebitda"]), ("EBITDA margin (LTM)", F["ebitda_margin"])]
for col, k, (label, f) in zip(cols, tile_keys, tiles):
    tile(col, label, fmt(f), learn.explain_figure(k, f, ctx, label), t.cik, help=why(f) or f.formula)
if t.low_52w and t.low_52w.ok:
    st.caption(md(f"52-week range {fmt(t.low_52w)} to {fmt(t.high_52w)} · price as of {F['price'].as_of}"))
sources_panel("snapshot", {label: f for label, f in tiles}, t.cik, "snap")
points_box = st.container()  # talking points, filled at the end (they cite the DCF)

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


def explain_financials(i: int, label: str, col: str):
    key = rows[i][1]
    d = dict(periods).get(col)
    if d is None:  # the row label itself
        c_ = learn.CONCEPTS[learn.FIGURE_CONCEPT[key]]
        return learn.Explanation(label, "", c_.what, drivers=c_.drivers, feeds=c_.feeds)
    if col.startswith("LTM"):
        key = {"revenue": "ltm_revenue", "operating_income": "ltm_operating_income", "d_and_a": "ltm_d_and_a",
               "ebitda": "ltm_ebitda", "net_income": "ltm_net_income", "sbc": "ltm_sbc"}.get(key, key)
    e = learn.explain_figure(key, d.get(rows[i][1]), ctx, f"{label}, {col}")
    if col.startswith("LTM"):
        e.here.insert(0, "LTM (last twelve months) = latest fiscal year + this year's year-to-date - last year's "
                         "same year-to-date, so it is always a full, current year (FD-4).")
    return e


show(table, explain=explain_financials, key="fin", cik=t.cik)
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
bridge_keys = ["price", "shares_outstanding", "equity_value", "total_debt", "preferred_stock",
               "noncontrolling_interest", "cash", "short_term_investments", "enterprise_value", "net_debt",
               "net_debt_ebitda"]
show(pd.DataFrame({"value": [fmt(f) for _, f in bridge], "as of": [str(f.as_of or "") for _, f in bridge],
                   "note": [why(f) for _, f in bridge]}, index=[l for l, _ in bridge]), wide=("note",),
     explain=lambda i, label, col: learn.explain_figure(bridge_keys[i], bridge[i][1], ctx, label.lstrip("×=+−- ")),
     key="ev", cik=t.cik)
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
    home = sector_of(t.ticker)
    st.info("Add peer tickers above to build the comps table and implied valuation."
            + (f" {t.ticker} is in the starter list \"{home}\": pick it in \"Fill peers from a sector list\"."
               if home else ""))
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
    comp_rows = [t, *c.peers]
    by_label = {LABELS[k]: k for k in columns}
    stat_attrs = {"25th percentile": "p25", "Median": "median", "Mean": "mean", "75th percentile": "p75"}

    def explain_comps(i: int, _label, col: str):
        key = by_label.get(col)
        if i >= len(comp_rows):
            stat = body[i]["Company"].removeprefix("Peers: ")
            s_ = c.stats.get(key) if key else None
            if s_ is None:
                return None
            return learn.explain_peer_stat(key, stat, getattr(s_, stat_attrs[stat]), s_, ctx, col)
        r = comp_rows[i]
        if r.metrics is None:
            return learn.Explanation(r.ticker, "", f"{r.ticker} couldn't be used: {r.error}.")
        if key is None:
            return learn.Explanation(f"{r.name} ({r.ticker})", "", "A row of the comps table: one company's size, "
                                     "valuation multiples and the operating numbers that explain them. Click a "
                                     "number to see what it means.")
        rctx = learn.Context(r.name, r.ticker, r.metrics, peer_stats=c.stats)
        e = learn.explain_figure(key, r.get(key), rctx, f"{r.ticker}: {col}")
        e.cik = r.cik
        return e

    show(pd.DataFrame(body), label=None, explain=explain_comps, key="comps",
         Company=st.column_config.TextColumn("Company", width=200, pinned=True),
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

    # ---- implied valuation (FD-8) ------------------------------------------
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
    imp_keys = list(c.implied)

    def explain_implied(i: int, _label, col: str):
        point = {"Implied price": 0, "At peer median": 1}.get(col, 1)
        e = learn.explain_implied(c.implied[imp_keys[i]], point, ctx, LABELS[imp_keys[i]])
        if col == "Implied price":  # the cell is a range: explain both ends
            hi = learn.explain_implied(c.implied[imp_keys[i]], 2, ctx, LABELS[imp_keys[i]])
            e.title = f"Implied price range from {LABELS[imp_keys[i]]}"
            e.value = f"{e.value} - {hi.value}"
            e.here += hi.here[:2]
        return e

    show(pd.DataFrame(imp_rows), label=None, explain=explain_implied, key="implied", cik=t.cik,
         Note=st.column_config.TextColumn("Note", width="large"))

    sources_panel("implied valuation", imp_figs, t.cik, "imp")

# ---- DCF (FD-11) -------------------------------------------------------------------------------

st.subheader("Discounted cash flow (FD-11)")
dcf_bar = dcf_export = None
b = rep.dcf_base
if b is None:
    st.info("The DCF needs the target's filings, which didn't load.")
else:
    st.caption(md(
        "A DCF values the business on the cash it will produce for all investors (unlevered free cash flow), "
        "discounted at their required return (WACC), plus a terminal value for the years after year 5. "
        "History comes from the filings; the forecast is assumptions. Each box starts from the company's "
        "own history or a stated convention (hover the ? to see which) and you can change any of them."))
    defaults = dcf_mod.default_assumptions(b, m)
    keys = [*dcf_mod.GROWTH_KEYS, *dcf_mod.OPERATING_KEYS, *dcf_mod.WACC_KEYS, "terminal_growth"]
    skey = lambda k: f"dcf-{t.ticker}-{k}"  # noqa: E731
    if st.button("Reset assumptions to defaults", key=f"dcf-reset-{t.ticker}"):
        for k in keys + ["mid_year", "steady"]:
            st.session_state.pop(skey(k), None)

    def shown(f: Figure, key: str) -> float | None:
        """Default as displayed: percent with 2 decimals, beta with 2 decimals."""
        if f.value is None:
            return None
        return round(f.value if dcf_mod.UNITS[key] == "x" else f.value * 100, 2)

    assume: dict[str, Figure] = {}

    def box(col, key: str, label: str | None = None) -> None:
        d = defaults[key]
        is_x = dcf_mod.UNITS[key] == "x"
        v = col.number_input(label or dcf_mod.LABELS[key] + ("" if is_x else " (%)"), value=shown(d, key),
                             step=0.05 if is_x else 0.25, format="%.2f", key=skey(key),
                             help=d.formula if d.ok else f"No default: {d.reason}")
        if v is None:
            assume[key] = missing(dcf_mod.LABELS[key], dcf_mod.UNITS[key], d.reason or "no value entered")
        elif v == shown(d, key):
            assume[key] = d
        else:
            assume[key] = dcf_mod.edited(key, v if is_x else v / 100, d)

    st.markdown("**Revenue growth**")
    for i, (col, k) in enumerate(zip(st.columns(dcf_mod.YEARS), dcf_mod.GROWTH_KEYS), 1):
        box(col, k, f"Year {i} (%)")
    st.markdown("**Operations** (each as a % of that year's revenue, except tax)")
    for col, k in zip(st.columns(5), dcf_mod.OPERATING_KEYS):
        box(col, k)
    st.markdown("**Discount rate and terminal value**")
    cols = st.columns(6)
    for col, k in zip(cols, [*dcf_mod.WACC_KEYS, "terminal_growth"]):
        box(col, k)
    mid_year = cols[5].toggle("Mid-year convention", key=skey("mid_year"),
                              help="Off: each year's cash arrives at year end. On: it arrives mid-year "
                                   "(discounted half a year less), which gives a slightly higher value. Banks use both.")
    steady = cols[5].toggle("Steady-state terminal year", value=True, key=skey("steady"),
                            help="On: if year-5 capex is above D&A, the terminal value uses capex = D&A. Spending "
                                 "above depreciation is growth investment, and a company growing only at the "
                                 "terminal rate forever doesn't keep building at that pace (FD-11).")

    for n in dict.fromkeys(n for f in assume.values() for n in f.notes):
        st.caption(md(f"Note: {n}"))
    res = dcf_mod.run(assume, m, b, mid_year, steady_state=steady)
    dctx = learn.DcfContext(res, assume, defaults, m, b, mid_year, steady)
    ctx.dcf = dctx
    if learning():
        pick_ = st.pills("Explain an assumption", keys, key=f"dcf-explain-{t.ticker}",
                         format_func=lambda k: dcf_mod.LABELS[k].replace("Revenue growth, year", "Growth yr"),
                         help="Pick any box above to see what it means, where its default came from, and what "
                              "happens to the value when it moves.")
        if pick_:
            e_ = learn.explain_assumption(pick_, dctx, ctx)
            e_.feeds = learn.chain(pick_)
            explain_card(e_, t.cik)
    if res.reason:
        st.warning(md(f"DCF not available: {res.reason}"))
    else:
        price_now = F["price"]
        up = (res.share_price.value / price_now.value - 1) if price_now.ok and res.share_price.ok else None
        tiles = st.columns(5)
        tile(tiles[0], "DCF share price", fmt(res.share_price), learn.explain_dcf_output("dcf_price", dctx, ctx),
             t.cik, delta=None if up is None else f"{up:+.1%} vs current", help=res.share_price.formula)
        tile(tiles[1], "DCF enterprise value", fmt(res.enterprise_value),
             learn.explain_dcf_output("dcf_ev", dctx, ctx), t.cik)
        tile(tiles[2], "WACC", fmt(res.wacc), learn.explain_dcf_output("wacc", dctx, ctx), t.cik,
             help=res.wacc.formula)
        tile(tiles[3], "Terminal value % of EV", f"{res.tv_share_of_ev:.0%}",
             learn.explain_dcf_output("tv_share", dctx, ctx), t.cik,
             help="Share of the value that comes from after year 5. Above ~75% means the answer "
                  "rests mostly on the terminal assumptions.")
        tile(tiles[4], "Implied exit multiple", "n/a" if res.implied_exit_multiple is None
             else f"{res.implied_exit_multiple:.1f}x", learn.explain_dcf_output("implied_exit", dctx, ctx), t.cik,
             help="Terminal value / year-5 EBITDA. Compare it with the peer EV/EBITDA multiples.")

        if learning():
            with st.expander(f"Step by step: how this DCF gets to {fmt(res.share_price)} per share"):
                show_steps(learn.walkthrough(dctx, ctx))

        for n in res.notes:
            st.caption(md(f"Check: {n}"))
        usd = lambda v: fmt(Figure("", v, "USD", ""))  # noqa: E731
        cols = ["LTM (base)"] + [f"Year {y.n}" for y in res.years] + ["Terminal year"]
        y5, tf = res.years[-1], res.terminal_fcf.value
        t_capex = y5.nopat + y5.d_and_a - y5.nwc_change - tf
        terminal = {"= NOPAT": usd(y5.nopat), "+ D&A": usd(y5.d_and_a), "− Capex": usd(-t_capex),
                    "− Increase in NWC": usd(-y5.nwc_change), "= Unlevered free cash flow": usd(tf)}
        lines = {
            "Revenue": [fmt(F["ltm_revenue"])] + [usd(y.revenue) for y in res.years],
            "Growth": [fmt(F["revenue_growth_ltm"])] + [f"{y.growth:.1%}" for y in res.years],
            "EBIT": [fmt(F["ltm_operating_income"])] + [usd(y.ebit) for y in res.years],
            "− Taxes on EBIT": [""] + [usd(-y.taxes) for y in res.years],
            "= NOPAT": [""] + [usd(y.nopat) for y in res.years],
            "+ D&A": [fmt(F["ltm_d_and_a"])] + [usd(y.d_and_a) for y in res.years],
            "− Capex": [""] + [usd(-y.capex) for y in res.years],
            "− Increase in NWC": [""] + [usd(-y.nwc_change) for y in res.years],
            "= Unlevered free cash flow": [""] + [usd(y.ufcf) for y in res.years],
            "Discount period (years)": [""] + [f"{y.period:g}" for y in res.years],
            "Discount factor": [""] + [f"{y.discount_factor:.3f}" for y in res.years],
            "PV of free cash flow": [""] + [usd(y.pv) for y in res.years],
        }
        lines = {k: v + [terminal.get(k, "")] for k, v in lines.items()}
        show(pd.DataFrame(lines, index=cols).T, explain=lambda i, label, col: learn.explain_dcf_cell(label, col, dctx, ctx),
             key=f"dcf-proj", cik=t.cik)
        if res.terminal_fcf.formula.startswith(f"year-{dcf_mod.YEARS} NOPAT"):
            st.caption(md(f"Terminal year: {res.terminal_fcf.formula}. The perpetuity grows from this cash flow."))

        left, right = st.columns(2)
        with left:
            st.markdown("**From enterprise value to share price**")
            bridge = [("PV of free cash flows", res.pv_fcf), ("+ PV of terminal value", res.pv_terminal),
                      ("= Enterprise value", res.enterprise_value),
                      ("− Total debt", F["total_debt"]), ("− Preferred stock", F["preferred_stock"]),
                      ("− Noncontrolling interest", F["noncontrolling_interest"]), ("+ Cash", F["cash"]),
                      ("+ Short-term investments", F["short_term_investments"]),
                      ("= Equity value", res.equity_value), ("÷ Shares outstanding", F["shares_outstanding"]),
                      ("= Share price", res.share_price)]
            dcf_bridge_keys = ["pv_fcf", "pv_terminal", "dcf_ev", "total_debt", "preferred_stock",
                               "noncontrolling_interest", "cash", "short_term_investments", "dcf_equity",
                               "shares_outstanding", "dcf_price"]

            def explain_dcf_bridge(i: int, label: str, _col):
                k_ = dcf_bridge_keys[i]
                if k_ in learn.FIGURE_CONCEPT:
                    return learn.explain_figure(k_, bridge[i][1], ctx, label.lstrip("=+−÷ "))
                return learn.explain_dcf_output(k_, dctx, ctx)

            show(pd.DataFrame({"value": [fmt(f) for _, f in bridge]}, index=[l for l, _ in bridge]),
                 explain=explain_dcf_bridge, key="dcf-bridge", cik=t.cik)
        with right:
            st.markdown("**WACC**")
            ke = res.cost_of_equity
            wacc_rows = [("Risk-free rate", assume["risk_free"]), ("× Beta", assume["beta"]),
                         ("× Equity risk premium", assume["erp"]), ("= Cost of equity (CAPM)", ke),
                         ("Pre-tax cost of debt", assume["cost_of_debt"]), ("Tax rate", assume["tax_rate"]),
                         ("Equity value (weight)", F["equity_value"]), ("Total debt (weight)", F["total_debt"]),
                         ("= WACC", res.wacc)]
            wacc_keys = ["risk_free", "beta", "erp", "cost_of_equity", "cost_of_debt", "tax_rate", "equity_value",
                         "total_debt", "wacc"]

            def explain_wacc(i: int, label: str, _col):
                k_ = wacc_keys[i]
                if k_ in assume:
                    return learn.explain_assumption(k_, dctx, ctx)
                if k_ in ("equity_value", "total_debt"):
                    e_ = learn.explain_figure(k_, wacc_rows[i][1], ctx, label)
                    E_, D_ = F["equity_value"].value or 0, F["total_debt"].value or 0
                    if E_ + D_:
                        e_.here.insert(0, f"Weight in WACC: {(E_ if k_ == 'equity_value' else D_) / (E_ + D_):.1%} "
                                          "(market equity value and total debt, FD-11).")
                    return e_
                return learn.explain_dcf_output(k_, dctx, ctx)

            show(pd.DataFrame({"value": [fmt(f) for _, f in wacc_rows]}, index=[l for l, _ in wacc_rows]),
                 explain=explain_wacc, key="dcf-wacc", cik=t.cik)
            if res.exit_price.ok:
                st.caption(md(
                    f"Cross-check: valuing year 5 at the peer median {b.peer_median_ev_ebitda.value:.1f}x EV/EBITDA "
                    f"instead gives {fmt(res.exit_price)} per share, which implies perpetual growth of "
                    f"{res.implied_growth_from_exit:.1%}."))
            else:
                st.caption(md(f"Exit-multiple cross-check: n/a ({res.exit_price.reason})."))

        st.markdown("**Sensitivity: share price by WACC (rows) and terminal growth (columns)**")
        ws, gs, grid = dcf_mod.sensitivity(assume, m, b, mid_year, steady_state=steady)
        sens = pd.DataFrame([[fmt(f) for f in row] for row in grid],
                            index=[f"{w:.2%}" for w in ws], columns=[f"g {g:.2%}" for g in gs])
        def explain_sens(i: int, _label, col: str):
            e_ = learn.explain("sensitivity", None, ctx, "Sensitivity table")
            if not col.startswith("g "):
                return e_
            j = list(sens.columns).index(col)
            f_ = grid[i][j]
            e_.title = f"Share price at WACC {ws[i]:.2%} and terminal growth {gs[j]:.2%}"
            e_.value = fmt(f_)
            e_.here = [f"Base case (centre cell): WACC {ws[2]:.2%}, g {gs[2]:.2%} → {fmt(grid[2][2])}."]
            if f_.ok and grid[2][2].ok:
                e_.here.append(f"This cell is {f_.value / grid[2][2].value - 1:+.1%} versus the base case"
                               + (f" and {f_.value / F['price'].value - 1:+.1%} versus the current price."
                                  if F["price"].ok else "."))
            elif not f_.ok:
                e_.here.append(f"n/a here: {f_.reason}.")
            e_.here.append("Read across a row: higher terminal growth raises value. Read down a column: higher "
                           "WACC lowers it. Both act mostly through the terminal value.")
            return e_

        show(sens, label="WACC", explain=explain_sens, key="dcf-sens")
        impact_section(dctx, ctx)
        dcf_bar = dcf_mod.football_bar(assume, m, b, mid_year, steady_state=steady)
        dcf_export = export.DcfExport(res, assume, dcf_mod.LABELS, (ws, gs, grid), mid_year, steady)

    sources_panel("DCF", {"DCF share price": res.share_price, "DCF enterprise value": res.enterprise_value,
                          "PV of terminal value": res.pv_terminal,
                          "Terminal-year free cash flow": res.terminal_fcf or res.pv_terminal, "WACC": res.wacc,
                          "Cost of equity": res.cost_of_equity}
                  | {dcf_mod.LABELS[k]: assume[k] for k in keys}
                  | {f"Net working capital, FY{y.end.year}": y.nwc for y in b.years}, t.cik, "dcf")

# ---- football field ----------------------------------------------------------------------------

st.subheader("Football field")
bars = c.football_field()
if dcf_bar is not None:
    bars.insert(len(c.implied), dcf_bar)
usable = [b_ for b_ in bars if b_["low"] is not None and b_["high"] is not None]
if usable:
    ff = go.Figure()
    price = F["price"].value
    for b_ in reversed(usable):
        if b_["label"] == "Current price":
            continue
        color = GRAY if b_["label"] == "52-week range" else BLUE
        ff.add_bar(y=[b_["label"]], x=[b_["high"] - b_["low"]], base=[b_["low"]], orientation="h",
                   marker_color=color, marker_line_width=0, width=0.5, showlegend=False,
                   text=[f"${b_['low']:,.0f} - ${b_['high']:,.0f}"], textposition="outside",
                   hovertemplate=f"{b_['label']}: ${b_['low']:,.2f} to ${b_['high']:,.2f}<extra></extra>")
    if price:
        ff.add_vline(x=price, line_width=2, line_dash="dot", line_color=ORANGE,
                     annotation_text=f"Current ${price:,.2f}", annotation_position="top")
    ff.update_layout(height=80 + 70 * len(usable), margin=dict(l=10, r=40, t=40, b=10),
                     xaxis_title="Share price (USD)", xaxis_tickprefix="$")
    ff.update_traces(cliponaxis=False)
    st.plotly_chart(ff, width="stretch", theme="streamlit")
    st.caption("Comps bars: target's LTM metric × peer 25th-75th percentile multiple, bridged back to equity "
               "value and divided by cover-page shares. DCF bar: the sensitivity table's corners at WACC ±1% "
               "and terminal growth ±0.5%. Gray: 52-week trading range.")
for b_ in bars:
    if b_ not in usable:
        st.caption(md(f"{b_['label']}: not shown ({b_['reason']})"))

# ---- talking points and exports (built from everything above) ----------------------------------

points = pitch.company_points(t, c, dcf_export.result.share_price if dcf_export else None)
if points:
    with points_box:
        st.subheader("Talking points")
        st.caption("Generated from this page's numbers by fixed templates, not by an AI. Check each one "
                   "against the tables before you use it.")
        for p in points:
            st.markdown(md(f"- {p}"))
with dl_box:
    d1, d2, d3, _ = st.columns([1, 1, 1.2, 1.8])
    downloads(d1, d2, f"tearsheet-{t.ticker}", lambda: export.report_workbook(rep, dcf_export, points),
              lambda: export.report_deck(rep, dcf_export, bars, points))
    if dcf_export is not None:
        try:
            d3.download_button("Download DCF model", dcf_workbook.dcf_workbook(rep, dcf_export),
                               file_name=f"DCF-{t.ticker}.xlsx", width="stretch", type="primary",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               help="Full banker-style DCF in Excel on the assumptions below: live formulas (blue "
                                    "inputs, black formulas), WACC build, perpetuity and exit-multiple values, "
                                    "sensitivity tables and a Sources sheet. Ties to this page's numbers.")
        except Exception as exc:  # an export bug must never take the page down
            d3.caption(f"DCF model export failed: {type(exc).__name__}: {exc}")

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
