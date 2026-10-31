# Map snapshots and local Canvas viewer

The opt-in `VacuumMapClient` exposes the verified Xiaomi X20 Pro map format as
JSON-ready snapshots. It supports **xiaomi.vacuum.d102gl only**. It does not start
cleaning, switch floors, request map uploads, log in or poll in the background.

Map download, saved floors, room IDs, label positions, robot/dock coordinates and
the most recent recorded route have been verified on actual stored device data.
**Position and route updates while cleaning, their latency and a five-second
cloud refresh rate are not yet verified.** Those measurements must wait for a
cleaning session started by the user. No cleaning was started during development.

## Public API

```python
from mihome_cloud import MiHomeCloud, MiHomeVacuum

cloud = MiHomeCloud("", "", country="de")
cloud.restore_auth_state(existing_private_session)
vacuum = MiHomeVacuum.from_cloud(
    cloud, did=device_id, model="xiaomi.vacuum.d102gl"
)

maps = vacuum.maps                  # Shared client; no network call yet
floors = maps.list_maps()           # List[MapInfo]: map_id, name, is_current
snapshot = maps.get_snapshot()     # Current downloaded map, position and route
payload = snapshot.to_dict()       # JSON-serializable; PRIVATE home layout
png = snapshot.png()               # Native-size static raster PNG

positions = maps.get_positions()   # robot, dock, map_id and freshness
route = maps.get_route()           # route, task_id, map_id and freshness
```

Those consecutive active getters share the same five-second cache; they do not
each trigger a cloud download. Keep ONE client per device, shared by browser
sessions and background consumers. `vacuum.maps` reuses its client. Calls are
synchronous; an async application should run them in a worker thread.

`get_snapshot(map_id=...)` downloads a reported saved floor without switching the
robot. Check `route.available` and `robot.available`; the tested saved-floor
files contain dock coordinates but do not contain current robot positions/routes.
If requesting a different floor immediately after another download, the shared
rate guard can raise `MapError`; callers should wait rather than create a new
client to bypass it. The saved file's embedded ID must match the selected ID.

For custom refresh settings or map-scoped names:

```python
from mihome_cloud import VacuumMapClient

maps = VacuumMapClient(
    cloud, device_id,
    min_refresh_interval=5,         # >=5; a local guard, not Xiaomi's SLA
    metadata_ttl=60,
    room_names={7: {11: "Kitchen"}}, # Synthetic IDs: map ID -> room ID -> name
)
```

The active snapshot refresh re-reads metadata and downloads the map again even
if its object name is unchanged. A cloud slot can hold changing content under
the same name. A permitted active refresh normally requires one property batch,
one signed-URL request and one HTTPS download. Five seconds is therefore not
"one cheap request per five seconds"; its suitability needs to be measured.
Use a slower cadence while idle, and stop refreshing when no view needs it.

## Snapshot contract: `mihome-map-snapshot-v1`

| Field | Meaning |
| --- | --- |
| `map` | ID/name, raster size, origin in mm, mm/cell, coordinate conventions and revisions. |
| `rooms[]` | Raw name, display fallback, room/grid IDs, room polygons and `label.{x,y,source}`. |
| `robot` | Availability, position, raw yaw and 350 mm circular footprint metadata. |
| `dock` | Availability, position, raw yaw and 340 × 420 mm manufacturer footprint; the user's approximate 400 mm depth is preserved separately. |
| `route` | Availability, raw point types, pose ID and display segments grouped by consecutive type. |
| `task_id` | Raw task ID from the same map file; not proof that a task is currently running. |
| `status_code` | MIoT 2/2 from metadata when fetching the active snapshot; sampled separately from the file. |
| `freshness` | Fetch/serve time, local cache age, change observation, stale/error flags and explicit live-verification status. |
| `identity` | Whether the file matches saved-map metadata; never derives floor ID from `room_info.map_uid`. |

Room names come from `room_attrs.room_name`, an explicitly matching `room_info`,
or a map-scoped caller override. Empty names remain empty in `name`; the viewer
displays **Rum ID**. Vendor label coordinates are used when inside the room;
otherwise an actual interior raster cell nearest the room's cell centroid is
selected. This avoids placing labels in holes or outside concave rooms.

Tested files included empty room names, valid vendor label coordinates and
interior-cell fallbacks. Saved floors also included named rooms. No names are
invented from furniture or layout.

Positions and routes are from the **same downloaded file**, not a merge of
possibly unrelated floor snapshots. MIoT 10/4 was empty during investigation,
so there is no verified lightweight live-position endpoint yet. `yaw_raw` is
retained; its units and the dock's coordinate anchor are not verified. The viewer
draws a 350 mm robot circle and a symbolic dock marker, without inventing rotation.

Routes use the observed interpretation `0=transport`, `1=cleaning`, while keeping
the original numeric type. Consecutive type-0 points are joined; they are not
discarded or each treated as a segment break. Unknown types remain `unknown`.
Invalid points break a display run instead of introducing false connecting lines.
The origin `(0, 0)` is accepted as a coordinate, not treated as an unverified
separator. `route.available=false` differs from an available empty route.

### Revisions, cache and failures

- `map.raster_revision` changes only when PNG bytes change.
- `map.revision` also tracks labels and room geometry.
- `overlay_revision` tracks positions, route, task and sampled status.
- `revision` combines static and overlay revisions. Fetch/serve times are excluded.

On a successful unchanged fetch, `fetched_at` advances but `content_changed_at`
does not. `content_changed_at` is when THIS client first observed this content,
not a robot event timestamp. `source_updated_at` is currently **null**, and
`live_updates_verified` is **false**. A recently fetched cloud file may still be
an old snapshot; fetch age cannot establish measurement age.

After an error, `get_snapshot()` can return cached data with `stale=true`,
`error=map_refresh_failed`, the original fetch time and increasing age.
`allow_stale=False` raises instead. Repeated failures back off from five seconds
up to five minutes. There is no automatic reauthentication or retry storm.
The client serializes refresh calls. Normal vacuum status polling is unchanged.

## Offline normalization and browser demo

```python
from mihome_cloud import build_map_snapshot
from mihome_cloud.map_view import write_map_view

snapshot = build_map_snapshot(decoded_map_json)
write_map_view(snapshot, "private-maps/view")
```

This works entirely offline. No fabricated current time is assigned to an old
map: `fetched_at` is null unless explicitly supplied. To generate a viewer from
one of the existing exports:

```sh
PYTHONPATH=src python tools/preview_x20_map.py \
  --input private-maps/export-01/active.json \
  --output private-maps/view
python -m http.server 8938 --bind 127.0.0.1 --directory private-maps/view
```

Open `http://127.0.0.1:8938/`. Opening `index.html` as `file://` will generally
block its JSON fetch; serve the directory on loopback. The viewer needs no CDN,
fonts, npm packages or new runtime dependencies. Its Canvas layers are:

1. Raster map, reused while its content hash is unchanged.
2. Original route coordinates with antialiasing: solid cleaning, optional dashed
   transport; **no smoothing and no dot at each route point**.
3. Robot/dock and room labels, with controls to hide route types or names.

The browser checks **local** `snapshot.json` every five seconds, pauses while
hidden and never receives Xiaomi credentials or signed URLs. This interval does
not itself fetch cloud data. A future backend producer calls `get_snapshot()`
and publishes its result. `write_map_view()` atomically replaces the JSON and
uses hash-named rasters, so a floor change cannot pair new overlays with an old
image. The viewer also waits for the matching raster before swapping snapshots.
It retains the previous drawing and shows an error if loading fails.

The helper manages a new private directory (0700, files 0600) and refuses an
unmarked existing directory. Exports remain sensitive home-layout data even
though device/account identifiers and signed URLs are absent. Keep the output
under ignored `private-maps/` and serve only via loopback or authenticated Mutti.
There is no automatic history capture or deletion of old raster files.

## Verification and next live experiment

Verified in the development checkout:

- **61 Python tests**: existing behavior, raw-format parsing, room identity and
  label placement, preserved route runs, static/dynamic hashes, cached getters,
  stale data/backoff, saved-floor mismatch, no implicit polling, private output.
- Previously downloaded active and saved maps normalize successfully, preserving
  every valid route point. This check is offline, not a new live test.
- **12 Chromium integration checks** using fictional deterministic geometry:
  labels, transport toggle, overlay-only update with image reuse, floor change,
  safe name rendering, failure/recovery, desktop/mobile size and no external
  page requests. Screenshots are browser-demo evidence, not robot live evidence.
- A wheel build includes the map modules, device profiles and HTML resource;
  resources load from the built wheel without additional dependencies.

Browser checks can be repeated with the optional developer dependency
`websocket-client`: generate the fixture with
`PYTHONPATH=src python tests/browser_map_fixture.py`, serve
`/tmp/mihome-browser-fixture` on loopback port 8937, start dedicated headless
Chromium with a new profile and debugging on loopback port 9347, and run
`PYTHONPATH=src python tests/browser_map_view.py`. Do not attach to a personal
browser profile. Screenshot outputs are `/tmp/mihome-view-{desktop,mobile}.png`.

When the user next starts cleaning, collect a bounded series of snapshots at
five-second intervals. Compare position, pose ID, task ID, route count/revision,
file hash and request duration while retaining timestamps. This can establish
whether the source changes during a run, how often it uploads, whether paths
are cumulative, and whether routing survives task transitions. It cannot by
itself establish exact device-to-cloud latency without a device timestamp or
simultaneous observation. Nothing in this change starts that experiment.

Later Mutti integration needs one shared map client on the backend, authenticated
snapshot/image endpoints (or SSE/WebSocket pushes), and the Canvas renderer.
Only the backend contacts Xiaomi. The browser can redraw smoothly while waiting
for real samples, but should not invent robot movement between stale samples.
No Mutti integration or production deployment is part of this change.
