"""First-run setup: setup code required, single first admin, completion flag, provider key check."""

import httpx

from captions.admin.app import create_app
from captions.admin.setup_routes import SETUP_CODE_KEY, _normalize
from captions.security import sha256_hex

from .conftest import needs_services
from .test_admin_api import ORIGIN, Admin, create_user

pytestmark = needs_services
CODE = "ABCD-EFGH"


async def test_first_admin_requires_setup_code_and_happens_once(clean, redis_client, run_server):
    async with run_server(create_app()) as srv, httpx.AsyncClient(base_url=srv.base, timeout=10) as c:
        st = (await c.get("/api/setup/status")).json()
        assert st == {"needs_admin": True, "setup_complete": False}
        assert await redis_client.exists(SETUP_CODE_KEY)  # generated and logged for the operator
        await redis_client.set(SETUP_CODE_KEY, sha256_hex(_normalize(CODE)))

        body = {"username": "pastor", "password": "a long enough password", "setup_code": "WRONG-CODE"}
        assert (await c.post("/api/setup/admin", json=body)).status_code == 403
        body["setup_code"] = "abcd efgh"  # case and separators are forgiven
        r = await c.post("/api/setup/admin", json=body)
        assert r.status_code == 200, r.text
        assert r.json()["mfa"] == "setup_required" and r.json()["user"]["role"] == "admin"
        assert not await redis_client.exists(SETUP_CODE_KEY)

        # Nobody can create another "first" admin.
        again = await c.post("/api/setup/admin", json={**body, "username": "intruder"})
        assert again.status_code in (403, 409)

        # The new session continues straight into MFA enrolment, then the wizard.
        a = Admin(c)
        a.csrf = r.json()["csrf_token"]
        await a.enrol_mfa()
        st = (await c.get("/api/setup/status")).json()
        assert st == {"needs_admin": False, "setup_complete": False}
        await a.put("/api/providers/stt", json={"provider": "simulated", "settings": {}})
        t = (await a.post("/api/setup/test-stt")).json()
        assert t["ok"] is True and t["provider"] == "simulated"
        assert (await a.post("/api/setup/complete")).status_code == 200
        assert (await c.get("/api/setup/status")).json()["setup_complete"] is True


async def test_setup_code_attempts_are_limited(clean, redis_client, run_server):
    async with run_server(create_app()) as srv, httpx.AsyncClient(base_url=srv.base, timeout=10) as c:
        await c.get("/api/setup/status")
        body = {"username": "pastor", "password": "a long enough password", "setup_code": "NOPE-NOPE"}
        codes = [(await c.post("/api/setup/admin", json=body)).status_code for _ in range(12)]
        assert codes[0] == 403 and codes[-1] == 429


async def test_existing_install_with_providers_counts_as_set_up(clean, run_server):
    await create_user()
    async with run_server(create_app()) as srv, httpx.AsyncClient(base_url=srv.base, timeout=10) as c:
        a = Admin(c)
        await a.login()
        await a.enrol_mfa()
        assert (await c.get("/api/setup/status")).json()["setup_complete"] is False
        await a.put("/api/providers/stt", json={"provider": "simulated", "settings": {}})
        await a.put("/api/providers/translation", json={"provider": "simulated", "settings": {}})
        assert (await c.get("/api/setup/status")).json()["setup_complete"] is True
        # Completing setup is an admin action protected like everything else.
        assert (await c.post("/api/setup/complete", headers={"Origin": ORIGIN})).status_code == 403


