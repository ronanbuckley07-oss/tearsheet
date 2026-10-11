"""Deep learn mode: interview-level material for each Learn chapter (FD-14).

Fixed text written for this app, no LLM at run time (CLAUDE.md rule 1). Each
chapter of engine/learn.py COURSE gets a few deep-dive sections; every section
ends with its own questions so the reader can check themselves before moving
on. The worked numbers in the answers are illustrations, not company data.

Conventions used in the answers (standard in banking interviews): a 25% tax
rate unless stated, the treasury stock method for dilution, unlevered free cash
flow for the DCF.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Section:
    title: str
    body: tuple[str, ...]  # paragraphs (markdown)
    questions: tuple[tuple[str, str], ...]  # (question, answer)


S = Section

DEEP: dict[int, tuple[Section, ...]] = {
    # 1. What this tool does
    0: (
        S("The main valuation methods",
          ("Bankers triangulate value with several methods and show them side by side on a football field:",
           "- **Trading comps**: what similar public companies trade at today (EV/EBITDA, EV/Revenue, P/E), applied "
           "to the target. Market-based, quick, reflects current sentiment.\n"
           "- **Precedent transactions**: what acquirers actually paid for similar companies in past deals. "
           "Includes a control premium, so it usually gives the highest values.\n"
           "- **DCF**: the present value of the company's own projected free cash flows. Intrinsic, so it doesn't "
           "depend on the market being right, but it is very sensitive to assumptions.\n"
           "- **LBO analysis**: the most a financial sponsor could pay and still earn its target return (often "
           "20-25% IRR). Gives a floor-like value for sponsor-relevant companies.",
           "Tearsheet builds the first and third (comps and DCF) plus the 52-week trading range. Precedents need "
           "deal data that the SEC company facts don't contain."),
          (("What are the main ways to value a company?",
            "Relative valuation (trading comps and precedent transactions) and intrinsic valuation (DCF). Many "
            "banks also show an LBO analysis and the 52-week trading range on the football field."),
           ("Which method usually gives the highest value, and why?",
            "Precedent transactions, because the prices include a control premium (often 20-40%) that buyers pay "
            "to own the whole company, plus expected synergies. A DCF can be higher or lower depending on the "
            "assumptions; it is the most variable."),
           ("When would you not use a DCF?",
            "When cash flows are very hard to forecast or negative for years (early-stage biotech, some startups), "
            "or for banks and insurers, where debt is part of operations, so 'unlevered' free cash flow isn't "
            "meaningful. Banks are valued on P/E, P/B and dividend discount models instead."))),
        S("Where the numbers come from",
          ("US public companies file with the SEC: the **10-K** (annual, audited), the **10-Q** (quarterly, "
           "reviewed but not audited), the **8-K** (major events: earnings releases, deals, executive changes) and "
           "the **proxy (DEF 14A)** (pay, board, voting). Since 2009 the financial statements are also tagged in "
           "**XBRL**, a machine-readable format: every number carries a tag like us-gaap:Revenues, a period and "
           "the filing it came from. That is what Tearsheet reads.",
           "The share price comes from the market. Shares outstanding come from the cover page of the latest "
           "10-K or 10-Q (FD-3), which is more current than the weighted-average count in the income statement.",
           "Two things to say in an interview: filings are the primary source, and you know which line of which "
           "filing a number came from. That is the habit analysts are hired for."),
          (("What's the difference between a 10-K and a 10-Q?",
            "The 10-K is the annual report: audited, with full notes, business description (Item 1), risk factors "
            "(Item 1A) and MD&A (Item 7). The 10-Q covers a quarter: unaudited, shorter, with year-to-date "
            "figures. There is no Q4 10-Q; Q4 is the 10-K minus the first three quarters."),
           ("Where would you find a company's share count for a valuation?",
            "The cover page of the latest 10-K or 10-Q for basic shares outstanding, plus the equity footnote for "
            "options, RSUs and convertibles, which you add using the treasury stock method to get diluted "
            "shares."))),
    ),
    # 2. Income statement
    1: (
        S("The three statements and how they link",
          ("**Income statement**: revenue down to net income over a period. **Balance sheet**: assets = liabilities "
           "+ equity at a point in time. **Cash flow statement**: starts from net income, adds back non-cash items "
           "(D&A, stock comp), adjusts for working capital, then investing (capex, acquisitions) and financing "
           "(debt, buybacks, dividends), and ends with the change in cash.",
           "The links: net income flows into retained earnings (balance sheet) and is the first line of the cash "
           "flow statement. The ending cash on the cash flow statement is the cash on the balance sheet. Capex "
           "increases PP&E; depreciation reduces it. Changes in working capital accounts on the balance sheet show "
           "up in operating cash flow.",
           "The classic interview test: change one line and walk it through all three statements, assuming a tax "
           "rate (25% here)."),
          (("Walk me through the three statements if depreciation goes up by $10 (25% tax).",
            "Income statement: operating income falls $10; taxes fall $2.50; net income falls $7.50. Cash flow: "
            "net income -$7.50, add back +$10 depreciation (non-cash), so cash from operations is up $2.50; cash "
            "ends $2.50 higher. Balance sheet: cash +$2.50, PP&E -$10, so assets are down $7.50; retained earnings "
            "(equity) are down $7.50. It balances. The cash gain is the tax saving."),
           ("A company buys $100 of inventory with cash. What changes?",
            "Nothing on the income statement (no sale yet). Cash flow: inventory up is a use of cash, so operating "
            "cash flow falls $100. Balance sheet: cash -$100, inventory +$100; total assets unchanged."),
           ("If you could use only one statement to judge a company, which would it be?",
            "The cash flow statement: it shows the cash the business actually generates and spends, and it can't "
            "be flattered by accrual accounting as easily. (Many interviewers accept the balance sheet if you "
            "argue it, but cash flow is the usual answer.)"))),
        S("EBITDA, adjustments and non-GAAP",
          ("EBITDA isn't a GAAP number; companies and banks each define 'adjusted EBITDA'. Common adjustments add "
           "back stock-based compensation, restructuring charges, impairments and one-off legal costs. Each "
           "add-back makes the multiple look cheaper, so check what has been added back before comparing.",
           "Tearsheet keeps stock comp as a real expense (FD-1): it is paid in shares instead of cash, but it is "
           "pay, and it dilutes shareholders. That makes its EBITDA lower and its multiples higher than many "
           "company-reported 'adjusted' figures.",
           "Interest, taxes and D&A are excluded because they depend on capital structure, tax jurisdiction and "
           "past investment rather than on how well the business operates today."),
          (("Should you add back stock-based compensation to EBITDA?",
            "There are two views. Adding it back treats it as non-cash, which is true for the company's cash. "
            "Leaving it in treats it as a real cost of paying employees, which shareholders bear through dilution. "
            "Whichever you choose, be consistent across all comps. This app leaves it in."),
           ("Why might EBITDA overstate cash generation?",
            "It ignores capex (a capital-heavy company has to keep reinvesting), changes in working capital, "
            "taxes and interest. A telecom or chip fab can have high EBITDA and low free cash flow."),
           ("What is the difference between EBIT and operating income?",
            "Usually nothing: both are profit before interest and taxes from operations. EBIT sometimes includes "
            "non-operating income (gains, equity-method income), so be specific about what's in it."))),
        S("LTM, calendarization and growth",
          ("**LTM** (last twelve months) = latest fiscal year + current year-to-date - prior year-to-date. It "
           "keeps every company current: Apple's fiscal year ends in September and NVIDIA's in January, so their "
           "fiscal years cover different months.",
           "**Calendarization** lines up fiscal years to calendar years when comparing forecasts (for example "
           "taking 3/12 of one fiscal year and 9/12 of the next). LTM avoids this for historical figures.",
           "Growth should be judged against the base: 80% growth from a small base is less impressive than 20% "
           "from a huge one, and a one-off year (a pandemic, a product launch) distorts year-on-year growth."),
          (("Why do comps use LTM rather than last fiscal year?",
            "LTM is the most recent twelve months for every company, regardless of fiscal year end, so the "
            "comparison is current and like-for-like."),
           ("How do you calculate LTM revenue for a company that just reported Q2?",
            "Last full fiscal year revenue + first-half revenue this year - first-half revenue last year."))),
        S("Margins and operating leverage",
          ("Margins (gross, EBITDA, EBIT, net) show how much of each revenue dollar becomes profit at each level. "
           "**Gross margin** tells you about pricing power and production cost; **EBITDA margin** about the whole "
           "cost structure.",
           "**Operating leverage**: when a large share of costs is fixed (R&D, software development, a factory), "
           "profit grows faster than revenue as the company scales, and falls faster in a downturn. Software "
           "and semiconductors are classic high-operating-leverage businesses."),
          (("Revenue grows 20% and EBITDA grows 40%. What's happening?",
            "Operating leverage: costs grew more slowly than revenue (some are fixed), so margins expanded."),
           ("Two companies have the same revenue. One has a 60% EBITDA margin, the other 20%. Which deserves the "
            "higher EV/Revenue multiple?",
            "Usually the 60% margin company, because each revenue dollar produces three times the EBITDA. That's "
            "why EV/Revenue only makes sense when compared with margins and growth."))),
    ),
    # 3. Equity value and EV
    2: (
        S("Equity value vs enterprise value in depth",
          ("**Equity value** = what belongs to shareholders. **Enterprise value** = the value of the operating "
           "business to all capital providers. The bridge: EV = equity value + debt + preferred stock + "
           "noncontrolling interest - cash and investments (FD-2). Some banks also add operating leases, unfunded "
           "pensions and capital leases; Tearsheet includes finance leases but not operating leases.",
           "Why each item: debt and preferred are claims ranking ahead of common equity. Noncontrolling interest is "
           "added because the company consolidates 100% of a subsidiary's EBITDA but doesn't own all of it. Cash "
           "is subtracted because it isn't part of the operating business and a buyer effectively gets it back.",
           "Equity method investments (stakes of roughly 20-50%) are often subtracted too, because their income "
           "isn't in EBITDA."),
          (("Why do you subtract cash in the EV calculation?",
            "Cash is a non-operating asset. A buyer of the business gets it, which reduces the net price paid, and "
            "EBITDA doesn't include interest earned on it. Subtracting it keeps EV matched with operating metrics."),
           ("Why add noncontrolling interest?",
            "Because the parent consolidates 100% of the subsidiary's revenue and EBITDA. To compare EV with that "
            "EBITDA consistently, EV must also include the value of the part owned by outsiders."),
           ("Can enterprise value be negative?",
            "Yes, if cash exceeds equity value plus debt. It happens with distressed companies or ones holding "
            "lots of cash the market discounts. Multiples are then NM."))),
        S("Diluted shares and the treasury stock method",
          ("Equity value should use **diluted** shares: basic shares plus in-the-money options, RSUs and "
           "convertibles. The **treasury stock method** (TSM) assumes options are exercised and the company uses "
           "the exercise proceeds to buy back shares at the current price.",
           "Example: share price $50, 100m basic shares, 10m options at a $30 strike. Exercise brings in 10m x $30 "
           "= $300m, which buys back $300m / $50 = 6m shares. Net new shares = 10m - 6m = 4m, so diluted shares = "
           "104m and diluted equity value = 104m x $50 = $5.2bn.",
           "Out-of-the-money options (strike above the price) are ignored. RSUs are added in full (no exercise "
           "price). Convertibles are added if in the money (if-converted method). Tearsheet uses cover-page "
           "shares and cross-checks them against diluted weighted-average shares (FD-3)."),
          (("A company has 50m shares at $20 and 5m options with a $10 strike. Diluted shares?",
            "Proceeds = 5m x $10 = $50m; buyback = $50m / $20 = 2.5m shares; net new = 5m - 2.5m = 2.5m; diluted "
            "shares = 52.5m."),
           ("Why use diluted rather than basic shares?",
            "Option and RSU holders have a claim on the equity. Ignoring them overstates value per share, "
            "especially in tech, where stock comp is large."))),
        S("What changes EV and what doesn't",
          ("Test your understanding by asking which side of the bridge moves.",
           "- **Issue $100 of new shares for cash**: equity value +$100, cash +$100, EV unchanged.\n"
           "- **Raise $100 of debt, keep the cash**: debt +$100, cash +$100, EV unchanged; equity unchanged.\n"
           "- **Use $100 of cash to repay debt**: cash -$100, debt -$100, EV unchanged.\n"
           "- **Pay a $100 dividend**: cash -$100, equity value falls about $100 (the share price drops), EV "
           "unchanged.\n"
           "- **Buy back $100 of shares**: cash -$100, equity value -$100, EV unchanged.\n"
           "- **The business wins a big contract**: the share price rises, equity value and EV both rise.",
           "Rule: financing moves don't change EV; only things that change the value of the operations do."),
          (("A company issues $200 of debt and uses it to buy back shares. What happens to EV and equity value?",
            "Debt +$200; equity value -$200 (fewer shares, same price, in theory); EV unchanged. In practice the "
            "price may move as leverage and the tax shield change."),
           ("Why is EV called 'capital structure neutral'?",
            "Because it values the operations regardless of how they're financed: shifting between debt and "
            "equity changes equity value but not EV. That's why EV multiples compare companies with different "
            "leverage fairly."))),
    ),
    # 4. Multiples
    3: (
        S("Matching numerator and denominator",
          ("The rule: an EV multiple needs a metric that belongs to all capital providers (before interest): "
           "revenue, EBITDA, EBIT, unlevered free cash flow. An equity value multiple needs a metric after "
           "interest that belongs to shareholders: net income (P/E), levered free cash flow, book value (P/B).",
           "EV/Net income or P/EBITDA mix the two and are wrong: they would make a company look cheaper or more "
           "expensive just because of how much debt it has."),
          (("Why is EV/Net income a meaningless multiple?",
            "Net income is after interest, so it belongs only to shareholders, while EV covers debt and equity "
            "holders. The ratio would change with leverage even if the business didn't."),
           ("Which multiple would you use for a company with negative EBITDA?",
            "EV/Revenue, or an industry metric (EV/subscribers, EV/ARR). Forward multiples (next year's EBITDA) "
            "help if it turns profitable soon."))),
        S("Why multiples differ",
          ("A multiple is a shorthand DCF. Under a constant-growth model, EV/FCF = 1 / (WACC - g). So multiples "
           "are higher when **growth is higher**, **risk (WACC) is lower**, and **more of each dollar of EBITDA "
           "turns into free cash flow** (low capex, high return on capital).",
           "That's why a fast-growing software company can trade at 30x EBITDA while a steel company trades at "
           "5x: the market expects the software company's cash flow to grow much faster and be more reliable."),
          (("Two companies have identical EBITDA and growth. Why might one trade at a higher multiple?",
            "Lower risk (lower WACC: more recurring revenue, less cyclical), lower capex needs (more free cash "
            "flow per dollar of EBITDA), better margins outlook, or a cleaner balance sheet."),
           ("What does a P/E of 20x imply in a simple model?",
            "Investors pay $20 for $1 of earnings, an earnings yield of 5%. With constant growth, P/E ≈ payout / "
            "(cost of equity - g), so higher growth or lower risk supports a higher P/E."))),
        S("LTM vs forward, and industry multiples",
          ("**LTM** multiples use actual reported numbers. **Forward** multiples (NTM, next year) use analyst "
           "estimates and are more common in pitch books for growing companies, because the market prices the "
           "future. Tearsheet uses LTM only, since estimates aren't in SEC filings.",
           "Industry multiples: banks P/E and P/Tangible book; REITs P/FFO; airlines and retailers EV/EBITDAR "
           "(adds rent); SaaS EV/ARR or EV/Revenue; energy EV/reserves or EV/production."),
          (("Why value banks on P/B instead of EV/EBITDA?",
            "For a bank, debt (deposits) is raw material, not financing, and interest is its revenue and cost of "
            "goods. EV and EBITDA lose meaning. Book equity is regulated capital, so price to book is the anchor."),
           ("Would you expect the forward multiple to be higher or lower than LTM for a growing company?",
            "Lower: the same EV divided by a bigger (next-year) EBITDA."))),
    ),
    # 5. Comps
    4: (
        S("Choosing peers",
          ("Good comps share the business model, end markets, size, growth and margin profile, and geography. "
           "Start with the company's own list of competitors (10-K Item 1), the SIC code, and the peers equity "
           "research uses; then trim outliers. Aim for 6-12 peers (FD-9).",
           "If no peer is a perfect match, use tiers: a core set of close peers and a broader set, and say which "
           "one drives your range."),
          (("How would you pick comps for a company?",
            "Same industry and business model, similar size, growth and margins, same geography. Use the 10-K's "
            "competitor list and equity research, then screen by market cap and growth, and drop outliers."),
           ("What if your company has no good comps?",
            "Widen the criteria (adjacent sectors, a broader size range), weight the DCF more heavily, and be "
            "explicit about the limitations."))),
        S("Precedent transactions and control premiums",
          ("Precedents use the price paid in past acquisitions: deal EV / target LTM EBITDA at announcement. "
           "Pick recent deals (ideally the last 3-5 years) of similar companies, because valuations depend on the "
           "market at the time.",
           "Prices include a **control premium**, usually 20-40% over the undisturbed share price, because a "
           "buyer gains control of cash flows and strategy and expects synergies. That's why precedents usually "
           "give higher values than trading comps."),
          (("Why do precedent transactions usually give a higher value than trading comps?",
            "The control premium and expected synergies paid by the acquirer."),
           ("What are the weaknesses of precedents?",
            "Few truly comparable deals, old deals reflect different markets, deal terms (cash vs stock, earn-outs) "
            "and synergies vary, and data is less available for private targets."))),
        S("From multiples to an implied price",
          ("Implied EV = peer multiple x target metric. Then subtract debt, preferred and noncontrolling interest, "
           "add cash: implied equity value. Divide by diluted shares: implied share price (FD-8). Use the 25th-75th "
           "percentile for the range and the median for the midpoint.",
           "Worked example: peers' EV/EBITDA median 12x, target EBITDA $500m, so implied EV $6.0bn. With $1.0bn "
           "debt and $0.4bn cash, implied equity value = $5.4bn. With 200m shares, implied price = $27."),
          (("Peer median EV/EBITDA is 10x. Target EBITDA $200m, debt $300m, cash $100m, 50m shares. Implied price?",
            "EV = $2.0bn; equity = $2.0bn - $0.3bn + $0.1bn = $1.8bn; price = $1.8bn / 50m = $36."),
           ("Why not apply P/E directly to get a price?",
            "You can (P/E x EPS = price), and banks do show it. But P/E is distorted by leverage, tax and "
            "one-offs, so EV/EBITDA is usually the primary method and P/E a cross-check."))),
    ),
    # 6. DCF
    5: (
        S("Unlevered free cash flow in depth",
          ("UFCF = EBIT x (1 - tax rate) + D&A - capex - increase in net working capital. Each piece:",
           "- **EBIT x (1 - t)** = NOPAT: operating profit after tax, ignoring interest.\n"
           "- **+ D&A**: non-cash, already deducted in EBIT.\n"
           "- **- capex**: the cash cost of the equipment that D&A slowly expenses.\n"
           "- **- increase in NWC**: growing companies tie up cash in receivables and inventory faster than "
           "suppliers fund them. A decrease in NWC releases cash.",
           "Other non-cash items (stock comp, deferred taxes) are sometimes added back. Tearsheet leaves stock comp "
           "in as a cost (FD-1), which is the conservative choice."),
          (("Why is it called unlevered free cash flow?",
            "It is calculated before interest payments, as if the company had no debt, so it is the cash "
            "available to all capital providers, both lenders and shareholders."),
           ("What is the difference between unlevered and levered free cash flow?",
            "Levered FCF subtracts interest (after tax) and net debt repayments, so it is cash for shareholders "
            "only. Discount it at the cost of equity and you get equity value directly."),
           ("How does an increase in accounts receivable affect free cash flow?",
            "It reduces it: revenue was booked but the cash hasn't been collected, so working capital rose and "
            "cash is tied up."))),
        S("WACC in depth",
          ("WACC = E/(D+E) x cost of equity + D/(D+E) x cost of debt x (1 - t). Use **market values** for the "
           "weights (or a target capital structure for a company whose structure will change).",
           "**Cost of equity (CAPM)** = risk-free rate + beta x equity risk premium. The risk-free rate is the "
           "10-year Treasury yield; the ERP is usually 5-6%; beta measures how the stock moves with the market.",
           "**Levering and unlevering beta**: a company's observed beta includes its own leverage. To use peers' "
           "betas, unlever each: unlevered beta = levered beta / (1 + (1 - t) x D/E). Take the median, then "
           "relever at the target's structure: levered = unlevered x (1 + (1 - t) x D/E). Tearsheet uses the "
           "company's own adjusted beta (FD-11).",
           "**Cost of debt**: the yield on the company's bonds, or interest expense / debt. It is multiplied by "
           "(1 - t) because interest is tax-deductible (the tax shield)."),
          (("Why is the cost of debt lower than the cost of equity?",
            "Lenders are paid first and have a fixed claim, so they take less risk; and interest is tax-deductible, "
            "lowering the after-tax cost further."),
           ("A company adds more debt. What happens to WACC?",
            "At first WACC falls, because cheap after-tax debt replaces expensive equity. But the cost of equity "
            "rises (higher levered beta) and eventually the cost of debt rises with default risk, so beyond some "
            "point WACC rises again."),
           ("Unlever a 1.5 beta with D/E 0.5 and 25% tax.",
            "1.5 / (1 + 0.75 x 0.5) = 1.5 / 1.375 = 1.09."))),
        S("Terminal value methods",
          ("**Perpetuity (Gordon) growth**: TV = FCF in year 5 x (1 + g) / (WACC - g). g should be at or below "
           "long-run nominal GDP growth (2-3%). **Exit multiple**: TV = year-5 EBITDA x an EV/EBITDA multiple from "
           "today's comps.",
           "Each cross-checks the other: compute the multiple your perpetuity value implies, and the growth rate "
           "your exit multiple implies. Tearsheet shows both (FD-11). If the perpetuity implies 25x when peers "
           "trade at 12x, your growth or WACC is too generous.",
           "The TV is discounted from year 5 (4.5 under the mid-year convention for the perpetuity method), not "
           "from year 6."),
          (("Which terminal value method do you prefer?",
            "Bankers often lead with the exit multiple because it ties to market data, academics prefer perpetuity "
            "growth because it doesn't import today's market sentiment into year 5. The good answer: use both "
            "and check that their implied growth and implied multiple are reasonable."),
           ("What growth rate would you use in perpetuity, and why?",
            "Around 2-3%, near long-run inflation plus a little real growth. Anything above long-run GDP growth "
            "implies the company eventually becomes larger than the economy."),
           ("If terminal value is 80% of EV, is that a problem?",
            "It is common for growth companies, but it means the answer rests on WACC and terminal growth. Show "
            "a sensitivity table and check the implied exit multiple."))),
        S("Mid-year, stubs and sanity checks",
          ("The **mid-year convention** assumes cash arrives evenly through each year, so year 1 is discounted 0.5 "
           "years, year 2 1.5 years, and so on. It raises the value slightly. A **stub period** handles a "
           "valuation date partway through a fiscal year: the first period is a fraction of a year.",
           "Sanity checks: implied exit multiple vs peers; TV share of EV; terminal growth below WACC; whether "
           "margins and capex in year 5 are believable for a mature company (Tearsheet's steady-state toggle "
           "sets terminal capex equal to D&A); and the DCF price vs the current price and comps."),
          (("What does the mid-year convention do to the valuation?",
            "Increases it slightly, because each cash flow is discounted half a year less."),
           ("Your DCF says the stock is worth 3x its current price. What do you check?",
            "Growth and margins against history and peers, the terminal value share and implied exit multiple, "
            "WACC inputs (beta, ERP), terminal capex vs D&A, and whether you used the right share count and net "
            "debt."))),
    ),
    # 7. What moves a valuation
    6: (
        S("Sensitivity tables and scenarios",
          ("A **sensitivity table** reruns the model across a grid of two inputs, usually WACC and terminal "
           "growth (or exit multiple). A **scenario** changes several assumptions together into a coherent story: "
           "base, upside (faster growth, margin expansion) and downside (recession).",
           "In an interview or pitch, the point is to say which assumption your answer depends on and why you "
           "believe it. The tornado chart in this app ranks the inputs by how much one notch moves the price."),
          (("Which has a bigger impact on a DCF: a 10% change in revenue or a 1% change in the discount rate?",
            "Usually the discount rate: a 1-point change in WACC often moves value by 10-15% or more for a growth "
            "company, mostly through the terminal value. A 10% revenue change moves value roughly 10% if margins "
            "hold. Run both in the tornado chart to see for a real company."),
           ("Why show a range instead of one number?",
            "Because every input is an estimate; a range makes the uncertainty explicit and shows which inputs "
            "drive it."))),
        S("Interest rates, inflation and valuation",
          ("Rates enter through the risk-free rate and the cost of debt. Higher rates raise WACC, lower the "
           "present value of every future cash flow, and hit long-duration assets (growth companies whose cash "
           "comes far in the future) hardest. That's why tech stocks often fall when rates rise.",
           "Inflation raises nominal revenue and costs; if a company can pass prices through, nominal cash flows "
           "rise and partly offset a higher discount rate."),
          (("Why do growth stocks fall more than value stocks when rates rise?",
            "More of their value is in distant cash flows and the terminal value, which shrink most when the "
            "discount rate rises."),
           ("Rates fall 1%. Walk me through the DCF.",
            "The risk-free rate falls, so the cost of equity and WACC fall (and possibly the cost of debt). "
            "Discount factors rise, the terminal value denominator (WACC - g) shrinks, and EV and the share price "
            "rise. Cash flows are unchanged."))),
        S("Common DCF mistakes",
          ("- Terminal growth above long-run GDP growth, or WACC too close to g.\n"
           "- Capex that stays far above D&A forever while growth falls to the terminal rate.\n"
           "- Margins that expand every year with no reason.\n"
           "- Mixing levered and unlevered: discounting UFCF at the cost of equity, or levered FCF at WACC.\n"
           "- Forgetting to subtract net debt, or using basic instead of diluted shares.\n"
           "- Using book value weights in WACC instead of market values."),
          (("You discount unlevered FCF at the cost of equity. What goes wrong?",
            "You mix a cash flow for all investors with a return for shareholders only. For a levered company the "
            "cost of equity is above WACC, so you understate EV."),
           ("Why should terminal capex be close to D&A?",
            "In a steady state the company only needs to replace worn-out assets plus a little for growth at the "
            "terminal rate. Capex far above D&A forever implies a permanent build-out that a slow-growing company "
            "wouldn't need."))),
    ),
    # 8. From numbers to a pitch
    7: (
        S("Pitching a stock",
          ("A good pitch in 2 minutes: (1) the company and recommendation (buy/sell, target price, upside); "
           "(2) two or three **investment theses**, each one where you disagree with the market and why; "
           "(3) valuation: comps and DCF, what the price implies and your target; (4) catalysts that will prove "
           "you right (earnings, product launches, a deal); (5) risks and what would make you wrong.",
           "Use the sector screen to find a stock that's cheap versus peers given its growth and margins, then "
           "the tearsheet to check why, and the DCF's tornado chart to know which assumption you're betting on."),
          (("Pitch me a stock.",
            "Name it and the call (for example 'Buy, $X target, Y% upside'), give two specific theses with "
            "numbers, explain how you valued it (comps and a DCF), name a catalyst and a key risk. Keep it under "
            "two minutes and know every number."),
           ("What's a catalyst?",
            "An event that will make the market recognise the value you see: an earnings release, a product "
            "launch, a margin target hit, a spin-off or an acquisition."))),
        S("Mergers: accretion and dilution",
          ("In an acquisition, the buyer's EPS after the deal can rise (**accretive**) or fall (**dilutive**). For "
           "an all-stock deal, a quick rule: if the buyer's P/E is higher than the P/E it pays for the target, "
           "the deal is accretive, because it issues expensive stock to buy cheaper earnings.",
           "With cash or debt, compare the target's earnings yield (1 / P/E paid) with the after-tax cost of cash "
           "(foregone interest) or debt. If the yield exceeds the cost, the deal is accretive. Synergies help; "
           "transaction costs and new amortization of intangibles hurt."),
          (("Buyer P/E 20x, target bought at 15x, all stock. Accretive or dilutive?",
            "Accretive: the buyer's earnings yield is 5%, the target's is 6.7%; it issues shares with a 5% "
            "'cost' to buy earnings yielding 6.7%."),
           ("Does accretive mean it's a good deal?",
            "No. EPS accretion ignores whether the price exceeds the target's value. A deal can be accretive and "
            "still destroy value if the buyer overpays."))),
        S("LBOs in one page",
          ("In a leveraged buyout, a private equity firm buys a company with mostly debt (often 50-70% of the "
           "price), uses the company's cash flow to pay down debt, and sells after 3-7 years. Returns are measured "
           "by IRR and money multiple (MOIC).",
           "Return drivers: **EBITDA growth**, **debt paydown** (equity's share of EV grows), and **multiple "
           "expansion** (selling at a higher multiple than bought). A good LBO candidate has stable cash flows, low "
           "capex needs, a strong market position and room for cost cuts."),
          (("Why does using leverage increase returns in an LBO?",
            "The sponsor puts in less equity, and the cheaper debt captures a fixed return; all the gain in value "
            "above the debt cost goes to the equity, so the return on the smaller equity cheque is higher. It "
            "also raises risk."),
           ("Buy at $100 with $40 equity and $60 debt; sell at $150 after 5 years with $20 debt left. MOIC and "
            "rough IRR?",
            "Exit equity = $150 - $20 = $130; MOIC = 130 / 40 = 3.25x. Over 5 years that's about 27% IRR "
            "(3.25^(1/5) ≈ 1.266)."),
           ("What makes a good LBO candidate?",
            "Stable, predictable cash flow; low capex; a defensible market position; a clean balance sheet to "
            "borrow against; and clear ways to improve operations."))),
    ),
}
