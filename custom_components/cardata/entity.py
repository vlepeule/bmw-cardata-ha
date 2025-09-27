"""Base entity classes for BMW CarData."""

from __future__ import annotations

from typing import Optional

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .coordinator import CardataCoordinator


class CardataEntity(Entity):
    def __init__(self, coordinator: CardataCoordinator, vin: str, descriptor: str) -> None:
        self._coordinator = coordinator
        self._vin = vin
        self._descriptor = descriptor
        self._attr_unique_id = f"{vin}_{descriptor}"
        self._attr_name = self._format_name()

    @property
    def device_info(self) -> DeviceInfo:
        name = self._coordinator.names.get(self._vin, self._vin)
        return DeviceInfo(
            identifiers={(DOMAIN, self._vin)},
            manufacturer="BMW",
            name=name,
        )

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
