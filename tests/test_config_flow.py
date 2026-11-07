"""Tests for the config and options flows."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType

from custom_components.hildebrand_glow_ihd.const import DOMAIN

from .const import DEVICE_ID, ENTRY_DATA

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from pytest_homeassistant_custom_component.typing import MqttMockHAClient


async def test_user_flow(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
) -> None:
    """The user step creates an entry for the given settings."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {**ENTRY_DATA, "device_id": DEVICE_ID},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"Hildebrand Glow IHD ({DEVICE_ID})"
    assert result["data"] == {**ENTRY_DATA, "device_id": DEVICE_ID}
    # Existing entries use this unique ID
    assert result["result"].unique_id == f"{DOMAIN}_{DEVICE_ID}"


async def test_user_flow_already_configured(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
    config_entry: MockConfigEntry,
) -> None:
    """A second entry for the same device ID is refused."""
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        ENTRY_DATA,
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,
    config_entry: MockConfigEntry,
) -> None:
    """Saved options are applied by reloading the entry."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {**ENTRY_DATA, "device_id": DEVICE_ID, "time_zone_gas": "Europe/London"},
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.runtime_data.device_id == DEVICE_ID
    assert str(config_entry.runtime_data.time_zone_gas) == "Europe/London"
    subscribed = [call.args[0] for call in mqtt_mock.async_subscribe.call_args_list]
    assert f"glow/{DEVICE_ID}/#" in subscribed
