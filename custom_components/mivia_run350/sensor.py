"""Sensor platform for MiVia Run 350."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MiViaCoordinator


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up MiVia sensors."""
    coordinator: MiViaCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            MiViaStepsSensor(coordinator, entry),
            MiViaCaloriesSensor(coordinator, entry),
            MiViaActiveCaloriesSensor(coordinator, entry),
        ]
    )


class MiViaBaseSensor(CoordinatorEntity[MiViaCoordinator], SensorEntity):
    """Base entity for MiVia measurements."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: MiViaCoordinator,
        entry,
        key: str,
        name: str,
        icon: str,
        unit: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = name
        self._attr_icon = icon
        if unit is not None:
            self._attr_native_unit_of_measurement = unit
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.data["address"])},
            "name": "MiVia Run 350",
            "manufacturer": "Mio-Magellan",
            "model": "Run 350",
        }

    @property
    def native_value(self):
        """Return the latest value for this measurement."""
        return self.coordinator.data.get(self._key)


class MiViaStepsSensor(MiViaBaseSensor):
    """Total step count reported by the watch."""

    _attr_native_unit_of_measurement = "steps"
    _attr_state_class = "total_increasing"

    def __init__(self, coordinator: MiViaCoordinator, entry) -> None:
        super().__init__(
            coordinator, entry, "steps", "Steps", "mdi:shoe-print", "steps"
        )


class MiViaCaloriesSensor(MiViaBaseSensor):
    """Total calories reported by the watch."""

    _attr_state_class = "measurement"

    def __init__(self, coordinator: MiViaCoordinator, entry) -> None:
        super().__init__(
            coordinator, entry, "calories", "Calories", "mdi:fire", "kcal"
        )


class MiViaActiveCaloriesSensor(MiViaBaseSensor):
    """Active calories reported by the watch."""

    _attr_state_class = "measurement"

    def __init__(self, coordinator: MiViaCoordinator, entry) -> None:
        super().__init__(
            coordinator,
            entry,
            "active_calories",
            "Active calories",
            "mdi:fire",
            "kcal",
        )
