"""Built-in language catalog.

Internal codes are BCP-47-ish tags used everywhere in the app (URLs, Redis
channels, i18n files). Provider modules map them to their own codes. The
database ``languages`` table is seeded from this catalog; administrators can
enable/disable entries and add new rows without code changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LanguageInfo:
    code: str
    name_en: str
    native_name: str
    rtl: bool = False
    # Provider-specific codes. Missing key = use ``code`` as-is.
    provider_codes: dict[str, str] = field(default_factory=dict)


CATALOG: list[LanguageInfo] = [
    LanguageInfo("en", "English", "English"),
    LanguageInfo("es", "Spanish", "Español"),
    LanguageInfo("pt", "Portuguese", "Português"),
    LanguageInfo("fr", "French", "Français"),
    LanguageInfo("ht", "Haitian Creole", "Kreyòl ayisyen"),
    LanguageInfo("zh", "Chinese (Mandarin, Simplified)", "中文", provider_codes={"azure": "zh-Hans", "google": "zh-CN"}),
    LanguageInfo("ko", "Korean", "한국어"),
    LanguageInfo("ar", "Arabic", "العربية", rtl=True),
    LanguageInfo("ru", "Russian", "Русский"),
    LanguageInfo("uk", "Ukrainian", "Українська"),
    LanguageInfo("vi", "Vietnamese", "Tiếng Việt"),
    LanguageInfo("hi", "Hindi", "हिन्दी"),
]

CATALOG_BY_CODE = {lang.code: lang for lang in CATALOG}


def provider_code(code: str, provider: str, overrides: dict[str, str] | None = None) -> str:
    if overrides and provider in overrides:
        return overrides[provider]
    info = CATALOG_BY_CODE.get(code)
    if info and provider in info.provider_codes:
        return info.provider_codes[provider]
    return code
