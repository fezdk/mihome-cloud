# Xiaomi Robot Vacuum X20 Pro map protocol findings

Model: **`xiaomi.vacuum.d102gl`**. Investigated on a real X20 Pro on
2026-10-31 using an existing MiHome session. Active and saved maps were downloaded,
decoded and exported successfully. No firmware, robot settings, maps or cleaning
tasks were changed. This document contains protocol findings, not private maps.

For the usable library interface and local viewer, see [map-api.md](map-api.md).
Changing positions and the active route were subsequently verified during a
user-started cleaning; exact latency remains unknown. See [live observations](map-api.md#verification-and-observed-live-behavior).

## What is available

| Data | Verified result |
| --- | --- |
| `room_info` (2/16) | JSON containing `map_uid` and rooms with `id`/`name`; no geometry. Names can be empty. |
| Active map | JSON-v2 envelope decrypting to structured JSON; raster length matches `width * height`. |
| Saved floors | `map_management.map_array` contains names, IDs, object references and `is_current`. Reported saved files were downloaded without switching floors. |
| Backups | `backup_map_list.backup_map_arr` was readable. Backup files were not downloaded or restored. |
| Room geometry | Exact closed contours can be derived from labeled raster cells, including holes. These are derived contours, not claimed original app polygons. |
| Room IDs | `map_room_info` maps `grid_id` to `room_id`; active IDs matched `room_info` and `room_attrs.id`. |
| Label positions | `room_attrs` supplies `room_name`, `name_pos_x` and `name_pos_y`. Invalid/outside anchors need an interior-cell fallback. |
| Walls/obstacles | Raster occupancy exists, but fixed walls cannot reliably be distinguished from furniture or other obstacles. |
| Additional lines | `map_3d_info` contains `room_id` and lines with `type`, `update`, `segment`, `bak_segment`. Some endpoints did not fit the raster bounds under a direct same-frame interpretation; semantics remain unverified. |
| Robot/dock | The map contains `position.{x,y,yaw}`, `have_pile`, `pile_x`, `pile_y`, `pile_yaw`. MIoT 10/4 was empty in the tested state. |
| Route | The active map contains ordered `paths.points` with `x`, `y`, `type`, plus `pose_id`. The final point matched the robot position. Tested saved floors omitted the route. |

Other preserved fields include `task_id`, `map_type`, `map_name`, `room_attrs`
and `current_cleaning_config`. The isolated low-level exporter preserves the full
decoded JSON rather than discarding fields it does not interpret.

## Map identity and timestamps

`current_map_id` (10/6) returned **0**. The active file's `map_id` matched the
saved-map entry marked `is_current`; `room_info.map_uid` did not match saved-map
IDs. Therefore `map_uid` must not be treated as a floor ID. Its exact semantics
are unknown. Explicit saved-floor downloads verify their embedded `map_id`.
Room identifiers should be scoped to a map, not treated as globally unique.

The active payload carries `task_id`, `map_id`, `paths` and
`current_cleaning_config` together, allowing a task/route/map snapshot association.
An idle robot can retain the last task: presence of `task_id` does not establish
ongoing cleaning. Task-ID uniqueness across restarts has not been verified.

No explicit per-map `ctime`, `mtime`, `created_at` or `updated_at` was found.
Map-list and backup-list `index` fields resemble Unix timestamps, but they were
not corroborated as cleaning or map-change times. Backup `map_name` values can
also look timestamp-based. Preserve these fields without calling them creation
times. Periodic storage/rewriting is a possible explanation, not a verified
mechanism. Local `fetched_at` describes retrieval, not device measurement time.

## Read-only endpoints

The tested regional base was `https://de.api.io.mi.com/app`. Xiaomi uses HTTP
POST for the following read-only API operations:

1. `/home/device_list`: discover the device/model if needed.
2. `/v2/home/rpc/{did}`, `method=get_properties`: read 2/16 and 10/1, 10/2,
   10/4, 10/5, 10/6, 10/7, 10/9, 10/13. The snapshot API also reads status 2/2.
3. `/v2/home/get_interim_file_url_pro`, body `{"obj_name": <reported object>}`:
   obtain a temporary signed URL for 10/1 or `map_array[].obj_name`.
4. HTTPS GET of that URL using a separate session without account cookies.

The non-pro `/v2/home/get_interim_file_url` returned **code -6** on the tested
account. `_pro` returned **code 0** and usable downloads. Object names come from
the device response; no slots are fabricated, and no upload action is requested.
Signed URLs are kept in memory, never persisted in the exported snapshot.

## Xiaomi JSON-v2 decode chain

The downloaded envelope is `{"version":2,"data":"<base64>"}`:

1. Take the last 16 model-string characters as a Latin-1 AES seed.
2. Use IV `ABCDEF1234123412`, a public protocol constant, not a credential.
3. AES-CBC encrypt PKCS#7-padded `seed + did` using that seed and IV.
4. MD5 of the ciphertext yields the map decryption key.
5. Base64-decode envelope `data`; AES-CBC decrypt using the derived key and
   same IV; PKCS#7-unpad; zlib-decompress; parse JSON.
6. Inner `map_data` is base64 + zlib, yielding one byte per raster cell.

Map decryption is separate from the existing authenticated RC4 RPC transport.
It needs model/DID, while cloud download authorization still requires the saved
session. The implementation reuses `MiHomeCloud` and adds no login mechanism.

## Coordinates, routes and rendering

The tested files report `resolution=50`, interpreted as **50 mm per cell** by
the Xiaomi JSON protocol reference. This has not been physically surveyed.
For grid cell `(col,row)`, the lower-left corner is
`(origin_x + col*resolution, origin_y + row*resolution)`. Centers add half a cell.
Rows grow toward +y; PNG/Canvas invert y. Geographic north and yaw units have
not been verified. Room contours retain outer CCW/hole CW winding in native axes.

The reference cell alphabet is 0 unknown/outside, 1–2 floor, 3–63 room labels,
and >63 occupied/wall. Use the explicit grid-to-room table, not the color value,
to join room IDs. Unknown cells must not automatically be called walls.

Separate plots of the actual ordered route support **0 = transport** and
**1 = cleaning**. This is an observed interpretation, not a vendor-defined enum;
it does not establish motor/mop state or shortest-path planning. Repeated zeros
form contiguous transport runs. Splitting at every zero, as a reference renderer
does, produces misleading isolated dots. Keep raw values, split display runs at
type changes, and do not join nonadjacent runs across another type.

The viewer uses original coordinates, antialiasing and no per-point markers.
Smoothing was explored locally but is not the default. Raster room contours
retain their cell-scale steps. Additional 3D lines are not verified as a complete
smoothed floor plan or as the official app's rendering source.

Manufacturer dimensions are robot diameter **350 mm**, height **97 mm**, and
dock **340 × 420 × 563 mm**. The viewer draws a scale-correct robot circle but
uses a symbolic dock because its anchor and yaw interpretation are unresolved.
[Xiaomi specifications](https://www.mi.com/se/product/xiaomi-robot-vacuum-x20-pro/specs/)

## History and live measurement

`clean-record` (10/3) returned totals and a `history_list` of cleaning summaries.
Each entry contained `stime` and an underscore-separated numeric `label`; there
was no direct `obj_name`, `map_id`, `task_id` or route geometry. Label-component
semantics were not validated.

`/user/get_user_device_data` with `type=prop`, `key=10.3`, `limit=5`, and a time
window from epoch to request time returned code 0 with an empty result. An initial
attempt with `prop.10.3` also returned empty, but that is not the reference's key
format. These responses do **not** establish that historical route files are
unavailable. No model-verified mapping from summary to old route file was found.
Roborock's `get_clean_record_map` and Dreame's historical-object flow were not
assumed compatible or called on this model.

Local end-of-task archiving is a possible fallback: retain the map, route, raw
blob, map/task IDs and fetch time after a verified task completion. A dock visit
for mop washing must not be mistaken for task completion. Automatic archiving is not implemented. Mutti now has a separate interactive
map/control panel; it does not archive completed tasks.

A read-only sample series during a user-started cleaning has now demonstrated
changing robot positions and an active route, including updates after Xiaomi Home
was closed. See the [measurement summary](map-api.md#verification-and-observed-live-behavior).
No cleaning was started by the experiment. A ten-second client interval is the
current dashboard choice; source measurement timestamps remain unknown.

## References and evidence boundaries

- [Xiaomi-vac JSON decryption](https://github.com/letitbe-dull/xiaomi-vac/blob/d1eb941ac8a1c4991221a56b9ca0e380362584b4/custom_components/xiaomi_vac/xiaomi_json_decrypt.py) documents findings from the Xiaomi Home `com.xiaomi.robovac` plugin. The decoder implements that protocol independently; this investigation did not instrument the official app.
- [Model routing](https://github.com/letitbe-dull/xiaomi-vac/blob/d1eb941ac8a1c4991221a56b9ca0e380362584b4/custom_components/xiaomi_vac/map_parsers.py) initially added d102gl on model-family grounds. Actual device downloads here provide the X20 Pro verification.
- [Grid/coordinate interpretation](https://github.com/letitbe-dull/xiaomi-vac/blob/d1eb941ac8a1c4991221a56b9ca0e380362584b4/custom_components/xiaomi_vac/map_vector.py) and [route parser](https://github.com/letitbe-dull/xiaomi-vac/blob/d1eb941ac8a1c4991221a56b9ca0e380362584b4/custom_components/xiaomi_vac/xiaomi_map_overlays.py) inform parsing; route segmentation differs where actual point sequences contradict the reference heuristic.
- [Tasshack cloud transport](https://github.com/Tasshack/dreame-vacuum/blob/master/custom_components/dreame_vacuum/dreame/protocol.py) documents the URL-endpoint family. Its Dreame map parser was not used.
- [Map Extractor #579](https://github.com/PiotrMachowski/Home-Assistant-custom-components-Xiaomi-Cloud-Map-Extractor/issues/579) and [#659](https://github.com/PiotrMachowski/Home-Assistant-custom-components-Xiaomi-Cloud-Map-Extractor/issues/659) document historical X20 Pro issues; a failing Dreame fallback does not prove the Xiaomi JSON format cannot be exported.
- [d102gl history metadata](https://github.com/al-one/hass-xiaomi-miot/issues/2707), [ov51gl map notes](https://github.com/jrrome/xiaomi-vacuum-ov51gl/blob/main/docs/map.md) and [X20 Pro room integration](https://github.com/AldenDana/ha-xiaomi-vacuum-x20pro) provide related model observations, not guarantees for all firmware/regions.

Validation uses synthetic fixtures in Git. Private downloads were checked locally
for dimensions, room-ID joins, closed-ring areas and snapshot normalization.
No credentials, actual device identifiers, room names, coordinates, maps or
route samples are included in commits. See [map-api.md](map-api.md) for test and
browser verification details.
