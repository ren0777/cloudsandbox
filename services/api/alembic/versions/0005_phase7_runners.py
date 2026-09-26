"""Phase 7: multi-runner registry (per-runner secret, drain, engines, host stats, reachability)

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

COLUMNS = [
    sa.Column("secret_enc", sa.Text(), nullable=True),
    sa.Column("drain", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    sa.Column("engines", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("default_engine", sa.String(20), nullable=True),
    sa.Column("cpu_count", sa.Integer(), nullable=True),
    sa.Column("mem_total_mib", sa.Integer(), nullable=True),
    sa.Column("mem_available_mib", sa.Integer(), nullable=True),
    sa.Column("last_error", sa.String(300), nullable=True),
    sa.Column("unreachable_since", sa.DateTime(timezone=True), nullable=True),
    sa.Column("registered_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
]


def upgrade() -> None:
    for c in COLUMNS:
        op.add_column("runners", c)
    op.create_index("ix_sessions_runner_state", "lab_sessions", ["runner_id", "state"])


def downgrade() -> None:
    op.drop_index("ix_sessions_runner_state", "lab_sessions")
    for c in reversed(COLUMNS):
        op.drop_column("runners", c.name)
