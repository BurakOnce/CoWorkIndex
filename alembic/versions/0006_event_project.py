"""interaction_events.project -- proje bazlı filtreleme

Revision ID: 0006_event_project
Revises: 0005_connector_capture
Create Date: 2026-09-21 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006_event_project"
down_revision: Union[str, None] = "0005_connector_capture"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Proje adı (klasörün son parçası, örn. "CoWorkIndex") -- içerik değil,
    # bağlam meta verisi; skor/maliyet uçlarının ?project= filtresi bunu kullanır.
    op.add_column("interaction_events", sa.Column("project", sa.Unicode(200), nullable=True))
    op.create_index("ix_interaction_events_project", "interaction_events", ["project"])

    # Mevcut bağlayıcı event'leri için proje adını içerik tablosundaki tam
    # yoldan türet (klasörün son parçası).
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT event_id, project FROM interaction_contents WHERE project IS NOT NULL")
    ).fetchall()
    for event_id, path in rows:
        name = str(path).replace("\\", "/").rstrip("/").split("/")[-1].strip()[:200]
        if name:
            bind.execute(
                sa.text("UPDATE interaction_events SET project = :name WHERE id = :id"),
                {"name": name, "id": event_id},
            )


def downgrade() -> None:
    op.drop_index("ix_interaction_events_project", table_name="interaction_events")
    op.drop_column("interaction_events", "project")
