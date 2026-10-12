"""Milestone 50: the sandbox's API-audit proxy.

`lab_sessions.audit_endpoint` is where the console sends a session's AWS calls (through the proxy, so they are
recorded as console calls) and where the grader reads the audit log. NULL for labs without `audit.*` checks.

Revision ID: 0008
Revises: 0007
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lab_sessions", sa.Column("audit_endpoint", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("lab_sessions", "audit_endpoint")
