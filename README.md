# mihome-cloud

Minimal Xiaomi MiHome cloud client for controlling MIoT smart home devices via the Xiaomi cloud API.

Works with any MIoT-compatible device — vacuums, air purifiers, lights, sensors, etc. No local network access needed.

## Installation

```bash
pip install mihome-cloud
```

Dependencies: `requests` + `pycryptodome` (installed automatically).

## Authentication

Xiaomi requires SSO authentication, which may involve CAPTCHA and/or 2FA (email code). The library handles both.

### First-Time Setup (Interactive)

The easiest way to authenticate is using the interactive helper:

```python
from mihome_cloud.auth import interactive_login

# This will prompt for CAPTCHA/2FA if needed
state = interactive_login(
    username="your-email@example.com",
    password="your-password",
    country="de",           # Server region (see table below)
    save_to="auth_state.json",  # Saves tokens for reuse
)
```

The helper handles:
- **CAPTCHA** — shows URL to view the image + saves it locally
- **2FA** — sends email code, prompts you to enter it
- **Token extraction** — captures `serviceToken` and `ssecurity` from the full redirect chain

**Important notes:**
- Xiaomi rate-limits 2FA to 3-5 requests per day. Don't retry excessively.
- Tokens are saved immediately after auth succeeds, before device verification.
- If device listing fails but auth succeeded, the tokens are still saved and likely valid.

### Subsequent Runs (No Login Needed)

Once you have `auth_state.json`, restore the session without re-authenticating:

```python
import json
from mihome_cloud import MiHomeCloud

with open("auth_state.json") as f:
    state = json.load(f)

cloud = MiHomeCloud("your-email@example.com", "your-password", country="de")
cloud.restore_auth_state(state)
# No login() needed — token is reused and auto-refreshes on expiry

devices = cloud.get_devices()
for d in devices:
    print(f"{d['did']}: {d['name']} ({d['model']})")
```

If the token expires, the next RPC call automatically triggers re-authentication (which may hit CAPTCHA/2FA limits — so persist your tokens).

### Manual Authentication

If you prefer full control:

```python
from mihome_cloud.auth import XiaomiAuth

auth = XiaomiAuth()
if auth.login("your-email@example.com", "your-password"):
    state = auth.get_state()
    # state = {"user_id": "...", "ssecurity": "...", "service_token": "...", "client_id": "..."}

    # Verify by listing devices
    devices = auth.get_devices("de")
    for d in devices:
        print(f"  {d['name']} ({d['model']})")
```

## Usage

### Get Device Properties

Properties are identified by (service_id, property_id) pairs from the [MIoT spec](https://home.miot-spec.com).

```python
from mihome_cloud import MiHomeCloud
import json

cloud = MiHomeCloud("user@example.com", "password", country="de")
with open("auth_state.json") as f:
    cloud.restore_auth_state(json.load(f))

# Find your device ID
devices = cloud.get_devices()
device_id = devices[0]["did"]

# Get vacuum battery (siid=3, piid=1) and status (siid=2, piid=2)
props = cloud.get_properties(device_id, [(3, 1), (2, 2)])
print(f"Battery: {props[(3, 1)]}%")
print(f"Status: {props[(2, 2)]}")
```

### Set a Property

```python
# Set vacuum suction level (siid=2, piid=9) to 2 (medium)
cloud.set_property(device_id, siid=2, piid=9, value=2)
```

### Execute an Action

```python
# Start vacuum cleaning (siid=2, aiid=1)
cloud.action(device_id, siid=2, aiid=1)

# Clean specific rooms (siid=2, aiid=16)
cloud.action(device_id, siid=2, aiid=16, params=[[1, 2, 3]])

# Return vacuum to dock (siid=3, aiid=1)
cloud.action(device_id, siid=3, aiid=1)
```

### Fault Code Lookup

```python
from mihome_cloud import lookup_fault

# Xiaomi-branded vacuums use 6-digit codes
print(lookup_fault("xiaomi.vacuum.d102gl", 320004))  # "drive_wheel_error"

# Dreame-branded vacuums use codes 0-125
print(lookup_fault("dreame.vacuum.r2205", 15))  # "left_wheel_motor"

# Unknown codes return "unknown_{code}"
print(lookup_fault("xiaomi.vacuum.d102gl", 999999))  # "unknown_999999"
```

### Session Persistence

```python
import json

# After login — save state
state = cloud.get_auth_state()
with open("auth_state.json", "w") as f:
    json.dump(state, f)

# On next run — restore state (no login needed)
with open("auth_state.json") as f:
    state = json.load(f)
cloud = MiHomeCloud("user@example.com", "password", country="de")
cloud.restore_auth_state(state)
```

### Context Manager

```python
with MiHomeCloud("user@example.com", "password", country="de") as cloud:
    cloud.login()
    devices = cloud.get_devices()
# Session auto-closed
```

## Server Regions

The `country` parameter must match the region in your Mi Home app:

| Region | Code |
|--------|------|
| China | `cn` |
| Germany / EU | `de` |
| United States | `us` |
| Singapore | `sg` |
| India | `in` |
| Russia | `ru` |
| Taiwan | `tw` |

## Finding MIoT Service/Property/Action IDs

Every Xiaomi device has a MIoT spec. Look up yours at [home.miot-spec.com](https://home.miot-spec.com):

1. Search for your device model (e.g. `xiaomi.vacuum.d102gl`)
2. Browse services (e.g. service 2 = vacuum, service 3 = battery)
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

## Troubleshooting

### CAPTCHA on every login
Xiaomi triggers CAPTCHA when it sees a new `client_id`. Persist the auth state (including `client_id`) to avoid this. The `interactive_login` helper does this automatically.

### 2FA rate limited
Xiaomi allows 3-5 2FA attempts per day. If you've exceeded the limit, wait 24 hours. Once you have a valid `auth_state.json`, you won't need 2FA again until the token fully expires.

### "auth error" or "invalid signature"
The `ssecurity` and `serviceToken` must come from the same auth session. If you manually constructed `auth_state.json`, ensure all fields are from the same login. The `interactive_login` helper handles this correctly.

### Device not found
Ensure your `country` matches the region in your Mi Home app. Devices registered in the EU (`de`) won't appear on the US (`us`) server.

## Credits

Cloud protocol extracted from [Tasshack/dreame-vacuum](https://github.com/Tasshack/dreame-vacuum).

## License

MIT
