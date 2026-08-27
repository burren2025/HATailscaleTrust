"""Diagnostics support for Tailscale Trust."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_CLIENT_ID, CONF_CLIENT_SECRET
from .coordinator import TailscaleTrustConfigEntry

TO_REDACT = {CONF_CLIENT_ID, CONF_CLIENT_SECRET}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: TailscaleTrustConfigEntry
) -> dict[str, Any]:
    """Return useful metadata without either long-lived OAuth credential."""
    return {
        "config_entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "devices": {
            node_id: {
                "name": device.name,
                "hostname": device.hostname,
                "os": device.os,
                "present": device.present,
                "online": device.online,
                "online_source": device.online_source,
            }
            for node_id, device in entry.runtime_data.data.items()
        },
    }
