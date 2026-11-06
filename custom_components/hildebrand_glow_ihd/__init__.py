"""The Home Assistant Hildebrand Glow IHD Integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from awesomeversion import AwesomeVersion
from homeassistant.components import mqtt
from homeassistant.const import CONF_DEVICE_ID
from homeassistant.const import __version__ as HA_VERSION  # noqa: N812
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, MIN_HA_VERSION, PLATFORMS
from .helpers import entry_title
from .models import async_build_runtime_data

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers.typing import ConfigType

    from .models import GlowConfigEntry

_LOGGER = logging.getLogger(__name__)

# Set up from the UI only, there is no YAML configuration
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(
    hass: HomeAssistant,  # noqa: ARG001
    config: ConfigType,  # noqa: ARG001
) -> bool:
    """Set up the Home Assistant Hildebrand Glow IHD Integration."""
    if AwesomeVersion(HA_VERSION) < AwesomeVersion(MIN_HA_VERSION):  # pragma: no cover
        _LOGGER.critical(
            "This integration requires at least Home Assistant version %s, you"
            " are running version %s. Please upgrade Home Assistant to continue"
            " using this integration.",
            MIN_HA_VERSION,
            HA_VERSION,
        )
        return False
    return True


async def async_setup_entry(hass: HomeAssistant, entry: GlowConfigEntry) -> bool:
    """Set up a Glow IHD from a config entry."""
    if not entry.title:
        # Entries created by earlier versions have a blank title, shown as
        # "Created configuration for ." and an unnamed integration entry.
        hass.config_entries.async_update_entry(
            entry,
            title=entry_title(entry.data.get(CONF_DEVICE_ID)),
        )

    # The sensors are fed by MQTT messages, so wait for the MQTT client
    if not await mqtt.async_wait_for_mqtt_client(hass):
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="mqtt_not_available",
        )

    entry.runtime_data = await async_build_runtime_data(entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GlowConfigEntry) -> bool:
    """Unload a config entry.

    The MQTT subscription is removed by the callback the sensor platform
    registered with ``entry.async_on_unload``.
    """
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant,  # noqa: ARG001
    config_entry: GlowConfigEntry,  # noqa: ARG001
    device_entry: dr.DeviceEntry,  # noqa: ARG001
) -> bool:
    """Allow a Glow device to be deleted from the UI.

    Devices are discovered from MQTT topics, so one that has been replaced or
    is no longer publishing would otherwise be stuck in the device list. If the
    device publishes again it is re-added after Home Assistant restarts or the
    integration is reloaded.
    """
    return True
