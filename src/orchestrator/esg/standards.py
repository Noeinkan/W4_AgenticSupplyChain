"""
ESG standard metric mappings and country-level reference data.

Sources:
  - World Bank WGI Control of Corruption (2023 estimate, percentile rank 0-100)
  - ILO labour standards composite (ratification + enforcement, 0-100)
  - CO2 benchmarks by transport mode (kg per unit per day of transit)
"""

# World Bank Worldwide Governance Indicators — Control of Corruption percentile rank 2023
COUNTRY_GOVERNANCE_SCORES: dict[str, float] = {
    "DE": 92.0, "JP": 88.0, "GB": 88.0, "SE": 96.0, "DK": 97.0,
    "US": 82.0, "AU": 88.0, "NL": 94.0, "CH": 96.0,
    "KR": 75.0, "MY": 60.0, "TH": 54.0, "TW": 80.0,
    "CN": 45.0, "VN": 42.0, "PH": 40.0,
    "IN": 52.0, "BD": 28.0, "PK": 25.0, "KH": 22.0, "ET": 30.0,
    "TR": 50.0, "MA": 53.0, "MX": 38.0, "BR": 45.0,
}

# ILO labour standards composite score (0–100)
COUNTRY_LABOUR_SCORES: dict[str, float] = {
    "DE": 90.0, "JP": 82.0, "GB": 85.0, "SE": 92.0, "DK": 93.0,
    "US": 75.0, "AU": 85.0,
    "KR": 72.0, "MY": 58.0, "TH": 54.0, "TW": 70.0,
    "CN": 40.0, "VN": 45.0, "PH": 48.0,
    "IN": 50.0, "BD": 35.0, "PK": 30.0, "KH": 32.0, "ET": 38.0,
    "TR": 52.0, "MA": 55.0, "MX": 48.0, "BR": 58.0,
}

# GRI disclosure → internal field mapping
GRI_METRICS: dict[str, str] = {
    "GRI-305-1": "scope1_co2_tonnes",
    "GRI-305-2": "scope2_co2_tonnes",
    "GRI-305-3": "supply_chain_co2_tonnes",        # Scope 3 — most relevant
    "GRI-308-1": "pct_suppliers_env_assessed",
    "GRI-414-1": "pct_suppliers_social_assessed",
    "GRI-204-1": "pct_spend_local_suppliers",
}

# SASB — Apparel, Accessories & Footwear (CG-AA) + Technology Hardware (TC-HW)
SASB_METRICS: dict[str, str] = {
    "CG-AA-430a.1": "pct_tier1_suppliers_social_audit",
    "CG-AA-430a.2": "pct_tier1_suppliers_env_audit",
    "CG-AA-440a.1": "water_withdrawn_high_stress_m3",
    "TC-HW-430a.1": "pct_suppliers_code_of_conduct",
    "TC-HW-430a.2": "pct_suppliers_audited_labour",
}

# Certification → ESG bonus points
CERTIFICATION_BONUSES: dict[str, dict[str, float]] = {
    "environmental": {
        "ISO14001": 10.0,
        "RE100": 15.0,      # 100% renewable energy pledge
        "SBTi": 10.0,       # Science-based targets
        "GOTS": 8.0,        # Global Organic Textile Standard
    },
    "social": {
        "SA8000": 20.0,     # Social Accountability International
        "WRAP": 15.0,       # Worldwide Responsible Accredited Production
        "GOTS": 5.0,
        "BSCI": 10.0,       # Business Social Compliance Initiative
    },
    "governance": {
        "ISO37001": 10.0,   # Anti-bribery management
        "ISO9001": 5.0,
    },
}
