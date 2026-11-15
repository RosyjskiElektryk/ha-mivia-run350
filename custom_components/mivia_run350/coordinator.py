"""BLE coordinator for MiVia Run 350."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from bleak import BleakClient
from bleak_retry_connector import establish_connection

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    BATTERY_CONTROL_CHARACTERISTIC_UUID,
    BATTERY_NOTIFICATION_TIMEOUT,
    BATTERY_RESPONSE_LENGTH,
    CONF_ADDRESS,
    CONTROL_POINT_CHARACTERISTIC_UUID,
    DOMAIN,
    EVENT_INSTANTANEOUS_DATA,
    OPCODE_GET_BATTERY_LEVEL,
    OPCODE_GET_DEVICE_INFO,
    OPCODE_INSTANTANEOUS_DATA,
)

_LOGGER = logging.getLogger(__name__)

# The app's InstantaneousDataVersion0 decoder reads 16 bytes:
# distance:u32 BE, steps:u32 BE, active_time:u32 BE,
# total_calories:u16 BE, active_calories:u16 BE.
INSTANTANEOUS_V0_LENGTH = 16
NOTIFICATION_TIMEOUT = 10


def parse_notification(data: bytes) -> dict | None:
    """Decode a Mercury instantaneous-data event."""
    if len(data) < 3 or data[1] != EVENT_INSTANTANEOUS_DATA:
        return None

    version = data[2]
    if version != 0:
        _LOGGER.warning("Unsupported MiVia instantaneous data version: %s", version)
        return None

    payload = data[3:]
    if len(payload) < INSTANTANEOUS_V0_LENGTH:
        _LOGGER.debug(
            "Short MiVia instantaneous packet (%s bytes): %s",
            len(data),
            data.hex(),
        )
        return None

    return {
        "distance_raw": int.from_bytes(payload[0:4], "big"),
        "steps": int.from_bytes(payload[4:8], "big"),
        "active_time_raw": int.from_bytes(payload[8:12], "big"),
        "calories": int.from_bytes(payload[12:14], "big"),
        "active_calories": int.from_bytes(payload[14:16], "big"),
    }


def parse_battery_notification(data: bytes) -> dict | None:
    """Decode a proprietary MiWell battery-level response."""
    if (
        len(data) < BATTERY_RESPONSE_LENGTH
        or data[0] != OPCODE_GET_DEVICE_INFO
        or data[1] != OPCODE_GET_BATTERY_LEVEL
    ):
        return None

    # The Android API maps data[2] == 0 to charging and data[3] to level.
    level = data[3] & 0xFF
    if level > 100:
        _LOGGER.warning("MiVia returned an out-of-range battery level: %s", level)
        return None

    return {
        "battery": level,
        "is_charging": data[2] == 0,
    }


class MiViaCoordinator(DataUpdateCoordinator[dict]):
    """Fetch instantaneous and battery data from the watch over BLE."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.address = entry.data[CONF_ADDRESS]
        self._last_data: dict = {}
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=1),
        )

    async def _async_update_data(self) -> dict:
        """Connect, subscribe to notifications and request watch data."""
        device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if device is None:
            raise UpdateFailed(
                f"MiVia {self.address} not found by the Home Assistant Bluetooth scanner"
            )

        instantaneous_received = asyncio.Event()
        battery_received = asyncio.Event()
        packet_data: dict = {}
        battery_notify_started = False
        battery_request_sent = False

        def instantaneous_handler(_sender, payload: bytearray) -> None:
            parsed = parse_notification(bytes(payload))
            if parsed is not None:
                packet_data.update(parsed)
                instantaneous_received.set()

        def battery_handler(_sender, payload: bytearray) -> None:
            parsed = parse_battery_notification(bytes(payload))
            if parsed is not None:
                packet_data.update(parsed)
                battery_received.set()

        client = None
        try:
            client = await establish_connection(
                BleakClient,
                device,
                "MiVia Run 350",
                max_attempts=3,
                pair=True,
                timeout=60,
            )

            # Battery data uses a separate proprietary MiWell characteristic.
            # It is optional: failure must not prevent steps/calories updates.
            try:
                await client.start_notify(
                    BATTERY_CONTROL_CHARACTERISTIC_UUID, battery_handler
                )
                battery_notify_started = True
                await client.write_gatt_char(
                    BATTERY_CONTROL_CHARACTERISTIC_UUID,
                    bytes((OPCODE_GET_DEVICE_INFO, OPCODE_GET_BATTERY_LEVEL)),
                    response=True,
                )
                battery_request_sent = True
            except Exception:  # noqa: BLE001
                _LOGGER.warning(
                    "Could not request MiVia battery data; continuing with activity data",
                    exc_info=True,
                )

            await client.start_notify(
                CONTROL_POINT_CHARACTERISTIC_UUID, instantaneous_handler
            )
            # Mercury.setInstantaneousAvailability(true, ...) sends exactly 40 01.
            await client.write_gatt_char(
                CONTROL_POINT_CHARACTERISTIC_UUID,
                bytes((OPCODE_INSTANTANEOUS_DATA, 0x01)),
                response=True,
            )

            await asyncio.wait_for(
                instantaneous_received.wait(), timeout=NOTIFICATION_TIMEOUT
            )

            if battery_request_sent and not battery_received.is_set():
                try:
                    await asyncio.wait_for(
                        battery_received.wait(), timeout=BATTERY_NOTIFICATION_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    _LOGGER.debug("MiVia battery response timed out; keeping last value")

            self._last_data.update(packet_data)
            return dict(self._last_data)

        except asyncio.TimeoutError as err:
            self._last_data.update(packet_data)
            if "steps" in self._last_data:
                _LOGGER.warning(
                    "MiVia did not send fresh instantaneous data; keeping last values"
                )
                return dict(self._last_data)
            raise UpdateFailed(
                "Connected to MiVia, but no instantaneous-data notification arrived "
                "within 10 seconds. Check the BLE connection and enable debug logging."
            ) from err
        except Exception as err:
            raise UpdateFailed(f"MiVia BLE communication failed: {err}") from err
        finally:
            if client is not None and client.is_connected:
                for characteristic, started in (
                    (CONTROL_POINT_CHARACTERISTIC_UUID, True),
                    (BATTERY_CONTROL_CHARACTERISTIC_UUID, battery_notify_started),
                ):
                    if started:
                        try:
                            await client.stop_notify(characteristic)
                        except Exception:  # noqa: BLE001
                            _LOGGER.debug(
                                "Could not stop MiVia notifications for %s",
                                characteristic,
                                exc_info=True,
                            )
                await client.disconnect()
