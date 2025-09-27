<p align="center">
  <img src="logo.png" alt="BimmerData Streamline logo" width="240" />
</p>

# BimmerData Streamline (BMW CarData for Home Assistant)

Turn your BMW CarData stream into native Home Assistant entities. This integration subscribes directly to the BMW CarData MQTT stream, keeps the token fresh automatically, and creates sensors/binary sensors for every descriptor that emits data.

> **Note:** This entire plugin was generated with the assistance of AI to quickly solve issues with the legacy implementation. The code is intentionally open—modify, fork, or build a new integration from it. PRs are welcome unless otherwise noted in the future.

> **Tested Environment:** The integration has only been verified on my own Home Assistant instance (2024.12.5). Newer releases might require adjustments.

## Features

- Device Code / PKCE auth flow
- Automatic token refreshing at 45-minute intervals.
- Direct MQTT streaming (`GCID/+/#`) with auto-reconnect and re-auth if credentials go stale.
- Sensors & binary sensors appear dynamically when descriptors send data (door states, charging info, HVAC settings, etc.).
- Device metadata (BMW VIN + model name) populated from `vehicle.vehicleIdentification.basicVehicleData`.

## BMW Portal Setup

The CarData web portal isn’t available everywhere (e.g., it’s disabled in Finland). You can still enable streaming by logging into https://www.bmw.de/de-de/mybmw/vehicle-overview and following these steps:

1. Select the vehicle you want to stream.
2. Choose **BMW CarData**.
3. Generate a client ID as described here: https://bmw-cardata.bmwgroup.com/customer/public/api-documentation/Id-Technical-registration_Step-1
4. Subscribe the client to both scopes: `cardata:api:read` and `cardata:streaming:read`.
5. Scroll to the **Data Selection** section (`Datenauswahl ändern`) and load all descriptors (keep clicking “Load more”).
6. Check every descriptor you want to stream. To automate this, open the browser console and run:

```js
(() => {
  const labels = document.querySelectorAll('.css-k008qs label.chakra-checkbox');
  let changed = 0;

  labels.forEach(label => {
    const input = label.querySelector('input.chakra-checkbox__input[type="checkbox"]');
    if (!input || input.disabled || input.checked) return;

    label.click();
    if (!input.checked) {
      const ctrl = label.querySelector('.chakra-checkbox__control');
      if (ctrl) ctrl.click();
    }
    if (!input.checked) {
      input.checked = true;
      ['click', 'input', 'change'].forEach(type =>
        input.dispatchEvent(new Event(type, { bubbles: true }))
      );
    }
    if (input.checked) changed++;
  });

  console.log(`Checked ${changed} of ${labels.length} checkboxes.`);
})();
```

7. Save the selection.
8. Install this integration via HACS.
9. During the Home Assistant config flow, paste the client ID, visit the provided verification URL, enter the code (if asked), and approve. **Do not click Continue/Submit in Home Assistant until the BMW page confirms the approval**; submitting early leaves the flow stuck and requires a restart.
10. Wait for the car to send data—triggering an action via the MyBMW app (lock/unlock doors) usually produces updates immediately.

## Installation (HACS)

1. Add this repo to HACS as a **custom repository** (type: Integration).
2. Install "BimmerData Streamline" from the Custom section.
3. Restart Home Assistant.

## Configuration Flow

1. Go to **Settings → Devices & Services → Add Integration** and pick **BimmerData Streamline**.
2. Enter your CarData **client ID** (created in the BMW portal).
3. The flow displays a `verification_url` and `user_code`. Open the link, enter the code, and approve the device.
4. Once the BMW portal confirms the approval, return to HA and click Submit. If you accidentally submit before finishing the BMW login, the flow will hang until the device-code exchange times out; cancel it and start over after completing the BMW login.
5. If you remove the integration later, you can re-add it with the same client ID—the flow deletes the old entry automatically.

### Reauthorization
If BMW rejects the token (e.g. because the portal revoked it), the integration:
- Logs `BMW MQTT connection failed: rc=5`
- Shows a persistent notification in HA
- Causes a re-auth flow to appear, where you repeat the approval steps

## Entity Naming & Structure

- Each VIN becomes a device in HA (`VIN` + model name pulled from CarData).
- Sensors/binary sensors are auto-created and named from descriptors (e.g. `Cabin Door Row1 Driver Is Open`).
- Additional attributes include the source timestamp.

## Debug Logging
Set `DEBUG_LOG = True` in `custom_components/cardata/const.py` for detailed MQTT/auth logs (enabled by default). To reduce noise, change it to `False` and reload HA.

## Requirements

- BMW CarData account with streaming access (CarData API + CarData Streaming subscribed in the portal).
- Client ID created in the BMW portal (see "BMW Portal Setup").
- Home Assistant 2024.6+.
- Familiarity with BMW’s CarData documentation: https://bmw-cardata.bmwgroup.com/customer/public/api-documentation/Id-Introduction

## Known Limitations

- Only one BMW stream per GCID: make sure no other clients are connected simultaneously.
- The CarData API is read-only; sending commands remains outside this integration.
- Premature Continue in auth flow: If you hit Continue before authorizing on BMW’s site, the device-code flow gets stuck. Cancel the flow and restart the integration (or Home Assistant) once you’ve completed the BMW login.

## License

This project is released into the public domain. Do whatever you want with it—personal, commercial, derivative works, etc. No attribution required (though appreciated).
