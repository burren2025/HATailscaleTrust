"""Tests for coordinator reconciliation and authentication handling."""

from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tailscale_trust.api import (
    TailscaleTrustAuthenticationError,
)
from custom_components.tailscale_trust.const import (
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_TAILNET,
    DOMAIN,
)
from custom_components.tailscale_trust.coordinator import (
    TailscaleTrustDataUpdateCoordinator,
)


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="example.com",
        data={
            CONF_TAILNET: "example.com",
            CONF_CLIENT_ID: "test-client",
            CONF_CLIENT_SECRET: "test-secret",
        },
    )


async def test_temporarily_absent_device_is_retained_offline(hass, device) -> None:
    """An omitted device keeps its registry identity and reports offline."""
    entry = _entry()
    entry.add_to_hass(hass)
    coordinator = TailscaleTrustDataUpdateCoordinator(hass, entry)
    coordinator.client.async_list_devices = AsyncMock(
        side_effect=[{device.node_id: device}, {}]
    )

    await coordinator.async_refresh()
    await coordinator.async_refresh()

    retained = coordinator.data[device.node_id]
    assert retained.present is False
    assert retained.online is False
    assert retained.online_source == "absent_from_device_list"


async def test_revoked_credentials_raise_config_entry_auth_failed(hass) -> None:
    """Coordinator turns OAuth revocation into Home Assistant reauth."""
    entry = _entry()
    entry.add_to_hass(hass)
    coordinator = TailscaleTrustDataUpdateCoordinator(hass, entry)
    coordinator.client.async_list_devices = AsyncMock(
        side_effect=TailscaleTrustAuthenticationError
    )

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()
