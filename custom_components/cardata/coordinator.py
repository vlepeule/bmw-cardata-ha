"""State coordinator for BMW CarData streaming payloads."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Iterable, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .const import DEBUG_LOG, DOMAIN, DIAGNOSTIC_LOG_INTERVAL

_LOGGER = logging.getLogger(__name__)


@dataclass
class DescriptorState:
    value: Any
    unit: Optional[str]
    timestamp: Optional[str]


@dataclass
class SocTracking:
    energy_kwh: Optional[float] = None
    max_energy_kwh: Optional[float] = None
    last_update: Optional[datetime] = None
    last_power_w: Optional[float] = None
    last_power_time: Optional[datetime] = None
    charging_active: bool = False
    last_soc_percent: Optional[float] = None

    def update_max_energy(self, value: Optional[float]) -> None:
        if value is None:
            return
        self.max_energy_kwh = value
        if self.last_soc_percent is not None and self.energy_kwh is None:
            self.energy_kwh = value * self.last_soc_percent / 100.0

    def update_actual_soc(self, percent: float, timestamp: Optional[datetime]) -> None:
        self.last_soc_percent = percent
        ts = timestamp or datetime.now(timezone.utc)
        self.last_update = ts
        if self.max_energy_kwh:
            self.energy_kwh = self.max_energy_kwh * percent / 100.0
        else:
            self.energy_kwh = None

    def update_power(self, power_w: Optional[float], timestamp: Optional[datetime]) -> None:
        if power_w is None:
            return
        self.last_power_w = power_w
        self.last_power_time = timestamp or datetime.now(timezone.utc)

    def update_status(self, status: Optional[str]) -> None:
        if status is None:
            return
        self.charging_active = status in {"CHARGINGACTIVE", "CHARGING_IN_PROGRESS"}

    def estimate(self, now: datetime) -> Optional[float]:
        if (
            not self.charging_active
            or self.energy_kwh is None
            or self.max_energy_kwh in (None, 0)
            or self.last_update is None
            or self.last_power_w in (None, 0)
        ):
            return None
        delta_seconds = (now - self.last_update).total_seconds()
        if delta_seconds <= 0:
            return None
        self.energy_kwh += (self.last_power_w * delta_seconds) / 3600.0
        if self.energy_kwh > self.max_energy_kwh:
            self.energy_kwh = self.max_energy_kwh
        self.last_update = now
        self.last_soc_percent = (self.energy_kwh / self.max_energy_kwh) * 100.0
        return self.last_soc_percent

    def current_rate_per_hour(self) -> Optional[float]:
        if (
            not self.charging_active
            or self.last_power_w in (None, 0)
            or self.max_energy_kwh in (None, 0)
        ):
            return None
        return (self.last_power_w / 1000.0) / self.max_energy_kwh * 100.0


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
    _soc_tracking: Dict[str, SocTracking] = field(default_factory=dict, init=False)
    _soc_rate: Dict[str, Optional[float]] = field(default_factory=dict, init=False)

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

        tracking = self._soc_tracking.setdefault(vin, SocTracking())
        now = datetime.now(timezone.utc)

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

            parsed_ts = dt_util.parse_datetime(timestamp) if timestamp else None
            if descriptor == "vehicle.drivetrain.batteryManagement.header":
                try:
                    tracking.update_actual_soc(float(value), parsed_ts)
                except (TypeError, ValueError):
                    pass
            elif descriptor == "vehicle.drivetrain.batteryManagement.maxEnergy":
                try:
                    tracking.update_max_energy(float(value))
                except (TypeError, ValueError):
                    pass
            elif descriptor == "vehicle.powertrain.electric.battery.charging.power":
                try:
                    tracking.update_power(float(value), parsed_ts)
                except (TypeError, ValueError):
                    pass
            elif descriptor == "vehicle.drivetrain.electricEngine.charging.status":
                if isinstance(value, str):
                    tracking.update_status(value)

            async_dispatcher_send(self.hass, self.signal_update, vin, descriptor)

        for descriptor in new_sensor:
            async_dispatcher_send(self.hass, self.signal_new_sensor, vin, descriptor)
        for descriptor in new_binary:
            async_dispatcher_send(self.hass, self.signal_new_binary, vin, descriptor)

        if vehicle_name:
            self.names[vin] = vehicle_name

        if vehicle_name:
            async_dispatcher_send(self.hass, f"{DOMAIN}_{self.entry_id}_name", vin, vehicle_name)

        self._apply_soc_estimate(vin, now)

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
        now = datetime.now(timezone.utc)
        for vin in list(self._soc_tracking.keys()):
            self._apply_soc_estimate(vin, now, dispatcher=False)
        async_dispatcher_send(self.hass, self.signal_diagnostics)

    def _apply_soc_estimate(self, vin: str, now: datetime, dispatcher: bool = True) -> None:
        tracking = self._soc_tracking.get(vin)
        if not tracking:
            return
        percent = tracking.estimate(now)
        rate = tracking.current_rate_per_hour()
        self._soc_rate[vin] = rate
        if percent is None:
            return
        header_descriptor = "vehicle.drivetrain.batteryManagement.header"
        vehicle_state = self.data.setdefault(vin, {})
        existing = vehicle_state.get(header_descriptor)
        current_value = None
        if existing and existing.value is not None:
            try:
                current_value = float(existing.value)
            except (TypeError, ValueError):
                current_value = None
        if current_value is not None and abs(current_value - percent) < 0.1:
            return
        timestamp = dt_util.as_utc(now).isoformat()
        vehicle_state[header_descriptor] = DescriptorState(
            value=round(percent, 2),
            unit="percent",
            timestamp=timestamp,
        )
        if dispatcher:
            async_dispatcher_send(self.hass, self.signal_update, vin, header_descriptor)

    def get_soc_rates(self) -> Dict[str, float]:
        return {
            vin: round(rate, 3)
            for vin, rate in self._soc_rate.items()
            if rate not in (None, 0)
        }
