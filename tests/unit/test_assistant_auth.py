"""Tests for the HTTP transport authentication (audit finding B4).

The stdio transport needs none of this: the client is the parent process. The
HTTP one binds to loopback, which keeps remote machines out but not the other
processes of the same machine — and the tools read and write files on behalf
of whoever calls them.
"""
import asyncio

import pytest

pytestmark = [pytest.mark.unit]

fastmcp = pytest.importorskip("fastmcp", reason="the optional `mcp` extra is not installed")

from fmu_manipulation_toolbox.assistant.auth import (  # noqa: E402
    GENERATE, TOKEN_ENV_VAR, build_auth_middleware, resolve_token,
)


# --------------------------------------------------------------------------- #
#                              token resolution                                #
# --------------------------------------------------------------------------- #
def test_no_token_by_default(monkeypatch):
    """Authentication is opt-in: enabling the assistant must keep working for
    a user who just points their IDE at the port."""
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)
    assert resolve_token() is None


def test_a_token_can_be_generated(monkeypatch):
    monkeypatch.setenv(TOKEN_ENV_VAR, GENERATE)
    first, second = resolve_token(), resolve_token()

    assert len(first) >= 32
    assert first != second  # a fresh one each time


def test_an_explicit_token_is_used_as_is(monkeypatch):
    monkeypatch.setenv(TOKEN_ENV_VAR, "a-long-enough-secret-value")
    assert resolve_token() == "a-long-enough-secret-value"


@pytest.mark.parametrize("value", ["", "short", "0123456789abcde"])
def test_a_weak_token_is_rejected(monkeypatch, value):
    """A two-character token is worse than none: it gives the illusion of
    protection."""
    monkeypatch.setenv(TOKEN_ENV_VAR, value)
    with pytest.raises(ValueError, match="at least 16 characters"):
        resolve_token()


# --------------------------------------------------------------------------- #
#                                 middleware                                   #
# --------------------------------------------------------------------------- #
TOKEN = "a-long-enough-secret-value"


class _Spy:
    """Minimal ASGI app recording whether it was reached."""

    def __init__(self):
        self.called = False

    async def __call__(self, scope, receive, send):
        self.called = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


def _request(headers, scope_type="http"):
    """Send one request through the middleware; return (status, app_reached)."""
    spy = _Spy()
    app = build_auth_middleware(TOKEN)(spy)
    sent = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request", "body": b""}

    scope = {"type": scope_type, "headers": headers}
    asyncio.run(app(scope, receive, send))
    status = next((m["status"] for m in sent if m["type"] == "http.response.start"), None)
    return status, spy.called


def test_the_right_token_is_accepted():
    status, reached = _request([(b"authorization", f"Bearer {TOKEN}".encode())])
    assert status == 200
    assert reached


def test_a_request_without_a_token_is_rejected():
    status, reached = _request([])
    assert status == 401
    assert not reached


def test_a_wrong_token_is_rejected():
    status, reached = _request([(b"authorization", b"Bearer not-the-right-token")])
    assert status == 401
    assert not reached


def test_a_bare_token_without_the_scheme_is_rejected():
    status, reached = _request([(b"authorization", TOKEN.encode())])
    assert status == 401
    assert not reached


def test_the_rejection_names_the_expected_scheme():
    """A client must be able to tell *why* it was refused."""
    spy = _Spy()
    app = build_auth_middleware(TOKEN)(spy)
    sent = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request", "body": b""}

    asyncio.run(app({"type": "http", "headers": []}, receive, send))

    start = next(m for m in sent if m["type"] == "http.response.start")
    assert (b"www-authenticate", b"Bearer") in start["headers"]
    body = next(m for m in sent if m["type"] == "http.response.body")
    assert b"bearer token" in body["body"].lower()


def test_non_http_scopes_pass_through():
    """Lifespan events are not requests and must not be answered with a 401,
    or the server never starts."""
    status, reached = _request([], scope_type="lifespan")
    assert reached
    assert status != 401


