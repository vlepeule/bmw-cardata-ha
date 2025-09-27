"""Sensor platform for BMW CarData."""

from __future__ import annotations

from typing import Dict, Tuple

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN
from .coordinator import CardataCoordinator
from .entity import CardataEntity


class CardataSensor(CardataEntity, SensorEntity):
    def __init__(self, coordinator: CardataCoordinator, vin: str, descriptor: str) -> None:
        super().__init__(coordinator, vin, descriptor)
        self._attr_should_poll = False
        self._unsubscribe = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if getattr(self, "_attr_native_value", None) is None:
            last_state = await self.async_get_last_state()
            if last_state and last_state.state not in ("unknown", "unavailable"):
                self._attr_native_value = last_state.state
                unit = last_state.attributes.get("unit_of_measurement")
                if unit is not None:
                    self._attr_native_unit_of_measurement = unit
        self._unsubscribe = async_dispatcher_connect(
            self.hass,
            self._coordinator.signal_update,
            self._handle_update,
        )
        self._handle_update(self.vin, self.descriptor)

    async def async_will_remove_from_hass(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None

    def _handle_update(self, vin: str, descriptor: str) -> None:
        if vin != self.vin or descriptor != self.descriptor:
            return
        state = self._coordinator.get_state(vin, descriptor)
        if not state:
            return
        self._attr_native_value = state.value
        self._attr_native_unit_of_measurement = state.unit

        self.schedule_update_ha_state()


class CardataDiagnosticsSensor(SensorEntity):
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: CardataCoordinator,
        entry_id: str,
        sensor_type: str,
    ) -> None:
        self._coordinator = coordinator
        self._entry_id = entry_id
        self._sensor_type = sensor_type
        self._unsub = None
        unique_suffix = "last_message" if sensor_type == "last_message" else "connection_status"
        self._attr_unique_id = f"{entry_id}_diagnostics_{unique_suffix}"
        if sensor_type == "last_message":
            self._attr_name = "Last Message Received"
            self._attr_device_class = SensorDeviceClass.TIMESTAMP
        elif sensor_type == "connection_status":
            self._attr_name = "Stream Connection Status"
        else:
            self._attr_name = sensor_type

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            manufacturer="BMW",
            name="CarData Debug Device",
        )

    @property
    def extra_state_attributes(self) -> dict:
        if self._sensor_type == "connection_status" and self._coordinator.last_disconnect_reason:
            return {"last_disconnect_reason": self._coordinator.last_disconnect_reason}
        return {}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._unsub = async_dispatcher_connect(
            self.hass,
            self._coordinator.signal_diagnostics,
            self._handle_update,
        )
        self._handle_update()

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None

    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self):
        if self._sensor_type == "last_message":
            return self._coordinator.last_message_at
        if self._sensor_type == "connection_status":
            return self._coordinator.connection_status
        return None


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    runtime = hass.data[DOMAIN][entry.entry_id]
    coordinator: CardataCoordinator = runtime.coordinator

    entities: Dict[Tuple[str, str], CardataSensor] = {}

    def ensure_entity(vin: str, descriptor: str, *, assume_sensor: bool = False) -> None:
        if (vin, descriptor) in entities:
            return
        state = coordinator.get_state(vin, descriptor)
        if state:
            if isinstance(state.value, bool):
                return
        elif not assume_sensor:
            return
        entity = CardataSensor(coordinator, vin, descriptor)
        entities[(vin, descriptor)] = entity
        async_add_entities([entity])

    entity_registry = er.async_get(hass)
    legacy_unique_ids = {
        f"{entry.entry_id}_connection_status": f"{entry.entry_id}_diagnostics_connection_status",
        f"{entry.entry_id}_last_message": f"{entry.entry_id}_diagnostics_last_message",
    }
    for old_unique_id, new_unique_id in legacy_unique_ids.items():
        entity_id = entity_registry.async_get_entity_id("sensor", DOMAIN, old_unique_id)
        if entity_id:
            entity_registry.async_update_entity(
                entity_id, new_unique_id=new_unique_id
            )

    for entity_entry in er.async_entries_for_config_entry(
        entity_registry, entry.entry_id
    ):
        if entity_entry.domain != "sensor":
            continue
        if entity_entry.disabled_by is not None:
            continue
        unique_id = entity_entry.unique_id
        if not unique_id or "_" not in unique_id:
            continue
        vin, descriptor = unique_id.split("_", 1)
        ensure_entity(vin, descriptor, assume_sensor=True)

    for vin, descriptor in coordinator.iter_descriptors(binary=False):
        ensure_entity(vin, descriptor)

    async def async_handle_new(vin: str, descriptor: str) -> None:
        ensure_entity(vin, descriptor)

    entry.async_on_unload(
        async_dispatcher_connect(hass, coordinator.signal_new_sensor, async_handle_new)
    )

    diagnostic_entities: list[CardataDiagnosticsSensor] = []
    for sensor_type in ("connection_status", "last_message"):
        unique_suffix = "last_message" if sensor_type == "last_message" else "connection_status"
        unique_id = f"{entry.entry_id}_diagnostics_{unique_suffix}"
        if entity_registry.async_get_entity_id("sensor", DOMAIN, unique_id):
            continue
        diagnostic_entities.append(
            CardataDiagnosticsSensor(coordinator, entry.entry_id, sensor_type)
        )

    if diagnostic_entities:
        async_add_entities(diagnostic_entities, True)
