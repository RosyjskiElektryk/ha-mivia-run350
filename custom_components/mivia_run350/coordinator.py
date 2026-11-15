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
    CONTROL_POINT_CHARACTERISTIC_UUID,
    CONF_ADDRESS,
    DOMAIN,
    EVENT_INSTANTANEOUS_DATA,
    OPCODE_INSTANTANEOUS_DATA,
)

_LOGGER = logging.getLogger(__name__)

# The app's InstantaneousDataVersion0 decoder reads 16 bytes:
# distance:u32 BE, steps:u32 BE, active_time:u32 BE,
# total_calories:u16 BE, active_calories:u16 BE.
INSTANTANEOUS_V0_LENGTH = 16
NOTIFICATION_TIMEOUT = 10


def parse_notification(data: bytes) -> dict | None:
    """Decode a Mercury instantaneous-data event.

    Packet layout observed in the companion library:
    type-code, event-code, structure-version, then version-0 data.
    """
    if len(data) < 3 or data[1] != EVENT_INSTANTANEOUS_DATA:
        return None

    version = data[2]
    if version != 0:
        _LOGGER.warning("Unsupported MiVia instantaneous data version: %s", version)
        return None

    payload = data[3:]
    if len(payload) < INSTANTANEOUS_V0_LENGTH:
        _LOGGER.debug("Short MiVia instantaneous packet (%s bytes): %s", len(data), data.hex())
        return None

    return {
        "distance_raw": int.from_bytes(payload[0:4], "big"),
        "steps": int.from_bytes(payload[4:8], "big"),
        "active_time_raw": int.from_bytes(payload[8:12], "big"),
        "calories": int.from_bytes(payload[12:14], "big"),
        "active_calories": int.from_bytes(payload[14:16], "big"),
    }


class MiViaCoordinator(DataUpdateCoordinator[dict]):
    """Fetch instantaneous data from the watch over BLE."""

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
        """Connect, enable instantaneous notifications and request data."""
        device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if device is None:
            raise UpdateFailed(
                f"MiVia {self.address} not found by the Home Assistant Bluetooth scanner"
            )

        received = asyncio.Event()
        packet_data: dict = {}

        def notification_handler(_sender, payload: bytearray) -> None:
            parsed = parse_notification(bytes(payload))
            if parsed is not None:
                packet_data.update(parsed)
                received.set()

        client = None
        try:
            client = await establish_connection(
                BleakClient,
                device,
                "MiVia Run 350",
                max_attempts=3,
            )
            await client.start_notify(
                CONTROL_POINT_CHARACTERISTIC_UUID, notification_handler
            )
            # Mercury.setInstantaneousAvailability(true, ...) sends exactly 40 01.
            await client.write_gatt_char(
                CONTROL_POINT_CHARACTERISTIC_UUID,
                bytes((OPCODE_INSTANTANEOUS_DATA, 0x01)),
                response=True,
            )
            await asyncio.wait_for(received.wait(), timeout=NOTIFICATION_TIMEOUT)
            self._last_data.update(packet_data)
            return dict(self._last_data)
        except asyncio.TimeoutError as err:
            if self._last_data:
                _LOGGER.warning("MiVia did not send a fresh steps packet; keeping last values")
                return dict(self._last_data)
            raise UpdateFailed(
                "Connected to MiVia, but no instantaneous-data notification arrived "
                "within 10 seconds. Check the BLE connection and enable debug logging."
            ) from err
        except Exception as err:
            raise UpdateFailed(f"MiVia BLE communication failed: {err}") from err
        finally:
            if client is not None and client.is_connected:
                try:
                    await client.stop_notify(CONTROL_POINT_CHARACTERISTIC_UUID)
                except Exception:  # noqa: BLE001
                    _LOGGER.debug("Could not stop MiVia notifications", exc_info=True)
                await client.disconnect()
