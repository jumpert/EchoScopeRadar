import ssl

import aiohttp
import trustme
from aiohttp.test_utils import TestClient, TestServer
from conftest import demo_config
from cryptography.fernet import Fernet

from echoscope.application.engine import Radar
from echoscope.bootstrap import registry
from echoscope.presentation.accounts import COOKIE, Accounts, set_password
from echoscope.presentation.web import Workspace, create_app


async def test_https_accounts_isolate_credentials_and_alert_reviews(tmp_path, monkeypatch):
    monkeypatch.setenv("ECHOSCOPE_YOUTUBE_KEY", "shared-environment-must-not-be-visible")
    password = "a local test password"
    for name in ("alice", "bob"):
        set_password(tmp_path, name, password)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    certificate = trustme.CA()
    certificate.issue_cert("127.0.0.1").configure_cert(tls)
    trust = ssl.create_default_context()
    certificate.configure_trust(trust)
    master = Fernet.generate_key()
    accounts = Accounts(tmp_path, "", master, Workspace)
    app = create_app(None, accounts=accounts)
    server = TestServer(app)
    await server.start_server(ssl=tls)
    async with TestClient(server, cookie_jar=aiohttp.DummyCookieJar()) as client:
        accounts.origin = str(client.make_url("/")).rstrip("/")
        origin = {"Origin": accounts.origin}
        assert (await client.get("/api/bootstrap", ssl=trust)).status == 401

        async def sign_in(username):
            response = await client.post(
                "/api/login",
                json={"username": username, "password": password},
                headers=origin,
                ssl=trust,
            )
            assert response.status == 200
            cookie = response.cookies[COOKIE]
            assert cookie["secure"] and cookie["httponly"] and cookie["samesite"] == "Strict"
            options = {"cookies": {COOKIE: cookie.value}, "ssl": trust}
            bootstrap = await (await client.get("/api/bootstrap", **options)).json()
            assert bootstrap["username"] == username
            return bootstrap, options, origin | {"X-EchoScope-Token": bootstrap["token"]}

        alice, a, a_headers = await sign_in("alice")
        bob, b, b_headers = await sign_in("bob")
        config = demo_config()
        alice_state = accounts.workspaces["alice"]
        await alice_state.service.store.configure(config)
        alice_state.config = config
        await Radar(alice_state.service.store, registry()).run_once("comentarios")
        alice_data = await client.post("/api/data-query", json={}, headers=a_headers, **a)
        assert (await alice_data.json())["rows"]
        bob_data = await client.post("/api/data-query", json={}, headers=b_headers, **b)
        assert (await bob_data.json())["rows"] == []
        bob_export = await client.post(
            "/api/data-export", json={"format": "csv"}, headers=b_headers, **b
        )
        assert len((await bob_export.text(encoding="utf-8-sig")).splitlines()) == 1
        assert not any(provider["available"] for provider in alice["credentials"]["providers"])
        assert not bob["credentials"]["entries"]
        payload = {"provider": "youtube", "name": "Institucional", "value": "fake-youtube-secret"}
        assert (
            await client.post("/api/credential-add", json=payload, headers=a_headers, **b)
        ).status == 403
        result = await client.post("/api/credential-add", json=payload, headers=a_headers, **a)
        assert result.status == 200 and "fake-youtube-secret" not in await result.text()
        for provider, label in [("openai", None), ("other", "Proveedor institucional")]:
            result = await client.post(
                "/api/credential-add",
                json={
                    "provider": provider,
                    "provider_label": label,
                    "name": "Ensayo",
                    "value": "fake-future-secret",
                },
                headers=a_headers,
                **a,
            )
            assert result.status == 200 and "fake-future-secret" not in await result.text()
            vault = await result.json()
            entry = vault["entries"][-1]
            assert not entry["active"]
            assert not next(p for p in vault["providers"] if p["id"] == entry["provider"])[
                "integrated"
            ]
            assert (
                await client.post(
                    "/api/credential-use", json={"value": entry["id"]}, headers=a_headers, **a
                )
            ).status == 400
        assert not (await (await client.get("/api/bootstrap", **b)).json())["credentials"][
            "entries"
        ]
        secret_record = await accounts.workspaces["alice"].service.store.desktop_setting(
            "credential_vault"
        )
        assert "fake-youtube-secret" not in secret_record
        assert "fake-future-secret" not in secret_record
        assert not accounts.workspaces["bob"].secrets
        key = "1" * 64
        assert (
            await client.post(
                "/api/alert-review", json={"keys": [key], "state": "threat"}, headers=a_headers, **a
            )
        ).status == 400
        await accounts.workspaces["alice"].service.store.set_alert_reviews([key], "threat")
        assert await accounts.workspaces["alice"].service.store.alert_reviews([key]) == {
            key: "threat"
        }
        assert await accounts.workspaces["bob"].service.store.alert_reviews([key]) == {}
        assert (await client.post("/api/logout", json={}, headers=b_headers, **b)).status == 200
        assert (await client.get("/api/bootstrap", **b)).status == 401

    restarted = Accounts(tmp_path, "https://127.0.0.1", master, Workspace)
    try:
        state = await restarted.workspace("alice")
        assert state.secrets["ECHOSCOPE_YOUTUBE_KEY"] == "fake-youtube-secret"
        assert list(state.vault.custom().values()) == ["Proveedor institucional"]
    finally:
        for state in restarted.workspaces.values():
            await state.service.close()
