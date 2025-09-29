"""Base entity classes for BMW CarData."""

from __future__ import annotations

from typing import Optional

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .coordinator import CardataCoordinator


class CardataEntity(RestoreEntity):
    def __init__(self, coordinator: CardataCoordinator, vin: str, descriptor: str) -> None:
        self._coordinator = coordinator
        self._vin = vin
        self._descriptor = descriptor
        self._attr_unique_id = f"{vin}_{descriptor}"
        self._attr_name = self._format_name()
        self._attr_available = True

    @property
    def device_info(self) -> DeviceInfo:
        metadata = self._coordinator.device_metadata.get(self._vin, {})
        name = metadata.get("name") or self._coordinator.names.get(self._vin, self._vin)
        manufacturer = metadata.get("manufacturer", "BMW")
        info: DeviceInfo = {
            "identifiers": {(DOMAIN, self._vin)},
            "manufacturer": manufacturer,
            "name": name,
        }
        if model := metadata.get("model"):
            info["model"] = model
        if sw_version := metadata.get("sw_version"):
            info["sw_version"] = sw_version
        if hw_version := metadata.get("hw_version"):
            info["hw_version"] = hw_version
        return info

    @property
    def available(self) -> bool:
        return True

    @property
    def extra_state_attributes(self) -> dict:
        state = self._coordinator.get_state(self._vin, self._descriptor)
        if not state:
            return {}
        attrs = {}
        if state.timestamp:
            attrs["timestamp"] = state.timestamp
        return attrs

    @property
    def descriptor(self) -> str:
        return self._descriptor

    @property
    def vin(self) -> str:
        return self._vin

    def _format_name(self) -> str:
        parts = [
            p
            for p in self._descriptor.replace("_", " ").replace(".", " ").split()
            if p and p.lower() != "vehicle"
        ]
        title = " ".join(p.capitalize() for p in parts)
        return title or self._vin
