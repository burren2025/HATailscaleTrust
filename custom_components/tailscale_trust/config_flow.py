"""Config flow for Tailscale Trust."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, override

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    TailscaleTrustAuthenticationError,
    TailscaleTrustClient,
    TailscaleTrustConnectionError,
    TailscaleTrustPermissionError,
)
from .const import CONF_CLIENT_ID, CONF_CLIENT_SECRET, CONF_TAILNET, DOMAIN

TRUST_CREDENTIALS_URL = "https://console.tailscale.com/admin/settings/trust-credentials"


async def async_validate_input(
    hass: HomeAssistant, *, tailnet: str, client_id: str, client_secret: str
) -> None:
    """Exchange a token and confirm that the credential can list devices."""
    client = TailscaleTrustClient(
        async_get_clientsession(hass),
        tailnet=tailnet,
        client_id=client_id,
        client_secret=client_secret,
    )
    await client.async_list_devices()


def _credential_schema(defaults: Mapping[str, Any]) -> vol.Schema:
    """Return the user/reauth form with a masked secret."""
    return vol.Schema(
        {
            vol.Required(
                CONF_TAILNET, default=defaults.get(CONF_TAILNET, "")
            ): TextSelector(),
            vol.Required(
                CONF_CLIENT_ID, default=defaults.get(CONF_CLIENT_ID, "")
            ): TextSelector(),
            vol.Required(CONF_CLIENT_SECRET): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
        }
    )


class TailscaleTrustConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle Tailscale Trust config and reauthentication flows."""

    VERSION = 1

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create an entry after validating the narrow read-only credential."""
        errors: dict[str, str] = {}
        if user_input is not None:
            clean = {
                CONF_TAILNET: user_input[CONF_TAILNET].strip(),
                CONF_CLIENT_ID: user_input[CONF_CLIENT_ID].strip(),
                CONF_CLIENT_SECRET: user_input[CONF_CLIENT_SECRET].strip(),
            }
            try:
                await async_validate_input(self.hass, **clean)
            except TailscaleTrustAuthenticationError:
                errors["base"] = "invalid_auth"
            except TailscaleTrustPermissionError:
                errors["base"] = "insufficient_scope"
            except TailscaleTrustConnectionError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(clean[CONF_TAILNET].casefold())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=clean[CONF_TAILNET], data=clean)

        return self.async_show_form(
            step_id="user",
            description_placeholders={"trust_credentials_url": TRUST_CREDENTIALS_URL},
            data_schema=_credential_schema(user_input or {}),
            errors=errors,
        )

    @override
    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication without removing the existing entry."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Replace a revoked OAuth client in the existing config entry."""
        reauth_entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        defaults = {
            CONF_TAILNET: reauth_entry.data[CONF_TAILNET],
            CONF_CLIENT_ID: reauth_entry.data[CONF_CLIENT_ID],
        }
        if user_input is not None:
            clean = {
                CONF_TAILNET: reauth_entry.data[CONF_TAILNET],
                CONF_CLIENT_ID: user_input[CONF_CLIENT_ID].strip(),
                CONF_CLIENT_SECRET: user_input[CONF_CLIENT_SECRET].strip(),
            }
            try:
                await async_validate_input(self.hass, **clean)
            except TailscaleTrustAuthenticationError:
                errors["base"] = "invalid_auth"
            except TailscaleTrustPermissionError:
                errors["base"] = "insufficient_scope"
            except TailscaleTrustConnectionError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data_updates={
                        CONF_CLIENT_ID: clean[CONF_CLIENT_ID],
                        CONF_CLIENT_SECRET: clean[CONF_CLIENT_SECRET],
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_CLIENT_ID, default=defaults[CONF_CLIENT_ID]
                ): TextSelector(),
                vol.Required(CONF_CLIENT_SECRET): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
            }
        )
        return self.async_show_form(
            step_id="reauth_confirm",
            description_placeholders={
                "tailnet": defaults[CONF_TAILNET],
                "trust_credentials_url": TRUST_CREDENTIALS_URL,
            },
            data_schema=schema,
            errors=errors,
        )
