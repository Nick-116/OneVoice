"""Initial schema, language seed data and least-privilege grants.

Revision ID: 0001
Revises:
Create Date: 2026-10-15
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from captions.languages import CATALOG

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", pg.JSONB, nullable=False),
        sa.Column("updated_at", TZ, server_default=sa.func.now()),
    )
    op.create_table(
        "languages",
        sa.Column("code", sa.String(16), primary_key=True),
        sa.Column("name_en", sa.String(80), nullable=False),
        sa.Column("native_name", sa.String(80), nullable=False),
        sa.Column("rtl", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="100"),
        sa.Column("provider_codes", pg.JSONB, nullable=False, server_default="{}"),
    )
    op.create_table(
        "campuses",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="America/New_York"),
        sa.Column("source_language", sa.String(16), nullable=False, server_default="en"),
        sa.Column("default_language", sa.String(16), nullable=False, server_default="en"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("retain_transcripts", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", TZ, server_default=sa.func.now()),
        sa.Column("updated_at", TZ, server_default=sa.func.now()),
    )
    op.create_table(
        "campus_languages",
        sa.Column("campus_id", sa.Integer, sa.ForeignKey("campuses.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("language_code", sa.String(16), sa.ForeignKey("languages.code", ondelete="CASCADE"), primary_key=True),
    )
    op.create_table(
        "service_schedules",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("campus_id", sa.Integer, sa.ForeignKey("campuses.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("weekday", sa.SmallInteger, nullable=False),
        sa.Column("start_time", sa.Time, nullable=False),
        sa.Column("end_time", sa.Time, nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="America/New_York"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("early_access_minutes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("languages", pg.JSONB, nullable=True),
        sa.Column("valid_from", sa.Date, nullable=True),
        sa.Column("valid_until", sa.Date, nullable=True),
        sa.Column("created_at", TZ, server_default=sa.func.now()),
        sa.CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_schedule_weekday"),
        sa.CheckConstraint("early_access_minutes BETWEEN 0 AND 240", name="ck_schedule_early"),
    )
    op.create_table(
        "service_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("campus_id", sa.Integer, sa.ForeignKey("campuses.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False, server_default="special"),
        sa.Column("start_at", TZ, nullable=False),
        sa.Column("end_at", TZ, nullable=False),
        sa.Column("early_access_minutes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cancelled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("languages", pg.JSONB, nullable=True),
        sa.Column("created_at", TZ, server_default=sa.func.now()),
        sa.CheckConstraint("end_at > start_at", name="ck_event_order"),
    )
    op.create_index("ix_service_events_end_at", "service_events", ["end_at"])
    op.create_table(
        "schedule_exceptions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("schedule_id", sa.Integer, sa.ForeignKey("service_schedules.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("occurrence_date", sa.Date, nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("start_at", TZ, nullable=True),
        sa.Column("end_at", TZ, nullable=True),
        sa.Column("note", sa.String(200), nullable=True),
        sa.Column("created_at", TZ, server_default=sa.func.now()),
        sa.UniqueConstraint("schedule_id", "occurrence_date"),
    )
    op.create_table(
        "audio_senders",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("campus_id", sa.Integer, sa.ForeignKey("campuses.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("token_hash", sa.String(128), nullable=False),
        sa.Column("allowed_cidrs", pg.JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", TZ, server_default=sa.func.now()),
        sa.Column("revoked_at", TZ, nullable=True),
    )
    op.create_table(
        "admin_users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("display_name", sa.String(120), nullable=False, server_default=""),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(16), nullable=False, server_default="operator"),
        sa.Column("totp_secret_enc", sa.Text, nullable=True),
        sa.Column("mfa_enabled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("disabled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", TZ, server_default=sa.func.now()),
        sa.Column("last_login_at", TZ, nullable=True),
        sa.CheckConstraint("role IN ('admin','operator')", name="ck_admin_role"),
    )
    op.create_table(
        "admin_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("csrf_token", sa.String(64), nullable=False),
        sa.Column("mfa_verified", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", TZ, server_default=sa.func.now()),
        sa.Column("last_seen_at", TZ, server_default=sa.func.now()),
        sa.Column("expires_at", TZ, nullable=False),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
    )
    op.create_table(
        "provider_configs",
        sa.Column("kind", sa.String(16), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("settings", pg.JSONB, nullable=False, server_default="{}"),
        sa.Column("secret_enc", sa.Text, nullable=True),
        sa.Column("updated_at", TZ, server_default=sa.func.now()),
    )
    op.create_table(
        "usage_records",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("period_start", TZ, nullable=False, index=True),
        sa.Column("campus_id", sa.Integer, nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("metric", sa.String(32), nullable=False),
        sa.Column("language", sa.String(16), nullable=False, server_default=""),
        sa.Column("quantity", sa.Numeric(18, 3), nullable=False, server_default="0"),
        sa.Column("est_cost_usd", sa.Numeric(12, 5), nullable=False, server_default="0"),
        sa.UniqueConstraint("period_start", "campus_id", "provider", "metric", "language"),
    )
    op.create_table(
        "transcripts",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("campus_id", sa.Integer, nullable=False, index=True),
        sa.Column("occurrence_key", sa.String(64), nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("created_at", TZ, server_default=sa.func.now(), index=True),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("at", TZ, server_default=sa.func.now(), index=True),
        sa.Column("user_id", sa.Integer, nullable=True),
        sa.Column("username", sa.String(64), nullable=False, server_default=""),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target", sa.String(200), nullable=False, server_default=""),
        sa.Column("details", pg.JSONB, nullable=False, server_default="{}"),
        sa.Column("ip", sa.String(64), nullable=True),
    )

    languages = sa.table(
        "languages",
        sa.column("code", sa.String),
        sa.column("name_en", sa.String),
        sa.column("native_name", sa.String),
        sa.column("rtl", sa.Boolean),
        sa.column("enabled", sa.Boolean),
        sa.column("sort_order", sa.Integer),
        sa.column("provider_codes", pg.JSONB),
    )
    op.bulk_insert(
        languages,
        [
            {
                "code": lang.code,
                "name_en": lang.name_en,
                "native_name": lang.native_name,
                "rtl": lang.rtl,
                "enabled": True,
                "sort_order": i * 10,
                "provider_codes": dict(lang.provider_codes),
            }
            for i, lang in enumerate(CATALOG)
        ],
    )

    # Least-privilege grants. Roles are created by deploy/postgres/sync-roles.sh;
    # the SQL is a no-op in environments without them (tests).
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'captions_worker') THEN
            GRANT SELECT ON app_settings, languages, campuses, campus_languages,
                  service_schedules, service_events, schedule_exceptions, provider_configs
                  TO captions_worker;
            GRANT SELECT, INSERT, UPDATE ON usage_records TO captions_worker;
            GRANT SELECT, INSERT, DELETE ON transcripts TO captions_worker;
            GRANT USAGE ON SEQUENCE usage_records_id_seq, transcripts_id_seq TO captions_worker;
          END IF;
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'captions_ingest') THEN
            GRANT SELECT (id, campus_id, name, token_hash, allowed_cidrs, revoked_at) ON audio_senders TO captions_ingest;
            GRANT SELECT (id, slug, enabled) ON campuses TO captions_ingest;
          END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    for table in [
        "audit_log",
        "transcripts",
        "usage_records",
        "provider_configs",
        "admin_sessions",
        "admin_users",
        "audio_senders",
        "schedule_exceptions",
        "service_events",
        "service_schedules",
        "campus_languages",
        "campuses",
        "languages",
        "app_settings",
    ]:
        op.drop_table(table)
