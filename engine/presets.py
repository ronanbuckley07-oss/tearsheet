"""Starter ticker lists for common sectors.

These are a starting point for a sector screen or a peer list, not an answer:
FD-9 still applies (similar business model first, then size). Every ticker is a
US 10-K filer that loaded cleanly when the list was written (2026-10-10). Banks,
insurers and REITs are left out on purpose: EV/EBITDA doesn't describe them
(debt is their raw material), so they need P/B or P/FFO, which v1 doesn't compute.
"""

from __future__ import annotations

SECTORS: dict[str, tuple[str, ...]] = {
    "Semiconductors": ("NVDA", "AVGO", "AMD", "QCOM", "TXN", "INTC", "MU", "ADI", "MRVL", "NXPI", "ON", "MCHP"),
    "Semiconductor equipment": ("AMAT", "LRCX", "KLAC", "TER", "ENTG", "ONTO"),
    "Enterprise software": ("MSFT", "ORCL", "CRM", "ADBE", "NOW", "INTU", "WDAY", "ADSK", "SNOW", "DDOG", "TEAM"),
    "Cybersecurity": ("PANW", "CRWD", "FTNT", "ZS", "NET", "OKTA", "S", "QLYS", "TENB"),
    "Internet platforms": ("GOOGL", "META", "AMZN", "NFLX", "SNAP", "PINS", "RDDT"),
    "Payments": ("V", "MA", "PYPL", "FISV", "FIS", "GPN", "XYZ", "TOST"),
    "Big-box retail": ("WMT", "COST", "TGT", "HD", "LOW", "BJ", "DG", "DLTR"),
    "Restaurants": ("MCD", "SBUX", "CMG", "YUM", "DRI", "DPZ", "WING", "TXRH", "CAVA"),
    "Consumer staples": ("PG", "KO", "PEP", "CL", "KMB", "MDLZ", "KDP", "CHD"),
    "Pharma": ("LLY", "JNJ", "MRK", "PFE", "ABBV", "BMY", "AMGN", "GILD"),
    "Medical devices": ("ABT", "SYK", "BSX", "MDT", "ISRG", "EW", "BDX", "ZBH"),
    "Aerospace & defense": ("LMT", "RTX", "NOC", "GD", "BA", "LHX", "HII", "TXT"),
    "Machinery & electrical": ("CAT", "DE", "PH", "ETN", "EMR", "ITW", "CMI", "ROK"),
    "Oil & gas": ("CVX", "COP", "EOG", "OXY", "DVN", "FANG"),
    "Airlines": ("DAL", "UAL", "LUV", "AAL", "ALK", "JBLU"),
    "Travel & leisure": ("BKNG", "ABNB", "EXPE", "MAR", "HLT", "RCL", "CCL"),
    "Telecom & cable": ("T", "VZ", "TMUS", "CMCSA", "CHTR"),
    "Autos": ("TSLA", "GM", "F", "RIVN", "LCID"),
}


def sector_of(ticker: str) -> str | None:
    """The first preset that lists ``ticker``, if any."""
    t = ticker.upper()
    return next((name for name, ts in SECTORS.items() if t in ts), None)


def peers_for(ticker: str) -> list[str]:
    """The rest of the ticker's preset sector, as a starting peer list."""
    name = sector_of(ticker)
    return [] if name is None else [t for t in SECTORS[name] if t != ticker.upper()]
