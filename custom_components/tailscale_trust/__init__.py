"""The Tailscale Trust integration."""

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .coordinator import TailscaleTrustConfigEntry, TailscaleTrustDataUpdateCoordinator

PLATFORMS = (Platform.BINARY_SENSOR, Platform.SENSOR)


async def async_setup_entry(
    hass: HomeAssistant, entry: TailscaleTrustConfigEntry
) -> bool:
    """Set up Tailscale Trust from a config entry."""
    coordinator = TailscaleTrustDataUpdateCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: TailscaleTrustConfigEntry
) -> bool:
    """Unload a Tailscale Trust config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    entry: TailscaleTrustConfigEntry,
    device_entry: dr.DeviceEntry,
) -> bool:
    """Allow users to remove a device only after it is absent from Tailscale."""
    del hass
    return any(
        domain == DOMAIN
        and (
            (device := entry.runtime_data.data.get(node_id)) is None
            or not device.present
        )
        for domain, node_id in device_entry.identifiers
    )
