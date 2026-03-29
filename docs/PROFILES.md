# Device Profile Reference

Device profiles are JSON files that map semantic names to MIoT siid/piid/aiid
values for specific device models.

## Generating a Profile

Use the profile generator tool to create a draft from the MIoT spec:

```bash
# Generate profile for a specific model
python tools/generate_profile.py xiaomi.vacuum.d102gl

# Save to the profiles directory
python tools/generate_profile.py xiaomi.vacuum.d102gl -o src/mihome_cloud/profiles/

# List available vacuum models
python tools/generate_profile.py --list vacuum

# List Dreame models
python tools/generate_profile.py --list dreame
```

The generator fetches the device's MIoT specification and creates a draft
with correct siid/piid/aiid mappings. You'll need to fill in:
- `value_maps` — human-readable names for fan speeds, water levels, etc.
- Verify `active_statuses` and `error_statuses` against real device behavior
- Verify `area_divisor` (usually 100, but some models use 10000)
- Remove duplicate consumable entries if any

## Profile Fields

### Required

| Field | Type | Description |
|-------|------|-------------|
| `model` | string | Device model string (e.g. `"xiaomi.vacuum.d102gl"`) |
| `device_type` | string | Device category: `"vacuum"`, `"air_purifier"`, `"light"`, etc. |
| `capabilities` | list | Enabled capability mixins: `"battery"`, `"consumables"`, `"rooms"`, `"station"`, `"fault"` |
| `properties` | object | Map of semantic name → `{"siid": N, "piid": N}` |
| `actions` | object | Map of semantic name → `{"siid": N, "aiid": N}` |

### Optional

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `consumable_properties` | list | `[]` | Property names that represent consumable levels (%) |
| `status_map` | object | `{}` | Maps raw status codes to human-readable strings: `{"2": "charging"}` |
| `value_maps` | object | `{}` | Maps property values to labels: `{"fan_speed": {"1": "silent"}}` |
| `active_statuses` | list | `[]` | Status codes that mean the device is busy |
| `error_statuses` | list | `[5, 15]` | Status codes that mean the device has an error |
| `area_divisor` | number | `100` | Divides raw cleaning_area to get m² |

### Special value_maps Keys

| Key | Used by | Description |
|-----|---------|-------------|
| `charging_true` | BatteryMixin | The charging property value that means "charging" (usually `1`) |
| `sweep_mop_type` | MiHomeVacuum | Maps cleaning mode codes to labels |
| `fan_speed` | full_state() | Maps fan speed codes to labels |
| `water_level` | full_state() | Maps water output codes to labels |

## Standard Property Names

These names are recognized by the mixins and device classes:

### Used by BatteryMixin
- `battery` — Battery level (0-100)
- `charging` — Charging state enum

### Used by ConsumablesMixin
- Any name listed in `consumable_properties`
- Common: `main_brush_life`, `side_brush_life`, `filter_life`, `mop_life`, `dust_bag_life`

### Used by RoomsMixin
- `room_info` — JSON string with `{"rooms": [{"id": N, "name": "..."}]}`

### Used by FaultMixin
- `fault` — Fault code (0 = no fault)
- `status` — Used with `error_statuses` to determine if fault is active
- `cleaning_area` — Used to detect interrupted tasks

### Used by MiHomeVacuum
- `status` — Numeric status code
- `sweep_mop_type` — Current cleaning mode
- `cleaning_area` — Area cleaned (raw, divided by `area_divisor`)
- `cleaning_time` — Time cleaned (seconds)
- `fan_speed` — Suction level
- `water_level` — Mop water output
- `carpet_boost` — Carpet boost enabled

## Standard Action Names

### Used by MiHomeVacuum
- `start_sweep` — Start sweeping
- `start_sweep_only` — Sweep without mop
- `start_mop` — Mop only
- `start_sweep_mop` — Sweep + mop
- `stop` — Stop cleaning
- `pause` — Pause
- `resume` — Resume
- `dock` / `go_charge` — Return to dock
- `locate` — Play sound
- `clean_rooms` — Room-specific cleaning (params: `[[room_ids]]`)

### Used by StationMixin
- `start_mop_wash` — Wash mop at station
- `start_dry` — Dry mop at station
- `start_dust_arrest` — Empty dust bin

## Finding MIoT IDs Manually

If the generator doesn't detect a property/action correctly:

1. Go to [home.miot-spec.com](https://home.miot-spec.com)
2. Search for your device model
3. Browse services → properties/actions
4. Note the siid, piid/aiid values
5. Add them to the profile with the appropriate semantic name
