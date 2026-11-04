"""Opaque, revocable operator sessions backed by the application's durable store."""

import hashlib
import secrets
import time

from fastapi import HTTPException, Request


def cookie_name(settings):
    return "__Host-steward_session" if settings.session_cookie_secure else "steward_session"


def token_matches(authorization, settings):
    return bool(authorization and secrets.compare_digest(authorization, f"Bearer {settings.operator_token}"))


def browser_write(request: Request, settings):
    """SameSite plus a non-simple request header prevents ambient-cookie CSRF."""
    origin = request.headers.get("origin")
    scheme = "https" if settings.session_cookie_secure else request.url.scheme
    expected = f"{scheme}://{request.url.netloc}"
    if (
        request.headers.get("x-csrf-protection") != "1"
        or request.headers.get("sec-fetch-site") == "cross-site"
        or (origin is not None and origin != expected)
    ):
        raise HTTPException(403, "Use this application's sign-in page to perform this action")


def session_key(raw):
    return "session-" + hashlib.sha256(raw.encode()).hexdigest()


def read_session(request, settings):
    raw = request.cookies.get(cookie_name(settings), "")
    if not raw or len(raw) > 128:
        return None
    _, record = request.app.state.service.store.get(session_key(raw))
    if (
        not record
        or record.get("revoked")
        or record.get("expires_at", 0) <= int(time.time())
        or record.get("operator_fingerprint") != hashlib.sha256(settings.operator_token.encode()).hexdigest()
    ):
        return None
    return record


def create_session(request, response, settings):
    raw = secrets.token_urlsafe(32)
    created = int(time.time())
    record = {
        "created_at": created,
        "expires_at": created + settings.session_ttl_seconds,
        "revoked": False,
        "operator_fingerprint": hashlib.sha256(settings.operator_token.encode()).hexdigest(),
    }
    request.app.state.service.store.put(session_key(raw), 0, record)
    response.set_cookie(
        cookie_name(settings),
        raw,
        max_age=settings.session_ttl_seconds,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="strict",
    )
    return record["expires_at"]


def revoke_session(request, response, settings):
    raw = request.cookies.get(cookie_name(settings), "")
    if raw and len(raw) <= 128:

        def revoke(record):
            return {**record, "revoked": True} if record else {"revoked": True, "expires_at": 0}

        service = request.app.state.service
        _, existing = service.store.get(session_key(raw))
        if existing:
            service.mutate(session_key(raw), revoke)
    response.delete_cookie(
        cookie_name(settings),
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="strict",
    )
