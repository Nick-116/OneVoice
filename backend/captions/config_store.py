"""Loads administrator-managed configuration from PostgreSQL.

Used by the worker (to drive scheduling and providers) and by the admin API.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import models as m
from .config import read_secret
from .schedule import EventSpec, ExceptionSpec, RecurringSpec
from .security import decrypt_secret

GENERAL_DEFAULTS: dict[str, Any] = {
    "church_name": "Our Church",
    "accent_color": "#2563EB",  # public site buttons/links; darker shades derived for contrast
    "body_font": "system",  # caption + interface text (keys in captions.branding.FONTS)
    "name_font": "system",  # church name under the logo
    "public_base_url": "",  # empty = use PUBLIC_BASE_URL env
    "manual_default_minutes": 120,
    "ended_grace_minutes": 180,
    "lookahead_days": 14,
    "transcript_retention_days": 30,
    "translate_partials": False,
    "partial_min_interval_ms": 1500,
    "language_grace_seconds": 15,  # stop translating a language this long after its last viewer leaves
    "audio_timeout_seconds": 5,
    "digital_silence_seconds": 20,
}

STT_PROVIDERS = {
    "deepgram": {"model": "nova-3", "endpointing_ms": 300, "keyterms": [], "price_per_minute": 0.0077},
    "assemblyai": {"price_per_minute": 0.0025, "keyterms": []},
    "simulated": {"price_per_minute": 0.0, "words_per_minute": 150},
}

TRANSLATION_PROVIDERS = {
    "azure": {"region": "eastus", "endpoint": "https://api.cognitive.microsofttranslator.com", "price_per_million_chars": 10.0},
    "google": {"price_per_million_chars": 20.0},
    "simulated": {"price_per_million_chars": 0.0, "fail_languages": [], "delay_ms": 150},
}

ENV_KEYS = {
    "deepgram": "DEEPGRAM_API_KEY",
    "assemblyai": "ASSEMBLYAI_API_KEY",
    "azure": "AZURE_TRANSLATOR_KEY",
    "google": "GOOGLE_TRANSLATE_API_KEY",
}


@dataclass
class ProviderSelection:
    kind: str
    provider: str
    settings: dict[str, Any]
    api_key: str | None

    @property
    def has_key(self) -> bool:
        return bool(self.api_key)


@dataclass
class CampusConfig:
    id: int
    slug: str
    name: str
    timezone: str
    source_language: str
    default_language: str
    enabled: bool
    retain_transcripts: bool
    languages: list[str]
    audio_source: str = "local"
    local_device: str | None = None
    local_channel: int = 1


@dataclass
class LanguageConfig:
    code: str
    name_en: str
    native_name: str
    rtl: bool
    enabled: bool
    sort_order: int
    provider_codes: dict[str, str]


@dataclass
class ConfigSnapshot:
    general: dict[str, Any]
    campuses: list[CampusConfig]
    languages: dict[str, LanguageConfig]
    recurring: list[RecurringSpec]
    events: list[EventSpec]
    exceptions: list[ExceptionSpec]
    stt: ProviderSelection
    translation: ProviderSelection
    loaded_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))


def merged_general(stored: dict | None) -> dict[str, Any]:
    out = dict(GENERAL_DEFAULTS)
    if stored:
        out.update({k: v for k, v in stored.items() if k in GENERAL_DEFAULTS})
    return out


def provider_selection(kind: str, row: m.ProviderConfig | None) -> ProviderSelection:
    defaults = STT_PROVIDERS if kind == "stt" else TRANSLATION_PROVIDERS
    provider = row.provider if row and row.provider in defaults else ("deepgram" if kind == "stt" else "azure")
    settings = dict(defaults[provider])
    if row and row.provider == provider and row.settings:
        settings.update(row.settings)
    key = decrypt_secret(row.secret_enc) if row and row.provider == provider else None
    if not key and provider in ENV_KEYS:
        key = read_secret(ENV_KEYS[provider])
    return ProviderSelection(kind=kind, provider=provider, settings=settings, api_key=key)


async def load_general(session: AsyncSession) -> dict[str, Any]:
    row = await session.get(m.AppSetting, "general")
    return merged_general(row.value if row else None)


async def load_snapshot(session: AsyncSession) -> ConfigSnapshot:
    general = await load_general(session)
    campuses = (await session.execute(select(m.Campus).order_by(m.Campus.id))).scalars().all()
    langs = (await session.execute(select(m.Language))).scalars().all()
    scheds = (await session.execute(select(m.ServiceSchedule))).scalars().all()
    now = dt.datetime.now(dt.timezone.utc)
    events = (
        await session.execute(
            select(m.ServiceEvent).where(m.ServiceEvent.end_at > now - dt.timedelta(days=2))
        )
    ).scalars().all()
    excs = (
        await session.execute(
            select(m.ScheduleException).where(
                m.ScheduleException.occurrence_date >= (now - dt.timedelta(days=2)).date()
            )
        )
    ).scalars().all()
    providers = {p.kind: p for p in (await session.execute(select(m.ProviderConfig))).scalars().all()}

    return ConfigSnapshot(
        general=general,
        campuses=[
            CampusConfig(
                id=c.id,
                slug=c.slug,
                name=c.name,
                timezone=c.timezone,
                source_language=c.source_language,
                default_language=c.default_language,
                enabled=c.enabled,
                retain_transcripts=c.retain_transcripts,
                languages=c.language_codes,
                audio_source=c.audio_source,
                local_device=c.local_device,
                local_channel=c.local_channel,
            )
            for c in campuses
        ],
        languages={
            lang.code: LanguageConfig(
                code=lang.code,
                name_en=lang.name_en,
                native_name=lang.native_name,
                rtl=lang.rtl,
                enabled=lang.enabled,
                sort_order=lang.sort_order,
                provider_codes=lang.provider_codes or {},
            )
            for lang in langs
        },
        recurring=[recurring_spec(s) for s in scheds],
        events=[event_spec(e) for e in events],
        exceptions=[exception_spec(x) for x in excs],
        stt=provider_selection("stt", providers.get("stt")),
        translation=provider_selection("translation", providers.get("translation")),
    )


def recurring_spec(s: m.ServiceSchedule) -> RecurringSpec:
    return RecurringSpec(
        id=s.id,
        campus_id=s.campus_id,
        name=s.name,
        weekday=s.weekday,
        start_time=s.start_time,
        end_time=s.end_time,
        timezone=s.timezone,
        enabled=s.enabled,
        early_access_minutes=s.early_access_minutes,
        languages=tuple(s.languages) if s.languages else None,
        valid_from=s.valid_from,
        valid_until=s.valid_until,
    )


def event_spec(e: m.ServiceEvent) -> EventSpec:
    return EventSpec(
        id=e.id,
        campus_id=e.campus_id,
        name=e.name,
        kind=e.kind,
        start_at=e.start_at,
        end_at=e.end_at,
        early_access_minutes=e.early_access_minutes,
        cancelled=e.cancelled,
        languages=tuple(e.languages) if e.languages else None,
    )


def exception_spec(x: m.ScheduleException) -> ExceptionSpec:
    return ExceptionSpec(
        schedule_id=x.schedule_id,
        occurrence_date=x.occurrence_date,
        kind=x.kind,
        start_at=x.start_at,
        end_at=x.end_at,
    )
