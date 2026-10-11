# Finance decisions

These are the judgment calls an analyst makes when building comps. Each one has a suggested default and the reasoning behind it. Read each one, decide, and write your call on the "Decision" line. Claude Code implements whatever is written here and cites the FD number in the code.

If you can't explain why you chose something, that's the one an interviewer will ask about.

---

FD-1. EBITDA definition

Default: EBITDA = operating income (EBIT) + D&A from the cash flow statement. Report stock-based compensation (SBC) as a separate line but don't add it back.

Why it matters: Many companies and some banks use "adjusted EBITDA," which adds back SBC and one-time items. That makes profits look bigger, especially for tech companies where SBC is large. Mixing adjusted and unadjusted EBITDA across a peer set makes the multiples meaningless. Reported EBIT + D&A is consistent and checkable. The cost is that it includes one-time charges that may distort a single year.

Decision: Default.

---

FD-2. Enterprise value bridge

Default: EV = equity value + total debt + preferred stock + noncontrolling interest − cash − short-term investments.
- Total debt includes finance leases, excludes operating leases.
- Use cash and equivalents plus short-term investments; exclude restricted cash.

Why it matters: EV is what it costs to buy the whole business, so it should include every claim on the business's cash flows that the EBITDA in the denominator pays for. Under current accounting (ASC 842), operating lease payments are already an expense above EBITDA. If you add operating lease liabilities to EV while EBITDA has already been reduced by lease expense, you count the leases twice and inflate the multiple. Finance leases work like debt, and their costs sit below EBITDA in depreciation and interest, so they belong in EV. Consistency between numerator and denominator is the whole point. Noncontrolling interest is added because consolidated EBITDA includes 100% of subsidiaries the company only partly owns.

Decision: Default.

---

FD-3. Share count

Default: Latest cover-page shares outstanding (summed across share classes) for equity value. Show diluted weighted-average shares as a cross-check, and flag if they differ by more than 3%.

Why it matters: Bankers use fully diluted shares from the treasury stock method, which needs option and RSU detail that's hard to get reliably from XBRL. Cover-page shares are current but undiluted. Diluted weighted average includes dilution, but it's an average over the past period and may lag buybacks or issuance. Neither is perfect, so the tool shows both and you decide which drives the math.

Decision: Default.

---

FD-4. Time period

Default: LTM (last twelve months) as the primary basis, plus the last two fiscal years. No forward multiples in v1.

Why it matters: Comps in banking usually lean on forward multiples (next year's estimated EBITDA), because buyers pay for future earnings. Consensus estimates aren't available for free, so v1 is backward-looking. LTM also solves most fiscal-year mismatches, since every company is measured over its most recent twelve months rather than fiscal years ending in different months.

Decision: Default.

---

FD-5. Multiples shown

Default: EV/Revenue, EV/EBITDA, P/E (LTM). Alongside them: revenue growth (LTM vs prior LTM or last FY growth), EBITDA margin, net debt/EBITDA.

Why it matters: Multiples without growth and margins can't be interpreted. A company at 20x EBITDA growing 30% may be cheaper than one at 10x shrinking. EV/Revenue is the fallback for unprofitable companies. P/E is an equity-level multiple, so it pairs with net income, not EBITDA.

Decision: Default.

---

FD-6. Negative and extreme values

Default: Any multiple with a negative or zero denominator shows "NM." Multiples above 100x also show "NM" but are kept visible in a footnote.

Why it matters: A negative EV/EBITDA isn't a cheap valuation, it's a meaningless number, and it will wreck an average. The 100x cutoff is a convention, not a rule. Pick what you can defend.

Decision: Default.

---

FD-7. Summary statistics

Default: Show median, mean, 25th percentile, and 75th percentile for each multiple, calculated only over non-NM values. The median is the headline figure.

Why it matters: Peer sets are small and skewed by one or two outliers, so the mean can be misleading. The median holds up better.

Decision: Default.

---

FD-8. Implied valuation range

Default: Apply the 25th–75th percentile peer EV/EBITDA to the target's LTM EBITDA, then bridge from EV back to equity value and an implied share price (reverse the FD-2 bridge, divide by FD-3 shares). Do the same with EV/Revenue. Show both as bars on a football field chart next to the current price and 52-week range.

Why it matters: Comps give a range, not a point. The interquartile range is a common convention. Going from EV back to share price applies the same bridge in reverse, which is a standard interview question.

Decision: Default.

---

FD-9. Peer selection criteria

Default: Peers should share business model and end market first, then be within roughly 0.25x–4x the target's market cap, US-listed 10-K filers. Aim for 6–12 peers. The tool suggests and you approve.

Why it matters: The peer set drives the answer more than any formula. Similarity in how the business makes money matters more than SIC code. Size matters because large companies usually trade at different multiples than small ones.

Decision: Default.

---

FD-10. Open questions log

When Claude Code hits a judgment call not covered above, it logs it here and asks you. Record the answer.

- Q1 (2026-10-09, Phase 1, FD-1). D&A when the cash flow statement shows depreciation only. Alphabet's FY2025 cash flow reports "Depreciation of property and equipment" ($21,136M, us-gaap:Depreciation); intangible amortization (~$0.5B) is folded into "other" and has no annual tag, so the Depreciation + AmortizationOfIntangibleAssets fallback finds no FY2025 D&A. Suggested: use depreciation alone in that case, with a note that amortization isn't reported separately. Decision: Suggested (owner, 2026-10-09). Implemented in engine/xbrl.py.
- Q2 (2026-10-09, Phase 1, FD-1). Microsoft's cash flow line is "Depreciation, amortization, and other" ($38,534M for FY2026), a company-specific tag (msft:DepreciationAmortizationAndOther) that companyfacts doesn't carry. The engine currently uses Depreciation ($34,300M, rounded in the notes) + AmortizationOfIntangibleAssets ($4,700M) = $39,000M. Suggested: keep the standard-tag sum (it is pure D&A and checkable), and show the cash-flow line beside it later. Decision: Suggested (owner, 2026-10-09). Keep the standard-tag sum.
- Q3 (2026-10-09, Phase 1, FD-2). Balance sheet items reported only annually. Apple tags finance lease liabilities ($538M current + $692M noncurrent) in the 10-K only, not in 10-Qs, so at a June 2026 LTM date the latest value is September 2025. Suggested: use the latest 10-K value, flagged as from an earlier date. Decision: Suggested (owner, 2026-10-09). Implement in Phase 2: use the latest 10-K value, flagged with its date.
- Q4 (2026-10-09, Phase 2, FD-2). Items a company doesn't report at the LTM date (no commercial paper, no preferred stock, no noncontrolling interest). Implemented for now: treat as 0 and list each one in the notes. Cash is the exception: missing cash makes EV n/a. Decision: Suggested (owner, 2026-10-09). Implemented in engine/metrics.py.
- Q5 (2026-10-09, Phase 2, FD-2). When a company tags both ShortTermBorrowings and CommercialPaper, the engine adds both and flags a possible overlap for you to check. Decision: Suggested (owner, 2026-10-09). Implemented in engine/metrics.py.
- Q6 (2026-10-09, Phase 2, FD-5). P/E computed as equity value / LTM net income, using the same FD-3 cover-page share count as EV (rather than price / reported diluted EPS). Decision: Suggested (owner, 2026-10-09). Implemented in engine/metrics.py.
- Q7 (2026-10-09, Phase 2, FD-6). A multiple whose numerator is negative (negative EV, e.g. a company with more cash than market cap) shows as NM like a negative denominator. Decision: Suggested (owner, 2026-10-09). Implemented in engine/metrics.py.
- Q8 (2026-10-09, Phase 2, FD-3). Multi-class companies: equity value = one share price (the ticker you typed) x all classes. For Alphabet that prices Class C (GOOG) and unlisted Class B at the GOOGL price. The alternative is pricing each listed class separately. Decision: Suggested (owner, 2026-10-09). Implemented in engine/metrics.py.
- Q9 (2026-10-09, Phase 2, FD-2). Company-specific debt tags. CoreWeave's June 2026 10-Q tags its debt only as crwv:RecourseDebtCurrent/NonCurrent and crwv:NonRecourseDebtCurrent/NonCurrent ($35,068M), which companyfacts doesn't carry. The engine now shows total debt as n/a and lists those tags. Suggested: when the standard debt tags are missing at the LTM date, sum the company-specific debt lines from that filing's balance sheet, flagged and listed one by one. Decision: Suggested (owner, 2026-10-09). Implemented in engine/metrics.py; skipped (n/a) when tag names suggest a total plus its parts.
- Q10 (2026-10-09, Phase 2, FD-2). Marketable equity securities (NVIDIA: $42,783M of stakes in other companies, separate from $34,143M of marketable debt securities). Currently excluded from "short-term investments": they are equity stakes with price risk, not cash-like. Suggested: keep excluded. Decision: Suggested (owner, 2026-10-09). Marketable equity securities stay excluded.
- Q11 (2026-10-10, Phase 3, FD-7). Percentile method: 25th/75th percentiles use linear interpolation between ranks, the same as Excel's PERCENTILE.INC (and QUARTILE.INC), so any figure can be reproduced in a spreadsheet. Decision: Suggested (owner, 2026-10-10). Implemented.
- Q12 (2026-10-10, Phase 3, FD-5). Net income when a company stops tagging NetIncomeLoss: Broadcom reports only ProfitLoss (consolidated net income incl. noncontrolling interests) from FY2025. Used as a fallback, flagged in the notes; identical when there's no NCI. Decision: Suggested (owner, 2026-10-10). Implemented.
- Q13 (2026-10-10, Phase 3, FD-1). Cash-flow D&A split across two lines: AMD and Marvell show "depreciation and amortization" (OtherDepreciationAndAmortization) plus "amortization of acquisition-related intangibles" on the cash flow statement. That pair is summed and preferred over Depreciation (from the PP&E note) + AmortizationOfIntangibleAssets, since FD-1 says D&A comes from the cash flow statement. Decision: Suggested (owner, 2026-10-10). Implemented.
- Q14 (2026-10-10, Phase 4c, FD-2). Balance-sheet cash tagged only as CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents (P&G, Target, Starbucks, Chevron use the cash-flow total for the balance-sheet line, usually because restricted cash is nil or immaterial). Used only when CashAndCashEquivalentsAtCarryingValue and Cash are both missing for the date, flagged on the figure as possibly including restricted cash. Decided by Claude under the 2026-10-10 delegation. Implemented in engine/xbrl.py.
- Q15 (2026-10-10, Phase 4c, FD-1). No operating income line (Lilly, J&J, Merck, Chevron, ConocoPhillips, Deere, KLA). For periods with no OperatingIncomeLoss: EBIT = pre-tax income + interest expense (the usual data-provider convention; it leaves other non-operating income/expense inside EBIT), or, when interest expense isn't tagged for the period (Lilly), pre-tax income - "other income (expense), net" (NonoperatingIncomeExpense). Each value is flagged with the method; a reported operating income always wins. Decided by Claude. Implemented in engine/xbrl.py.
- Q16 (2026-10-10, Phase 4c, rule 2/3). Two data-freshness fixes. (a) SEC's companyfacts API sometimes lags a filing by months (Visa's July 2026 10-Q was missing in October; also PayPal, Coca-Cola, Abbott, General Dynamics, Ford, NXP). When the latest 10-K/10-Q's accession appears nowhere in companyfacts, its non-dimensional us-gaap/dei facts are read from that filing's own XBRL instance, with the same tag/form/accession/date provenance and a note on each fact. (b) A cover-page share count more than 200 days older than the latest filing is re-read from that filing (Visa's last undimensioned count in companyfacts is from 2010), and one more than 400 days older than the LTM date is n/a rather than used. Also: PepsiCo's 12/12/12/16-week calendar makes its half-year 168 days and nine months 252, so the YTD period windows were widened to 165-192 and 248-285 days. Decided by Claude. Implemented in engine/xbrl.py and engine/metrics.py.

---

FD-11. Discounted cash flow (DCF)

Decided by Claude 2026-10-10. The owner delegated finance calls ("I don't need to sign off on all finance decisions, just build"); each is listed here so it can still be changed. Implemented in engine/dcf.py; every assumption is editable in the app.

- Free cash flow. Unlevered free cash flow = EBIT x (1 - tax rate) + D&A - capex - increase in net working capital. Stock-based comp stays inside EBIT as a real cost (consistent with FD-1). No tax is charged on a negative EBIT (no loss carryforwards are modeled).
- Forecast. 5 years. Year 1 is the 12 months after the LTM date; LTM revenue is the base.
- Starting values. Revenue growth starts at LTM growth and fades in a straight line to terminal growth by year 5. EBIT margin, D&A and capex are 3-fiscal-year totals divided by 3-year total revenue (a revenue-weighted average) from 10-Ks. Net working capital is the average of NWC / revenue at the last 3 fiscal year ends, and stays at that % of revenue, so the cash tied up each year = NWC % x the increase in revenue.
- Net working capital = (current assets - cash - short-term investments) - (current liabilities - current debt - short-term borrowings - commercial paper - current finance leases). Cash and debt come out because the EV bridge handles them.
- Tax rate. 3-year total tax expense / total pretax income. If that is negative, above 50%, or missing, the 21% US federal rate is used and flagged.
- Cost of equity (CAPM) = risk-free rate + beta x equity risk premium.
  - Risk-free: the latest 10-year Treasury par yield from home.treasury.gov.
  - Beta: raw beta from 60 complete months of dividend-adjusted returns against the S&P 500 (Yahoo Finance), then adjusted toward 1 as Bloomberg does: 0.67 x raw + 0.33. Fewer than 24 months of history means n/a (enter one).
  - Equity risk premium: 5.0% (a judgment input; Damodaran's published estimate is a common reference).
- Cost of debt = LTM interest expense / total debt at the LTM date, then x (1 - tax rate) inside WACC. n/a when the company doesn't tag interest expense (Apple stopped in FY2023); enter it.
- WACC weights. Market equity value (FD-3 shares x price) and total debt (FD-2).
- Terminal value. Perpetuity growth, g = 2.5%. NM if WACC <= g or year-5 free cash flow is negative. The exit-multiple method (peer median EV/EBITDA x year-5 EBITDA) is shown as a cross-check with the perpetual growth rate it implies, and the perpetuity method's implied EV/EBITDA is shown too.
- Steady-state terminal year (added 2026-10-10 after MSFT came out at a third of its price). If year-5 capex is above D&A, the terminal value's cash flow uses capex = D&A. Capex above depreciation is growth investment (MSFT's FY2026 capex was $116bn against $39bn of D&A); carrying it into a perpetuity that grows at 2.5% charges a build-out forever. Capex below D&A is left alone, since that gap is usually amortization of acquired intangibles (Broadcom), which is never replaced. The forecast years themselves are unchanged. A toggle turns it off.
- Discounting. End-of-year by default. The mid-year toggle discounts each year's cash half a year less, and the perpetuity terminal value from year 4.5 (Rosenbaum & Pearl convention); the exit-multiple terminal value always from year 5.
- To share price. Reverse the FD-2 bridge, divide by FD-3 cover-page shares (as FD-8).
- Output. Share price, a 5x5 sensitivity table (WACC +/-1% and terminal growth +/-1%, in 0.5% steps), and a football field bar spanning WACC +/-1% and growth +/-0.5%.
- Sanity flags (shown, change nothing): capex above 1.5x D&A when the steady-state toggle is off, NWC beyond +/-50% of revenue, terminal value above 85% of EV.

Why it matters: comps say what the market pays for similar companies; a DCF says what the cash flows are worth on your own assumptions. The defaults are history carried forward, which is a starting point, not a forecast. Most defaults land well below today's prices for the AI-cycle names (heavy current capex is assumed to continue forever, betas are high). Seeing which assumption moves the answer is the point of the exercise.

---

FD-12. Sector screen

Decided by Claude 2026-10-10 (owner's delegation). Implemented in engine/sector.py; the screen has no target.

- Statistics. Median, mean, 25th and 75th percentiles per column, over every company in the screen with a usable value. FD-6 NM rules and the FD-7 percentile method (Excel QUARTILE.INC) are unchanged. Unlike comps, nobody is excluded as "the target": the screen describes the whole sector.
- Relative value. Company multiple / sector median - 1, for EV/Revenue, EV/EBITDA and P/E. n/a when the company's multiple is NM.
- Distance from the 52-week high = share price / 52-week high - 1.
- Fitted line on the scatter charts. Ordinary least squares over companies with both values (NM excluded), shown with R². It is a picture of how the market prices growth or margins in this group, not a valuation method, so it produces no implied price. Needs 3+ companies.
- Talking points (engine/pitch.py) are fixed sentence templates over these numbers; a sentence is dropped when a number it needs is NM or n/a. No LLM is involved (CLAUDE.md rule 1).
- Starter sector lists (engine/presets.py) are a starting point for FD-9, not a peer selection. Banks, insurers and REITs are left out because EV/EBITDA doesn't describe them.

- Screening tools (added 2026-10-10, Phase 4e):
  - Percentile rank = companies with a lower value / (usable values - 1), Excel PERCENTRANK.INC (ties share the lower rank; 0% = lowest, 100% = highest). Same spreadsheet-reproducible choice as FD-10 Q11. NM/n/a values get no rank.
  - Gap to the fitted line = actual multiple - the line's prediction at the company's growth (or margin), in turns, and as actual / predicted - 1. Negative = cheaper than peers with the same growth. It is a screen, not a valuation: no implied price. When R² < 0.2 the line explains little, so the gaps are shown with a warning and the "furthest below the line" talking point is dropped (it also needs 5+ companies). One extreme point can flatten the line (MU's 256% growth in the October 2026 semiconductor screen gave R² = 0.00), so the chart should always be checked first.
  - Filters (min/max market cap, min growth, min margin) re-slice companies already loaded and recompute every statistic over the survivors. A company whose value on a filtered column is NM or n/a is dropped, since it can't be shown to pass.

Why it matters: a pitch starts with the sector. Lining up who trades where, and against what growth and margins, is how you find a stock that looks mispriced and how you defend the peer set you then use for its comps.

---

FD-13. DCF model workbook (Excel)

Decided by Claude 2026-10-11 (owner's delegation). Implemented in engine/dcf_workbook.py; downloaded with "Download DCF model" once the DCF has run.

- Same model as FD-11, written as Excel formulas. Every projection, discounting, terminal-value, bridge and sensitivity cell is a formula on the Inputs sheet, so changing a blue input reflows the file. On the app's assumptions it reproduces the app's share price, EV, WACC and every sensitivity cell exactly (tests/test_dcf_workbook.py recalculates it in LibreOffice and compares); a Checks block on the DCF sheet shows the tie-out.
- Colour code (banking convention): blue = typed input or filing figure, black = formula, green = link to another sheet; yellow fill = assumptions meant to be changed.
- Beta. Raw regression beta and the 0.67 Blume weight are separate inputs, with adjusted beta as a formula. If the user typed a beta in the app, that value is typed into the adjusted-beta cell instead.
- Terminal value by both methods side by side. Perpetuity growth exactly as FD-11. Exit multiple: peer median EV / LTM EBITDA (FD-7) x year-5 EBITDA, discounted from the end of year 5 even when the mid-year convention is on, because an exit value is realised at a point in time (the standard banking treatment, and what the app's cross-check already did). Each method shows its implied counterpart (implied exit multiple, implied perpetual growth).
- No peer median. The exit multiple starts at the multiple the perpetuity method implies (so both methods agree) and is labelled as such; it is never filled from a guess.
- Sensitivities. Share price by WACC x terminal growth (+/-1% in 0.5% steps, as FD-11) and by WACC x exit multiple (+/-2.0x in 1.0x steps), plus upside vs the current price. Steps are inputs.
- Football field on the Cover. DCF bars use the sensitivity corners (WACC +/-1%, g +/-0.5%, as FD-11; exit +/-1.0x); comps bars are the FD-8 25th-75th percentile ranges and the 52-week range, as values from the app.

Why it matters: a DCF you can present has to survive "what if growth is lower?" in the room. A live model lets you change one blue cell and show the answer, and the colour code tells the reader which numbers are judgment and which are arithmetic.

---

FD-14. Learn mode: explanations and "what moves" numbers

Decided by Claude 2026-10-11 (owner's delegation). Implemented in engine/learn.py; shown on the app's separate Learn view (course chapters, engine/learn.py COURSE) and, on the tearsheet, behind the "Click-to-explain" toggle (off by default so experienced users get a clean page).

- Explanations are fixed templates (engine/learn.py CONCEPTS) filled with figures the engine already computed. No LLM writes them (CLAUDE.md rule 1). A template sentence that needs an n/a or NM figure is dropped, never estimated (rule 3).
- Every "if it changes" number is a rerun of the real DCF (engine/dcf.run) on a copy of the assumptions, with everything else held fixed. Nothing in learn mode changes the valuation shown on the page.
- Standard step for the tornado chart and the "raise it / lower it" lines: 1 percentage point for every % input (each growth year, EBIT margin, capex, NWC, tax, risk-free, ERP, cost of debt), 0.10 for beta, 0.5 points for terminal growth (matching the sensitivity table's step). The revenue growth bar moves all five years together. One shared unit makes the bars comparable; the trade-off is that 1 point is a bigger move for a small input (a 1.4% cost of debt) than a large one (a 60% EBIT margin), which the bar labels state.
- A step that breaks the DCF (WACC at or below terminal growth, negative terminal cash flow) is reported as breaking it, not drawn.
- "What your edits did" compares the current assumptions with the FD-11 defaults on the same toggles (mid-year, steady state).
- Comps rules of thumb are exact arithmetic on the current figures: each 1.0x of multiple = the target's LTM metric of EV, divided by cover-page shares for the per-share figure; each $1bn of debt or cash = $1bn / shares per share.

Why it matters: the owner has to explain every number in an interview. Seeing the arithmetic in the company's own numbers, and which inputs actually move the answer, teaches the mechanics faster than the formulas alone.

---

FD-15. Peer tools from SEC data (FD-9 size check, SIC-code candidates)

Decided by Claude 2026-10-10 (owner's delegation), Phase 4e. Implemented in engine/peers.py. No LLM; the Phase 5 LLM suggestions will go through the same validation.

- Size check on a loaded peer list. Peer market cap / target market cap; inside 0.25x-4x (inclusive) passes FD-9. A peer whose market cap is n/a can't be shown to pass and is not kept by "keep only the size band". The pitch builder offers the size-band peers as the default; the whole screen stays one click away.
- SIC-code candidates. Companies come from EDGAR's company search by SIC code (paged, up to 1,000 per code), kept only if they appear in company_tickers.json (one ticker per company: the first listed, its primary class), then sized by revenue from the SEC XBRL frames API, which returns every filer's value for one tag and calendar year in one request.
  - Revenue tag order: RevenueFromContractWithCustomerExcludingAssessedTax, then Revenues, then RevenueFromContractWithCustomerIncludingAssessedTax (the SPEC chain; SalesRevenueNet left out because it was retired with ASC 606). The first tag a company reports wins, as in the per-period chain. The third tag matters: Old Dominion, J.B. Hunt, Akamai and Rambus report only it.
  - If a company's tags disagree by more than 10x, one is mis-scaled (Tigo Energy's FY2025 10-K tags $103.5m once as $103.5bn). Its revenue is shown with the conflict and not used for sizing.
  - Year: the latest calendar year most 10-Ks cover: the prior year from April onward, the year before that until then (December filers' 10-Ks are due by late March). Frames place a non-December fiscal year in the calendar year it mostly overlaps.
  - Size band for candidates: revenue within 0.25x-4x of the target's revenue in the same frame. This is a proxy for the FD-9 market-cap band, used only because pricing hundreds of companies isn't practical; the comps page re-checks market cap once prices load. Revenue understates the size of high-multiple companies and overstates low-margin ones, which is why the proxy only shortlists.
  - Order: in-band candidates by closeness in size (|log of the revenue ratio|), then the rest by closeness, then unsized ones, so a very large or small target still gets a list. Each shortlisted company is checked for filing 10-Ks; 20-F filers that report in US GAAP (Alibaba) appear in frames and are dropped with a note.
  - A sector list from a SIC code takes the largest 10-K filers by revenue (default 12), for screens the starter lists don't cover.

Why it matters: SIC codes describe products, not business models (Qualcomm is SIC 3663, "radio & TV equipment", not semiconductors; Uber's 7389 also holds Accenture and Mastercard), so these lists are candidates the user prunes, never a peer set. The size test is the one a judge applies by eye: QCOM ($184bn) against NVDA ($5.5tn, 30x) and AVGO (9x) is a comparison of different businesses. In the October 2026 semiconductor screen only 5 of 11 peers passed for QCOM, and the peer median EV/EBITDA moved from 29.0x to 29.6x while the 25th-75th range narrowed and shifted up (22.7x-33.5x to 28.4x-45.9x).

---

FD-16. Thesis support (scorecard, valuation summary)

Decided by Claude 2026-10-10 (owner's delegation), Phase 4e. Implemented in engine/thesis.py. Every output is computed from figures already on the page; nothing is estimated.

- Scorecard rows: revenue growth, EBITDA margin, net debt / EBITDA, EV/EBITDA, EV/Revenue, P/E, each against the peer 25th percentile, median and 75th percentile (FD-7, target excluded).
- Notable = outside the peer interquartile range; inside = "in line". The IQR is the band FD-8 already uses as "typical", so the scorecard and the implied range agree on what counts as unusual.
- Direction for a long: higher growth and margin are stronger; lower leverage is safer; lower multiples are cheaper. A notable reading in the favorable direction is labeled "long", the other "short". Distance from the 52-week high is left out because it reads as value or as momentum depending on the thesis. These are conventions for organizing evidence, not a recommendation: the deck leaves the recommendation for the team to write.
- Rank = share of peers below the target among peers + target (PERCENTRANK.INC, as FD-12).
- Comparability warnings: the target's growth or margin outside every peer's value (the peers' multiples price a different business) or outside the peer IQR (the median multiple may over- or understate it). These are the cases where a judge asks why the peers' multiples apply.
- Upside = implied price / current price - 1, for the low, mid and high of each method: comps EV/EBITDA and EV/Revenue (FD-8, mid = peer median), DCF (low/high = the football field bar corners, mid = the base case), and the 52-week range (no midpoint: it isn't a valuation). Methods are not averaged or weighted into one target price; that weighting is the team's argument to make.
- When method midpoints sit on both sides of the current price, a note says so. Example (QCOM, October 2026): comps imply +84% to +222% at the peer median while the history-based DCF implies -51%, because QCOM grows 1.9% against size-band peers at 7.5%-33.6%.

Why it matters: judges test whether the numbers support the call, and the first questions are predictable: how does it compare, how much upside on which method, why those peers, and what assumption drives the DCF. Computing those answers from the same figures as the tables keeps the pitch consistent and checkable.
