"""
Seed script: populate suppliers + routes with realistic mock data.
Fashion: Bangladesh, Vietnam, Turkey, India, Cambodia
Electronics: Taiwan, South Korea, Malaysia, Thailand, Japan

Run:
    PYTHONPATH=src python scripts/seed_data.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from orchestrator.db.engine import AsyncSessionLocal, engine, Base
from orchestrator.db.models import Route, Supplier


SUPPLIERS = [
    # --- Fashion ---
    {
        "name": "Apex Garments Ltd",
        "country_code": "BD",
        "region": "Dhaka",
        "tier": 1,
        "commodity_codes": ["6101", "6104", "6201", "6204"],
        "lead_time_days": 45,
        "capacity_units": 500_000,
        "unit_cost_usd": 12.50,
        "esg_score": 62.0,
        "certifications": {"SA8000": True, "WRAP": True, "ISO14001": False},
        "latitude": 23.81, "longitude": 90.41,
    },
    {
        "name": "Vinatex Fashion",
        "country_code": "VN",
        "region": "Ho Chi Minh City",
        "tier": 1,
        "commodity_codes": ["6101", "6104", "6204"],
        "lead_time_days": 35,
        "capacity_units": 400_000,
        "unit_cost_usd": 14.20,
        "esg_score": 68.0,
        "certifications": {"SA8000": True, "GOTS": False, "ISO14001": True},
        "latitude": 10.82, "longitude": 106.63,
    },
    {
        "name": "Bossa Tekstil",
        "country_code": "TR",
        "region": "Adana",
        "tier": 1,
        "commodity_codes": ["6101", "6201", "6204"],
        "lead_time_days": 20,
        "capacity_units": 250_000,
        "unit_cost_usd": 18.80,
        "esg_score": 74.0,
        "certifications": {"SA8000": True, "ISO14001": True, "GOTS": True},
        "latitude": 37.00, "longitude": 35.32,
    },
    {
        "name": "Arvind Mills",
        "country_code": "IN",
        "region": "Ahmedabad",
        "tier": 1,
        "commodity_codes": ["6201", "6204", "6101"],
        "lead_time_days": 38,
        "capacity_units": 600_000,
        "unit_cost_usd": 11.90,
        "esg_score": 65.0,
        "certifications": {"SA8000": False, "ISO14001": True, "WRAP": True},
        "latitude": 23.02, "longitude": 72.57,
    },
    {
        "name": "Phnom Penh Apparel",
        "country_code": "KH",
        "region": "Phnom Penh",
        "tier": 2,
        "commodity_codes": ["6101", "6104"],
        "lead_time_days": 50,
        "capacity_units": 200_000,
        "unit_cost_usd": 10.50,
        "esg_score": 55.0,
        "certifications": {"SA8000": False, "WRAP": False},
        "latitude": 11.56, "longitude": 104.92,
    },
    # --- Electronics ---
    {
        "name": "TSMC Supply Partners",
        "country_code": "TW",
        "region": "Hsinchu",
        "tier": 1,
        "commodity_codes": ["8542", "8471", "8517"],
        "lead_time_days": 90,
        "capacity_units": 100_000,
        "unit_cost_usd": 320.00,
        "esg_score": 82.0,
        "certifications": {"ISO14001": True, "SA8000": True, "SBTi": True},
        "latitude": 24.80, "longitude": 120.97,
    },
    {
        "name": "Samsung Electronics Components",
        "country_code": "KR",
        "region": "Suwon",
        "tier": 1,
        "commodity_codes": ["8542", "8528", "8517"],
        "lead_time_days": 60,
        "capacity_units": 150_000,
        "unit_cost_usd": 280.00,
        "esg_score": 79.0,
        "certifications": {"ISO14001": True, "SA8000": True, "RE100": True},
        "latitude": 37.27, "longitude": 127.01,
    },
    {
        "name": "Inari Amertron",
        "country_code": "MY",
        "region": "Penang",
        "tier": 1,
        "commodity_codes": ["8542", "8471"],
        "lead_time_days": 45,
        "capacity_units": 80_000,
        "unit_cost_usd": 95.00,
        "esg_score": 71.0,
        "certifications": {"ISO14001": True, "SA8000": False},
        "latitude": 5.41, "longitude": 100.33,
    },
    {
        "name": "Delta Electronics Thailand",
        "country_code": "TH",
        "region": "Bangkok",
        "tier": 1,
        "commodity_codes": ["8471", "8528", "8517"],
        "lead_time_days": 40,
        "capacity_units": 120_000,
        "unit_cost_usd": 88.00,
        "esg_score": 75.0,
        "certifications": {"ISO14001": True, "SA8000": True, "ISO37001": True},
        "latitude": 13.76, "longitude": 100.50,
    },
    {
        "name": "Murata Manufacturing",
        "country_code": "JP",
        "region": "Kyoto",
        "tier": 2,
        "commodity_codes": ["8542", "8471"],
        "lead_time_days": 55,
        "capacity_units": 60_000,
        "unit_cost_usd": 450.00,
        "esg_score": 88.0,
        "certifications": {"ISO14001": True, "SA8000": True, "RE100": True, "SBTi": True},
        "latitude": 35.01, "longitude": 135.76,
    },
    # --- Backup / alternative suppliers ---
    {
        "name": "Ethiopian Garment Manufacturers",
        "country_code": "ET",
        "region": "Addis Ababa",
        "tier": 2,
        "commodity_codes": ["6101", "6104"],
        "lead_time_days": 55,
        "capacity_units": 100_000,
        "unit_cost_usd": 9.80,
        "esg_score": 50.0,
        "certifications": {},
        "latitude": 9.03, "longitude": 38.74,
    },
    {
        "name": "Morocco Textile Hub",
        "country_code": "MA",
        "region": "Casablanca",
        "tier": 1,
        "commodity_codes": ["6101", "6201", "6204"],
        "lead_time_days": 18,
        "capacity_units": 180_000,
        "unit_cost_usd": 16.50,
        "esg_score": 70.0,
        "certifications": {"SA8000": True, "ISO14001": True},
        "latitude": 33.59, "longitude": -7.62,
    },
]


# Routes: each supplier gets a primary sea route + optional air route
ROUTES_TEMPLATE = [
    # (mode, dest_port, transit_days_factor, cost_factor, co2_factor, reliability_pct)
    ("sea", "Port of Los Angeles", 1.0, 1.0, 1.0, 87.0),
    ("air", "LAX Air Freight", 0.1, 8.0, 12.0, 98.0),
    ("sea", "Port of Rotterdam", 0.9, 0.9, 0.9, 89.0),
]


async def seed():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        # Check if already seeded
        from sqlalchemy import select, func
        result = await db.execute(select(func.count()).select_from(Supplier))
        if result.scalar() > 0:
            print("Database already seeded — skipping.")
            return

        supplier_ids: dict[str, str] = {}

        for s_data in SUPPLIERS:
            supplier = Supplier(**s_data)
            db.add(supplier)
            await db.flush()  # get the ID
            supplier_ids[s_data["name"]] = supplier.id
            print(f"  Added supplier: {s_data['name']} ({s_data['country_code']})")

        # Create routes for each supplier
        base_transit: dict[str, int] = {
            "BD": 28, "VN": 25, "TR": 14, "IN": 22, "KH": 30,
            "TW": 18, "KR": 20, "MY": 22, "TH": 24, "JP": 18,
            "ET": 35, "MA": 12,
        }

        for s_data in SUPPLIERS:
            sid = supplier_ids[s_data["name"]]
            base_days = base_transit.get(s_data["country_code"], 25)
            is_cn_route = s_data["country_code"] in ("CN", "TW")

            # Sea route to LA
            route_sea = Route(
                origin_supplier_id=sid,
                destination_port="Port of Los Angeles",
                mode="sea",
                carrier="Maersk",
                transit_days=base_days,
                cost_per_unit=round(s_data["unit_cost_usd"] * 0.08, 2),
                co2_kg_per_unit=round(base_days * 0.05, 2),
                reliability_pct=87.0,
                through_affected_country=is_cn_route,
                active=True,
            )
            db.add(route_sea)

            # Air route to LA (premium)
            route_air = Route(
                origin_supplier_id=sid,
                destination_port="LAX Air Freight",
                mode="air",
                carrier="FedEx Air",
                transit_days=max(2, base_days // 10),
                cost_per_unit=round(s_data["unit_cost_usd"] * 0.65, 2),
                co2_kg_per_unit=round(base_days * 0.55, 2),
                reliability_pct=97.0,
                through_affected_country=False,
                active=True,
            )
            db.add(route_air)

        await db.commit()
        print(f"\nSeeded {len(SUPPLIERS)} suppliers and {len(SUPPLIERS) * 2} routes.")


if __name__ == "__main__":
    asyncio.run(seed())
