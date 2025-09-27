"""State coordinator for BMW CarData streaming payloads."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import DOMAIN


@dataclass
class DescriptorState:
    value: Any
    unit: Optional[str]
    timestamp: Optional[str]


@dataclass
class CardataCoordinator:
    hass: HomeAssistant
    entry_id: str
    data: Dict[str, Dict[str, DescriptorState]] = field(default_factory=dict)

    @property
    def signal_new_sensor(self) -> str:
        return f"{DOMAIN}_{self.entry_id}_new_sensor"

    @property
    def signal_new_binary(self) -> str:
        return f"{DOMAIN}_{self.entry_id}_new_binary"

    @property
    def signal_update(self) -> str:
        return f"{DOMAIN}_{self.entry_id}_update"

    async def async_handle_message(self, payload: Dict[str, Any]) -> None:
        vin = payload.get("vin")
        data = payload.get("data") or {}
        if not vin or not isinstance(data, dict):
            return

        vehicle_state = self.data.setdefault(vin, {})
        new_binary: list[str] = []
        new_sensor: list[str] = []

        for descriptor, descriptor_payload in data.items():
            if not isinstance(descriptor_payload, dict):
                continue
            value = descriptor_payload.get("value")
            if value is None:
                continue
            unit = descriptor_payload.get("unit")
            timestamp = descriptor_payload.get("timestamp")
            is_new = descriptor not in vehicle_state
            vehicle_state[descriptor] = DescriptorState(value=value, unit=unit, timestamp=timestamp)
            if is_new:
                if isinstance(value, bool):
                    new_binary.append(descriptor)
                else:
                    new_sensor.append(descriptor)

            async_dispatcher_send(self.hass, self.signal_update, vin, descriptor)

        for descriptor in new_sensor:
            async_dispatcher_send(self.hass, self.signal_new_sensor, vin, descriptor)
        for descriptor in new_binary:
            async_dispatcher_send(self.hass, self.signal_new_binary, vin, descriptor)

    def get_state(self, vin: str, descriptor: str) -> Optional[DescriptorState]:
        return self.data.get(vin, {}).get(descriptor)

    def iter_descriptors(self, *, binary: bool) -> Iterable[tuple[str, str]]:
        for vin, descriptors in self.data.items():
            for descriptor, descriptor_state in descriptors.items():
                if isinstance(descriptor_state.value, bool) == binary:
                    yield vin, descriptor
