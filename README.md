# mihome-cloud

Control Xiaomi MIoT smart home devices via the Xiaomi cloud API.

Provides both a **high-level device API** (profile-driven, no magic numbers)
and **low-level raw access** for any MIoT device — vacuums, air purifiers,
lights, sensors, etc.

## Installation

```bash
pip install git+https://github.com/fezdk/mihome-cloud.git
```

Or clone and install locally:

```bash
git clone https://github.com/fezdk/mihome-cloud.git
cd mihome-cloud
pip install -e .
```

Dependencies: `requests` + `pycryptodome`.

## Setup

### 1. Authenticate

Xiaomi requires SSO authentication, which may involve CAPTCHA and/or 2FA.
Run the interactive helper once to create `auth_state.json`:

```python
from mihome_cloud.auth import interactive_login

state = interactive_login(
    username="your-email@example.com",
    password="your-password",
    country="de",
    save_to="auth_state.json",
)
```

This handles CAPTCHA, 2FA email codes, and token extraction. You only need
to do this once — the saved tokens auto-refresh.

### 2. Use the Library

```python
import json
from mihome_cloud import MiHomeCloud, MiHomeVacuum

# Load saved auth
cloud = MiHomeCloud("user@example.com", "password", country="de")
cloud.restore_auth_state(json.load(open("auth_state.json")))

# Find your devices
for d in cloud.get_devices():
    print(f"{d['did']}: {d['name']} ({d['model']})")

# Control your vacuum
vacuum = MiHomeVacuum.from_cloud(cloud, did="1173085625")
print(vacuum.status())           # "charging"
print(vacuum.battery_level())    # 100
print(vacuum.rooms())            # {"Kitchen": 4, "Living room": 3, ...}
vacuum.clean_rooms(["kitchen"])
```

## Authentication Details

### Notes
- Xiaomi rate-limits 2FA to 3-5 requests per day — don't retry excessively
- Tokens are saved immediately after auth, before device listing
- If device listing fails but auth succeeded, the tokens are still valid
- Tokens auto-refresh on expiry; you shouldn't need to re-authenticate

### Restoring a Session

```python
import json
from mihome_cloud import MiHomeCloud

cloud = MiHomeCloud("user@example.com", "password", country="de")
with open("auth_state.json") as f:
    cloud.restore_auth_state(json.load(f))
# No login() needed — token auto-refreshes on expiry
```

### Server Regions

| Region | Code |
|--------|------|
| China | `cn` |
| Germany / EU | `de` |
| United States | `us` |
| Singapore | `sg` |
| India | `in` |
| Russia | `ru` |

## Vacuum Control

The `MiHomeVacuum` class provides a clean API for robot vacuums. All
MIoT-specific details are resolved from a device profile — no magic numbers.

### Setup

```python
from mihome_cloud import MiHomeCloud, MiHomeVacuum

cloud = MiHomeCloud(...)
cloud.restore_auth_state(...)

# Auto-detects model and loads the right profile
vacuum = MiHomeVacuum.from_cloud(cloud, did="1173085625")
```

### Status & Sensors

```python
vacuum.status()           # "charging", "sweeping_mopping", "paused", etc.
vacuum.status_code()      # Raw numeric code
vacuum.battery_level()    # 0-100
vacuum.is_charging()      # True/False
vacuum.is_busy()          # True if actively cleaning
vacuum.fault()            # "drive_wheel_error" or None
vacuum.has_fault()        # True/False
```

### Cleaning

```python
vacuum.start()                          # Start sweep + mop
vacuum.start_sweep()                    # Sweep only (no mop)
vacuum.start_mop()                      # Mop only
vacuum.clean_rooms(["kitchen", "bedroom"])  # Clean specific rooms by name
vacuum.pause()
vacuum.resume()
vacuum.stop()
vacuum.dock()                           # Return to base
vacuum.locate()                         # Play sound to find it
```

Room names are resolved from the vacuum's map — use the names you see
in your Mi Home app. Partial and case-insensitive matching is supported.

### Rooms

```python
vacuum.rooms()
# {"Living room": 3, "Kitchen": 4, "Bryggers": 5, "Stue gang": 6, "Eddies": 7}
```

### Consumables

```python
vacuum.consumables()
# {"main_brush_life": 77, "side_brush_life": 66, "filter_life": 54,
#  "mop_life": 47, "dust_bag_life": 100}
```

### Station Control

```python
vacuum.wash_mop()       # Wash mop pads at station
vacuum.dry_mop()        # Dry mop pads
vacuum.empty_bin()      # Empty dust bin
```

### Pre-Command Safety Check

```python
warning = vacuum.check_before_command()
if warning:
    print(warning)
    # "Vacuum has an interrupted task (59m² done) with active fault:
    #  drive_wheel_error. Send 'resume' to continue or 'stop' first."
else:
    vacuum.clean_rooms(["kitchen"])
```

### Full State (for polling/dashboards)

```python
state = vacuum.full_state()
# Returns a flat dict with all status, consumables, rooms, faults:
# {"status": "charging", "battery": 100, "charging": True,
#  "rooms/kitchen": 4, "consumables/filter_life": 54, ...}
```

### Fault Codes

```python
from mihome_cloud import lookup_fault

lookup_fault("xiaomi.vacuum.d102gl", 320004)  # "drive_wheel_error"
lookup_fault("dreame.vacuum.r2205", 15)       # "left_wheel_motor"
```

## Device Profiles

The library uses JSON profiles to map semantic names to MIoT IDs.
Profiles are auto-loaded by model string.

### Supported Models

| Model | Device |
|-------|--------|
| `xiaomi.vacuum.d102gl` | Xiaomi Robot Vacuum X20 Pro |

### Adding a New Model

Create a JSON file in `src/mihome_cloud/profiles/`:

```json
{
  "model": "your.device.model",
  "device_type": "vacuum",
  "capabilities": ["battery", "consumables", "rooms", "station", "fault"],
  "properties": {
    "status":  {"siid": 2, "piid": 2},
    "battery": {"siid": 3, "piid": 1},
    ...
  },
  "actions": {
    "start_sweep_mop": {"siid": 2, "aiid": 6},
    "stop":            {"siid": 2, "aiid": 2},
    ...
  },
  "status_map": {"1": "idle", "2": "charging", ...},
  "value_maps": {"fan_speed": {"1": "silent", "2": "basic", ...}},
  "active_statuses": [4, 7, 12, 14, 16, 17]
}
```

Find your device's MIoT IDs at [home.miot-spec.com](https://home.miot-spec.com).

## Low-Level Access

For devices without a profile or device class, use the raw cloud client:

### Get Properties

```python
# Properties are identified by (service_id, property_id) pairs
props = cloud.get_properties(device_id, [(3, 1), (2, 2)])
print(f"Battery: {props[(3, 1)]}%")
```

### Set a Property

```python
cloud.set_property(device_id, siid=2, piid=9, value=2)
```

### Execute an Action

```python
cloud.action(device_id, siid=2, aiid=1)              # Start cleaning
cloud.action(device_id, siid=2, aiid=16, params=[[4]])  # Clean room 4
```

### List Devices

```python
for d in cloud.get_devices():
    print(f"{d['did']}: {d['name']} ({d['model']})")
```

## Architecture

```
MiHomeCloud          — Raw RPC (siid/piid/aiid)
  ↓
MiHomeDevice         — Profile-driven property/action access by name
  ↓
Capability Mixins    — Battery, Consumables, Rooms, Station, Fault
  ↓
MiHomeVacuum         — High-level vacuum API (start, stop, clean_rooms)
  ↓
Device Profile JSON  — Model-specific MIoT mappings (no code changes)
```

## Troubleshooting

### CAPTCHA on every login
Persist auth state including `client_id`. The `interactive_login` helper does this automatically.

### 2FA rate limited
3-5 attempts per day. Once you have `auth_state.json`, you won't need 2FA again.

### "auth error" or "invalid signature"
Ensure `ssecurity` and `serviceToken` are from the same login session. Use `interactive_login` — it handles the multi-step redirect chain correctly.

### No profile for my device
Use the low-level `cloud.get_properties()` / `cloud.action()` API directly.
To add a profile, find your device's MIoT spec at [home.miot-spec.com](https://home.miot-spec.com).

## Credits

Cloud protocol extracted from [Tasshack/dreame-vacuum](https://github.com/Tasshack/dreame-vacuum).

## License

MIT
