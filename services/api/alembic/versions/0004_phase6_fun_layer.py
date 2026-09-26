"""Phase 6: user_badges (append-only) and courses.leaderboard

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("courses", sa.Column("leaderboard", sa.String(12), nullable=False, server_default="off"))
    op.create_check_constraint("ck_courses_leaderboard", "courses", "leaderboard IN ('off', 'anonymous', 'named')")
    op.create_table(
        "user_badges",
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("badge_id", sa.String(40), nullable=False),
        sa.Column("attempt_id", sa.UUID(), sa.ForeignKey("attempts.id"), nullable=False),
        sa.Column("awarded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "badge_id"),
    )
    op.execute("CREATE TRIGGER user_badges_append_only BEFORE UPDATE OR DELETE ON user_badges "
               "FOR EACH ROW EXECUTE FUNCTION cloudlabs_append_only()")
    op.execute("CREATE TRIGGER user_badges_no_truncate BEFORE TRUNCATE ON user_badges "
               "FOR EACH STATEMENT EXECUTE FUNCTION cloudlabs_append_only()")
    op.execute("GRANT SELECT, INSERT ON user_badges TO cloudlabs_app")


def downgrade() -> None:
    op.drop_table("user_badges")
    op.drop_constraint("ck_courses_leaderboard", "courses")
    op.drop_column("courses", "leaderboard")
