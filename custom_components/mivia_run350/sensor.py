"""Sensor platform for MiVia Run 350."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory, UnitOfLength
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MiViaCoordinator


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up MiVia sensors."""
    coordinator: MiViaCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([MiViaStepsSensor(coordinator, entry)])


class MiViaStepsSensor(CoordinatorEntity[MiViaCoordinator], SensorEntity):
    """Total step count reported by the watch."""

    _attr_has_entity_name = True
    _attr_name = "Steps"
    _attr_icon = "mdi:shoe-print"
    _attr_native_unit_of_measurement = "steps"
    _attr_state_class = "total_increasing"

    def __init__(self, coordinator: MiViaCoordinator, entry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_steps"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.data["address"])},
            "name": "MiVia Run 350",
            "manufacturer": "Mio-Magellan",
            "model": "Run 350",
        }

    @property
    def native_value(self):
        return self.coordinator.data.get("steps")
