#!/usr/bin/env python3
"""Generate a device profile from the MIoT spec.

Fetches the MIoT specification for a device model and creates a draft
profile JSON with the correct siid/piid/aiid mappings. Status maps and
value maps need manual filling based on testing.

Usage:
    python tools/generate_profile.py xiaomi.vacuum.d102gl
    python tools/generate_profile.py dreame.vacuum.r2205 --output profiles/
    python tools/generate_profile.py --list vacuum     # List all vacuum models

The generated profile is a starting point — test it against real hardware
and fill in the status_map, value_maps, and active_statuses fields.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import requests

SPEC_INSTANCES_URL = "https://miot-spec.org/miot-spec-v2/instances?status=all"
SPEC_INSTANCE_URL = "https://miot-spec.org/miot-spec-v2/instance?type={type}"

# Known MIoT service URN patterns → semantic names
SERVICE_PATTERNS = {
    "vacuum": "vacuum",
    "battery": "battery",
    "alarm": "alarm",
    "physical-controls-locked": "physical_lock",
    "identify": "identify",
    "filter": "filter",
    "brush-cleaner": "brush",
    "indicator-light": "light",
    "air-purifier": "air_purifier",
    "environment": "environment",
    "fan": "fan",
    "humidifier": "humidifier",
    "light": "light",
}

# Known property URN patterns → semantic property names
PROPERTY_PATTERNS = {
    "status": "status",
    "fault": "fault",
    "battery-level": "battery",
    "charging-state": "charging",
    "mode": "fan_speed",
    "target-temperature": "target_temperature",
    "temperature": "temperature",
    "relative-humidity": "humidity",
    "brush-life-level": None,  # Handled by service context
    "filter-life-level": "filter_life",
    "on": "power",
    "brightness": "brightness",
    "color-temperature": "color_temperature",
}

# Known action URN patterns → semantic action names
ACTION_PATTERNS = {
    "start-sweep": "start_sweep",
    "stop-sweeping": "stop",
    "start-charge": "dock",
    "start-mop": "start_mop",
    "pause": "pause",
    "identify": "locate",
    "reset-brush-life": None,
    "reset-filter-life": None,
    "toggle": "toggle",
    "turn-on": "turn_on",
    "turn-off": "turn_off",
}


def fetch_spec(model: str) -> dict | None:
    """Fetch the MIoT spec for a device model."""
    # Find the instance type
    resp = requests.get(SPEC_INSTANCES_URL, timeout=15)
    instances = resp.json().get("instances", [])

    matches = [i for i in instances if i.get("model") == model]
    if not matches:
        print(f"Model '{model}' not found in MIoT spec registry.")
        # Try fuzzy match
        fuzzy = [i for i in instances if model in i.get("model", "")]
        if fuzzy:
            print(f"Did you mean: {', '.join(i['model'] for i in fuzzy[:5])}")
        return None

    # Use the latest version
    instance = sorted(matches, key=lambda i: i.get("version", 0), reverse=True)[0]
    spec_type = instance["type"]
    print(f"Found: {model} → {spec_type}")

    # Fetch full spec
    resp = requests.get(SPEC_INSTANCE_URL.format(type=spec_type), timeout=15)
    return resp.json()


def detect_device_type(spec: dict) -> str:
    """Detect the device type from the spec's service URNs."""
    for svc in spec.get("services", []):
        svc_type = svc.get("type", "").lower()
        if "vacuum" in svc_type:
            return "vacuum"
        if "air-purifier" in svc_type:
            return "air_purifier"
        if "light" in svc_type and "indicator" not in svc_type:
            return "light"
        if "fan" in svc_type:
            return "fan"
        if "humidifier" in svc_type:
            return "humidifier"
    return "unknown"


def extract_urn_name(urn: str) -> str:
    """Extract the semantic name from a MIoT URN.
    e.g. 'urn:miot-spec-v2:property:status:00000007:xiaomi-d102gl:1' → 'status'
    """
    parts = urn.split(":")
    if len(parts) >= 4:
        return parts[3]
    return urn


def generate_profile(spec: dict, model: str) -> dict[str, Any]:
    """Generate a draft profile from a MIoT spec."""
    device_type = detect_device_type(spec)

    properties: dict[str, dict] = {}
    actions: dict[str, dict] = {}
    consumables: list[str] = []
    status_map: dict[str, str] = {}
    capabilities: list[str] = []

    for svc in spec.get("services", []):
        siid = svc["iid"]
        svc_desc = svc.get("description", "")
        svc_urn = extract_urn_name(svc.get("type", ""))

        # Properties
        for prop in svc.get("properties", []):
            piid = prop["iid"]
            prop_desc = prop.get("description", "")
            prop_urn = extract_urn_name(prop.get("type", ""))
            access = prop.get("access", [])

            if "read" not in access:
                continue

            # Generate a semantic name
            name = _property_name(svc_urn, svc_desc, prop_urn, prop_desc, siid, piid)
            if name:
                properties[name] = {"siid": siid, "piid": piid}

                # Track consumables
                if "life" in name and "level" not in prop_urn:
                    consumables.append(name)
                elif "life-level" in prop_urn or "life" in prop_desc.lower():
                    consumables.append(name)

                # Extract value-list for status_map
                if name == "status" and prop.get("value-list"):
                    for v in prop["value-list"]:
                        status_map[str(v["value"])] = v["description"].lower().replace(" ", "_")

        # Actions
        for act in svc.get("actions", []):
            aiid = act["iid"]
            act_desc = act.get("description", "")
            act_urn = extract_urn_name(act.get("type", ""))

            name = _action_name(svc_urn, act_urn, act_desc, siid, aiid)
            if name:
                actions[name] = {"siid": siid, "aiid": aiid}

    # Detect capabilities
    if "battery" in properties:
        capabilities.append("battery")
    if consumables:
        capabilities.append("consumables")
    if any("room" in p for p in properties):
        capabilities.append("rooms")
    if any("mop" in a for a in actions):
        capabilities.append("mop")
        capabilities.append("station")
    if "fault" in properties:
        capabilities.append("fault")

    # Build active_statuses from status_map
    active_statuses = []
    for code, label in status_map.items():
        if any(w in label for w in ("sweep", "mop", "clean", "working", "wash", "remote")):
            active_statuses.append(int(code))

    error_statuses = []
    for code, label in status_map.items():
        if any(w in label for w in ("error", "paused", "fault")):
            error_statuses.append(int(code))

    profile = {
        "model": model,
        "device_type": device_type,
        "capabilities": capabilities,
        "properties": properties,
        "actions": actions,
    }

    if consumables:
        profile["consumable_properties"] = consumables

    if status_map:
        profile["status_map"] = status_map

    profile["value_maps"] = {
        "_comment": "Fill in value maps from testing (e.g. fan_speed, water_level)"
    }

    if active_statuses:
        profile["active_statuses"] = active_statuses
    if error_statuses:
        profile["error_statuses"] = error_statuses

    profile["area_divisor"] = 100  # Common default, verify with real device

    return profile


def _property_name(svc_urn: str, svc_desc: str, prop_urn: str, prop_desc: str,
                    siid: int, piid: int) -> str | None:
    """Generate a semantic name for a property."""
    # Skip device info service (siid=1 usually)
    if svc_urn == "device-information":
        return None

    # Direct URN matches
    if prop_urn in PROPERTY_PATTERNS:
        base = PROPERTY_PATTERNS[prop_urn]
        if base is None:
            return None
        # Disambiguate by service
        if base == "filter_life" and "brush" in svc_desc.lower():
            if "side" in svc_desc.lower():
                return "side_brush_life"
            return "main_brush_life"
        return base

    # Fallback: use description
    desc = prop_desc.lower().replace(" ", "_")
    if not desc or desc == "":
        return None

    # Common patterns
    if "brush_life" in desc or "brush_left" in desc:
        if "side" in svc_desc.lower():
            return "side_brush_life"
        return "main_brush_life"
    if "filter_life" in desc:
        return "filter_life"
    if "mop_life" in desc or "mop_left" in desc:
        return "mop_life"
    if "dust_bag" in desc:
        return "dust_bag_life"
    if "room" in desc and "info" in desc:
        return "room_info"
    if "clean" in desc and "area" in desc:
        return "cleaning_area"
    if "clean" in desc and "time" in desc:
        return "cleaning_time"
    if "water" in desc and ("output" in desc or "level" in desc):
        return "water_level"
    if "sweep" in desc and "mop" in desc and "type" in desc:
        return "sweep_mop_type"
    if "carpet" in desc and "boost" in desc:
        return "carpet_boost"

    return None


def _action_name(svc_urn: str, act_urn: str, act_desc: str,
                  siid: int, aiid: int) -> str | None:
    """Generate a semantic name for an action."""
    if act_urn in ACTION_PATTERNS:
        return ACTION_PATTERNS[act_urn]

    desc = act_desc.lower().replace(" ", "_")

    # Common patterns
    if "start_sweep_mop" in desc or "sweep_mop" in desc:
        return "start_sweep_mop"
    if "start_sweep" in desc and "only" not in desc:
        return "start_sweep"
    if "only_sweep" in desc or "sweep_only" in desc:
        return "start_sweep_only"
    if "start_mop" in desc and "wash" not in desc:
        return "start_mop"
    if "stop" in desc and ("charge" in desc or "go" in desc):
        return "go_charge"
    if "stop" in desc:
        return "stop"
    if "pause" in desc:
        return "pause"
    if "continue" in desc or "resume" in desc:
        return "resume"
    if "room" in desc and "sweep" in desc:
        return "clean_rooms"
    if "dust" in desc and ("arrest" in desc or "collect" in desc):
        return "start_dust_arrest"
    if "mop_wash" in desc or "wash" in desc and "mop" in svc_urn:
        return "start_mop_wash"
    if "dry" in desc:
        return "start_dry"
    if "eject" in desc:
        return "start_eject"

    return None


def list_models(filter_text: str) -> None:
    """List available models matching a filter."""
    resp = requests.get(SPEC_INSTANCES_URL, timeout=15)
    instances = resp.json().get("instances", [])

    matches = [i for i in instances if filter_text.lower() in i.get("model", "").lower()]
    models = sorted(set(i["model"] for i in matches))
    print(f"Found {len(models)} models matching '{filter_text}':")
    for m in models[:50]:
        print(f"  {m}")
    if len(models) > 50:
        print(f"  ... and {len(models) - 50} more")


def main():
    parser = argparse.ArgumentParser(description="Generate a MIoT device profile")
    parser.add_argument("model", nargs="?", help="Device model (e.g. xiaomi.vacuum.d102gl)")
    parser.add_argument("--output", "-o", help="Output directory (default: stdout)")
    parser.add_argument("--list", "-l", help="List models matching a filter")
    args = parser.parse_args()

    if args.list:
        list_models(args.list)
        return

    if not args.model:
        parser.error("Specify a model or use --list")

    spec = fetch_spec(args.model)
    if not spec:
        sys.exit(1)

    profile = generate_profile(spec, args.model)

    output = json.dumps(profile, indent=2)

    if args.output:
        from pathlib import Path
        out_dir = Path(args.output)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{args.model}.json"
        out_path.write_text(output + "\n")
        print(f"\nProfile written to {out_path}")
        print(f"Properties: {len(profile['properties'])}, Actions: {len(profile['actions'])}")
        print(f"Capabilities: {profile['capabilities']}")
        print(f"\nTODO: Fill in value_maps from real device testing")
    else:
        print(output)


if __name__ == "__main__":
    main()
