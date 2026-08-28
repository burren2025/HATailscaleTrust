"""Tests for the Tailscale Trust config flow."""

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tailscale_trust.api import (
    TailscaleTrustAuthenticationError,
    TailscaleTrustConnectionError,
    TailscaleTrustPermissionError,
)
from custom_components.tailscale_trust.const import (
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_TAILNET,
    DOMAIN,
)

USER_INPUT = {
    CONF_TAILNET: "example.com",
    CONF_CLIENT_ID: "test-client",
    CONF_CLIENT_SECRET: "test-secret",
}


async def test_user_flow_success(hass) -> None:
    """Valid read-only credentials create a config entry."""
    with patch(
        "custom_components.tailscale_trust.config_flow.async_validate_input",
        AsyncMock(),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data=USER_INPUT,
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "example.com"
    assert result["data"] == USER_INPUT


async def test_user_flow_invalid_auth(hass) -> None:
    """Invalid credentials keep the flow open with a specific error."""
    with patch(
        "custom_components.tailscale_trust.config_flow.async_validate_input",
        AsyncMock(side_effect=TailscaleTrustAuthenticationError),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data=USER_INPUT,
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_error_mapping(hass) -> None:
    """Permission and network failures give actionable form errors."""
    for index, (failure, error) in enumerate(
        (
            (TailscaleTrustPermissionError, "insufficient_scope"),
            (TailscaleTrustConnectionError, "cannot_connect"),
        )
    ):
        user_input = {**USER_INPUT, CONF_TAILNET: f"example-{index}.com"}
        with patch(
            "custom_components.tailscale_trust.config_flow.async_validate_input",
            AsyncMock(side_effect=failure),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
                data=user_input,
            )

        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": error}


async def test_duplicate_entry_aborts_before_live_validation(hass) -> None:
    """Re-adding a tailnet does not spend API quota validating a duplicate."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id="example.com", data=USER_INPUT)
    entry.add_to_hass(hass)
    validate = AsyncMock()

    with patch(
        "custom_components.tailscale_trust.config_flow.async_validate_input",
        validate,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data=USER_INPUT,
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    validate.assert_not_awaited()


async def test_reauth_updates_entry_in_place(hass) -> None:
    """Replacement credentials keep the same config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="example.com",
        data=USER_INPUT,
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_REAUTH,
            "entry_id": entry.entry_id,
        },
        data=entry.data,
    )

    with patch(
        "custom_components.tailscale_trust.config_flow.async_validate_input",
        AsyncMock(),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_CLIENT_ID: "replacement-client",
                CONF_CLIENT_SECRET: "replacement-secret",
            },
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_CLIENT_ID] == "replacement-client"
    assert entry.data[CONF_CLIENT_SECRET] == "replacement-secret"
    assert entry.data[CONF_TAILNET] == "example.com"
