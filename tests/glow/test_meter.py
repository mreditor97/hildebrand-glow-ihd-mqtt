"""Tests for the glow package's meter calculations."""

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from custom_components.hildebrand_glow_ihd.glow import (
    MeterInterval,
    calculate_cost_today,
    determine_last_reset,
    gas_volume,
)
from tests.const import ELECTRICITY_PAYLOAD, GAS_PAYLOAD


def _meter(day: float | None, price: dict[str, Any] | None) -> dict[str, Any]:
    """Return meter data with a day's usage and a price."""
    return {"energy": {"import": {"day": day, "price": price}}}


@pytest.mark.parametrize(
    ("meter_data", "expected"),
    [
        (ELECTRICITY_PAYLOAD["electricitymeter"], 0.9),
        (_meter(10, {"unitrate": 0.25, "standingcharge": None}), 2.5),
        (_meter(10, {"unitrate": None, "standingcharge": 0.5}), 0.5),
        (_meter(None, {"unitrate": 0.25, "standingcharge": 0.5}), 0.5),
        (_meter(10, {"unitrate": None, "standingcharge": None}), None),
        (_meter(10, None), None),
    ],
)
def test_calculate_cost_today(
    meter_data: dict[str, Any],
    expected: float | None,
) -> None:
    """Cost is standing charge + usage * unit rate, unknown with no prices."""
    assert calculate_cost_today(meter_data) == expected


def test_gas_volume() -> None:
    """Volumes are only reported when the IHD says they're in cubic metres."""
    assert gas_volume(GAS_PAYLOAD, "cumulativevol", "cumulativevolunits") == 1500.2
    # The IHD reports the day/week/month volumes in kWh in this payload
    assert gas_volume(GAS_PAYLOAD, "dayvol", "dayweekmonthvolunits") is None


def test_gas_volume_without_units() -> None:
    """A volume without a units field is reported as it is."""
    payload = {"gasmeter": {"energy": {"import": {"dayvol": 1.5}}}}
    assert gas_volume(payload, "dayvol", "dayweekmonthvolunits") == 1.5


def test_gas_volume_missing_field() -> None:
    """A missing volume field raises KeyError, which the sensor handles."""
    with pytest.raises(KeyError):
        gas_volume({"gasmeter": {"energy": {"import": {}}}}, "dayvol", "units")


LONDON = ZoneInfo("Europe/London")


@pytest.mark.parametrize(
    ("message_time", "time_zone", "interval", "expected"),
    [
        # 00:38 BST on Sunday 12 June 2022
        (
            datetime(2022, 6, 11, 23, 38, tzinfo=UTC),
            LONDON,
            MeterInterval.DAY,
            datetime(2022, 6, 11, 23, 0, tzinfo=UTC),
        ),
        (
            datetime(2022, 6, 11, 23, 38, tzinfo=UTC),
            ZoneInfo("UTC"),
            MeterInterval.DAY,
            datetime(2022, 6, 11, 0, 0, tzinfo=UTC),
        ),
        # Weeks start on Monday 6 June
        (
            datetime(2022, 6, 11, 23, 38, tzinfo=UTC),
            LONDON,
            MeterInterval.WEEK,
            datetime(2022, 6, 5, 23, 0, tzinfo=UTC),
        ),
        (
            datetime(2022, 6, 11, 23, 38, tzinfo=UTC),
            LONDON,
            MeterInterval.MONTH,
            datetime(2022, 5, 31, 23, 0, tzinfo=UTC),
        ),
        # 1 January is in GMT, so midnight is 00:00 UTC
        (
            datetime(2022, 6, 11, 23, 38, tzinfo=UTC),
            LONDON,
            MeterInterval.YEAR,
            datetime(2022, 1, 1, 0, 0, tzinfo=UTC),
        ),
    ],
)
def test_determine_last_reset(
    message_time: datetime,
    time_zone: ZoneInfo,
    interval: MeterInterval,
    expected: datetime,
) -> None:
    """The last reset is the start of the interval in the meter's time zone."""
    assert determine_last_reset(message_time, time_zone, interval) == expected
