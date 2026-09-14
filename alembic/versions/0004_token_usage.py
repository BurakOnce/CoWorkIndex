"""interaction_events: input_tokens, output_tokens

Revision ID: 0004_token_usage
Revises: 0003_quality_check_runs
Create Date: 2026-01-04 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_token_usage"
down_revision: Union[str, None] = "0003_quality_check_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "interaction_events",
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "interaction_events",
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_input_tokens_nonneg", "interaction_events", "input_tokens >= 0"
    )
    op.create_check_constraint(
        "ck_output_tokens_nonneg", "interaction_events", "output_tokens >= 0"
    )


def downgrade() -> None:
    op.drop_constraint("ck_output_tokens_nonneg", "interaction_events", type_="check")
    op.drop_constraint("ck_input_tokens_nonneg", "interaction_events", type_="check")
    op.drop_column("interaction_events", "output_tokens")
    op.drop_column("interaction_events", "input_tokens")
