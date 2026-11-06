"""Helpers for the Home Assistant Hildebrand Glow IHD Integration."""

from __future__ import annotations

from .const import DEFAULT_TITLE
from .glow import DEFAULT_DEVICE_ID


def entry_title(device_id: str | None) -> str:
    """Return the config entry title for a configured device ID."""
    device_id = (device_id or "").strip()
    if not device_id or device_id == DEFAULT_DEVICE_ID:
        return DEFAULT_TITLE
    return f"{DEFAULT_TITLE} ({device_id})"
