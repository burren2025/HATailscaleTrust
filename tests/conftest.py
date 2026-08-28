"""Shared fixtures for Tailscale Trust tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from custom_components.tailscale_trust.api import ClientSupports, TailscaleDevice

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations in every Home Assistant test."""


@pytest.fixture
def device() -> TailscaleDevice:
    """Return a representative connected device."""
    return TailscaleDevice(
        node_id="nNODE123",
        legacy_id="12345",
        name="tablet.example.ts.net",
        hostname="tablet",
        addresses=("100.64.0.10", "fd7a:115c:a1e0::10"),
        os="android",
        client_version="1.82.0",
        expires=datetime(2027, 1, 1, tzinfo=UTC),
        last_seen=None,
        update_available=False,
        key_expiry_disabled=True,
        connected_to_control=True,
        online=True,
        online_source="connected_to_control",
        client_supports=ClientSupports(
            ipv6=True, pcp=False, pmp=False, udp=True, upnp=False
        ),
        advertised_routes=("0.0.0.0/0", "::/0", "192.168.50.0/24"),
        enabled_routes=("0.0.0.0/0", "::/0"),
        routes_available=True,
    )
