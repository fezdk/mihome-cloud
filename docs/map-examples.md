# Room configuration with the recorded route drawn on the map

This read-only example supports **Xiaomi Robot Vacuum X20 Pro
(`xiaomi.vacuum.d102gl`)**. It uses the existing saved session and does not start
cleaning or switch floors. Install the checkout with `pip install -e .` first.
Set `--country` to the region of your working cloud connection.

## Complete export and browser view

Run from the repository root:

```sh
mkdir -m 700 -p private-maps
python tools/export_x20_map.py \
  --auth-state auth_state.json \
  --country de \
  --output private-maps/room-route-01
python tools/preview_x20_map.py \
  --input private-maps/room-route-01/active.json \
  --output private-maps/room-route-view
python -m http.server 8938 --bind 127.0.0.1 --directory private-maps/room-route-view
```

Open [the local room-and-route view](http://127.0.0.1:8938/). Stop the server with
Ctrl+C. Use a new export directory for another cloud download; the managed viewer
directory can be updated by rerunning the preview command.

The exporter discovers the vacuum automatically when exactly one X20 Pro is
present. With multiple devices, pass `--device-id` using a DID returned by
`cloud.get_devices()`; names and model codes are also available in that list.
Both tools reuse local data/session information and never initiate a login.

The view draws:

- The floor plan, with room names or an explicit room-ID fallback.
- The most recent recorded cleaning route (`type=1`) as continuous lines with
  antialiasing, without smoothing or a marker at every point.
- Optional transport runs (`type=0`) as dashed lines, toggled separately.
- Robot and dock markers where the downloaded file supplies positions.

Route types reflect observed behavior, not a verified manufacturer enum. The
route may be from the last completed task; this example does not establish that
cleaning is underway. Files without route data still show their floor plan.

| Output | Contents |
| --- | --- |
| `room-route-01/active.raw` | Original encrypted map envelope. |
| `room-route-01/active.json` | Full decoded vendor map, including room attributes and available route points. |
| `room-route-01/active-geometry.json` | Derived room boundaries, IDs and coordinate metadata. |
| `room-route-01/active.png` | Static raster floor plan. Names, route and position markers are separate overlays. |
| `room-route-view/snapshot.json` | Normalized room configuration, boundaries, labels, route, positions and freshness fields. |
| `room-route-view/index.html` | Canvas viewer that draws those overlays on the raster. |

All these paths are under `private-maps/`. The **browser view is the combined
map with its route drawn on it**; the PNG exporter does not bake overlays into
the image. The viewer only reloads local JSON, so this one-shot export stays
static until a producer publishes another snapshot.

## Use the room configuration and route in Python

After the export above, the normalized data can be read entirely offline:

```python
import json
from pathlib import Path

snapshot = json.loads(
    Path("private-maps/room-route-view/snapshot.json").read_text()
)
map_id = snapshot["map"]["id"]
room_configuration = snapshot["rooms"]
# Each entry includes room_id, grid_id, name, display_name, label, rings_grid and rings_mm.
route = snapshot["route"]
# route["points"] retains x/y/type; route["segments"] groups consecutive types.
cleaning_runs = [s for s in route["segments"] if s["kind"] == "cleaning"]
```

Use the rings and label coordinates in the snapshot's millimetre coordinate
system. For raster/Canvas coordinates:

```python
m = snapshot["map"]

def to_pixel(x_mm, y_mm):
    x = (x_mm - m["origin"]["x"]) / m["resolution_mm"]
    y = m["height"] - 1 - (y_mm - m["origin"]["y"]) / m["resolution_mm"]
    return x, y
```

Draw each consecutive route segment as its own line. Do not concatenate
separate cleaning runs across intervening transport runs. The included viewer
already implements the coordinate conversion and layer drawing.

To build the same viewer from an existing authenticated device instance:

```python
from mihome_cloud.map_view import write_map_view

snapshot = vacuum.maps.get_snapshot()
write_map_view(snapshot, "private-maps/library-view")
room_configuration = snapshot.to_dict()["rooms"]
route = snapshot.to_dict()["route"]
```

Serve `private-maps/library-view` on loopback as above. Reuse `vacuum.maps` for
later refreshes; publishing a new snapshot updates the local view on its next
five-second check. For ongoing cloud reads, use a ten-second interval. Changing
positions/routes were observed during cleaning; exact upload cadence remains
unknown. See the [snapshot contract and refresh limits](map-api.md).

## Named, unnamed and saved-floor rooms

`vacuum.rooms()` supplies the named entries from the MIoT `room_info` property.
For the complete property, including unnamed entries:

```python
import json

raw = vacuum.get_property("room_info")
room_info = json.loads(raw) if isinstance(raw, str) else (raw or {})
reported_rooms = room_info.get("rooms", [])
```

The snapshot supplies room IDs and geometry even when the file has no room
names. Empty `name` values stay empty; `display_name` supplies `Room <id>` or
`Segment <grid_id>` for presentation. The Danish demo uses `Rum <id>` on the
canvas. These fallback labels are not aliases for `clean_rooms()`.

`vacuum.maps.list_maps()` returns saved-floor names, IDs and `is_current`.
`get_snapshot(map_id=...)` reads a selected saved floor without switching the
robot; wait for the shared refresh interval when requesting another uncached
floor. Saved-floor files can omit robot positions and routes. Scope room IDs
to the map, and use the current room configuration when issuing room commands.

For a one-shot export of all reported saved maps, add `--all-maps` to the first
command. `manifest.json` associates `saved-N` files with their map IDs. Run the
preview tool against the chosen `saved-N.json` to view that floor.
