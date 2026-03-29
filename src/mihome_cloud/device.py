"""Base class for all MIoT devices.

MiHomeDevice provides generic property/action access driven by a device
profile (JSON). Subclasses add high-level methods for specific device types.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mihome_cloud.client import MiHomeCloud

logger = logging.getLogger(__name__)


class MiHomeDevice:
    """Generic MIoT device with profile-driven property and action access.

    All MIoT-specific siid/piid/aiid numbers are resolved from the profile.
    Subclasses never need to know raw MIoT IDs.

    Args:
        cloud: Authenticated MiHomeCloud client.
        did: Device ID (from cloud.get_devices()).
        model: Device model string (e.g. "xiaomi.vacuum.d102gl").
        profile: Device profile dict (loaded from JSON).
    """

    def __init__(self, cloud: MiHomeCloud, did: str, model: str, profile: dict):
        self.cloud = cloud
        self.did = did
        self.model = model
        self.profile = profile

    @classmethod
    def from_cloud(cls, cloud: MiHomeCloud, did: str, model: str | None = None,
                    profile: dict | None = None) -> "MiHomeDevice":
        """Create a device instance, auto-loading the profile if not provided."""
        if not model:
            devices = cloud.get_devices()
            for d in devices:
                if str(d.get("did")) == str(did):
                    model = d.get("model", "unknown")
                    break
            else:
                raise ValueError(f"Device {did} not found on account")

        if not profile:
            from mihome_cloud.profiles import load_profile
            profile = load_profile(model)

        return cls(cloud=cloud, did=did, model=model, profile=profile)

    # ── Property access ──

    def get_property(self, name: str) -> Any:
        """Get a single property by semantic name.

        The name is resolved to siid/piid via the profile.
        """
        spec = self.profile.get("properties", {}).get(name)
        if not spec:
            raise ValueError(f"Property '{name}' not in profile for {self.model}")
        result = self.cloud.get_properties(self.did, [(spec["siid"], spec["piid"])])
        return result.get((spec["siid"], spec["piid"]))

    def get_properties(self, names: list[str]) -> dict[str, Any]:
        """Get multiple properties by semantic name in a single API call."""
        props = self.profile.get("properties", {})
        batch = []
        name_map = {}
        for name in names:
            spec = props.get(name)
            if spec:
                key = (spec["siid"], spec["piid"])
                batch.append(key)
                name_map[key] = name

        if not batch:
            return {}

        raw = self.cloud.get_properties(self.did, batch)
        return {name_map[k]: v for k, v in raw.items() if k in name_map}

    def set_property(self, name: str, value: Any) -> dict:
        """Set a single property by semantic name."""
        spec = self.profile.get("properties", {}).get(name)
        if not spec:
            raise ValueError(f"Property '{name}' not in profile for {self.model}")
        return self.cloud.set_property(self.did, spec["siid"], spec["piid"], value)

    # ── Action access ──

    def run_action(self, name: str, params: list | None = None) -> dict:
        """Execute a named action.

        The name is resolved to siid/aiid via the profile.
        """
        spec = self.profile.get("actions", {}).get(name)
        if not spec:
            raise ValueError(f"Action '{name}' not in profile for {self.model}")
        return self.cloud.action(self.did, spec["siid"], spec["aiid"], params)

    # ── Capability discovery ──

    def has_capability(self, name: str) -> bool:
        """Check if the device profile declares a capability."""
        return name in self.profile.get("capabilities", [])

    @property
    def available_actions(self) -> list[str]:
        """List all actions defined in the profile."""
        return list(self.profile.get("actions", {}).keys())

    @property
    def available_properties(self) -> list[str]:
        """List all properties defined in the profile."""
        return list(self.profile.get("properties", {}).keys())

    # ── Value mapping ──

    def map_value(self, prop_name: str, raw_value: Any) -> str:
        """Translate a raw property value to a human-readable string.

        Uses value_maps from the profile. Returns str(raw_value) if no mapping.
        """
        maps = self.profile.get("value_maps", {})
        prop_map = maps.get(prop_name, {})
        return prop_map.get(str(raw_value), str(raw_value))

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} model={self.model} did={self.did}>"
