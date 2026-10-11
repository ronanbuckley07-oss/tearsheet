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


# ---- Phase 4e loading changes ------------------------------------------------------------------


class CountingClient(FakeClient):
    def __init__(self):
        self.ticker_downloads = 0

    def get_json(self, url, refresh=False):
        if "company_tickers" in url:
            self.ticker_downloads += 1
        return super().get_json(url, refresh)


def test_ticker_list_parsed_once_per_batch():
    from engine.report import load_companies

    client = CountingClient()
    rows = load_companies(["TSM", "ZZZZ", "tsm", "YYYY"], client, no_quote)
    assert client.ticker_downloads == 1
    assert [r.error[:6] for r in rows] == ["files ", "not in", "files ", "not in"]


def test_market_inputs_only_for_a_known_target():
    calls = []

    def rf():
        calls.append("rf")
        raise AssertionError("not for an unknown ticker")

    build_report("ZZZZ", ["TSM"], CountingClient(), no_quote, get_risk_free=rf, get_beta=lambda t: calls.append(t))
    assert calls == []
    build_report("tsm", [], CountingClient(), no_quote, get_risk_free=lambda: calls.append("rf"),
                 get_beta=lambda t: calls.append(t))
    assert sorted(calls) == ["TSM", "rf"]  # fetched alongside the load, with the normalized ticker
