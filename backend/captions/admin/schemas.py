"""Request/response validation for the admin API."""

from __future__ import annotations

import datetime as dt
import ipaddress
import re
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, BaseModel, Field, field_validator, model_validator

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
LANG_RE = re.compile(r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$")
RESERVED_SLUGS = {"api", "assets", "branding", "campus", "healthz", "static", "admin", "favicon.ico", "favicon.svg", "robots.txt"}


def _tz(v: str) -> str:
    try:
        ZoneInfo(v)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("unknown IANA time zone")
    return v


def _langs(v: list[str] | None) -> list[str] | None:
    if v is None:
        return None
    for code in v:
        if not LANG_RE.match(code):
            raise ValueError(f"invalid language code {code!r}")
    return list(dict.fromkeys(v))


TimeZoneName = Annotated[str, AfterValidator(_tz)]
LangList = Annotated[list[str], AfterValidator(_langs)]
OptLangList = Annotated[list[str] | None, AfterValidator(_langs)]


class Strict(BaseModel):
    model_config = {"extra": "forbid", "str_strip_whitespace": True}


# ---------------------------------------------------------------- auth
class LoginIn(Strict):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class CodeIn(Strict):
    code: str = Field(pattern=r"^\d{6}$")


class PasswordChangeIn(Strict):
    current_password: str = Field(max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


# ---------------------------------------------------------------- campuses
class CampusIn(Strict):
    slug: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    timezone: TimeZoneName = "America/New_York"
    source_language: str = Field(default="en", pattern=LANG_RE.pattern)
    default_language: str = Field(default="en", pattern=LANG_RE.pattern)
    enabled: bool = True
    retain_transcripts: bool = False
    languages: LangList = Field(default_factory=lambda: ["en", "es"])
    audio_source: Literal["local", "remote"] = "local"
    local_device: str | None = Field(default=None, max_length=200)
    local_channel: int = Field(default=1, ge=1, le=64)

    @field_validator("slug")
    @classmethod
    def slug_ok(cls, v: str) -> str:
        v = v.lower()
        if not SLUG_RE.match(v) or v in RESERVED_SLUGS:
            raise ValueError("slug must be lowercase letters, digits and dashes, and not a reserved word")
        return v



class CampusPatch(Strict):
    slug: str | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    timezone: str | None = None
    source_language: str | None = None
    default_language: str | None = None
    enabled: bool | None = None
    retain_transcripts: bool | None = None
    languages: OptLangList = None
    audio_source: Literal["local", "remote"] | None = None
    local_device: str | None = Field(default=None, max_length=200)
    local_channel: int | None = Field(default=None, ge=1, le=64)

    @field_validator("slug")
    @classmethod
    def slug_ok(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return CampusIn.slug_ok(v)

    @field_validator("timezone")
    @classmethod
    def tz_ok(cls, v: str | None) -> str | None:
        return _tz(v) if v else v



# ---------------------------------------------------------------- schedules
class ScheduleIn(Strict):
    campus_id: int
    name: str = Field(min_length=1, max_length=120)
    weekday: int = Field(ge=0, le=6)
    start_time: dt.time
    end_time: dt.time
    timezone: TimeZoneName = "America/New_York"
    enabled: bool = True
    early_access_minutes: int = Field(default=0, ge=0, le=240)
    languages: OptLangList = None
    valid_from: dt.date | None = None
    valid_until: dt.date | None = None


    @model_validator(mode="after")
    def times_ok(self):
        if self.start_time == self.end_time:
            raise ValueError("start and end time must differ")
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("valid_until is before valid_from")
        return self


class SchedulePatch(Strict):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    weekday: int | None = Field(default=None, ge=0, le=6)
    start_time: dt.time | None = None
    end_time: dt.time | None = None
    timezone: str | None = None
    enabled: bool | None = None
    early_access_minutes: int | None = Field(default=None, ge=0, le=240)
    languages: OptLangList = None
    valid_from: dt.date | None = None
    valid_until: dt.date | None = None
    campus_id: int | None = None

    @field_validator("timezone")
    @classmethod
    def tz_ok(cls, v):
        return _tz(v) if v else v



class EventIn(Strict):
    campus_id: int
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["special", "holiday"] = "special"
    start_at: dt.datetime
    end_at: dt.datetime
    early_access_minutes: int = Field(default=0, ge=0, le=240)
    languages: OptLangList = None

    @model_validator(mode="after")
    def order_ok(self):
        if self.start_at.tzinfo is None or self.end_at.tzinfo is None:
            raise ValueError("start_at and end_at must include a UTC offset")
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        if self.end_at - self.start_at > dt.timedelta(hours=24):
            raise ValueError("a service cannot be longer than 24 hours")
        return self


class EventPatch(Strict):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    kind: Literal["special", "holiday", "manual"] | None = None
    start_at: dt.datetime | None = None
    end_at: dt.datetime | None = None
    early_access_minutes: int | None = Field(default=None, ge=0, le=240)
    cancelled: bool | None = None
    languages: OptLangList = None



class OccurrenceRef(Strict):
    key: str = Field(pattern=r"^(r\d+-\d{4}-\d{2}-\d{2}|e\d+)$")


class StartIn(Strict):
    duration_minutes: int | None = Field(default=None, ge=5, le=720)
    name: str = Field(default="Live service", min_length=1, max_length=120)


class ExtendIn(Strict):
    minutes: int = Field(ge=5, le=240)


# ---------------------------------------------------------------- languages
class LanguagePatch(Strict):
    enabled: bool | None = None
    native_name: str | None = Field(default=None, min_length=1, max_length=80)
    name_en: str | None = Field(default=None, min_length=1, max_length=80)
    sort_order: int | None = Field(default=None, ge=0, le=10000)
    rtl: bool | None = None
    provider_codes: dict[str, str] | None = None


class LanguageIn(Strict):
    code: str
    name_en: str = Field(min_length=1, max_length=80)
    native_name: str = Field(min_length=1, max_length=80)
    rtl: bool = False
    enabled: bool = True
    sort_order: int = Field(default=500, ge=0, le=10000)
    provider_codes: dict[str, str] = Field(default_factory=dict)

    @field_validator("code")
    @classmethod
    def code_ok(cls, v: str) -> str:
        if not LANG_RE.match(v):
            raise ValueError("invalid language code")
        return v


class TranslateTestIn(Strict):
    text: str = Field(min_length=1, max_length=500)
    target: str
    source: str = "en"


# ---------------------------------------------------------------- providers & settings
class ProviderIn(Strict):
    provider: str = Field(max_length=32)
    settings: dict[str, Any] = Field(default_factory=dict)
    api_key: str | None = Field(default=None, max_length=512)  # None = keep existing
    clear_key: bool = False


class GeneralSettingsIn(Strict):
    church_name: str | None = Field(default=None, max_length=120)
    accent_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    public_base_url: str | None = Field(default=None, max_length=200)
    manual_default_minutes: int | None = Field(default=None, ge=5, le=720)
    ended_grace_minutes: int | None = Field(default=None, ge=0, le=1440)
    lookahead_days: int | None = Field(default=None, ge=1, le=60)
    transcript_retention_days: int | None = Field(default=None, ge=1, le=3650)
    translate_partials: bool | None = None
    partial_min_interval_ms: int | None = Field(default=None, ge=500, le=10000)
    language_grace_seconds: int | None = Field(default=None, ge=0, le=3600)
    audio_timeout_seconds: int | None = Field(default=None, ge=2, le=60)
    digital_silence_seconds: int | None = Field(default=None, ge=5, le=600)

    @field_validator("public_base_url")
    @classmethod
    def url_ok(cls, v):
        if v and not re.match(r"^https?://[A-Za-z0-9.-]+(:\d+)?(/[A-Za-z0-9._~/-]*)?$", v):
            raise ValueError("must be an http(s) URL")
        return v.rstrip("/") if v else v


# ---------------------------------------------------------------- senders & users
class SenderIn(Strict):
    campus_id: int
    name: str = Field(min_length=1, max_length=120)
    allowed_cidrs: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("allowed_cidrs")
    @classmethod
    def cidrs_ok(cls, v: list[str]) -> list[str]:
        out = []
        for c in v:
            try:
                out.append(str(ipaddress.ip_network(c.strip(), strict=False)))
            except ValueError:
                raise ValueError(f"invalid CIDR {c!r}")
        return out


class SenderPatch(Strict):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    allowed_cidrs: list[str] | None = None

    @field_validator("allowed_cidrs")
    @classmethod
    def cidrs_ok(cls, v):
        return SenderIn.cidrs_ok(v) if v is not None else v


class UserIn(Strict):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9._@-]+$")
    display_name: str = Field(default="", max_length=120)
    password: str = Field(min_length=12, max_length=256)
    role: Literal["admin", "operator"] = "operator"


class UserPatch(Strict):
    display_name: str | None = Field(default=None, max_length=120)
    role: Literal["admin", "operator"] | None = None
    disabled: bool | None = None
    password: str | None = Field(default=None, min_length=12, max_length=256)
    reset_mfa: bool = False


class BrandingIn(Strict):
    church_name: str | None = Field(default=None, min_length=1, max_length=120)
    accent_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    body_font: str | None = None
    name_font: str | None = None

    @field_validator("body_font", "name_font")
    @classmethod
    def font_ok(cls, v: str | None) -> str | None:
        from ..branding import FONTS

        if v is not None and v not in FONTS:
            raise ValueError("unknown font")
        return v
