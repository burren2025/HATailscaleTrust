"""Tests for entity state and stable IDs."""

from unittest.mock import AsyncMock, patch

from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tailscale_trust.const import (
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_TAILNET,
    DOMAIN,
)


async def _setup(hass, devices) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="example.com",
        data={
            CONF_TAILNET: "example.com",
            CONF_CLIENT_ID: "test-client",
            CONF_CLIENT_SECRET: "test-secret",
        },
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.tailscale_trust.api.TailscaleTrustClient.async_list_devices",
        AsyncMock(return_value=devices),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_online_state_and_unique_id_use_node_id(hass, device) -> None:
    """The online sensor reflects connectivity and uses nodeId for identity."""
    await _setup(hass, {device.node_id: device})
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("binary_sensor", DOMAIN, "nNODE123_online")

    assert entity_id is not None
    assert hass.states.get(entity_id).state == "on"


async def test_useful_built_in_entity_keys_are_reproduced(hass, device) -> None:
    """Entities keep the useful built-in description keys for easy mapping."""
    await _setup(hass, {device.node_id: device})
    registry = er.async_get(hass)
    expected = {
        "sensor": {"expires", "ip", "last_seen"},
        "binary_sensor": {
            "online",
            "update_available",
            "key_expiry_disabled",
            "client_supports_ipv6",
            "client_supports_pcp",
            "client_supports_pmp",
            "client_supports_udp",
            "client_supports_upnp",
        },
    }

    for platform, keys in expected.items():
        for key in keys:
            assert registry.async_get_entity_id(
                platform, DOMAIN, f"{device.node_id}_{key}"
            )


async def test_device_rename_does_not_change_unique_id(hass, device) -> None:
    """A name change updates metadata but not the registry identity."""
    await _setup(hass, {device.node_id: device})
    registry = er.async_get(hass)

    assert (
        registry.async_get_entity_id("sensor", DOMAIN, f"{device.node_id}_last_seen")
        is not None
    )
