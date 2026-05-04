# Instance Entity Bridge Documentation

## Setup

1. Install and start the add-on.
2. Open the add-on from the Home Assistant sidebar.
3. Add one or more source Home Assistant instances.
4. Use a long-lived access token from each source instance.
5. Scan, review the plan, and import selected entities.

## Add-on Options

| Option | Description |
| --- | --- |
| `log_level` | Runtime log level. |
| `poll_interval` | Seconds between background synchronization passes. |
| `allow_config_writes` | Allows the add-on to manage `/homeassistant/packages/<package_name>.yaml` and enable packages in `configuration.yaml`. |
| `package_name` | Name of the generated package file. |
| `max_entities_per_import` | Maximum number of entities accepted in one import request. |

## Files Managed

The add-on writes:

- `/data/entity_bridge_store.json`
- `/homeassistant/packages/<package_name>.yaml`
- a one-time `configuration.yaml.<package_name>.bak` backup before adding package support

The add-on only writes Home Assistant configuration when `allow_config_writes` is enabled.

## Native Integrations

The source Home Assistant API can expose entity states and registry metadata, but it cannot provide enough information to safely recreate every integration config entry on another instance. Native device entities from integrations like KNX, WiZ, Matter, ZHA, Z-Wave JS, MQTT, Hue, Shelly, and ESPHome require those integrations to be configured on the target instance.

The bridge therefore creates local proxy/mirror helpers and shows native requirements in the import plan.

## Control Forwarding

Direct command forwarding is supported for:

- `switch`
- `light`
- `fan`
- `lock`
- `cover`
- `number`
- `select`
- `input_boolean`
- `input_number`
- `input_select`

Unsupported domains are imported as mirrors.

## Recovery

To remove all imported helper entities:

1. Delete imports in the add-on UI, or clear `/homeassistant/packages/<package_name>.yaml`.
2. Reload helper integrations or restart Home Assistant.
3. Keep the backup file until the target Home Assistant configuration has been verified.
