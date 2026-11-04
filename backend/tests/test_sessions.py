from types import SimpleNamespace

from fastapi.testclient import TestClient

from steward import auth
from steward.app import create_app

SAME_ORIGIN = {"X-CSRF-Protection": "1", "Origin": "https://testserver"}


def login(client, settings):
    return client.post(
        "/api/auth/login", headers={**SAME_ORIGIN, "Authorization": f"Bearer {settings.operator_token}"}
    )


def test_session_survives_new_app_and_logout_revokes_cookie(service):
    settings = service.settings
    with TestClient(create_app(settings, service), base_url="https://testserver") as first:
        response = login(first, settings)
        assert response.status_code == 200
        header = response.headers["set-cookie"].lower()
        assert "httponly" in header and "secure" in header and "samesite=strict" in header
        assert "max-age=14400" in header and "domain=" not in header
        raw = first.cookies.get(auth.cookie_name(settings))
        assert raw and settings.operator_token not in raw
        assert settings.operator_token not in response.text
        records = service.store.list("session-")
        assert len(records) == 1 and raw not in str(records) and settings.operator_token not in str(records)
        assert first.get("/api/dashboard").status_code == 200
    # Simulate browser refresh and a new API process, with no Authorization header.
    with TestClient(create_app(settings, service), base_url="https://testserver") as refreshed:
        refreshed.cookies.set(auth.cookie_name(settings), raw)
        assert refreshed.get("/api/auth/session").status_code == 200
        assert refreshed.get("/api/dashboard").status_code == 200
        response = refreshed.post("/api/auth/logout", headers=SAME_ORIGIN)
        assert response.status_code == 200 and "max-age=0" in response.headers["set-cookie"].lower()
        assert refreshed.get("/api/dashboard").status_code == 401
        refreshed.cookies.set(auth.cookie_name(settings), raw)
        assert refreshed.get("/api/dashboard").status_code == 401


def test_expired_and_forged_sessions_are_rejected(service, monkeypatch):
    with TestClient(create_app(service.settings, service), base_url="https://testserver") as client:
        assert login(client, service.settings).status_code == 200
        raw = client.cookies.get(auth.cookie_name(service.settings))
        _, record = service.store.get(auth.session_key(raw))
        monkeypatch.setattr(auth, "time", SimpleNamespace(time=lambda: record["expires_at"]))
        assert client.get("/api/dashboard").status_code == 401
        client.cookies.set(auth.cookie_name(service.settings), "forged-session")
        assert client.get("/api/dashboard").status_code == 401


def test_cookie_writes_reject_cross_site_and_missing_csrf_header(service):
    with TestClient(create_app(service.settings, service), base_url="https://testserver") as client:
        assert login(client, service.settings).status_code == 200
        assert client.post("/api/candidates/missing/action", json={"days": 7}).status_code == 403
        assert (
            client.post(
                "/api/auth/logout", headers={"X-CSRF-Protection": "1", "Origin": "https://other.example"}
            ).status_code
            == 403
        )
        assert client.get("/api/dashboard").status_code == 200
        # With the correct header the request reaches the business handler.
        assert (
            client.post("/api/candidates/missing/action", headers=SAME_ORIGIN, json={"days": 7}).status_code
            == 422
        )
        assert (
            client.post(
                "/api/auth/login", headers={"Authorization": f"Bearer {service.settings.operator_token}"}
            ).status_code
            == 403
        )


def test_wrong_token_cannot_log_in_and_unknown_logout_does_not_create_rows(service):
    with TestClient(create_app(service.settings, service), base_url="https://testserver") as client:
        assert (
            client.post(
                "/api/auth/login", headers={**SAME_ORIGIN, "Authorization": "Bearer incorrect"}
            ).status_code
            == 401
        )
        client.cookies.set(auth.cookie_name(service.settings), "unknown-session")
        assert client.post("/api/auth/logout", headers=SAME_ORIGIN).status_code == 200
        assert service.store.list("session-") == []


def test_operator_token_rotation_invalidates_existing_sessions(service):
    with TestClient(create_app(service.settings, service), base_url="https://testserver") as client:
        login(client, service.settings)
        raw = client.cookies.get(auth.cookie_name(service.settings))
    rotated = service.settings.model_copy(update={"operator_token": "r" * 32})
    with TestClient(create_app(rotated, service), base_url="https://testserver") as client:
        client.cookies.set(auth.cookie_name(rotated), raw)
        assert client.get("/api/auth/session").status_code == 401
