"""State coordinator for BMW CarData streaming payloads."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Iterable, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import DEBUG_LOG, DOMAIN, DIAGNOSTIC_LOG_INTERVAL

_LOGGER = logging.getLogger(__name__)


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
    names: Dict[str, str] = field(default_factory=dict)
    last_message_at: Optional[datetime] = None
    connection_status: str = "connecting"
    last_disconnect_reason: Optional[str] = None
    watchdog_task: Optional[asyncio.Task] = field(default=None, init=False, repr=False)

    @property
    def signal_new_sensor(self) -> str:
        return f"{DOMAIN}_{self.entry_id}_new_sensor"

    @property
    def signal_new_binary(self) -> str:
        return f"{DOMAIN}_{self.entry_id}_new_binary"

    @property
    def signal_update(self) -> str:
        return f"{DOMAIN}_{self.entry_id}_update"

    @property
    def signal_diagnostics(self) -> str:
        return f"{DOMAIN}_{self.entry_id}_diagnostics"

    async def async_handle_message(self, payload: Dict[str, Any]) -> None:
        vin = payload.get("vin")
        data = payload.get("data") or {}
        if not vin or not isinstance(data, dict):
            return

        vehicle_state = self.data.setdefault(vin, {})
        new_binary: list[str] = []
        new_sensor: list[str] = []

        self.last_message_at = datetime.now(timezone.utc)

        if DEBUG_LOG:
            _LOGGER.debug("Processing message for VIN %s: %s", vin, list(data.keys()))

        vehicle_name: Optional[str] = None

        vehicle_name: Optional[str] = None

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
            if descriptor == "vehicle.vehicleIdentification.basicVehicleData" and isinstance(value, dict):
                vehicle_name = value.get("modelName") or value.get("model") or vehicle_name
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

        if vehicle_name:
            self.names[vin] = vehicle_name

        if vehicle_name:
            async_dispatcher_send(self.hass, f"{DOMAIN}_{self.entry_id}_name", vin, vehicle_name)

        async_dispatcher_send(self.hass, self.signal_diagnostics)

    def get_state(self, vin: str, descriptor: str) -> Optional[DescriptorState]:
        return self.data.get(vin, {}).get(descriptor)

    def iter_descriptors(self, *, binary: bool) -> Iterable[tuple[str, str]]:
        for vin, descriptors in self.data.items():
            for descriptor, descriptor_state in descriptors.items():
                if isinstance(descriptor_state.value, bool) == binary:
                    yield vin, descriptor

    async def async_handle_connection_event(
        self, status: str, *, reason: Optional[str] = None
    ) -> None:
        self.connection_status = status
        if reason:
            self.last_disconnect_reason = reason
        elif status == "connected":
            self.last_disconnect_reason = None
        self._log_diagnostics()

    async def async_start_watchdog(self) -> None:
        if self.watchdog_task:
            return
        self.watchdog_task = self.hass.loop.create_task(self._watchdog_loop())

    async def async_stop_watchdog(self) -> None:
        if not self.watchdog_task:
            return
        self.watchdog_task.cancel()
        try:
            await self.watchdog_task
        except asyncio.CancelledError:
            pass
        self.watchdog_task = None

    async def _watchdog_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(DIAGNOSTIC_LOG_INTERVAL)
                self._log_diagnostics()
        except asyncio.CancelledError:
            return

    def _log_diagnostics(self) -> None:
        if DEBUG_LOG:
            _LOGGER.debug(
                "Stream heartbeat: status=%s last_reason=%s last_message=%s",
                self.connection_status,
                self.last_disconnect_reason,
                self.last_message_at,
            )
        async_dispatcher_send(self.hass, self.signal_diagnostics)
