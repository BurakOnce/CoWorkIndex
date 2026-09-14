"""score_snapshots table

Revision ID: 0002_score_snapshots
Revises: 0001_base_tables
Create Date: 2026-01-02 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_score_snapshots"
down_revision: Union[str, None] = "0001_base_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UTC_NOW = sa.text("GETUTCDATE()")

archetype_enum = sa.Enum(
    "kopyala_yapistirci",
    "diyalog_ortagi",
    "supheci",
    "emir_verici",
    "pasif_kullanici",
    name="archetype_enum",
)


def upgrade() -> None:
    op.create_table(
        "score_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "employee_id",
            sa.Integer(),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("usage_score", sa.Float(), nullable=False),
        sa.Column("approval_score", sa.Float(), nullable=False),
        sa.Column("dialogue_score", sa.Float(), nullable=False),
        sa.Column("tone_score", sa.Float(), nullable=False),
        sa.Column("outcome_score", sa.Float(), nullable=False),
        sa.Column("critical_thinking_score", sa.Float(), nullable=False),
        sa.Column("composite_score", sa.Float(), nullable=False),
        sa.Column("archetype", archetype_enum, nullable=False),
        sa.Column("computed_at", sa.DateTime(), server_default=UTC_NOW),
        sa.UniqueConstraint("employee_id", "period_start", "period_end", name="uq_employee_period"),
    )
    op.create_index("ix_score_snapshots_employee_id", "score_snapshots", ["employee_id"])


def downgrade() -> None:
    op.drop_index("ix_score_snapshots_employee_id", table_name="score_snapshots")
    op.drop_table("score_snapshots")
