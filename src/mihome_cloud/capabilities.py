"""Reusable capability mixins for MIoT devices.

Each mixin adds a small set of methods for a specific capability.
Device type classes combine multiple mixins to build their feature set.
All mixins expect `self` to be a MiHomeDevice (or subclass) with
`get_property()`, `run_action()`, `profile`, and `model` available.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class BatteryMixin:
    """Devices with a rechargeable battery."""

    def battery_level(self) -> int:
        """Battery percentage (0-100)."""
        return self.get_property("battery") or 0

    def is_charging(self) -> bool:
        """Whether the device is currently charging."""
        val = self.get_property("charging")
        true_val = self.profile.get("value_maps", {}).get("charging_true", 1)
        return val == true_val


class ConsumablesMixin:
    """Devices with replaceable consumable parts (filters, brushes, mops)."""

    def consumables(self) -> dict[str, int]:
        """Get all consumable levels as {name: percentage_remaining}."""
        names = self.profile.get("consumable_properties", [])
        if not names:
            return {}
        result = self.get_properties(names)
        return {k: v for k, v in result.items() if v is not None}


class RoomsMixin:
    """Devices that understand room maps (vacuums, etc.)."""

    def rooms(self) -> dict[str, int]:
        """Get room name → ID mapping from the device's map.

        Returns a dict of {room_name: room_id}. Only named rooms are included.
        """
        raw = self.get_property("room_info")
        if not raw:
            return {}
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
            return {
                r["name"]: r["id"]
                for r in data.get("rooms", [])
                if r.get("name")
            }
        except (json.JSONDecodeError, TypeError, KeyError):
            logger.debug("Failed to parse room_info", exc_info=True)
            return {}

    def resolve_room_ids(self, room_names: list[str]) -> list[int]:
        """Resolve room names (or IDs) to numeric IDs.

        Accepts exact names, slugified names, partial matches, and raw int IDs.
        Raises ValueError if a room can't be resolved.
        """
        all_rooms = self.rooms()
        # Build slug → id lookup
        slug_map = {}
        for name, rid in all_rooms.items():
            slug_map[name.lower().replace(" ", "-")] = rid
            slug_map[name.lower()] = rid

        ids = []
        for r in room_names:
            if isinstance(r, int):
                ids.append(r)
                continue
            slug = r.lower().replace(" ", "-")
            rid = slug_map.get(slug)
            if rid is None:
                # Fuzzy match
                for s, i in slug_map.items():
                    if slug in s or s in slug:
                        rid = i
                        break
            if rid is None:
                raise ValueError(f"Room '{r}' not found. Available: {list(all_rooms.keys())}")
            ids.append(rid)
        return ids


class StationMixin:
    """Devices with a docking station (wash, dry, empty functions)."""

    def wash_mop(self) -> dict:
        """Start mop washing at the station."""
        return self.run_action("start_mop_wash")

    def dry_mop(self) -> dict:
        """Start mop drying at the station."""
        return self.run_action("start_dry")

    def empty_bin(self) -> dict:
        """Empty the dust bin at the station."""
        return self.run_action("start_dust_arrest")


class FaultMixin:
    """Devices that report fault/error codes."""

    def fault(self) -> str | None:
        """Get current fault as a human-readable string, or None if no fault."""
        code = self.get_property("fault")
        if not code or code == 0:
            return None
        from mihome_cloud.fault_codes import lookup_fault
        return lookup_fault(self.model, code)

    def fault_code(self) -> int:
        """Get raw fault code (0 = no fault)."""
        return self.get_property("fault") or 0

    def has_fault(self) -> bool:
        """Whether the device has an active fault."""
        code = self.get_property("fault")
        return bool(code and code != 0)

    def has_interrupted_task(self) -> bool:
        """Whether the device has an unfinished task from a previous error.

        Detected by: fault != 0 AND cleaning_area > 0 while not actively cleaning.
        """
        fault = self.get_property("fault")
        area = self.get_property("cleaning_area")
        return bool(fault and fault != 0 and area and area > 0)
