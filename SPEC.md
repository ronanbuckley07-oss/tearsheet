# Tearsheet: build spec

## Goal for v1

Ticker in, report out. v1 is done when a user can enter a ticker, confirm or edit a peer list, and see a correct snapshot, financial summary, comps table, and implied valuation range, with sources available for every number. Narrative sections, PDF export, DCF, risks, and news come after v1.

Scope limits for v1: US filers that file 10-K and 10-Q (no 20-F/40-F foreign filers), USD only, no private companies, no precedent transactions (that data mostly lives in paid tools).

## Folder structure

```
tearsheet/
  app.py                  # Streamlit UI only
  engine/
    sec_client.py         # EDGAR HTTP calls, User-Agent, rate limiting, disk cache
    tickers.py            # ticker -> CIK, company name, validation
    xbrl.py               # tag fallback chains, fact extraction, dedupe, source metadata
    periods.py            # annual, quarterly, YTD, LTM calculation
    market.py             # share price via yfinance
    metrics.py            # EV bridge, EBITDA, multiples, margins, growth
    comps.py              # peer table, summary stats, implied valuation range
    peers.py              # LLM peer suggestions + validation (Phase 5)
    narrative.py          # LLM business overview (Phase 6)
    report.py             # assembles everything into one report object
  templates/report.html   # Jinja template for export (Phase 7)
  tests/
  data/cache/
  .env.example
  requirements.txt
  CLAUDE.md, SPEC.md, FINANCE_DECISIONS.md
```

## Data sources

- Ticker to CIK: `https://www.sec.gov/files/company_tickers.json`
- Company financials (XBRL): `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` (CIK zero-padded to 10 digits)
- Company metadata and filing list (name, SIC code, fiscal year end, recent filings): `https://data.sec.gov/submissions/CIK##########.json`
- Share price: yfinance. It is unofficial and occasionally breaks, so isolate it in market.py so it can be swapped out later.
- Narrative: Anthropic API.

## Known data problems to handle

- Companies switch XBRL tags over time (revenue especially changed around the 2018 ASC 606 adoption). Fallback chains must be resolved per period, not per company: for each period, take the first tag in the chain that has a value.
- The same fact appears in many filings. Dedupe by (tag, start, end), keeping the most recently filed value so restatements win. Keep the accession number of the value used.
- Flow items (revenue, operating income, D&A) are durations. Identify period length from start/end dates: ~365 days annual, ~90 quarterly, ~180 and ~270 YTD. Q4 is often not reported on its own.
- LTM = latest fiscal year + current YTD − prior-year same YTD. If the latest filing is a 10-K, LTM equals that fiscal year. Record which periods were combined.
- Balance sheet items are instants (end date only). Use the latest one, and make sure it matches the LTM period end.
- Starting tag chains (Claude Code should verify against real filings and extend):
  - Revenue: RevenueFromContractWithCustomerExcludingAssessedTax, Revenues, SalesRevenueNet, RevenueFromContractWithCustomerIncludingAssessedTax
  - Operating income: OperatingIncomeLoss
  - D&A: DepreciationDepletionAndAmortization, DepreciationAndAmortization, DepreciationAmortizationAndAccretionNet (else Depreciation + AmortizationOfIntangibleAssets)
  - Net income: NetIncomeLoss
  - Cash: CashAndCashEquivalentsAtCarryingValue; short-term investments: ShortTermInvestments, MarketableSecuritiesCurrent, AvailableForSaleSecuritiesDebtSecuritiesCurrent
  - Debt: LongTermDebtCurrent, LongTermDebtNoncurrent, LongTermDebt, ShortTermBorrowings, CommercialPaper, FinanceLeaseLiabilityCurrent, FinanceLeaseLiabilityNoncurrent. Watch for double counting: LongTermDebt often already includes the current portion. Show components so the owner can check.
  - Noncontrolling interest: MinorityInterest. Preferred: PreferredStockValue
  - Shares: dei:EntityCommonStockSharesOutstanding (may be reported per share class; sum classes), WeightedAverageNumberOfDilutedSharesOutstanding
  - Cash flow: NetCashProvidedByUsedInOperatingActivities, PaymentsToAcquirePropertyPlantAndEquipment; ShareBasedCompensation

## Build phases

Stop for review after each phase.

Phase 0 – Setup. Repo, folder structure, requirements.txt, .env.example, pytest running, SEC client with User-Agent, rate limit, and disk cache.

Phase 1 – Data layer. Ticker to CIK, metadata, company facts. xbrl.py returns clean time series per metric with source metadata attached. Test on AAPL, MSFT, and one company with a non-December fiscal year end.

Phase 2 – Metrics. periods.py (annual, YTD, LTM) and metrics.py (EBITDA, EV bridge, multiples, margins, growth) implementing FINANCE_DECISIONS.md. Unit tests with hand-built fixtures, plus validation tests against the owner's hand-checked values (see below).

Phase 3 – Comps. Given a target and a manually typed peer list, build the comps table, summary stats, and implied valuation range per FINANCE_DECISIONS.md.

Phase 4 – Streamlit UI. Ticker input, peer list editor, snapshot, financial summary table and charts (Plotly), comps table, football field chart, and a "sources" expander for every number. Deployable on Render or Streamlit Community Cloud.

Weekend target: Phases 0–4.

Phase 5 – Peer suggestions. LLM reads the company's business description and SIC code and proposes 10–15 peers with a one-line reason each. Every ticker is validated against company_tickers.json and checked for being a 10-K filer. User approves or edits the list before comps run.

Phase 6 – Narrative. Business overview from 10-K Item 1 text. Each paragraph cites the filing it came from. The LLM receives the computed numbers as input and may reference them but never produce new ones. Item extraction from 10-K HTML is messy; consider the edgartools package for this part (check it is maintained and fits).

Phase 7 – Export. Report rendered through templates/report.html. HTML download first; PDF (WeasyPrint or similar) once the HTML is stable.

Later – Simple DCF, key risks from Item 1A, recent 8-K developments, saved report history.

## Validation set

Before Phase 2 is marked done, the owner picks three companies and fills in the expected values below by hand from the 10-K/10-Q. Tests assert the engine matches within 0.5%. Any mismatch gets explained, not patched over.

How to fill it in: dollar amounts and shares in millions (commas are fine), period end as YYYY-MM-DD and equal to the latest 10-K/10-Q period end. "Diluted shares" is the diluted weighted-average share count for the latest quarter (or the fiscal year, if the latest filing is a 10-K). `RUN_LIVE=1 pytest tests/test_validation.py` reads this table directly; empty rows are skipped.

| Ticker | Period end | LTM revenue | LTM EBITDA | Total debt | Cash + ST inv. | Diluted shares |
|---|---|---|---|---|---|---|
| NVDA | 2026-07-26 | 302,970 | 201,266 | 33,366 | 56,586 | 24,285 |
| CRWV | 2026-06-30 | 7,590 | 3,760 | 35,289 | 5,539 | 551 |
| AVGO | 2026-08-02 | 89,104 | 51,578 | 59,419 | 23,975 | 4,887 |

Filled 2026-10-09 at the owner's request by Claude, read from the rendered financial statements in each filing (not from companyfacts). The owner should spot-check them against the filings. TSMC was the owner's third pick but files 20-F (out of v1 scope), so Broadcom replaced it. Working:
- NVDA (10-K 0001045810-26-000021, 10-Q 0001045810-26-000075). Revenue 215,938 + 177,837 - 90,805. EBIT 130,387 + 117,270 - 50,078; D&A (cash flow) 2,843 + 2,124 - 1,280. Debt: short-term 1,000 + long-term 32,366 (no finance leases on the face). Cash 22,443 + marketable debt securities 34,143; marketable equity securities (42,783) excluded, see FD-10 Q10. Diluted shares Q2 FY2027.
- CRWV (10-K 0001769628-26-000104, 10-Q 0001769628-26-000366). Revenue 5,131 + 4,653 - 2,194. EBIT -46 + (-193) - (-8); D&A 2,454 + 2,540 - 1,003. Debt: recourse 6,235 + 25,170, non-recourse 1,278 + 2,385, finance leases 7 + 214. Cash 5,524 + marketable securities 15 (restricted cash excluded, FD-2). Diluted shares Q2 2026.
- AVGO (10-K 0001730168-25-000121, 10-Q 0001730168-26-000080). Revenue 63,887 + 71,089 - 45,872. EBIT 25,484 + 35,306 - 17,976; D&A from the cash flow lines "amortization of intangible and right-of-use assets" + "depreciation": 8,775 + 6,531 - 6,542. Debt: short-term 2,252 + long-term 57,167. Cash 23,975 (no short-term investments). Diluted shares Q3 FY2026 (EPS note).
