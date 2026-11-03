"""Support for hildebrand glow MQTT sensors."""

from __future__ import annotations
from datetime import datetime, time, timedelta, tzinfo
import json
import logging
import re
from typing import Iterable
from zoneinfo import ZoneInfo

from homeassistant.components import mqtt
from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
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
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity
from homeassistant.util import dt as dt_util, slugify

from .const import (
    CONF_TIME_ZONE_ELECTRICITY,
    CONF_TIME_ZONE_GAS,
    CONF_TOPIC_PREFIX,
    DEFAULT_DEVICE_ID,
    DEFAULT_TOPIC_PREFIX,
    DOMAIN,
    MeterInterval,
)

_LOGGER = logging.getLogger(__name__)

# glow/XXXXXXYYYYYY/STATE                   {"software":"v1.8.12","timestamp":"2022-06-11T20:54:53Z","hardware":"GLOW-IHD-01-1v4-SMETS2","ethmac":"1234567890AB","smetsversion":"SMETS2","eui":"12:34:56:78:91:23:45","zigbee":"1.2.5","han":{"rssi":-75,"status":"joined","lqi":100}}
# glow/XXXXXXYYYYYY/SENSOR/electricitymeter {"electricitymeter":{"timestamp":"2022-06-11T20:38:00Z","energy":{"export":{"cumulative":0.000,"units":"kWh"},"import":{"cumulative":6613.405,"day":13.252,"week":141.710,"month":293.598,"units":"kWh","mpan":"1234","supplier":"ABC ENERGY","price":{"unitrate":0.04998,"standingcharge":0.24030}}},"power":{"value":0.951,"units":"kW"}}}
# glow/XXXXXXYYYYYY/SENSOR/gasmeter         {"gasmeter":{"timestamp":"2022-06-11T20:53:52Z","energy":{"export":{"cumulative":0.000,"units":"kWh"},"import":{"cumulative":17940.852,"day":11.128,"week":104.749,"month":217.122,"units":"kWh","mprn":"1234","supplier":"---","price":{"unitrate":0.07320,"standingcharge":0.17850}}},"power":{"value":0.000,"units":"kW"}}}

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
        "entity_class": "cost",
        "cost_meter": "electricitymeter",
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
        "func": lambda js: js["gasmeter"]["energy"]["import"]["cumulativevol"],
        "ignore_zero_values": True,
    },
    {
        "name": "Smart Meter Gas: Import Vol (Today)",
        "device_class": SensorDeviceClass.GAS,
        "unit_of_measurement": UnitOfVolume.CUBIC_METERS,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:fire",
        "func": lambda js: js["gasmeter"]["energy"]["import"]["dayvol"],
    },
    {
        "name": "Smart Meter Gas: Import Vol (This week)",
        "device_class": SensorDeviceClass.GAS,
        "unit_of_measurement": UnitOfVolume.CUBIC_METERS,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:fire",
        "func": lambda js: js["gasmeter"]["energy"]["import"]["weekvol"],
    },
    {
        "name": "Smart Meter Gas: Import Vol (This month)",
        "device_class": SensorDeviceClass.GAS,
        "unit_of_measurement": UnitOfVolume.CUBIC_METERS,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:fire",
        "func": lambda js: js["gasmeter"]["energy"]["import"]["monthvol"],
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
    # Removed June 2022 in IHD software update 1.8.13
    # {
    #   "name": "Smart Meter Gas: Power",
    #   "device_class": SensorDeviceClass.POWER,
    #   "unit_of_measurement": UnitOfPower.KILO_WATT,
    #   "state_class": SensorStateClass.MEASUREMENT,
    #   "icon": "mdi:fire",
    #   "func": lambda js : js['gasmeter']['power']['value'],
    # },
    {
        "name": "Smart Meter Gas: Cost (Today)",
        "device_class": SensorDeviceClass.MONETARY,
        "unit_of_measurement": "GBP",
        "state_class": SensorStateClass.TOTAL,
        "icon": "mdi:cash",
        "entity_class": "cost",
        "cost_meter": "gasmeter",
    },
]


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the Smart Meter sensors."""

    # the config is defaulted to + which happens to mean we will subscribe to all devices
    device_mac = hass.data[DOMAIN][config_entry.entry_id][CONF_DEVICE_ID]
    topic_prefix = hass.data[DOMAIN][config_entry.entry_id][CONF_TOPIC_PREFIX] or DEFAULT_TOPIC_PREFIX
    time_zone_electricity = hass.data[DOMAIN][config_entry.entry_id][
        CONF_TIME_ZONE_ELECTRICITY
    ]
    time_zone_gas = hass.data[DOMAIN][config_entry.entry_id][CONF_TIME_ZONE_GAS]

    deviceUpdateGroups = {}

    @callback
    async def mqtt_message_received(message: ReceiveMessage):
        """Handle received MQTT message."""
        topic = message.topic
        payload = message.payload
        device_id = topic.split("/")[1]
        if device_mac == DEFAULT_DEVICE_ID or device_id == device_mac:
            updateGroups = await async_get_device_groups(
                deviceUpdateGroups,
                async_add_entities,
                device_id,
                time_zone_electricity,
                time_zone_gas,
            )
            _LOGGER.debug("Received message: %s", topic)
            _LOGGER.debug("  Payload: %s", payload)
            for updateGroup in updateGroups:
                updateGroup.process_update(message)

    data_topic = f"{topic_prefix}/#"

    await mqtt.async_subscribe(hass, data_topic, mqtt_message_received, 1)


async def async_get_device_groups(
    deviceUpdateGroups,
    async_add_entities,
    device_id,
    time_zone_electricity,
    time_zone_gas,
):
    # add to update groups if not already there
    if device_id not in deviceUpdateGroups:
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
                device_id, "gasmeter", GAS_SENSORS, time_zone_gas
            ),
        ]
        async_add_entities(
            [
                sensorEntity
                for updateGroup in groups
                for sensorEntity in updateGroup.all_sensors
            ],
            # True
        )
        deviceUpdateGroups[device_id] = groups

    return deviceUpdateGroups[device_id]


def _create_sensor(entity_class: str | None = None, **kwargs) -> HildebrandGlowMqttSensor:
    """Create the sensor entity described by a sensor definition."""
    if entity_class == "cost":
        return HildebrandGlowMqttCostSensor(**kwargs)
    return HildebrandGlowMqttSensor(**kwargs)


class HildebrandGlowMqttSensorUpdateGroup:
    """Representation of Hildebrand Glow MQTT Meter Sensors that all get updated together."""

    def __init__(
        self, device_id: str, topic_regex: str, meters: Iterable, time_zone: str | None = None
    ) -> None:
        """Initialize the sensor collection."""
        self._topic_regex = re.compile(topic_regex)
        self._sensors = [
            _create_sensor(device_id=device_id, time_zone=time_zone, **meter)
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

    def __init__(
        self,
        device_id,
        time_zone,
        name,
        icon,
        device_class,
        unit_of_measurement,
        state_class,
        func,
        entity_category=None,
        ignore_zero_values=False,
        error_response_values=None,
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
        message_datetime: datetime, meter_timezone: tzinfo, meter_interval: MeterInterval
    ) -> datetime:
        """Return midnight of the meter's reset interval in UTC."""
        meter_datetime = message_datetime.astimezone(meter_timezone)
        meter_midnight = datetime.combine(
            meter_datetime.date(), time.min, meter_datetime.tzinfo
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
    def get_message_datetime(mqtt_data) -> datetime:
        """Return the message timestamp as a datetime."""
        timestamp = (
            mqtt_data.get("timestamp")
            or mqtt_data.get("electricitymeter", {}).get("timestamp")
            or mqtt_data.get("gasmeter", {}).get("timestamp")
        )
        try:
            return datetime.fromisoformat(timestamp)
        except (TypeError, ValueError) as err:
            raise ValueError("Valid timestamp not present in MQTT data.") from err

    def process_update(self, mqtt_data) -> None:
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
                "Ignored new value of %s on %s.", new_value, self._attr_unique_id
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

        zoneInfo = None
        if self._time_zone:
            zoneInfo = self._time_zone
        elif (self.hass is not None and 
              self.hass.config is not None):
            zoneInfo = self.hass.config.time_zone
            
        if zoneInfo and self._last_reset_reported and self._meter_interval:
            self._attr_last_reset = self.determine_last_reset(
                self.get_message_datetime(mqtt_data),
                ZoneInfo(zoneInfo),
                self._meter_interval
            )

        if (
            self.hass is not None
        ):  # this is a hack to get around the fact that the entity is not yet initialized at first
            self.async_schedule_update_ha_state()

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return {ATTR_DEVICE_ID: self._device_id}


# A drop in the day's kWh to below this fraction of the highest value seen in
# the current cycle is treated as the meter resetting its daily total. Smaller
# drops are treated as meter corrections and ignored.
COST_RESET_RATIO = 0.9
# If no message has been processed for longer than this (e.g. Home Assistant
# was stopped), the day total can't be compared reliably, so start a new cycle.
COST_STALE_AFTER = timedelta(hours=24)


class HildebrandGlowCostExtraStoredData(ExtraStoredData):
    """Accrual state for the cost sensor, persisted across restarts."""

    def __init__(self, data: dict) -> None:
        """Initialise the stored data."""
        self.data = data

    def as_dict(self) -> dict:
        """Return a dict representation of the stored data."""
        return self.data


class HildebrandGlowMqttCostSensor(HildebrandGlowMqttSensor, RestoreEntity):
    """Today's cost (standing charge + energy used today), accrued per message.

    The IHD only publishes the day's total kWh and the *current* unit rate.
    Multiplying the two revalues everything used so far today whenever the
    rate changes (time-of-use / Economy 7 tariffs), producing jumps up when the
    rate rises and negative "costs" when it falls. Instead, each increase in the
    day's kWh is priced at the unit rate in force when it was reported.

    A new cycle (and ``last_reset``) starts when the meter's daily total
    actually resets, rather than at a fixed clock time, so meters whose day
    rolls over at a different time to the configured time zone (e.g. gas
    meters on UTC) don't produce a negative value at the start of the day.
    """

    def __init__(self, cost_meter: str, **kwargs) -> None:
        """Initialize the sensor."""
        super().__init__(func=None, **kwargs)
        self._cost_meter = cost_meter
        self._accrued: float | None = None
        self._standing_charge: float | None = None
        self._cycle_kwh: float | None = None
        self._last_rate: float | None = None
        self._last_message_time: datetime | None = None
        self._attr_last_reset = None

    async def async_added_to_hass(self) -> None:
        """Restore the accrual state."""
        await super().async_added_to_hass()
        if (extra_data := await self.async_get_last_extra_data()) is None:
            return
        data = extra_data.as_dict()
        try:
            self._accrued = data.get("accrued")
            self._standing_charge = data.get("standing_charge")
            self._cycle_kwh = data.get("cycle_kwh")
            self._last_rate = data.get("last_rate")
            self._attr_last_reset = _parse_datetime(data.get("last_reset"))
            self._last_message_time = _parse_datetime(data.get("last_message_time"))
        except (TypeError, ValueError):
            _LOGGER.debug("Unable to restore state of %s", self._attr_unique_id)
            self._accrued = self._standing_charge = self._cycle_kwh = None
            self._last_rate = self._attr_last_reset = self._last_message_time = None
            return
        self._attr_native_value = self._current_cost()

    @property
    def extra_restore_state_data(self) -> HildebrandGlowCostExtraStoredData:
        """Return the accrual state to be persisted."""
        return HildebrandGlowCostExtraStoredData(
            {
                "accrued": self._accrued,
                "standing_charge": self._standing_charge,
                "cycle_kwh": self._cycle_kwh,
                "last_rate": self._last_rate,
                "last_reset": _format_datetime(self._attr_last_reset),
                "last_message_time": _format_datetime(self._last_message_time),
            }
        )

    def _current_cost(self) -> float | None:
        if self._accrued is None and self._standing_charge is None:
            return None
        return round((self._standing_charge or 0) + (self._accrued or 0), 2)

    def _meter_time_zone(self) -> ZoneInfo:
        if self._time_zone:
            return ZoneInfo(self._time_zone)
        if self.hass is not None and self.hass.config is not None:
            return ZoneInfo(self.hass.config.time_zone)
        return ZoneInfo("UTC")

    def _is_new_cycle(
        self, day_kwh: float, message_time: datetime, cycle_start: datetime
    ) -> bool:
        if self._cycle_kwh is None or self._attr_last_reset is None:
            return True
        if (
            self._last_message_time is not None
            and message_time - self._last_message_time > COST_STALE_AFTER
        ):
            return True
        if day_kwh < self._cycle_kwh * COST_RESET_RATIO:
            # The meter has reset its daily total.
            return True
        # A new day with nothing used yet: the kWh total can't drop, so fall
        # back to the clock to pick up the new day's standing charge.
        return day_kwh == 0 and cycle_start > self._attr_last_reset

    def process_update(self, mqtt_data) -> None:
        """Update the state of the sensor."""
        try:
            energy_import = mqtt_data[self._cost_meter]["energy"]["import"]
            day_kwh = energy_import["day"]
            price = energy_import.get("price") or {}
            unit_rate = price.get("unitrate")
            standing_charge = price.get("standingcharge")
        except (KeyError, TypeError, AttributeError) as err:
            _LOGGER.debug(
                "Unable to read cost data for %s from payload (%r).",
                self._attr_unique_id,
                err,
            )
            return
        if day_kwh is None:
            return

        if unit_rate is not None:
            self._last_rate = unit_rate
        rate = self._last_rate

        try:
            message_time = self.get_message_datetime(mqtt_data)
        except ValueError:
            message_time = dt_util.utcnow()
        cycle_start = self.determine_last_reset(
            message_time, self._meter_time_zone(), MeterInterval.DAY
        )

        if self._is_new_cycle(day_kwh, message_time, cycle_start):
            _LOGGER.debug("Starting new cost cycle for %s", self._attr_unique_id)
            # Usage already on the meter at the start of a cycle can only be
            # priced at the current rate.
            self._accrued = day_kwh * rate if rate is not None else None
            self._standing_charge = standing_charge
            self._cycle_kwh = day_kwh
            if self._attr_last_reset is None or cycle_start > self._attr_last_reset:
                self._attr_last_reset = cycle_start
            else:
                # The meter reset at a different time to midnight in the
                # configured time zone; last_reset must still move forward.
                self._attr_last_reset = message_time.astimezone(ZoneInfo("UTC"))
        else:
            if day_kwh > self._cycle_kwh:
                if rate is not None:
                    if self._accrued is None:
                        self._accrued = day_kwh * rate
                    else:
                        self._accrued += (day_kwh - self._cycle_kwh) * rate
                self._cycle_kwh = day_kwh
            elif self._accrued is None and rate is not None:
                self._accrued = day_kwh * rate
            if self._standing_charge is None:
                self._standing_charge = standing_charge

        self._last_message_time = message_time
        self._attr_native_value = self._current_cost()

        if self.hass is not None:
            self.async_schedule_update_ha_state()


def _format_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None
