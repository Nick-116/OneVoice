"""Branding: accent palette generation and logo validation.

The administrator picks any accent color. Text and filled buttons must stay
readable (WCAG AA), so darker shades are derived by mixing toward black until
each shade reaches its contrast target against white. The chosen color itself
is kept as shade 500 for decorative uses (focus rings, accents).
"""

from __future__ import annotations

import hashlib
import io
import re

HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

# Fonts bundled with the public site (public-web/src/lib/fonts.ts), key -> display name.
FONTS = {
    "system": "Phone default (system)",
    "inter": "Inter",
    "open-sans": "Open Sans",
    "lato": "Lato",
    "nunito": "Nunito",
    "source-sans": "Source Sans 3",
    "atkinson": "Atkinson Hyperlegible (high legibility)",
    "merriweather": "Merriweather (serif)",
    "lora": "Lora (serif)",
    "playfair": "Playfair Display (serif)",
    "montserrat": "Montserrat",
    "poppins": "Poppins",
    "cinzel": "Cinzel (classic capitals)",
    "cormorant": "Cormorant Garamond (serif)",
    "raleway": "Raleway",
}
DEFAULT_ACCENT = "#2563EB"

MAX_LOGO_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_LOGO_DIMENSION = 1024  # px; larger logos are downscaled
MAX_LOGO_PIXELS = 40_000_000  # refuse decompression bombs before decoding

# shade -> minimum contrast ratio against white
CONTRAST_TARGETS = {600: 3.0, 700: 4.5, 800: 7.0}


def _rgb(hex_color: str) -> tuple[int, int, int]:
    return int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)


def _hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02X}" for c in rgb)


def relative_luminance(hex_color: str) -> float:
    def channel(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = _rgb(hex_color)
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(a: str, b: str) -> float:
    la, lb = sorted((relative_luminance(a), relative_luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _mix(hex_color: str, other: tuple[int, int, int], amount: float) -> str:
    r, g, b = _rgb(hex_color)
    return _hex(tuple(c + (o - c) * amount for c, o in zip((r, g, b), other)))


def _darken_until(hex_color: str, target: float, floor: str | None = None) -> str:
    """Smallest mix toward black that reaches ``target`` contrast with white,
    never lighter than ``floor`` (keeps shades ordered)."""
    start = floor or hex_color
    for step in range(0, 101):
        candidate = _mix(start, (0, 0, 0), step / 100)
        if contrast_ratio(candidate, "#FFFFFF") >= target:
            return candidate
    return "#000000"


def build_palette(accent: str) -> dict[str, str]:
    if not HEX_RE.match(accent or ""):
        accent = DEFAULT_ACCENT
    accent = accent.upper()
    palette = {
        "50": _mix(accent, (255, 255, 255), 0.92),
        "100": _mix(accent, (255, 255, 255), 0.82),
        "500": accent,
    }
    prev = accent
    for shade, target in CONTRAST_TARGETS.items():
        prev = _darken_until(accent, target, floor=prev)
        palette[str(shade)] = prev
    return palette


class LogoError(ValueError):
    pass


def normalize_logo(data: bytes) -> tuple[bytes, str]:
    """Validate an uploaded PNG and re-encode it.

    Re-encoding through Pillow drops metadata, ancillary chunks and anything
    appended after the image data, so the stored file is a plain PNG no matter
    what was uploaded. Returns (png_bytes, sha256_hex).
    """
    from PIL import Image, UnidentifiedImageError

    if len(data) > MAX_LOGO_UPLOAD_BYTES:
        raise LogoError("Logo must be 5 MB or smaller")
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise LogoError("Logo must be a PNG file")
    Image.MAX_IMAGE_PIXELS = MAX_LOGO_PIXELS
    try:
        with Image.open(io.BytesIO(data)) as probe:
            if probe.format != "PNG":
                raise LogoError("Logo must be a PNG file")
            probe.verify()
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            img = img.convert("RGBA")
    except LogoError:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError) as e:
        raise LogoError("The file is not a valid PNG image") from e
    if img.width < 16 or img.height < 16:
        raise LogoError("Logo is too small (minimum 16×16 pixels)")
    img.thumbnail((MAX_LOGO_DIMENSION, MAX_LOGO_DIMENSION), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    png = out.getvalue()
    return png, hashlib.sha256(png).hexdigest()
