"""Assembles everything into one report object.

This is the only engine module that fetches: SEC data (via sec_client) and the
share price (via market). Everything it returns is built by the pure modules
(xbrl, periods, metrics, comps), so app.py only has to display it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from engine import comps, market, metrics
from engine.comps import CompanyRow
from engine.sec_client import SECClient, SECError
from engine.tickers import TickerNotFound, get_metadata, lookup, normalize_ticker
from engine.xbrl import get_series


@dataclass
class Report:
    target: CompanyRow
    comps: comps.Comps


def load_company(ticker: str, client: SECClient,
                 get_quote: Callable[[str], market.Quote] = market.get_quote) -> CompanyRow:
    """Fetch and compute one company. Never raises for bad input: the row carries the reason."""
    t = normalize_ticker(ticker)
    try:
        company = lookup(t, client)
    except TickerNotFound:
        return CompanyRow(t, t, None, error="not in the SEC ticker list")
    try:
        meta = get_metadata(company.cik, client)
        if not meta.in_scope:
            kind = "files 20-F/40-F (foreign filer)" if meta.files_foreign_annual else "doesn't file 10-Ks"
            return CompanyRow(t, company.name, None, error=f"{kind}; v1 covers 10-K filers only")
        last = meta.latest("10-K", "10-Q")
        if last is None or last.report_date is None:
            return CompanyRow(t, company.name, None, error="no 10-K or 10-Q with a period end")
        series = get_series(company.cik, client, meta)
    except SECError as exc:
        return CompanyRow(t, company.name, None, error=f"SEC request failed: {exc}")
    quote = get_quote(company.ticker)
    m = metrics.compute(series, last.report_date, quote.price)
    return CompanyRow(
        t, company.name, m, high_52w=quote.high_52w, low_52w=quote.low_52w,
        cik=company.cik, sic_description=meta.sic_description, fiscal_year_end=meta.fiscal_year_end,
        latest_filing=f"{last.form} {last.accession} (period end {last.report_date})",
    )


def build_report(target: str, peers: list[str], client: SECClient | None = None,
                 get_quote: Callable[[str], market.Quote] = market.get_quote) -> Report:
    client = client or SECClient()
    t = load_company(target, client, get_quote)
    rows = [load_company(p, client, get_quote) for p in peers if p.strip()]
    return Report(target=t, comps=comps.build(t, rows))
