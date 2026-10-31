"""Opt-in, read-only Xiaomi X20 Pro map export. Never used by status polling.

Protocol references and limitations: docs/x20-pro-maps.md. All returned data
is private home-layout data. Callers must not log it or commit exports.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import struct
import zlib
from collections import defaultdict
from urllib.parse import urlparse

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

from mihome_cloud.client import MiHomeCloud

MODEL = "xiaomi.vacuum.d102gl"
MAX_BYTES = 16 * 1024 * 1024
MAX_CELLS = 4 * 1024 * 1024
PROPERTIES = {
    "status": (2, 2), "room_info": (2, 16), "map_object": (10, 1),
    "trajectory_object": (10, 2), "vacuum_position": (10, 4),
    "map_management": (10, 5), "current_map_id": (10, 6),
    "carpet_object": (10, 7), "map_3d_info": (10, 9),
    "backup_map_list": (10, 13),
}


class MapError(ValueError):
    """Safe, payload-free error from the experimental map reader."""


def _inflate(data: bytes, limit: int = MAX_BYTES) -> bytes:
    decoder = zlib.decompressobj()
    try:
        result = decoder.decompress(data, limit + 1)
    except zlib.error:
        raise MapError("Invalid compressed map") from None
    if len(result) > limit or not decoder.eof or decoder.unused_data:
        raise MapError("Oversized, truncated or trailing compressed map")
    return result


def decode_map(raw: bytes, device_id: str, model: str = MODEL) -> dict:
    """Decode the observed JSON-v2 / base64 / AES-CBC / zlib format.

    Model-derived key protocol independently implemented from the documented
    Xiaomi Home plugin findings in letitbe-dull/xiaomi-vac. No device token,
    firmware change, Dreame encryption key, or extra login is needed.
    """
    if model != MODEL or len(raw) > MAX_BYTES:
        raise MapError("Unsupported model or oversized map")
    try:
        envelope = json.loads(raw)
        if not isinstance(envelope, dict) or envelope.get("version") != 2:
            raise MapError("Unsupported map envelope (expected version 2)")
        ciphertext = base64.b64decode(envelope["data"], validate=True)
        seed = model[-16:].encode("latin1")
        iv = b"ABCDEF1234123412"
        material = AES.new(seed, AES.MODE_CBC, iv).encrypt(
            pad(seed + str(device_id).encode("latin1"), AES.block_size)
        )
        key = hashlib.md5(material).digest()
        compressed = unpad(AES.new(key, AES.MODE_CBC, iv).decrypt(ciphertext), 16)
        data = json.loads(_inflate(compressed))
        if not isinstance(data, dict):
            raise MapError("Map payload must be an object")
        return data
    except MapError:
        raise
    except (KeyError, TypeError, ValueError, UnicodeError):
        raise MapError("Map decryption or JSON decoding failed") from None


class X20MapReader:
    """One-shot reader using a restored MiHomeCloud session, without renewal.

    Every RPC is allowlisted here and uses allow_reauth=False. A stale session
    fails instead of starting a password login or modifying session files.
    """

    def __init__(self, cloud: MiHomeCloud, device_id: str, model: str = MODEL):
        if model != MODEL or not str(device_id).isdigit():
            raise MapError("Expected X20 Pro model and numeric cloud device ID")
        self.cloud = cloud
        self.device_id = str(device_id)

    def _read(self, path: str, data: dict) -> dict:
        try:
            result = self.cloud._rpc(self.cloud._base_url + path, data, allow_reauth=False)
        except Exception:
            raise MapError("Cloud read failed; check the existing session and connection") from None
        if not isinstance(result, dict) or result.get("code") != 0:
            raise MapError("Cloud read was rejected")
        return result

    def metadata(self) -> dict:
        """Preserve the complete property response, including error codes."""
        response = self._read("/v2/home/rpc/" + self.device_id, {
            "method": "get_properties", "params": [
                {"did": f"{s}.{p}", "siid": s, "piid": p}
                for s, p in PROPERTIES.values()
            ],
        })
        items = response.get("result")
        if not isinstance(items, list):
            raise MapError("Missing property response")
        by_pair = {(i.get("siid"), i.get("piid")): i for i in items}
        values = {}
        for name, pair in PROPERTIES.items():
            item = by_pair.get(pair, {})
            value = item.get("value") if item.get("code") == 0 else None
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except ValueError:
                    pass
            values[name] = value
        return {"raw_response": response, "values": values}

    def download(self, object_name: str) -> bytes:
        """Fetch an explicitly reported object; no guessed slots or upload actions.

        The _pro endpoint is verified on X20 Pro; the non-pro endpoint returned
        -6 on the tested account. Signed URLs are kept only in memory.
        """
        if not isinstance(object_name, str) or not object_name:
            raise MapError("No cloud map object reported")
        result = self._read("/v2/home/get_interim_file_url_pro", {"obj_name": object_name})
        url = (result.get("result") or {}).get("url")
        if not isinstance(url, str):
            raise MapError("No map download URL returned")
        parsed = urlparse(url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.fragment):
            raise MapError("Invalid map download URL")
        # Separate HTTP session: never forward Xiaomi account cookies to storage.
        # Redirects are refused rather than leaking the signed query elsewhere.
        try:
            with requests.Session() as session:
                with session.get(url, timeout=(10, 30), stream=True,
                                 allow_redirects=False) as response:
                    if response.status_code != 200:
                        raise MapError("Map storage rejected download")
                    chunks, size = [], 0
                    for chunk in response.iter_content(65536):
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise MapError("Map download exceeds size limit")
                        chunks.append(chunk)
                    return b"".join(chunks)
        except requests.RequestException:
            raise MapError("Map download failed") from None

    def fetch(self, object_name: str) -> tuple[bytes, dict]:
        raw = self.download(object_name)
        return raw, decode_map(raw, self.device_id)


def grid_data(data: dict) -> tuple[int, int, bytes]:
    try:
        width, height = data["width"], data["height"]
        if (type(width) is not int or type(height) is not int
                or min(width, height) <= 0 or width * height > MAX_CELLS):
            raise MapError("Invalid map dimensions")
        cells = _inflate(base64.b64decode(data["map_data"], validate=True), width * height)
        if len(cells) != width * height:
            raise MapError("Map grid size does not match dimensions")
        return width, height, cells
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, MapError):
            raise
        raise MapError("Invalid map grid") from None


def _rings(cells: set[tuple[int, int]]) -> list[list[list[int]]]:
    """Trace exact cell-edge rings; holes remain separate clockwise rings."""
    edges = set()
    for x, y in cells:
        corners = [(x, y), (x + 1, y), (x + 1, y + 1), (x, y + 1)]
        for start, end in zip(corners, corners[1:] + corners[:1]):
            if (end, start) in edges:
                edges.remove((end, start))
            else:
                edges.add((start, end))
    outgoing = defaultdict(set)
    for a, b in edges:
        outgoing[a].add(b)
    rings = []
    directions = {(1, 0): 0, (0, 1): 1, (-1, 0): 2, (0, -1): 3}
    while edges:
        start, end = min(edges)
        ring = [start]
        a, b = start, end
        while True:
            edges.remove((a, b))
            outgoing[a].remove(b)
            ring.append(b)
            if b == start:
                break
            direction = directions[(b[0] - a[0], b[1] - a[1])]
            def priority(c):
                turn = (directions[(c[0] - b[0], c[1] - b[1])] - direction) % 4
                return {1: 0, 0: 1, 3: 2, 2: 3}[turn]
            if not outgoing[b]:
                raise MapError("Open room boundary")
            a, b = b, min(outgoing[b], key=priority)
        # Remove collinear vertices, preserving exact corners and hole winding.
        points = ring[:-1]
        simple = []
        for i, point in enumerate(points):
            prev, nxt = points[i - 1], points[(i + 1) % len(points)]
            if ((point[0] - prev[0]) * (nxt[1] - point[1])
                    != (point[1] - prev[1]) * (nxt[0] - point[0])):
                simple.append(list(point))
        rings.append(simple + [simple[0]])
    return rings


def geometry(data: dict, room_info: dict | None = None) -> dict:
    """Export native coordinates, exact raster-derived room rings and occupied cells.

    room_id comes ONLY from the explicit grid_id -> room_id table. Ambiguous
    labels are preserved with room_id=None, never guessed from pixel values.
    Millimetre units follow the Xiaomi JSON protocol; true north is unknown.
    """
    width, height, cells = grid_data(data)
    try:
        resolution = float(data["resolution"])
        ox, oy = float(data["origin_x"]), float(data["origin_y"])
        if resolution <= 0 or not all(math.isfinite(v) for v in (resolution, ox, oy)):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise MapError("Invalid map coordinate metadata") from None
    mapping = defaultdict(set)
    for row in data.get("map_room_info", []):
        mapping[row["grid_id"]].add(row["room_id"])
    names = {row["id"]: row.get("room_name", "") for row in data.get("room_attrs", [])}
    # Property names may be stale: only use them when caller establishes map identity.
    property_rooms = (room_info or {}).get("rooms", [])
    property_ids = {row["id"] for row in property_rooms}
    property_map_matches = (room_info or {}).get("map_uid") == data.get("map_id")
    if property_map_matches:
        for row in property_rooms:
            if row.get("name"):
                names[row["id"]] = row["name"]
    masks = defaultdict(set)
    occupied = []
    for index, value in enumerate(cells):
        cell = (index % width, index // width)
        if 3 <= value <= 63:
            masks[value].add(cell)
        elif value > 63:
            occupied.append(list(cell))
    rooms = []
    used_ids = [next(iter(ids)) for ids in mapping.values() if len(ids) == 1]
    for label, mask in sorted(masks.items()):
        ids = mapping[label]
        rid = next(iter(ids)) if len(ids) == 1 else None
        if used_ids.count(rid) != 1 or rid == 0:
            rid = None
        rings = _rings(mask)
        rooms.append({
            "grid_id": label, "room_id": rid, "name": names.get(rid, ""),
            "cell_count": len(mask), "rings_grid": rings,
            "rings_mm": [[[ox + x * resolution, oy + y * resolution] for x, y in ring]
                         for ring in rings],
        })
    return {
        "format": "mihome-x20-map-geometry-v1", "map_id": data.get("map_id"),
        "coordinates": {"unit": "mm", "unit_basis": "Xiaomi JSON protocol; not surveyed",
                        "resolution": resolution, "origin": [ox, oy],
                        "size_cells": [width, height], "row_direction": "+y",
                        "png_y": "height - 1 - row", "north": None,
                        "yaw_unit": "unverified; preserved in decoded JSON",
                        "rings": "closed; outer CCW, holes CW; native axes"},
        "rooms": rooms, "occupied_cells_grid": occupied,
        "occupancy_note": "Values >63: occupied/wall class; not semantic fixed obstacles",
        "robot": data.get("position"),
        "dock": {k: data.get(k) for k in ("have_pile", "pile_x", "pile_y", "pile_yaw")},
        "map_3d_info": data.get("map_3d_info"),
        "room_info_comparison": {
            "map_uid_matches_map_id": property_map_matches,
            "room_ids_match": ({r["room_id"] for r in rooms} == property_ids)
                              if room_info else None,
            "warning": "Matching room IDs alone do not prove map identity",
        },
    }


def render_png(data: dict, scale: int = 4) -> bytes:
    """Render a static occupancy/room PNG using only the standard library.

    No smoothing, rotation or geometry inference. Positions and vendor line
    data are exported separately; this PNG shows the raster exactly.
    """
    width, height, cells = grid_data(data)
    if type(scale) is not int or not 1 <= scale <= 8 or width * height * scale**2 > 32_000_000:
        raise MapError("PNG scale or image size exceeds limit")
    palette = [(129, 181, 201), (236, 188, 123), (172, 192, 143), (191, 162, 199),
               (217, 150, 149), (143, 171, 211)]
    def color(value):
        if value == 0:
            return (248, 247, 244)
        if value in (1, 2):
            return (221, 226, 230)
        if value <= 63:
            return palette[(value - 3) % len(palette)]
        return (53, 65, 76)
    rows = bytearray()
    for y in reversed(range(height)):
        row = b"\0" + b"".join(bytes(color(v)) * scale for v in cells[y * width:(y + 1) * width])
        rows.extend(row * scale)
    def chunk(kind, payload):
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width * scale, height * scale, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(rows))) + chunk(b"IEND", b""))
