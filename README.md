<p align="center">
  <img src="logo.png" alt="BimmerData Streamline logo" width="240" />
</p>

# BimmerData Streamline (BMW CarData for Home Assistant)

## This is experimental. Wait for the core integration to get fixed if you want stable experience but if you want to help, keep reporting the bugs and I'll take a look! :) The Beta branch is used as a day to day development branch and can contain even completely broken stuff. The main branch is updated when I feel that it works well enough and has something new. However, the integration currently lacks proper testing and I also need to keep my own automations running so not everything is tested on every release and there's a possibility that something works on my instance, since I already had something installed. Create an issue if you have problems when making a clean install. 


## Known problems: 
### BEV battery update rate is quite slow. Latest version has "extrapolated SOC" sensor that is calculated dynamically from the last known soc, charging speed and time. It's still really early revision and lacks some features. For example it won't detect when the target SOC is reached and charging stopped, before the car actually sends a message.
### Log shows constant RC=7 dis/reconnects. That's on purpose and is caused by >60 Keepalive time. Lower keepalive time seems to make the connection stay alive, but after a while BMW stops sending updates. Reconnecting periodically fixes that issue. Some users reported seeing data even with lower keepalive, so I'll keep experimenting with that.
### Either because of the forced disconnections or something else, I once got the integration into disconnected state where it didn't try to reconnect. It's on my todo list, but hard to debug since it happens after hours of working.

## Upcoming features:
### Goal is to also utilize the 50 API requests/24h that the public cardata provides. Those could be used to increase the data resolution when the stream is quiet and fetch some data not available on the stream (car model, target soc, etc.)

Turn your BMW CarData stream into native Home Assistant entities. This integration subscribes directly to the BMW CarData MQTT stream, keeps the token fresh automatically, and creates sensors/binary sensors for every descriptor that emits data.

**IMPORTANT: I released this to public after verifying that it works on my automations, so the testing time has been quite low so far. If you're running any critical automations, please don't use this plugin yet.**

> **Note:** This entire plugin was generated with the assistance of AI to quickly solve issues with the legacy implementation. The code is intentionally open—to-modify, fork, or build a new integration from it. PRs are welcome unless otherwise noted in the future.

> **Tested Environment:** The integration has only been verified on my own Home Assistant instance (2024.12.5). Newer releases might require adjustments.

> **Heads-up:** The first authentication attempt occasionally stalls. If the integration immediately asks for re-auth, repeat the flow slowly—sign in on the BMW page, wait a moment after the portal confirms, then click Submit in Home Assistant. Once it completes, trigger an action in the MyBMW app (e.g., lock/unlock) to nudge the vehicle to send data and give it a couple of minutes to appear. So far the most reliant way to trigger the stream seems to be to change the charging speed remotely.

> **Heads-up:** I've tested this on 2022 i4 and 2016 i3. Both show up entities, i4 sends them instantly after locking/closing the car remotely using MyBMW app. i3 seems to send the data when it wants to. So far after reinstalling the plugin, I haven't seen anything for an hour, but received data multiple times earlier. So be patient, maybe go and drive around or something to trigger the data transfer :) 


## Features

- Device Code / PKCE auth flow
- Automatic token refreshing at 45-minute intervals.
- Direct MQTT streaming (`GCID/+/#`) with auto-reconnect and re-auth if credentials go stale.
- Sensors & binary sensors appear dynamically when descriptors send data (door states, charging info, HVAC settings, etc.).
- Device metadata (BMW VIN + model name) populated from `vehicle.vehicleIdentification.basicVehicleData`.

## BMW Portal Setup (DON'T SKIP, DO THIS FIRST)

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
8. Repeat for all the cars you want to support
9. Install this integration via HACS.
10. During the Home Assistant config flow, paste the client ID, visit the provided verification URL, enter the code (if asked), and approve. **Do not click Continue/Submit in Home Assistant until the BMW page confirms the approval**; submitting early leaves the flow stuck and requires a restart.
11. Wait for the car to send data—triggering an action via the MyBMW app (lock/unlock doors) usually produces updates immediately.

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

- Each VIN becomes a device in HA (`VIN` pulled from CarData).
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
