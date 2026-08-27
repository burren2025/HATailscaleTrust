"""Base entity for Tailscale Trust."""

from __future__ import annotations

from typing import override

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import TailscaleDevice
from .const import DOMAIN
from .coordinator import TailscaleTrustDataUpdateCoordinator


class TailscaleTrustEntity(CoordinatorEntity[TailscaleTrustDataUpdateCoordinator]):
    """Represent one property of a Tailscale device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        *,
        coordinator: TailscaleTrustDataUpdateCoordinator,
        node_id: str,
        description: EntityDescription,
    ) -> None:
        """Initialize the entity with an immutable Tailscale node ID."""
        super().__init__(coordinator)
        self.entity_description = description
        self.node_id = node_id
        self._attr_unique_id = f"{node_id}_{description.key}"

    @property
    def device(self) -> TailscaleDevice:
        """Return current coordinator data for this device."""
        return self.coordinator.data[self.node_id]

    @property
    @override
    def available(self) -> bool:
        """Return whether the device was present in the latest list."""
        return super().available and self.device.present

    @property
    @override
    def device_info(self) -> DeviceInfo:
        """Return registry information that follows device renames."""
        device = self.device
        configuration_url = "https://login.tailscale.com/admin/machines"
        if device.addresses:
            configuration_url += f"/{device.addresses[0]}"
        return DeviceInfo(
            configuration_url=configuration_url,
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, device.node_id)},
            manufacturer="Tailscale Inc.",
            model=device.os,
            name=device.display_name,
            sw_version=device.client_version,
        )
