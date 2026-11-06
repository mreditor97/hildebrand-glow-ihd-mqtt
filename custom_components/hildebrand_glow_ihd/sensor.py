"""Sensors for the Home Assistant Hildebrand Glow IHD Integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components import mqtt
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    SIGNAL_STRENGTH_DECIBELS,
    EntityCategory,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfVolume,
)
from homeassistant.core import callback
from homeassistant.util.json import json_loads

from .const import (
    DEFAULT_DEVICE_ID,
    POWER_ERROR_VALUE,
    TOPIC_ELECTRICITY_METER,
    TOPIC_GAS_METER,
    TOPIC_STATE,
    MeterInterval,
)
from .entity import GlowEntity
from .helpers import (
    calculate_cost_today,
    determine_last_reset,
    gas_volume,
    message_datetime,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import tzinfo

    from homeassistant.components.mqtt import ReceiveMessage
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .models import GlowConfigEntry

_LOGGER = logging.getLogger(__name__)

# Example payloads:
# glow/XXXXXXYYYYYY/STATE                   {"software":"v1.8.12","timestamp":"2022-06-11T20:54:53Z","hardware":"GLOW-IHD-01-1v4-SMETS2","ethmac":"1234567890AB","smetsversion":"SMETS2","eui":"12:34:56:78:91:23:45","zigbee":"1.2.5","han":{"rssi":-75,"status":"joined","lqi":100}}  # noqa: E501
# glow/XXXXXXYYYYYY/SENSOR/electricitymeter {"electricitymeter":{"timestamp":"2022-06-11T20:38:00Z","energy":{"export":{"cumulative":0.000,"units":"kWh"},"import":{"cumulative":6613.405,"day":13.252,"week":141.710,"month":293.598,"units":"kWh","mpan":"1234","supplier":"ABC ENERGY","price":{"unitrate":0.04998,"standingcharge":0.24030}}},"power":{"value":0.951,"units":"kW"}}}  # noqa: E501
# glow/XXXXXXYYYYYY/SENSOR/gasmeter         {"gasmeter":{"timestamp":"2022-06-11T20:53:52Z","energy":{"export":{"cumulative":0.000,"units":"kWh"},"import":{"cumulative":17940.852,"day":11.128,"week":104.749,"month":217.122,"units":"kWh","mprn":"1234","supplier":"---","price":{"unitrate":0.07320,"standingcharge":0.17850}}},"power":{"value":0.000,"units":"kW"}}}  # noqa: E501


@dataclass(frozen=True, kw_only=True)
class GlowSensorEntityDescription(SensorEntityDescription):
    """Describes a sensor read from a Glow MQTT payload."""

    # The sensor's name before it was translated. Existing installs rely on
    # the unique ID made from it, so it must not change.
    unique_id_name: str
    value_fn: Callable[[dict[str, Any]], Any]
    # Keep the previous state when the IHD reports 0
    ignore_zero_values: bool = False
    # Values the IHD reports when it can't read the meter
    error_values: tuple[float, ...] = ()
    # Set for sensors that reset, so last_reset can be reported
    meter_interval: MeterInterval | None = None


STATE_SENSORS: tuple[GlowSensorEntityDescription, ...] = (
    GlowSensorEntityDescription(
        key="software_version",
        translation_key="software_version",
        unique_id_name="Smart Meter IHD Software Version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda js: js["software"],
    ),
    GlowSensorEntityDescription(
        key="hardware",
        translation_key="hardware",
        unique_id_name="Smart Meter IHD Hardware",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda js: js["hardware"],
    ),
    GlowSensorEntityDescription(
        key="han_status",
        translation_key="han_status",
        unique_id_name="Smart Meter IHD HAN Status",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda js: js["han"]["status"],
    ),
    GlowSensorEntityDescription(
        key="han_rssi",
        translation_key="han_rssi",
        unique_id_name="Smart Meter IHD HAN RSSI",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda js: js["han"]["rssi"],
    ),
    GlowSensorEntityDescription(
        key="han_lqi",
        translation_key="han_lqi",
        unique_id_name="Smart Meter IHD HAN LQI",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda js: js["han"]["lqi"],
    ),
)

ELECTRICITY_SENSORS: tuple[GlowSensorEntityDescription, ...] = (
    GlowSensorEntityDescription(
        key="electricity_export",
        translation_key="electricity_export",
        unique_id_name="Smart Meter Electricity: Export",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda js: js["electricitymeter"]["energy"]["export"]["cumulative"],
    ),
    GlowSensorEntityDescription(
        key="electricity_import",
        translation_key="electricity_import",
        unique_id_name="Smart Meter Electricity: Import",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda js: js["electricitymeter"]["energy"]["import"]["cumulative"],
        ignore_zero_values=True,
    ),
    GlowSensorEntityDescription(
        key="electricity_import_today",
        translation_key="electricity_import_today",
        unique_id_name="Smart Meter Electricity: Import (Today)",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda js: js["electricitymeter"]["energy"]["import"]["day"],
    ),
    GlowSensorEntityDescription(
        key="electricity_import_week",
        translation_key="electricity_import_week",
        unique_id_name="Smart Meter Electricity: Import (This week)",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda js: js["electricitymeter"]["energy"]["import"]["week"],
    ),
    GlowSensorEntityDescription(
        key="electricity_import_month",
        translation_key="electricity_import_month",
        unique_id_name="Smart Meter Electricity: Import (This month)",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda js: js["electricitymeter"]["energy"]["import"]["month"],
    ),
    GlowSensorEntityDescription(
        key="electricity_unit_rate",
        translation_key="electricity_unit_rate",
        unique_id_name="Smart Meter Electricity: Import Unit Rate",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="GBP/kWh",
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda js: js["electricitymeter"]["energy"]["import"]["price"][
            "unitrate"
        ],
        ignore_zero_values=True,
    ),
    GlowSensorEntityDescription(
        key="electricity_standing_charge",
        translation_key="electricity_standing_charge",
        unique_id_name="Smart Meter Electricity: Import Standing Charge",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="GBP",
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda js: js["electricitymeter"]["energy"]["import"]["price"][
            "standingcharge"
        ],
        ignore_zero_values=True,
    ),
    GlowSensorEntityDescription(
        key="electricity_power",
        translation_key="electricity_power",
        unique_id_name="Smart Meter Electricity: Power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda js: js["electricitymeter"]["power"]["value"],
        error_values=(POWER_ERROR_VALUE,),
    ),
    GlowSensorEntityDescription(
        key="electricity_cost_today",
        translation_key="electricity_cost_today",
        unique_id_name="Smart Meter Electricity: Cost (Today)",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="GBP",
        state_class=SensorStateClass.TOTAL,
        meter_interval=MeterInterval.DAY,
        value_fn=lambda js: calculate_cost_today(js["electricitymeter"]),
    ),
)

GAS_SENSORS: tuple[GlowSensorEntityDescription, ...] = (
    GlowSensorEntityDescription(
        key="gas_import",
        translation_key="gas_import",
        unique_id_name="Smart Meter Gas: Import",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda js: js["gasmeter"]["energy"]["import"]["cumulative"],
        ignore_zero_values=True,
    ),
    GlowSensorEntityDescription(
        key="gas_import_volume",
        translation_key="gas_import_volume",
        unique_id_name="Smart Meter Gas: Import Vol",
        device_class=SensorDeviceClass.GAS,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda js: gas_volume(js, "cumulativevol", "cumulativevolunits"),
        ignore_zero_values=True,
    ),
    GlowSensorEntityDescription(
        key="gas_import_volume_today",
        translation_key="gas_import_volume_today",
        unique_id_name="Smart Meter Gas: Import Vol (Today)",
        device_class=SensorDeviceClass.GAS,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda js: gas_volume(js, "dayvol", "dayweekmonthvolunits"),
    ),
    GlowSensorEntityDescription(
        key="gas_import_volume_week",
        translation_key="gas_import_volume_week",
        unique_id_name="Smart Meter Gas: Import Vol (This week)",
        device_class=SensorDeviceClass.GAS,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda js: gas_volume(js, "weekvol", "dayweekmonthvolunits"),
    ),
    GlowSensorEntityDescription(
        key="gas_import_volume_month",
        translation_key="gas_import_volume_month",
        unique_id_name="Smart Meter Gas: Import Vol (This month)",
        device_class=SensorDeviceClass.GAS,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda js: gas_volume(js, "monthvol", "dayweekmonthvolunits"),
    ),
    GlowSensorEntityDescription(
        key="gas_import_today",
        translation_key="gas_import_today",
        unique_id_name="Smart Meter Gas: Import (Today)",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda js: js["gasmeter"]["energy"]["import"]["day"],
    ),
    GlowSensorEntityDescription(
        key="gas_import_week",
        translation_key="gas_import_week",
        unique_id_name="Smart Meter Gas: Import (This week)",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda js: js["gasmeter"]["energy"]["import"]["week"],
    ),
    GlowSensorEntityDescription(
        key="gas_import_month",
        translation_key="gas_import_month",
        unique_id_name="Smart Meter Gas: Import (This month)",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda js: js["gasmeter"]["energy"]["import"]["month"],
    ),
    GlowSensorEntityDescription(
        key="gas_unit_rate",
        translation_key="gas_unit_rate",
        unique_id_name="Smart Meter Gas: Import Unit Rate",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="GBP/kWh",
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda js: js["gasmeter"]["energy"]["import"]["price"]["unitrate"],
        ignore_zero_values=True,
    ),
    GlowSensorEntityDescription(
        key="gas_standing_charge",
        translation_key="gas_standing_charge",
        unique_id_name="Smart Meter Gas: Import Standing Charge",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="GBP",
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda js: js["gasmeter"]["energy"]["import"]["price"][
            "standingcharge"
        ],
        ignore_zero_values=True,
    ),
    # The "Smart Meter Gas: Power" sensor was removed in June 2022, IHD
    # software update 1.8.13 stopped publishing the gas power value
    GlowSensorEntityDescription(
        key="gas_cost_today",
        translation_key="gas_cost_today",
        unique_id_name="Smart Meter Gas: Cost (Today)",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="GBP",
        state_class=SensorStateClass.TOTAL,
        meter_interval=MeterInterval.DAY,
        value_fn=lambda js: calculate_cost_today(js["gasmeter"]),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GlowConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Glow sensors, adding each device's when it first publishes."""
    settings = entry.runtime_data
    prefix = f"{settings.topic_prefix}/"
    # The time zone each topic's resets are reported in
    topic_time_zones: dict[str, tzinfo | None] = {
        TOPIC_STATE: None,
        TOPIC_ELECTRICITY_METER: settings.time_zone_electricity,
        TOPIC_GAS_METER: settings.time_zone_gas,
    }
    # The sensors of each device found so far, by the topic that updates them
    devices: dict[str, dict[str, list[GlowSensor]]] = {}

    @callback
    def async_add_device(device_id: str) -> dict[str, list[GlowSensor]]:
        """Add the sensors of a newly found device."""
        _LOGGER.debug("New Glow device found: %s", device_id)
        sensors = {
            topic: [
                GlowSensor(device_id, description, topic_time_zones[topic])
                for description in descriptions
            ]
            for topic, descriptions in (
                (TOPIC_STATE, STATE_SENSORS),
                (TOPIC_ELECTRICITY_METER, ELECTRICITY_SENSORS),
                (TOPIC_GAS_METER, GAS_SENSORS),
            )
        }
        async_add_entities(
            sensor for topic_sensors in sensors.values() for sensor in topic_sensors
        )
        devices[device_id] = sensors
        return sensors

    @callback
    def async_message_received(message: ReceiveMessage) -> None:
        """Update a device's sensors from an MQTT message."""
        topic = message.topic
        if not topic.startswith(prefix):
            return
        device_id, _, rest = topic.removeprefix(prefix).partition("/")
        topic_name = rest.rpartition("/")[2]
        if topic_name not in topic_time_zones:
            return
        if settings.device_id not in (DEFAULT_DEVICE_ID, device_id):
            return

        _LOGGER.debug("Received message on %s: %s", topic, message.payload)
        try:
            payload = json_loads(message.payload)
        except ValueError:
            _LOGGER.debug("Ignored message on %s, it is not valid JSON", topic)
            return
        if not isinstance(payload, dict):
            _LOGGER.debug("Ignored message on %s, it is not a JSON object", topic)
            return

        sensors = devices.get(device_id) or async_add_device(device_id)
        for sensor in sensors[topic_name]:
            sensor.async_process_payload(payload)

    # Subscribe to one device's topics when one is set, otherwise to all
    device_topic = (
        "+" if settings.device_id == DEFAULT_DEVICE_ID else settings.device_id
    )
    entry.async_on_unload(
        await mqtt.async_subscribe(
            hass,
            f"{prefix}{device_topic}/#",
            async_message_received,
            qos=1,
        ),
    )


class GlowSensor(GlowEntity, SensorEntity):
    """A sensor of a Glow device."""

    entity_description: GlowSensorEntityDescription

    def __init__(
        self,
        device_id: str,
        description: GlowSensorEntityDescription,
        time_zone: tzinfo | None,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(device_id, description, description.unique_id_name)
        self._time_zone = time_zone
        self._attr_native_value = None
        if description.meter_interval is not None:
            self._attr_last_reset = None

    @callback
    def async_process_payload(self, payload: dict[str, Any]) -> None:
        """Update the sensor from an MQTT payload."""
        description = self.entity_description
        try:
            value = description.value_fn(payload)
        except (KeyError, IndexError, TypeError) as err:
            # A field this sensor depends on is missing or null in the payload
            # (e.g. no tariff data from the supplier). Report the state as
            # unknown instead of raising, so the other sensors of the same
            # topic are still updated.
            _LOGGER.debug(
                "Unable to read value for %s from payload (%r), state unknown",
                self.unique_id,
                err,
            )
            value = None

        if description.ignore_zero_values and value == 0:
            _LOGGER.debug("Ignored value of 0 for %s", self.unique_id)
            return
        if value in description.error_values:
            _LOGGER.debug(
                "Received error value %s for %s, state unknown",
                value,
                self.unique_id,
            )
            value = None
        self._attr_native_value = value

        if (
            description.meter_interval is not None
            and self._time_zone is not None
            and (message_time := message_datetime(payload)) is not None
        ):
            self._attr_last_reset = determine_last_reset(
                message_time,
                self._time_zone,
                description.meter_interval,
            )

        self.async_write_state_if_added()
