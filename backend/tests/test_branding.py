"""Palette contrast, logo upload validation, public delivery, and the update request bridge."""

import io
import json

import httpx
import pytest

from captions.branding import LogoError, build_palette, contrast_ratio, normalize_logo

from .conftest import needs_services


def png_bytes(w=200, h=120, color=(243, 113, 33, 255), extra: bytes = b"") -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGBA", (w, h), color).save(buf, format="PNG")
    return buf.getvalue() + extra


@pytest.mark.parametrize("accent", ["#F37121", "#2563EB", "#FFD400", "#00FF00", "#111111", "#FFFFFF", "#7C3AED"])
def test_palette_meets_contrast_targets(accent):
    p = build_palette(accent)
    assert p["500"] == accent.upper()
    assert contrast_ratio(p["600"], "#FFFFFF") >= 3.0
    assert contrast_ratio(p["700"], "#FFFFFF") >= 4.5  # buttons with white text, links
    assert contrast_ratio(p["800"], "#FFFFFF") >= 7.0
    # Shades never get lighter as the number goes up.
    lum = [contrast_ratio(p[k], "#FFFFFF") for k in ("600", "700", "800")]
    assert lum == sorted(lum)


def test_palette_rejects_garbage():
    assert build_palette("red; background:url(x)")["500"] == "#2563EB"


def test_normalize_logo_reencodes_and_strips_trailing_data():
    raw = png_bytes(extra=b"<script>alert(1)</script>")
    out, sha = normalize_logo(raw)
    assert out.startswith(b"\x89PNG") and b"<script>" not in out and len(sha) == 64


def test_normalize_logo_downscales_large_images():
    from PIL import Image

    out, _ = normalize_logo(png_bytes(3000, 1500))
    with Image.open(io.BytesIO(out)) as img:
        assert max(img.size) == 1024


@pytest.mark.parametrize("data", [b"GIF89a....", b"<svg xmlns='http://www.w3.org/2000/svg'/>", b"\x89PNG\r\n\x1a\nnot really"])
def test_normalize_logo_rejects_non_png(data):
    with pytest.raises(LogoError):
        normalize_logo(data)


# ---------------------------------------------------------------- API (needs services)
pytestmark_services = needs_services


@needs_services
async def test_branding_upload_flows_to_public_site(clean, redis_client, run_server, monkeypatch, tmp_path):
    from captions.admin.app import create_app as admin_app
    from captions.public.app import create_app as public_app
    from captions.redisio import make_redis
    from captions.worker.supervisor import Supervisor

    from .test_admin_api import Admin, create_user

    await create_user()
    async with run_server(admin_app()) as srv, httpx.AsyncClient(base_url=srv.base, timeout=10) as c:
        a = Admin(c)
        await a.login()
        await a.enrol_mfa()

        r = await a.put("/api/branding", json={"church_name": "Grace Chapel", "accent_color": "#f37121"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["accent_color"] == "#F37121" and body["contrast"]["700"] >= 4.5
        assert (await a.put("/api/branding", json={"accent_color": "orange"})).status_code == 422
        assert (await a.put("/api/branding", json={"body_font": "Comic Sans; }"})).status_code == 422
        r = await a.put("/api/branding", json={"body_font": "atkinson", "name_font": "cinzel"})
        assert r.json()["body_font"] == "atkinson" and r.json()["name_font"] == "cinzel"

        # Wrong type, fake PNG, oversize: all refused.
        assert (await c.put("/api/branding/logo", content=b"x", headers={**a.headers(), "Content-Type": "image/svg+xml"})).status_code == 415
        assert (await c.put("/api/branding/logo", content=b"\x89PNG\r\n\x1a\nnope", headers={**a.headers(), "Content-Type": "image/png"})).status_code == 422
        big = b"\x89PNG\r\n\x1a\n" + b"0" * (6 * 1024 * 1024)
        assert (await c.put("/api/branding/logo", content=big, headers={**a.headers(), "Content-Type": "image/png"})).status_code == 413
        # CSRF still enforced on uploads.
        assert (await c.put("/api/branding/logo", content=png_bytes(), headers={"Content-Type": "image/png"})).status_code == 403

        r = await c.put("/api/branding/logo", content=png_bytes(), headers={**a.headers(), "Content-Type": "image/png"})
        assert r.status_code == 200, r.text
        assert r.json()["logo"]["sha256"]
        assert (await a.get("/api/branding/logo")).headers["content-type"] == "image/png"

    # The worker relays branding to Redis; the public site (no DB access) serves it.
    sup = Supervisor(make_redis(), make_redis(decode=False))
    try:
        await sup.reload_config()
        await sup.tick()
    finally:
        await sup.stop_all()
    async with run_server(public_app()) as srv, httpx.AsyncClient(base_url=srv.base) as c:
        cfg = (await c.get("/api/public/config")).json()
        assert cfg["church_name"] == "Grace Chapel"
        assert cfg["theme"]["500"] == "#F37121" and cfg["logo_version"]
        assert cfg["fonts"] == {"body": "atkinson", "name": "cinzel"}
        logo = await c.get("/branding/logo", params={"v": cfg["logo_version"]})
        assert logo.status_code == 200 and logo.headers["content-type"] == "image/png"
        assert "immutable" in logo.headers["cache-control"]
        again = await c.get("/branding/logo", headers={"If-None-Match": logo.headers["etag"]})
        assert again.status_code == 304


@needs_services
async def test_update_requests_are_admin_only_and_validated(clean, run_server, monkeypatch, tmp_path):
    from captions.admin.app import create_app as admin_app

    from .test_admin_api import Admin, create_user

    monkeypatch.setenv("UPDATER_DIR", str(tmp_path))
    await create_user()
    await create_user("olivia", role="operator")
    async with run_server(admin_app()) as srv, httpx.AsyncClient(base_url=srv.base, timeout=10) as c:
        op = Admin(c)
        await op.login("olivia")
        await op.enrol_mfa()
        assert (await op.get("/api/updates")).status_code == 403
        assert (await op.post("/api/updates/check")).status_code == 403
        await op.post("/api/auth/logout")

        a = Admin(c)
        await a.login()
        await a.enrol_mfa()
        state = (await a.get("/api/updates")).json()
        assert state["updater_online"] is False and state["installed"]["version"]
        assert (await a.post("/api/updates/apply", json={})).status_code == 503  # updater not running

        assert (await a.post("/api/updates/check")).status_code == 200
        req = json.loads((tmp_path / "request.json").read_text())
        assert req["action"] == "check" and req["by"] == "alice"

        # Simulate a running updater and request an install.
        (tmp_path / "status.json").write_text(json.dumps({"state": "idle", "heartbeat": "2999-01-01T00:00:00Z"}))
        assert (await a.post("/api/updates/apply", json={"force": False})).status_code == 200
        assert json.loads((tmp_path / "request.json").read_text())["action"] == "apply"
        assert (await a.post("/api/updates/apply", json={"evil": "rm -rf /"})).status_code == 422
