"""Tests for the integration's helpers."""

import pytest

from custom_components.hildebrand_glow_ihd.helpers import entry_title


@pytest.mark.parametrize(
    ("device_id", "expected"),
    [
        ("+", "Hildebrand Glow IHD"),
        ("", "Hildebrand Glow IHD"),
        (None, "Hildebrand Glow IHD"),
        (" AABBCCDDEEFF ", "Hildebrand Glow IHD (AABBCCDDEEFF)"),
    ],
)
def test_entry_title(device_id: str | None, expected: str) -> None:
    """The title names the device, unless every device is detected."""
    assert entry_title(device_id) == expected
