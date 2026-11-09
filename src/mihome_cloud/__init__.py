"""mihome-cloud — Minimal Xiaomi MiHome cloud client for MIoT devices.

Access cloud-supported Xiaomi MIoT properties/actions via the Xiaomi cloud API.
Includes SSO/session reuse, RC4 RPC, a high-level X20 Pro vacuum API and opt-in
map snapshots. Map requests never attempt automatic reauthentication.

Usage:
    from mihome_cloud import MiHomeCloud

    cloud = MiHomeCloud("", "", country="de")
    cloud.restore_auth_state(saved_state)
    # Create saved_state with interactive_login() if no working session exists.

    # List devices
    devices = cloud.get_devices()

    # Get properties (by MIoT siid, piid)
    props = cloud.get_properties(device_id, [(2, 2), (3, 1)])

    # Execute action
    cloud.action(device_id, siid=2, aiid=1)

    # Persist session for next run
    state = cloud.get_auth_state()
    # ... save state to file ...

    # Restore on next run
    cloud.restore_auth_state(state)
"""

from mihome_cloud.client import MiHomeCloud
from mihome_cloud.device import MiHomeDevice
from mihome_cloud.fault_codes import lookup_fault, lookup_fault_message
from mihome_cloud.auth import interactive_login, XiaomiAuth
from mihome_cloud.devices import MiHomeVacuum
from mihome_cloud.map_api import MapInfo, MapSnapshot, VacuumMapClient, build_map_snapshot
from mihome_cloud.maps import MapError

__all__ = [
    "MiHomeCloud",
    "MiHomeDevice",
    "MiHomeVacuum",
    "VacuumMapClient",
    "MapInfo",
    "MapSnapshot",
    "MapError",
    "build_map_snapshot",
    "lookup_fault",
    "lookup_fault_message",
    "interactive_login",
    "XiaomiAuth",
]
__version__ = "0.4.0"
