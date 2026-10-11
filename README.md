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

Phases 0 to 3 are done: the data layer, LTM periods, EBITDA, the EV bridge and multiples (validated in `SPEC.md` against NVDA, CRWV and AVGO within 0.5%), and the comps engine with FD-7 peer statistics and the FD-8 implied valuation. Phase 4 (the Streamlit app) and Phase 4b (a DCF, FD-11) are built and awaiting review.

- `streamlit run app.py`: the app. Enter a ticker and peers; every section has a "Sources" panel that shows the formula, the XBRL facts and a link to each filing behind any number.
- The DCF section sits under the comps: it starts from 3 years of 10-K history, the 10-year Treasury yield and an adjusted beta, and every assumption can be edited.
- Sector screen (Phase 4c, for pitch competitions): switch the view at the top to "Sector screen", pick one of 18 starter sector lists (or type tickers), and get every company side by side (size, growth, margins, multiples, premium/discount to the sector median, distance from the 52-week high), a valuation-vs-growth scatter with a fitted line, a ranking chart and computed talking points. "Open as a full tearsheet" takes the company you pick into the tearsheet with the rest of the sector as its peers.
- DCF model: after entering a ticker, "Download DCF model" gives a presentation-ready Excel DCF (FD-13): cover page with football field, an Inputs sheet (blue inputs), historicals and a 5-year projection, WACC build, perpetuity-growth and exit-multiple values, sensitivity tables and a Sources sheet. Every figure past the inputs is a live formula, and on the app's assumptions it ties to the app exactly.
- Exports: both views have "Download Excel" (numbers in $m, summary rows as live MEDIAN / QUARTILE.INC formulas, a Sources sheet with the XBRL facts behind every figure) and "Download PowerPoint" (16:9 slides with editable native tables and charts: overview and talking points, financial summary, comps, football field, DCF; or the sector overview, comps, rankings and scatter).
- Speed: companies load in parallel (the SEC rate limit is still shared across threads), prices are cached for 15 minutes per ticker, and SEC responses are cached on disk for a day, so a 12-company sector loads in a few seconds and re-screening is near instant.
- `python scripts/inspect_ticker.py AAPL`: raw extracted series with sources
- `python scripts/inspect_metrics.py AAPL --sources`: LTM figures, EV bridge and multiples, each with its formula and the filings behind it
- `python scripts/run_comps.py NVDA AMD AVGO QCOM TXN`: comps table, peer stats and implied share price range
- `RUN_LIVE=1 pytest -m live`: tests against real SEC and Yahoo Finance data

## Deploying

The app needs two settings, `SEC_USER_NAME` and `SEC_CONTACT_EMAIL` (the SEC rejects requests without them). Set them in the host's secrets, never in the repo. SEC responses are cached under `data/cache/`; on a hosted app that cache lasts until the app restarts, which is fine.

**Streamlit Community Cloud** (free, simplest):
1. At share.streamlit.io, choose "Create app", pick this repo, branch `main`, main file `app.py`.
2. Under "Advanced settings", pick Python 3.11 or later and paste into Secrets:
   ```toml
   SEC_USER_NAME = "Your Name"
   SEC_CONTACT_EMAIL = "you@example.com"
   ```
   Top-level secrets become environment variables, which is where the app reads them.
3. Deploy. A private repo works if you grant Streamlit access to it.

**Render**: New > Blueprint, select this repo. `render.yaml` sets the build and start commands (`streamlit run app.py --server.port $PORT --server.address 0.0.0.0`); fill in the two variables when asked. The free plan sleeps when idle, so the first load after a pause is slow.
