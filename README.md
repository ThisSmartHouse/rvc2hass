# rvc2hass

RV-C CAN bus to Home Assistant via MQTT auto-discovery.

Replaces CoachProxy's Perl stack (`rvc2mqtt.pl`, `dc_dimmer.pl`,
`mqtt-launcher.py`, watchdog cron jobs) with a single Python service that reads
RV-C protocol frames from a CAN bus, decodes them, and publishes native Home
Assistant entities via MQTT auto-discovery. No custom HA component needed.

## Architecture

```
Raspberry Pi (CAN HAT)                    Home Assistant host
┌─────────────────────────────────┐       ┌─────────────────────┐
│  can0 (socketcan, 250kbps)      │       │                     │
│        ↓                        │       │  Mosquitto broker   │
│  rvc2hass                       │       │        ↓            │
│    ├─ python-can                │       │  Home Assistant     │
│    ├─ RV-C decoder              │  MQTT │  (auto-discovered   │
│    │  (specs/rvc_spec.yaml)     │ ─────►│   entities)         │
│    ├─ entity manager            │       │                     │
│    └─ paho-mqtt                 │       │  HA sends commands  │
│         ↑ command subscriptions │ ◄──── │  (light/switch/     │
│         └─ CAN frame writer     │       │   cover control)    │
└─────────────────────────────────┘       └─────────────────────┘
```

**Data flows:**
- **Read path:** CAN frame → RV-C decoder → entity manager → MQTT state topic → HA
- **Write path:** HA command → MQTT command topic → CAN frame builder → CAN bus → RV multiplex system

## Quick start

```bash
# Clone and install
git clone https://github.com/ThisSmartHouse/rvc2hass.git
cd rvc2hass
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# Run tests
.venv/bin/pytest -v

# Discover what's on your CAN bus
.venv/bin/python -m rvc2hass --profile profiles/thor_hurricane_35m.yaml --discover

# Run the service
.venv/bin/python -m rvc2hass --profile profiles/thor_hurricane_35m.yaml
```

## Three-layer data model

The system separates protocol knowledge from vehicle-specific configuration:

### 1. RV-C Protocol Spec (`specs/rvc_spec.yaml`)

Defines how to decode raw CAN frames. Shared across all RVs — currently covers
201 DGNs ported from CoachProxy. Adding a new DGN is just YAML, no code changes.

```yaml
1FEDA:
  name: DC_DIMMER_STATUS_3
  parameters:
    - byte: 0
      name: instance
      type: uint8
    - byte: 2
      name: "operating status (brightness)"
      type: uint8
      unit: pct
    - byte: 3
      bit: 2-3
      name: "lock status"
      type: bit
      values:
        "00": unlocked
        "01": locked
```

### 2. RV Profile (`profiles/*.yaml`)

Maps what's on **this specific RV** to Home Assistant entities. Different coaches
have different dimmer instances, tanks, etc. See
`profiles/thor_hurricane_35m.yaml` for a complete example.

```yaml
profile:
  name: "Thor Hurricane 35M"
  manufacturer: "Thor Motor Coach"
  model: "Hurricane 35M"
  year: 2020
  multiplex: "Firefly"

mqtt:
  broker: "10.11.12.11"
  port: 1883

can:
  interface: "socketcan"
  channel: "can0"
  bitrate: 250000

lights:
  - instance: 17
    name: "Living Room"
    dimmable: true
  - instance: 26
    name: "Cargo"
    dimmable: false

switches:
  - instance: 1
    name: "Front A/C Compressor"
    payload_on: 2
    payload_off: 3

covers:
  - name: "Awning"
    extend_instance: 24
    retract_instance: 25

sensors:
  - dgn: DC_SOURCE_STATUS_1
    instance: 1
    name: "House Battery Voltage"
    field: "dc voltage"
    unit: "V"
    device_class: voltage
  - dgn: TANK_STATUS
    instance: 0
    name: "Freshwater Tank"
    unit: "%"
    value_template: "relative_level / resolution * 100"

binary_sensors:
  - dgn: GENERATOR_STATUS_1
    name: "Generator Running"
    field: "status"
    on_value: 3
```

### 3. Entity Handlers (`rvc2hass/entities/`)

Generic Python code for each HA entity type. These work with any profile — a
light handler knows how to control any DC dimmer instance regardless of which
RV it's on.

## Creating a profile

1. **Start with discovery mode** to see what's on your bus:
   ```bash
   python -m rvc2hass --profile profiles/minimal.yaml --discover --discover-duration 120
   ```

2. **Map instances to physical devices.** Discovery reports DGN names and instance
   numbers. Walk around your RV toggling things to identify which instance
   controls what.

3. **Create your profile YAML** with the entity sections below.

### Profile entity reference

**lights** — DC dimmer instances exposed as HA lights:
| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `instance` | yes | — | DC dimmer instance number |
| `name` | yes | — | Display name in HA |
| `dimmable` | no | `true` | Whether to expose brightness control |

**switches** — DC dimmer instances exposed as HA switches:
| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `instance` | yes | — | DC dimmer instance number |
| `name` | yes | — | Display name in HA |
| `payload_on` | no | `2` | Command byte for on (1 or 2) |
| `payload_off` | no | `3` | Command byte for off |

**covers** — Paired extend/retract dimmer instances (slides, awnings):
| Field | Required | Description |
|-------|----------|-------------|
| `name` | yes | Display name in HA |
| `extend_instance` | yes | DC dimmer instance for extend/open |
| `retract_instance` | yes | DC dimmer instance for retract/close |

**sensors** — Values from any decoded DGN:
| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `dgn` | yes | — | DGN name from the spec (e.g. `TANK_STATUS`) |
| `name` | yes | — | Display name in HA |
| `instance` | no | `null` | DGN instance filter (null = any) |
| `field` | no | `null` | Decoded field name to use as value |
| `unit` | no | `null` | Unit of measurement |
| `device_class` | no | `null` | HA device class (voltage, temperature, battery) |
| `value_template` | no | `null` | Expression to compute value (see below) |
| `value_map` | no | `null` | Map raw values to strings |

Supported `value_template` expressions:
- `relative_level / resolution * 100` — Tank percentage from RV-C tank data
- `value / 60` — Convert minutes to hours (e.g. generator runtime)
- `voltage_to_soc` — Lead-acid battery voltage → state of charge percentage

**binary_sensors** — On/off from any decoded DGN field:
| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `dgn` | yes | — | DGN name from the spec |
| `name` | yes | — | Display name in HA |
| `instance` | no | `null` | DGN instance filter |
| `field` | no | `null` | Decoded field name to compare |
| `on_value` | no | `null` | Value that means "on" |

## Discovery mode

Scan the CAN bus to see what DGNs and instances are active:

```bash
python -m rvc2hass --profile profiles/thor_hurricane_35m.yaml --discover
```

Options:
- `--discover-duration N` — Scan for N seconds (default: 60)

Example output:
```
=== CAN Bus Discovery Report ===

Known DGNs seen:
  DC_DIMMER_STATUS_3 (1FEDA) - 864 frames, instances: [1,2,3,5,6,7,10,11,12,13,15,16,17,18,19,20,24,25,26,27,28,29,30,31,32,34,35]
  DC_SOURCE_STATUS_1 (1FFFD) - 124 frames, instances: [1,2]
  THERMOSTAT_AMBIENT_STATUS (1FF9C) - 62 frames, instances: [1,2]
  TANK_STATUS (1FFB7) - 31 frames, instances: [0,1,2,3,17,18]

UNKNOWN DGNs seen (not in rvc_spec.yaml):
  DGN 1FEBD - 45 frames, src addresses: [42, 44]

Instances in profile but NOT seen on bus (possible config errors):
  DC_DIMMER_STATUS_3 instance 34 - no traffic (generator may be off)

Instances seen on bus but NOT in profile (candidates to add):
  DC_DIMMER_STATUS_3 instance 4 - seen 62 frames (not in profile)
```

## MQTT topics

| Topic pattern | Direction | Purpose |
|---------------|-----------|---------|
| `rvc2hass/status` | → broker | LWT: `online` / `offline` |
| `rvc2hass/<type>/<id>/state` | → broker | State updates from CAN bus |
| `rvc2hass/<type>/<id>/set` | ← broker | Commands from HA |
| `homeassistant/<type>/rvc_*/config` | → broker | Discovery configs (retained) |

All entities are grouped under a single HA device ("RV-C Bus") using the profile's
manufacturer and model.

## Command handling

### Lights and switches

Commands use the DC_DIMMER_COMMAND_2 DGN (0x1FEDB). The service builds 8-byte
CAN frames with this layout:

| Byte | Field | Value |
|------|-------|-------|
| 0 | Instance | Dimmer instance number |
| 1 | Group | 0xFF (all groups) |
| 2 | Brightness | 0-200 (percentage * 2) |
| 3 | Command | 1=on, 2=on-delay, 3=off, 17=ramp, etc. |
| 4 | Duration | 0xFF (no delay) |
| 5 | Interlock | 0x00 (none) |
| 6-7 | Reserved | 0xFF |

### Brightness ramping

Dimmable lights use a two-phase sequence matching the Firefly multiplex
system's expectations:

1. Send ramp command (command byte 17) with target brightness
2. Wait 5 seconds for the Firefly to physically ramp to target
3. Send stop command (command byte 21) + lock command (command byte 4)

The service uses `threading.Timer` for the 5-second delay between phases.

### Covers

Covers use two DC dimmer instances — one for extend, one for retract. Open sends
command 1 (on-duration) to the extend instance; close sends it to the retract
instance; stop sends command 3 (off) to both.

### Optimistic state

The Firefly multiplex system only broadcasts status for active devices (lights
that are on). When a device is turned off, it stops sending status frames. The
service publishes optimistic state updates immediately after sending commands
to keep HA in sync.

## Deployment

### Install on the CAN bus Pi

```bash
# Copy the project
rsync -avz --exclude='__pycache__' --exclude='.git' --exclude='*.pyc' \
  . pi@your-can-pi:/opt/rvc2hass/

# On the Pi: create venv and install
ssh pi@your-can-pi
cd /opt/rvc2hass
python3 -m venv .venv
.venv/bin/pip install --upgrade pip setuptools wheel
.venv/bin/pip install -e .
```

### systemd service

```bash
sudo cp systemd/rvc2hass.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now rvc2hass

# Check status
sudo systemctl status rvc2hass
sudo journalctl -u rvc2hass -f
```

The service auto-restarts on crash with a 5-second delay.

### Updating

```bash
# From your dev machine
rsync -avz --exclude='__pycache__' --exclude='.git' --exclude='*.pyc' \
  --exclude='.venv' . pi@your-can-pi:/opt/rvc2hass/

# Restart the service
ssh pi@your-can-pi sudo systemctl restart rvc2hass
```

## RV-C protocol primer

RV-C is a CAN bus protocol (250 kbps, 29-bit extended IDs) used by RV
multiplex systems like Firefly, Spyder, and Silverleaf.

### CAN arbitration ID layout

```
Bits 28-26: Priority (3 bits, typically 6)
Bit  25:    Reserved (always 0)
Bits 24-8:  DGN — Data Group Number (17 bits)
Bits  7-0:  Source Address (8 bits)

Example: 0x19FEDA9F
  Priority = 6, DGN = 1FEDA (DC_DIMMER_STATUS_3), Source = 0x9F
```

### Byte ordering

Multi-byte values are transmitted **least-significant byte first**
(little-endian). The decoder swaps byte order when extracting multi-byte fields.

### Unit conversions (RV-C Table 5.3)

| Unit | uint8 | uint16 | uint32 |
|------|-------|--------|--------|
| pct | value / 2 | — | — |
| Deg C | value - 40 | value * 0.03125 - 273 | — |
| V | value | value * 0.05 | — |
| A | value | value * 0.05 - 1600 | value * 0.001 - 2000000 |
| Hz | value | value / 128 | — |

Sentinel values (0xFF for uint8, 0xFFFF for uint16) mean "not available".

## Project structure

```
rvc2hass/
├── rvc2hass/
│   ├── __main__.py         # CLI entry point
│   ├── app.py              # Main async service loop
│   ├── can_bus.py          # python-can wrapper (read/write)
│   ├── config.py           # Profile loading, CLI arg parsing
│   ├── discovery.py        # Bus discovery/scanning mode
│   ├── entity_manager.py   # Routes decoded messages → MQTT state
│   ├── mqtt_client.py      # MQTT connection, discovery, commands
│   ├── rvc_decoder.py      # RV-C protocol decoder
│   └── entities/
│       ├── light.py        # DC dimmer light commands
│       ├── switch.py       # DC dimmer switch commands
│       └── cover.py        # Cover extend/retract commands
├── specs/
│   └── rvc_spec.yaml       # RV-C DGN definitions (201 DGNs)
├── profiles/
│   └── thor_hurricane_35m.yaml  # Example: Thor Hurricane 35M
├── systemd/
│   └── rvc2hass.service    # systemd unit file
├── tests/                  # pytest test suite (165 tests)
├── pyproject.toml
└── README.md
```

## CLI reference

```
usage: rvc2hass [-h] --profile PROFILE [--spec SPEC] [--discover]
                [--discover-duration N] [--debug]

options:
  --profile PROFILE       Path to the RV profile YAML file (required)
  --spec SPEC             Path to the RV-C spec YAML
                          (default: specs/rvc_spec.yaml)
  --discover              Scan the bus and report what's there
  --discover-duration N   Seconds to scan in discovery mode (default: 60)
  --debug                 Enable debug logging
```

## Testing

```bash
# Run all tests
.venv/bin/pytest -v

# Run a specific test module
.venv/bin/pytest tests/test_decoder.py -v

# Run with coverage
.venv/bin/pytest --cov=rvc2hass -v
```

Tests use virtual CAN (`vcan0`) where hardware tests are needed. Most tests are
pure unit tests that don't require any CAN hardware.

## License

MIT
