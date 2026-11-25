"""Constants for the MiVia Run 350 integration."""

DOMAIN = "mivia_run350"
CONF_ADDRESS = "address"

CONTROL_POINT_SERVICE_UUID = "0a0a1010-0a00-1000-8000-00805f9b34fb"
CONTROL_POINT_CHARACTERISTIC_UUID = "0a0a1011-0a00-1000-8000-00805f9b34fb"

# Proprietary MiWell wearable service used by the companion app for battery data.
BATTERY_SERVICE_UUID = "0a0aee03-0a00-1000-8000-00805f9b34fb"
BATTERY_CONTROL_CHARACTERISTIC_UUID = "0a0ae00a-0a00-1000-8000-00805f9b34fb"

# Standard Bluetooth Device Information Service (read-only characteristics).
DEVICE_INFO_SERVICE_UUID = "0000180a-0000-1000-8000-00805f9b34fb"
DEVICE_INFO_CHARACTERISTICS = {
    "firmware_revision": "00002a26-0000-1000-8000-00805f9b34fb",
    "software_revision": "00002a28-0000-1000-8000-00805f9b34fb",
    "hardware_revision": "00002a27-0000-1000-8000-00805f9b34fb",
    "model_number": "00002a24-0000-1000-8000-00805f9b34fb",
    "manufacturer_name": "00002a29-0000-1000-8000-00805f9b34fb",
}

# Mercury protocol opcodes/events confirmed from the companion application's
# protocol classes. 0x40 enables instantaneous data; 0x71 carries that data.
OPCODE_INSTANTANEOUS_DATA = 0x40
EVENT_INSTANTANEOUS_DATA = 0x71

# Proprietary MiWell battery request/response: [0x0F, 0x17].
OPCODE_GET_DEVICE_INFO = 0x0F
OPCODE_GET_BATTERY_LEVEL = 0x17
BATTERY_RESPONSE_LENGTH = 4
BATTERY_NOTIFICATION_TIMEOUT = 2
BATTERY_REQUEST_RETRIES = 1

# Additional notify/indicate characteristics discovered on the watch.
# These are monitored passively; no undocumented commands are sent to them.
DIAGNOSTIC_CHANNELS = {
    "e00a": "0a0ae00a-0a00-1000-8000-00805f9b34fb",
    "1011": "0a0a1011-0a00-1000-8000-00805f9b34fb",
    "e00f": "0a0ae00f-0a00-1000-8000-00805f9b34fb",
    "e010": "0a0ae010-0a00-1000-8000-00805f9b34fb",
    "e011": "0a0ae011-0a00-1000-8000-00805f9b34fb",
    "1012": "0a0a1012-0a00-1000-8000-00805f9b34fb",
}
