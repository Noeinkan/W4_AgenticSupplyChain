"""
The supplier / route / event catalog.

This is the single source of truth for reference data. It works in two modes:

  * **memory** (default) - data is generated in-process from the definitions
    below. No Postgres, no docker, no API keys. This is what makes ``npm start``
    work on a clean machine.
  * **db** - the same shapes are read from Postgres via the repositories, used
    when ``DATA_BACKEND=db`` and the database is reachable.

IDs are deterministic UUIDv5 values derived from the entity name, so a supplier
keeps the same ID across restarts and between the two backends. The dashboard
can therefore deep-link to a supplier without a database.

``scripts/seed_data.py`` imports from here, so the seeded database and the
in-memory catalog never drift apart.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)

_NS = uuid.UUID("6f3a1d2e-9c14-4b7a-8f2d-5e1c0a7b3d99")


def stable_id(kind: str, name: str) -> str:
    """Deterministic UUID for an entity, stable across processes and backends."""
    return str(uuid.uuid5(_NS, f"{kind}:{name}"))


SUPPLIER_DEFS: list[dict] = [
    # Fashion
    {
        "name": "Apex Garments Ltd", "country_code": "BD", "region": "Dhaka", "tier": 1,
        "commodity_codes": ["6101", "6104", "6201", "6204"], "lead_time_days": 45,
        "capacity_units": 500_000, "unit_cost_usd": 12.50, "esg_score": 62.0,
        "certifications": {"SA8000": True, "WRAP": True, "ISO14001": False},
        "latitude": 23.81, "longitude": 90.41,
    },
    {
        "name": "Vinatex Fashion", "country_code": "VN", "region": "Ho Chi Minh City", "tier": 1,
        "commodity_codes": ["6101", "6104", "6204"], "lead_time_days": 35,
        "capacity_units": 400_000, "unit_cost_usd": 14.20, "esg_score": 68.0,
        "certifications": {"SA8000": True, "GOTS": False, "ISO14001": True},
        "latitude": 10.82, "longitude": 106.63,
    },
    {
        "name": "Bossa Tekstil", "country_code": "TR", "region": "Adana", "tier": 1,
        "commodity_codes": ["6101", "6201", "6204"], "lead_time_days": 20,
        "capacity_units": 250_000, "unit_cost_usd": 18.80, "esg_score": 74.0,
        "certifications": {"SA8000": True, "ISO14001": True, "GOTS": True},
        "latitude": 37.00, "longitude": 35.32,
    },
    {
        "name": "Arvind Mills", "country_code": "IN", "region": "Ahmedabad", "tier": 1,
        "commodity_codes": ["6201", "6204", "6101"], "lead_time_days": 38,
        "capacity_units": 600_000, "unit_cost_usd": 11.90, "esg_score": 65.0,
        "certifications": {"SA8000": False, "ISO14001": True, "WRAP": True},
        "latitude": 23.02, "longitude": 72.57,
    },
    {
        "name": "Phnom Penh Apparel", "country_code": "KH", "region": "Phnom Penh", "tier": 2,
        "commodity_codes": ["6101", "6104"], "lead_time_days": 50,
        "capacity_units": 200_000, "unit_cost_usd": 10.50, "esg_score": 55.0,
        "certifications": {"SA8000": False, "WRAP": False},
        "latitude": 11.56, "longitude": 104.92,
    },
    # Electronics
    {
        "name": "TSMC Supply Partners", "country_code": "TW", "region": "Hsinchu", "tier": 1,
        "commodity_codes": ["8542", "8471", "8517"], "lead_time_days": 90,
        "capacity_units": 100_000, "unit_cost_usd": 320.00, "esg_score": 82.0,
        "certifications": {"ISO14001": True, "SA8000": True, "SBTi": True},
        "latitude": 24.80, "longitude": 120.97,
    },
    {
        "name": "Samsung Electronics Components", "country_code": "KR", "region": "Suwon", "tier": 1,
        "commodity_codes": ["8542", "8528", "8517"], "lead_time_days": 60,
        "capacity_units": 150_000, "unit_cost_usd": 280.00, "esg_score": 79.0,
        "certifications": {"ISO14001": True, "SA8000": True, "RE100": True},
        "latitude": 37.27, "longitude": 127.01,
    },
    {
        "name": "Inari Amertron", "country_code": "MY", "region": "Penang", "tier": 1,
        "commodity_codes": ["8542", "8471"], "lead_time_days": 45,
        "capacity_units": 80_000, "unit_cost_usd": 95.00, "esg_score": 71.0,
        "certifications": {"ISO14001": True, "SA8000": False},
        "latitude": 5.41, "longitude": 100.33,
    },
    {
        "name": "Delta Electronics Thailand", "country_code": "TH", "region": "Bangkok", "tier": 1,
        "commodity_codes": ["8471", "8528", "8517"], "lead_time_days": 40,
        "capacity_units": 120_000, "unit_cost_usd": 88.00, "esg_score": 75.0,
        "certifications": {"ISO14001": True, "SA8000": True, "ISO37001": True},
        "latitude": 13.76, "longitude": 100.50,
    },
    {
        "name": "Murata Manufacturing", "country_code": "JP", "region": "Kyoto", "tier": 2,
        "commodity_codes": ["8542", "8471"], "lead_time_days": 55,
        "capacity_units": 60_000, "unit_cost_usd": 450.00, "esg_score": 88.0,
        "certifications": {"ISO14001": True, "SA8000": True, "RE100": True, "SBTi": True},
        "latitude": 35.01, "longitude": 135.76,
    },
    # Backup / alternative sources
    {
        "name": "Ethiopian Garment Manufacturers", "country_code": "ET", "region": "Addis Ababa",
        "tier": 2, "commodity_codes": ["6101", "6104"], "lead_time_days": 55,
        "capacity_units": 100_000, "unit_cost_usd": 9.80, "esg_score": 50.0,
        "certifications": {}, "latitude": 9.03, "longitude": 38.74,
    },
    {
        "name": "Morocco Textile Hub", "country_code": "MA", "region": "Casablanca", "tier": 1,
        "commodity_codes": ["6101", "6201", "6204"], "lead_time_days": 18,
        "capacity_units": 180_000, "unit_cost_usd": 16.50, "esg_score": 70.0,
        "certifications": {"SA8000": True, "ISO14001": True},
        "latitude": 33.59, "longitude": -7.62,
    },
]

BASE_TRANSIT_DAYS: dict[str, int] = {
    "BD": 28, "VN": 25, "TR": 14, "IN": 22, "KH": 30,
    "TW": 18, "KR": 20, "MY": 22, "TH": 24, "JP": 18,
    "ET": 35, "MA": 12,
}

# Lanes that transit chokepoints exposed to the modelled disruptions.
_CHOKEPOINT_COUNTRIES = {"TW", "VN", "KH", "TH", "MY"}
_SUEZ_COUNTRIES = {"IN", "BD", "VN", "TH", "MY", "KH"}


def build_routes(supplier: dict, supplier_id: str) -> list[dict]:
    """Three lanes per supplier: sea to LA, air to LA, sea to Rotterdam."""
    cc = supplier["country_code"]
    base_days = BASE_TRANSIT_DAYS.get(cc, 25)
    unit = supplier["unit_cost_usd"]
    exposed = cc in _CHOKEPOINT_COUNTRIES

    return [
        {
            "id": stable_id("route", f"{supplier['name']}|sea|LAX"),
            "origin_supplier_id": supplier_id,
            "destination_port": "Port of Los Angeles",
            "mode": "sea", "carrier": "Maersk",
            "transit_days": base_days,
            "cost_per_unit": round(unit * 0.08, 2),
            "co2_kg_per_unit": round(base_days * 0.05, 2),
            "reliability_pct": 87.0,
            "through_affected_country": exposed,
            "active": True,
        },
        {
            "id": stable_id("route", f"{supplier['name']}|air|LAX"),
            "origin_supplier_id": supplier_id,
            "destination_port": "LAX Air Freight",
            "mode": "air", "carrier": "FedEx Air",
            "transit_days": max(2, base_days // 10),
            "cost_per_unit": round(unit * 0.65, 2),
            "co2_kg_per_unit": round(base_days * 0.55, 2),
            "reliability_pct": 97.0,
            "through_affected_country": False,
            "active": True,
        },
        {
            "id": stable_id("route", f"{supplier['name']}|sea|RTM"),
            "origin_supplier_id": supplier_id,
            "destination_port": "Port of Rotterdam",
            "mode": "sea", "carrier": "MSC",
            "transit_days": int(base_days * 1.15),
            "cost_per_unit": round(unit * 0.075, 2),
            "co2_kg_per_unit": round(base_days * 0.048, 2),
            "reliability_pct": 89.0,
            "through_affected_country": cc in _SUEZ_COUNTRIES,
            "active": True,
        },
    ]


def _sample_events() -> list[dict]:
    """Illustrative live-feed events, timestamped relative to now."""
    now = datetime.now(UTC)
    raw = [
        ("tariff", 5, ["CN", "VN"], "US raises Section 301 tariffs on textile imports",
         "Additional 25% duty announced on apparel HS 6101-6204 originating in or transhipped through affected ports.", 6),
        ("weather", 4, ["VN", "TH", "KH"], "Typhoon Halong tracking toward Gulf of Tonkin",
         "Regional met office forecasts sustained 140 km/h winds; Haiphong and Cat Lai expected to suspend operations 48-72h.", 14),
        ("geopolitical", 5, ["EG", "IN", "BD"], "Red Sea transits down 61% year on year",
         "Carriers continue routing via Cape of Good Hope, adding roughly 14 days and materially raising bunker cost per TEU.", 30),
        ("strike", 3, ["US"], "ILWU local ballots on West Coast work stoppage",
         "Union leadership signals a strike authorisation vote covering Los Angeles and Long Beach terminals.", 52),
        ("supply", 4, ["TW", "KR"], "Advanced node capacity fully booked through Q3",
         "Foundry allocation tightening for 8542 components; lead times quoted at 90+ days for new orders.", 20),
        ("news", 2, ["BD"], "Dhaka minimum wage review reopens",
         "Tripartite board reconvenes on garment sector wage floor; industry expects a mid-single-digit percentage uplift.", 40),
    ]
    return [
        {
            "id": stable_id("event", title),
            "event_type": etype,
            "severity": sev,
            "affected_countries": countries,
            "affected_hs_codes": [],
            "title": title,
            "description": desc,
            "source_url": None,
            "valid_from": (now - timedelta(hours=hours)).isoformat(),
            "valid_to": None,
            "created_at": (now - timedelta(hours=hours)).isoformat(),
        }
        for etype, sev, countries, title, desc, hours in raw
    ]


class Catalog:
    """Suppliers, routes and events, from memory or from Postgres."""

    def __init__(self, suppliers: list[dict], routes: list[dict], events: list[dict], backend: str):
        self.suppliers = suppliers
        self.routes = routes
        self.events = events
        self.backend = backend
        self._by_id = {s["id"]: s for s in suppliers}

    # -- construction ---------------------------------------------------------

    @classmethod
    def in_memory(cls) -> "Catalog":
        suppliers, routes = [], []
        for definition in SUPPLIER_DEFS:
            sid = stable_id("supplier", definition["name"])
            suppliers.append({"id": sid, "active": True, **definition})
            routes.extend(build_routes(definition, sid))
        return cls(suppliers, routes, _sample_events(), backend="memory")

    @classmethod
    async def from_db(cls) -> "Catalog":
        """Read the catalog from Postgres. Raises if the DB is unreachable."""
        from orchestrator.db.engine import AsyncSessionLocal
        from orchestrator.db.repositories.route_repo import get_all_active
        from orchestrator.db.repositories.supplier_repo import get_all_active as get_suppliers

        async with AsyncSessionLocal() as db:
            db_suppliers = await get_suppliers(db)
            db_routes = await get_all_active(db)

        suppliers = [
            {
                "id": s.id, "name": s.name, "country_code": s.country_code, "region": s.region,
                "tier": s.tier, "commodity_codes": s.commodity_codes or [],
                "lead_time_days": s.lead_time_days, "capacity_units": s.capacity_units,
                "unit_cost_usd": float(s.unit_cost_usd or 0), "esg_score": float(s.esg_score or 50),
                "certifications": s.certifications or {},
                "latitude": s.latitude, "longitude": s.longitude, "active": s.active,
            }
            for s in db_suppliers
        ]
        routes = [
            {
                "id": r.id, "origin_supplier_id": r.origin_supplier_id,
                "destination_port": r.destination_port, "mode": r.mode, "carrier": r.carrier,
                "transit_days": r.transit_days, "cost_per_unit": float(r.cost_per_unit or 0),
                "co2_kg_per_unit": float(r.co2_kg_per_unit or 1),
                "reliability_pct": float(r.reliability_pct or 85),
                "through_affected_country": r.through_affected_country, "active": r.active,
            }
            for r in db_routes
        ]
        return cls(suppliers, routes, _sample_events(), backend="db")

    # -- queries --------------------------------------------------------------

    def supplier(self, supplier_id: str) -> dict | None:
        return self._by_id.get(supplier_id)

    def routes_for(self, supplier_id: str) -> list[dict]:
        return [r for r in self.routes if r.get("origin_supplier_id") == supplier_id]

    def countries(self) -> list[str]:
        return sorted({s["country_code"] for s in self.suppliers})

    def for_profile(self, countries: list[str] | None, hs_codes: list[str] | None) -> list[dict]:
        """Suppliers matching a manufacturer profile, falling back to all."""
        pool = [s for s in self.suppliers if s.get("active", True)]
        if countries:
            wanted = {c.upper() for c in countries}
            filtered = [s for s in pool if s["country_code"] in wanted]
            if filtered:
                pool = filtered
        if hs_codes:
            prefixes = tuple(hs_codes)
            filtered = [
                s for s in pool
                if any(code.startswith(prefixes) for code in (s.get("commodity_codes") or []))
            ]
            if filtered:
                pool = filtered
        return pool


_catalog: Catalog | None = None


async def get_catalog(refresh: bool = False) -> Catalog:
    """Process-wide catalog. Falls back to memory whenever the DB is unavailable."""
    global _catalog
    if _catalog is not None and not refresh:
        return _catalog

    from orchestrator.config import settings

    if settings.data_backend == "db":
        try:
            _catalog = await Catalog.from_db()
            logger.info("Catalog loaded from Postgres: %d suppliers", len(_catalog.suppliers))
            return _catalog
        except Exception as exc:
            logger.warning("Catalog DB load failed (%s) - using in-memory catalog", exc)

    _catalog = Catalog.in_memory()
    logger.info("Catalog loaded in memory: %d suppliers", len(_catalog.suppliers))
    return _catalog
