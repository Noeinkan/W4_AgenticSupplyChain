"""Initial schema with pgvector extension

Revision ID: 0001
Revises:
Create Date: 2026-02-23

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "suppliers",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("region", sa.Text()),
        sa.Column("tier", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("commodity_codes", sa.ARRAY(sa.Text())),
        sa.Column("lead_time_days", sa.SmallInteger()),
        sa.Column("capacity_units", sa.Integer()),
        sa.Column("unit_cost_usd", sa.Numeric(12, 4)),
        sa.Column("esg_score", sa.Numeric(5, 2)),
        sa.Column("certifications", sa.dialects.postgresql.JSONB()),
        sa.Column("latitude", sa.Float()),
        sa.Column("longitude", sa.Float()),
        sa.Column("active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "routes",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("origin_supplier_id", sa.String(), sa.ForeignKey("suppliers.id")),
        sa.Column("destination_port", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("carrier", sa.Text()),
        sa.Column("transit_days", sa.SmallInteger()),
        sa.Column("cost_per_unit", sa.Numeric(10, 4)),
        sa.Column("co2_kg_per_unit", sa.Numeric(8, 4)),
        sa.Column("reliability_pct", sa.Numeric(5, 2)),
        sa.Column("through_affected_country", sa.Boolean(), server_default="false"),
        sa.Column("active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("severity", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("affected_countries", sa.ARRAY(sa.Text())),
        sa.Column("affected_hs_codes", sa.ARRAY(sa.Text())),
        sa.Column("title", sa.Text()),
        sa.Column("description", sa.Text()),
        sa.Column("source_url", sa.Text()),
        sa.Column("raw_data", sa.dialects.postgresql.JSONB()),
        sa.Column("embedding", Vector(1536)),
        sa.Column("valid_from", sa.DateTime(timezone=True)),
        sa.Column("valid_to", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )

    # IVFFlat index for fast cosine similarity search on event embeddings
    op.execute(
        "CREATE INDEX events_embedding_idx ON events "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50)"
    )

    op.create_table(
        "scenarios",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("trigger_event_id", sa.String(), sa.ForeignKey("events.id")),
        sa.Column("parameters", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending"),
        sa.Column("run_count", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "simulation_runs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("scenario_id", sa.String(), sa.ForeignKey("scenarios.id")),
        sa.Column("iterations", sa.Integer(), server_default="1000"),
        sa.Column("cost_mean", sa.Numeric(14, 2)),
        sa.Column("cost_p5", sa.Numeric(14, 2)),
        sa.Column("cost_p95", sa.Numeric(14, 2)),
        sa.Column("delay_mean", sa.Numeric(6, 2)),
        sa.Column("risk_score_mean", sa.Numeric(5, 2)),
        sa.Column("esg_score_mean", sa.Numeric(5, 2)),
        sa.Column("pareto_front", sa.dialects.postgresql.JSONB()),
        sa.Column("best_config", sa.dialects.postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "recommendations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("scenario_id", sa.String(), sa.ForeignKey("scenarios.id")),
        sa.Column("thread_id", sa.Text()),
        sa.Column("rec_type", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("proposed_config", sa.dialects.postgresql.JSONB()),
        sa.Column("cost_delta_usd", sa.Numeric(12, 2)),
        sa.Column("risk_delta", sa.Numeric(5, 2)),
        sa.Column("esg_delta", sa.Numeric(5, 2)),
        sa.Column("confidence_pct", sa.Numeric(5, 2)),
        sa.Column("status", sa.Text(), server_default="pending"),
        sa.Column("approved_by", sa.Text()),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("approval_notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("recommendations")
    op.drop_table("simulation_runs")
    op.drop_table("scenarios")
    op.execute("DROP INDEX IF EXISTS events_embedding_idx")
    op.drop_table("events")
    op.drop_table("routes")
    op.drop_table("suppliers")
