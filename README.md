# rvc2hass

RV-C CAN bus to Home Assistant via MQTT auto-discovery.

Reads RV-C protocol frames from a CAN bus interface, decodes them using a
YAML-based protocol spec, and publishes state updates to Home Assistant via
MQTT auto-discovery. Also handles commands from HA (lights, switches, covers)
by encoding and sending CAN frames back to the bus.

## Architecture

```
CAN HAT → can0
      ↓
rvc2hass (Python, asyncio)
  ├─ python-can (socketcan)
  ├─ RV-C decoder (specs/rvc_spec.yaml)
  ├─ paho-mqtt
  │   ├─ homeassistant/*/rvc_*/config  (discovery, retained)
  │   ├─ rvc2hass/*/state              (state updates)
  │   └─ rvc2hass/*/set                (command subscriptions)
  └─ profiles/thor_hurricane_35m.yaml  (what's on this RV)
```

## Quick Start

```bash
# Create venv and install
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# Run with a profile
.venv/bin/python -m rvc2hass --profile profiles/thor_hurricane_35m.yaml

# Discovery mode — scan the bus and report what's there
.venv/bin/python -m rvc2hass --profile profiles/thor_hurricane_35m.yaml --discover

# Run tests
.venv/bin/pytest -v
```

## Three-Layer Data Model

1. **RV-C Protocol Spec** (`specs/rvc_spec.yaml`) — How to decode CAN frames. Shared across all RVs.
2. **RV Profile** (`profiles/*.yaml`) — What's on this specific coach. Maps instances to HA entities.
3. **Entity Handlers** (`rvc2hass/entities/`) — Generic code for each HA entity type.

## Creating a Profile

See `profiles/thor_hurricane_35m.yaml` for a complete example. Use `--discover`
mode to find what DGN instances are active on your bus.

## Deployment

```bash
# Install on the CAN bus Pi
sudo cp -r . /opt/rvc2hass
cd /opt/rvc2hass && python3 -m venv .venv && .venv/bin/pip install .

# Install systemd service
sudo cp systemd/rvc2hass.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now rvc2hass
```

## MQTT Topics

| Topic | Direction | Purpose |
|-------|-----------|---------|
| `rvc2hass/status` | → Broker | LWT: "online"/"offline" |
| `rvc2hass/<type>/<id>/state` | → Broker | State updates |
| `rvc2hass/<type>/<id>/set` | ← Broker | Commands from HA |
| `homeassistant/<type>/rvc_*/config` | → Broker | Discovery (retained) |
