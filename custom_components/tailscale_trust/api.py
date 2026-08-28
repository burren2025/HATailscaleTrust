"""Minimal asynchronous Tailscale API client with OAuth token management."""

from __future__ import annotations

import asyncio
import math
import random
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Final
from urllib.parse import quote

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import (
    API_BASE_URL,
    EXIT_NODE_ROUTES,
    OAUTH_SCOPE,
    OAUTH_TOKEN_URL,
    ONLINE_FALLBACK_WINDOW,
    RATE_LIMIT_DEFAULT_RETRY,
    RATE_LIMIT_MAX_RETRY,
    ROUTE_REQUEST_CONCURRENCY,
    ROUTE_SCAN_INTERVAL,
    TOKEN_REFRESH_SKEW,
)

REQUEST_TIMEOUT: Final = ClientTimeout(total=20)


class TailscaleTrustError(Exception):
    """Base exception for sanitized integration failures."""


class TailscaleTrustAuthenticationError(TailscaleTrustError):
    """The OAuth client is invalid or revoked."""


class TailscaleTrustPermissionError(TailscaleTrustError):
    """The OAuth client lacks the required permission."""


class TailscaleTrustConnectionError(TailscaleTrustError):
    """The service could not be reached or returned an invalid response."""


class TailscaleTrustRateLimitError(TailscaleTrustConnectionError):
    """Tailscale asked the client to defer its next API request."""

    def __init__(self, retry_after: float) -> None:
        """Initialize a sanitized rate-limit failure."""
        super().__init__("Tailscale API rate limit exceeded")
        self.retry_after = retry_after


@dataclass(frozen=True, slots=True)
class ClientSupports:
    """Protocols reported by Tailscale device connectivity data."""

    ipv6: bool | None = None
    pcp: bool | None = None
    pmp: bool | None = None
    udp: bool | None = None
    upnp: bool | None = None


@dataclass(frozen=True, slots=True)
class TailscaleDevice:
    """Normalized subset of a device returned by the Tailscale API."""

    node_id: str
    legacy_id: str | None
    name: str
    hostname: str
    addresses: tuple[str, ...]
    os: str | None
    client_version: str | None
    expires: datetime | None
    last_seen: datetime | None
    update_available: bool | None
    key_expiry_disabled: bool | None
    connected_to_control: bool | None
    online: bool | None
    online_source: str
    client_supports: ClientSupports
    advertised_routes: tuple[str, ...] = ()
    enabled_routes: tuple[str, ...] = ()
    routes_available: bool = False
    present: bool = True

    @property
    def display_name(self) -> str:
        """Return a concise device name."""
        return (self.name or self.hostname or self.node_id).split(".")[0]

    @property
    def advertises_exit_node(self) -> bool:
        """Return whether both default routes are advertised."""
        return EXIT_NODE_ROUTES.issubset(self.advertised_routes)

    @property
    def exit_node_enabled(self) -> bool:
        """Return whether both default routes are enabled."""
        return EXIT_NODE_ROUTES.issubset(self.enabled_routes)

    @property
    def advertises_subnet_routes(self) -> bool:
        """Return whether at least one non-exit route is advertised."""
        return any(route not in EXIT_NODE_ROUTES for route in self.advertised_routes)

    @property
    def routes_awaiting_approval(self) -> tuple[str, ...]:
        """Return advertised routes which are not enabled."""
        enabled = set(self.enabled_routes)
        return tuple(route for route in self.advertised_routes if route not in enabled)


def _optional_bool(value: Any) -> bool | None:
    """Return a JSON boolean without coercing arbitrary values."""
    return value if isinstance(value, bool) else None


def _optional_string(value: Any) -> str | None:
    """Return a non-empty JSON string."""
    return value if isinstance(value, str) and value else None


def _string_tuple(value: Any) -> tuple[str, ...]:
    """Return a stable tuple containing only non-empty strings."""
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


def _timestamp(value: Any) -> datetime | None:
    """Parse an RFC 3339 timestamp from the API."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_device(
    raw: Mapping[str, Any], *, now: datetime | None = None
) -> TailscaleDevice:
    """Normalize a device, preserving whether connectivity was authoritative."""
    node_id = _optional_string(raw.get("nodeId"))
    legacy_id = _optional_string(raw.get("id"))
    immutable_id = node_id or legacy_id
    if immutable_id is None:
        raise TailscaleTrustConnectionError("Device response omitted an identifier")

    connected = _optional_bool(raw.get("connectedToControl"))
    last_seen = _timestamp(raw.get("lastSeen"))
    if connected is not None:
        online = connected
        online_source = "connected_to_control"
    elif last_seen is not None:
        reference = now or datetime.now(UTC)
        online = reference - last_seen <= ONLINE_FALLBACK_WINDOW
        online_source = "recent_last_seen_fallback"
    else:
        online = None
        online_source = "unknown"

    connectivity = raw.get("clientConnectivity")
    supports_raw: Mapping[str, Any] = {}
    if isinstance(connectivity, Mapping):
        candidate = connectivity.get("clientSupports")
        if isinstance(candidate, Mapping):
            supports_raw = candidate

    addresses = raw.get("addresses")
    return TailscaleDevice(
        node_id=immutable_id,
        legacy_id=legacy_id,
        name=_optional_string(raw.get("name")) or "",
        hostname=_optional_string(raw.get("hostname")) or "",
        addresses=_string_tuple(addresses),
        os=_optional_string(raw.get("os")),
        client_version=_optional_string(raw.get("clientVersion")),
        expires=_timestamp(raw.get("expires")),
        last_seen=last_seen,
        update_available=_optional_bool(raw.get("updateAvailable")),
        key_expiry_disabled=_optional_bool(raw.get("keyExpiryDisabled")),
        connected_to_control=connected,
        online=online,
        online_source=online_source,
        client_supports=ClientSupports(
            ipv6=_optional_bool(supports_raw.get("ipv6")),
            pcp=_optional_bool(supports_raw.get("pcp")),
            pmp=_optional_bool(supports_raw.get("pmp")),
            udp=_optional_bool(supports_raw.get("udp")),
            upnp=_optional_bool(supports_raw.get("upnp")),
        ),
    )


class TailscaleTrustClient:
    """Read devices with a cached, automatically refreshed OAuth token."""

    def __init__(
        self,
        session: ClientSession,
        *,
        tailnet: str,
        client_id: str,
        client_secret: str,
        token_url: str = OAUTH_TOKEN_URL,
        api_base_url: str = API_BASE_URL,
        monotonic: Callable[[], float] = time.monotonic,
        random_value: Callable[[], float] = random.random,
    ) -> None:
        """Initialize the client without retaining access tokens on disk."""
        self._session = session
        self._tailnet = tailnet
        self._client_id = client_id
        self._client_secret = client_secret
        self._token_url = token_url
        self._api_base_url = api_base_url.rstrip("/")
        self._monotonic = monotonic
        self._random_value = random_value
        self._access_token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()
        self._device_rate_limit_failures = 0
        self._route_rate_limit_failures = 0
        self._routes_next_refresh = 0.0
        self._route_cache: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}

    def invalidate_token(self) -> None:
        """Discard a cached access token."""
        self._access_token = None
        self._token_expires_at = 0.0

    async def _async_token(self, *, force: bool = False) -> str:
        """Return a token that remains valid beyond the clock-skew margin."""
        if (
            not force
            and self._access_token is not None
            and self._monotonic() < self._token_expires_at
        ):
            return self._access_token

        async with self._token_lock:
            if (
                not force
                and self._access_token is not None
                and self._monotonic() < self._token_expires_at
            ):
                return self._access_token
            return await self._async_exchange_token()

    async def _async_exchange_token(self) -> str:
        """Exchange the long-lived OAuth credentials for a one-hour token."""
        try:
            response = await self._session.post(
                self._token_url,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "client_credentials",
                    "scope": OAUTH_SCOPE,
                },
                timeout=REQUEST_TIMEOUT,
            )
        except (ClientError, TimeoutError) as err:
            raise TailscaleTrustConnectionError("OAuth endpoint unavailable") from err

        async with response:
            if response.status == 429:
                raise TailscaleTrustRateLimitError(
                    self._rate_limit_delay(
                        self._retry_after_header(response), routes=False
                    )
                )
            if response.status == 400:
                try:
                    error_payload = await response.json()
                except (ClientError, ValueError, TypeError):
                    error_payload = None
                if (
                    isinstance(error_payload, Mapping)
                    and error_payload.get("error") == "invalid_scope"
                ):
                    raise TailscaleTrustPermissionError(
                        f"OAuth client must grant {OAUTH_SCOPE}"
                    )
                raise TailscaleTrustAuthenticationError(
                    "OAuth client is invalid or revoked"
                )
            if response.status == 401:
                raise TailscaleTrustAuthenticationError(
                    "OAuth client is invalid or revoked"
                )
            if response.status == 403:
                raise TailscaleTrustPermissionError(
                    f"OAuth client must grant {OAUTH_SCOPE}"
                )
            if response.status >= 400:
                raise TailscaleTrustConnectionError(
                    f"OAuth endpoint returned HTTP {response.status}"
                )
            try:
                payload = await response.json()
            except (ClientError, ValueError, TypeError) as err:
                raise TailscaleTrustConnectionError(
                    "OAuth endpoint returned invalid JSON"
                ) from err

        token = payload.get("access_token") if isinstance(payload, Mapping) else None
        expires_in = payload.get("expires_in") if isinstance(payload, Mapping) else None
        if not isinstance(token, str) or not token:
            raise TailscaleTrustConnectionError("OAuth response omitted access_token")
        if (
            not isinstance(expires_in, (int, float))
            or isinstance(expires_in, bool)
            or not math.isfinite(float(expires_in))
            or expires_in <= 0
        ):
            expires_in = 3600

        refresh_margin = min(TOKEN_REFRESH_SKEW, max(0.0, float(expires_in) / 10))
        self._access_token = token
        self._token_expires_at = self._monotonic() + max(
            0.0, float(expires_in) - refresh_margin
        )
        return token

    @staticmethod
    def _retry_after_header(response: Any) -> str | None:
        """Return Retry-After without exposing other response headers."""
        headers = getattr(response, "headers", None)
        get_header = getattr(headers, "get", None)
        if callable(get_header):
            value = get_header("Retry-After")
            return value if isinstance(value, str) else None
        return None

    @staticmethod
    def _parse_retry_after(value: str | None) -> float | None:
        """Parse and sanitize delta-seconds or an HTTP-date Retry-After value."""
        if value is None:
            return None
        try:
            delay = float(value)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
            except (TypeError, ValueError, OverflowError):
                return None
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=UTC)
            delay = (retry_at.astimezone(UTC) - datetime.now(UTC)).total_seconds()
        if not math.isfinite(delay):
            return None
        return min(RATE_LIMIT_MAX_RETRY, max(1.0, delay))

    def _rate_limit_delay(self, value: str | None, *, routes: bool) -> float:
        """Return a bounded server delay or jittered exponential fallback."""
        if parsed := self._parse_retry_after(value):
            return parsed

        if routes:
            self._route_rate_limit_failures += 1
            failures = self._route_rate_limit_failures
        else:
            self._device_rate_limit_failures += 1
            failures = self._device_rate_limit_failures

        base = min(
            RATE_LIMIT_MAX_RETRY,
            RATE_LIMIT_DEFAULT_RETRY * (2 ** min(failures - 1, 4)),
        )
        jitter = 0.8 + (0.4 * min(1.0, max(0.0, self._random_value())))
        return min(RATE_LIMIT_MAX_RETRY, max(1.0, base * jitter))

    def _apply_route_cache(self, devices: dict[str, TailscaleDevice]) -> None:
        """Apply the latest successful route state to freshly listed devices."""
        for node_id, device in devices.items():
            if cached := self._route_cache.get(node_id):
                devices[node_id] = replace(
                    device,
                    advertised_routes=cached[0],
                    enabled_routes=cached[1],
                    routes_available=True,
                )

    async def _async_route_requests(
        self, token: str, node_ids: tuple[str, ...]
    ) -> list[tuple[str, int, Any, str | None]]:
        """Read routes in bounded batches and stop on a global API failure."""
        results: list[tuple[str, int, Any, str | None]] = []
        for start in range(0, len(node_ids), ROUTE_REQUEST_CONCURRENCY):
            batch = node_ids[start : start + ROUTE_REQUEST_CONCURRENCY]
            batch_results = await asyncio.gather(
                *(self._async_routes_request(token, node_id) for node_id in batch)
            )
            results.extend(batch_results)
            if any(status in {401, 403, 429} for _, status, _, _ in batch_results):
                break
        return results

    async def async_list_devices(self) -> dict[str, TailscaleDevice]:
        """List devices and routes, retrying once after an authentication failure."""
        for attempt in range(2):
            token = await self._async_token(force=attempt == 1)
            status, payload, retry_after = await self._async_devices_request(token)
            if status == 401 and attempt == 0:
                self.invalidate_token()
                continue
            if status == 401:
                raise TailscaleTrustAuthenticationError(
                    "Tailscale rejected refreshed OAuth credentials"
                )
            if status == 403:
                raise TailscaleTrustPermissionError(
                    f"OAuth client must grant {OAUTH_SCOPE} for this tailnet"
                )
            if status == 429:
                raise TailscaleTrustRateLimitError(
                    self._rate_limit_delay(retry_after, routes=False)
                )
            if status >= 400:
                raise TailscaleTrustConnectionError(
                    f"Devices endpoint returned HTTP {status}"
                )

            raw_devices = (
                payload.get("devices") if isinstance(payload, Mapping) else None
            )
            if not isinstance(raw_devices, list):
                raise TailscaleTrustConnectionError(
                    "Devices endpoint returned an invalid response"
                )
            now = datetime.now(UTC)
            devices: dict[str, TailscaleDevice] = {}
            for item in raw_devices:
                if not isinstance(item, Mapping):
                    continue
                try:
                    device = parse_device(item, now=now)
                except TailscaleTrustConnectionError:
                    continue
                devices[device.node_id] = device
            if raw_devices and not devices:
                raise TailscaleTrustConnectionError(
                    "Devices endpoint returned no usable device identifiers"
                )
            self._device_rate_limit_failures = 0
            self._apply_route_cache(devices)

            if self._monotonic() < self._routes_next_refresh:
                return devices

            route_results = await self._async_route_requests(token, tuple(devices))
            if any(status == 401 for _, status, _, _ in route_results):
                if attempt == 0:
                    self.invalidate_token()
                    continue
                raise TailscaleTrustAuthenticationError(
                    "Tailscale rejected refreshed OAuth credentials"
                )

            route_rate_limit_headers = [
                retry_header
                for _, route_status, _, retry_header in route_results
                if route_status == 429
            ]
            parsed_route_delays = [
                delay
                for retry_header in route_rate_limit_headers
                if (delay := self._parse_retry_after(retry_header)) is not None
            ]
            route_retry_after = (
                max(parsed_route_delays)
                if parsed_route_delays
                else (
                    self._rate_limit_delay(None, routes=True)
                    if route_rate_limit_headers
                    else 0.0
                )
            )
            for node_id, route_status, route_payload, _retry_header in route_results:
                if route_status == 403:
                    raise TailscaleTrustPermissionError(
                        f"OAuth client must grant {OAUTH_SCOPE} for this tailnet"
                    )
                if route_status == 404:
                    # The device may have been removed between the list and route calls.
                    continue
                if route_status == 429:
                    continue
                if route_status >= 400:
                    continue
                if not isinstance(route_payload, Mapping):
                    continue
                advertised_routes = _string_tuple(route_payload.get("advertisedRoutes"))
                enabled_routes = _string_tuple(route_payload.get("enabledRoutes"))
                self._route_cache[node_id] = (advertised_routes, enabled_routes)
                devices[node_id] = replace(
                    devices[node_id],
                    advertised_routes=advertised_routes,
                    enabled_routes=enabled_routes,
                    routes_available=True,
                )

            if route_retry_after:
                self._routes_next_refresh = self._monotonic() + route_retry_after
            else:
                self._route_rate_limit_failures = 0
                self._routes_next_refresh = (
                    self._monotonic() + ROUTE_SCAN_INTERVAL.total_seconds()
                )
            return devices

        raise AssertionError("Unreachable authentication retry state")

    async def _async_devices_request(self, token: str) -> tuple[int, Any, str | None]:
        """Perform a single authenticated device-list request."""
        url = f"{self._api_base_url}/tailnet/{quote(self._tailnet, safe='')}/devices"
        try:
            response = await self._session.get(
                url,
                params={"fields": "all"},
                headers={"Authorization": f"Bearer {token}"},
                timeout=REQUEST_TIMEOUT,
            )
        except (ClientError, TimeoutError) as err:
            raise TailscaleTrustConnectionError("Devices endpoint unavailable") from err

        async with response:
            if response.status >= 400:
                return response.status, None, self._retry_after_header(response)
            try:
                return response.status, await response.json(), None
            except (ClientError, ValueError, TypeError) as err:
                raise TailscaleTrustConnectionError(
                    "Devices endpoint returned invalid JSON"
                ) from err

    async def _async_routes_request(
        self, token: str, node_id: str
    ) -> tuple[str, int, Any, str | None]:
        """Perform one authenticated read-only device-routes request."""
        url = f"{self._api_base_url}/device/{quote(node_id, safe='')}/routes"
        try:
            response = await self._session.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=REQUEST_TIMEOUT,
            )
        except (ClientError, TimeoutError):
            return node_id, 0, None, None

        async with response:
            if response.status >= 400:
                return (
                    node_id,
                    response.status,
                    None,
                    self._retry_after_header(response),
                )
            try:
                return node_id, response.status, await response.json(), None
            except (ClientError, ValueError, TypeError):
                return node_id, response.status, None, None
