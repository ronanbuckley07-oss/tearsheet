"""Peer-set tools (engine/peers.py, FD-9 and FD-15) on hand-built SEC responses.

Target T: market cap 1,000. Peers' market caps 250 (0.25x, in), 4,000 (4x, in),
4,100 (4.1x, out), 200 (0.2x, out) and one n/a.

SIC candidates: target TGT has $100m of CY2025 revenue. Same-SIC companies:
  NEAR  $120m  (1.2x, in band)       FAR   $390m  (3.9x, in band)
  BIG   $900m  (9x, out of band)     TINY  $10m   (0.1x, out of band)
  FOR   $110m  (1.1x, in band, but files 20-F: dropped)
  BAD   tags $50m and $50bn (1,000x apart): flagged, not sized
  NOREV no revenue in either frame; DEAD has no ticker.
Ordering: in band by closeness |log ratio|: NEAR (0.18), FAR (1.36); then out of band:
BIG (2.20), TINY (2.30); then unsized: BAD.
"""

import math
from datetime import date

import pytest

from engine import peers
from engine.comps import CompanyRow
from engine.sec_client import SECError
from tests.test_comps import company, fig
from tests.test_tickers import submissions

# ---- FD-9 size check ------------------------------------------------------------------------


def cap(ticker, value):
    return company(ticker, 10, equity_value=fig("equity value", value))


def test_size_check_band_edges_inclusive():
    t = cap("T", 1000.0)
    ps = [cap("A", 250.0), cap("B", 4000.0), cap("C", 4100.0), cap("D", 200.0),
          CompanyRow("E", "E", None, error="not in the SEC ticker list"), cap("T", 1000.0)]
    fits = peers.size_check(t, ps)
    got = {f.ticker: (round(f.ratio.value, 3) if f.ratio.ok else None, f.in_band) for f in fits}
    assert got == {"A": (0.25, True), "B": (4.0, True), "C": (4.1, False), "D": (0.2, False), "E": (None, None)}
    assert "E market cap n/a" in next(f for f in fits if f.ticker == "E").ratio.reason
    assert peers.in_band(fits) == ["A", "B"]  # n/a can't be shown to pass


def test_size_check_target_market_cap_missing():
    from engine.periods import missing
    t = company("T", 10, equity_value=missing("equity value", "USD", "share price n/a"))
    fits = peers.size_check(t, [cap("A", 250.0)])
    assert fits[0].in_band is None and "T market cap n/a" in fits[0].ratio.reason


# ---- SIC candidates -------------------------------------------------------------------------------

TICKERS = {str(i): {"cik_str": cik, "ticker": tk, "title": f"{tk} Inc"} for i, (cik, tk) in enumerate(
    [(1, "TGT"), (2, "NEAR"), (3, "FAR"), (4, "BIG"), (5, "TINY"), (6, "FOR"), (7, "BAD"), (8, "NOREV"),
     (2, "NEAR-B")])}  # a second share class of NEAR: one ticker per company, the first listed


def frame(rows, tag):
    return {"tag": tag, "data": [{"accn": f"0000000{cik}-26-000001", "cik": cik, "entityName": "x",
                                  "start": "2025-01-01", "end": "2025-12-31", "val": v} for cik, v in rows]}


FRAMES = {
    "RevenueFromContractWithCustomerExcludingAssessedTax": [(1, 100e6), (2, 120e6), (4, 900e6), (7, 50e6)],
    "Revenues": [(3, 390e6), (5, 10e6), (6, 110e6), (7, 50e9), (2, 999e6)],  # NEAR's second tag: first one wins
    "RevenueFromContractWithCustomerIncludingAssessedTax": [],
}


def atom(ciks):
    return "<feed>" + "".join(f"<entry><cik>{c:010d}</cik></entry>" for c in ciks) + "</feed>"


class SECStub:
    """Routes the URLs engine/peers.py asks for to hand-built responses."""

    def __init__(self, pages=None, missing_frames=()):
        self.pages = pages or [[1, 2, 3, 4, 5, 6, 7, 8, 99]]
        self.missing_frames = set(missing_frames)
        self.urls = []

    def get_text(self, url, refresh=False):
        self.urls.append(url)
        start = int(url.split("start=")[1].split("&")[0])
        page = start // peers.PAGE_SIZE
        return atom(self.pages[page] if page < len(self.pages) else [])

    def get_json(self, url, refresh=False):
        self.urls.append(url)
        if "company_tickers" in url:
            return TICKERS
        if "frames" in url:
            tag = url.split("/us-gaap/")[1].split("/")[0]
            if tag in self.missing_frames:
                raise SECError("HTTP 404")
            return frame(FRAMES[tag], tag)
        if "submissions" in url:
            cik = int(url.split("CIK")[1].split(".")[0])
            s = submissions(["20-F"] if cik == 6 else ["10-K", "10-Q"])
            s["cik"] = str(cik)
            s["sic"], s["sicDescription"] = "3674", "Semiconductors & Related Devices"
            return s
        raise AssertionError(url)


def test_frame_year_switches_in_april():
    assert peers.frame_year(date(2026, 3, 31)) == 2024
    assert peers.frame_year(date(2026, 4, 1)) == 2025


def test_sic_ciks_pages_until_a_short_page():
    stub = SECStub(pages=[list(range(1, 101)), [101, 102]])
    ciks, cut = peers.sic_ciks("3674", stub)
    assert len(ciks) == 102 and not cut and len(stub.urls) == 2
    ciks, cut = peers.sic_ciks("3674", SECStub(pages=[list(range(1, 101))] * 3), max_pages=2)
    assert cut


def test_revenue_frame_tag_priority_and_conflict():
    rev = peers.revenue_frame(2025, SECStub())
    assert rev[2].value == 120e6 and rev[2].tag.startswith("RevenueFromContract")  # first tag wins
    assert rev[3].tag == "Revenues"  # only in the second frame
    assert rev[7].conflict and "mis-scaled" in rev[7].conflict  # $50m vs $50bn
    assert rev[2].conflict is None  # 120m vs 999m is 8.3x: under the 10x threshold
    assert rev[1].accession == "00000001-26-000001"


def test_revenue_frame_survives_a_missing_frame():
    rev = peers.revenue_frame(2025, SECStub(missing_frames={"Revenues"}))
    assert 1 in rev and 3 not in rev


def test_sic_candidates_order_and_filters():
    stub = SECStub()
    out = peers.sic_candidates("TGT", stub, year=2025, limit=10)
    assert out.sic == "3674" and out.target.revenue.value == 100e6
    assert out.tickers == ["NEAR", "FAR", "BIG", "TINY", "BAD"]
    near = out.candidates[0]
    assert near.size_ratio == pytest.approx(1.2) and near.in_band
    assert abs(math.log(near.size_ratio)) < abs(math.log(out.candidates[1].size_ratio))
    assert [c.in_band for c in out.candidates] == [True, True, False, False, None]
    notes = " ".join(out.notes)
    assert "FOR (20-F/40-F filer)" in notes and "NOREV" in notes and "BAD" in notes
    assert "3 of 6 are within 0.25x-4x" in notes  # NEAR, FAR, FOR (FOR then dropped as a 20-F filer)


def test_sic_candidates_limit_counts_kept_filers_only():
    out = peers.sic_candidates("TGT", SECStub(), year=2025, limit=2)
    assert out.tickers == ["NEAR", "FAR"]


def test_sic_sector_largest_first_and_by_ticker():
    out = peers.sic_sector("3674", SECStub(), year=2025, limit=4)
    assert out.tickers == ["BIG", "FAR", "NEAR", "TGT"]  # by revenue; FOR (20-F) never reached the list
    assert out.sic_description == "Semiconductors & Related Devices"
    by_ticker = peers.sic_sector("near", SECStub(), year=2025, limit=4)
    assert by_ticker.sic == "3674" and "NEAR is filed under SIC 3674" in by_ticker.notes[0]
    bad = peers.sic_sector("ZZZZ", SECStub(), year=2025)
    assert bad.candidates == [] and "neither a SIC code" in bad.notes[0]
