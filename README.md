# Tearsheet

Type a US public company's ticker and get an investment-banking-style profile: a snapshot, a financial summary, trading comps against a peer set, and an implied valuation range. Every number comes from SEC EDGAR or market price data and is computed in code. Each one can be traced back to its source filing.

- `SPEC.md`: the build plan and phases
- `FINANCE_DECISIONS.md`: how each financial figure is calculated
- `CLAUDE.md`: rules for Claude Code when working in this repo

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in your name and email (the SEC requires them)
pytest                 # offline unit tests
RUN_LIVE=1 pytest -m live   # optional: one real request to SEC EDGAR
streamlit run app.py
```

## Status

Phases 0 and 1 are done (data layer checked against live SEC data for AAPL, MSFT, GOOGL). Phase 2 (LTM periods, EBITDA, EV bridge, multiples) is built and awaiting review. Phase 2 is not done until the validation table in `SPEC.md` is filled in by hand and passes.

- `python scripts/inspect_ticker.py AAPL`: raw extracted series with sources
- `python scripts/inspect_metrics.py AAPL --sources`: LTM figures, EV bridge and multiples, each with its formula and the filings behind it
- `RUN_LIVE=1 pytest -m live`: tests against real SEC and Yahoo Finance data
