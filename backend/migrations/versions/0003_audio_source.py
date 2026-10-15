"""Per-campus audio source: local input on the server (default) or remote sender app.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-15
"""

import sqlalchemy as sa
from alembic import op

from captions.grants import GRANTS_SQL

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("campuses", sa.Column("audio_source", sa.String(16), nullable=False, server_default="local"))
    op.add_column("campuses", sa.Column("local_device", sa.String(200), nullable=True))
    op.add_column("campuses", sa.Column("local_channel", sa.Integer, nullable=False, server_default="1"))
    op.create_check_constraint("ck_campus_audio_source", "campuses", "audio_source IN ('local','remote')")
    # Existing campuses that already use the sender app keep working unchanged.
    op.execute("UPDATE campuses SET audio_source = 'remote' WHERE id IN (SELECT DISTINCT campus_id FROM audio_senders)")
    op.execute(GRANTS_SQL)


def downgrade() -> None:
    op.drop_constraint("ck_campus_audio_source", "campuses")
    op.drop_column("campuses", "local_channel")
    op.drop_column("campuses", "local_device")
    op.drop_column("campuses", "audio_source")
