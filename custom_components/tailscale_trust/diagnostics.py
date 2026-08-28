"""Diagnostics support for Tailscale Trust."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .coordinator import TailscaleTrustConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: TailscaleTrustConfigEntry
) -> dict[str, Any]:
    """Return aggregate and pseudonymous metadata without tailnet topology."""
    devices = entry.runtime_data.data
    return {
        "config_entry": {
            "domain": entry.domain,
            "source": entry.source,
            "version": entry.version,
            "minor_version": entry.minor_version,
        },
        "summary": {
            "device_count": len(devices),
            "present_count": sum(device.present for device in devices.values()),
            "online_count": sum(device.online is True for device in devices.values()),
            "routes_available_count": sum(
                device.routes_available for device in devices.values()
            ),
            "route_approval_required_count": sum(
                bool(device.routes_awaiting_approval) for device in devices.values()
            ),
        },
        "devices": [
            {
                "device": f"device_{index}",
                "os": device.os,
                "present": device.present,
                "online": device.online,
                "online_source": device.online_source,
                "routes_available": device.routes_available,
                "advertised_route_count": len(device.advertised_routes),
                "enabled_route_count": len(device.enabled_routes),
                "routes_awaiting_approval_count": len(device.routes_awaiting_approval),
                "advertises_exit_node": device.advertises_exit_node,
                "exit_node_enabled": device.exit_node_enabled,
                "advertises_subnet_routes": device.advertises_subnet_routes,
            }
            for index, (_, device) in enumerate(sorted(devices.items()), start=1)
        ],
    }
