"""mihome-cloud — Minimal Xiaomi MiHome cloud client for MIoT devices.

Control any Xiaomi MIoT smart home device via the Xiaomi cloud API.
Handles SSO authentication, RC4-encrypted RPC, and automatic token refresh.

Usage:
    from mihome_cloud import MiHomeCloud

    cloud = MiHomeCloud("user@example.com", "password", country="de")
    cloud.login()

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
from mihome_cloud.fault_codes import lookup_fault
from mihome_cloud.auth import interactive_login, XiaomiAuth
from mihome_cloud.devices import MiHomeVacuum

__all__ = [
    "MiHomeCloud",
    "MiHomeDevice",
    "MiHomeVacuum",
    "lookup_fault",
    "interactive_login",
    "XiaomiAuth",
]
__version__ = "0.3.0"
