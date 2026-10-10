"""Fallbacks added for the sector screen (FD-10 Q14-Q16), on hand-built data.

- Filings SEC companyfacts hasn't processed yet: read from the filing's XBRL instance.
- No operating income line: EBIT from pre-tax income (+ interest, or - non-operating).
- Cash tagged only with the restricted-cash total: used, flagged.
- PepsiCo-style 12/12/12/16-week quarters: 168- and 252-day YTD periods.
- A cover-page share count years older than the LTM date is n/a, not used.
"""

from datetime import date

from engine.metrics import shares_outstanding
from engine.xbrl import (
    INSTANCE_NOTE, MetricSeries, PeriodType, add_unprocessed_filing, classify_period, extract_all,
    extract_metric, fill_operating_income, instance_rows, merge_rows,
)
from tests.test_xbrl import FILING, _meta, facts, row

INSTANCE = """<?xml version="1.0" encoding="utf-8"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:us-gaap="http://fasb.org/us-gaap/2026"
      xmlns:dei="http://xbrl.sec.gov/dei/2026" xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
      xmlns:iso4217="http://www.xbrl.org/2003/iso4217" xmlns:x="http://example.com/x">
  <context id="d"><entity><identifier scheme="http://www.sec.gov/CIK">1</identifier></entity>
    <period><startDate>2026-01-01</startDate><endDate>2026-06-30</endDate></period></context>
  <context id="i"><entity><identifier scheme="http://www.sec.gov/CIK">1</identifier></entity>
    <period><instant>2026-06-30</instant></period></context>
  <context id="dim"><entity><identifier scheme="http://www.sec.gov/CIK">1</identifier>
    <segment><xbrldi:explicitMember dimension="us-gaap:SegmentAxis">x:CloudMember</xbrldi:explicitMember></segment>
    </entity><period><instant>2026-06-30</instant></period></context>
  <unit id="usd"><measure>iso4217:USD</measure></unit>
  <unit id="shares"><measure>shares</measure></unit>
  <dei:DocumentFiscalYearFocus contextRef="d">2026</dei:DocumentFiscalYearFocus>
  <dei:DocumentFiscalPeriodFocus contextRef="d">Q2</dei:DocumentFiscalPeriodFocus>
  <us-gaap:OperatingIncomeLoss contextRef="d" unitRef="usd" decimals="-6">500000000</us-gaap:OperatingIncomeLoss>
  <us-gaap:OperatingIncomeLoss contextRef="d" unitRef="usd" decimals="-6">500000000</us-gaap:OperatingIncomeLoss>
  <us-gaap:CashAndCashEquivalentsAtCarryingValue contextRef="i" unitRef="usd">90000000</us-gaap:CashAndCashEquivalentsAtCarryingValue>
  <us-gaap:CashAndCashEquivalentsAtCarryingValue contextRef="dim" unitRef="usd">1</us-gaap:CashAndCashEquivalentsAtCarryingValue>
  <x:CompanyOnlyThing contextRef="i" unitRef="usd">7</x:CompanyOnlyThing>
</xbrl>"""


class TextClient:
    def __init__(self, text):
        self.text, self.urls = text, []

    def get_text(self, url):
        self.urls.append(url)
        return self.text


def test_instance_rows_keep_plain_standard_facts_only():
    rows = instance_rows(INSTANCE, FILING)
    op = rows["us-gaap"]["OperatingIncomeLoss"]["USD"]
    assert len(op) == 1  # the repeated fact counts once
    assert op[0] == {"start": "2026-01-01", "end": "2026-06-30", "val": 500e6, "accn": FILING.accession,
                     "fy": 2026, "fp": "Q2", "form": "10-Q", "filed": "2026-07-23", "_note": INSTANCE_NOTE}
    cash = rows["us-gaap"]["CashAndCashEquivalentsAtCarryingValue"]["USD"]
    assert [r["val"] for r in cash] == [90e6]  # the dimensional fact is dropped, as companyfacts does
    assert "x" not in rows and "CompanyOnlyThing" not in str(rows)


def test_unprocessed_filing_is_merged_and_flagged():
    cf = facts({"CashAndCashEquivalentsAtCarryingValue": [row(80e6, "2025-12-31", accn="0000000001-26-000010")]})
    client = TextClient(INSTANCE)
    merged = add_unprocessed_filing(cf, 1, _meta([FILING]), client)
    assert client.urls and len(cf["facts"]["us-gaap"]["CashAndCashEquivalentsAtCarryingValue"]["units"]["USD"]) == 1
    cash = extract_metric(merged, "cash")
    assert [f.value for f in cash.facts] == [80e6, 90e6]
    latest = cash.latest()
    assert latest.source.accession == FILING.accession and latest.note == INSTANCE_NOTE


def test_processed_filing_not_refetched():
    cf = facts({"Revenues": [row(1.0, "2026-06-30", start="2026-01-01", accn=FILING.accession)]})
    client = TextClient(INSTANCE)
    assert add_unprocessed_filing(cf, 1, _meta([FILING]), client) is cf
    assert client.urls == []


def test_merge_rows_appends_without_touching_input():
    cf = facts({"Revenues": [row(1.0, "2025-12-31", start="2025-01-01")]})
    out = merge_rows(cf, {"us-gaap": {"Revenues": {"USD": [row(2.0, "2026-06-30", start="2026-01-01")]}}})
    assert len(out["facts"]["us-gaap"]["Revenues"]["units"]["USD"]) == 2
    assert len(cf["facts"]["us-gaap"]["Revenues"]["units"]["USD"]) == 1


def _income(op=None, pretax=None, interest=None, nonop=None):
    tags = {}
    for tag, val in (("OperatingIncomeLoss", op), ("InterestExpense", interest),
                     ("IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest", pretax),
                     ("NonoperatingIncomeExpense", nonop)):
        if val is not None:
            tags[tag] = [row(val, "2025-12-31", start="2025-01-01")]
    s = extract_all(facts(tags))
    fill_operating_income(s)
    return s["operating_income"]


def test_ebit_from_pretax_plus_interest():
    f = _income(pretax=900.0, interest=100.0, nonop=50.0).latest()
    assert f.value == 1000.0 and "pre-tax income + interest expense" in f.note
    assert len(f.sources) == 2


def test_ebit_from_pretax_minus_nonoperating_when_no_interest_tag():
    f = _income(pretax=900.0, nonop=-40.0).latest()  # net non-operating expense of 40
    assert f.value == 940.0 and "non-operating" in f.note


def test_reported_operating_income_is_never_replaced():
    f = _income(op=777.0, pretax=900.0, interest=100.0).latest()
    assert f.value == 777.0 and f.note is None


def test_no_ebit_without_a_bridge_item():
    assert not _income(pretax=900.0)


def test_cash_from_restricted_total_is_flagged():
    cf = facts({"CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents": [row(55.0, "2026-06-30")]})
    f = extract_metric(cf, "cash").latest()
    assert f.value == 55.0 and "FD-10 Q14" in f.note


def test_plain_cash_tag_beats_restricted_total():
    cf = facts({"CashAndCashEquivalentsAtCarryingValue": [row(50.0, "2026-06-30")],
                "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents": [row(55.0, "2026-06-30")]})
    f = extract_metric(cf, "cash").latest()
    assert f.value == 50.0 and f.note is None


def test_pepsico_16_week_fourth_quarter_calendar():
    assert classify_period(date(2025, 12, 28), date(2026, 6, 13)) == PeriodType.YTD_6M  # 24 weeks
    assert classify_period(date(2025, 12, 28), date(2026, 9, 5)) == PeriodType.YTD_9M  # 36 weeks


def test_stale_cover_share_count_is_na():
    cf = facts(dei={"EntityCommonStockSharesOutstanding": [row(469e6, "2010-01-27")]}, unit="shares")
    series = extract_metric(cf, "shares_outstanding_cover")
    assert shares_outstanding(series).value == 469e6  # no LTM date given: unchanged behavior
    f = shares_outstanding(series, date(2026, 6, 30))
    assert f.value is None and "2010-01-27" in f.reason
