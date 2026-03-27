# mihome-cloud

Minimal Xiaomi MiHome cloud client for controlling MIoT smart home devices via the Xiaomi cloud API.

Works with any MIoT-compatible device — vacuums, air purifiers, lights, sensors, etc. No local network access needed.

## Installation

```bash
pip install mihome-cloud
```

## Quick Start

```python
from mihome_cloud import MiHomeCloud

cloud = MiHomeCloud("user@example.com", "password", country="de")
cloud.login()

# List all devices on your account
for device in cloud.get_devices():
    print(f"{device['did']}: {device['name']} ({device['model']})")
```

## Usage

### Get Device Properties

Properties are identified by (service_id, property_id) pairs from the [MIoT spec](https://home.miot-spec.com).

```python
# Get vacuum battery (siid=3, piid=1) and status (siid=2, piid=2)
props = cloud.get_properties("device_id", [(3, 1), (2, 2)])
print(f"Battery: {props[(3, 1)]}%")
print(f"Status: {props[(2, 2)]}")
```

### Set a Property

```python
# Set vacuum suction level (siid=2, piid=9) to 2 (medium)
cloud.set_property("device_id", siid=2, piid=9, value=2)
```

### Execute an Action

```python
# Start vacuum cleaning (siid=2, aiid=1)
cloud.action("device_id", siid=2, aiid=1)

# Clean specific rooms (siid=2, aiid=16)
cloud.action("device_id", siid=2, aiid=16, params=[[1, 2, 3]])

# Return vacuum to dock (siid=3, aiid=1)
cloud.action("device_id", siid=3, aiid=1)
```

### Session Persistence

Save and restore auth state to avoid re-authentication on every run:

```python
import json

# After login — save state
state = cloud.get_auth_state()
with open("auth_state.json", "w") as f:
    json.dump(state, f)

# On next run — restore state
with open("auth_state.json") as f:
    state = json.load(f)

cloud = MiHomeCloud("user@example.com", "password", country="de")
cloud.restore_auth_state(state)
# No login() needed — token is reused (auto-refreshes if expired)
```

### Context Manager

```python
with MiHomeCloud("user@example.com", "password", country="de") as cloud:
    cloud.login()
    devices = cloud.get_devices()
# Session auto-closed
```

## Authentication

Uses Xiaomi SSO (account.xiaomi.com) with RC4-encrypted RPC calls. On first login, you may need to approve a 2FA prompt in the Mi Home app.

The `country` parameter must match the server region in your Mi Home app:

| Region | Code |
|--------|------|
| China | `cn` |
| Germany / EU | `de` |
| United States | `us` |
| Singapore | `sg` |
| India | `in` |
| Russia | `ru` |

## Finding MIoT Service/Property/Action IDs

Every Xiaomi device has a MIoT spec that defines its services, properties, and actions. Look up your device at [home.miot-spec.com](https://home.miot-spec.com):

1. Search for your device model (e.g. `xiaomi.vacuum.d102gl`)
2. Browse the services (e.g. service 2 = vacuum, service 3 = battery)
3. Find the property/action IDs you need

Common vacuum IDs:

| Operation | siid | piid/aiid | Type |
|-----------|------|-----------|------|
| Battery level | 3 | piid=1 | property |
| Vacuum status | 2 | piid=2 | property |
| Start cleaning | 2 | aiid=1 | action |
| Stop cleaning | 2 | aiid=2 | action |
| Return to dock | 3 | aiid=1 | action |
| Clean rooms | 2 | aiid=16 | action |

## Credits

Cloud protocol extracted and simplified from [Tasshack/dreame-vacuum](https://github.com/Tasshack/dreame-vacuum).

## License

MIT
