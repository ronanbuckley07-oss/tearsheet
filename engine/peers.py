"""Peer-set tools built only from SEC data (Phase 4e). No LLM.

Two jobs:

1. ``size_check``: the FD-9 size test on a peer list that has already loaded.
   Each peer's market cap / the target's; inside 0.25x-4x passes. This is the
   check a judge runs in their head when a $180bn company is compared with a
   $5tn one.
2. ``sic_candidates`` / ``sic_universe``: a starting peer list (or a whole sector
   list) from the SEC's own industry codes. Companies come from EDGAR's company
   search by SIC code, are kept only if they have a ticker in company_tickers.json,
   and are sized by revenue from the SEC's XBRL "frames" API: one request returns
   every filer's value for one tag and calendar year, so sizing 400 companies
   costs two requests instead of 400 (FD-15).

FD-9 still rules: SIC codes group companies by what they make, not how they make
money (Qualcomm is "radio & TV equipment", 3663, not semiconductors), so these
are candidates for the user to approve, never a peer set. Each candidate carries
the accession number of the filing its revenue came from. The Phase 5 LLM
suggestions will plug in here and go through the same validation.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date

from engine.comps import CompanyRow
from engine.periods import Figure, missing
from engine.sec_client import SECClient, SECError
from engine.tickers import Company, TickerNotFound, get_metadata, load_ticker_map, lookup

SIZE_BAND = (0.25, 4.0)  # FD-9: peers roughly 0.25x-4x the target's market cap

BROWSE_URL = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&SIC={sic}&owner=include"
              "&start={start}&count=100&output=atom")
FRAMES_URL = "https://data.sec.gov/api/xbrl/frames/us-gaap/{tag}/USD/CY{year}.json"
# FD-15: the SPEC revenue chain minus SalesRevenueNet (retired with ASC 606, so absent from recent
# frames); a company is sized by the first one it reports. Old Dominion, J.B. Hunt, Akamai and
# Rambus report only the "including assessed tax" tag.
REVENUE_FRAME_TAGS = ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
                      "RevenueFromContractWithCustomerIncludingAssessedTax")
PAGE_SIZE = 100
MAX_PAGES = 10  # 1,000 companies; EDGAR lists every company ever filed under a code, most of them inactive


# ---- 1. FD-9 size check on a loaded peer list ---------------------------------------------


@dataclass(frozen=True)
class SizeFit:
    ticker: str
    name: str
    ratio: Figure  # peer market cap / target market cap
    in_band: bool | None  # None when either market cap is n/a


def size_check(target: CompanyRow, peers: list[CompanyRow], band: tuple[float, float] = SIZE_BAND) -> list[SizeFit]:
    """FD-9: each peer's market cap as a multiple of the target's, and whether it sits in the band."""
    lo, hi = band
    te = target.get("equity_value")
    out = []
    for p in peers:
        if p.ticker == target.ticker:
            continue
        pe = p.get("equity_value")
        if not te.ok or not pe.ok:
            bad = te if not te.ok else pe
            who = target.ticker if bad is te else p.ticker
            out.append(SizeFit(p.ticker, p.name,
                               missing("market cap vs target", "x", f"{who} market cap n/a ({bad.reason})"), None))
            continue
        if te.value <= 0:
            out.append(SizeFit(p.ticker, p.name, missing("market cap vs target", "x", "target market cap not positive"),
                               None))
            continue
        r = pe.value / te.value
        f = Figure(name=f"{p.ticker} market cap / {target.ticker} market cap", value=r, unit="x",
                   formula=f"{p.ticker} equity value / {target.ticker} equity value (FD-9 band {lo:g}x-{hi:g}x)",
                   inputs=(pe, te))
        out.append(SizeFit(p.ticker, p.name, f, lo <= r <= hi))
    return out


def in_band(fits: list[SizeFit]) -> list[str]:
    """Tickers that pass the FD-9 size test (n/a sizes are left out: they can't be shown to pass)."""
    return [f.ticker for f in fits if f.in_band]


# ---- 2. SIC-code candidates from SEC data ------------------------------------------------------


@dataclass(frozen=True)
class Revenue:
    """One company's calendar-year revenue from an XBRL frame, with its filing."""

    value: float
    tag: str
    start: date
    end: date
    accession: str
    conflict: str | None = None  # FD-15: the two revenue tags disagree; not used for sizing


@dataclass(frozen=True)
class Candidate:
    ticker: str
    cik: int
    name: str
    revenue: Revenue | None
    size_ratio: float | None  # candidate revenue / target revenue, same frame
    in_band: bool | None  # FD-15: revenue within the FD-9 band; None if either revenue is missing


@dataclass
class CandidateList:
    sic: str | None
    sic_description: str | None
    year: int
    target: Candidate | None  # the target itself, sized from the same frame (None for a sector list)
    candidates: list[Candidate] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def tickers(self) -> list[str]:
        return [c.ticker for c in self.candidates]


def frame_year(today: date | None = None) -> int:
    """FD-15: the latest calendar year most filers have reported in a 10-K.

    December year-end 10-Ks are due by early March (large filers) to late March;
    from April the prior calendar year is complete, before that the one before it.
    """
    today = today or date.today()
    return today.year - 1 if today.month >= 4 else today.year - 2


def sic_ciks(sic: str, client: SECClient, max_pages: int = MAX_PAGES) -> tuple[list[int], bool]:
    """CIKs EDGAR lists under a SIC code, and whether the list was cut at max_pages."""
    ciks: list[int] = []
    for page in range(max_pages):
        text = client.get_text(BROWSE_URL.format(sic=sic, start=page * PAGE_SIZE))
        found = [int(c) for c in re.findall(r"<cik>(\d+)</cik>", text)]
        ciks.extend(c for c in found if c not in ciks)
        if len(found) < PAGE_SIZE:
            return ciks, False
    return ciks, True


TAG_CONFLICT_FACTOR = 10  # FD-15: two revenue tags an order of magnitude apart is a tagging error


def revenue_frame(year: int, client: SECClient) -> dict[int, Revenue]:
    """CIK -> calendar-year revenue, the first REVENUE_FRAME_TAGS tag each company reports (FD-15).

    When a company reports both tags and they differ by more than 10x, one of them
    is mis-scaled (Tigo Energy's FY2025 10-K tags $103.5m once as $103.5bn), so the
    revenue is kept for display but flagged and not used to size the company.
    """
    frames = []
    for tag in REVENUE_FRAME_TAGS:
        try:
            frames.append(parse_frame(client.get_json(FRAMES_URL.format(tag=tag, year=year)), tag))
        except SECError:
            continue  # a frame that doesn't exist yet; the other tag may still size most companies
    out: dict[int, Revenue] = {}
    for frame in frames:
        for cik, rev in frame.items():
            first = out.get(cik)
            if first is None:
                out[cik] = rev
            elif first.conflict is None and min(first.value, rev.value) > 0 and \
                    max(first.value, rev.value) / min(first.value, rev.value) > TAG_CONFLICT_FACTOR:
                out[cik] = Revenue(first.value, first.tag, first.start, first.end, first.accession,
                                   conflict=f"{first.tag} {first.value / 1e6:,.0f}m vs {rev.tag} "
                                            f"{rev.value / 1e6:,.0f}m in the same filing period; one is mis-scaled")
    return out


def parse_frame(raw: dict, tag: str) -> dict[int, Revenue]:
    out = {}
    for row in raw.get("data", []):
        try:
            out[int(row["cik"])] = Revenue(float(row["val"]), tag, date.fromisoformat(row["start"]),
                                           date.fromisoformat(row["end"]), row["accn"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _by_cik(ticker_map: dict[str, Company]) -> dict[int, Company]:
    """One ticker per company: the first listed in company_tickers.json (its primary listing)."""
    out: dict[int, Company] = {}
    for c in ticker_map.values():
        out.setdefault(c.cik, c)
    return out


def _candidate(c: Company, rev: Revenue | None, target_rev: Revenue | None,
               band: tuple[float, float]) -> Candidate:
    if rev is None or target_rev is None or target_rev.value <= 0 or rev.value <= 0 or rev.conflict:
        return Candidate(c.ticker, c.cik, c.name, rev, None, None)
    r = rev.value / target_rev.value
    return Candidate(c.ticker, c.cik, c.name, rev, r, band[0] <= r <= band[1])


def sic_universe(sic: str, client: SECClient, year: int | None = None, exclude_cik: int | None = None,
                 target_rev: Revenue | None = None, band: tuple[float, float] = SIZE_BAND,
                 revenue: dict[int, Revenue] | None = None) -> tuple[list[Candidate], list[str]]:
    """Every listed company under a SIC code that reported revenue for ``year``, largest first."""
    year = year or frame_year()
    notes = []
    ciks, cut = sic_ciks(sic, client)
    if cut:
        notes.append(f"EDGAR lists more than {MAX_PAGES * PAGE_SIZE} companies under SIC {sic}; "
                     f"only the first {MAX_PAGES * PAGE_SIZE} were checked")
    companies = _by_cik(load_ticker_map(client))
    revenue = revenue if revenue is not None else revenue_frame(year, client)
    listed = [companies[c] for c in ciks if c in companies and c != exclude_cik]
    no_rev = [c.ticker for c in listed if c.cik not in revenue]
    out = [_candidate(c, revenue[c.cik], target_rev, band) for c in listed if c.cik in revenue]
    out.sort(key=lambda x: x.revenue.value, reverse=True)
    notes.append(f"SIC {sic}: {len(ciks)} companies on EDGAR, {len(listed)} with a ticker, "
                 f"{len(out)} reported CY{year} revenue in the SEC frames ({', '.join(REVENUE_FRAME_TAGS)})")
    if no_rev:
        notes.append("Listed but no CY{} revenue in the frame (not a 10-K filer, a different revenue tag, "
                     "or pre-revenue): {}".format(year, ", ".join(no_rev[:25]) + (" ..." if len(no_rev) > 25 else "")))
    return out, notes


def ten_k_filers(cands: list[Candidate], client: SECClient, limit: int, notes: list[str]) -> list[Candidate]:
    """The first ``limit`` candidates that file 10-Ks (v1 scope), checked in order.

    20-F filers that report in US GAAP (Alibaba) appear in the frames too; the
    comps engine would refuse them, so they are dropped here with a note.
    """
    kept, dropped = [], []
    for c in cands:
        if len(kept) >= limit:
            break
        try:
            meta = get_metadata(c.cik, client)
        except SECError as exc:
            dropped.append(f"{c.ticker} (SEC request failed: {exc})")
            continue
        if meta.in_scope:
            kept.append(c)
        else:
            dropped.append(f"{c.ticker} ({'20-F/40-F filer' if meta.files_foreign_annual else 'no 10-K'})")
    if dropped:
        notes.append("Left out, outside v1's 10-K scope: " + ", ".join(dropped))
    return kept


def sic_candidates(ticker: str, client: SECClient, year: int | None = None, limit: int = 15,
                   band: tuple[float, float] = SIZE_BAND) -> CandidateList:
    """Starting peers for ``ticker``: same SIC code, revenue within the FD-9 band, closest in size first."""
    year = year or frame_year()
    company = lookup(ticker, client)
    meta = get_metadata(company.cik, client)
    if not meta.sic:
        return CandidateList(None, None, year, None, notes=[f"{company.ticker} has no SIC code on EDGAR"])
    revenue = revenue_frame(year, client)
    target_rev = revenue.get(company.cik)
    target = Candidate(company.ticker, company.cik, company.name, target_rev, 1.0 if target_rev else None,
                       True if target_rev else None)
    universe, notes = sic_universe(meta.sic, client, year, exclude_cik=company.cik,
                                   target_rev=target_rev, band=band, revenue=revenue)
    out = CandidateList(meta.sic, meta.sic_description, year, target, notes=notes)
    if target_rev is None:
        out.notes.append(f"{company.ticker} has no CY{year} revenue in the frame, so candidates can't be sized; "
                         "listed largest first instead")
        out.candidates = universe[:limit]
        return out
    if target_rev.conflict:
        out.notes.append(f"{company.ticker}'s own revenue tags disagree ({target_rev.conflict}); "
                         "candidates can't be sized")
    # In the band first, then the rest by closeness in size, so a very large or very small
    # target still gets a list; in_band says which is which.
    sized = sorted((c for c in universe if c.size_ratio is not None),
                   key=lambda c: (not c.in_band, abs(math.log(c.size_ratio))))
    unsized = [c for c in universe if c.size_ratio is None]
    out.candidates = ten_k_filers(sized + unsized, client, limit, out.notes)
    inside = sum(1 for c in universe if c.in_band)
    out.notes.append(f"{inside} of {len(universe)} are within {band[0]:g}x-{band[1]:g}x of "
                     f"{company.ticker}'s CY{year} revenue (FD-15 proxy for the FD-9 market-cap band; "
                     "the comps page re-checks market cap once prices load)")
    flagged = [c.ticker for c in universe if c.revenue and c.revenue.conflict]
    if flagged:
        out.notes.append("Revenue tags disagree by more than 10x, not sized: " + ", ".join(flagged))
    return out


def sic_sector(sic: str, client: SECClient, year: int | None = None, limit: int = 12) -> CandidateList:
    """A sector list from a SIC code (or a ticker, meaning its SIC code): the largest listed
    10-K filers by CY revenue (FD-15).

    Largest first because a pitch sector screen is usually the investable names;
    the user edits the list before building the screen.
    """
    sic = str(sic).strip()
    year = year or frame_year()
    pre = []
    if not sic.isdigit():
        # A ticker instead of a code: use that company's SIC code.
        try:
            meta = get_metadata(lookup(sic, client).cik, client)
        except (TickerNotFound, SECError) as exc:
            return CandidateList(sic, None, year, None,
                                 notes=[f"{sic!r} is neither a SIC code (4 digits, e.g. 3674) nor a known ticker ({exc})"])
        if not meta.sic:
            return CandidateList(None, None, year, None, notes=[f"{sic.upper()} has no SIC code on EDGAR"])
        pre.append(f"{sic.upper()} is filed under SIC {meta.sic} ({meta.sic_description})")
        sic = meta.sic
    universe, notes = sic_universe(sic, client, year)
    out = CandidateList(sic, None, year, None, notes=pre + notes)
    out.candidates = ten_k_filers(universe, client, limit, out.notes)
    if out.candidates:
        out.sic_description = get_metadata(out.candidates[0].cik, client).sic_description
    return out
