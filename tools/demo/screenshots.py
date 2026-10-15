#!/usr/bin/env python3
"""Generate the README screenshots from a throwaway demo stack with example data.

    # 1. start an isolated demo copy (separate database/volumes, ports 28080-28082)
    export PUBLIC_PORT=28080 ADMIN_PORT=28081 INGEST_PORT=28082 \
           PUBLIC_BIND=127.0.0.1 ADMIN_BIND=127.0.0.1 INGEST_BIND=127.0.0.1 \
           PUBLIC_BASE_URL=http://localhost:28080 ADMIN_ORIGIN=http://localhost:28081
    docker compose -p onevoice-demo up -d --build
    # 2. run this (needs Google Chrome installed; pip install playwright==1.48.0 pyotp==2.9.0 websockets==13.1)
    python tools/demo/screenshots.py
    # 3. throw the demo away
    docker compose -p onevoice-demo down -v

Everything shown is fictional example data using the simulated speech/translation providers.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import pyotp
from playwright.async_api import Page, async_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "screenshots"
PUBLIC = "http://localhost:28080"
ADMIN = "http://localhost:28081"
INGEST = "ws://localhost:28082/ingest/v1/stream"
SENDER_UI = ROOT / "sender" / "church_sender" / "ui"
LANGS = ["en", "es", "pt", "fr", "ht", "zh", "ko", "ar", "ru", "uk", "vi", "hi"]
USER, PASSWORD = "demo-admin", "demo-password-not-secret"


def setup_code() -> str:
    logs = subprocess.run(["docker", "compose", "-p", "onevoice-demo", "logs", "admin"], capture_output=True, text=True, cwd=ROOT).stdout
    codes = re.findall(r"setup code: ([A-Z0-9]{4}-[A-Z0-9]{4})", logs)
    if not codes:
        sys.exit("No setup code in the admin log: is this a fresh demo stack?")
    return codes[-1]


async def shot(page: Page, name: str, full_page: bool = False) -> None:
    await page.wait_for_timeout(400)
    await page.screenshot(path=str(OUT / f"{name}.png"), full_page=full_page)
    print("saved", name)


async def api(page: Page, method: str, path: str, body=None, raw: bytes | None = None):
    """Call the admin API from inside the logged-in page (cookies + CSRF like the real UI)."""
    script = """async ([method, path, body, raw]) => {
      const me = await (await fetch('/api/auth/me')).json();
      const headers = {'X-CSRF-Token': me.csrf_token};
      let payload;
      if (raw) { headers['Content-Type'] = 'image/png'; payload = Uint8Array.from(atob(raw), c => c.charCodeAt(0)); }
      else if (body !== null) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body); }
      const r = await fetch(path, {method, headers, body: payload});
      const text = await r.text();
      if (!r.ok) throw new Error(method + ' ' + path + ' -> ' + r.status + ' ' + text);
      return text ? JSON.parse(text) : null;
    }"""
    import base64

    return await page.evaluate(script, [method, path, body, base64.b64encode(raw).decode() if raw else None])


async def admin_flow(browser) -> tuple[str, str]:
    ctx = await browser.new_context(viewport={"width": 1360, "height": 900}, device_scale_factor=1.5)
    page = await ctx.new_page()

    # First-run setup: create the first administrator.
    await page.goto(f"{ADMIN}/setup")
    await page.wait_for_selector("text=Create administrator")
    await shot(page, "setup-1-first-admin")
    await page.get_by_label("Setup code").fill(setup_code())
    await page.get_by_label("Username").fill(USER)
    await page.get_by_label("Your name (optional)").fill("Demo Admin")
    await page.get_by_label("Password", exact=True).fill(PASSWORD)
    await page.get_by_label("Confirm password").fill(PASSWORD)
    await page.get_by_role("button", name="Create administrator").click()

    # Two-factor enrolment.
    await page.wait_for_selector("text=Enable two-factor authentication")
    secret = (await page.locator("code").first.inner_text()).strip().replace(" ", "")
    await page.get_by_label("6-digit code").fill(pyotp.TOTP(secret).now())
    await page.get_by_role("button", name="Enable two-factor authentication").click()

    # Wizard: church, speech-to-text, translation.
    await page.wait_for_selector("text=Your church")
    await page.get_by_label("Church name").fill("Grace Community Church")
    await page.get_by_role("button", name="Continue").click()
    await page.wait_for_selector("text=Speech-to-text provider")
    await page.get_by_label("Provider").select_option("deepgram")
    await shot(page, "setup-2-speech-to-text")
    await page.get_by_label("Provider").select_option("simulated")
    await page.get_by_role("button", name="Save provider").click()
    await page.wait_for_timeout(600)
    await page.get_by_role("button", name="Continue").click()
    await page.wait_for_selector("text=Translation provider")
    await page.get_by_label("Provider").select_option("simulated")
    await page.get_by_role("button", name="Save provider").click()
    await page.wait_for_timeout(600)
    await page.get_by_role("button", name="Continue").click()
    await page.get_by_role("button", name="Go to the dashboard").click()
    await page.wait_for_selector("text=Live overview")

    # Example data.
    logo = (ROOT / "tools" / "demo" / "demo-church-logo.png").read_bytes()
    await api(page, "PUT", "/api/branding/logo", raw=logo)
    await api(page, "PUT", "/api/branding", {"accent_color": "#0E7490", "body_font": "inter", "name_font": "playfair"})
    await api(page, "PUT", "/api/providers/translation", {"provider": "simulated", "settings": {"delay_ms": 120}})
    downtown = await api(page, "POST", "/api/campuses", {"slug": "downtown", "name": "Downtown", "languages": LANGS})
    northside = await api(page, "POST", "/api/campuses", {"slug": "northside", "name": "Northside", "languages": LANGS[:8]})
    for campus in (downtown, northside):
        for name, weekday, start, end in (("Sunday 9 AM", 6, "09:00", "10:30"), ("Sunday 11 AM", 6, "11:00", "12:30"), ("Wednesday Night", 2, "19:00", "20:30")):
            await api(page, "POST", "/api/schedules", {"campus_id": campus["id"], "name": name, "weekday": weekday,
                                                       "start_time": start, "end_time": end, "early_access_minutes": 10})
    from datetime import datetime, timedelta, timezone

    soon = datetime.now(timezone.utc) + timedelta(minutes=25, seconds=30)
    await api(page, "POST", "/api/events", {"campus_id": northside["id"], "name": "Night of Worship", "kind": "special",
                                            "start_at": soon.isoformat(), "end_at": (soon + timedelta(hours=2)).isoformat()})
    sender = await api(page, "POST", "/api/senders", {"campus_id": downtown["id"], "name": "Downtown booth PC"})
    await api(page, "POST", f"/api/campuses/{downtown['id']}/start", {"duration_minutes": 90, "name": "Sunday Worship"})
    await ctx.storage_state(path="/tmp/onevoice-demo-admin.json")
    await ctx.close()
    return sender["token"], downtown["slug"]


def wait_published(slug: str, phase: str | None = None, timeout: float = 30) -> None:
    """Wait until the worker has published the campus status to the public site."""
    import urllib.request

    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(f"{PUBLIC}/api/public/campus/{slug}", timeout=3) as r:
                if phase is None or json.loads(r.read()).get("phase") == phase:
                    return
        except Exception:
            pass
        time.sleep(0.5)
    sys.exit(f"campus {slug} was not published in time")


async def phone(browser, lang: str | None = None):
    ctx = await browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
    if lang:
        await ctx.add_init_script(f"localStorage.setItem('cc.lang', {json.dumps(lang)})")
    return ctx, await ctx.new_page()


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome")
        token, slug = await admin_flow(browser)

        sim = subprocess.Popen([sys.executable, str(ROOT / "tools" / "simulate_sender.py"), "--url", INGEST, "--token", token],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            wait_published(slug, "live")
            wait_published("northside", "upcoming")
            # Phone: welcome / language choice.
            ctx, page = await phone(browser)
            await page.goto(f"{PUBLIC}/{slug}")
            await page.get_by_role("heading", name="Welcome").wait_for()
            await shot(page, "phone-1-welcome")
            await ctx.close()

            # Phones following along in Spanish, Haitian Creole and Arabic (RTL); English shows live partials.
            viewers = []
            for lang in ("es", "ht", "ar", "en"):
                c, pg = await phone(browser, lang)
                await pg.goto(f"{PUBLIC}/{slug}")
                viewers.append((lang, c, pg))
            await asyncio.sleep(40)  # let captions accumulate
            for lang, c, pg in viewers:
                await shot(pg, f"phone-2-live-{lang}")
                await c.close()

            # Countdown at the other campus.
            ctx, page = await phone(browser, "es")
            await page.goto(f"{PUBLIC}/northside")
            await page.wait_for_timeout(3000)
            await shot(page, "phone-3-countdown-es")
            await ctx.close()

            # Admin dashboard pages.
            ctx = await browser.new_context(viewport={"width": 1360, "height": 900}, device_scale_factor=1.5,
                                            storage_state="/tmp/onevoice-demo-admin.json")
            page = await ctx.new_page()
            for c2, pg2 in [await phone(browser, "es") for _ in range(3)]:  # some viewers for the overview
                await pg2.goto(f"{PUBLIC}/{slug}")
            await page.goto(f"{ADMIN}/")
            await page.wait_for_selector("text=Live overview")
            await asyncio.sleep(8)
            await shot(page, "admin-1-overview")
            for path, name, wait in (("/branding", "admin-2-branding", "Name, colors and fonts"),
                                     ("/schedule", "admin-3-services", "Services"),
                                     ("/qr", "admin-4-qr-codes", "QR codes"),
                                     ("/languages", "admin-5-languages", "Languages"),
                                     ("/updates", "admin-6-updates", "Updates")):
                await page.goto(f"{ADMIN}{path}")
                await page.wait_for_selector(f"text={wait}")
                await asyncio.sleep(1.5)
                await shot(page, name)
            await ctx.close()
        finally:
            sim.terminate()

        # Desktop sender app (its UI rendered in preview mode with sample data).
        ctx = await browser.new_context(viewport={"width": 1000, "height": 760}, device_scale_factor=2)
        page = await ctx.new_page()
        server = subprocess.Popen([sys.executable, "-m", "http.server", "28090", "--bind", "127.0.0.1"], cwd=SENDER_UI,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            time.sleep(1)
            await page.goto("http://127.0.0.1:28090/index.html")
            await page.wait_for_selector("text=Stop streaming")
            await asyncio.sleep(1.5)
            await shot(page, "sender-app")
        finally:
            server.terminate()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
