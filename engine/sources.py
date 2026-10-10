"""Flatten a Figure into the rows the UI shows in its "sources" panels (CLAUDE.md rule 2).

For every number: its formula, the XBRL facts behind it (tag, form, accession,
period, filed date, link to the filing), any non-SEC source (the share price),
and every note or flag raised along the way.
"""

from __future__ import annotations

from engine.periods import Figure


def fact_rows(fig: Figure, cik: int | None) -> list[dict]:
    """Every XBRL fact under ``fig`` (its own and its inputs'), deduplicated."""
    rows, seen = [], set()

    def walk(f: Figure, sign: int) -> None:
        for s, fact in f.facts:
            for one in fact.sources:
                key = (sign * s, one.tag, one.accession, fact.start, fact.end)
                if key in seen:
                    continue
                seen.add(key)
                rows.append({
                    "": "+" if sign * s > 0 else "−",
                    "value": fact.value if len(fact.sources) == 1 else None,
                    "tag": f"{one.taxonomy}:{one.tag}",
                    "period": f"{fact.start} to {fact.end}" if fact.start else f"at {fact.end}",
                    "form": one.form,
                    "accession": one.accession,
                    "filed": str(one.filed),
                    "link": one.filing_url(cik) if cik else "",
                    "note": fact.note or ("summed parts" if len(fact.sources) > 1 else ""),
                })
        # A sum (metrics.combine) already carries its inputs' signed facts; walk the
        # inputs that don't (e.g. equity value = price x shares inside the EV sum).
        for i in f.inputs:
            if not f.facts or not i.facts:
                walk(i, sign)

    walk(fig, 1)
    return rows


def other_sources(fig: Figure) -> list[str]:
    out = []

    def walk(f: Figure) -> None:
        line = f"{f.name}: {f.source} ({f.formula})" if f.source else None
        if line and line not in out:
            out.append(line)
        for i in f.inputs:
            walk(i)

    walk(fig)
    return out


def formula_tree(fig: Figure, depth: int = 0, max_depth: int = 4) -> list[str]:
    """Indented 'name = value: formula' lines, top figure first."""
    pad = "  " * depth
    value = "n/a" if fig.value is None else f"{fig.value:,.6g}" if abs(fig.value) < 1000 else f"{fig.value:,.0f}"
    if fig.nm:
        value = "NM"
    line = f"{pad}{fig.name} = {value} [{fig.unit}]: {fig.formula}"
    if fig.reason:
        line += f" ({fig.reason})"
    lines = [line]
    if depth < max_depth:
        for i in fig.inputs:
            lines.extend(formula_tree(i, depth + 1, max_depth))
    return lines
