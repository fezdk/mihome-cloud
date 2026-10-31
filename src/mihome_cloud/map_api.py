"""JSON-ready map snapshots for Xiaomi X20 Pro, without implicit polling.

Positions and routes come from the SAME downloaded map file. Fetch time is not
robot measurement time. Updating routes during cleaning is not yet verified.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .maps import MODEL, MapError, X20MapReader, geometry, grid_data, render_png


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _position(value: Any) -> dict | None:
    if not isinstance(value, dict) or not all(_number(value.get(k)) for k in ("x", "y")):
        return None
    return {"x": value["x"], "y": value["y"]}


def _id(value: Any) -> bool:
    return type(value) is int and value >= 0


@dataclass(frozen=True)
class MapInfo:
    """Saved-map identity; cloud object names are intentionally not exposed."""
    map_id: int
    name: str = field(repr=False)
    is_current: bool

    def to_dict(self) -> dict:
        return {"map_id": self.map_id, "name": self.name, "is_current": self.is_current}


@dataclass(frozen=True, repr=False)
class MapSnapshot:
    """Private snapshot; repr never includes names, coordinates or credentials.

    ``to_dict()`` is JSON-ready and safe from mutation of the cached snapshot.
    It still contains PRIVATE home data: serve only through authorized access.
    ``png()`` is the static raster, with label and route overlays kept separate.
    """
    _payload: dict
    _image: bytes

    def __repr__(self) -> str:
        return "<MapSnapshot private>"

    def to_dict(self) -> dict:
        return copy.deepcopy(self._payload)

    def png(self) -> bytes:
        return self._image

    @property
    def map_id(self) -> int:
        return self._payload["map"]["id"]

    @property
    def revision(self) -> str:
        return self._payload["revision"]


def route_geometry(data: dict) -> dict:
    """Preserve raw types; split display runs at TYPE CHANGES, never every zero.

    Labels transport/cleaning reflect observations on our d102gl. They do not
    establish motor state, route destination or a vendor-defined type enum.
    Invalid points break runs, so missing coordinates never create fake links.
    """
    paths = data.get("paths")
    if paths is None:
        return {"available": False, "pose_id": None, "points": [], "segments": [],
                "discarded_points": 0, "type_interpretation": "observed_d102gl"}
    if not isinstance(paths, dict):
        raise MapError("Invalid route container")
    points = paths.get("points", [])
    if isinstance(points, str):
        try:
            points = json.loads(points)
        except ValueError:
            raise MapError("Invalid route points") from None
    if not isinstance(points, list) or len(points) > 200_000:
        raise MapError("Invalid or oversized route")
    valid, segments, current, discarded = [], [], None, 0
    for point in points:
        position = _position(point)
        kind = point.get("type") if isinstance(point, dict) else None
        if position is None or type(kind) is not int:
            discarded += 1
            current = None
            continue
        valid.append({**position, "type": kind})
        if current is None or current["type"] != kind:
            current = {"type": kind, "kind": {0: "transport", 1: "cleaning"}.get(kind, "unknown"),
                       "points": []}
            segments.append(current)
        # (0, 0) is a valid coordinate: no unverified sentinel heuristics.
        current["points"].append([position["x"], position["y"]])
    return {"available": True, "pose_id": paths.get("pose_id"), "points": valid,
            "segments": segments, "discarded_points": discarded,
            "type_interpretation": "observed_d102gl"}


def build_map_snapshot(data: dict, *, name: str = "", room_info: dict | None = None,
                       room_names: dict[int, str] | None = None,
                       fetched_at: str | None = None, status_code: int | None = None,
                       source: str = "offline_file") -> MapSnapshot:
    """Normalize an already decoded file, with no network or disk side effects.

    ``room_names`` overrides labels ONLY for this map; ID alone is not globally
    unique. Empty vendor names stay empty in ``name``; ``display_name`` identifies
    unnamed rooms explicitly. Source label positions outside the room fall back
    to an actual interior cell rather than a centroid possibly inside a hole.
    """
    if not _id(data.get("map_id")):
        raise MapError("Missing or invalid map ID")
    geom = geometry(data, room_info)
    width, height, cells = grid_data(data)
    res = geom["coordinates"]["resolution"]
    ox, oy = geom["coordinates"]["origin"]
    attrs = {row["id"]: row for row in data.get("room_attrs", [])}
    masks: dict[int, list[tuple[int, int]]] = {}
    for i, label in enumerate(cells):
        if 3 <= label <= 63:
            masks.setdefault(label, []).append((i % width, i // width))
    rooms = []
    for room in geom["rooms"]:
        label, rid = room["grid_id"], room["room_id"]
        attr = attrs.get(rid, {})
        x, y = attr.get("name_pos_x"), attr.get("name_pos_y")
        col = math.floor((x - ox) / res) if _number(x) else -1
        row = math.floor((y - oy) / res) if _number(y) else -1
        inside = (0 <= col < width and 0 <= row < height and cells[row * width + col] == label)
        label_source = "map_room_attrs" if inside else "interior_cell"
        if not inside:
            mask = masks[label]
            cx = sum(p[0] for p in mask) / len(mask)
            cy = sum(p[1] for p in mask) / len(mask)
            col, row = min(mask, key=lambda p: (p[0] - cx)**2 + (p[1] - cy)**2)
            x, y = ox + (col + .5) * res, oy + (row + .5) * res
        actual_name = (room_names or {}).get(rid, room["name"])
        if not isinstance(actual_name, str):
            raise MapError("Room name must be a string")
        rooms.append({**room, "name": actual_name,
                      "display_name": actual_name or (f"Room {rid}" if rid is not None else f"Segment {label}"),
                      "label": {"x": x, "y": y, "source": label_source}})
    robot_raw = data.get("position") or {}
    robot_pos = _position(robot_raw)
    robot = {"available": robot_pos is not None, "position": robot_pos,
             "yaw_raw": robot_raw.get("yaw") if isinstance(robot_raw, dict) else None,
             "source": "map_file", "orientation_verified": False,
             "footprint": {"shape": "circle", "diameter_mm": 350}}
    dock_pos = (_position({"x": data.get("pile_x"), "y": data.get("pile_y")})
                if data.get("have_pile") is True else None)
    dock = {"available": dock_pos is not None, "position": dock_pos,
            "yaw_raw": data.get("pile_yaw"), "source": "map_file",
            "orientation_verified": False, "anchor_verified": False,
            "footprint": {"shape": "rectangle", "width_mm": 340, "depth_mm": 420,
                          "basis": "manufacturer_outer_dimensions", "user_sketch_depth_mm": 400}}
    route = route_geometry(data)
    png = render_png(data, scale=1)
    raster_revision = hashlib.sha256(png).hexdigest()
    map_data = {"id": data["map_id"], "name": name or data.get("map_name", ""),
                "width": width, "height": height, "resolution_mm": res,
                "origin": {"x": ox, "y": oy}, "unit": "mm", "row_direction": "+y",
                "image_y": "height - 1 - row", "north": None,
                "raster_revision": raster_revision}
    map_revision = _digest({"map": map_data, "rooms": rooms})
    overlay = {"robot": robot, "dock": dock, "route": route,
               "task_id": data.get("task_id"), "status_code": status_code}
    overlay_revision = _digest(overlay)
    map_data["revision"] = map_revision
    payload = {"schema": "mihome-map-snapshot-v1", "model": MODEL, "map": map_data,
               "rooms": rooms, **overlay, "overlay_revision": overlay_revision,
               "revision": _digest([map_revision, overlay_revision]),
               "freshness": {"source": source, "fetched_at": fetched_at,
                             "served_at": _utc(), "source_updated_at": None,
                             "content_changed_at": None, "age_seconds": None,
                             "cache_hit": False, "stale": False, "error": None,
                             "live_updates_verified": False},
               "identity": {"room_info_map_uid_matches": geom["room_info_comparison"]["map_uid_matches_map_id"],
                            "saved_map_match": None}}
    return MapSnapshot(payload, png)


@dataclass
class _Cached:
    snapshot: MapSnapshot
    fetched: float


class VacuumMapClient:
    """Read-only, rate-limited snapshots. No threads, timers or login on creation.

    A shared client serves multiple consumers from the same cache. Five seconds
    is a local request guard, NOT a claim about Xiaomi's update rate. Errors use
    exponential backoff up to 5 minutes. Explicit saved-map reads never switch
    the robot's active map. Positions and route come only from the map file,
    since MIoT 10/4 was empty on the tested X20 Pro.
    """

    def __init__(self, cloud, device_id: str, model: str = MODEL, *,
                 min_refresh_interval: float = 5, metadata_ttl: float = 60,
                 room_names: dict[int, dict[int, str]] | None = None):
        if (not _number(min_refresh_interval) or min_refresh_interval < 5
                or not _number(metadata_ttl) or metadata_ttl < min_refresh_interval):
            raise ValueError("Refresh interval must be >=5 seconds and metadata TTL >= interval")
        self._reader = X20MapReader(cloud, device_id, model)
        self.min_refresh_interval = float(min_refresh_interval)
        self.metadata_ttl = float(metadata_ttl)
        self._names = copy.deepcopy(room_names or {})
        self._lock = threading.RLock()
        self._metadata: dict | None = None
        self._metadata_time = float('-inf')
        self._next_metadata = float('-inf')
        self._cache: dict[int | None, _Cached] = {}
        self._next_fetch = float('-inf')
        self._failures = 0
        self._last_error: str | None = None

    def _load_metadata(self, *, force: bool = False) -> dict:
        now = time.monotonic()
        if self._metadata is not None and not force and now - self._metadata_time < self.metadata_ttl:
            return self._metadata
        if now < self._next_metadata:
            raise MapError("Map metadata refresh is rate limited")
        self._next_metadata = now + self.min_refresh_interval
        metadata = self._reader.metadata()
        self._metadata = metadata
        self._metadata_time = time.monotonic()
        return metadata

    @staticmethod
    def _entries(metadata: dict) -> list[dict]:
        management = metadata["values"].get("map_management")
        if not isinstance(management, dict) or not isinstance(management.get("map_array"), list):
            raise MapError("Saved-map inventory unavailable")
        entries = management["map_array"]
        if len(entries) > 10 or any(not isinstance(e, dict) or not _id(e.get("map_id")) for e in entries):
            raise MapError("Invalid saved-map inventory")
        if len({e["map_id"] for e in entries}) != len(entries):
            raise MapError("Ambiguous saved-map inventory")
        return entries

    def list_maps(self) -> list[MapInfo]:
        """List saved maps with names and is_current, without downloading files."""
        with self._lock:
            entries = self._entries(self._load_metadata())
            return [MapInfo(e["map_id"], str(e.get("map_name") or ""), bool(e.get("is_current")))
                    for e in entries]

    def _deliver(self, cached: _Cached, *, cache_hit: bool, error: str | None = None) -> MapSnapshot:
        result = cached.snapshot.to_dict()
        result["freshness"].update({
            "served_at": _utc(), "age_seconds": round(max(0, time.monotonic() - cached.fetched), 3),
            "cache_hit": cache_hit, "stale": error is not None, "error": error,
        })
        return MapSnapshot(result, cached.snapshot.png())

    def get_snapshot(self, map_id: int | None = None, *, allow_stale: bool = True) -> MapSnapshot:
        """Get current snapshot, or a saved floor by ID, with a shared rate guard.

        Never infer an active floor from current_map_id=0 or room_info.map_uid.
        Saved map IDs must match the embedded file ID. A mismatch is an error;
        existing data may be returned only with explicit stale/error flags.
        """
        if map_id is not None and not _id(map_id):
            raise ValueError("map_id must be a nonnegative integer or None")
        with self._lock:
            now = time.monotonic()
            cached = self._cache.get(map_id)
            if now < self._next_fetch:
                if cached is not None and (allow_stale or self._last_error is None):
                    return self._deliver(cached, cache_hit=True, error=self._last_error)
                raise MapError("Map refresh is rate limited or backing off")
            self._next_fetch = now + self.min_refresh_interval
            try:
                # Current metadata is re-read once per permitted active refresh:
                # object slots may stay constant while position/route change.
                metadata = self._load_metadata(force=(map_id is None and
                                                     now - self._metadata_time >= self.min_refresh_interval))
                values = metadata["values"]
                entries = self._entries(metadata)
                entry = next((e for e in entries if e["map_id"] == map_id), None)
                if map_id is not None and entry is None:
                    raise MapError("Unknown saved map ID")
                obj = entry.get("obj_name") if entry else values.get("map_object")
                # Some related firmware wraps obj_name; never fabricate a slot.
                if isinstance(obj, dict):
                    obj = obj.get("obj_name")
                _, data = self._reader.fetch(obj)
                if map_id is not None and data.get("map_id") != map_id:
                    raise MapError("Saved object map ID does not match inventory")
                match = next((e for e in entries if e["map_id"] == data.get("map_id")), None)
                fetched_at = _utc()
                snapshot = build_map_snapshot(
                    data, name=str((match or {}).get("map_name") or ""),
                    room_info=values.get("room_info") if map_id is None else None,
                    room_names=self._names.get(data.get("map_id")), fetched_at=fetched_at,
                    status_code=values.get("status") if map_id is None else None,
                    source="xiaomi_cloud_map",
                )
                payload = snapshot.to_dict()
                payload["identity"]["saved_map_match"] = match is not None
                payload["freshness"]["content_changed_at"] = (
                    cached.snapshot.to_dict()["freshness"]["content_changed_at"]
                    if cached and cached.snapshot.revision == snapshot.revision else fetched_at)
                stored = _Cached(MapSnapshot(payload, snapshot.png()), time.monotonic())
                self._cache[map_id] = stored
                self._failures, self._last_error = 0, None
                self._next_fetch = time.monotonic() + self.min_refresh_interval
                return self._deliver(stored, cache_hit=False)
            except Exception:
                self._failures += 1
                self._last_error = "map_refresh_failed"
                self._next_fetch = time.monotonic() + min(300, self.min_refresh_interval * 2**min(self._failures - 1, 6))
                if cached is not None and allow_stale:
                    return self._deliver(cached, cache_hit=True, error=self._last_error)
                raise MapError("Map refresh failed; check session, connection and reported map identity") from None

    def get_positions(self) -> dict:
        """Positions from the active snapshot, sharing its cache and freshness."""
        data = self.get_snapshot().to_dict()
        return {k: data[k] for k in ("robot", "dock", "freshness")} | {"map_id": data["map"]["id"]}

    def get_route(self) -> dict:
        """Last available route, not a guarantee of an ongoing cleaning task."""
        data = self.get_snapshot().to_dict()
        return {"map_id": data["map"]["id"], "task_id": data["task_id"],
                "route": data["route"], "freshness": data["freshness"]}
