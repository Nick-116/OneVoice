"""Branding assets (uploaded logo) + worker read access.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-15
"""

import sqlalchemy as sa
from alembic import op


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "branding_assets",
        sa.Column("key", sa.String(32), primary_key=True),
        sa.Column("content", sa.LargeBinary, nullable=False),
        sa.Column("content_type", sa.String(64), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    # Grants as of this revision (frozen: captions.grants tracks the newest schema only).
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'captions_worker') THEN
            GRANT SELECT ON branding_assets TO captions_worker;
          END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.drop_table("branding_assets")
