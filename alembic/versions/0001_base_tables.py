"""base tables: teams, employees, tools, interaction_events

Revision ID: 0001_base_tables
Revises:
Create Date: 2026-01-01 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_base_tables"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UTC_NOW = sa.text("GETUTCDATE()")

action_type_enum = sa.Enum("accepted", "rejected", "edited", name="action_type_enum")
persuasion_direction_enum = sa.Enum(
    "ai_persuaded_user", "user_persuaded_ai", "none", name="persuasion_direction_enum"
)
outcome_status_enum = sa.Enum("production", "test_only", "abandoned", name="outcome_status_enum")
task_category_enum = sa.Enum("code", "writing", "analysis", "other", name="task_category_enum")


def upgrade() -> None:
    op.create_table(
        "teams",
        sa.Column("id", sa.Integer(), primary_key=True),
        # Unicode (-> NVARCHAR): Türkçe serbest metin (ş, ğ, ı, İ) VARCHAR'ın
        # varsayılan koleksiyonunda sessizce ASCII'ye indirgenip kaybolur.
        sa.Column("name", sa.Unicode(length=120), nullable=False, unique=True),
        sa.Column("department", sa.Unicode(length=120), nullable=False),
    )

    op.create_table(
        "employees",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("full_name", sa.Unicode(length=200), nullable=False),
        sa.Column(
            "team_id", sa.Integer(), sa.ForeignKey("teams.id", ondelete="NO ACTION"), nullable=False
        ),
        sa.Column("role", sa.Unicode(length=120), nullable=False),
        sa.Column("hire_date", sa.Date(), nullable=False),
    )

    op.create_table(
        "tools",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Unicode(length=80), nullable=False, unique=True),
    )

    op.create_table(
        "interaction_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "employee_id",
            sa.Integer(),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tool_id", sa.Integer(), sa.ForeignKey("tools.id", ondelete="NO ACTION"), nullable=False
        ),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("action_type", action_type_enum, nullable=False),
        sa.Column("dialogue_turn_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("had_disagreement", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "persuasion_direction",
            persuasion_direction_enum,
            nullable=False,
            server_default="none",
        ),
        sa.Column("directive_language_ratio", sa.Float(), nullable=False, server_default="0"),
        sa.Column("politeness_marker_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_sentence_length", sa.Float(), nullable=False, server_default="0"),
        sa.Column("exclamation_density", sa.Float(), nullable=False, server_default="0"),
        sa.Column("outcome_status", outcome_status_enum, nullable=False),
        sa.Column("critical_check_flag", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("task_category", task_category_enum, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=UTC_NOW),
        sa.CheckConstraint(
            "directive_language_ratio BETWEEN 0 AND 1", name="ck_directive_language_ratio_range"
        ),
        sa.CheckConstraint("dialogue_turn_count >= 0", name="ck_dialogue_turn_count_nonneg"),
        sa.CheckConstraint(
            "politeness_marker_count >= 0", name="ck_politeness_marker_count_nonneg"
        ),
        sa.CheckConstraint("avg_sentence_length >= 0", name="ck_avg_sentence_length_nonneg"),
        sa.CheckConstraint(
            "exclamation_density BETWEEN 0 AND 1", name="ck_exclamation_density_range"
        ),
    )
    op.create_index("ix_interaction_events_employee_id", "interaction_events", ["employee_id"])
    op.create_index("ix_interaction_events_occurred_at", "interaction_events", ["occurred_at"])
    op.create_index("ix_interaction_events_session_id", "interaction_events", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_interaction_events_session_id", table_name="interaction_events")
    op.drop_index("ix_interaction_events_occurred_at", table_name="interaction_events")
    op.drop_index("ix_interaction_events_employee_id", table_name="interaction_events")
    op.drop_table("interaction_events")
    op.drop_table("tools")
    op.drop_table("employees")
    op.drop_table("teams")
