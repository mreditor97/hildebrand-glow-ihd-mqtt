"""Constants for the Home Assistant Hildebrand Glow IHD Integration."""

from enum import StrEnum
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

# "+" matches every device
DEFAULT_DEVICE_ID: Final = "+"
DEFAULT_TOPIC_PREFIX: Final = "glow"

# The IHD reports this power value when it can't read the meter
POWER_ERROR_VALUE: Final = -8388.608

# Units the IHD uses for gas volume readings in cubic metres
GAS_VOLUME_UNITS: Final = frozenset({"m3", "m³", "m^3"})


class TopicKind(StrEnum):
    """The kinds of message a Glow device publishes, by the end of the topic.

    The topics are:
      <prefix>/<device id>/STATE
      <prefix>/<device id>/SENSOR/electricitymeter
      <prefix>/<device id>/SENSOR/gasmeter
    """

    STATE = "STATE"
    ELECTRICITY_METER = "electricitymeter"
    GAS_METER = "gasmeter"


class MeterInterval(StrEnum):
    """Intervals that a meter's running totals reset on."""

    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"
