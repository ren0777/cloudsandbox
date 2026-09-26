"""Phase 5: audit_events (append-only), users.must_change_password, lab_sessions.last_progress

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("must_change_password", sa.Boolean(), nullable=False,
                                     server_default=sa.text("false")))
    op.add_column("lab_sessions", sa.Column("last_progress", postgresql.JSONB(), nullable=True))
    op.add_column("lab_sessions", sa.Column("last_progress_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("actor_role", sa.String(20), nullable=False),
        sa.Column("action", sa.String(48), nullable=False),
        sa.Column("course_id", sa.UUID(), nullable=True),
        sa.Column("assignment_id", sa.UUID(), nullable=True),
        sa.Column("subject_user_id", sa.UUID(), nullable=True),
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    for col in ("action", "course_id", "assignment_id", "subject_user_id"):
        op.create_index(f"ix_audit_events_{col}", "audit_events", [col])
    # Same protection as the other append-only tables (0001): triggers + no UPDATE/DELETE/TRUNCATE grant.
    op.execute("CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events "
               "FOR EACH ROW EXECUTE FUNCTION cloudlabs_append_only()")
    op.execute("CREATE TRIGGER audit_events_no_truncate BEFORE TRUNCATE ON audit_events "
               "FOR EACH STATEMENT EXECUTE FUNCTION cloudlabs_append_only()")
    op.execute("GRANT SELECT, INSERT ON audit_events TO cloudlabs_app")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE audit_events_id_seq TO cloudlabs_app")


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_column("lab_sessions", "last_progress_at")
    op.drop_column("lab_sessions", "last_progress")
    op.drop_column("users", "must_change_password")
