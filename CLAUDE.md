# Tearsheet: project context for Claude Code

## What this is

A web app where the user types a US public company's ticker and gets an investment-banking-style company profile: snapshot, financial summary, trading comps against a peer set, an implied valuation range, and (later) a written business overview. Built in Python with a Streamlit front end. The owner is a freshman recruiting for investment banking. The tool has to be correct, and he has to be able to explain every number it produces in an interview.

Read SPEC.md for the build plan and FINANCE_DECISIONS.md for how each financial figure must be calculated.

## Non-negotiable rules

1. Numbers never come from an LLM. Every figure in the report is pulled from SEC EDGAR or market price data and computed in code. The LLM only writes narrative text and suggests peer tickers, and its peer suggestions must be validated against the SEC ticker list before use.
2. Every number is traceable. Each extracted value carries its source: XBRL tag, filing form (10-K/10-Q), accession number, period start/end, and filed date. The UI must be able to show this for any figure.
3. When data is missing or ambiguous, say so. Show "NM" (not meaningful) or "n/a" with a reason. Never fill a gap with an estimate, a default, or a value from a different period without flagging it.
4. Finance logic follows FINANCE_DECISIONS.md exactly. The owner delegated new finance judgment calls to Claude (2026-10-10): when FINANCE_DECISIONS.md doesn't cover one, pick the standard banking convention, record it in FINANCE_DECISIONS.md with the reasoning, flag it in the phase summary, and keep building. Code that implements a decision should cite it in a comment (e.g. `# FD-2: operating leases excluded from EV`).
5. Build one phase at a time (see SPEC.md). At the end of each phase: run the tests, summarize what was built and anything you were unsure about, and stop for review. Do not start the next phase or add features outside the current one.
6. Explain finance-relevant choices in plain language when you make them, so the owner learns the mechanics, not just the result.

## Technical conventions

- Python 3.11+. Dependencies in requirements.txt. Secrets (Anthropic API key, SEC contact email) in a .env file loaded with python-dotenv; commit a .env.example, never the .env.
- SEC requests must send a User-Agent header with a name and email (from .env), and stay under 10 requests per second. Cache every SEC response on disk so repeat runs don't re-download.
- Keep the engine (data, calculations, report assembly) separate from the Streamlit UI. app.py should contain no finance logic.
- Write tests with pytest. Calculation functions (LTM, EV bridge, multiples) get unit tests with small hand-built fixtures.
- Use the Anthropic API model `claude-sonnet-5-5` for narrative and peer suggestions.
