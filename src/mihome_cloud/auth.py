"""Interactive Xiaomi authentication with CAPTCHA + 2FA support.

Handles the full Xiaomi SSO login flow including CAPTCHA image display
and email-based 2FA verification. Saves auth state for reuse.

Usage:
    from mihome_cloud.auth import interactive_login

    state = interactive_login("user@example.com", "password", country="de")
    # state is a dict with user_id, ssecurity, service_token, client_id
    # Save it to a file for reuse with MiHomeCloud.restore_auth_state()

Protocol adapted from PiotrMachowski/Xiaomi-cloud-tokens-extractor (MIT).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import random
import string
import tempfile
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests
from Crypto.Cipher import ARC4

logger = logging.getLogger(__name__)

SERVERS = ["cn", "de", "us", "ru", "tw", "sg", "in", "i2"]


def _generate_agent():
    agent_id = "".join(chr(random.randint(65, 69)) for _ in range(13))
    rand = "".join(chr(random.randint(97, 122)) for _ in range(18))
    return f"{rand}-{agent_id} APP/com.xiaomi.mihome APPV/10.5.201"


def _generate_device_id():
    return "".join(random.choices(string.ascii_lowercase, k=6))


def _to_json(text):
    return json.loads(text.replace("&&&START&&&", ""))


def _b64pad(s):
    return s + "=" * ((4 - len(s) % 4) % 4)


def _encrypt_rc4(password, payload):
    r = ARC4.new(base64.b64decode(_b64pad(password)))
    r.encrypt(bytes(1024))
    return base64.b64encode(r.encrypt(payload.encode())).decode()


def _decrypt_rc4(password, payload):
    r = ARC4.new(base64.b64decode(_b64pad(password)))
    r.encrypt(bytes(1024))
    return r.encrypt(base64.b64decode(_b64pad(payload)))


def _signed_nonce(ssecurity, nonce):
    h = hashlib.sha256(base64.b64decode(_b64pad(ssecurity)) + base64.b64decode(_b64pad(nonce)))
    return base64.b64encode(h.digest()).decode()


def _generate_nonce():
    nonce_bytes = os.urandom(8) + int(time.time() * 1000 / 60000).to_bytes(4, "big")
    return base64.b64encode(nonce_bytes).decode()


def _enc_signature(url, method, snonce, params):
    parts = [method.upper(), url.split("com")[1].replace("/app/", "/")]
    for k, v in params.items():
        parts.append(f"{k}={v}")
    parts.append(snonce)
    return base64.b64encode(hashlib.sha1("&".join(parts).encode()).digest()).decode()


def _enc_params(url, method, snonce, nonce, params, ssecurity):
    params["rc4_hash__"] = _enc_signature(url, method, snonce, params)
    for k, v in list(params.items()):
        params[k] = _encrypt_rc4(snonce, str(v))
    params["signature"] = _enc_signature(url, method, snonce, params)
    params["ssecurity"] = ssecurity
    params["_nonce"] = nonce
    return params


class XiaomiAuth:
    """Interactive Xiaomi SSO authentication with CAPTCHA and 2FA support.

    Example::

        auth = XiaomiAuth()
        if auth.login("user@example.com", "password"):
            state = auth.get_state()
            # Save state to file for MiHomeCloud.restore_auth_state()
    """

    def __init__(self):
        self.agent = _generate_agent()
        self.device_id = _generate_device_id()
        self.session = requests.Session()
        self.ssecurity = None
        self.user_id = None
        self.service_token = None

    def get_state(self) -> dict[str, str]:
        """Export auth state for persistence.

        Save this dict to a JSON file. Pass it to
        ``MiHomeCloud.restore_auth_state()`` to skip re-authentication.
        """
        return {
            "user_id": self.user_id or "",
            "ssecurity": self.ssecurity or "",
            "service_token": self.service_token or "",
            "client_id": self.device_id,
        }

    def login(self, username: str, password: str) -> bool:
        """Run the full 3-step login flow with CAPTCHA and 2FA handling.

        Returns True on success. On failure, prints diagnostics to stdout.
        """
        headers = {"User-Agent": self.agent, "Content-Type": "application/x-www-form-urlencoded"}

        self.session.cookies.set("sdkVersion", "accountsdk-18.8.15", domain="mi.com")
        self.session.cookies.set("sdkVersion", "accountsdk-18.8.15", domain="xiaomi.com")
        self.session.cookies.set("deviceId", self.device_id, domain="mi.com")
        self.session.cookies.set("deviceId", self.device_id, domain="xiaomi.com")

        # Step 1: Get _sign
        resp = self.session.get(
            "https://account.xiaomi.com/pass/serviceLogin?sid=xiaomiio&_json=true",
            headers=headers, cookies={"userId": username},
        )
        data = _to_json(resp.text)
        if resp.status_code != 200 or "_sign" not in data:
            if data.get("ssecurity"):
                self.ssecurity = data["ssecurity"]
                self.user_id = str(data.get("userId", ""))
                self.service_token = data.get("serviceToken") or self.session.cookies.get("serviceToken")
                return bool(self.service_token)
            print(f"Step 1 failed: {data}")
            return False

        sign = data["_sign"]

        # Step 2: Submit credentials
        fields = {
            "sid": "xiaomiio",
            "hash": hashlib.md5(password.encode()).hexdigest().upper(),
            "callback": "https://sts.api.io.mi.com/sts",
            "qs": "%3Fsid%3Dxiaomiio%26_json%3Dtrue",
            "user": username,
            "_sign": sign,
            "_json": "true",
        }
        resp = self.session.post(
            "https://account.xiaomi.com/pass/serviceLoginAuth2",
            headers=headers, params=fields, allow_redirects=False,
        )
        data = _to_json(resp.text)

        # Handle CAPTCHA
        if "captchaUrl" in data and data["captchaUrl"]:
            captcha_url = data["captchaUrl"]
            if captcha_url.startswith("/"):
                captcha_url = "https://account.xiaomi.com" + captcha_url
            print(f"\nCAPTCHA required. Open this URL in your browser:")
            print(f"  {captcha_url}")
            try:
                img_resp = self.session.get(captcha_url)
                if img_resp.status_code == 200:
                    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                    tmp.write(img_resp.content)
                    tmp.close()
                    print(f"  Or view saved file: {tmp.name}")
            except Exception:
                pass

            captcha_code = input("\nEnter CAPTCHA text: ").strip()
            if not captcha_code:
                return False
            fields["captCode"] = captcha_code
            resp = self.session.post(
                "https://account.xiaomi.com/pass/serviceLoginAuth2",
                headers=headers, params=fields, allow_redirects=False,
            )
            data = _to_json(resp.text)
            if data.get("code") == 87001:
                print("Invalid CAPTCHA.")
                return False

        # Handle 2FA
        if "notificationUrl" in data:
            if data.get("userId"):
                self.user_id = str(data["userId"])
            return self._handle_2fa(data["notificationUrl"], headers)

        if "ssecurity" not in data or len(str(data.get("ssecurity", ""))) < 4:
            print(f"Step 2 failed: {data}")
            return False

        self.ssecurity = data["ssecurity"]
        self.user_id = str(data.get("userId", ""))
        location = data.get("location")
        if not location:
            print("No redirect location.")
            return False

        # Step 3: Follow redirect to get serviceToken
        resp = self.session.get(location, headers=headers)
        self.service_token = resp.cookies.get("serviceToken")
        if not self.service_token:
            print("Step 3 failed: no serviceToken.")
            return False

        return True

    def _handle_2fa(self, notification_url: str, headers: dict) -> bool:
        """Handle email-based 2FA verification."""
        print("\n2FA verification required. A code will be sent to your email.")

        self.session.get(notification_url, headers=headers)
        context = parse_qs(urlparse(notification_url).query).get("context", [""])[0]

        self.session.get(
            "https://account.xiaomi.com/identity/list",
            params={"sid": "xiaomiio", "context": context, "_locale": "en_US"},
            headers=headers,
        )

        self.session.post(
            "https://account.xiaomi.com/identity/auth/sendEmailTicket",
            params={"_dc": str(int(time.time() * 1000)), "sid": "xiaomiio", "context": context, "mask": "0", "_locale": "en_US"},
            data={"retry": "0", "icode": "", "_json": "true", "ick": self.session.cookies.get("ick", "")},
            headers=headers,
        )

        code = input("\nEnter the 2FA code from your email: ").strip()
        if not code:
            return False

        resp = self.session.post(
            "https://account.xiaomi.com/identity/auth/verifyEmail",
            params={"_flag": "8", "_json": "true", "sid": "xiaomiio", "context": context, "mask": "0", "_locale": "en_US"},
            data={"_flag": "8", "ticket": code, "trust": "false", "_json": "true", "ick": self.session.cookies.get("ick", "")},
            headers=headers,
        )
        if resp.status_code != 200:
            print(f"2FA verification failed: {resp.status_code}")
            return False

        try:
            data = _to_json(resp.text)
            location = data.get("location")
        except Exception:
            location = None

        if location:
            # Follow redirect chain to get ssecurity + serviceToken
            # Chain: identity/result/check → serviceLoginAuth2/end → sts
            if "identity/result/check" in location:
                resp = self.session.get(location, headers=headers, allow_redirects=False)
                end_url = resp.headers.get("Location", "")
            else:
                end_url = location

            if end_url:
                resp = self.session.get(end_url, headers=headers, allow_redirects=False)
                if resp.status_code == 200 and "Tips" in resp.text:
                    resp = self.session.get(end_url, headers=headers, allow_redirects=False)

                # ssecurity is in the extension-pragma header
                ext_pragma = resp.headers.get("extension-pragma")
                if ext_pragma:
                    try:
                        ep = json.loads(ext_pragma)
                        if ep.get("ssecurity"):
                            self.ssecurity = ep["ssecurity"]
                    except Exception:
                        pass

                # Follow to STS for serviceToken cookie
                import re
                sts_url = resp.headers.get("Location", "")
                if not sts_url:
                    m = re.search(r'https://sts\.api\.io\.mi\.com/sts[^\s"\']*', resp.text)
                    if m:
                        sts_url = m.group(0)
                if sts_url:
                    resp = self.session.get(sts_url, headers=headers, allow_redirects=True)
                    self.service_token = self.session.cookies.get("serviceToken", domain=".sts.api.io.mi.com")
                    if not self.service_token:
                        self.service_token = self.session.cookies.get("serviceToken")

        if not self.service_token:
            self.service_token = self.session.cookies.get("serviceToken")

        return bool(self.service_token and self.ssecurity)

    def get_devices(self, country: str) -> list[dict]:
        """Fetch device list to verify authentication works."""
        url = f"https://{'api' if country == 'cn' else country + '.api'}.io.mi.com/app/home/device_list"
        nonce = _generate_nonce()
        snonce = _signed_nonce(self.ssecurity, nonce)
        params = {"data": json.dumps({"getVirtualModel": False, "getHuamiDevices": 0})}
        enc = _enc_params(url, "POST", snonce, nonce, params, self.ssecurity)

        headers = {
            "User-Agent": self.agent,
            "Accept-Encoding": "identity",
            "x-xiaomi-protocal-flag-cli": "PROTOCAL-HTTP2",
            "Content-Type": "application/x-www-form-urlencoded",
            "MIOT-ENCRYPT-ALGORITHM": "ENCRYPT-RC4",
        }
        cookies = {
            "userId": str(self.user_id),
            "yetAnotherServiceToken": self.service_token,
            "serviceToken": self.service_token,
            "locale": "en_US",
            "channel": "MI_APP_STORE",
        }
        resp = self.session.post(url, headers=headers, cookies=cookies, data=enc)
        dec = _decrypt_rc4(_signed_nonce(self.ssecurity, enc["_nonce"]), resp.text)
        result = json.loads(dec)
        return result.get("result", {}).get("list", [])


def interactive_login(
    username: str,
    password: str,
    country: str = "de",
    save_to: str | None = None,
) -> dict[str, str]:
    """Run interactive login and return auth state.

    Handles CAPTCHA (shows URL + saves image) and 2FA (email code prompt).

    Args:
        username: Xiaomi account email or phone number.
        password: Xiaomi account password.
        country: Server region (de, us, cn, sg, etc.)
        save_to: Optional path to save auth state JSON file.

    Returns:
        Auth state dict for use with MiHomeCloud.restore_auth_state().

    Raises:
        RuntimeError: If login fails.

    Example::

        from mihome_cloud.auth import interactive_login

        state = interactive_login("user@example.com", "password", country="de",
                                  save_to="auth_state.json")
        # state = {"user_id": "...", "ssecurity": "...", "service_token": "...", "client_id": "..."}
    """
    auth = XiaomiAuth()
    if not auth.login(username, password):
        raise RuntimeError("Login failed")

    state = auth.get_state()

    if save_to:
        import json as _json
        with open(save_to, "w") as f:
            _json.dump(state, f, indent=2)
        print(f"Auth state saved to {save_to}")

    # Verify
    try:
        devices = auth.get_devices(country)
        print(f"Authenticated. Found {len(devices)} device(s):")
        for d in devices:
            online = "online" if d.get("isOnline") else "offline"
            print(f"  - {d.get('name', '?')} ({d.get('model', '?')}, {online})")
    except Exception as e:
        print(f"Device listing failed (auth state saved, may still work): {e}")

    return state
