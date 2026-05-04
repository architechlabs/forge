# Forge

Discover entities from other Home Assistant instances, review the native integrations they depend on, and import them into the current instance as managed helper/proxy entities.

Forge creates real Home Assistant helper entities through a managed package file and keeps them synchronized through the Home Assistant API. For device-native behavior, the target instance still needs the relevant integration configured, such as KNX, WiZ, MQTT, ZHA, Z-Wave JS, ESPHome, Matter, Shelly, Hue, or Tuya.

## Highlights

- Multiple source Home Assistant instances.
- Source URL and long-lived token storage inside the add-on data volume.
- Discovery of states, entity registry, device registry, and areas when permitted by the token.
- Integration requirement summary before import.
- Conflict handling with rename, update, or skip behavior.
- Managed YAML package generation under the Home Assistant config folder at `/config/packages` inside the add-on.
- Helper reload attempts after each import.
- Background sync and direct command forwarding for supported controllable domains.
- Responsive Ingress UI.

## Entity Strategy

The add-on imports source entities as managed local helpers:

- `switch`, `light`, `fan`, `lock`, `cover`, `binary_sensor`, and similar boolean states become `input_boolean` proxy helpers.
- Numeric `sensor`, `number`, and `input_number` states become `input_number` helpers.
- `select` and `input_select` states become `input_select` helpers.
- `button` and `input_button` states become `input_button` helpers.
- Other entities become `input_text` mirror helpers.

This makes the imported entities real entities in the current Home Assistant instance. Native recreation of hardware-backed entities is not possible from a remote HA token alone, so the UI shows which integrations are required for native setup.
