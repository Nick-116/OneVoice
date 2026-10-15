-- Test database only: the per-service roles exist so migrations really apply their GRANTs
-- (production creates them with passwords in init-roles.sh).
CREATE ROLE captions_worker NOLOGIN;
CREATE ROLE captions_ingest NOLOGIN;
