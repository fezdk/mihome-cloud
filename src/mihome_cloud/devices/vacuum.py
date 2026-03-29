"""High-level vacuum device class.

Provides a clean API for robot vacuums — status, cleaning, room control,
consumables, fault handling. All MIoT-specific details resolved via profile.

Usage::

    from mihome_cloud import MiHomeCloud
    from mihome_cloud.devices import MiHomeVacuum

    cloud = MiHomeCloud("user", "pass", country="de")
    cloud.restore_auth_state(saved_state)

    vacuum = MiHomeVacuum.from_cloud(cloud, did="1173085625")
    print(vacuum.status())          # "charging"
    print(vacuum.battery_level())   # 100
    vacuum.clean_rooms(["kitchen", "living-room"])
"""

from __future__ import annotations

import logging
from typing import Any

from mihome_cloud.device import MiHomeDevice
from mihome_cloud.capabilities import (
    BatteryMixin,
    ConsumablesMixin,
    FaultMixin,
    RoomsMixin,
    StationMixin,
)

logger = logging.getLogger(__name__)


class MiHomeVacuum(MiHomeDevice, BatteryMixin, ConsumablesMixin,
                    RoomsMixin, StationMixin, FaultMixin):
    """High-level robot vacuum API.

    Combines all relevant capabilities. Methods raise ValueError if
    the profile doesn't support a given action/property.
    """

    # ── Status ──

    def status(self) -> str:
        """Current status as a human-readable string (e.g. 'charging', 'sweeping_mopping')."""
        code = self.get_property("status")
        label = self.profile.get("status_map", {}).get(str(code), f"unknown_{code}")

        # Enrich with sweep_mop_type if actively cleaning
        active = self.profile.get("active_statuses", [])
        if code in active:
            try:
                smt = self.get_property("sweep_mop_type")
                smt_map = self.profile.get("value_maps", {}).get("sweep_mop_type", {})
                if smt and str(smt) in smt_map:
                    label = smt_map[str(smt)]
            except Exception:
                pass

        return label

    def status_code(self) -> int:
        """Raw numeric status code."""
        return self.get_property("status") or 0

    def is_busy(self) -> bool:
        """Whether the vacuum is actively cleaning or in a station operation."""
        code = self.get_property("status")
        return code in self.profile.get("active_statuses", [])

    # ── Cleaning commands ──

    def start(self) -> dict:
        """Start sweep + mop (or best available cleaning mode)."""
        for action in ("start_sweep_mop", "start_sweep", "start"):
            if action in self.profile.get("actions", {}):
                return self.run_action(action)
        raise ValueError("No start action in profile")

    def start_sweep(self) -> dict:
        """Start sweeping only (no mop)."""
        return self.run_action("start_sweep_only" if "start_sweep_only" in self.profile.get("actions", {}) else "start_sweep")

    def start_mop(self) -> dict:
        """Start mopping only."""
        return self.run_action("start_mop")

    def stop(self) -> dict:
        """Stop cleaning."""
        return self.run_action("stop")

    def pause(self) -> dict:
        """Pause cleaning."""
        return self.run_action("pause")

    def resume(self) -> dict:
        """Resume paused cleaning."""
        return self.run_action("resume")

    def dock(self) -> dict:
        """Return to charging dock."""
        for action in ("dock", "go_charge"):
            if action in self.profile.get("actions", {}):
                return self.run_action(action)
        raise ValueError("No dock action in profile")

    def locate(self) -> dict:
        """Play a sound to find the vacuum."""
        return self.run_action("locate")

    def clean_rooms(self, room_names: list[str]) -> dict:
        """Clean specific rooms by name.

        Room names are resolved to IDs via the device's room map.
        Accepts exact names, slugified names, or partial matches.
        """
        ids = self.resolve_room_ids(room_names)
        return self.run_action("clean_rooms", [ids])

    # ── Pre-command safety check ──

    def check_before_command(self) -> str | None:
        """Check if the vacuum is ready for a new cleaning command.

        Returns None if ready, or an error message explaining why not.
        """
        try:
            props = self.get_properties(["status", "fault", "cleaning_area"])
        except Exception:
            return None  # Don't block on check failure

        status = props.get("status", 0)
        fault = props.get("fault", 0)
        area = props.get("cleaning_area", 0)

        active = self.profile.get("active_statuses", [])
        if status in active:
            label = self.profile.get("status_map", {}).get(str(status), str(status))
            return f"Vacuum is already busy ({label}). Send 'stop' first."

        # Only warn about interrupted tasks if fault is actually active
        error_statuses = self.profile.get("error_statuses", [5, 15])
        if status in error_statuses and fault and fault != 0 and area and area > 0:
            area_divisor = self.profile.get("area_divisor", 100)
            fault_name = self.fault() or str(fault)
            area_m2 = area / area_divisor
            return (
                f"Vacuum has an interrupted task ({area_m2:.0f}m² done) with "
                f"active fault: {fault_name}. Send 'resume' to continue or "
                f"'stop' first then retry."
            )

        return None

    # ── Full state for polling ──

    def full_state(self) -> dict[str, Any]:
        """Get the complete device state for a poll cycle.

        Returns a flat dict suitable for a state store. Property values
        are mapped to human-readable strings where profile defines mappings.
        """
        result: dict[str, Any] = {}

        # Batch-fetch all properties
        all_names = list(self.profile.get("properties", {}).keys())
        raw = self.get_properties(all_names)

        for name, value in raw.items():
            if value is None:
                continue

            # Status — enriched with sweep_mop_type
            if name == "status":
                result["status"] = self.profile.get("status_map", {}).get(str(value), str(value))
                result["status_code"] = value
                active = self.profile.get("active_statuses", [])
                if value in active:
                    smt = raw.get("sweep_mop_type")
                    smt_map = self.profile.get("value_maps", {}).get("sweep_mop_type", {})
                    if smt and str(smt) in smt_map:
                        result["status"] = smt_map[str(smt)]
                continue

            # Fault — only report if status indicates an actual error
            if name == "fault":
                if value and value != 0:
                    status_val = raw.get("status", 0)
                    error_statuses = self.profile.get("error_statuses", [5, 15])
                    if status_val in error_statuses:
                        result["fault_code"] = value
                        from mihome_cloud.fault_codes import lookup_fault
                        result["fault"] = lookup_fault(self.model, value)
                    # else: stale fault code from previous error, don't report
                continue

            # Charging
            if name == "charging":
                true_val = self.profile.get("value_maps", {}).get("charging_true", 1)
                result["charging"] = value == true_val
                continue

            # Cleaning area
            if name == "cleaning_area":
                divisor = self.profile.get("area_divisor", 100)
                result["cleaning_area_m2"] = round(value / divisor, 1)
                continue

            # Cleaning time
            if name == "cleaning_time":
                result["cleaning_time_min"] = round(value / 60, 1)
                continue

            # Consumables
            consumables = self.profile.get("consumable_properties", [])
            if name in consumables:
                result[f"consumables/{name}"] = value
                continue

            # Room info → room list
            if name == "room_info":
                try:
                    import json
                    data = json.loads(value) if isinstance(value, str) else value
                    rooms = data.get("rooms", [])
                    count = 0
                    for r in rooms:
                        rname = r.get("name", "")
                        rid = r.get("id")
                        if rname and rid:
                            slug = rname.lower().replace(" ", "-")
                            result[f"rooms/{slug}"] = rid
                            count += 1
                    result["rooms/count"] = count
                except Exception:
                    pass
                continue

            # Value-mapped properties
            mapped = self.map_value(name, value)
            if mapped != str(value):
                result[name] = mapped
            else:
                result[name] = value

        return result
