# Implementation status and architecture

The original device-abstraction plan has been implemented. This file now records
current boundaries; use the [README](README.md) for runnable examples and the
[profile reference](docs/PROFILES.md) for extending property/action support.

## Current components

| Component | Responsibility |
| --- | --- |
| `client.py` / `MiHomeCloud` | Xiaomi SSO/session reuse and RC4 cloud RPC; device discovery and raw properties/actions. |
| `auth.py` | Interactive CAPTCHA/2FA flow and private saved-session persistence. |
| `device.py` / `MiHomeDevice` | Semantic property/action access, available names and capability declarations. |
| `capabilities.py` | Battery, consumables, named rooms, station actions and fault helpers. |
| `devices/vacuum.py` / `MiHomeVacuum` | Vacuum commands, status, normalized polling state and an opt-in map client. |
| `profiles/` | Model-specific property/action IDs, status labels, value maps and scaling. |
| `maps.py` / `map_api.py` | Verified X20 Pro map decoder and cached JSON-ready snapshots. |
| `map_view.py` / `resources/map_view.html` | Private viewer bundle and Canvas map with room labels, positions and route. |
| `tools/` | Draft profile generation, one-shot map export and offline viewer generation. |

The bundled device class/profile covers **Xiaomi Robot Vacuum X20 Pro
(`xiaomi.vacuum.d102gl`)**. Other cloud-accessible MIoT devices can use raw RPC
or `MiHomeDevice` with a custom profile; dedicated air-purifier/light classes
are not implemented. Capability declarations do not dynamically attach mixins.

## Discovery and profiles

- `cloud.get_devices()` supplies device IDs, names and model strings.
- `MiHomeVacuum.from_cloud(cloud, did=...)` discovers the model when omitted.
- `load_profile()` tries the exact model, then existing prefix profile files.
  It raises `FileNotFoundError` if none exists; there is no universal fallback.
- Pass a profile dict explicitly with `from_cloud(..., profile=profile)` or the
  device constructor. There is no automatic user-config directory lookup.
- `tools/generate_profile.py` fetches the MIoT specification and generates a
  draft. Semantic names, status classifications, scaling and value maps need
  review before use. A new profile does not implement a new map protocol.

## Map support and remaining work

Active/saved map downloads, PNG/JSON export, raster-derived room boundaries,
name markers, robot/dock positions and the latest recorded route are implemented.
See the [complete room-and-route example](docs/map-examples.md) and
[snapshot contract](docs/map-api.md).

Normal `full_state()` polling does not download maps. Applications explicitly
refresh one shared `vacuum.maps` client and publish its output to their viewers.
The viewer polls local JSON; it never contacts Xiaomi.

Still unverified or unimplemented:

- Position and route changes during active cleaning, cloud upload latency and
  the suitability of five-second sampling. Measure during a user-started run.
- Historical-route downloads and automatic completion-time archiving.
- Raw yaw interpretation, dock coordinate anchor and semantic wall/furniture
  separation. Raster room contours retain their cell-scale steps.
- Map decoders for models other than `xiaomi.vacuum.d102gl`.
- Map integration into Mutti. This repository provides the reusable client and
  viewer; it does not deploy or configure consuming applications.
