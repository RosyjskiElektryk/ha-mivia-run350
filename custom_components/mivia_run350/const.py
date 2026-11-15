"""Constants for the MiVia Run 350 integration."""

DOMAIN = "mivia_run350"
CONF_ADDRESS = "address"

CONTROL_POINT_SERVICE_UUID = "0a0a1010-0a00-1000-8000-00805f9b34fb"
CONTROL_POINT_CHARACTERISTIC_UUID = "0a0a1011-0a00-1000-8000-00805f9b34fb"

# Mercury protocol opcodes/events confirmed from the companion application's
# protocol classes. 0x40 enables instantaneous data; 0x71 carries that data.
OPCODE_INSTANTANEOUS_DATA = 0x40
EVENT_INSTANTANEOUS_DATA = 0x71
