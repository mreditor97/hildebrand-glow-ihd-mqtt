"""Tests for setting up and unloading the integration."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from pytest_homeassistant_custom_component.typing import (
        MqttMockHAClient,
        WebSocketGenerator,
    )


async def test_setup_and_unload(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,
    config_entry: MockConfigEntry,
) -> None:
    """The entry subscribes when set up and unsubscribes when unloaded."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.runtime_data.device_id == "+"
    assert config_entry.runtime_data.topic_prefix == "glow"
    subscribed = {
        call.args[0]: call.args[2] for call in mqtt_mock.async_subscribe.call_args_list
    }
    assert subscribed["glow/+/#"] == 1

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_retries_without_mqtt(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """Setup is retried later when the MQTT client isn't available."""
    config_entry.add_to_hass(hass)
    with patch(
        "homeassistant.components.mqtt.async_wait_for_mqtt_client",
        return_value=False,
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_blank_title_is_replaced(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
    config_entry: MockConfigEntry,
) -> None:
    """Entries from earlier versions with a blank title get one."""
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(config_entry, title="")
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.title == "Hildebrand Glow IHD"


async def test_device_can_be_removed(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
    config_entry: MockConfigEntry,
) -> None:
    """A Glow device can be deleted from the UI."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    device_registry = dr.async_get(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, "AABBCCDDEEFF")},
    )
    assert await async_setup_component(hass, "config", {})
    client = await hass_ws_client(hass)
    response = await client.remove_device(device.id)
    assert response["success"]
    assert device_registry.async_get(device.id) is None
