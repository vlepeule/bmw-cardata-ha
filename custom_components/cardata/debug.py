"""Dynamic debug flag handling for the Cardata integration."""

from __future__ import annotations

from .const import DEBUG_LOG

_DEBUG_ENABLED = DEBUG_LOG


def set_debug_enabled(value: bool) -> None:
    """Update the global debug flag."""
    global _DEBUG_ENABLED
    _DEBUG_ENABLED = value


def debug_enabled() -> bool:
    """Return whether verbose debug logging is enabled."""
    return _DEBUG_ENABLED
