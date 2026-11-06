"""Constants for the Home Assistant Hildebrand Glow IHD Integration."""

from enum import Enum
from typing import Final

DOMAIN: Final = "hildebrand_glow_ihd"
MIN_HA_VERSION = "2024.12"

ATTR_NAME = "name"
ATTR_ACTIVITY = "activity"
ATTR_BATTERY_STATE = "battery_state"
ATTR_RF_LINK_LEVEL = "rf_link_level"
ATTR_RF_LINK_STATE = "rf_link_state"
ATTR_SERIAL = "serial"
ATTR_OPERATING_HOURS = "operating_hours"
ATTR_LAST_ERROR = "last_error"
ATTR_ERROR = "error"
ATTR_STATE = "state"

CONF_TIME_ZONE_ELECTRICITY = "time_zone_electricity"
CONF_TIME_ZONE_GAS = "time_zone_gas"
CONF_TOPIC_PREFIX = "topic_prefix"

DEFAULT_DEVICE_ID = "+"
DEFAULT_TOPIC_PREFIX = "glow"
DEFAULT_TITLE = "Hildebrand Glow IHD"


def entry_title(device_id: str | None) -> str:
    """Return the config entry title for a configured device ID."""
    device_id = (device_id or "").strip()
    if not device_id or device_id == DEFAULT_DEVICE_ID:
        return DEFAULT_TITLE
    return f"{DEFAULT_TITLE} ({device_id})"


# Meter intervals
class MeterInterval(Enum):
    """Meter intervals."""

    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"
