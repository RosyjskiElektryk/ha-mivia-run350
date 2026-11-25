"""BLE coordinator for MiVia Run 350."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from bleak import BleakClient
from bleak_retry_connector import establish_connection

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    BATTERY_CONTROL_CHARACTERISTIC_UUID,
    BATTERY_NOTIFICATION_TIMEOUT,
    BATTERY_REQUEST_RETRIES,
    BATTERY_RESPONSE_LENGTH,
    CONF_ADDRESS,
    CONTROL_POINT_CHARACTERISTIC_UUID,
    DOMAIN,
    DIAGNOSTIC_CHANNELS,
    EVENT_INSTANTANEOUS_DATA,
    OPCODE_GET_BATTERY_LEVEL,
    OPCODE_GET_DEVICE_INFO,
    OPCODE_INSTANTANEOUS_DATA,
)

_LOGGER = logging.getLogger(__name__)


def _mask_address(address: str) -> str:
    """Mask the last three octets of a Bluetooth address for log output."""
    parts = address.split(":")
    if len(parts) == 6:
        return ":".join((*parts[:3], "**", "**", "**"))
    return "<redacted>"

# Mercury uses Garmin FIT field numbers as packet type codes:
# 0xFD = event packet, 0xFE = response packet.
MERCURY_EVENT_PACKET = 0xFD
MERCURY_RESPONSE_PACKET = 0xFE
MERCURY_RESPONSE_SUCCESS = 0x01

# InstantaneousDataVersion0 reads 16 bytes after skipping one payload byte:
# distance:u32 BE, steps:u32 BE, active_time:u32 BE,
# total_calories:u16 BE, active_calories:u16 BE.
INSTANTANEOUS_V0_LENGTH = 16
NOTIFICATION_TIMEOUT = 10


def parse_instantaneous_response(data: bytes) -> int | None:
    """Decode the Mercury response and return its data-structure version."""
    if (
        len(data) < 3
        or data[0] != MERCURY_RESPONSE_PACKET
        or data[1] != OPCODE_INSTANTANEOUS_DATA
    ):
        return None

    response_code = data[2]
    if response_code != MERCURY_RESPONSE_SUCCESS:
        _LOGGER.warning(
            "MiVia instantaneous request failed with response code 0x%02X",
            response_code,
        )
        return None

    if len(data) < 4:
        _LOGGER.warning(
            "Short MiVia instantaneous response: %s", data.hex(" ")
        )
        return None

    return data[3]


def parse_notification(data: bytes, struct_version: int | None) -> dict | None:
    """Decode a Mercury instantaneous-data event."""
    if (
        len(data) < 3
        or data[0] != MERCURY_EVENT_PACKET
        or data[1] != EVENT_INSTANTANEOUS_DATA
    ):
        return None

    if struct_version is None:
        _LOGGER.debug(
            "MiVia instantaneous event arrived before a successful version response: %s",
            data.hex(" "),
        )
        return None

    if struct_version != 0:
        _LOGGER.warning(
            "Unsupported MiVia instantaneous data version: %s", struct_version
        )
        return None

    # InstantaneousAssistant.processPacket() skips this first payload byte.
    payload = data[3:]
    if len(payload) < INSTANTANEOUS_V0_LENGTH:
        _LOGGER.debug(
            "Short MiVia instantaneous packet (%s bytes): %s",
            len(data),
            data.hex(" "),
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
        started_at = datetime.now(timezone.utc)
        packet_data: dict = {}

        def increment_counter(key: str) -> None:
            packet_data[key] = packet_data.get(key, self._last_data.get(key, 0)) + 1

        def set_stage(stage: str) -> None:
            packet_data["last_stage"] = stage
            _LOGGER.debug("MiVia stage: %s", stage)

        def record_tx(channel: str, raw: bytes) -> None:
            increment_counter("tx_count")
            packet_data["tx_last_channel"] = channel
            packet_data["tx_last_packet"] = raw.hex(" ")
            packet_data["tx_last_seen"] = datetime.now(timezone.utc)
            _LOGGER.debug("MiVia TX channel=%s payload=%s", channel, raw.hex(" "))

        set_stage("bluetooth_discovery")
        device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if device is None:
            increment_counter("ble_error_count")
            packet_data["connection_state"] = "not_found"
            packet_data["last_error"] = "Device not found by the Home Assistant Bluetooth scanner"
            packet_data["connection_duration"] = (datetime.now(timezone.utc) - started_at).total_seconds()
            self._last_data.update(packet_data)
            raise UpdateFailed(
                f"MiVia {_mask_address(self.address)} not found by the Home Assistant Bluetooth scanner"
            )

        debug_enabled = _LOGGER.isEnabledFor(logging.DEBUG)
        rssi = getattr(device, "rssi", None)
        if isinstance(rssi, (int, float)):
            self._last_data["rssi"] = rssi
        if debug_enabled:
            _LOGGER.debug(
                "MiVia BLE device selected: address=%s name=%s rssi=%s",
                _mask_address(getattr(device, "address", self.address)),
                getattr(device, "name", None),
                getattr(device, "rssi", None),
            )

        instantaneous_received = asyncio.Event()
        battery_received = asyncio.Event()
        instantaneous_struct_version: int | None = None
        battery_notify_started = False
        battery_request_sent = False
        battery_write_response = False
        battery_write_supported = False
        diagnostic_notify_started: list[str] = []

        def record_diagnostic_packet(channel: str, raw: bytes) -> None:
            """Store packet count, payload and timestamp for a GATT channel."""
            prefix = f"diag_{channel}"
            count_key = f"{prefix}_count"
            packet_data[count_key] = packet_data.get(
                count_key, self._last_data.get(count_key, 0)
            ) + 1
            packet_data[f"{prefix}_last_packet"] = raw.hex(" ")
            packet_data[f"{prefix}_last_seen"] = datetime.now(timezone.utc)
            increment_counter("rx_count")

        def instantaneous_handler(_sender, payload: bytearray) -> None:
            nonlocal instantaneous_struct_version

            raw = bytes(payload)
            record_diagnostic_packet("1011", raw)
            _LOGGER.debug("MiVia RX instantaneous %s: %s", _sender, raw.hex(" "))

            response_version = parse_instantaneous_response(raw)
            if response_version is not None:
                instantaneous_struct_version = response_version
                _LOGGER.debug(
                    "MiVia instantaneous response accepted: struct_version=%s",
                    response_version,
                )
                return

            parsed = parse_notification(raw, instantaneous_struct_version)
            if parsed is not None:
                packet_data.update(parsed)
                instantaneous_received.set()

        def battery_handler(_sender, payload: bytearray) -> None:
            raw = bytes(payload)
            record_diagnostic_packet("e00a", raw)
            _LOGGER.debug("MiVia RX battery %s: %s", _sender, raw.hex(" "))
            parsed = parse_battery_notification(raw)
            if parsed is not None:
                _LOGGER.debug("MiVia battery parsed: %s", parsed)
                packet_data.update(parsed)
                battery_received.set()
            else:
                _LOGGER.debug(
                    "MiVia battery-channel notification did not match 0F 17 response"
                )

        def make_diagnostic_handler(channel: str):
            """Create a handler that records raw packets from one GATT channel."""
            def handler(_sender, payload: bytearray) -> None:
                raw = bytes(payload)
                record_diagnostic_packet(channel, raw)
                _LOGGER.debug(
                    "MiVia RX diagnostic channel=%s sender=%s payload=%s",
                    channel,
                    _sender,
                    raw.hex(" "),
                )
            return handler

        client = None
        try:
            set_stage("connecting")
            client = await establish_connection(
                BleakClient,
                device,
                "MiVia Run 350",
                max_attempts=10,
                pair=True,
                timeout=60,
            )

            packet_data["connection_state"] = "connected"
            set_stage("gatt_discovery")
            if debug_enabled:
                _LOGGER.debug(
                    "MiVia BLE connected: address=%s mtu=%s",
                    _mask_address(self.address),
                    getattr(client, "mtu_size", None),
                )
                # Dump the complete GATT database discovered by Bleak.
                for service in client.services:
                    _LOGGER.debug(
                        "MiVia GATT service: uuid=%s handle=%s",
                        service.uuid,
                        service.handle,
                    )
                    for characteristic in service.characteristics:
                        _LOGGER.debug(
                            "MiVia GATT characteristic: service=%s uuid=%s "
                            "handle=%s properties=%s",
                            service.uuid,
                            characteristic.uuid,
                            characteristic.handle,
                            characteristic.properties,
                        )
                        for descriptor in characteristic.descriptors:
                            _LOGGER.debug(
                                "MiVia GATT descriptor: characteristic=%s "
                                "uuid=%s handle=%s",
                                characteristic.uuid,
                                descriptor.uuid,
                                descriptor.handle,
                            )

            # The companion app sends 0F 17 to this exact MiWell characteristic.
            # Select the GATT write mode from the properties reported by the watch.
            battery_characteristic = next(
                (
                    characteristic
                    for service in client.services
                    for characteristic in service.characteristics
                    if characteristic.uuid.lower()
                    == BATTERY_CONTROL_CHARACTERISTIC_UUID.lower()
                ),
                None,
            )
            if battery_characteristic is not None:
                battery_properties = {
                    prop.lower() for prop in battery_characteristic.properties
                }
                packet_data["battery_characteristic_properties"] = ", ".join(
                    sorted(battery_properties)
                )
                if "write-without-response" in battery_properties:
                    battery_write_supported = True
                    battery_write_response = False
                    packet_data["battery_write_mode"] = "without_response"
                elif "write" in battery_properties:
                    battery_write_supported = True
                    battery_write_response = True
                    packet_data["battery_write_mode"] = "with_response"
                else:
                    packet_data["battery_write_mode"] = "unsupported"
                    _LOGGER.warning(
                        "MiVia battery characteristic has no supported write property: %s",
                        sorted(battery_properties),
                    )
            else:
                packet_data["battery_characteristic_properties"] = "not_found"
                packet_data["battery_write_mode"] = "not_found"
                _LOGGER.warning(
                    "MiVia battery characteristic %s was not found in GATT",
                    BATTERY_CONTROL_CHARACTERISTIC_UUID,
                )

            packet_data["battery_notify_started"] = False
            packet_data["battery_request_sent"] = False
            packet_data["battery_response_received"] = False
            set_stage("subscribe_battery")
            try:
                await client.start_notify(
                    BATTERY_CONTROL_CHARACTERISTIC_UUID, battery_handler
                )
                battery_notify_started = True
                packet_data["battery_notify_started"] = True
                _LOGGER.debug(
                    "MiVia battery notifications enabled on %s",
                    BATTERY_CONTROL_CHARACTERISTIC_UUID,
                )
            except Exception:  # noqa: BLE001
                _LOGGER.warning(
                    "Could not subscribe to MiVia battery notifications; "
                    "continuing with activity data",
                    exc_info=True,
                )

            set_stage("subscribe_mercury")
            await client.start_notify(
                CONTROL_POINT_CHARACTERISTIC_UUID, instantaneous_handler
            )

            # Subscribe to every additional notify/indicate characteristic.
            # This is passive diagnostics: no undocumented writes are sent.
            known_characteristics = {
                BATTERY_CONTROL_CHARACTERISTIC_UUID.lower(),
                CONTROL_POINT_CHARACTERISTIC_UUID.lower(),
            }
            channel_by_uuid = {
                uuid.lower(): channel for channel, uuid in DIAGNOSTIC_CHANNELS.items()
            }
            for service in client.services:
                for characteristic in service.characteristics:
                    uuid = characteristic.uuid.lower()
                    properties = {
                        prop.lower() for prop in characteristic.properties
                    }
                    if (
                        uuid in known_characteristics
                        or not properties.intersection({"notify", "indicate"})
                    ):
                        continue
                    channel = channel_by_uuid.get(uuid, uuid.replace("-", "")[-4:])
                    try:
                        await client.start_notify(
                            characteristic.uuid, make_diagnostic_handler(channel)
                        )
                        diagnostic_notify_started.append(characteristic.uuid)
                        _LOGGER.debug(
                            "MiVia diagnostic subscription started: channel=%s uuid=%s",
                            channel,
                            characteristic.uuid,
                        )
                    except Exception:  # noqa: BLE001
                        _LOGGER.debug(
                            "MiVia diagnostic subscription failed: %s",
                            characteristic.uuid,
                            exc_info=True,
                        )

            # Battery data is optional; a failure must not block activity updates.
            set_stage("request_battery")
            if (
                battery_notify_started
                and battery_characteristic is not None
                and battery_write_supported
            ):
                try:
                    battery_command = bytes(
                        (OPCODE_GET_DEVICE_INFO, OPCODE_GET_BATTERY_LEVEL)
                    )
                    _LOGGER.debug(
                        "MiVia TX battery characteristic=%s response=%s payload=%s",
                        BATTERY_CONTROL_CHARACTERISTIC_UUID,
                        battery_write_response,
                        battery_command.hex(" "),
                    )
                    record_tx("e00a", battery_command)
                    await client.write_gatt_char(
                        BATTERY_CONTROL_CHARACTERISTIC_UUID,
                        battery_command,
                        response=battery_write_response,
                    )
                    battery_request_sent = True
                    packet_data["battery_request_sent"] = True
                except Exception as err:  # noqa: BLE001
                    packet_data["last_error"] = (
                        "Battery request write failed: "
                        + str(err).replace(self.address, _mask_address(self.address))[:180]
                    )
                    increment_counter("ble_error_count")
                    _LOGGER.warning(
                        "Could not request MiVia battery data; continuing with activity data",
                        exc_info=True,
                    )

            # Mercury.setInstantaneousAvailability(true, ...) sends exactly 40 01.
            set_stage("request_instantaneous")
            activity_command = bytes((OPCODE_INSTANTANEOUS_DATA, 0x01))
            record_tx("1011", activity_command)
            _LOGGER.debug(
                "MiVia TX instantaneous characteristic=%s response=True payload=%s",
                CONTROL_POINT_CHARACTERISTIC_UUID,
                activity_command.hex(" "),
            )
            await client.write_gatt_char(
                CONTROL_POINT_CHARACTERISTIC_UUID,
                activity_command,
                response=True,
            )

            set_stage("wait_instantaneous")
            await asyncio.wait_for(
                instantaneous_received.wait(), timeout=NOTIFICATION_TIMEOUT
            )

            # Some firmware drops the first battery query. Retry once, but never
            # fail the coordinator refresh solely because battery data is absent.
            set_stage("wait_battery")
            if battery_request_sent:
                for attempt in range(BATTERY_REQUEST_RETRIES + 1):
                    if battery_received.is_set():
                        break
                    if attempt:
                        _LOGGER.debug(
                            "MiVia battery response missing; retrying request (%s/%s)",
                            attempt,
                            BATTERY_REQUEST_RETRIES,
                        )
                        try:
                            retry_command = bytes(
                                (OPCODE_GET_DEVICE_INFO, OPCODE_GET_BATTERY_LEVEL)
                            )
                            record_tx("e00a", retry_command)
                            await client.write_gatt_char(
                                BATTERY_CONTROL_CHARACTERISTIC_UUID,
                                retry_command,
                                response=battery_write_response,
                            )
                        except Exception:  # noqa: BLE001
                            _LOGGER.warning(
                                "MiVia battery retry write failed",
                                exc_info=True,
                            )
                            break
                    try:
                        await asyncio.wait_for(
                            battery_received.wait(),
                            timeout=BATTERY_NOTIFICATION_TIMEOUT,
                        )
                    except asyncio.TimeoutError:
                        increment_counter("timeout_count")
                        if attempt == BATTERY_REQUEST_RETRIES:
                            packet_data["last_error"] = "Battery response timeout"
                            _LOGGER.warning(
                                "MiVia battery response timed out after %s request(s)",
                                attempt + 1,
                            )

            packet_data["battery_response_received"] = battery_received.is_set()
            packet_data["connection_state"] = "idle"
            packet_data["last_stage"] = "complete"
            packet_data["last_success"] = datetime.now(timezone.utc)
            if battery_received.is_set():
                packet_data["last_error"] = None
            elif battery_request_sent and "last_error" not in packet_data:
                packet_data["last_error"] = "Battery response timeout or no valid response"
            packet_data["connection_duration"] = (
                datetime.now(timezone.utc) - started_at
            ).total_seconds()
            self._last_data.update(packet_data)
            return dict(self._last_data)

        except asyncio.TimeoutError as err:
            increment_counter("timeout_count")
            failed_stage = packet_data.get("last_stage", "unknown")
            packet_data["connection_state"] = "timeout"
            packet_data["last_error"] = f"Timeout during {failed_stage}"
            packet_data["connection_duration"] = (
                datetime.now(timezone.utc) - started_at
            ).total_seconds()
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
            increment_counter("ble_error_count")
            packet_data["connection_state"] = "error"
            packet_data["last_stage"] = packet_data.get("last_stage", "unknown")
            packet_data["last_error"] = str(err).replace(
                self.address, _mask_address(self.address)
            )[:255]
            packet_data["connection_duration"] = (
                datetime.now(timezone.utc) - started_at
            ).total_seconds()
            self._last_data.update(packet_data)
            _LOGGER.exception(
                "MiVia BLE communication failed at stage %s", packet_data["last_stage"]
            )
            safe_error = str(err).replace(self.address, _mask_address(self.address))
            raise UpdateFailed(f"MiVia BLE communication failed: {safe_error}") from err
        finally:
            if client is not None and client.is_connected:
                for characteristic in (
                    CONTROL_POINT_CHARACTERISTIC_UUID,
                    BATTERY_CONTROL_CHARACTERISTIC_UUID,
                    *diagnostic_notify_started,
                ):
                    try:
                        await client.stop_notify(characteristic)
                    except Exception:  # noqa: BLE001
                        _LOGGER.debug(
                            "Could not stop MiVia notifications for %s",
                            characteristic,
                            exc_info=True,
                        )
                await client.disconnect()
                if debug_enabled:
                    _LOGGER.debug(
                        "MiVia BLE disconnected: address=%s", _mask_address(self.address)
                    )
