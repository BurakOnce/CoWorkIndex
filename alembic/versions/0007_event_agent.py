"""interaction_events.model / .effort -- hangi AI ajanı/düşünme bütçesi

Revision ID: 0007_event_agent
Revises: 0006_event_project
Create Date: 2026-09-23 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007_event_agent"
down_revision: Union[str, None] = "0006_event_project"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Etkileşimi işleyen AI modeli (örn. "claude-sonnet-5") ve düşünme
    # bütçesi (low/medium/high) -- davranışsal bağlam, içerik değil; bu
    # yüzden capture_content kapalıyken de tutulur.
    op.add_column("interaction_events", sa.Column("model", sa.String(120), nullable=True))
    op.add_column("interaction_events", sa.Column("effort", sa.String(20), nullable=True))

    # Mevcut bağlayıcı event'leri için modeli içerik tablosundan taşı.
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT event_id, model FROM interaction_contents WHERE model IS NOT NULL")
    ).fetchall()
    for event_id, model in rows:
        bind.execute(
            sa.text("UPDATE interaction_events SET model = :model WHERE id = :id"),
            {"model": model, "id": event_id},
        )


def downgrade() -> None:
    op.drop_column("interaction_events", "effort")
    op.drop_column("interaction_events", "model")
