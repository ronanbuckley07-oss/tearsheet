"""Print Phase 2 metrics for a ticker, with formulas and notes.

Usage: python scripts/inspect_metrics.py AAPL [--sources]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import market, metrics  # noqa: E402
from engine.sec_client import SECClient  # noqa: E402
from engine.tickers import get_metadata, lookup  # noqa: E402
from engine.xbrl import get_series  # noqa: E402


def fmt(f):
    if f.value is None:
        if f.nm:
            extra = f" [{f.raw_value:.1f}x]" if f.raw_value is not None else ""
            return f"NM ({f.reason}){extra}"
        return f"n/a ({f.reason})"
    if f.unit == "USD":
        return f"{f.value / 1e6:,.0f}m"
    if f.unit == "shares":
        return f"{f.value / 1e6:,.1f}m sh"
    if f.unit == "x":
        return f"{f.value:.1f}x"
    if f.unit == "ratio":
        return f"{f.value:.1%}"
    return f"{f.value:,.2f}"


def show(label, f, sources):
    print(f"  {label:32} {fmt(f):>22}   {f.formula}")
    if sources:
        for sign, fact in f.facts:
            s = fact.source
            period = f"{fact.start}..{fact.end}" if fact.start else f"@{fact.end}"
            print(f"  {'':32} {'+' if sign > 0 else '-'} {fact.value / 1e6:>14,.1f}m  {period:24} "
                  f"{fact.tag} {s.form} {s.accession}")
        if f.source:
            print(f"  {'':32}   {f.source}")


def main(ticker, sources=False):
    client = SECClient()
    company = lookup(ticker, client)
    meta = get_metadata(company.cik, client)
    last = meta.latest("10-K", "10-Q")
    series = get_series(company.cik, client, meta)
    quote = market.get_quote(company.ticker)
    m = metrics.compute(series, last.report_date, quote.price)

    print(f"{company.name} ({company.ticker})  latest {last.form} {last.accession} period end {last.report_date}")
    print(f"Fiscal years: {', '.join(map(str, m.fiscal_year_ends))}\n")
    for name, f in m.figures.items():
        show(name, f, sources)
    for end, fy in m.fiscal_years.items():
        print(f"\n FY ending {end}")
        for name, f in fy.items():
            show(name, f, sources)
    notes = []
    for f in list(m.figures.values()) + [f for fy in m.fiscal_years.values() for f in fy.values()]:
        for n in f.all_notes():
            if n not in notes:
                notes.append(n)
    if notes:
        print("\nNotes:")
        for n in notes:
            print(f"  - {n}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(args[0] if args else "AAPL", sources="--sources" in sys.argv)
