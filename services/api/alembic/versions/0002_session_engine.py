"""lab_sessions.engine — the emulator engine a session runs on

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lab_sessions", sa.Column("engine", sa.String(length=20), nullable=False, server_default="moto"))


def downgrade() -> None:
    op.drop_column("lab_sessions", "engine")
