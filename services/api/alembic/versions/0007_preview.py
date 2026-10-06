"""Phase 9: interactive preview sandbox for authored labs.

`lab_drafts.last_preview` stores the current preview (sandbox id, engine, endpoints, encrypted terminal
credential, timestamps). `terminal_tickets` can now target a draft preview instead of a session, so the
browser terminal reuses the same ticket + WebSocket machinery.

Revision ID: 0007
Revises: 0006
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lab_drafts", sa.Column("last_preview", postgresql.JSONB(), nullable=True))
    op.alter_column("terminal_tickets", "session_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)
    op.add_column("terminal_tickets", sa.Column("draft_id", postgresql.UUID(as_uuid=True),
                                                sa.ForeignKey("lab_drafts.id", ondelete="CASCADE"), nullable=True))
    op.create_index("ix_terminal_tickets_draft_id", "terminal_tickets", ["draft_id"])


def downgrade() -> None:
    op.drop_index("ix_terminal_tickets_draft_id", "terminal_tickets")
    op.drop_column("terminal_tickets", "draft_id")
    op.execute("DELETE FROM terminal_tickets WHERE session_id IS NULL")
    op.alter_column("terminal_tickets", "session_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
    op.drop_column("lab_drafts", "last_preview")
