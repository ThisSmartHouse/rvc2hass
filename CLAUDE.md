# CLAUDE.md

## Project Overview

rvc2hass is a Python service that bridges RV-C CAN bus protocols to Home Assistant via MQTT auto-discovery. It runs on a Raspberry Pi with a CAN HAT, reads RV-C protocol frames, decodes them using a YAML spec, and publishes native HA entities. It also handles commands from HA (lights, switches, covers) by encoding and sending CAN frames back to the bus.

This replaced CoachProxy's Perl stack (rvc2mqtt.pl, dc_dimmer.pl, mqtt-launcher.py, watchdog cron jobs) with a single Python service.

## Architecture

See README.md for the full architecture diagram and three-layer data model.

**Data flows:**
- **Read:** CAN frame → `rvc_decoder` → `entity_manager` → MQTT state → HA
- **Write:** HA → MQTT command → `app._setup_commands` handler → entity builder → `can_reader.send()` → CAN bus

**Threading model:**
- asyncio event loop (main)
- CAN read loop runs in a `ThreadPoolExecutor` via `run_in_executor` (single blocking thread)
- paho-mqtt `loop_start()` runs its own background thread for MQTT I/O
- MQTT command callbacks execute on the paho thread, NOT the asyncio thread
- `threading.Timer` used for brightness ramp delays (fires on yet another thread)

## Environment & Deployment

### Network Topology
- **Main Pi** (this machine): `10.11.12.11` — runs Home Assistant, Mosquitto (Docker), Ansible
- **CAN Pi** (`rvc.coogle.rv` / `10.11.12.8`): runs rvc2hass, has CAN HAT
- **10.11.12.2**: OLD mosquitto broker — do NOT use (legacy, no longer active)

### Deployment Target
- Host: `pi@rvc.coogle.rv` (ssh accessible)
- Install path: `/opt/rvc2hass/`
- Venv: `/opt/rvc2hass/.venv/` (Python 3.7.3 on Raspbian Buster)
- Service: `rvc2hass.service` (systemd, enabled, auto-restart)
- Profile: `/opt/rvc2hass/profiles/thor_hurricane_35m.yaml`

### MQTT Broker
- Host: `10.11.12.11:1883` (Docker container named `mosquitto` on the main Pi)
- To subscribe/publish from main Pi: `docker exec mosquitto mosquitto_sub ...`
- Do NOT use a local mosquitto_sub binary — use the Docker container's client

### Home Assistant
- Runs on main Pi in Docker, port 80 (not 8123)
- `hass-cli` available: `source /home/john/.shell_env && hass-cli ...`
- Live config at `/home/john/homeassistant/` (Docker volume mount)
- HA config repo: `/home/john/rv-homeassistant/`

## Common Commands

### Run tests
```bash
.venv/bin/pytest tests/ -v
```

### Deploy to CAN Pi
```bash
# Sync source only (not venv)
rsync -avz --exclude='__pycache__' --exclude='.git' --exclude='*.pyc' \
  --exclude='.venv' . pi@rvc.coogle.rv:/opt/rvc2hass/

# If dependencies changed, rebuild venv on Pi:
ssh pi@rvc.coogle.rv "/opt/rvc2hass/.venv/bin/pip install -e /opt/rvc2hass/"

# Restart service
ssh pi@rvc.coogle.rv "sudo systemctl restart rvc2hass"
```

### Check service status
```bash
ssh pi@rvc.coogle.rv "sudo systemctl status rvc2hass"
ssh pi@rvc.coogle.rv "sudo journalctl -u rvc2hass --since '10 minutes ago' --no-pager"
```

### Monitor MQTT traffic
```bash
# All rvc2hass state updates
docker exec mosquitto mosquitto_sub -t 'rvc2hass/#' -v

# Specific entity
docker exec mosquitto mosquitto_sub -t 'rvc2hass/light/18/#' -v

# Discovery configs
docker exec mosquitto mosquitto_sub -t 'homeassistant/#' -v
```

### Test entity control via HA
```bash
source /home/john/.shell_env
hass-cli service call light.turn_on --arguments 'entity_id=light.rvc_bedroom'
hass-cli service call light.turn_on --arguments 'entity_id=light.rvc_living_room,brightness_pct=50'
hass-cli state get light.rvc_bedroom
hass-cli --output json state get light.rvc_living_room
```

### Check CAN bus directly
```bash
ssh pi@rvc.coogle.rv "candump can0 -n 5"
ssh pi@rvc.coogle.rv "ip link show can0"
```

## Debugging Workflow

When commands from HA aren't working:

1. **Check service is running:** `ssh pi@rvc.coogle.rv "sudo systemctl status rvc2hass"`
2. **Check state updates flowing:** `docker exec mosquitto mosquitto_sub -t 'rvc2hass/#' -v -W 5`
   - If only `rvc2hass/status online` appears (no sensor/light states), the CAN read loop has died. Restart the service.
3. **Check CAN bus is alive:** `ssh pi@rvc.coogle.rv "candump can0 -n 3 -T 3000"`
4. **Check command arrives at MQTT:** Subscribe to the command topic, then trigger from HA
5. **Check service logs:** `ssh pi@rvc.coogle.rv "sudo journalctl -u rvc2hass --since '5 minutes ago' --no-pager"`
6. **Health logging:** The CAN read loop logs frame counts every 5 minutes. If these stop appearing in the journal, the loop has stalled.

## Conventions

### Git Commits
Never add `Co-Authored-By` lines to commit messages.

### Python Compatibility
All code must work on Python 3.7 (Raspbian Buster on the CAN Pi). Use `from __future__ import annotations` in every module for `X | Y` type union syntax.

### Entity Naming
All HA entities are prefixed `rvc_`. The `slugify()` function in `mqtt_client.py` converts names (e.g., "Living Room" → `living_room`). Entity IDs become `light.rvc_living_room`, `switch.rvc_furnace`, etc.

## Critical Lessons Learned

### Firefly Multiplex System Behavior
The RV uses a Firefly multiplex system for lighting/switch/cover control. Key behaviors:

- **Stops broadcasting when off:** Firefly only sends DC_DIMMER_STATUS_3 frames for devices that are actively on. When a light is turned off, it stops sending status. This means we MUST publish optimistic state updates immediately after sending commands — otherwise HA never learns the device turned off.
- **Brightness ramping needs 5-second delay:** Setting brightness requires: (1) send ramp command, (2) wait 5 seconds for Firefly to physically ramp, (3) send stop + lock commands. Sending all three back-to-back doesn't work — the Firefly ignores the stop because it hasn't started ramping yet. See `build_brightness_ramp()` / `build_brightness_stop()` in `entities/light.py`.
- **DC_DIMMER_COMMAND_2 (DGN 0x1FEDB):** All light/switch/cover commands use this DGN. Command bytes: 1=on-duration, 2=on-delay, 3=off, 4=lock, 17=ramp, 21=stop.

### Cover State Tracking
Each cover has TWO dimmer instances (extend + retract) that BOTH broadcast status continuously. If you naively map each instance to a state independently, the cover entity will bounce rapidly between "open" and "closed" in the HA UI. The `entity_manager` tracks both instances together and derives state from the combination, with deduplication to only publish on actual changes.

### HA MQTT Discovery Gotchas
- Do NOT include `"schema": "default"` in light discovery configs — modern HA versions reject this field and the entity silently fails to create.
- Use `"on_command_type": "brightness"` for dimmable lights so HA sends brightness commands on turn_on.
- `brightness_scale` is 100 (not 255) because RV-C uses 0-100%.

### CAN Read Loop Resilience
The CAN read loop runs in a thread executor. If an exception in the frame callback propagates out of `_read_loop`, the entire loop dies silently. Exceptions in the callback MUST be caught and logged inside `_read_loop` to prevent this. The `read_frames` method also logs a warning if `_read_loop` exits unexpectedly and auto-reconnects.

### Variable Scoping in Command Handlers
Command handlers are created in loops (`for light in profile.lights`). Always use the factory pattern (`make_light_handler(lt)`) to capture the loop variable. Without this, all handlers would reference the last value of the loop variable (classic Python closure gotcha).

### paho-mqtt v2 API
This project uses paho-mqtt >= 2.0. The `Client()` constructor requires `callback_api_version=mqtt.CallbackAPIVersion.VERSION2`. The `on_connect` callback signature includes a `properties` parameter.

### Sensor Template Evaluation Order
In `entity_manager._handle_sensor()`, `value_template` must be checked BEFORE `field`. If both are set, the template should take precedence — it may use the field value as input (e.g., `voltage_to_soc` reads voltage from the `field` but applies a lookup table).

## Project Structure

```
rvc2hass/
├── rvc2hass/
│   ├── __main__.py         # CLI entry point, mode selection
│   ├── app.py              # Main service loop, command wiring
│   ├── can_bus.py          # python-can wrapper (threaded read, send)
│   ├── config.py           # Profile YAML loading, dataclasses, CLI args
│   ├── discovery.py        # Bus scan mode (--discover)
│   ├── entity_manager.py   # Decoded frames → MQTT state routing
│   ├── mqtt_client.py      # MQTT connection, discovery, commands
│   ├── rvc_decoder.py      # RV-C protocol decoder (from spec YAML)
│   └── entities/
│       ├── light.py        # DC dimmer light CAN frame builders
│       ├── switch.py       # DC dimmer switch CAN frame builders
│       └── cover.py        # Cover extend/retract CAN frame builders
├── specs/
│   └── rvc_spec.yaml       # RV-C DGN definitions (201 DGNs)
├── profiles/
│   └── thor_hurricane_35m.yaml  # This RV's entity config
├── systemd/
│   └── rvc2hass.service    # systemd unit file
├── tests/                  # pytest suite (169 tests)
├── pyproject.toml
└── README.md               # Full documentation
```
