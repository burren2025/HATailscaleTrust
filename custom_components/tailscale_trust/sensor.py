"""Sensors for Tailscale Trust."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import TailscaleDevice
from .coordinator import TailscaleTrustConfigEntry
from .entity import TailscaleTrustEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class TailscaleTrustSensorEntityDescription(SensorEntityDescription):
    """Describe a Tailscale Trust sensor."""

    value_fn: Callable[[TailscaleDevice], datetime | str | None]


SENSORS: tuple[TailscaleTrustSensorEntityDescription, ...] = (
    TailscaleTrustSensorEntityDescription(
        key="expires",
        translation_key="expires",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: device.expires,
    ),
    TailscaleTrustSensorEntityDescription(
        key="ip",
        translation_key="ip",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: device.addresses[0] if device.addresses else None,
    ),
    TailscaleTrustSensorEntityDescription(
        key="last_seen",
        translation_key="last_seen",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda device: device.last_seen,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TailscaleTrustConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors and discover devices added after startup."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def async_add_new_entities() -> None:
        new_ids = coordinator.data.keys() - known
        if not new_ids:
            return
        async_add_entities(
            TailscaleTrustSensorEntity(
                coordinator=coordinator,
                node_id=node_id,
                description=description,
            )
            for node_id in new_ids
            for description in SENSORS
        )
        known.update(new_ids)

    async_add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(async_add_new_entities))


class TailscaleTrustSensorEntity(TailscaleTrustEntity, SensorEntity):
    """Represent a Tailscale device sensor."""

    entity_description: TailscaleTrustSensorEntityDescription

    @property
    @override
    def native_value(self) -> datetime | str | None:
        """Return the current sensor value."""
        return self.entity_description.value_fn(self.device)
