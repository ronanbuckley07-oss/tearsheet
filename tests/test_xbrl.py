from datetime import date

import pytest

from engine.tickers import CompanyMetadata, Filing
from engine.xbrl import (
    METRICS,
    MetricDef,
    PeriodType,
    classify_period,
    extract_all,
    extract_metric,
    fill_cover_shares_from_filing,
    instance_url,
    parse_cover_shares,
)


def row(val, end, start=None, form="10-K", filed="2024-11-01", accn="0000000001-24-000001", fp="FY", fy=2024):
    r = {"val": val, "end": end, "form": form, "filed": filed, "accn": accn, "fp": fp, "fy": fy}
    if start:
        r["start"] = start
    return r


def facts(us_gaap=None, dei=None, unit="USD"):
    """Build a minimal companyfacts dict: {tag: [rows]} per taxonomy."""
    out = {"cik": 1, "entityName": "Test Co", "facts": {}}
    for tax, tags in (("us-gaap", us_gaap or {}), ("dei", dei or {})):
        out["facts"][tax] = {
            tag: {"units": rows if isinstance(rows, dict) else {unit: rows}} for tag, rows in tags.items()
        }
    return out


# ---- period classification ----------------------------------------------------


@pytest.mark.parametrize(
    "start,end,expected",
    [
        (None, "2024-09-28", PeriodType.INSTANT),
        ("2023-10-01", "2024-09-28", PeriodType.ANNUAL),  # Apple 52-week year, 364 days
        ("2022-09-25", "2023-09-30", PeriodType.ANNUAL),  # 53-week year, 371 days
        ("2024-01-01", "2024-12-31", PeriodType.ANNUAL),
        ("2024-07-01", "2024-09-30", PeriodType.QUARTER),
        ("2023-09-25", "2023-12-30", PeriodType.QUARTER),  # 14-week quarter, 97 days
        ("2024-01-01", "2024-06-30", PeriodType.YTD_6M),
        ("2024-01-01", "2024-09-30", PeriodType.YTD_9M),
        ("2024-01-01", "2024-02-29", PeriodType.OTHER),
    ],
)
def test_classify_period(start, end, expected):
    s = date.fromisoformat(start) if start else None
    assert classify_period(s, date.fromisoformat(end)) == expected


# ---- dedupe -------------------------------------------------------------------


def test_restatement_wins_and_keeps_its_accession():
    cf = facts(
        {
            "OperatingIncomeLoss": [
                row(100, "2023-12-31", "2023-01-01", filed="2024-02-01", accn="A-2024"),
                row(95, "2023-12-31", "2023-01-01", filed="2025-02-01", accn="A-2025"),  # restated
                row(80, "2022-12-31", "2022-01-01", filed="2023-02-01", accn="A-2023"),
            ]
        }
    )
    s = extract_metric(cf, "operating_income")
    fy23 = s.get(date(2023, 1, 1), date(2023, 12, 31))
    assert fy23.value == 95
    assert fy23.source.accession == "A-2025"
    assert fy23.restated is True
    assert s.get(date(2022, 1, 1), date(2022, 12, 31)).restated is False


def test_identical_comparatives_not_flagged_restated():
    cf = facts(
        {
            "OperatingIncomeLoss": [
                row(100, "2023-12-31", "2023-01-01", filed="2024-02-01", accn="A-2024"),
                row(100, "2023-12-31", "2023-01-01", filed="2025-02-01", accn="A-2025"),
            ]
        }
    )
    f = extract_metric(cf, "operating_income").facts[0]
    assert f.restated is False
    assert f.source.accession == "A-2025"  # most recent filing still cited


def test_non_10k_10q_forms_excluded():
    cf = facts(
        {
            "OperatingIncomeLoss": [
                row(100, "2023-12-31", "2023-01-01", form="8-K", filed="2024-03-01"),
                row(90, "2023-12-31", "2023-01-01", form="10-K", filed="2024-02-01"),
            ]
        }
    )
    assert extract_metric(cf, "operating_income").facts[0].value == 90


def test_amendment_included_and_wins():
    cf = facts(
        {
            "OperatingIncomeLoss": [
                row(90, "2023-12-31", "2023-01-01", form="10-K", filed="2024-02-01"),
                row(88, "2023-12-31", "2023-01-01", form="10-K/A", filed="2024-05-01", accn="AMEND"),
            ]
        }
    )
    f = extract_metric(cf, "operating_income").facts[0]
    assert f.value == 88 and f.source.form == "10-K/A"


def test_duration_metric_ignores_instant_rows_and_vice_versa():
    cf = facts(
        {
            "OperatingIncomeLoss": [row(5, "2023-12-31"), row(90, "2023-12-31", "2023-01-01")],
            "CashAndCashEquivalentsAtCarryingValue": [
                row(7, "2023-12-31", "2023-01-01"),
                row(50, "2023-12-31"),
            ],
        }
    )
    assert [f.value for f in extract_metric(cf, "operating_income").facts] == [90]
    assert [f.value for f in extract_metric(cf, "cash").facts] == [50]


# ---- fallback chains ----------------------------------------------------------


def test_revenue_chain_resolved_per_period_across_asc606_switch():
    cf = facts(
        {
            # Pre-2018 filings used SalesRevenueNet; post-ASC 606 the new tag.
            "SalesRevenueNet": [row(800, "2017-12-31", "2017-01-01", filed="2018-02-01")],
            "RevenueFromContractWithCustomerExcludingAssessedTax": [
                row(900, "2018-12-31", "2018-01-01", filed="2019-02-01"),
                row(1000, "2019-12-31", "2019-01-01", filed="2020-02-01"),
            ],
        }
    )
    s = extract_metric(cf, "revenue")
    assert [(f.end.year, f.value, f.source.tag) for f in s.facts] == [
        (2017, 800, "SalesRevenueNet"),
        (2018, 900, "RevenueFromContractWithCustomerExcludingAssessedTax"),
        (2019, 1000, "RevenueFromContractWithCustomerExcludingAssessedTax"),
    ]


def test_chain_priority_when_two_tags_report_same_period():
    cf = facts(
        {
            "Revenues": [row(1050, "2019-12-31", "2019-01-01")],
            "RevenueFromContractWithCustomerExcludingAssessedTax": [row(1000, "2019-12-31", "2019-01-01")],
        }
    )
    f = extract_metric(cf, "revenue").facts[0]
    assert f.value == 1000
    assert f.source.tag == "RevenueFromContractWithCustomerExcludingAssessedTax"


def test_d_and_a_composite_used_only_when_no_chain_tag():
    cf = facts(
        {
            "DepreciationDepletionAndAmortization": [row(30, "2023-12-31", "2023-01-01")],
            "Depreciation": [
                row(20, "2023-12-31", "2023-01-01"),
                row(18, "2022-12-31", "2022-01-01"),
            ],
            "AmortizationOfIntangibleAssets": [
                row(9, "2023-12-31", "2023-01-01"),
                row(7, "2022-12-31", "2022-01-01"),
            ],
        }
    )
    s = extract_metric(cf, "d_and_a")
    fy22, fy23 = s.facts
    assert fy23.value == 30 and fy23.tag == "DepreciationDepletionAndAmortization"
    assert fy22.value == 25
    assert fy22.tag == "Depreciation+AmortizationOfIntangibleAssets"
    assert len(fy22.sources) == 2 and fy22.note


def test_d_and_a_depreciation_alone_when_amortization_not_reported():
    # FD-10 Q1: depreciation alone, flagged, when amortization isn't broken out.
    cf = facts({"Depreciation": [row(20, "2023-12-31", "2023-01-01")]})
    s = extract_metric(cf, "d_and_a")
    f = s.latest()
    assert f.value == 20 and f.tag == "Depreciation"
    assert "understate" in f.note and "FD-10 Q1" in f.note


def test_d_and_a_amortization_alone_left_missing_and_noted():
    cf = facts({"AmortizationOfIntangibleAssets": [row(9, "2023-12-31", "2023-01-01")]})
    s = extract_metric(cf, "d_and_a")
    assert not s
    assert any("only part of" in n for n in s.notes)


# ---- units and share classes --------------------------------------------------


def test_non_usd_units_ignored_with_note():
    cf = facts({"OperatingIncomeLoss": {"EUR": [row(90, "2023-12-31", "2023-01-01")]}})
    s = extract_metric(cf, "operating_income")
    assert not s
    assert any("EUR" in n for n in s.notes)


def test_missing_metric_noted():
    s = extract_metric(facts({}), "noncontrolling_interest")
    assert not s and s.notes


def test_cover_shares_single_class():
    cf = facts(dei={"EntityCommonStockSharesOutstanding": [row(15_000, "2024-10-18", accn="K1")]}, unit="shares")
    f = extract_metric(cf, "shares_outstanding_cover").latest()
    assert f.value == 15_000 and f.source.taxonomy == "dei" and f.note is None


def test_cover_shares_summed_across_classes():
    cf = facts(
        dei={
            "EntityCommonStockSharesOutstanding": [
                row(5_800, "2025-01-28", accn="K1"),  # Class A
                row(860, "2025-01-28", accn="K1"),  # Class B
                row(5_400, "2025-01-28", accn="K1"),  # Class C
                row(12_000, "2024-04-20", accn="Q1", form="10-Q", filed="2024-04-25"),
            ]
        },
        unit="shares",
    )
    s = extract_metric(cf, "shares_outstanding_cover")
    latest = s.latest()
    assert latest.value == 12_060
    assert "3 share classes" in latest.note
    assert any("multiple share classes" in n for n in s.notes)


def test_cover_shares_exact_duplicate_not_double_counted():
    cf = facts(
        dei={
            "EntityCommonStockSharesOutstanding": [
                row(15_000, "2024-10-18", accn="K1"),
                row(15_000, "2024-10-18", accn="K1"),
            ]
        },
        unit="shares",
    )
    assert extract_metric(cf, "shares_outstanding_cover").latest().value == 15_000


# ---- series helpers and sources -----------------------------------------------


def test_series_sorted_and_latest_by_type():
    cf = facts(
        {
            "OperatingIncomeLoss": [
                row(30, "2024-06-30", "2024-01-01", form="10-Q", fp="Q2"),
                row(100, "2023-12-31", "2023-01-01"),
                row(14, "2024-06-30", "2024-04-01", form="10-Q", fp="Q2"),
            ]
        }
    )
    s = extract_metric(cf, "operating_income")
    assert [f.end for f in s.facts] == sorted(f.end for f in s.facts)
    assert s.latest(PeriodType.ANNUAL).value == 100
    assert s.latest(PeriodType.QUARTER).value == 14
    assert s.latest(PeriodType.YTD_6M).value == 30


def test_source_carries_full_provenance():
    cf = facts({"NetIncomeLoss": [row(42, "2024-09-28", "2023-10-01", accn="0000320193-24-000123")]})
    src = extract_metric(cf, "net_income").facts[0].source
    assert (src.tag, src.form, src.accession, src.start, src.end, src.filed) == (
        "NetIncomeLoss",
        "10-K",
        "0000320193-24-000123",
        date(2023, 10, 1),
        date(2024, 9, 28),
        date(2024, 11, 1),
    )
    assert src.filing_url(320193) == (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/0000320193-24-000123-index.htm"
    )


def test_extract_all_returns_every_metric():
    assert set(extract_all(facts({}))) == set(METRICS)


def test_debt_components_kept_separate():
    names = [m for m in METRICS if m.startswith("debt_") or m.startswith("finance_lease")]
    assert len(names) == 8  # totalled in Phase 2 under FD-2, not here


def test_finance_lease_total_extracted():
    s = extract_metric(facts({"FinanceLeaseLiability": [row(66_594e6, "2026-06-30")]}), "finance_lease_total")
    assert s.latest().value == 66_594e6


# ---- cover-page shares from the XBRL instance (multi-class filers) --------------

INSTANCE = """<?xml version="1.0" encoding="utf-8"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:dei="http://xbrl.sec.gov/dei/2026"
      xmlns:xbrldi="http://xbrl.org/2006/xbrldi">
  <context id="c-1"><entity><identifier scheme="http://www.sec.gov/CIK">1</identifier></entity>
    <period><startDate>2026-01-01</startDate><endDate>2026-06-30</endDate></period></context>
  <context id="a"><entity><identifier scheme="http://www.sec.gov/CIK">1</identifier><segment>
    <xbrldi:explicitMember dimension="us-gaap:StatementClassOfStockAxis">us-gaap:CommonClassAMember</xbrldi:explicitMember>
    </segment></entity><period><instant>2026-07-17</instant></period></context>
  <context id="b"><entity><identifier scheme="http://www.sec.gov/CIK">1</identifier><segment>
    <xbrldi:explicitMember dimension="us-gaap:StatementClassOfStockAxis">us-gaap:CommonClassBMember</xbrldi:explicitMember>
    </segment></entity><period><instant>2026-07-17</instant></period></context>
  <dei:DocumentType contextRef="c-1">10-Q</dei:DocumentType>
  <dei:EntityCommonStockSharesOutstanding contextRef="a" unitRef="shares">5868000000</dei:EntityCommonStockSharesOutstanding>
  <dei:EntityCommonStockSharesOutstanding contextRef="b" unitRef="shares">835000000</dei:EntityCommonStockSharesOutstanding>
</xbrl>"""

FILING = Filing(form="10-Q", accession="0000000001-26-000071", filing_date=date(2026, 7, 23),
                report_date=date(2026, 6, 30), primary_document="x-20260630.htm")


def _meta(filings):
    return CompanyMetadata(cik=1, name="Test", tickers=[], exchanges=[], sic=None, sic_description=None,
                           fiscal_year_end="1231", state_of_incorporation=None, filings=filings)


class TextClient:
    def __init__(self, text):
        self.text, self.urls = text, []

    def get_text(self, url):
        self.urls.append(url)
        return self.text


def test_instance_url():
    assert instance_url(1, FILING) == (
        "https://www.sec.gov/Archives/edgar/data/1/000000000126000071/x-20260630_htm.xml"
    )


def test_parse_cover_shares_reads_each_class():
    got = parse_cover_shares(INSTANCE)
    assert sorted(got) == [
        ("us-gaap:CommonClassAMember", 5_868e6, date(2026, 7, 17)),
        ("us-gaap:CommonClassBMember", 835e6, date(2026, 7, 17)),
    ]


def test_cover_shares_fallback_sums_classes_with_sources():
    series = extract_metric(facts({}), "shares_outstanding_cover")
    assert not series
    client = TextClient(INSTANCE)
    fill_cover_shares_from_filing(series, 1, _meta([FILING]), client)
    f = series.latest()
    assert f.value == 6_703e6 and f.end == date(2026, 7, 17)
    assert len(f.sources) == 2 and f.source.accession == FILING.accession
    assert "Sum of 2 share classes" in f.note and "CommonClassAMember 5,868,000,000" in f.note
    assert not any(n.startswith("No shares values found") for n in series.notes)


def test_cover_shares_fallback_different_dates_not_summed():
    series = extract_metric(facts({}), "shares_outstanding_cover")
    text = INSTANCE.replace('<instant>2026-07-17</instant></period></context>\n  <dei:Doc',
                            '<instant>2026-07-18</instant></period></context>\n  <dei:Doc')
    assert text != INSTANCE
    fill_cover_shares_from_filing(series, 1, _meta([FILING]), TextClient(text))
    assert not series and any("different as-of dates" in n for n in series.notes)


def test_cover_shares_fallback_no_filing_noted():
    series = extract_metric(facts({}), "shares_outstanding_cover")
    fill_cover_shares_from_filing(series, 1, _meta([]), TextClient(INSTANCE))
    assert not series and any("no inline-XBRL" in n for n in series.notes)


def test_debt_securities_current_is_short_term_investments():
    s = extract_metric(facts({"DebtSecuritiesCurrent": [row(34_143, "2026-07-26", form="10-Q")]}),
                       "short_term_investments")
    assert s.latest().value == 34_143


COMPANY_DEBT = """<?xml version="1.0" encoding="utf-8"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:crwv="http://www.coreweave.com/20260630"
      xmlns:us-gaap="http://fasb.org/us-gaap/2026" xmlns:xbrldi="http://xbrl.org/2006/xbrldi">
  <context id="i"><entity><identifier scheme="http://www.sec.gov/CIK">1</identifier></entity>
    <period><instant>2026-06-30</instant></period></context>
  <context id="old"><entity><identifier scheme="http://www.sec.gov/CIK">1</identifier></entity>
    <period><instant>2025-12-31</instant></period></context>
  <context id="dim"><entity><identifier scheme="http://www.sec.gov/CIK">1</identifier><segment>
    <xbrldi:explicitMember dimension="us-gaap:DebtInstrumentAxis">crwv:NotesMember</xbrldi:explicitMember>
    </segment></entity><period><instant>2026-06-30</instant></period></context>
  <crwv:RecourseDebtCurrent contextRef="i" unitRef="usd">6235000000</crwv:RecourseDebtCurrent>
  <crwv:RecourseDebtNonCurrent contextRef="i" unitRef="usd">25170000000</crwv:RecourseDebtNonCurrent>
  <crwv:RecourseDebtNonCurrent contextRef="old" unitRef="usd">14608000000</crwv:RecourseDebtNonCurrent>
  <crwv:RecourseDebtNonCurrent contextRef="dim" unitRef="usd">2000000000</crwv:RecourseDebtNonCurrent>
  <crwv:LongTermDebtMaturityAfterYearFour contextRef="i" unitRef="usd">9000000000</crwv:LongTermDebtMaturityAfterYearFour>
  <us-gaap:LongTermDebtCurrent contextRef="i" unitRef="usd">1</us-gaap:LongTermDebtCurrent>
</xbrl>"""


def test_parse_company_debt_keeps_plain_custom_debt_at_date():
    from engine.xbrl import parse_company_debt
    assert parse_company_debt(COMPANY_DEBT, date(2026, 6, 30)) == [
        ("crwv:RecourseDebtCurrent", 6_235e6),
        ("crwv:RecourseDebtNonCurrent", 25_170e6),
    ]
