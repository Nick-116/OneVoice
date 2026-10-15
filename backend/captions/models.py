"""SQLAlchemy ORM models. The schema itself is owned by Alembic migrations."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Language(Base):
    __tablename__ = "languages"
    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name_en: Mapped[str] = mapped_column(String(80))
    native_name: Mapped[str] = mapped_column(String(80))
    rtl: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=100)
    provider_codes: Mapped[dict] = mapped_column(JSONB, default=dict)


class Campus(Base):
    __tablename__ = "campuses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(String(64), default="America/New_York")
    source_language: Mapped[str] = mapped_column(String(16), default="en")
    default_language: Mapped[str] = mapped_column(String(16), default="en")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    retain_transcripts: Mapped[bool] = mapped_column(Boolean, default=False)
    # "local" = audio interface on the OneVoice server (local-audio service); "remote" = OneVoice Sender app.
    audio_source: Mapped[str] = mapped_column(String(16), default="local")
    local_device: Mapped[str | None] = mapped_column(String(200), nullable=True)
    local_channel: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    languages: Mapped[list["CampusLanguage"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def language_codes(self) -> list[str]:
        return [cl.language_code for cl in self.languages]


class CampusLanguage(Base):
    __tablename__ = "campus_languages"
    campus_id: Mapped[int] = mapped_column(ForeignKey("campuses.id", ondelete="CASCADE"), primary_key=True)
    language_code: Mapped[str] = mapped_column(ForeignKey("languages.code", ondelete="CASCADE"), primary_key=True)


class ServiceSchedule(Base):
    """A recurring weekly service (e.g. Sundays 9:00-10:30)."""

    __tablename__ = "service_schedules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campus_id: Mapped[int] = mapped_column(ForeignKey("campuses.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    weekday: Mapped[int] = mapped_column(SmallInteger)  # 0 = Monday ... 6 = Sunday
    start_time: Mapped[dt.time] = mapped_column(Time)
    end_time: Mapped[dt.time] = mapped_column(Time)
    timezone: Mapped[str] = mapped_column(String(64), default="America/New_York")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    early_access_minutes: Mapped[int] = mapped_column(Integer, default=0)
    languages: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # None = campus languages
    valid_from: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    valid_until: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ServiceEvent(Base):
    """A one-time service: special event, holiday service or manual start."""

    __tablename__ = "service_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campus_id: Mapped[int] = mapped_column(ForeignKey("campuses.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(16), default="special")  # special | holiday | manual
    start_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    early_access_minutes: Mapped[int] = mapped_column(Integer, default=0)
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    languages: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScheduleException(Base):
    """Cancels or re-times a single occurrence of a recurring schedule."""

    __tablename__ = "schedule_exceptions"
    __table_args__ = (UniqueConstraint("schedule_id", "occurrence_date"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    schedule_id: Mapped[int] = mapped_column(ForeignKey("service_schedules.id", ondelete="CASCADE"), index=True)
    occurrence_date: Mapped[dt.date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(16))  # cancel | modify
    start_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AudioSender(Base):
    __tablename__ = "audio_senders"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campus_id: Mapped[int] = mapped_column(ForeignKey("campuses.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    token_hash: Mapped[str] = mapped_column(String(128))
    allowed_cidrs: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AdminUser(Base):
    __tablename__ = "admin_users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="operator")  # admin | operator
    totp_secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AdminSession(Base):
    __tablename__ = "admin_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("admin_users.id", ondelete="CASCADE"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    mfa_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user: Mapped[AdminUser] = relationship(lazy="joined")


class ProviderConfig(Base):
    __tablename__ = "provider_configs"
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)  # stt | translation
    provider: Mapped[str] = mapped_column(String(32))
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)
    secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class UsageRecord(Base):
    __tablename__ = "usage_records"
    __table_args__ = (UniqueConstraint("period_start", "campus_id", "provider", "metric", "language"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    period_start: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    campus_id: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(32))
    metric: Mapped[str] = mapped_column(String(32))  # stt_seconds | translation_chars
    language: Mapped[str] = mapped_column(String(16), default="")
    quantity: Mapped[float] = mapped_column(Numeric(18, 3), default=0)
    est_cost_usd: Mapped[float] = mapped_column(Numeric(12, 5), default=0)


class Transcript(Base):
    __tablename__ = "transcripts"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    campus_id: Mapped[int] = mapped_column(Integer, index=True)
    occurrence_key: Mapped[str] = mapped_column(String(64))
    language: Mapped[str] = mapped_column(String(16))
    seq: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    username: Mapped[str] = mapped_column(String(64), default="")
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String(200), default="")
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)


class BrandingAsset(Base):
    """Uploaded branding files (currently only key='logo', a re-encoded PNG)."""

    __tablename__ = "branding_assets"
    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    content: Mapped[bytes] = mapped_column(LargeBinary)
    content_type: Mapped[str] = mapped_column(String(64))
    sha256: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
