"""Xiaomi MiHome cloud client — SSO auth + RC4-encrypted RPC for MIoT devices.

Protocol extracted and simplified from the Tasshack/dreame-vacuum project.
Only two external dependencies: requests + pycryptodome.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import random
import string
import time
from typing import Any

import requests
from Crypto.Cipher import ARC4

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Android-7.1.1-1.0.0-ONEPLUS A3010-136-{cid} "
    "APP/xiaomi.smarthome APPV/62830"
)


def _generate_client_id() -> str:
    """Generate a random 16-char client ID."""
    return "".join(random.choices(string.ascii_lowercase, k=16))


def _generate_nonce() -> str:
    """Generate a nonce from random bytes + minute-granularity timestamp."""
    b = (random.getrandbits(64) - 2**63).to_bytes(8, "big", signed=True)
    millis = int(round(time.time() * 1000))
    part2 = int(millis / 60000)
    b += part2.to_bytes(max(1, (part2.bit_length() + 7) // 8), "big")
    return base64.b64encode(b).decode()


def _signed_nonce(ssecurity: str, nonce: str) -> str:
    """SHA-256(ssecurity + nonce) as base64."""
    h = hashlib.sha256(base64.b64decode(ssecurity) + base64.b64decode(nonce))
    return base64.b64encode(h.digest()).decode()


def _rc4_encrypt(key_b64: str, plaintext: str) -> str:
    """RC4-encrypt with 1024-byte keystream skip."""
    r = ARC4.new(base64.b64decode(key_b64))
    r.encrypt(bytes(1024))
    return base64.b64encode(r.encrypt(plaintext.encode())).decode()


def _rc4_decrypt(key_b64: str, ciphertext_b64: str) -> bytes:
    """RC4-decrypt with 1024-byte keystream skip."""
    r = ARC4.new(base64.b64decode(key_b64))
    r.encrypt(bytes(1024))
    return r.encrypt(base64.b64decode(ciphertext_b64))


def _enc_signature(url: str, method: str, snonce: str, params: dict) -> str:
    """SHA-1 signature over method + path + params + signed_nonce."""
    parts = [method.upper(), url.split("com")[1].replace("/app/", "/")]
    for k, v in params.items():
        parts.append(f"{k}={v}")
    parts.append(snonce)
    return base64.b64encode(hashlib.sha1("&".join(parts).encode()).digest()).decode()


def _enc_params(
    url: str, method: str, snonce: str, nonce: str, params: dict, ssecurity: str
) -> dict:
    """Encrypt all params with RC4 and sign."""
    params["rc4_hash__"] = _enc_signature(url, method, snonce, params)
    encrypted = {}
    for k, v in params.items():
        encrypted[k] = _rc4_encrypt(snonce, str(v))
    encrypted["signature"] = _enc_signature(url, method, snonce, encrypted)
    encrypted["ssecurity"] = ssecurity
    encrypted["_nonce"] = nonce
    return encrypted


def _parse_response(text: str) -> dict:
    """Parse Xiaomi JSON response (strips &&&START&&& prefix)."""
    return json.loads(text.replace("&&&START&&&", ""))


class MiHomeCloud:
    """Xiaomi MiHome cloud client for MIoT device control.

    Authenticates via Xiaomi SSO and sends RC4-encrypted RPC calls
    to the MiHome cloud API. Works with any MIoT-compatible device
    (vacuums, air purifiers, lights, sensors, etc.).

    Args:
        username: Xiaomi account email or phone number.
        password: Xiaomi account password.
        country: Server region code (e.g. "de", "us", "cn", "sg", "in").
            Must match the region in your Mi Home app.
        client_id: Optional persistent client ID. Auto-generated if not provided.
            Persisting this across sessions avoids triggering 2FA repeatedly.

    Example::

        cloud = MiHomeCloud("user@example.com", "password", country="de")
        cloud.login()

        # List all devices
        for device in cloud.get_devices():
            print(device["did"], device["model"], device["name"])

        # Read vacuum battery level (siid=3, piid=1)
        props = cloud.get_properties("device_id", [(3, 1)])
        print(f"Battery: {props[(3, 1)]}%")

        # Start cleaning (siid=2, aiid=1)
        cloud.action("device_id", siid=2, aiid=1)
    """

    def __init__(
        self,
        username: str,
        password: str,
        country: str = "de",
        client_id: str | None = None,
    ):
        self._username = username
        self._password = password
        self._country = country
        self._client_id = client_id or _generate_client_id()

        self._user_id: str | None = None
        self._ssecurity: str | None = None
        self._service_token: str | None = None
        self._session = requests.Session()

        self._base_url = (
            "https://api.io.mi.com/app"
            if country == "cn"
            else f"https://{country}.api.io.mi.com/app"
        )

    @property
    def is_logged_in(self) -> bool:
        """Whether the client has a valid service token."""
        return self._service_token is not None

    @property
    def user_id(self) -> str | None:
        """The Xiaomi user ID (set after login)."""
        return self._user_id

    def get_auth_state(self) -> dict[str, str]:
        """Export auth state for persistence between restarts.

        Save the returned dict to a file and pass it to
        ``restore_auth_state()`` on the next run to skip re-authentication.
        """
        return {
            "user_id": self._user_id or "",
            "ssecurity": self._ssecurity or "",
            "service_token": self._service_token or "",
            "client_id": self._client_id,
        }

    def restore_auth_state(self, state: dict[str, str]) -> None:
        """Restore auth state from a previous session.

        If the token has expired, the next RPC call will automatically
        trigger re-authentication.
        """
        self._user_id = state.get("user_id") or None
        self._ssecurity = state.get("ssecurity") or None
        self._service_token = state.get("service_token") or None
        self._client_id = state.get("client_id", self._client_id)

    def login(self) -> None:
        """Authenticate with Xiaomi SSO.

        Three-step flow:
        1. Get CSRF token from account.xiaomi.com
        2. Submit credentials (MD5-hashed password)
        3. Follow redirect to obtain serviceToken

        Raises:
            RuntimeError: If login fails, 2FA is required, or CAPTCHA is triggered.
        """
        ua = _USER_AGENT.format(cid=self._client_id)
        headers = {
            "User-Agent": ua,
            "Content-Type": "application/x-www-form-urlencoded",
        }

        for domain in ["mi.com", "xiaomi.com"]:
            self._session.cookies.set("sdkVersion", "3.8.6", domain=domain)
            self._session.cookies.set("deviceId", self._client_id, domain=domain)

        # Step 1: Get _sign token
        resp = self._session.get(
            "https://account.xiaomi.com/pass/serviceLogin",
            params={"sid": "xiaomiio", "_json": "true"},
            headers=headers,
            timeout=15,
        )
        data = _parse_response(resp.text)
        if data.get("code") == 0 and data.get("serviceToken"):
            self._service_token = data["serviceToken"]
            self._user_id = str(data.get("userId", ""))
            self._ssecurity = data.get("ssecurity", "")
            logger.info("MiHome cloud: reused existing session")
            return

        sign = data.get("_sign")
        if not sign:
            raise RuntimeError(f"Login step 1 failed: {data}")

        # Step 2: Submit credentials
        password_hash = hashlib.md5(self._password.encode()).hexdigest().upper()
        resp = self._session.post(
            "https://account.xiaomi.com/pass/serviceLoginAuth2",
            params={"_json": "true"},
            headers=headers,
            data={
                "user": self._username,
                "hash": password_hash,
                "callback": "https://sts.api.io.mi.com/sts",
                "sid": "xiaomiio",
                "qs": "%3Fsid%3Dxiaomiio%26_json%3Dtrue",
                "_sign": sign,
            },
            timeout=15,
        )
        data = _parse_response(resp.text)

        if "notificationUrl" in data:
            raise RuntimeError(
                "2FA required. Approve the login in your Mi Home app, "
                "then call login() again within 60 seconds."
            )
        if "captchaUrl" in data:
            raise RuntimeError("CAPTCHA required. Try again later.")

        location = data.get("location")
        self._user_id = str(data.get("userId", ""))
        self._ssecurity = data.get("ssecurity", "")

        if not location or not self._ssecurity:
            raise RuntimeError(f"Login step 2 failed: {data}")

        # Step 3: Follow redirect to get serviceToken
        resp = self._session.get(location, headers=headers, timeout=15)
        self._service_token = resp.cookies.get("serviceToken")

        if not self._service_token:
            raise RuntimeError("Login step 3 failed: no serviceToken in cookies")

        logger.info("MiHome cloud: logged in as user %s", self._user_id)

    def _rpc(self, url: str, data: dict) -> dict:
        """Send an RC4-encrypted RPC request to the MiHome API."""
        if not self._service_token or not self._ssecurity:
            raise RuntimeError("Not logged in. Call login() first.")

        nonce = _generate_nonce()
        snonce = _signed_nonce(self._ssecurity, nonce)

        params = {"data": json.dumps(data, separators=(",", ":"))}
        enc = _enc_params(url, "POST", snonce, nonce, params, self._ssecurity)

        ua = _USER_AGENT.format(cid=self._client_id)
        headers = {
            "User-Agent": ua,
            "Accept-Encoding": "identity",
            "x-xiaomi-protocal-flag-cli": "PROTOCAL-HTTP2",
            "Content-Type": "application/x-www-form-urlencoded",
            "MIOT-ENCRYPT-ALGORITHM": "ENCRYPT-RC4",
        }
        cookies = {
            "userId": self._user_id,
            "yetAnotherServiceToken": self._service_token,
            "serviceToken": self._service_token,
            "locale": "en_US",
            "channel": "MI_APP_STORE",
        }

        resp = self._session.post(
            url, headers=headers, cookies=cookies, data=enc, timeout=15
        )

        if resp.status_code == 401 or "SERVICETOKEN_EXPIRED" in resp.text:
            logger.info("MiHome cloud: token expired, re-authenticating")
            self.login()
            return self._rpc(url, data)

        dec_nonce = _signed_nonce(self._ssecurity, enc.get("_nonce", nonce))
        decrypted = _rc4_decrypt(dec_nonce, resp.text)
        return json.loads(decrypted)

    def send(self, device_id: str, method: str, params: Any) -> dict:
        """Send a raw RPC command to a device.

        Args:
            device_id: The device DID (from ``get_devices()``).
            method: MIoT method name (e.g. "get_properties", "set_properties", "action").
            params: Method parameters (list or dict, method-dependent).

        Returns:
            The parsed JSON response from the device.
        """
        url = f"{self._base_url}/v2/home/rpc/{device_id}"
        return self._rpc(url, {"method": method, "params": params})

    def get_properties(
        self, device_id: str, props: list[tuple[int, int]]
    ) -> dict[tuple[int, int], Any]:
        """Get MIoT properties by (siid, piid) pairs.

        Args:
            device_id: The device DID.
            props: List of (service_id, property_id) tuples. Find these
                in the MIoT spec for your device at https://home.miot-spec.com.

        Returns:
            Dict mapping (siid, piid) -> value for each property that returned data.

        Example::

            # Get battery (siid=3, piid=1) and status (siid=2, piid=2)
            props = cloud.get_properties("12345", [(3, 1), (2, 2)])
            battery = props.get((3, 1))  # e.g. 85
        """
        params = [
            {"did": f"{siid}.{piid}", "siid": siid, "piid": piid}
            for siid, piid in props
        ]
        result = self.send(device_id, "get_properties", params)
        values = {}
        for item in result.get("result", []):
            siid = item.get("siid")
            piid = item.get("piid")
            if siid is not None and piid is not None:
                values[(siid, piid)] = item.get("value")
        return values

    def set_property(
        self, device_id: str, siid: int, piid: int, value: Any
    ) -> dict:
        """Set a single MIoT property.

        Args:
            device_id: The device DID.
            siid: Service ID.
            piid: Property ID.
            value: The value to set.

        Returns:
            The raw API response.
        """
        params = [
            {"did": f"{siid}.{piid}", "siid": siid, "piid": piid, "value": value}
        ]
        return self.send(device_id, "set_properties", params)

    def action(
        self, device_id: str, siid: int, aiid: int, params: list | None = None
    ) -> dict:
        """Execute a MIoT action.

        Args:
            device_id: The device DID.
            siid: Service ID.
            aiid: Action ID.
            params: Optional action parameters.

        Returns:
            The raw API response.

        Example::

            # Start vacuum cleaning (siid=2, aiid=1)
            cloud.action("12345", siid=2, aiid=1)

            # Clean specific rooms (siid=2, aiid=16)
            cloud.action("12345", siid=2, aiid=16, params=[[1, 2, 3]])
        """
        data = {
            "did": f"{siid}.{aiid}",
            "siid": siid,
            "aiid": aiid,
            "in": params or [],
        }
        return self.send(device_id, "action", data)

    def get_devices(self) -> list[dict]:
        """List all devices on the Xiaomi account.

        Returns:
            List of device dicts, each containing at least:
            - ``did``: Device ID (use this for RPC calls)
            - ``model``: Device model string (e.g. "xiaomi.vacuum.d102gl")
            - ``name``: User-assigned device name
            - ``mac``: MAC address
            - ``isOnline``: Whether device is currently online
        """
        url = f"{self._base_url}/home/device_list"
        result = self._rpc(url, {"getVirtualModel": False, "getHuamiDevices": 0})
        return result.get("result", {}).get("list", [])

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
