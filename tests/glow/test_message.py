"""Tests for the glow package's MQTT message handling."""

import json
from datetime import UTC, datetime

import pytest

from custom_components.hildebrand_glow_ihd.glow import TopicKind, parse_message
from custom_components.hildebrand_glow_ihd.glow.message import payload_timestamp
from tests.const import ELECTRICITY_PAYLOAD, GAS_PAYLOAD, STATE_PAYLOAD


def test_parse_state_message() -> None:
    """A STATE message is decoded with its own timestamp."""
    message = parse_message(
        "glow",
        "glow/AABBCCDDEEFF/STATE",
        json.dumps(STATE_PAYLOAD),
    )
    assert message is not None
    assert message.device_id == "AABBCCDDEEFF"
    assert message.kind is TopicKind.STATE
    assert message.payload == STATE_PAYLOAD
    assert message.timestamp == datetime(2022, 6, 11, 20, 54, 53, tzinfo=UTC)


@pytest.mark.parametrize(
    ("topic", "payload", "kind", "timestamp"),
    [
        (
            "glow/AABBCCDDEEFF/SENSOR/electricitymeter",
            ELECTRICITY_PAYLOAD,
            TopicKind.ELECTRICITY_METER,
            datetime(2022, 6, 11, 23, 38, tzinfo=UTC),
        ),
        (
            "glow/AABBCCDDEEFF/SENSOR/gasmeter",
            GAS_PAYLOAD,
            TopicKind.GAS_METER,
            datetime(2022, 6, 11, 20, 53, 52, tzinfo=UTC),
        ),
    ],
)
def test_parse_meter_message(
    topic: str,
    payload: dict[str, object],
    kind: TopicKind,
    timestamp: datetime,
) -> None:
    """A meter message takes its timestamp from the meter's data."""
    message = parse_message("glow", topic, json.dumps(payload).encode())
    assert message is not None
    assert message.kind is kind
    assert message.timestamp == timestamp


@pytest.mark.parametrize(
    ("topic", "payload"),
    [
        ("glow/AABBCCDDEEFF/STATE", "not json"),
        ("glow/AABBCCDDEEFF/STATE", "[1, 2]"),
        ("glow/AABBCCDDEEFF/OTHER", json.dumps(STATE_PAYLOAD)),
    ],
)
def test_parse_message_ignores_others(topic: str, payload: str) -> None:
    """Invalid JSON, non-object JSON and other topics aren't Glow messages."""
    assert parse_message("glow", topic, payload) is None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"timestamp": "not a time"},
        {"timestamp": None},
        {"electricitymeter": "not an object"},
        {"gasmeter": {}},
    ],
)
def test_payload_without_timestamp(payload: dict[str, object]) -> None:
    """A missing or invalid timestamp is None rather than an error."""
    assert payload_timestamp(payload) is None
