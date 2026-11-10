# mihome-cloud

Control Xiaomi MIoT smart home devices via the Xiaomi cloud API.

Provides both a **high-level device API** (profile-driven, no magic numbers)
and **low-level raw access** for cloud-accessible MIoT devices. The bundled
high-level device class and verified profile currently cover the X20 Pro vacuum;
other device types can use raw RPC or caller-supplied profiles.

Includes verified **Xiaomi Robot Vacuum X20 Pro (`xiaomi.vacuum.d102gl`) map
export**: floor plans as PNG/JSON, room geometry and name markers, robot/dock
positions and recorded cleaning routes. See the [map guide](#x20-pro-maps-room-labels-and-routes)
for setup, the local viewer and current live-data limitations.

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

This handles CAPTCHA, 2FA email codes, and token extraction. Save the returned
state in a private file (mode `0600`); it contains credentials equivalent to a
logged-in Xiaomi account session. Xiaomi may still require a new interactive
login later.

### 2. Use the Library

```python
import json
from mihome_cloud import MiHomeCloud, MiHomeVacuum

# Reuse saved auth; no password is needed while the session works.
cloud = MiHomeCloud("", "", country="de")
with open("auth_state.json") as f:
    cloud.restore_auth_state(json.load(f))

# Discover device IDs, names and model codes from the cloud.
devices = cloud.get_devices()
for d in devices:
    print(f"{d['did']}: {d['name']} ({d['model']})")

# Select the X20 Pro; if there are several, select a DID from devices above.
matches = [d for d in devices if d.get("model") == "xiaomi.vacuum.d102gl"]
if len(matches) != 1:
    raise ValueError("Select one vacuum from the discovered device list")
device = matches[0]
vacuum = MiHomeVacuum.from_cloud(cloud, did=device["did"], model=device["model"])
print(vacuum.status())           # "charging"
print(vacuum.battery_level())    # 100
print(vacuum.rooms())            # Available named rooms: {name: id}
cloud.close()
```

## Authentication Details

### Notes

- Xiaomi can rate-limit verification attempts; no fixed daily quota is assumed.
- The state includes `pass_token` and `session_refreshed_at` after a new login.
  Older four-field state files still load, but cannot use account-session renewal.
- Calling `refresh_if_due()` renews an eligible session after 30 days by
  default; there is no background renewal timer. A failed attempt backs off
  for one hour. The existing service session is retained if renewal fails.
- On HTTP 401 or `SERVICETOKEN_EXPIRED`, regular cloud requests try account-session
  renewal when a `pass_token` exists; otherwise they attempt `login()` using the
  configured username/password. Failed renewal does not fall back to a password
  login. A rejected retry or a required CAPTCHA/2FA needs caller intervention.
  Map requests disable automatic reauthentication.
- Renewal changes the in-memory state. Persist `cloud.get_auth_state()` privately
  after renewal if the replacement session should survive a process restart.
- Renewal is not guaranteed forever: Xiaomi can invalidate the account session
  or require CAPTCHA/2FA. Never print or commit the saved state.

### Restoring a Session

```python
import json
from mihome_cloud import MiHomeCloud

cloud = MiHomeCloud("", "", country="de")
with open("auth_state.json") as f:
    cloud.restore_auth_state(json.load(f))
# No login() needed while the account session remains valid.
```

### Server Regions

Set `country` to the region where the devices are registered. It is caller
configuration: saved auth state does not contain the region, and the client does
not search regions automatically. `get_devices()` lists devices in the selected
region; their `did`, `name` and `model` need no manual lookup.

| Region | Code |
|--------|------|
| China | `cn` |
| Germany / EU | `de` |
| United States | `us` |
| Singapore | `sg` |
| India | `in` |
| Russia | `ru` |

## Vacuum Control

The `MiHomeVacuum` class provides a high-level API for robot vacuums.
Property/action IDs are resolved from a device profile. X20 Pro map decoding
uses a separate model-specific implementation, exposed through `vacuum.maps`.

### Setup

```python
from mihome_cloud import MiHomeCloud, MiHomeVacuum

cloud = MiHomeCloud(...)
cloud.restore_auth_state(...)

# Auto-detects model and loads the right profile
vacuum = MiHomeVacuum.from_cloud(cloud, did="1234567890")
```

### Status & Sensors

```python
vacuum.status()           # "charging", "sweeping_mopping", "paused", etc.
vacuum.status_code()      # Raw numeric code
vacuum.battery_level()    # 0-100
vacuum.is_charging()      # True/False
vacuum.is_busy()          # Profile busy states, including washing/station work
vacuum.fault()            # "drive_wheel_error" or None
vacuum.has_fault()        # Nonzero raw code; can be residual after recovery
vacuum.has_active_fault() # Nonzero code plus an error-capable device status
```

### Cleaning

```python
vacuum.start()                          # Sweep + mop, or best available action
vacuum.start_sweep()                    # Sweep only (no mop)
vacuum.start_mop()                      # Mop only
vacuum.clean_rooms(["kitchen", "bedroom"])  # Clean specific rooms by name
vacuum.pause()
vacuum.resume()
vacuum.stop()
vacuum.dock()                           # Return to base
vacuum.locate()                         # Play sound to find it
```

Read the available names and IDs with `vacuum.rooms()` before selecting rooms.
Name matching is case-insensitive and accepts spaces/hyphens and substrings.
Prefer full names or IDs: a partial match selects the first match and does not
reject ambiguity. Numeric IDs are passed through without validation.

### Rooms

```python
rooms = vacuum.rooms()
# Example result: {"Living room": 3, "Kitchen": 4, "Bedroom": 5}

# Inspect the full property, including unnamed rooms and map_uid.
import json
raw = vacuum.get_property("room_info")
room_info = json.loads(raw) if isinstance(raw, str) else (raw or {})
room_entries = room_info.get("rooms", [])  # [{"id": ..., "name": ...}, ...]
```

`rooms()` reads the `room_info` property and includes only named rooms; duplicate
names collapse to one dict entry. It does not download a map or synthesize names.
An empty dict therefore does not prove the robot has no rooms. Use the raw list
above for all reported IDs, or `vacuum.maps.get_snapshot().to_dict()["rooms"]`
for X20 Pro geometry, names and display-label fallbacks.

For X20 Pro room starts, use **0.4.2 or later**. The direct device RPC requires
MIoT-tagged inputs: action 2/16 receives `[{"piid": 15, "value": "4,6"}]`.
Both `clean_rooms()` and `cleaning.start()` encode this automatically. Earlier
versions sent nested arrays (0.4.0) or an untagged CSV string (0.4.1), which can
receive a successful acknowledgement without starting the robot. This wire
format follows the [X20 Pro protocol investigation](https://github.com/AldenDana/ha-xiaomi-vacuum-x20pro/blob/master/docs/METHOD.md)
and MIoT input property 2/15. An acknowledgement is still not proof of movement;
check subsequent robot status. Never automatically retry an ambiguous start.
The corrected tagged format has synthetic wire-contract coverage; physical
execution on our test robot remains to be confirmed.

`clean_rooms()` also accepts integer IDs from the current room configuration,
for example `vacuum.clean_rooms([4])`. IDs belong to a floor: do not send IDs
from another saved floor, and do not treat a display fallback such as `Room 4`
as a resolvable room name. See the [room-and-route example](docs/map-examples.md)
for a complete read-only export and drawing.

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
# Returns available profile properties, including status and named rooms:
# {"status": "charging", "battery": 100, "charging": True,
#  "rooms/kitchen": 4, "consumables/filter_life": 54, ...}
```

`full_state()` batches the profile properties and normalizes available values;
it does not include map geometry, positions or routes. Fetch those explicitly
through `vacuum.maps`. `fault_code_raw` can retain a previous fault; use
`fault_active` to distinguish an active fault from residual telemetry.

### Fault Codes

```python
from mihome_cloud import lookup_fault

lookup_fault("xiaomi.vacuum.d102gl", 320004)  # "drive_wheel_error"
lookup_fault("dreame.vacuum.r2205", 15)       # "left_wheel_motor"
```

## X20 Pro maps, room labels and routes

`xiaomi.vacuum.d102gl` (Xiaomi Robot Vacuum X20 Pro) supports read-only map
snapshots through the existing MiHome cloud session. The implementation has been
verified against real device downloads and does not depend on another vacuum
integration. Its runtime dependencies remain `requests` and `pycryptodome`.

| Data | Available through the map API |
| --- | --- |
| Maps and floors | Active map, saved-map inventory and explicit saved-map downloads. |
| Floor plan | PNG raster, room boundaries and native coordinates in millimetres. |
| Room markers | Names, IDs and label positions; unnamed rooms get a display fallback. |
| Robot and dock | Positions from the downloaded map, with availability and freshness metadata. |
| Route | Original points and separate transport/cleaning runs, retaining raw `type` values. |
| Freshness | Fetch time, cache age, content revisions and stale/error flags. |

These are **cloud snapshots**. Changing robot positions and the active route were
verified during a user-started X20 Pro cleaning, including updates after the
official app was closed. Use a ten-second refresh interval for a dashboard.
Exact measurement age and device-to-cloud latency remain unknown.
Fetching a snapshot does not start cleaning, switch floors or request a new map
upload. The map API never starts a background poller or attempts a new login.

### Model notes: Xiaomi Robot Vacuum X20 Pro

The findings below were verified on the maintainer's **Xiaomi Robot Vacuum X20
Pro, model `xiaomi.vacuum.d102gl`**. They establish support for this tested device;
they do not automatically establish support for every Xiaomi/Dreame model or
firmware version. No firmware modification was required.

- **Map access works.** The active floor plan and multiple saved maps were
  downloaded, decrypted and exported. The model uses a Xiaomi JSON-v2 map
  envelope; do not route it through a Dreame map parser merely because the
  library's cloud transport was originally based on Dreame-project research.
- **Use the `_pro` URL endpoint.** `/v2/home/get_interim_file_url_pro` returned
  usable map downloads with the existing session. The non-`_pro` variant returned
  code `-6` on the tested account.
- **Room metadata is split across sources.** MIoT `room_info` (SIID 2, PIID 16)
  has room IDs/names and `map_uid`, but no geometry. The map file supplies
  `grid_id` → `room_id`, room attributes and label positions. Room IDs matched
  the cleaning API; some room names were empty, so a room-ID fallback is needed.
- **Do not assume all map identifiers agree.** `current_map_id` (10/6) was `0`;
  `room_info.map_uid` did not match saved-map IDs. The downloaded file's `map_id`
  matched a saved-map entry marked `is_current`. The API uses the file's identity
  and verifies explicit saved-floor requests against it.
- **Positions and a recorded route are available.** The map file contains robot
  and dock coordinates plus `paths.points`. Observed `type=0` runs look like
  transport; `type=1` runs form the cleaning lanes. These are observed meanings,
  not a verified manufacturer enum. Breaking the line at every zero incorrectly
  turns transport runs into isolated points.
- **Geometry uses a 50 mm grid in the tested files.** The viewer preserves raw
  route coordinates and uses antialiasing, without smoothing. Robot diameter is
  350 mm; the manufacturer's dock footprint is 340 × 420 mm. Raw yaw units and
  the dock's exact coordinate anchor still need verification.
- **Timestamps and history have limits.** List `index` values resemble Unix
  timestamps but were not confirmed as map creation/change times. `clean-record`
  (10/3) returned cleaning summaries; access to older route files remains
  unverified. The latest recorded route is available for local snapshot export.
- **Active routes and positions are verified.** Read-only sampling during a
  user-started cleaning observed changing positions and routes, including after
  closing Xiaomi Home. Replace the whole route on each update: earlier endpoints
  can be revised. A ten-second client interval is suitable for the tested run;
  it is not a guaranteed upload cadence or latency bound.

The [investigation notes](docs/x20-pro-maps.md) document endpoints, the decode
chain and the evidence behind these model-specific decisions. No private map
files, room names, account identifiers or session credentials are included.


### Fetch a snapshot using a saved session

Use a DID and model returned by `cloud.get_devices()` (the example DID is
synthetic), and the same configured `country` as your working cloud connection.
The [complete room-and-route example](docs/map-examples.md) discovers the X20 Pro
automatically when there is exactly one matching device:

```python
import json
from pathlib import Path
from mihome_cloud import MiHomeCloud, MiHomeVacuum
from mihome_cloud.map_view import write_map_view

with MiHomeCloud("", "", country="de") as cloud:
    cloud.restore_auth_state(json.loads(Path("auth_state.json").read_text()))
    vacuum = MiHomeVacuum.from_cloud(
        cloud, did="1234567890", model="xiaomi.vacuum.d102gl"
    )

    maps = vacuum.maps                  # Reuses one client; no request yet
    floors = maps.list_maps()           # MapInfo: map_id, name, is_current
    snapshot = maps.get_snapshot()      # Active map plus available overlays
    payload = snapshot.to_dict()        # JSON-ready, private home-layout data
    png = snapshot.png()                # Static raster; overlays are separate

    positions = maps.get_positions()   # robot, dock, map_id, freshness
    route = maps.get_route()           # route, task_id, map_id, freshness

    Path("private-maps").mkdir(mode=0o700, exist_ok=True)
    write_map_view(snapshot, "private-maps/view")
```

Consecutive active getters share a five-second cache. Keep the same client per
device across consumers. `get_snapshot(map_id=...)` fetches a saved floor without
changing the active floor; wait for the shared refresh interval before fetching
a different uncached map. Saved files may omit robot position and route, so
check their `available` flags. An expired session raises an error or returns an
explicitly stale cached snapshot; restore a valid session through your existing
authentication workflow.

`payload["rooms"]` includes each room's `room_id`, `name`, `display_name`,
`label` position and boundary rings. Vendor label coordinates are used when
inside the room, otherwise an interior raster cell is selected. Names can be
empty even when the map contains room geometry. Optional overrides are scoped
to both map and room to avoid mixing floors:

```python
from mihome_cloud import VacuumMapClient

# Synthetic map/room IDs; use your own IDs and an already restored cloud client.
maps = VacuumMapClient(
    cloud, device_id,
    min_refresh_interval=5,
    room_names={7: {11: "Kitchen", 12: "Living room"}},
)
```

### Export PNG and JSON from the command line

From a checkout installed with `pip install -e .`:

```sh
mkdir -m 700 -p private-maps
python tools/export_x20_map.py \
  --auth-state auth_state.json \
  --country de \
  --output private-maps/export-01
```

The exporter discovers exactly one X20 Pro. Supply `--device-id` if you have
multiple matching devices. Add `--all-maps` to also download reported saved
floors; no map switch is performed. Each run needs a new output directory.

Output includes `active.raw`, decoded `active.json`, `active-geometry.json`,
`active.png`, private metadata and a manifest. The PNG is the static floor plan;
room labels, positions and routes are drawn by the browser viewer below.

### View room names, positions and routes in a browser

The Python example above already creates a viewer bundle. Alternatively, build
one **offline** from an exported JSON file:

```sh
python tools/preview_x20_map.py \
  --input private-maps/export-01/active.json \
  --output private-maps/view
python -m http.server 8938 --bind 127.0.0.1 --directory private-maps/view
```

Open [the local viewer](http://127.0.0.1:8938/). It uses Canvas to draw room labels,
the robot/dock and original route coordinates with antialiasing, without smoothing
or point markers. Cleaning is solid; optional transport is dashed. These route
categories reflect observations on X20 Pro; raw numeric types remain available.
The robot is drawn at its 350 mm diameter; the dock is symbolic because its
coordinate anchor and rotation are not yet verified.

The viewer checks its **local** `snapshot.json` every five seconds. It does not
contact Xiaomi. To update it, a backend must fetch a new snapshot through the
same map client and call `write_map_view()` again. The helper atomically publishes
JSON and hash-named rasters; the browser reuses an unchanged map image and keeps
the previous view if loading fails. No CDN, npm build or extra runtime dependency
is required. Stop the local server with Ctrl+C.

### Refresh behavior and limits

- Five seconds is the default minimum between new snapshot fetches, not a
  guarantee of fresh measurements from Xiaomi. One active refresh normally
  performs a property batch, a signed-URL request and a file download.
- Repeated getters use cached data. Refresh failures back off and retain the
  previous snapshot with `stale=true`; use `allow_stale=False` to raise instead.
- `fetched_at` is download time. The robot's measurement time is unknown;
  `source_updated_at` is null. `live_updates_verified=true` records model-level
  testing, not proof that an individual snapshot is current.
- The newest route can belong to the last completed cleaning. Historical route
  downloads and automatic end-of-task archiving are not implemented.
- For a dashboard, keep Xiaomi access on the backend and serve snapshots/images
  through authenticated endpoints. Stop refreshing when the view is unused and
  use a slower cadence while idle. `full_state()` polling remains unchanged.

Exports contain private home layouts and must stay out of Git and logs. The
helpers create private directories/files (0700/0600); `private-maps/` is ignored.
The local demo binds only to loopback and never receives Xiaomi credentials.

See the [full API and snapshot contract](docs/map-api.md) and the
[protocol findings and model limitations](docs/x20-pro-maps.md).


## Device Profiles

The library uses JSON profiles to map semantic names to MIoT IDs.
Profiles are auto-loaded by model string.

### Supported Models

| Model | Device |
|-------|--------|
| `xiaomi.vacuum.d102gl` | Xiaomi Robot Vacuum X20 Pro |

### Adding a New Model

Create a reviewed JSON file in `src/mihome_cloud/profiles/`. This abbreviated
shape is illustrative; its IDs and declared capabilities must match the device:

```json
{
  "model": "your.device.model",
  "device_type": "vacuum",
  "capabilities": ["battery", "consumables", "rooms", "station", "fault"],
  "properties": {
    "status":  {"siid": 2, "piid": 2},
    "battery": {"siid": 3, "piid": 1}
  },
  "actions": {
    "start_sweep_mop": {"siid": 2, "aiid": 6},
    "stop":            {"siid": 2, "aiid": 2}
  },
  "status_map": {"1": "idle", "2": "charging"},
  "value_maps": {"fan_speed": {"1": "silent", "2": "basic"}},
  "active_statuses": [4, 7, 12, 14, 16, 17]
}
```

The [profile generator](docs/PROFILES.md#generating-a-profile) can fetch the MIoT
specification using the model returned by `cloud.get_devices()`. Review its draft
before use. See the [profile reference](docs/PROFILES.md) for loading a custom
profile and checking available properties/actions. A profile alone does not add
a map decoder for another model.

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
MiHomeVacuum         — High-level vacuum API, backed by Device Profile JSON
  └─ .maps           — Opt-in X20 Pro snapshots (VacuumMapClient)
                       Xiaomi map decoder → JSON/PNG → local Canvas viewer
```

## Troubleshooting

### CAPTCHA on every login
Persist the state returned by `interactive_login`, including `client_id`. Pass
`save_to="auth_state.json"` to save it atomically with private permissions. Reuse
that state instead of logging in on every run; Xiaomi may still request CAPTCHA.

### 2FA rate limited
Avoid repeated login attempts. Reuse `auth_state.json` while it remains valid;
Xiaomi may still require interactive authorization after the session expires.

### "auth error" or "invalid signature"
Ensure `ssecurity` and `serviceToken` are from the same login session. Use `interactive_login` — it handles the multi-step redirect chain correctly.

### No profile for my device
Use the low-level `cloud.get_properties()` / `cloud.action()` API directly.
Use `tools/generate_profile.py` with the discovered model to create a draft;
see [Device Profile Reference](docs/PROFILES.md). Profile loading does not
automatically generate a profile for unknown models.

## Credits

Cloud transport is based on [Tasshack/dreame-vacuum](https://github.com/Tasshack/dreame-vacuum)
research; authentication is adapted from
[PiotrMachowski/Xiaomi-cloud-tokens-extractor](https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor).
The independent X20 Pro decoder uses the documented Xiaomi JSON protocol; see
[map protocol references](docs/x20-pro-maps.md#references-and-evidence-boundaries).
These projects are references, not runtime dependencies.

## License

MIT

## X20 Pro cleaning plans

`vacuum.cleaning` reuses the existing MiHome client and session. It reads available
settings, applies an explicit plan with readback, and exposes pause/resume/stop/dock.
The map reader stays read-only. See the [cleaning API guide](docs/cleaning-api.md)
for examples, property mappings, persistent settings and uncertain command outcomes.
The new four-mode plan flow is tested with mocked cloud transport; it has not yet
been exercised as a physical start for every mode.
