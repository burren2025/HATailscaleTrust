"""Binary sensors for Tailscale Trust."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import override

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import TailscaleDevice
from .coordinator import TailscaleTrustConfigEntry
from .entity import TailscaleTrustEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class TailscaleTrustBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describe a Tailscale Trust binary sensor."""

    is_on_fn: Callable[[TailscaleDevice], bool | None]
    available_when_absent: bool = False
    requires_routes: bool = False


BINARY_SENSORS: tuple[TailscaleTrustBinarySensorEntityDescription, ...] = (
    TailscaleTrustBinarySensorEntityDescription(
        key="online",
        translation_key="online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        is_on_fn=lambda device: device.online,
        available_when_absent=True,
    ),
    TailscaleTrustBinarySensorEntityDescription(
        key="update_available",
        translation_key="client",
        device_class=BinarySensorDeviceClass.UPDATE,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda device: device.update_available,
    ),
    TailscaleTrustBinarySensorEntityDescription(
        key="key_expiry_disabled",
        translation_key="key_expiry_disabled",
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda device: device.key_expiry_disabled,
    ),
    TailscaleTrustBinarySensorEntityDescription(
        key="client_supports_ipv6",
        translation_key="client_supports_ipv6",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        is_on_fn=lambda device: device.client_supports.ipv6,
    ),
    TailscaleTrustBinarySensorEntityDescription(
        key="client_supports_pcp",
        translation_key="client_supports_pcp",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        is_on_fn=lambda device: device.client_supports.pcp,
    ),
    TailscaleTrustBinarySensorEntityDescription(
        key="client_supports_pmp",
        translation_key="client_supports_pmp",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        is_on_fn=lambda device: device.client_supports.pmp,
    ),
    TailscaleTrustBinarySensorEntityDescription(
        key="client_supports_udp",
        translation_key="client_supports_udp",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        is_on_fn=lambda device: device.client_supports.udp,
    ),
    TailscaleTrustBinarySensorEntityDescription(
        key="client_supports_upnp",
        translation_key="client_supports_upnp",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        is_on_fn=lambda device: device.client_supports.upnp,
    ),
    TailscaleTrustBinarySensorEntityDescription(
        key="exit_node_advertised",
        translation_key="exit_node_advertised",
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda device: device.advertises_exit_node,
        requires_routes=True,
    ),
    TailscaleTrustBinarySensorEntityDescription(
        key="exit_node_enabled",
        translation_key="exit_node_enabled",
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda device: device.exit_node_enabled,
        requires_routes=True,
    ),
    TailscaleTrustBinarySensorEntityDescription(
        key="subnet_routes_advertised",
        translation_key="subnet_routes_advertised",
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda device: device.advertises_subnet_routes,
        requires_routes=True,
    ),
    TailscaleTrustBinarySensorEntityDescription(
        key="route_approval_required",
        translation_key="route_approval_required",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda device: bool(device.routes_awaiting_approval),
        requires_routes=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TailscaleTrustConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors and discover devices added after startup."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def async_add_new_entities() -> None:
        new_ids = coordinator.data.keys() - known
        if not new_ids:
            return
        async_add_entities(
            TailscaleTrustBinarySensorEntity(
                coordinator=coordinator,
                node_id=node_id,
                description=description,
            )
            for node_id in new_ids
            for description in BINARY_SENSORS
        )
        known.update(new_ids)

    async_add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(async_add_new_entities))


class TailscaleTrustBinarySensorEntity(TailscaleTrustEntity, BinarySensorEntity):
    """Represent a Tailscale device binary sensor."""

    entity_description: TailscaleTrustBinarySensorEntityDescription

    @property
    @override
    def available(self) -> bool:
        """Keep connectivity available and off for omitted devices."""
        if self.entity_description.available_when_absent:
            return self.coordinator.last_update_success and self.is_on is not None
        return super().available and (
            not self.entity_description.requires_routes or self.device.routes_available
        )

    @property
    @override
    def is_on(self) -> bool | None:
        """Return the current binary state."""
        return self.entity_description.is_on_fn(self.device)
