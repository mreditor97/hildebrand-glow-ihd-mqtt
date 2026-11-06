"""Helpers for the Home Assistant Hildebrand Glow IHD Integration."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta, tzinfo
from typing import Any

from .const import (
    DEFAULT_DEVICE_ID,
    DEFAULT_TITLE,
    DEFAULT_TOPIC_PREFIX,
    GAS_VOLUME_UNITS,
    MeterInterval,
)


def entry_title(device_id: str | None) -> str:
    """Return the config entry title for a configured device ID."""
    device_id = (device_id or "").strip()
    if not device_id or device_id == DEFAULT_DEVICE_ID:
        return DEFAULT_TITLE
    return f"{DEFAULT_TITLE} ({device_id})"


def normalize_device_id(device_id: str | None) -> str:
    """Return a device ID in the form the IHD uses in its MQTT topics.

    The ID is the device's MAC address in upper case without separators,
    e.g. ``AABBCCDDEEFF``. ``+`` matches every device.
    """
    normalized = (device_id or "").strip().upper().replace(":", "").replace(" ", "")
    return normalized or DEFAULT_DEVICE_ID


def normalize_topic_prefix(topic_prefix: str | None) -> str:
    """Return a topic prefix with wildcards, spaces and slashes removed."""
    normalized = (topic_prefix or "").strip().replace("#", "").replace(" ", "")
    return normalized.strip("/") or DEFAULT_TOPIC_PREFIX


def calculate_cost_today(meter_data: dict[str, Any]) -> float | None:
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


def gas_volume(payload: dict[str, Any], field: str, units_field: str) -> float | None:
    """Return a gas volume reading only if the IHD reports it in cubic metres.

    Some meters/IHDs populate the volume fields with the kWh figures and say
    so in the accompanying units field (e.g. "dayweekmonthvolunits": "kWh").
    Reporting those as m³ is wrong, and kWh can't be converted to m³ without
    the calorific value, so report the state as unknown instead.
    """
    energy_import = payload["gasmeter"]["energy"]["import"]
    units = energy_import.get(units_field)
    if units is not None and str(units).strip().lower() not in GAS_VOLUME_UNITS:
        return None
    return energy_import[field]


def message_datetime(payload: dict[str, Any]) -> datetime | None:
    """Return the timestamp of an MQTT payload, or None if it has none."""
    timestamp = (
        payload.get("timestamp")
        or payload.get("electricitymeter", {}).get("timestamp")
        or payload.get("gasmeter", {}).get("timestamp")
    )
    try:
        return datetime.fromisoformat(timestamp)
    except (TypeError, ValueError):
        return None


def determine_last_reset(
    message_time: datetime,
    meter_time_zone: tzinfo,
    meter_interval: MeterInterval,
) -> datetime:
    """Return the start of the meter's current reset interval in UTC."""
    meter_datetime = message_time.astimezone(meter_time_zone)
    meter_midnight = datetime.combine(
        meter_datetime.date(),
        time.min,
        meter_datetime.tzinfo,
    )
    match meter_interval:
        case MeterInterval.DAY:
            last_reset = meter_midnight
        case MeterInterval.WEEK:
            last_reset = meter_midnight - timedelta(days=meter_midnight.weekday())
        case MeterInterval.MONTH:
            last_reset = meter_midnight.replace(day=1)
        case MeterInterval.YEAR:
            last_reset = meter_midnight.replace(day=1, month=1)
    return last_reset.astimezone(UTC)
