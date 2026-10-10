"""report.load_company turns bad tickers into rows with reasons, never exceptions."""

from engine.report import build_report, load_company

TICKERS = {"0": {"cik_str": 1046179, "ticker": "TSM", "title": "TAIWAN SEMICONDUCTOR"}}
SUBMISSIONS = {"cik": "1046179", "name": "TSMC", "filings": {"recent": {
    "form": ["20-F"], "accessionNumber": ["x"], "filingDate": ["2026-04-01"],
    "reportDate": ["2025-12-31"], "primaryDocument": ["a.htm"]}}}


class FakeClient:
    def get_json(self, url, refresh=False):
        return TICKERS if "company_tickers" in url else SUBMISSIONS


def no_quote(ticker):
    raise AssertionError("price shouldn't be fetched for an unusable company")


def test_unknown_ticker():
    row = load_company("zzzz", FakeClient(), no_quote)
    assert row.metrics is None and row.error == "not in the SEC ticker list"


def test_foreign_filer_out_of_scope():
    row = load_company("TSM", FakeClient(), no_quote)
    assert row.metrics is None and "20-F" in row.error


def test_report_with_unusable_target_has_no_implied_range():
    r = build_report("ZZZZ", ["TSM", " "], FakeClient(), no_quote)
    assert r.comps.implied == {} and len(r.comps.peers) == 1
    assert any("couldn't load" in n for n in r.comps.notes)
