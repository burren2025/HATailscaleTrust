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
    """Neither OAuth credential can appear in downloaded diagnostics."""
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
    assert "example.com" in serialized
