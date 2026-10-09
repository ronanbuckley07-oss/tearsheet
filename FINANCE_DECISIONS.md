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
