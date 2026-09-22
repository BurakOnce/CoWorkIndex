"""connectors: event source/external_id + optional interaction_contents capture

Revision ID: 0005_connector_capture
Revises: 0004_token_usage
Create Date: 2026-09-21 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_connector_capture"
down_revision: Union[str, None] = "0004_token_usage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("interaction_events", sa.Column("source", sa.String(40), nullable=True))
    op.add_column("interaction_events", sa.Column("external_id", sa.String(200), nullable=True))
    # Aynı kaynaktan gelen aynı etkileşim (örn. Claude Code'daki bir tur)
    # tekrar gönderildiğinde yeni satır değil, güncelleme olmalı (upsert).
    op.create_index(
        "uq_interaction_events_source_external_id",
        "interaction_events",
        ["source", "external_id"],
        unique=True,
        mssql_where=sa.text("external_id IS NOT NULL"),
    )

    # Opsiyonel içerik yakalama katmanı. interaction_events kasıtlı olarak
    # içerik taşımaz; bir bağlayıcı içerik yakalamayı açtığında ham metin
    # ve çıkarılan sinyallerin gerekçesi bu ayrı tabloya yazılır.
    op.create_table(
        "interaction_contents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "event_id",
            sa.Integer(),
            sa.ForeignKey("interaction_events.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("model", sa.String(120), nullable=True),
        sa.Column("project", sa.Unicode(400), nullable=True),
        sa.Column("prompt_text", sa.UnicodeText(), nullable=True),
        sa.Column("response_text", sa.UnicodeText(), nullable=True),
        sa.Column("feedback_text", sa.UnicodeText(), nullable=True),
        sa.Column("tool_calls_json", sa.UnicodeText(), nullable=True),
        sa.Column("usage_json", sa.UnicodeText(), nullable=True),
        sa.Column("signals_json", sa.UnicodeText(), nullable=True),
        sa.Column("classifier", sa.String(40), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("GETUTCDATE()")),
    )


def downgrade() -> None:
    op.drop_table("interaction_contents")
    op.drop_index("uq_interaction_events_source_external_id", table_name="interaction_events")
    op.drop_column("interaction_events", "external_id")
    op.drop_column("interaction_events", "source")
