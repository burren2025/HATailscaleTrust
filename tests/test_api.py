"""Tests for OAuth handling and device parsing."""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from custom_components.tailscale_trust.api import (
    TailscaleTrustAuthenticationError,
    TailscaleTrustClient,
    parse_device,
)
from custom_components.tailscale_trust.const import OAUTH_SCOPE


class FakeResponse:
    """Small aiohttp response substitute."""

    def __init__(self, status: int, payload: Any = None) -> None:
        self.status = status
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    async def json(self) -> Any:
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
            FakeResponse(200, {"devices": [_device_payload()]}),
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
    assert session.get_calls[-1]["params"] == {"fields": "all"}


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
    assert len(session.get_calls) == 2
    assert session.get_calls[1]["headers"]["Authorization"] == "Bearer fresh"


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
