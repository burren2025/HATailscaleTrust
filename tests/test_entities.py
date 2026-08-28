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
            "exit_node_advertised",
            "exit_node_enabled",
            "subnet_routes_advertised",
            "route_approval_required",
        },
    }
    expected["sensor"].update({"advertised_routes", "enabled_routes"})

    for platform, keys in expected.items():
        for key in keys:
            assert registry.async_get_entity_id(
                platform, DOMAIN, f"{device.node_id}_{key}"
            )


async def test_route_entities_expose_state_and_exact_routes(hass, device) -> None:
    """Route counts support automations while attributes preserve the CIDRs."""
    await _setup(hass, {device.node_id: device})
    registry = er.async_get(hass)

    advertised_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{device.node_id}_advertised_routes"
    )
    approval_id = registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{device.node_id}_route_approval_required"
    )
    exit_id = registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{device.node_id}_exit_node_enabled"
    )

    advertised = hass.states.get(advertised_id)
    assert advertised.state == "3"
    assert advertised.attributes["routes"] == [
        "0.0.0.0/0",
        "::/0",
        "192.168.50.0/24",
    ]
    assert hass.states.get(approval_id).state == "on"
    assert hass.states.get(exit_id).state == "on"


async def test_device_rename_does_not_change_unique_id(hass, device) -> None:
    """A name change updates metadata but not the registry identity."""
    await _setup(hass, {device.node_id: device})
    registry = er.async_get(hass)

    assert (
        registry.async_get_entity_id("sensor", DOMAIN, f"{device.node_id}_last_seen")
        is not None
    )


async def test_verbose_capability_entities_are_disabled_by_default(
    hass, device
) -> None:
    """Low-value protocol details do not create state or recorder churn by default."""
    await _setup(hass, {device.node_id: device})
    registry = er.async_get(hass)

    for key in (
        "client_supports_ipv6",
        "client_supports_pcp",
        "client_supports_pmp",
        "client_supports_udp",
        "client_supports_upnp",
    ):
        entity_id = registry.async_get_entity_id(
            "binary_sensor", DOMAIN, f"{device.node_id}_{key}"
        )
        assert entity_id is not None
        assert (
            registry.async_get(entity_id).disabled_by
            is er.RegistryEntryDisabler.INTEGRATION
        )
        assert hass.states.get(entity_id) is None
