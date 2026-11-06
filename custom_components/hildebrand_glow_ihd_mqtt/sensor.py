"""Support for hildebrand glow MQTT sensors."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, time, timedelta, tzinfo
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from homeassistant.components import mqtt
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    ATTR_DEVICE_ID,
    CONF_DEVICE_ID,
    SIGNAL_STRENGTH_DECIBELS,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfVolume,
)
from homeassistant.core import callback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.util import slugify

from .const import (
    CONF_TIME_ZONE_ELECTRICITY,
    CONF_TIME_ZONE_GAS,
    CONF_TOPIC_PREFIX,
    DEFAULT_DEVICE_ID,
    DEFAULT_TOPIC_PREFIX,
    DOMAIN,
    MeterInterval,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from homeassistant.components.mqtt.models import ReceiveMessage
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

_LOGGER = logging.getLogger(__name__)

# glow/XXXXXXYYYYYY/STATE                   {"software":"v1.8.12","timestamp":"2022-06-11T20:54:53Z","hardware":"GLOW-IHD-01-1v4-SMETS2","ethmac":"1234567890AB","smetsversion":"SMETS2","eui":"12:34:56:78:91:23:45","zigbee":"1.2.5","han":{"rssi":-75,"status":"joined","lqi":100}}  # noqa: E501
# glow/XXXXXXYYYYYY/SENSOR/electricitymeter {"electricitymeter":{"timestamp":"2022-06-11T20:38:00Z","energy":{"export":{"cumulative":0.000,"units":"kWh"},"import":{"cumulative":6613.405,"day":13.252,"week":141.710,"month":293.598,"units":"kWh","mpan":"1234","supplier":"ABC ENERGY","price":{"unitrate":0.04998,"standingcharge":0.24030}}},"power":{"value":0.951,"units":"kW"}}}  # noqa: E501
# glow/XXXXXXYYYYYY/SENSOR/gasmeter         {"gasmeter":{"timestamp":"2022-06-11T20:53:52Z","energy":{"export":{"cumulative":0.000,"units":"kWh"},"import":{"cumulative":17940.852,"day":11.128,"week":104.749,"month":217.122,"units":"kWh","mprn":"1234","supplier":"---","price":{"unitrate":0.07320,"standingcharge":0.17850}}},"power":{"value":0.000,"units":"kW"}}}  # noqa: E501


def calculate_cost_today(meter_data: dict) -> float | None:
    """Return today's cost (standing charge + day kWh * unit rate).

    The IHD publishes ``null`` for the unit rate and/or standing charge when
    the supplier has not sent tariff data to the meter. Rather than raising a
    TypeError on every message, treat a missing component as zero and only
    report unknown (None) when there is no price information at all.
    """
    energy_import = meter_data["energy"]["import"]
    price = energy_import.get("price") or {}
    unit_rate = price.get("unitrate")
    standing_charge = price.get("standingcharge")
    if unit_rate is None and standing_charge is None:
        return None
    return round(
        (standing_charge or 0) + (energy_import.get("day") or 0) * (unit_rate or 0),
        2,
    )


GAS_VOLUME_UNITS = {"m3", "m³", "m^3"}


def gas_volume(js: dict, field: str, units_field: str) -> float | None:
    """Return a gas volume reading only if the IHD reports it in cubic metres.

    Some meters/IHDs populate the volume fields with the kWh figures and say
    so in the accompanying units field (e.g. "dayweekmonthvolunits": "kWh").
    Reporting those as m³ is wrong, and kWh can't be converted to m³ without
    the calorific value, so report the state as unknown instead.
    """
    energy_import = js["gasmeter"]["energy"]["import"]
    units = energy_import.get(units_field)
    if units is not None and str(units).strip().lower() not in GAS_VOLUME_UNITS:
        return None
    return energy_import[field]


STATE_SENSORS = [
    {
        "name": "Smart Meter IHD Software Version",
        "device_class": None,
        "unit_of_measurement": None,
        "state_class": None,
        "entity_category": EntityCategory.DIAGNOSTIC,
        "icon": "mdi:information-outline",
        "func": lambda js: js["software"],
    },
    {
        "name": "Smart Meter IHD Hardware",
        "device_class": None,
        "unit_of_measurement": None,
        "state_class": None,
        "entity_category": EntityCategory.DIAGNOSTIC,
        "icon": "mdi:information-outline",
        "func": lambda js: js["hardware"],
    },
    {
        "name": "Smart Meter IHD HAN Status",
        "device_class": None,
        "unit_of_measurement": None,
        "state_class": None,
        "entity_category": EntityCategory.DIAGNOSTIC,
        "icon": "mdi:information-outline",
        "func": lambda js: js["han"]["status"],
    },
    {
        "name": "Smart Meter IHD HAN RSSI",
        "device_class": SensorDeviceClass.SIGNAL_STRENGTH,
        "unit_of_measurement": SIGNAL_STRENGTH_DECIBELS,
        "state_class": SensorStateClass.MEASUREMENT,
        "entity_category": EntityCategory.DIAGNOSTIC,
        "icon": "mdi:wifi-strength-outline",
        "func": lambda js: js["han"]["rssi"],
    },
    {
        "name": "Smart Meter IHD HAN LQI",
        "device_class": None,
        "unit_of_measurement": None,
        "state_class": SensorStateClass.MEASUREMENT,
        "entity_category": EntityCategory.DIAGNOSTIC,
        "icon": "mdi:wifi-strength-outline",
        "func": lambda js: js["han"]["lqi"],
    },
]

ELECTRICITY_SENSORS = [
    {
        "name": "Smart Meter Electricity: Export",
        "device_class": SensorDeviceClass.ENERGY,
        "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:flash",
        "func": lambda js: js["electricitymeter"]["energy"]["export"]["cumulative"],
    },
    {
        "name": "Smart Meter Electricity: Import",
        "device_class": SensorDeviceClass.ENERGY,
        "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:flash",
        "func": lambda js: js["electricitymeter"]["energy"]["import"]["cumulative"],
        "ignore_zero_values": True,
    },
    {
        "name": "Smart Meter Electricity: Import (Today)",
        "device_class": SensorDeviceClass.ENERGY,
        "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:flash",
        "func": lambda js: js["electricitymeter"]["energy"]["import"]["day"],
    },
    {
        "name": "Smart Meter Electricity: Import (This week)",
        "device_class": SensorDeviceClass.ENERGY,
        "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:flash",
        "func": lambda js: js["electricitymeter"]["energy"]["import"]["week"],
    },
    {
        "name": "Smart Meter Electricity: Import (This month)",
        "device_class": SensorDeviceClass.ENERGY,
        "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:flash",
        "func": lambda js: js["electricitymeter"]["energy"]["import"]["month"],
    },
    {
        "name": "Smart Meter Electricity: Import Unit Rate",
        "device_class": SensorDeviceClass.MONETARY,
        "unit_of_measurement": "GBP/kWh",
        "state_class": SensorStateClass.TOTAL,
        "icon": "mdi:cash",
        "func": lambda js: js["electricitymeter"]["energy"]["import"]["price"][
            "unitrate"
        ],
        "ignore_zero_values": True,
    },
    {
        "name": "Smart Meter Electricity: Import Standing Charge",
        "device_class": SensorDeviceClass.MONETARY,
        "unit_of_measurement": "GBP",
        "state_class": SensorStateClass.TOTAL,
        "icon": "mdi:cash",
        "func": lambda js: js["electricitymeter"]["energy"]["import"]["price"][
            "standingcharge"
        ],
        "ignore_zero_values": True,
    },
    {
        "name": "Smart Meter Electricity: Power",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": UnitOfPower.KILO_WATT,
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:flash",
        "func": lambda js: js["electricitymeter"]["power"]["value"],
        "error_response_values": [-8388.608],
    },
    {
        "name": "Smart Meter Electricity: Cost (Today)",
        "device_class": SensorDeviceClass.MONETARY,
        "unit_of_measurement": "GBP",
        "state_class": SensorStateClass.TOTAL,
        "icon": "mdi:cash",
        "meter_interval": MeterInterval.DAY,
        "func": lambda js: calculate_cost_today(js["electricitymeter"]),
    },
]

GAS_SENSORS = [
    {
        "name": "Smart Meter Gas: Import",
        "device_class": SensorDeviceClass.ENERGY,
        "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:fire",
        "func": lambda js: js["gasmeter"]["energy"]["import"]["cumulative"],
        "ignore_zero_values": True,
    },
    {
        "name": "Smart Meter Gas: Import Vol",
        "device_class": SensorDeviceClass.GAS,
        "unit_of_measurement": UnitOfVolume.CUBIC_METERS,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:fire",
        "func": lambda js: gas_volume(js, "cumulativevol", "cumulativevolunits"),
        "ignore_zero_values": True,
    },
    {
        "name": "Smart Meter Gas: Import Vol (Today)",
        "device_class": SensorDeviceClass.GAS,
        "unit_of_measurement": UnitOfVolume.CUBIC_METERS,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:fire",
        "func": lambda js: gas_volume(js, "dayvol", "dayweekmonthvolunits"),
    },
    {
        "name": "Smart Meter Gas: Import Vol (This week)",
        "device_class": SensorDeviceClass.GAS,
        "unit_of_measurement": UnitOfVolume.CUBIC_METERS,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:fire",
        "func": lambda js: gas_volume(js, "weekvol", "dayweekmonthvolunits"),
    },
    {
        "name": "Smart Meter Gas: Import Vol (This month)",
        "device_class": SensorDeviceClass.GAS,
        "unit_of_measurement": UnitOfVolume.CUBIC_METERS,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:fire",
        "func": lambda js: gas_volume(js, "monthvol", "dayweekmonthvolunits"),
    },
    {
        "name": "Smart Meter Gas: Import (Today)",
        "device_class": SensorDeviceClass.ENERGY,
        "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:fire",
        "func": lambda js: js["gasmeter"]["energy"]["import"]["day"],
    },
    {
        "name": "Smart Meter Gas: Import (This week)",
        "device_class": SensorDeviceClass.ENERGY,
        "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:fire",
        "func": lambda js: js["gasmeter"]["energy"]["import"]["week"],
    },
    {
        "name": "Smart Meter Gas: Import (This month)",
        "device_class": SensorDeviceClass.ENERGY,
        "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:fire",
        "func": lambda js: js["gasmeter"]["energy"]["import"]["month"],
    },
    {
        "name": "Smart Meter Gas: Import Unit Rate",
        "device_class": SensorDeviceClass.MONETARY,
        "unit_of_measurement": "GBP/kWh",
        "state_class": SensorStateClass.TOTAL,
        "icon": "mdi:cash",
        "func": lambda js: js["gasmeter"]["energy"]["import"]["price"]["unitrate"],
        "ignore_zero_values": True,
    },
    {
        "name": "Smart Meter Gas: Import Standing Charge",
        "device_class": SensorDeviceClass.MONETARY,
        "unit_of_measurement": "GBP",
        "state_class": SensorStateClass.TOTAL,
        "icon": "mdi:cash",
        "func": lambda js: js["gasmeter"]["energy"]["import"]["price"][
            "standingcharge"
        ],
        "ignore_zero_values": True,
    },
    # The "Smart Meter Gas: Power" sensor was removed in June 2022, IHD
    # software update 1.8.13 stopped publishing the gas power value
    {
        "name": "Smart Meter Gas: Cost (Today)",
        "device_class": SensorDeviceClass.MONETARY,
        "unit_of_measurement": "GBP",
        "state_class": SensorStateClass.TOTAL,
        "icon": "mdi:cash",
        "meter_interval": MeterInterval.DAY,
        "func": lambda js: calculate_cost_today(js["gasmeter"]),
    },
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Smart Meter sensors."""
    # The config is defaulted to +, which means we subscribe to all devices
    device_mac = hass.data[DOMAIN][config_entry.entry_id][CONF_DEVICE_ID]
    topic_prefix = (
        hass.data[DOMAIN][config_entry.entry_id][CONF_TOPIC_PREFIX]
        or DEFAULT_TOPIC_PREFIX
    )
    time_zone_electricity = hass.data[DOMAIN][config_entry.entry_id][
        CONF_TIME_ZONE_ELECTRICITY
    ]
    time_zone_gas = hass.data[DOMAIN][config_entry.entry_id][CONF_TIME_ZONE_GAS]

    device_update_groups: dict[str, list[HildebrandGlowMqttSensorUpdateGroup]] = {}

    @callback
    async def mqtt_message_received(message: ReceiveMessage) -> None:
        """Handle received MQTT message."""
        topic = message.topic
        payload = message.payload
        device_id = topic.split("/")[1]
        if device_mac in (DEFAULT_DEVICE_ID, device_id):
            update_groups = await async_get_device_groups(
                device_update_groups,
                async_add_entities,
                device_id,
                time_zone_electricity,
                time_zone_gas,
            )
            _LOGGER.debug("Received message: %s", topic)
            _LOGGER.debug("  Payload: %s", payload)
            for update_group in update_groups:
                update_group.process_update(message)

    data_topic = f"{topic_prefix}/#"

    await mqtt.async_subscribe(hass, data_topic, mqtt_message_received, 1)


async def async_get_device_groups(
    device_update_groups: dict[str, list[HildebrandGlowMqttSensorUpdateGroup]],
    async_add_entities: AddEntitiesCallback,
    device_id: str,
    time_zone_electricity: str | None,
    time_zone_gas: str | None,
) -> list[HildebrandGlowMqttSensorUpdateGroup]:
    """Return a device's update groups, adding its sensors when first seen."""
    if device_id not in device_update_groups:
        _LOGGER.debug("New device found: %s", device_id)
        groups = [
            HildebrandGlowMqttSensorUpdateGroup(device_id, "STATE", STATE_SENSORS),
            HildebrandGlowMqttSensorUpdateGroup(
                device_id,
                "electricitymeter",
                ELECTRICITY_SENSORS,
                time_zone_electricity,
            ),
            HildebrandGlowMqttSensorUpdateGroup(
                device_id,
                "gasmeter",
                GAS_SENSORS,
                time_zone_gas,
            ),
        ]
        async_add_entities(
            [
                sensor_entity
                for update_group in groups
                for sensor_entity in update_group.all_sensors
            ],
            # True
        )
        device_update_groups[device_id] = groups

    return device_update_groups[device_id]


class HildebrandGlowMqttSensorUpdateGroup:
    """Hildebrand Glow MQTT meter sensors that are all updated together."""

    def __init__(
        self,
        device_id: str,
        topic_regex: str,
        meters: Iterable[dict[str, Any]],
        time_zone: str | None = None,
    ) -> None:
        """Initialize the sensor collection."""
        self._topic_regex = re.compile(topic_regex)
        self._sensors = [
            HildebrandGlowMqttSensor(device_id=device_id, time_zone=time_zone, **meter)
            for meter in meters
        ]

    def process_update(self, message: ReceiveMessage) -> None:
        """Process an update from the MQTT broker."""
        topic = message.topic
        payload = message.payload
        if self._topic_regex.search(topic):
            _LOGGER.debug("Matched on %s", self._topic_regex.pattern)
            parsed_data = json.loads(payload)
            for sensor in self._sensors:
                sensor.process_update(parsed_data)

    @property
    def all_sensors(self) -> Iterable[HildebrandGlowMqttSensor]:
        """Return all meters."""
        return self._sensors


class HildebrandGlowMqttSensor(SensorEntity):
    """Representation of a room sensor that is updated via MQTT."""

    def __init__(  # noqa: PLR0913
        self,
        *,
        device_id: str,
        time_zone: str | None,
        name: str,
        icon: str,
        device_class: SensorDeviceClass | None,
        unit_of_measurement: str | None,
        state_class: SensorStateClass | None,
        func: Callable[[dict[str, Any]], Any],
        entity_category: EntityCategory | None = None,
        ignore_zero_values: bool = False,
        error_response_values: Iterable[Any] | None = None,
        meter_interval: MeterInterval | None = None,
    ) -> None:
        """Initialize the sensor."""
        self._device_id = device_id
        self._time_zone = time_zone
        self._attr_name = name
        self._attr_icon = icon
        if device_class:
            self._attr_device_class = device_class
        if unit_of_measurement:
            self._attr_native_unit_of_measurement = unit_of_measurement
        if state_class:
            self._attr_state_class = state_class
        self._attr_unique_id = slugify(device_id + "_" + name)
        self._attr_should_poll = False
        self._func = func
        self._attr_entity_category = entity_category
        self._ignore_zero_values = ignore_zero_values
        self._error_response_values = error_response_values
        self._meter_interval = meter_interval
        self._attr_device_info = DeviceInfo(
            connections={("mac", device_id)},
            manufacturer="Hildebrand Technology Limited",
            model="Glow Smart Meter IHD",
            name=f"Glow Smart Meter {device_id}",
        )
        self._attr_native_value = None
        if state_class == SensorStateClass.TOTAL and meter_interval:
            self._attr_last_reset = None
            self._last_reset_reported = True

    @staticmethod
    def determine_last_reset(
        message_datetime: datetime,
        meter_timezone: tzinfo,
        meter_interval: MeterInterval,
    ) -> datetime:
        """Return midnight of the meter's reset interval in UTC."""
        meter_datetime = message_datetime.astimezone(meter_timezone)
        meter_midnight = datetime.combine(
            meter_datetime.date(),
            time.min,
            meter_datetime.tzinfo,
        )
        if meter_interval == MeterInterval.DAY:
            last_reset = meter_midnight
        elif meter_interval == MeterInterval.WEEK:
            last_reset = meter_midnight - timedelta(days=meter_midnight.weekday())
        elif meter_interval == MeterInterval.MONTH:
            last_reset = meter_midnight.replace(day=1)
        elif meter_interval == MeterInterval.YEAR:
            last_reset = meter_midnight.replace(day=1, month=1)
        return last_reset.astimezone(ZoneInfo("UTC"))

    @staticmethod
    def get_message_datetime(mqtt_data: dict[str, Any]) -> datetime:
        """Return the message timestamp as a datetime."""
        timestamp = (
            mqtt_data.get("timestamp")
            or mqtt_data.get("electricitymeter", {}).get("timestamp")
            or mqtt_data.get("gasmeter", {}).get("timestamp")
        )
        try:
            return datetime.fromisoformat(timestamp)
        except (TypeError, ValueError) as err:
            msg = "Valid timestamp not present in MQTT data."
            raise ValueError(msg) from err

    def process_update(self, mqtt_data: dict[str, Any]) -> None:
        """Update the state of the sensor."""
        try:
            new_value = self._func(mqtt_data)
        except (KeyError, IndexError, TypeError) as err:
            # A field this sensor depends on is missing or null in the payload
            # (e.g. no tariff data from the supplier). Report the state as
            # unknown instead of raising, so the other sensors in the same
            # update group are still processed.
            _LOGGER.debug(
                "Unable to read value for %s from payload (%r), state unknown.",
                self._attr_unique_id,
                err,
            )
            new_value = None
        if self._ignore_zero_values and new_value == 0:
            _LOGGER.debug(
                "Ignored new value of %s on %s.",
                new_value,
                self._attr_unique_id,
            )
            return
        if self._error_response_values and new_value in self._error_response_values:
            _LOGGER.debug(
                "Received error response value of %s on %s, state unknown.",
                new_value,
                self._attr_unique_id,
            )
            new_value = None
        self._attr_native_value = new_value

        zone_info = None
        if self._time_zone:
            zone_info = self._time_zone
        elif self.hass is not None and self.hass.config is not None:
            zone_info = self.hass.config.time_zone

        if zone_info and self._last_reset_reported and self._meter_interval:
            self._attr_last_reset = self.determine_last_reset(
                self.get_message_datetime(mqtt_data),
                ZoneInfo(zone_info),
                self._meter_interval,
            )

        # The entity has no hass object until it is added, skip the state
        # update until then
        if self.hass is not None:
            self.async_schedule_update_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        return {ATTR_DEVICE_ID: self._device_id}
