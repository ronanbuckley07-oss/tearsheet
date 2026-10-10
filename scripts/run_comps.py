"""Print a comps table, FD-7 stats and the FD-8 implied valuation.

Usage: python scripts/run_comps.py TARGET PEER1 PEER2 ...
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.comps import CONTEXT, MULTIPLES, _LABEL  # noqa: E402
from engine.report import build_report  # noqa: E402


def cell(f):
    if f.value is None:
        return "NM" if f.nm else "n/a"
    if f.unit == "x":
        return f"{f.value:.1f}x"
    if f.unit == "ratio":
        return f"{f.value:.1%}"
    if f.unit == "USD":
        return f"{f.value / 1e9:,.1f}bn"
    return f"{f.value:,.2f}"


def main(target, peers):
    r = build_report(target, peers)
    cols = ["equity_value", "enterprise_value", *MULTIPLES, *CONTEXT]
    heads = ["Equity val", "EV", *(_LABEL[c] for c in MULTIPLES + CONTEXT)]
    print(f"{'':8}{'LTM end':12}" + "".join(f"{h:>14}" for h in heads))
    for row in [r.target, *r.comps.peers]:
        tag = "* " if row is r.target else "  "
        if row.metrics is None:
            print(f"{tag}{row.ticker:6}  {row.error}")
            continue
        print(f"{tag}{row.ticker:6}{str(row.metrics.ltm_end):12}" + "".join(f"{cell(row.get(c)):>14}" for c in cols))
    print("\nPeer statistics (non-NM values only, FD-7)")
    for col, s in r.comps.stats.items():
        fmt = (lambda v: f"{v:.1%}") if col in ("revenue_growth_ltm", "ebitda_margin") else (lambda v: f"{v:.1f}x")
        vals = "  ".join(f"{k} {fmt(v) if v is not None else 'n/a'}"
                         for k, v in (("25th", s.p25), ("median", s.median), ("mean", s.mean), ("75th", s.p75)))
        print(f"  {_LABEL[col]:22} n={s.n:<3} {vals}")
        for t, why in s.excluded:
            print(f"  {'':22} excluded {t}: {why}")
    print("\nImplied share price (FD-8)")
    for key, ir in r.comps.implied.items():
        lo, mid, hi = ir.share_price
        if ir.reason:
            print(f"  {_LABEL[key]:12} n/a: {ir.reason}")
        else:
            print(f"  {_LABEL[key]:12} {ir.low_multiple:.1f}x-{ir.high_multiple:.1f}x on {ir.target_metric.value / 1e9:,.1f}bn"
                  f" -> ${cell(lo)} to ${cell(hi)} (median ${cell(mid)})")
    for b in r.comps.football_field():
        if b["label"] in ("52-week range", "Current price"):
            print(f"  {b['label']:12} " + (f"${b['low']:,.2f} to ${b['high']:,.2f}" if b["low"] else f"n/a ({b['reason']})"))
    if r.comps.notes:
        print("\nNotes:")
        for n in r.comps.notes:
            print(f"  - {n}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
