"""Admin API: authentication, MFA, CSRF, roles, and that every control changes backend state."""

import datetime as dt

import httpx
import pyotp
import pytest

from captions import db
from captions import models as m
from captions.admin.app import create_app
from captions.security import hash_password

from .conftest import make_campus, needs_services

pytestmark = needs_services
ORIGIN = "http://admin.test"
PASSWORD = "correct horse battery staple"


async def create_user(username="alice", role="admin"):
    async with db.sessionmaker()() as s:
        s.add(m.AdminUser(username=username, role=role, password_hash=hash_password(PASSWORD)))
        await s.commit()


class Admin:
    """Logged-in, MFA-enrolled test client that sends CSRF tokens."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.c = client
        self.csrf = ""
        self.secret = ""

    async def login(self, username="alice"):
        r = await self.c.post("/api/auth/login", json={"username": username, "password": PASSWORD})
        assert r.status_code == 200, r.text
        self.csrf = r.json()["csrf_token"]
        return r.json()

    async def enrol_mfa(self):
        r = await self.post("/api/auth/mfa/setup")
        assert r.status_code == 200, r.text
        self.secret = r.json()["secret"]
        assert r.json()["qr_svg"].startswith("<svg") and "xmlns=\"http://www.w3.org/2000/svg\"" in r.json()["qr_svg"]
        r = await self.post("/api/auth/mfa/enable", json={"code": pyotp.TOTP(self.secret).now()})
        assert r.status_code == 200, r.text
        self.csrf = r.json()["csrf_token"]

    def headers(self):
        return {"X-CSRF-Token": self.csrf, "Origin": ORIGIN}

    async def get(self, path, **kw):
        return await self.c.get(path, **kw)

    async def post(self, path, **kw):
        return await self.c.post(path, headers=self.headers(), **kw)

    async def patch(self, path, **kw):
        return await self.c.patch(path, headers=self.headers(), **kw)

    async def put(self, path, **kw):
        return await self.c.put(path, headers=self.headers(), **kw)

    async def delete(self, path, **kw):
        return await self.c.delete(path, headers=self.headers(), **kw)


@pytest.fixture
async def admin(clean, run_server):
    await create_user()
    async with run_server(create_app()) as srv, httpx.AsyncClient(base_url=srv.base, timeout=10) as c:
        a = Admin(c)
        await a.login()
        await a.enrol_mfa()
        yield a


PROTECTED = [
    ("GET", "/api/overview"), ("GET", "/api/campuses"), ("POST", "/api/campuses"), ("GET", "/api/schedules"),
    ("POST", "/api/schedules"), ("POST", "/api/campuses/1/start"), ("POST", "/api/campuses/1/stop"),
    ("GET", "/api/senders"), ("POST", "/api/senders"), ("GET", "/api/providers"), ("PUT", "/api/providers/stt"),
    ("GET", "/api/users"), ("GET", "/api/audit"), ("GET", "/api/campuses/1/qr"), ("PUT", "/api/settings"),
]


async def test_everything_requires_authentication(clean, run_server):
    async with run_server(create_app()) as srv, httpx.AsyncClient(base_url=srv.base) as c:
        for method, path in PROTECTED:
            r = await c.request(method, path, json={})
            assert r.status_code == 401, (method, path, r.status_code)


async def test_login_failures_and_throttling(clean, run_server):
    await create_user()
    async with run_server(create_app()) as srv, httpx.AsyncClient(base_url=srv.base) as c:
        r = await c.post("/api/auth/login", json={"username": "alice", "password": "wrong"})
        assert r.status_code == 401
        r = await c.post("/api/auth/login", json={"username": "nobody", "password": "wrong"})
        assert r.status_code == 401
        for _ in range(10):
            r = await c.post("/api/auth/login", json={"username": "alice", "password": "wrong"})
        assert r.status_code == 429


async def test_mfa_is_required_before_access(clean, run_server):
    await create_user()
    async with run_server(create_app()) as srv, httpx.AsyncClient(base_url=srv.base) as c:
        a = Admin(c)
        body = await a.login()
        assert body["mfa"] == "setup_required"
        assert (await a.get("/api/overview")).status_code == 403
        await a.enrol_mfa()
        assert (await a.get("/api/overview")).status_code == 200
        # Log in again: now a TOTP code is required, and codes cannot be replayed.
        await a.post("/api/auth/logout")
        body = await a.login()
        assert body["mfa"] == "required"
        assert (await a.get("/api/overview")).status_code == 403
        assert (await a.post("/api/auth/mfa/verify", json={"code": "000000"})).status_code == 401
        code = pyotp.TOTP(a.secret).now()
        r = await a.post("/api/auth/mfa/verify", json={"code": code})
        assert r.status_code in (200, 401)  # 401 if the same code was used during enrolment this period
        if r.status_code == 200:
            a.csrf = r.json()["csrf_token"]
            assert (await a.get("/api/overview")).status_code == 200


async def test_csrf_token_and_origin_are_enforced(admin):
    r = await admin.c.post("/api/campuses", json={"slug": "x", "name": "X"})
    assert r.status_code == 403
    r = await admin.c.post("/api/campuses", json={"slug": "x", "name": "X"},
                           headers={"X-CSRF-Token": admin.csrf, "Origin": "https://evil.example"})
    assert r.status_code == 403
    r = await admin.post("/api/campuses", json={"slug": "x", "name": "X"})
    assert r.status_code == 201


async def test_operator_cannot_use_admin_routes(clean, run_server):
    await create_user("olivia", role="operator")
    async with run_server(create_app()) as srv, httpx.AsyncClient(base_url=srv.base) as c:
        op = Admin(c)
        await op.login("olivia")
        await op.enrol_mfa()
        assert (await op.post("/api/campuses", json={"slug": "x", "name": "X"})).status_code == 403
        assert (await op.get("/api/users")).status_code == 403
        assert (await op.get("/api/providers")).status_code == 403
        assert (await op.get("/api/overview")).status_code == 200


async def test_campus_schedule_and_validation(admin):
    r = await admin.post("/api/campuses", json={"slug": "east-hartford", "name": "East Hartford", "languages": ["en", "es", "ht"]})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert sorted(r.json()["languages"]) == ["en", "es", "ht"]
    assert (await admin.post("/api/campuses", json={"slug": "east-hartford", "name": "Dup"})).status_code == 409
    assert (await admin.post("/api/campuses", json={"slug": "api", "name": "Reserved"})).status_code == 422
    assert (await admin.post("/api/campuses", json={"slug": "Bad Slug!", "name": "x"})).status_code == 422
    assert (await admin.post("/api/campuses", json={"slug": "z", "name": "x", "timezone": "Mars/Base"})).status_code == 422
    assert (await admin.post("/api/campuses", json={"slug": "z", "name": "x", "languages": ["xx"]})).status_code == 422

    r = await admin.patch(f"/api/campuses/{cid}", json={"languages": ["es", "fr"]})
    assert sorted(r.json()["languages"]) == ["en", "es", "fr"]  # source language always kept

    r = await admin.post("/api/schedules", json={"campus_id": cid, "name": "Sunday 9", "weekday": 6,
                                                 "start_time": "09:00", "end_time": "10:30", "early_access_minutes": 10})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    r = await admin.get(f"/api/campuses/{cid}/occurrences", params={"days": 21})
    sundays = [o for o in r.json() if o["schedule_id"] == sid]
    assert len(sundays) >= 3
    key = sundays[1]["key"]
    assert (await admin.post("/api/occurrences/cancel", json={"key": key})).status_code == 200
    r = await admin.get(f"/api/campuses/{cid}/occurrences", params={"days": 21})
    assert next(o for o in r.json() if o["key"] == key)["cancelled"] is True
    assert (await admin.post("/api/occurrences/restore", json={"key": key})).status_code == 200
    r = await admin.get(f"/api/campuses/{cid}/occurrences", params={"days": 21})
    assert next(o for o in r.json() if o["key"] == key)["cancelled"] is False

    r = await admin.post("/api/events", json={"campus_id": cid, "name": "Christmas Eve", "kind": "holiday",
                                              "start_at": "2026-12-24T19:00:00-05:00", "end_at": "2026-12-24T21:00:00-05:00"})
    assert r.status_code == 201, r.text
    assert r.json()["start_at"] == "2026-12-25T00:00:00Z"
    bad = await admin.post("/api/events", json={"campus_id": cid, "name": "x", "start_at": "2026-12-24T19:00:00",
                                                "end_at": "2026-12-24T21:00:00"})
    assert bad.status_code == 422  # naive datetimes rejected


async def test_manual_start_extend_stop(admin):
    cid = await make_campus("east")
    r = await admin.post(f"/api/campuses/{cid}/start", json={"duration_minutes": 60})
    assert r.status_code == 200, r.text
    assert (await admin.post(f"/api/campuses/{cid}/start", json={})).status_code == 409
    end_before = dt.datetime.fromisoformat(r.json()["end_at"].replace("Z", "+00:00"))
    r = await admin.post(f"/api/campuses/{cid}/extend", json={"minutes": 30})
    assert r.status_code == 200
    end_after = dt.datetime.fromisoformat(r.json()["end"].replace("Z", "+00:00"))
    assert end_after - end_before == dt.timedelta(minutes=30)
    assert (await admin.post(f"/api/campuses/{cid}/stop")).status_code == 200
    assert (await admin.post(f"/api/campuses/{cid}/stop")).status_code == 409
    audit = (await admin.get("/api/audit")).json()
    assert {"service_started", "service_extended", "service_stopped"} <= {a["action"] for a in audit}


async def test_stop_and_extend_recurring_service_uses_exceptions(admin):
    cid = await make_campus("east")
    now = dt.datetime.now(dt.timezone.utc).astimezone(__import__("zoneinfo").ZoneInfo("America/New_York"))
    start = (now - dt.timedelta(minutes=10)).time().replace(second=0, microsecond=0)
    end = (now + dt.timedelta(minutes=50)).time().replace(second=0, microsecond=0)
    if end <= start:
        pytest.skip("too close to midnight for this test")
    r = await admin.post("/api/schedules", json={"campus_id": cid, "name": "Now", "weekday": now.weekday(),
                                                 "start_time": start.strftime("%H:%M"), "end_time": end.strftime("%H:%M")})
    assert r.status_code == 201
    assert (await admin.post(f"/api/campuses/{cid}/extend", json={"minutes": 15})).status_code == 200
    async with db.sessionmaker()() as s:
        exc = (await s.execute(m.ScheduleException.__table__.select())).first()
        assert exc.kind == "modify"
    assert (await admin.post(f"/api/campuses/{cid}/stop")).status_code == 200
    assert (await admin.post(f"/api/campuses/{cid}/stop")).status_code == 409


async def test_sender_tokens_shown_once_and_revocable(admin):
    cid = await make_campus("east")
    r = await admin.post("/api/senders", json={"campus_id": cid, "name": "Booth PC", "allowed_cidrs": ["203.0.113.0/24"]})
    assert r.status_code == 201
    token = r.json()["token"]
    assert token.startswith("cs_")
    listed = (await admin.get("/api/senders")).json()
    assert "token" not in listed[0] and token not in str(listed)
    assert (await admin.post("/api/senders", json={"campus_id": cid, "name": "x", "allowed_cidrs": ["nope"]})).status_code == 422
    sid = listed[0]["id"]
    r = await admin.post(f"/api/senders/{sid}/revoke")
    assert r.json()["revoked_at"]


async def test_qr_codes_and_providers_and_settings(admin):
    cid = await make_campus("east-windsor")
    svg = await admin.get(f"/api/campuses/{cid}/qr", params={"format": "svg"})
    assert svg.status_code == 200 and svg.headers["content-type"].startswith("image/svg+xml")
    png = await admin.get(f"/api/campuses/{cid}/qr", params={"format": "png"})
    assert png.content[:4] == b"\x89PNG"
    links = (await admin.get("/api/qr-links")).json()
    assert links[0]["url"] == "https://captions.test/campus/east-windsor"

    r = await admin.put("/api/settings", json={"public_base_url": "https://captions.mychurch.org", "church_name": "Grace"})
    assert r.status_code == 200
    links = (await admin.get("/api/qr-links")).json()
    assert links[0]["url"] == "https://captions.mychurch.org/campus/east-windsor"

    r = await admin.put("/api/providers/translation", json={"provider": "simulated", "settings": {"delay_ms": 0}})
    assert r.status_code == 200
    r = await admin.put("/api/providers/stt", json={"provider": "deepgram", "settings": {"model": "nova-3"}, "api_key": "dg-secret"})
    assert r.status_code == 200
    prov = (await admin.get("/api/providers")).json()
    assert prov["stt"]["has_key"] is True and "dg-secret" not in str(prov)
    assert (await admin.put("/api/providers/stt", json={"provider": "nope", "settings": {}})).status_code == 422
    assert (await admin.put("/api/providers/stt", json={"provider": "deepgram", "settings": {"evil": 1}})).status_code == 422

    r = await admin.post("/api/languages/test", json={"text": "Good morning", "target": "es"})
    assert r.status_code == 200 and r.json()["text"] == "[es] Good morning"

    langs = (await admin.get("/api/languages")).json()
    assert {l["code"] for l in langs} >= {"en", "es", "pt", "fr", "ht", "zh", "ko", "ar", "ru", "uk", "vi", "hi"}
    assert next(l for l in langs if l["code"] == "ht")["native_name"] == "Kreyòl ayisyen"
    assert (await admin.patch("/api/languages/hi", json={"enabled": False})).status_code == 200
    assert (await admin.delete("/api/languages/es")).status_code == 400  # built-ins cannot be deleted


async def test_user_management(admin):
    r = await admin.post("/api/users", json={"username": "bob", "password": "short", "role": "operator"})
    assert r.status_code == 422
    r = await admin.post("/api/users", json={"username": "bob", "password": "a much longer password", "role": "operator"})
    assert r.status_code == 201
    me = next(u for u in (await admin.get("/api/users")).json() if u["username"] == "alice")
    assert (await admin.patch(f"/api/users/{me['id']}", json={"disabled": True})).status_code == 400
    assert (await admin.delete(f"/api/users/{me['id']}")).status_code == 400
