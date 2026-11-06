"""Constants for the Home Assistant Hildebrand Glow IHD Integration."""

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "hildebrand_glow_ihd"
# Keep in step with "homeassistant" in hacs.json
MIN_HA_VERSION: Final = "2026.4.0"

PLATFORMS: Final = [Platform.SENSOR]

CONF_TIME_ZONE_ELECTRICITY: Final = "time_zone_electricity"
CONF_TIME_ZONE_GAS: Final = "time_zone_gas"
CONF_TOPIC_PREFIX: Final = "topic_prefix"

DEFAULT_TITLE: Final = "Hildebrand Glow IHD"

MANUFACTURER: Final = "Hildebrand Technology Limited"
MODEL: Final = "Glow Smart Meter IHD"
