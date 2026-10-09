"""Print what Phase 1 extracts for a ticker, with sources.

Usage: python scripts/inspect_ticker.py AAPL
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.sec_client import SECClient  # noqa: E402
from engine.tickers import get_metadata, lookup  # noqa: E402
from engine.xbrl import PeriodType, extract_all, get_company_facts  # noqa: E402


def main(ticker: str) -> None:
    client = SECClient()
    company = lookup(ticker, client)
    meta = get_metadata(company.cik, client)
    series = extract_all(get_company_facts(company.cik, client))

    print(f"{company.name}  CIK {company.cik10}  SIC {meta.sic} ({meta.sic_description})")
    print(f"Fiscal year end {meta.fiscal_year_end}  10-K filer: {meta.in_scope}\n")
    for name, s in series.items():
        latest = s.latest(PeriodType.ANNUAL) or s.latest()
        if latest is None:
            print(f"{name:28} n/a  {'; '.join(s.notes)}")
            continue
        src = latest.source
        period = f"{latest.start}..{latest.end}" if latest.start else f"@{latest.end}"
        flags = (" RESTATED" if latest.restated else "") + (f" [{latest.note}]" if latest.note else "")
        print(f"{name:28} {latest.value:>20,.0f} {latest.unit:6} {latest.period_type.value:8} "
              f"{period:24} {latest.tag} {src.form} {src.accession} filed {src.filed}{flags}")
        for n in s.notes:
            print(f"{'':28} note: {n}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "AAPL")
