"""Binary sensor platform for MiVia Run 350."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MiViaCoordinator


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up MiVia binary sensors."""
    coordinator: MiViaCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([MiViaChargingSensor(coordinator, entry)])


class MiViaChargingSensor(
    CoordinatorEntity[MiViaCoordinator], BinarySensorEntity
):
    """Charging state reported by the watch."""

    _attr_has_entity_name = True
    _attr_name = "Charging"
    _attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING
    _attr_icon = "mdi:battery-charging"

    def __init__(self, coordinator: MiViaCoordinator, entry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_is_charging"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.data["address"])},
            "name": "MiVia Run 350",
            "manufacturer": "Mio-Magellan",
            "model": "Run 350",
        }

    @property
    def is_on(self) -> bool | None:
        """Return True while the watch is charging."""
        value = self.coordinator.data.get("is_charging")
        return value if isinstance(value, bool) else None
