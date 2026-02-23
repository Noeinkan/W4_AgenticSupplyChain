import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from orchestrator.db.engine import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Supplier(Base):
    """
    Tier-1 and tier-2 supplier master record.
    ESG scores and certifications are updated by the ESG calculator.
    """

    __tablename__ = "suppliers"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)  # ISO 3166-1 alpha-2
    region: Mapped[str | None] = mapped_column(Text)
    tier: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)  # 1=direct, 2=sub
    commodity_codes: Mapped[list[str] | None] = mapped_column(ARRAY(Text))  # HS codes
    lead_time_days: Mapped[int | None] = mapped_column(SmallInteger)
    capacity_units: Mapped[int | None] = mapped_column(Integer)
    unit_cost_usd: Mapped[float | None] = mapped_column(Numeric(12, 4))
    esg_score: Mapped[float | None] = mapped_column(Numeric(5, 2))  # 0-100
    certifications: Mapped[dict | None] = mapped_column(JSONB)  # {"ISO14001": True, ...}
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    routes: Mapped[list["Route"]] = relationship("Route", back_populates="supplier")


class Route(Base):
    """
    Shipping route from a supplier to a destination port.
    co2_kg_per_unit is used for ESG scoring.
    """

    __tablename__ = "routes"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    origin_supplier_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("suppliers.id")
    )
    destination_port: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(Text, nullable=False)  # sea | air | rail | road
    carrier: Mapped[str | None] = mapped_column(Text)
    transit_days: Mapped[int | None] = mapped_column(SmallInteger)
    cost_per_unit: Mapped[float | None] = mapped_column(Numeric(10, 4))
    co2_kg_per_unit: Mapped[float | None] = mapped_column(Numeric(8, 4))
    reliability_pct: Mapped[float | None] = mapped_column(Numeric(5, 2))  # historical on-time %
    through_affected_country: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    supplier: Mapped["Supplier"] = relationship("Supplier", back_populates="routes")


class Event(Base):
    """
    Disruption event ingested from news, climate, or trade APIs.
    embedding is a 1536-dim vector for pgvector semantic search.
    """

    __tablename__ = "events"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    event_type: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # tariff | weather | strike | geopolitical | news
    severity: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)  # 1-5
    affected_countries: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    affected_hs_codes: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    title: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    raw_data: Mapped[dict | None] = mapped_column(JSONB)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))  # pgvector
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Scenario(Base):
    """
    A simulation scenario, either from a template or auto-generated from events.
    """

    __tablename__ = "scenarios"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_event_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("events.id")
    )
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="pending")  # pending|running|complete|failed
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    simulation_runs: Mapped[list["SimulationRun"]] = relationship(
        "SimulationRun", back_populates="scenario"
    )
    recommendations: Mapped[list["Recommendation"]] = relationship(
        "Recommendation", back_populates="scenario"
    )


class SimulationRun(Base):
    """
    A single Monte Carlo run result — one record per iteration batch.
    Stores aggregate statistics, not individual iterations.
    """

    __tablename__ = "simulation_runs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    scenario_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("scenarios.id")
    )
    iterations: Mapped[int] = mapped_column(Integer, default=1000)
    cost_mean: Mapped[float | None] = mapped_column(Numeric(14, 2))
    cost_p5: Mapped[float | None] = mapped_column(Numeric(14, 2))
    cost_p95: Mapped[float | None] = mapped_column(Numeric(14, 2))
    delay_mean: Mapped[float | None] = mapped_column(Numeric(6, 2))
    risk_score_mean: Mapped[float | None] = mapped_column(Numeric(5, 2))
    esg_score_mean: Mapped[float | None] = mapped_column(Numeric(5, 2))
    pareto_front: Mapped[list | None] = mapped_column(JSONB)
    best_config: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    scenario: Mapped["Scenario"] = relationship("Scenario", back_populates="simulation_runs")


class Recommendation(Base):
    """
    Agent-generated recommendation awaiting or post human governance decision.
    status lifecycle: pending → approved | rejected → (if approved) executed
    """

    __tablename__ = "recommendations"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    scenario_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("scenarios.id")
    )
    thread_id: Mapped[str | None] = mapped_column(Text)  # LangGraph checkpoint thread
    rec_type: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # reroute | supplier_switch | inventory_adj
    description: Mapped[str | None] = mapped_column(Text)
    proposed_config: Mapped[dict | None] = mapped_column(JSONB)
    cost_delta_usd: Mapped[float | None] = mapped_column(Numeric(12, 2))
    risk_delta: Mapped[float | None] = mapped_column(Numeric(5, 2))
    esg_delta: Mapped[float | None] = mapped_column(Numeric(5, 2))
    confidence_pct: Mapped[float | None] = mapped_column(Numeric(5, 2))
    status: Mapped[str] = mapped_column(Text, default="pending")
    approved_by: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    scenario: Mapped["Scenario"] = relationship("Scenario", back_populates="recommendations")
