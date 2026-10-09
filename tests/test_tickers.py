from datetime import date

import pytest

from engine.tickers import TickerNotFound, cik10, lookup, normalize_ticker, parse_submissions

TICKERS = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 1067983, "ticker": "BRK-B", "title": "BERKSHIRE HATHAWAY INC"},
}


class StubClient:
    def __init__(self, payload):
        self.payload = payload

    def get_json(self, url, refresh=False):
        return self.payload


def test_cik10_pads():
    assert cik10(320193) == "0000320193"
    assert cik10("0000320193") == "0000320193"


@pytest.mark.parametrize("raw,norm", [(" aapl ", "AAPL"), ("brk.b", "BRK-B"), ("BRK/B", "BRK-B")])
def test_normalize_ticker(raw, norm):
    assert normalize_ticker(raw) == norm


def test_lookup_found():
    c = lookup("aapl", StubClient(TICKERS))
    assert (c.ticker, c.cik, c.name, c.cik10) == ("AAPL", 320193, "Apple Inc.", "0000320193")


def test_lookup_share_class_dot():
    assert lookup("BRK.B", StubClient(TICKERS)).cik == 1067983


def test_lookup_not_found():
    with pytest.raises(TickerNotFound):
        lookup("ZZZZ", StubClient(TICKERS))


def submissions(forms):
    n = len(forms)
    return {
        "cik": "320193",
        "name": "Apple Inc.",
        "tickers": ["AAPL"],
        "exchanges": ["Nasdaq"],
        "sic": "3571",
        "sicDescription": "Electronic Computers",
        "fiscalYearEnd": "0928",
        "stateOfIncorporation": "CA",
        "filings": {
            "recent": {
                "form": forms,
                "accessionNumber": [f"A-{i}" for i in range(n)],
                "filingDate": [f"2024-0{i + 1}-15" for i in range(n)],
                "reportDate": ["2024-01-01"] * n,
                "primaryDocument": ["doc.htm"] * n,
            }
        },
    }


def test_parse_submissions():
    m = parse_submissions(submissions(["10-Q", "8-K", "10-K"]))
    assert m.cik == 320193 and m.sic == "3571" and m.fiscal_year_end == "0928"
    assert m.fiscal_year_end_month == 9
    assert m.files_10k and m.in_scope
    assert m.filings[0].filing_date == date(2024, 3, 15)  # most recent first
    assert m.latest("10-K").accession == "A-2"


def test_foreign_filer_out_of_scope():
    m = parse_submissions(submissions(["20-F", "6-K"]))
    assert not m.in_scope and m.files_foreign_annual
