"""Redis key and channel names, in one place.

The Redis ACL file (deploy/redis/entrypoint.sh) grants each service access
only to the key/channel prefixes it needs; keep the two in sync.

public-web may only touch: public:*  capbuf:*  viewers:*  and channels cap:* status:*
ingest     may only touch: audio:*   ingest:*  campus:live:*
localaudio may only touch: audio:*   localaudio:*  campus:live:*
"""

# Published by worker, read by public-web
PUBLIC_CAMPUSES = "public:campuses"  # JSON list of {slug, name}
PUBLIC_BRANDING = "public:branding"  # JSON {church_name, theme, logo_version}
PUBLIC_LOGO = "public:logo"  # base64 PNG uploaded in the admin dashboard


def public_status(slug: str) -> str:
    return f"public:campus:{slug}"


def status_channel(slug: str) -> str:
    return f"status:{slug}"


def caption_channel(slug: str, lang: str) -> str:
    return f"cap:{slug}:{lang}"


def caption_buffer(slug: str, lang: str) -> str:
    return f"capbuf:{slug}:{lang}"


# Written by public-web, read by worker/admin
def viewers_key(instance: str) -> str:
    return f"viewers:{instance}"


VIEWERS_PATTERN = "viewers:*"


# Audio path (ingest -> worker)
def audio_stream(campus_id: int) -> str:
    return f"audio:stream:{campus_id}"


def audio_status(campus_id: int) -> str:
    return f"audio:status:{campus_id}"


def audio_history(campus_id: int) -> str:
    return f"audio:history:{campus_id}"


def campus_live_flag(campus_id: int) -> str:
    return f"campus:live:{campus_id}"


INGEST_REVOKED_CHANNEL = "ingest:revoked"  # admin -> ingest: drop a sender now

# Local audio input on the server (worker -> local-audio service -> admin)
LOCALAUDIO_CONFIG = "localaudio:config"  # JSON [{campus_id, slug, device, channel}] written by worker
LOCALAUDIO_DEVICES = "localaudio:devices"  # JSON [{name, hostapi, channels, rate}] written by local-audio
LOCALAUDIO_HEARTBEAT = "localaudio:heartbeat"

# Worker/admin internal
CONFIG_CHANGED_CHANNEL = "config:changed"
WORKER_HEARTBEAT = "worker:heartbeat"
ERRORS_LIST = "errors:recent"


def metrics_key(campus_id: int) -> str:
    return f"metrics:{campus_id}"


def provider_status_key(campus_id: int) -> str:
    return f"provider:status:{campus_id}"


def campus_internal_status(campus_id: int) -> str:
    return f"internal:campus:{campus_id}"
