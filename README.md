# MiVia Run 350 for Home Assistant

Experimental custom integration for reading data from the **MiVia Run 350** over BLE.

> **Status: proof of concept.** The integration has been tested on one MiVia Run 350 device. BLE packet decoding is based on protocol behavior observed while studying the watch and its companion app; no app code, APK, firmware, or vendor library is included here.

## Current scope

- Connect to the watch using its Bluetooth address.
- Attempt BLE pairing/bonding before connecting. If the watch requires a passkey, the Bluetooth host must be able to handle the pairing prompt; this integration does not guess or hardcode a PIN.
- Subscribe to the Mercury control-point notification characteristic.
- Send the instantaneous-data enable command `40 01`.
- Decode version-0 instantaneous packets.
- Expose steps, total calories, and active calories as Home Assistant sensors.

The version-0 payload is decoded as big-endian fields: distance (u32), steps (u32), active time (u32), total calories (u16), active calories (u16). Distance and active-time fields are currently parsed but are not exposed because their units/scaling have not yet been independently verified.

## Install manually

1. Copy `custom_components/mivia_run350` into `/config/custom_components/mivia_run350`.
2. Restart Home Assistant.
3. Open **Settings → Devices & services → Add integration**.
4. Search for **MiVia Run 350** and enter the watch's Bluetooth address.
5. Keep the watch close to a Home Assistant Bluetooth adapter or Bluetooth proxy.
6. On first connection, allow up to 60 seconds for BLE pairing. If the watch asks for a passkey, enter the code requested by the watch/operating system. No default PIN is assumed.

The watch must be available to Home Assistant's Bluetooth scanner. Close the vendor phone app while testing because it may hold the BLE connection.

## Known limitations

- The integration opens a BLE connection for each refresh and requests instantaneous data. This is intentionally simple for initial protocol validation, not optimized for battery life.
- A fresh instantaneous notification is expected within 10 seconds. If no packet arrives, initial setup will fail with a diagnostic message.
- Only protocol structure version 0 is decoded.
- Battery level/charging state and heart-rate events are not implemented yet. Their GATT characteristics or Mercury protocol messages still need to be identified and tested.
- The watch's advertised address may be private/randomized on some firmware; if it changes, reconfigure the integration.
- No claim is made that this prototype is stable or compatible with every Home Assistant release.

## Tested watch firmware

The following versions were reported for the test device:

| Component | Version |
| --- | --- |
| Software | `0.0.2.4` |
| BLE | `00.03.03.10` |
| OHR | `7804` |
| GPS | `3` |

## Current BLE connection issue

The watch is advertised to Home Assistant as `FF:03:A6:F1:53:FA`. A Bluetooth proxy may appear as the advertisement `source`; that source address is the receiving Bluetooth adapter/proxy, not the watch address.

The prototype attempts BLE pairing (`pair=True`) and allows up to 60 seconds for the connection attempt. BlueZ previously reported `org.bluez.Error.ConnectionAttemptFailed: Page Timeout`, and ESPHome Bluetooth Proxy reported GATT connection errors. These indicate connection-layer problems, not proof of an incorrect passkey or a packet-decoding problem.

## Debug logging

Add to `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.mivia_run350: debug
    bleak: debug
```

Restart Home Assistant and inspect the logs if setup fails.

## License

The original integration code in this repository is licensed under the MIT License. This does not grant rights to MiVia/Mio-Magellan trademarks, firmware, companion-app code, or other third-party materials.
