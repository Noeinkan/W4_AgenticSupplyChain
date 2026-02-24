"""
Pre-built scenario templates for common supply-chain shocks.
Each scenario is a dict consumed by monte_carlo.run_monte_carlo().

Keys:
  id, name, event_type
  tariff_shock:   {country, rate_range}          – additional cost % on routes through country
  weather_impact: {region, delay_multiplier_range}
  demand_shock:   {change_range}                  – fractional demand change e.g. [-0.3, 0.15]
  port_closure_probability: float 0–1
  capacity_reduction: {country, range}            – fractional capacity cut on suppliers
"""

SCENARIO_TEMPLATES: dict[str, dict] = {
    "china_tariff_25pct": {
        "id": "china_tariff_25pct",
        "name": "US-China 25% Tariff Shock",
        "event_type": "tariff",
        "tariff_shock": {"country": "CN", "rate_range": [0.20, 0.30]},
        "weather_impact": {"region": "CN", "delay_multiplier_range": [1.0, 1.1]},
        "demand_shock": {"change_range": [-0.10, 0.05]},
        "port_closure_probability": 0.02,
        "capacity_reduction": {"country": "CN", "range": [0.0, 0.15]},
    },
    "sea_typhoon_season": {
        "id": "sea_typhoon_season",
        "name": "SE Asia Typhoon Season",
        "event_type": "weather",
        "tariff_shock": {"country": "VN", "rate_range": [0.0, 0.0]},
        "weather_impact": {"region": "SEA", "delay_multiplier_range": [1.5, 4.0]},
        "demand_shock": {"change_range": [-0.05, 0.10]},
        "port_closure_probability": 0.25,
        "capacity_reduction": {"country": "VN", "range": [0.10, 0.50]},
    },
    "suez_canal_blockage": {
        "id": "suez_canal_blockage",
        "name": "Suez Canal Closure",
        "event_type": "geopolitical",
        "tariff_shock": {"country": "ALL", "rate_range": [0.0, 0.0]},
        "weather_impact": {"region": "ALL", "delay_multiplier_range": [2.0, 3.5]},
        "demand_shock": {"change_range": [0.0, 0.0]},
        "port_closure_probability": 0.80,
        "capacity_reduction": {"country": "ALL", "range": [0.0, 0.0]},
        "extra_transit_days": 14,  # Cape of Good Hope re-routing
    },
    "semiconductor_shortage": {
        "id": "semiconductor_shortage",
        "name": "Global Semiconductor Shortage",
        "event_type": "supply",
        "tariff_shock": {"country": "TW", "rate_range": [0.0, 0.05]},
        "weather_impact": {"region": "TW", "delay_multiplier_range": [1.0, 1.2]},
        "demand_shock": {"change_range": [0.10, 0.50]},  # demand surge
        "port_closure_probability": 0.03,
        "capacity_reduction": {"country": "TW", "range": [0.30, 0.70]},
    },
    "west_coast_port_strike": {
        "id": "west_coast_port_strike",
        "name": "West Coast Port Strike (US)",
        "event_type": "strike",
        "tariff_shock": {"country": "US", "rate_range": [0.0, 0.0]},
        "weather_impact": {"region": "US_WEST", "delay_multiplier_range": [1.5, 5.0]},
        "demand_shock": {"change_range": [-0.05, 0.05]},
        "port_closure_probability": 0.90,
        "capacity_reduction": {"country": "US", "range": [0.0, 0.0]},
        "duration_days_range": [7, 45],
    },
}


def select_relevant_scenarios(
    risk_scores: dict[str, float],
    active_events: list[dict],
) -> list[dict]:
    """
    Select scenario templates relevant to the current risk profile.

    Rules:
    - CN risk > 0.4  → include china_tariff_25pct
    - VN/TH/BD risk > 0.3 + weather events → sea_typhoon_season
    - geopolitical events with severity ≥ 4 → suez_canal_blockage
    - TW/KR risk > 0.3 or 'semiconductor' in events → semiconductor_shortage
    - US strike events → west_coast_port_strike

    Always returns at least 1 scenario.
    """
    selected: list[dict] = []
    event_types = {e.get("event_type", "") for e in active_events}
    event_descriptions = " ".join(
        e.get("description", "") + e.get("title", "") for e in active_events
    ).lower()

    cn_risk = max(risk_scores.get("CN", 0), risk_scores.get("HK", 0))
    sea_risk = max(risk_scores.get("VN", 0), risk_scores.get("TH", 0), risk_scores.get("BD", 0))
    tw_kr_risk = max(risk_scores.get("TW", 0), risk_scores.get("KR", 0))

    if cn_risk > 0.4 or "tariff" in event_types:
        selected.append(SCENARIO_TEMPLATES["china_tariff_25pct"])

    if sea_risk > 0.3 or "weather" in event_types:
        selected.append(SCENARIO_TEMPLATES["sea_typhoon_season"])

    if "geopolitical" in event_types or "suez" in event_descriptions or "blockade" in event_descriptions:
        selected.append(SCENARIO_TEMPLATES["suez_canal_blockage"])

    if tw_kr_risk > 0.3 or "semiconductor" in event_descriptions or "chip" in event_descriptions:
        selected.append(SCENARIO_TEMPLATES["semiconductor_shortage"])

    if "strike" in event_types or "port strike" in event_descriptions:
        selected.append(SCENARIO_TEMPLATES["west_coast_port_strike"])

    # Deduplicate by id
    seen: set[str] = set()
    unique = []
    for s in selected:
        if s["id"] not in seen:
            seen.add(s["id"])
            unique.append(s)

    # Always run at least 2 scenarios
    if len(unique) < 2:
        for key, template in SCENARIO_TEMPLATES.items():
            if template["id"] not in seen:
                unique.append(template)
                if len(unique) >= 2:
                    break

    return unique
