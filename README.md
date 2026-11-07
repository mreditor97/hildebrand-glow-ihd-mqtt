# Home Assistant Hildebrand Glow IHD Integration

A Home Assistant custom integration for the **Hildebrand Glow IHD** (in-home display) and **Glow CAD**. It reads your smart meter data **locally over MQTT**: no cloud account or API polling is needed.

The device publishes the readings from your SMETS1/SMETS2 smart meter to your MQTT broker. This integration subscribes to those messages and creates Home Assistant sensors for electricity and gas usage, tariff prices, daily cost and device diagnostics, which you can use in the Energy dashboard.

![Glow device and sensors in Home Assistant](https://user-images.githubusercontent.com/1478003/173249987-4724af89-ceaa-4422-a426-4b8a2b16d98e.png)

## Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Sensors](#sensors)
- [Energy dashboard](#energy-dashboard)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [Credits](#credits)

## Requirements

- A [Hildebrand Glow IHD or CAD](https://shop.glowmarkt.com/products/display-and-cad-combined-for-smart-meter-customers) paired with your smart meter.
- An MQTT broker, such as the Mosquitto broker add-on, and the [MQTT integration](https://www.home-assistant.io/integrations/mqtt/) set up in Home Assistant.
- Local MQTT turned on for your Glow device and pointed at your broker. This [guide by Joshua Cooper](https://medium.com/@joshua.cooper/glow-local-mqtt-f69b776b7af4) explains how.
- Home Assistant 2026.11 or newer, which includes the Marketplace.

## Installation

### Home Assistant Marketplace (recommended)

1. Open **Settings → Marketplace** and add this repository as a custom repository, with the type **Integration**:
   `https://github.com/mreditor97/integration-hildebrand-glow-ihd`
2. Search for **Hildebrand Glow IHD Integration** and install it.
3. Restart Home Assistant.

### Manual

1. Copy the `custom_components/hildebrand_glow_ihd` folder from this repository into your Home Assistant config folder's `custom_components` folder. The folder name must match the integration's domain, `hildebrand_glow_ihd`.
2. Restart Home Assistant.

## Configuration

Go to **Settings → Devices & services → Add integration** and search for **Hildebrand Glow IHD Integration**.

| Option                      | Default           | Description                                                                                                                                                                                                          |
| --------------------------- | ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Device ID                   | `+`               | Leave as `+` to detect every Glow device publishing to your broker (recommended). To limit it to one device, enter that device's ID: the part of the topic after the prefix, e.g. `glow/`**`AABBCCDDEEFF`**`/STATE`. |
| Topic prefix                | `glow`            | The first part of the MQTT topic. Only change this if you changed it on the device.                                                                                                                                  |
| Electricity meter time zone | Your HA time zone | The time zone your electricity meter's daily total resets in.                                                                                                                                                        |
| Gas meter time zone         | Your HA time zone | The time zone your gas meter's daily total resets in. Some gas meters reset at midnight UTC (01:00 during British Summer Time). If yours does, choose `UTC`.                                                         |

Each Glow device appears as a device named **Glow Smart Meter &lt;device id&gt;**, and its sensors appear as soon as the first MQTT message arrives.

To change these settings later, open the integration and select **Configure**. The integration reloads to apply them.

## Sensors

Home Assistant shows each sensor after its device's name, e.g. **Glow Smart Meter AABBCCDDEEFF Electricity: Import (Today)**, and new entity IDs look like `sensor.glow_smart_meter_aabbccddeeff_electricity_import_today`. Entity IDs of sensors you already have aren't changed.

### Electricity

| Sensor                                               | Unit    | Notes                                       |
| ---------------------------------------------------- | ------- | ------------------------------------------- |
| Electricity: Import                                  | kWh     | Lifetime meter reading                      |
| Electricity: Import (Today / This week / This month) | kWh     | Reset by the meter                          |
| Electricity: Export                                  | kWh     | Lifetime export reading                     |
| Electricity: Power                                   | kW      | Current demand                              |
| Electricity: Import Unit Rate                        | GBP/kWh | Current unit rate                           |
| Electricity: Import Standing Charge                  | GBP     | Daily standing charge                       |
| Electricity: Cost (Today)                            | GBP     | Standing charge + today's usage × unit rate |

### Gas

| Sensor                                           | Unit    | Notes                                       |
| ------------------------------------------------ | ------- | ------------------------------------------- |
| Gas: Import                                      | kWh     | Lifetime meter reading                      |
| Gas: Import (Today / This week / This month)     | kWh     | Reset by the meter                          |
| Gas: Import Vol                                  | m³      | Lifetime volume reading                     |
| Gas: Import Vol (Today / This week / This month) | m³      | Reset by the meter                          |
| Gas: Import Unit Rate                            | GBP/kWh | Current unit rate                           |
| Gas: Import Standing Charge                      | GBP     | Daily standing charge                       |
| Gas: Cost (Today)                                | GBP     | Standing charge + today's usage × unit rate |

There is no live gas power sensor: the IHD stopped publishing gas power in software update 1.8.13 (June 2022).

### Diagnostics

IHD software version, hardware, HAN (Zigbee) status, HAN RSSI and HAN LQI.

## Energy dashboard

In **Settings → Dashboards → Energy**:

- **Electricity grid consumption:** `Electricity: Import`
- **Return to grid:** `Electricity: Export` (if you export)
- **Gas consumption:** `Gas: Import` (kWh) or `Gas: Import Vol` (m³)
- **Cost:** choose _Use an entity with current price_ and pick the matching **Import Unit Rate** sensor.

The lifetime **Import** sensors give the most reliable statistics. The _Today_ sensors and _Cost (Today)_ reset every day, so a reset at an unexpected time can show up as a spike or a negative value.

## Troubleshooting

**No sensors appear.** Check that the device is publishing to your broker. Subscribe to `glow/#`, for example with MQTT Explorer or:

```sh
mosquitto_sub -h <broker> -u <user> -P <password> -t 'glow/#' -v
```

You should see `glow/<device id>/STATE`, `glow/<device id>/SENSOR/electricitymeter` and, if you have gas, `glow/<device id>/SENSOR/gasmeter`. If the topic prefix or device ID doesn't match your configuration, no sensors are created.

**Prices or cost show as unknown.** The device publishes `null` prices until your supplier sends tariff data to the meter. This depends on the supplier, not on this integration.

**Daily values reset at 01:00 instead of midnight.** The meter resets its daily totals in UTC. Add the integration again with that meter's time zone set to `UTC` (see [Configuration](#configuration)).

**Debug logging.** Add this to `configuration.yaml`, restart, and check the log:

```yaml
logger:
  logs:
    custom_components.hildebrand_glow_ihd: debug
```

## Development

The integration is in `custom_components/hildebrand_glow_ihd`. The files Home Assistant loads by name (`__init__.py`, `config_flow.py`, `sensor.py`, `manifest.json` and the translations) are at the top of that folder. `helpers.py` reads the topics and payloads the Glow device publishes.

The development tools need [uv](https://docs.astral.sh/uv/) and Python 3.14. The tests run against the Home Assistant version that `pytest-homeassistant-custom-component` pins in `pyproject.toml`.

```bash
uv sync
uv run pytest
uv run mypy
uv run pre-commit run --all-files
```

## Credits

- Originally created by [@megakid](https://github.com/megakid) as [ha_hildebrand_glow_ihd_mqtt](https://github.com/megakid/ha_hildebrand_glow_ihd_mqtt), and improved by its contributors.
- Inspired by and heavily based on [@robertalexa](https://github.com/robertalexa)'s [Home Assistant community thread](https://community.home-assistant.io/t/glow-hildebrand-display-local-mqtt-access-template-help/428638).
