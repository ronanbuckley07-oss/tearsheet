"""Ticker -> CIK, company name, and filing metadata from SEC EDGAR.

Sources:
- https://www.sec.gov/files/company_tickers.json  (ticker -> CIK, name)
- https://data.sec.gov/submissions/CIK##########.json  (SIC, fiscal year end, filings)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from engine.sec_client import SECClient

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"

# v1 scope (SPEC.md): domestic filers that file 10-K and 10-Q.
DOMESTIC_ANNUAL_FORMS = {"10-K", "10-K/A"}
FOREIGN_ANNUAL_FORMS = {"20-F", "20-F/A", "40-F", "40-F/A"}


class TickerNotFound(LookupError):
    pass


@dataclass(frozen=True)
class Company:
    ticker: str
    cik: int
    name: str

    @property
    def cik10(self) -> str:
        return cik10(self.cik)


@dataclass(frozen=True)
class Filing:
    form: str
    accession: str
    filing_date: date
    report_date: date | None
    primary_document: str


@dataclass
class CompanyMetadata:
    cik: int
    name: str
    tickers: list[str]
    exchanges: list[str]
    sic: str | None
    sic_description: str | None
    fiscal_year_end: str | None  # "MMDD", e.g. "0928" for Apple
    state_of_incorporation: str | None
    filings: list[Filing] = field(default_factory=list)  # most recent first

    @property
    def files_10k(self) -> bool:
        return any(f.form in DOMESTIC_ANNUAL_FORMS for f in self.filings)

    @property
    def files_foreign_annual(self) -> bool:
        return any(f.form in FOREIGN_ANNUAL_FORMS for f in self.filings)

    @property
    def in_scope(self) -> bool:
        """True if this is a 10-K filer, which v1 requires."""
        return self.files_10k

    @property
    def fiscal_year_end_month(self) -> int | None:
        return int(self.fiscal_year_end[:2]) if self.fiscal_year_end else None

    def latest(self, *forms: str) -> Filing | None:
        return next((f for f in self.filings if f.form in forms), None)


def cik10(cik: int | str) -> str:
    return str(int(cik)).zfill(10)


def normalize_ticker(ticker: str) -> str:
    """Upper-case and use SEC's share-class separator ("BRK.B" -> "BRK-B")."""
    return ticker.strip().upper().replace(".", "-").replace("/", "-")


def load_ticker_map(client: SECClient) -> dict[str, Company]:
    raw = client.get_json(TICKERS_URL)
    out: dict[str, Company] = {}
    for row in raw.values():
        t = normalize_ticker(row["ticker"])
        out[t] = Company(ticker=t, cik=int(row["cik_str"]), name=row["title"])
    return out


def lookup(ticker: str, client: SECClient) -> Company:
    t = normalize_ticker(ticker)
    company = load_ticker_map(client).get(t)
    if company is None:
        raise TickerNotFound(f"{ticker!r} is not in the SEC ticker list")
    return company


def get_metadata(cik: int | str, client: SECClient) -> CompanyMetadata:
    return parse_submissions(client.get_json(SUBMISSIONS_URL.format(cik10=cik10(cik))))


def parse_submissions(raw: dict) -> CompanyMetadata:
    recent = raw.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    filings = [
        Filing(
            form=forms[i],
            accession=recent["accessionNumber"][i],
            filing_date=date.fromisoformat(recent["filingDate"][i]),
            report_date=_maybe_date(recent.get("reportDate", [None] * len(forms))[i]),
            primary_document=recent.get("primaryDocument", [""] * len(forms))[i],
        )
        for i in range(len(forms))
    ]
    filings.sort(key=lambda f: f.filing_date, reverse=True)
    return CompanyMetadata(
        cik=int(raw["cik"]),
        name=raw.get("name", ""),
        tickers=raw.get("tickers", []),
        exchanges=raw.get("exchanges", []),
        sic=raw.get("sic") or None,
        sic_description=raw.get("sicDescription") or None,
        fiscal_year_end=raw.get("fiscalYearEnd") or None,
        state_of_incorporation=raw.get("stateOfIncorporation") or None,
        filings=filings,
    )


def _maybe_date(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None
