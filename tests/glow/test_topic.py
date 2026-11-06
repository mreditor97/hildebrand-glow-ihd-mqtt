"""Tests for the glow package's MQTT topic handling."""

import pytest

from custom_components.hildebrand_glow_ihd.glow import (
    GlowTopic,
    TopicKind,
    normalize_device_id,
    normalize_topic_prefix,
    parse_topic,
    subscription_topic,
)


@pytest.mark.parametrize(
    ("device_id", "expected"),
    [
        ("aa:bb:cc:dd:ee:ff", "AABBCCDDEEFF"),
        (" AABBCC DDEEFF ", "AABBCCDDEEFF"),
        ("+", "+"),
        ("", "+"),
        (None, "+"),
    ],
)
def test_normalize_device_id(device_id: str | None, expected: str) -> None:
    """Device IDs are upper case without separators, blank means every device."""
    assert normalize_device_id(device_id) == expected


@pytest.mark.parametrize(
    ("topic_prefix", "expected"),
    [
        ("glow", "glow"),
        (" glow/# ", "glow"),
        ("glow/", "glow"),
        ("home/glow", "home/glow"),
        ("", "glow"),
        (None, "glow"),
    ],
)
def test_normalize_topic_prefix(topic_prefix: str | None, expected: str) -> None:
    """Prefixes lose wildcards, spaces and outer slashes, blank means glow."""
    assert normalize_topic_prefix(topic_prefix) == expected


def test_subscription_topic() -> None:
    """The subscription covers one device, or every device with +."""
    assert subscription_topic("glow", "+") == "glow/+/#"
    assert subscription_topic("glow", "AABBCCDDEEFF") == "glow/AABBCCDDEEFF/#"


@pytest.mark.parametrize(
    ("topic", "expected"),
    [
        ("glow/AABBCCDDEEFF/STATE", GlowTopic("AABBCCDDEEFF", TopicKind.STATE)),
        (
            "glow/AABBCCDDEEFF/SENSOR/electricitymeter",
            GlowTopic("AABBCCDDEEFF", TopicKind.ELECTRICITY_METER),
        ),
        (
            "glow/AABBCCDDEEFF/SENSOR/gasmeter",
            GlowTopic("AABBCCDDEEFF", TopicKind.GAS_METER),
        ),
        ("glow/AABBCCDDEEFF/SENSOR/other", None),
        ("glow/AABBCCDDEEFF", None),
        ("other/AABBCCDDEEFF/STATE", None),
        ("glowing/AABBCCDDEEFF/STATE", None),
    ],
)
def test_parse_topic(topic: str, expected: GlowTopic | None) -> None:
    """Only the three kinds of Glow topic under the prefix are recognised."""
    assert parse_topic("glow", topic) == expected


def test_parse_topic_with_nested_prefix() -> None:
    """A prefix with more than one level still finds the device ID."""
    assert parse_topic("home/glow", "home/glow/AABBCCDDEEFF/STATE") == GlowTopic(
        "AABBCCDDEEFF",
        TopicKind.STATE,
    )
