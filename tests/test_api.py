"""Tests for OAuth handling and device parsing."""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from custom_components.tailscale_trust.api import (
    TailscaleTrustAuthenticationError,
    TailscaleTrustClient,
    TailscaleTrustConnectionError,
    TailscaleTrustPermissionError,
    TailscaleTrustRateLimitError,
    parse_device,
)
from custom_components.tailscale_trust.const import (
    OAUTH_SCOPE,
    ROUTE_REQUEST_CONCURRENCY,
)


class FakeResponse:
    """Small aiohttp response substitute."""

    def __init__(
        self,
        status: int,
        payload: Any = None,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self.payload = payload
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    async def json(self) -> Any:
        if isinstance(self.payload, BaseException):
            raise self.payload
        return self.payload


class FakeSession:
    """Queue deterministic OAuth and API responses."""

    def __init__(self, *, posts: list[FakeResponse], gets: list[FakeResponse]) -> None:
        self.posts = deque(posts)
        self.gets = deque(gets)
        self.post_calls: list[dict[str, Any]] = []
        self.get_calls: list[dict[str, Any]] = []

    async def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.post_calls.append({"url": url, **kwargs})
        return self.posts.popleft()

    async def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.get_calls.append({"url": url, **kwargs})
        return self.gets.popleft()


def _device_payload(**updates: Any) -> dict[str, Any]:
    payload = {
        "nodeId": "nNODE123",
        "id": "12345",
        "name": "tablet.example.ts.net",
        "hostname": "tablet",
        "addresses": ["100.64.0.10"],
        "connectedToControl": True,
        "lastSeen": None,
        "clientConnectivity": {
            "clientSupports": {
                "ipv6": True,
                "pcp": False,
                "pmp": False,
                "udp": True,
                "upnp": False,
            }
        },
    }
    payload.update(updates)
    return payload


def _routes_payload(
    *, advertised: list[str] | None = None, enabled: list[str] | None = None
) -> dict[str, Any]:
    return {
        "advertisedRoutes": advertised or [],
        "enabledRoutes": enabled or [],
    }


@pytest.mark.asyncio
async def test_token_is_cached_and_refreshed_before_expiry() -> None:
    """One-hour tokens are reused until the early-refresh margin."""
    now = [100.0]
    session = FakeSession(
        posts=[
            FakeResponse(200, {"access_token": "token-1", "expires_in": 3600}),
            FakeResponse(200, {"access_token": "token-2", "expires_in": 3600}),
        ],
        gets=[
            FakeResponse(200, {"devices": [_device_payload()]}),
            FakeResponse(200, _routes_payload()),
            FakeResponse(200, {"devices": [_device_payload()]}),
            FakeResponse(200, _routes_payload()),
            FakeResponse(200, {"devices": [_device_payload()]}),
            FakeResponse(200, _routes_payload()),
        ],
    )
    client = TailscaleTrustClient(
        session,  # type: ignore[arg-type]
        tailnet="example.com",
        client_id="test-client",
        client_secret="test-secret",
        monotonic=lambda: now[0],
    )

    await client.async_list_devices()
    now[0] = 1000
    await client.async_list_devices()
    assert len(session.post_calls) == 1

    now[0] = 3641
    await client.async_list_devices()
    assert len(session.post_calls) == 2
    assert session.post_calls[0]["data"]["scope"] == OAUTH_SCOPE
    assert session.post_calls[0]["data"]["grant_type"] == "client_credentials"
    assert session.get_calls[-1]["headers"]["Authorization"] == "Bearer token-2"
    assert session.get_calls[-2]["params"] == {"fields": "all"}
    assert session.get_calls[-1]["url"].endswith("/device/nNODE123/routes")


@pytest.mark.asyncio
async def test_401_refreshes_token_and_retries_once() -> None:
    """An API authentication failure discards the cached access token."""
    session = FakeSession(
        posts=[
            FakeResponse(200, {"access_token": "stale", "expires_in": 3600}),
            FakeResponse(200, {"access_token": "fresh", "expires_in": 3600}),
        ],
        gets=[
            FakeResponse(401),
            FakeResponse(200, {"devices": [_device_payload()]}),
            FakeResponse(200, _routes_payload()),
        ],
    )
    client = TailscaleTrustClient(
        session,  # type: ignore[arg-type]
        tailnet="-",
        client_id="test-client",
        client_secret="test-secret",
    )

    devices = await client.async_list_devices()

    assert list(devices) == ["nNODE123"]
    assert len(session.post_calls) == 2
    assert len(session.get_calls) == 3
    assert session.get_calls[1]["headers"]["Authorization"] == "Bearer fresh"


@pytest.mark.asyncio
async def test_routes_are_read_with_the_narrow_route_scope() -> None:
    """Advertised and enabled routes are attached to their immutable node."""
    session = FakeSession(
        posts=[FakeResponse(200, {"access_token": "token", "expires_in": 3600})],
        gets=[
            FakeResponse(200, {"devices": [_device_payload()]}),
            FakeResponse(
                200,
                _routes_payload(
                    advertised=["0.0.0.0/0", "::/0", "192.168.50.0/24"],
                    enabled=["0.0.0.0/0", "::/0"],
                ),
            ),
        ],
    )
    client = TailscaleTrustClient(
        session,  # type: ignore[arg-type]
        tailnet="example.com",
        client_id="test-client",
        client_secret="test-secret",
    )

    device = (await client.async_list_devices())["nNODE123"]

    assert session.post_calls[0]["data"]["scope"] == (
        "devices:core:read devices:routes:read"
    )
    assert device.routes_available is True
    assert device.advertised_routes == (
        "0.0.0.0/0",
        "::/0",
        "192.168.50.0/24",
    )
    assert device.enabled_routes == ("0.0.0.0/0", "::/0")
    assert device.advertises_exit_node is True
    assert device.exit_node_enabled is True
    assert device.advertises_subnet_routes is True
    assert device.routes_awaiting_approval == ("192.168.50.0/24",)


@pytest.mark.asyncio
async def test_route_401_refreshes_token_and_retries_once() -> None:
    """An authentication failure on the routes endpoint refreshes the token."""
    session = FakeSession(
        posts=[
            FakeResponse(200, {"access_token": "stale", "expires_in": 3600}),
            FakeResponse(200, {"access_token": "fresh", "expires_in": 3600}),
        ],
        gets=[
            FakeResponse(200, {"devices": [_device_payload()]}),
            FakeResponse(401),
            FakeResponse(200, {"devices": [_device_payload()]}),
            FakeResponse(200, _routes_payload()),
        ],
    )
    client = TailscaleTrustClient(
        session,  # type: ignore[arg-type]
        tailnet="example.com",
        client_id="test-client",
        client_secret="test-secret",
    )

    await client.async_list_devices()

    assert len(session.post_calls) == 2
    assert session.get_calls[-1]["headers"]["Authorization"] == "Bearer fresh"


@pytest.mark.asyncio
async def test_missing_route_scope_is_a_permission_failure() -> None:
    """A route permission denial starts Home Assistant reauthentication."""
    session = FakeSession(
        posts=[FakeResponse(200, {"access_token": "token", "expires_in": 3600})],
        gets=[
            FakeResponse(200, {"devices": [_device_payload()]}),
            FakeResponse(403),
        ],
    )
    client = TailscaleTrustClient(
        session,  # type: ignore[arg-type]
        tailnet="example.com",
        client_id="test-client",
        client_secret="test-secret",
    )

    with pytest.raises(TailscaleTrustPermissionError):
        await client.async_list_devices()


@pytest.mark.asyncio
async def test_revoked_oauth_client_is_authentication_failure() -> None:
    """A revoked client fails without leaking the server response."""
    session = FakeSession(posts=[FakeResponse(401, {"secret": "echo"})], gets=[])
    client = TailscaleTrustClient(
        session,  # type: ignore[arg-type]
        tailnet="example.com",
        client_id="test-client",
        client_secret="never-log-this",
    )

    with pytest.raises(TailscaleTrustAuthenticationError) as err:
        await client.async_list_devices()

    assert "never-log-this" not in str(err.value)
    assert "echo" not in str(err.value)


@pytest.mark.asyncio
async def test_oauth_invalid_scope_is_a_permission_failure() -> None:
    """OAuth invalid_scope is distinguished from a bad client secret."""
    session = FakeSession(
        posts=[FakeResponse(400, {"error": "invalid_scope"})], gets=[]
    )
    client = TailscaleTrustClient(
        session,  # type: ignore[arg-type]
        tailnet="example.com",
        client_id="test-client",
        client_secret="test-secret",
    )

    with pytest.raises(TailscaleTrustPermissionError):
        await client.async_list_devices()


def test_online_uses_authoritative_connectivity() -> None:
    """connectedToControl wins even when lastSeen is stale."""
    device = parse_device(
        _device_payload(
            connectedToControl=False,
            lastSeen="2026-01-01T00:00:00Z",
        ),
        now=datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
    )

    assert device.online is False
    assert device.online_source == "connected_to_control"


def test_online_fallback_uses_recent_last_seen() -> None:
    """Older API responses get a documented five-minute approximation."""
    reference = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    online = parse_device(
        _device_payload(
            connectedToControl="missing",
            lastSeen=(reference - timedelta(minutes=4)).isoformat(),
        ),
        now=reference,
    )
    offline = parse_device(
        _device_payload(
            connectedToControl="missing",
            lastSeen=(reference - timedelta(minutes=6)).isoformat(),
        ),
        now=reference,
    )

    assert online.online is True
    assert offline.online is False
    assert online.online_source == "recent_last_seen_fallback"


def test_node_id_is_preferred_over_legacy_id() -> None:
    """The immutable node ID is the stable entity identity."""
    assert parse_device(_device_payload()).node_id == "nNODE123"


@pytest.mark.asyncio
async def test_device_rate_limit_uses_retry_after() -> None:
    """A device-list 429 tells the coordinator when it may safely retry."""
    session = FakeSession(
        posts=[FakeResponse(200, {"access_token": "token", "expires_in": 3600})],
        gets=[FakeResponse(429, headers={"Retry-After": "120"})],
    )
    client = TailscaleTrustClient(
        session,  # type: ignore[arg-type]
        tailnet="example.com",
        client_id="test-client",
        client_secret="test-secret",
    )

    with pytest.raises(TailscaleTrustRateLimitError) as err:
        await client.async_list_devices()

    assert err.value.retry_after == 120


@pytest.mark.asyncio
async def test_token_rate_limit_uses_bounded_fallback() -> None:
    """OAuth throttling without Retry-After receives jittered exponential delay."""
    session = FakeSession(posts=[FakeResponse(429)], gets=[])
    client = TailscaleTrustClient(
        session,  # type: ignore[arg-type]
        tailnet="example.com",
        client_id="test-client",
        client_secret="test-secret",
        random_value=lambda: 0.5,
    )

    with pytest.raises(TailscaleTrustRateLimitError) as err:
        await client.async_list_devices()

    assert err.value.retry_after == 300


@pytest.mark.asyncio
async def test_route_rate_limit_preserves_cache_and_defers_routes() -> None:
    """Route throttling retains known state while device polling continues."""
    now = [0.0]
    cached_routes = _routes_payload(
        advertised=["0.0.0.0/0", "::/0"], enabled=["0.0.0.0/0", "::/0"]
    )
    session = FakeSession(
        posts=[FakeResponse(200, {"access_token": "token", "expires_in": 3600})],
        gets=[
            FakeResponse(200, {"devices": [_device_payload()]}),
            FakeResponse(200, cached_routes),
            FakeResponse(200, {"devices": [_device_payload()]}),
            FakeResponse(429, headers={"Retry-After": "600"}),
            FakeResponse(200, {"devices": [_device_payload()]}),
        ],
    )
    client = TailscaleTrustClient(
        session,  # type: ignore[arg-type]
        tailnet="example.com",
        client_id="test-client",
        client_secret="test-secret",
        monotonic=lambda: now[0],
    )

    first = (await client.async_list_devices())["nNODE123"]
    now[0] = 601
    throttled = (await client.async_list_devices())["nNODE123"]
    now[0] = 700
    deferred = (await client.async_list_devices())["nNODE123"]

    assert first.enabled_routes == ("0.0.0.0/0", "::/0")
    assert throttled.enabled_routes == first.enabled_routes
    assert deferred.enabled_routes == first.enabled_routes
    assert len(session.get_calls) == 5


@pytest.mark.asyncio
async def test_route_requests_have_bounded_concurrency() -> None:
    """Large tailnets never fan out more than the configured route batch."""
    client = TailscaleTrustClient(
        FakeSession(posts=[], gets=[]),  # type: ignore[arg-type]
        tailnet="example.com",
        client_id="test-client",
        client_secret="test-secret",
    )
    active = 0
    maximum = 0

    async def request(token: str, node_id: str):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0)
        active -= 1
        return node_id, 200, _routes_payload(), None

    client._async_routes_request = request  # type: ignore[method-assign]
    results = await client._async_route_requests(
        "token", tuple(f"node-{index}" for index in range(13))
    )

    assert len(results) == 13
    assert maximum == ROUTE_REQUEST_CONCURRENCY


@pytest.mark.asyncio
async def test_one_malformed_device_does_not_fail_update() -> None:
    """A bad record is skipped when the response still has usable devices."""
    session = FakeSession(
        posts=[FakeResponse(200, {"access_token": "token", "expires_in": 3600})],
        gets=[
            FakeResponse(200, {"devices": [{"name": "invalid"}, _device_payload()]}),
            FakeResponse(200, _routes_payload()),
        ],
    )
    client = TailscaleTrustClient(
        session,  # type: ignore[arg-type]
        tailnet="example.com",
        client_id="test-client",
        client_secret="test-secret",
    )

    assert list(await client.async_list_devices()) == ["nNODE123"]


@pytest.mark.asyncio
async def test_all_malformed_devices_fail_update() -> None:
    """A structurally broken response is not mistaken for an empty tailnet."""
    session = FakeSession(
        posts=[FakeResponse(200, {"access_token": "token", "expires_in": 3600})],
        gets=[FakeResponse(200, {"devices": [{"name": "invalid"}]})],
    )
    client = TailscaleTrustClient(
        session,  # type: ignore[arg-type]
        tailnet="example.com",
        client_id="test-client",
        client_secret="test-secret",
    )

    with pytest.raises(TailscaleTrustConnectionError):
        await client.async_list_devices()


def test_retry_after_parser_rejects_invalid_values() -> None:
    """Malformed or non-finite rate headers cannot poison update scheduling."""
    assert TailscaleTrustClient._parse_retry_after("not-a-date") is None
    assert TailscaleTrustClient._parse_retry_after("nan") is None
    assert TailscaleTrustClient._parse_retry_after("999999") == 3600
