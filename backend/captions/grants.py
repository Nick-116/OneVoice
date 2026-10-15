"""Least-privilege grants for the worker and ingest database roles.

Reflects the latest schema. Applied by the newest migration that changes
permissions, and re-applied after a restore:
    docker compose run --rm migrate python -m captions.grants
"""

from __future__ import annotations

GRANTS_SQL = """
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'captions_worker') THEN
    GRANT SELECT ON app_settings, languages, campuses, campus_languages,
          service_schedules, service_events, schedule_exceptions, provider_configs,
          branding_assets
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


if __name__ == "__main__":
    import asyncio

    from sqlalchemy import text

    from . import db

    async def main() -> None:
        async with db.get_engine().begin() as conn:
            await conn.execute(text(GRANTS_SQL))
        await db.dispose()
        print("grants applied")

    asyncio.run(main())
