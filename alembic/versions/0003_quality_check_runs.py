"""quality_check_runs table

Revision ID: 0003_quality_check_runs
Revises: 0002_score_snapshots
Create Date: 2026-01-03 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_quality_check_runs"
down_revision: Union[str, None] = "0002_score_snapshots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UTC_NOW = sa.text("GETUTCDATE()")

quality_check_status_enum = sa.Enum(
    "passed", "warning", "failed", name="quality_check_status_enum"
)


def upgrade() -> None:
    op.create_table(
        "quality_check_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_at", sa.DateTime(), server_default=UTC_NOW),
        sa.Column("check_name", sa.String(length=120), nullable=False),
        sa.Column("status", quality_check_status_enum, nullable=False),
        sa.Column("affected_row_count", sa.Integer(), nullable=False, server_default="0"),
        # UnicodeText (-> NVARCHAR(max)): mesajlar Türkçe içerir (örn. "eşiğini aştı").
        sa.Column("details", sa.UnicodeText(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("quality_check_runs")
