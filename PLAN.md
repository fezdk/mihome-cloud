# mihome-cloud Device Abstraction Plan

## Goal

Replace magic numbers and model-specific code with a profile-driven, layered
abstraction that works across all MIoT devices — vacuums, air purifiers,
lights, sensors, etc.

## Architecture (4 layers)

```
Layer 4: Profile JSON          ← Model-specific MIoT mappings (no code)
Layer 3: Device Type Classes   ← High-level API per type (MiHomeVacuum, etc.)
Layer 2: Capability Mixins     ← Reusable across types (Battery, Rooms, etc.)
Layer 1: MiHomeDevice          ← Generic property/action access via profile
Layer 0: MiHomeCloud           ← Raw RPC (already exists, unchanged)
```

## File Structure

```
src/mihome_cloud/
  client.py              # Layer 0: MiHomeCloud raw RPC (existing)
  auth.py                # Authentication (existing)
  fault_codes.py         # Fault code lookup (existing)

  device.py              # Layer 1: MiHomeDevice base class
  capabilities.py        # Layer 2: Capability mixins

  devices/
    __init__.py
    vacuum.py            # Layer 3: MiHomeVacuum

  profiles/
    __init__.py           # Profile loader + auto-detection
    xiaomi.vacuum.d102gl.json
```

## Layer 1: MiHomeDevice (base)

Generic device that reads a profile to know its properties and actions.

```python
class MiHomeDevice:
    cloud: MiHomeCloud
    did: str
    model: str
    profile: dict

    def get_property(name) -> Any        # Read by semantic name
    def get_properties(names) -> dict    # Batch read
    def set_property(name, value)        # Write by semantic name
    def run_action(name, params) -> dict # Execute by semantic name
    def has_capability(name) -> bool     # Check capability
    def available_actions -> list[str]
    def available_properties -> list[str]
    def map_value(prop, raw) -> str      # Translate raw → human-readable
```

No MIoT siid/piid/aiid numbers anywhere — all resolved from profile.

## Layer 2: Capability Mixins

Reusable building blocks, each providing a few methods:

- **BatteryMixin**: `battery_level()`, `is_charging()`
- **ConsumablesMixin**: `consumables() -> dict[str, int]`
- **RoomsMixin**: `rooms() -> dict[str, int]`, room name resolution
- **StationMixin**: `wash_mop()`, `dry_mop()`, `empty_bin()`
- **FaultMixin**: `fault() -> str|None`, `has_fault()`, `has_interrupted_task()`

A vacuum uses all of these. An air purifier uses Battery + Consumables.
A light might use none.

## Layer 3: Device Type Classes

Combine base + mixins + type-specific high-level methods:

### MiHomeVacuum
```python
class MiHomeVacuum(MiHomeDevice, BatteryMixin, ConsumablesMixin,
                    RoomsMixin, StationMixin, FaultMixin):
    def status() -> str
    def is_busy() -> bool
    def start()
    def stop()
    def pause()
    def resume()
    def dock()
    def locate()
    def clean_rooms(room_names: list[str])
    def full_state() -> dict      # Everything for a poll
```

### Future: MiHomeAirPurifier, MiHomeLight, etc.

## Layer 4: Profile JSON

All model-specific knowledge in one file:

```json
{
  "model": "xiaomi.vacuum.d102gl",
  "device_type": "vacuum",
  "capabilities": ["battery", "consumables", "rooms", "mop", "station", "fault"],
  "properties": { ... siid/piid mappings ... },
  "actions": { ... siid/aiid mappings ... },
  "consumable_properties": ["main_brush_life", ...],
  "status_map": { "1": "idle", "2": "charging", ... },
  "value_maps": { "fan_speed": {"1": "silent", ...} },
  "active_statuses": [4, 7, 12, 14, 16, 17],
  "area_divisor": 100
}
```

### Profile loading
- Auto-detect from `model` string returned by `get_devices()`
- Fall back to generic profile if no exact match
- Users can provide custom profiles in their config

## What changes for consumers

### Before (raw)
```python
cloud.get_properties(did, [(2, 2), (3, 1)])
cloud.action(did, siid=2, aiid=16, params=[[4]])
```

### After (abstracted)
```python
vacuum = MiHomeVacuum.from_cloud(cloud, did="1173085625")
print(vacuum.status())        # "charging"
print(vacuum.battery_level())  # 100
vacuum.clean_rooms(["kitchen", "living-room"])
```

## What stays the same

- MiHomeCloud (Layer 0) — unchanged, still available for raw access
- Authentication (auth.py) — unchanged
- fault_codes.py — unchanged, used by FaultMixin

## Implementation order

1. Write `device.py` (MiHomeDevice base)
2. Write `capabilities.py` (all mixins)
3. Write `devices/vacuum.py` (MiHomeVacuum)
4. Write `profiles/__init__.py` (loader)
5. Create `profiles/xiaomi.vacuum.d102gl.json`
6. Update `__init__.py` exports
7. Update README with new API
8. Test with mutti's vacuum
9. Convert mutti's xiaomi-vacuum connector to use MiHomeVacuum
