"""Data update coordinator for Tailscale Trust."""

from __future__ import annotations

from dataclasses import replace
from typing import override

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    TailscaleDevice,
    TailscaleTrustAuthenticationError,
    TailscaleTrustClient,
    TailscaleTrustError,
    TailscaleTrustPermissionError,
)
from .const import (
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_TAILNET,
    DOMAIN,
    LOGGER,
    SCAN_INTERVAL,
)

type TailscaleTrustConfigEntry = ConfigEntry[TailscaleTrustDataUpdateCoordinator]


class TailscaleTrustDataUpdateCoordinator(
    DataUpdateCoordinator[dict[str, TailscaleDevice]]
):
    """Coordinate device polling while retaining temporarily absent devices."""

    config_entry: TailscaleTrustConfigEntry

    def __init__(
        self, hass: HomeAssistant, config_entry: TailscaleTrustConfigEntry
    ) -> None:
        """Initialize the coordinator."""
        data = config_entry.data
        self.client = TailscaleTrustClient(
            async_get_clientsession(hass),
            tailnet=data[CONF_TAILNET],
            client_id=data[CONF_CLIENT_ID],
            client_secret=data[CONF_CLIENT_SECRET],
        )
        super().__init__(
            hass,
            LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )

    @override
    async def _async_update_data(self) -> dict[str, TailscaleDevice]:
        """Fetch and reconcile the tailnet device list."""
        try:
            current = await self.client.async_list_devices()
        except (
            TailscaleTrustAuthenticationError,
            TailscaleTrustPermissionError,
        ) as err:
            raise ConfigEntryAuthFailed(
                "The Tailscale OAuth client is invalid, revoked, or lacks read access"
            ) from err
        except TailscaleTrustError as err:
            raise UpdateFailed(str(err)) from err

        if not self.data:
            return current

        # Do not delete registry entries when a device is temporarily omitted or
        # removed. It remains visible as offline and will resume under the same
        # immutable node ID if it returns.
        for node_id, device in self.data.items():
            if node_id not in current:
                current[node_id] = replace(
                    device,
                    connected_to_control=False,
                    online=False,
                    online_source="absent_from_device_list",
                    present=False,
                )
        return current
