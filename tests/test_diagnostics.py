"""Tests for secret-safe diagnostics."""

import json
from types import SimpleNamespace

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tailscale_trust.const import (
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_TAILNET,
    DOMAIN,
)
from custom_components.tailscale_trust.diagnostics import (
    async_get_config_entry_diagnostics,
)


async def test_credentials_are_redacted(hass, device) -> None:
    """Credentials, tailnet identity, and topology never enter diagnostics."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="example.com",
        data={
            CONF_TAILNET: "example.com",
            CONF_CLIENT_ID: "sensitive-client-id",
            CONF_CLIENT_SECRET: "sensitive-client-secret",
        },
    )
    entry.add_to_hass(hass)
    entry.runtime_data = SimpleNamespace(data={device.node_id: device})

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    serialized = json.dumps(diagnostics)

    assert "sensitive-client-id" not in serialized
    assert "sensitive-client-secret" not in serialized
    assert "example.com" not in serialized
    assert device.node_id not in serialized
    assert device.name not in serialized
    assert device.hostname not in serialized
    assert "100.64.0.10" not in serialized
    assert "192.168.50.0/24" not in serialized
    assert diagnostics["summary"] == {
        "device_count": 1,
        "present_count": 1,
        "online_count": 1,
        "routes_available_count": 1,
        "route_approval_required_count": 1,
    }
    assert diagnostics["devices"][0]["device"] == "device_1"
    assert diagnostics["devices"][0]["routes_awaiting_approval_count"] == 1
