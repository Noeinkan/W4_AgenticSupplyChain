"""
Commodity families and the HS codes that identify them.

One table, read by three layers that used to each hard-code their own codes:

  * ingestion - which HS codes Comtrade polls, and which news keywords tag an
    article with a family's codes;
  * the monitor node - an event tagged with HS codes only reaches a profile whose
    codes belong to the same family;
  * the simulator - alternative suppliers are drawn from the same family, so a
    diesel run never "reroutes" volume onto a T-shirt factory.

Matching is by prefix and the longest prefix wins, which is what lets 8505
(permanent magnets) sit in ``rare_earths`` while the rest of chapter 85 stays in
``electronics``.
"""

from __future__ import annotations

COMMODITY_FAMILIES: dict[str, dict] = {
    "fashion": {
        "label": "Apparel",
        "prefixes": ["61", "62"],
        "watch_codes": ["6101", "6104", "6201", "6204"],
        "keywords": [],
    },
    "electronics": {
        "label": "Electronics",
        "prefixes": ["84", "85"],
        "watch_codes": ["8471", "8542", "8517", "8528"],
        "keywords": [],
    },
    "crude_oil": {
        "label": "Crude oil",
        "prefixes": ["2709"],
        "watch_codes": ["2709"],
        "keywords": ["crude oil", "brent", "wti", "opec", "oil tanker", "oil price", "strait of hormuz"],
    },
    "diesel": {
        "label": "Diesel and refined fuels",
        "prefixes": ["2710"],
        "watch_codes": ["2710"],
        "keywords": ["diesel", "gasoil", "refinery", "refined fuel", "fuel shortage", "jet fuel"],
    },
    "fertiliser": {
        "label": "Fertiliser",
        "prefixes": ["31"],
        "watch_codes": ["3102", "3104", "3105"],
        "keywords": ["fertiliser", "fertilizer", "urea", "potash", "ammonia", "phosphate"],
    },
    "rare_earths": {
        "label": "Rare earths and magnets",
        "prefixes": ["2805", "2846", "8505"],
        "watch_codes": ["2805", "2846", "8505"],
        "keywords": ["rare earth", "rare-earth", "neodymium", "dysprosium", "praseodymium",
                     "permanent magnet"],
    },
}

# Families shipped as liquid or dry bulk: no air lane is modelled for them.
BULK_FAMILIES = {"crude_oil", "diesel", "fertiliser"}


def family_of(hs_code: str) -> str | None:
    """The family an HS code belongs to, by longest matching prefix."""
    code = str(hs_code).strip()
    best, best_len = None, 0
    for name, family in COMMODITY_FAMILIES.items():
        for prefix in family["prefixes"]:
            if code.startswith(prefix) and len(prefix) > best_len:
                best, best_len = name, len(prefix)
    return best


def families_of(hs_codes: list[str] | None) -> set[str]:
    return {f for f in (family_of(c) for c in hs_codes or []) if f}


def is_bulk(hs_codes: list[str] | None) -> bool:
    families = families_of(hs_codes)
    return bool(families) and families <= BULK_FAMILIES


def watch_codes() -> list[str]:
    """Every HS code ingestion should poll, in table order."""
    return [code for family in COMMODITY_FAMILIES.values() for code in family["watch_codes"]]


def tag_text(text: str) -> list[str]:
    """HS codes for every family whose keywords appear in ``text``."""
    lower = text.lower()
    codes: list[str] = []
    for family in COMMODITY_FAMILIES.values():
        if any(k in lower for k in family["keywords"]):
            codes.extend(family["watch_codes"])
    return codes
