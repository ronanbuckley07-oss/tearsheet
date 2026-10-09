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

Phase 0 (setup) is done. Phase 1 (data layer) code and fixture tests are written: `engine/tickers.py` and `engine/xbrl.py`. They have not yet been checked against live SEC data (`RUN_LIVE=1 pytest -m live`). To see what is extracted for a ticker, run `python scripts/inspect_ticker.py AAPL`.
