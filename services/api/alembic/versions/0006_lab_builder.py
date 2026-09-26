"""Phase 8: Instructor Lab Builder (lab ownership + sharing, lab drafts)

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

DRAFT_STATUSES = ("draft", "testing", "passed", "failed", "published")


def upgrade() -> None:
    # owner_id NULL = built-in mission (imported from labs/ on disk), visible to everyone.
    op.add_column("labs", sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"),
                                    nullable=True))
    op.add_column("labs", sa.Column("shared", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.create_index("ix_labs_owner_id", "labs", ["owner_id"])
    op.create_table(
        "lab_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("base_lab_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("lab_versions.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("status", sa.String(12), nullable=False, server_default="draft"),
        sa.Column("last_validation", postgresql.JSONB(), nullable=True),
        sa.Column("last_test", postgresql.JSONB(), nullable=True),
        sa.Column("tested_sha256", sa.String(64), nullable=True),
        sa.Column("published_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("lab_versions.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN (" + ", ".join(f"'{s}'" for s in DRAFT_STATUSES) + ")",
                           name="ck_lab_drafts_status"),
    )
    op.create_index("ix_lab_drafts_owner_id", "lab_drafts", ["owner_id"])
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON lab_drafts TO cloudlabs_app")


def downgrade() -> None:
    op.drop_index("ix_lab_drafts_owner_id", "lab_drafts")
    op.drop_table("lab_drafts")
    op.drop_index("ix_labs_owner_id", "labs")
    op.drop_column("labs", "shared")
    op.drop_column("labs", "owner_id")
