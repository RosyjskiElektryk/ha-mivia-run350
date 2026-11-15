"""Sensor platform for MiVia Run 350."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory, PERCENTAGE
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
            MiViaDistanceRawSensor(coordinator, entry),
            MiViaActiveTimeRawSensor(coordinator, entry),
            MiViaBatterySensor(coordinator, entry),
            MiViaRssiSensor(coordinator, entry),
            *[
                MiViaDiagnosticSensor(coordinator, entry, channel, metric)
                for channel in ("e00a", "1011", "e00f", "e010", "e011", "1012")
                for metric in ("count", "last_packet", "last_seen")
            ],
            *[
                MiViaSystemDiagnosticSensor(coordinator, entry, key, name, icon)
                for key, name, icon in (
                    ("connection_state", "Connection state", "mdi:bluetooth-connect"),
                    ("last_stage", "Last communication stage", "mdi:timeline-text-outline"),
                    ("last_error", "Last BLE error", "mdi:alert-circle-outline"),
                    ("ble_error_count", "BLE errors", "mdi:alert-counter"),
                    ("timeout_count", "Timeouts", "mdi:timer-alert-outline"),
                    ("tx_count", "Sent packets", "mdi:upload-network-outline"),
                    ("rx_count", "Received packets", "mdi:download-network-outline"),
                    ("tx_last_channel", "Last TX channel", "mdi:bluetooth-transfer"),
                    ("tx_last_packet", "Last TX packet", "mdi:code-braces"),
                    ("tx_last_seen", "Last TX time", "mdi:clock-outline"),
                    ("last_success", "Last successful update", "mdi:check-circle-outline"),
                    ("connection_duration", "Last connection duration", "mdi:timer-outline"),
                )
            ],
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


class MiViaBatterySensor(MiViaBaseSensor):
    """Battery percentage reported by the watch."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = "measurement"

    def __init__(self, coordinator: MiViaCoordinator, entry) -> None:
        super().__init__(
            coordinator, entry, "battery", "Battery", "mdi:battery", PERCENTAGE
        )



class MiViaDistanceRawSensor(MiViaBaseSensor):
    """Raw distance field; unit conversion is not confirmed yet."""

    _attr_state_class = "measurement"

    def __init__(self, coordinator: MiViaCoordinator, entry) -> None:
        super().__init__(
            coordinator, entry, "distance_raw", "Distance (raw)", "mdi:map-marker-distance"
        )


class MiViaActiveTimeRawSensor(MiViaBaseSensor):
    """Raw active-time field; unit conversion is not confirmed yet."""

    _attr_state_class = "measurement"

    def __init__(self, coordinator: MiViaCoordinator, entry) -> None:
        super().__init__(
            coordinator, entry, "active_time_raw", "Active time (raw)", "mdi:timer-outline"
        )


class MiViaRssiSensor(MiViaBaseSensor):
    """RSSI from the latest Bluetooth advertisement received by Home Assistant."""

    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = "dBm"
    _attr_state_class = "measurement"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: MiViaCoordinator, entry) -> None:
        super().__init__(coordinator, entry, "rssi", "Bluetooth signal", "mdi:bluetooth")


class MiViaDiagnosticSensor(MiViaBaseSensor):
    """Raw diagnostics for an additional GATT notification channel."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: MiViaCoordinator, entry, channel: str, metric: str
    ) -> None:
        names = {
            "count": "packets",
            "last_packet": "last packet",
            "last_seen": "last seen",
        }
        icons = {
            "count": "mdi:counter",
            "last_packet": "mdi:code-braces",
            "last_seen": "mdi:clock-outline",
        }
        key = f"diag_{channel}_{metric}"
        super().__init__(
            coordinator,
            entry,
            key,
            f"BLE {channel.upper()} {names[metric]}",
            icons[metric],
        )
        if metric == "count":
            self._attr_state_class = "total_increasing"
        elif metric == "last_seen":
            self._attr_device_class = SensorDeviceClass.TIMESTAMP


class MiViaSystemDiagnosticSensor(MiViaBaseSensor):
    """Connection and protocol diagnostics."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: MiViaCoordinator,
        entry,
        key: str,
        name: str,
        icon: str,
    ) -> None:
        super().__init__(coordinator, entry, key, name, icon)
        if key in {"ble_error_count", "timeout_count", "tx_count", "rx_count"}:
            self._attr_state_class = "total_increasing"
        elif key in {"tx_last_seen", "last_success"}:
            self._attr_device_class = SensorDeviceClass.TIMESTAMP
        elif key == "connection_duration":
            self._attr_native_unit_of_measurement = "s"
            self._attr_suggested_display_precision = 2
