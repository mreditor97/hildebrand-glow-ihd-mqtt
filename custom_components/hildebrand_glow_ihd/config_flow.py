"""Config flow for the Home Assistant Hildebrand Glow IHD Integration."""

from __future__ import annotations

import zoneinfo
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_DEVICE_ID
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_TIME_ZONE_ELECTRICITY,
    CONF_TIME_ZONE_GAS,
    CONF_TOPIC_PREFIX,
    DEFAULT_DEVICE_ID,
    DEFAULT_TOPIC_PREFIX,
    DOMAIN,
)
from .helpers import entry_title
from .models import entry_settings

if TYPE_CHECKING:
    from collections.abc import Mapping

    from homeassistant.config_entries import ConfigEntry, ConfigFlowResult
    from homeassistant.core import HomeAssistant


async def _async_settings_schema(
    hass: HomeAssistant,
    defaults: Mapping[str, Any],
) -> vol.Schema:
    """Return the form schema shared by the config and options flows.

    Home Assistant 2026.9 replaced voluptuous with probatio and installs
    probatio under the voluptuous name, while 2026.4 to 2026.8 use voluptuous
    itself. Importing voluptuous works on both, but mypy sees the real
    voluptuous types, hence the type ignores where the schema is used.
    """
    # Listing the time zones reads the disk, so don't do it in the event loop
    time_zones = await hass.async_add_executor_job(zoneinfo.available_timezones)
    time_zone_selector = SelectSelector(
        SelectSelectorConfig(
            options=list(time_zones),
            mode=SelectSelectorMode.DROPDOWN,
            sort=True,
        ),
    )
    return vol.Schema(
        {
            vol.Required(
                CONF_DEVICE_ID,
                default=defaults.get(CONF_DEVICE_ID, DEFAULT_DEVICE_ID),
            ): str,
            vol.Required(
                CONF_TOPIC_PREFIX,
                default=defaults.get(CONF_TOPIC_PREFIX, DEFAULT_TOPIC_PREFIX),
            ): str,
            vol.Required(
                CONF_TIME_ZONE_ELECTRICITY,
                default=defaults.get(
                    CONF_TIME_ZONE_ELECTRICITY,
                    hass.config.time_zone,
                ),
            ): time_zone_selector,
            vol.Required(
                CONF_TIME_ZONE_GAS,
                default=defaults.get(CONF_TIME_ZONE_GAS, hass.config.time_zone),
            ): time_zone_selector,
        },
    )


class HildebrandGlowIHDMQTTConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for a Glow IHD."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        if user_input is not None:
            device_id = user_input[CONF_DEVICE_ID]
            # Existing entries use this unique ID, don't change it
            await self.async_set_unique_id(f"{DOMAIN}_{device_id}")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=entry_title(device_id),
                data=user_input,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=await _async_settings_schema(self.hass, {}),  # type: ignore[arg-type]
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,  # noqa: ARG004
    ) -> HildebrandGlowIHDMQTTOptionsFlowHandler:
        """Get the options flow for this handler."""
        return HildebrandGlowIHDMQTTOptionsFlowHandler()


class HildebrandGlowIHDMQTTOptionsFlowHandler(OptionsFlowWithReload):
    """Change the settings of a Glow IHD, then reload it to apply them."""

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle options flow."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=await _async_settings_schema(  # type: ignore[arg-type]
                self.hass,
                entry_settings(self.config_entry),
            ),
        )
