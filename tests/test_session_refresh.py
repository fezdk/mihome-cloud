"""Offline checks for Xiaomi account-session renewal."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest
from requests.cookies import RequestsCookieJar

from mihome_cloud import MiHomeCloud
from mihome_cloud.auth import XiaomiAuth
import mihome_cloud.client as cloud_module


class FakeSession:
    def __init__(self, account_response, service_response):
        self.account_response = account_response
        self.service_response = service_response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.account_response if len(self.calls) == 1 else self.service_response


def _client() -> MiHomeCloud:
    client = MiHomeCloud("user@example.invalid", "secret", client_id="stable-device-id")
    client.restore_auth_state({
        "user_id": "123", "ssecurity": "old-security", "service_token": "old-service",
        "pass_token": "old-pass", "client_id": "stable-device-id",
        "session_refreshed_at": time.time() - 31 * 86400,
    })
    return client


def test_refresh_uses_pass_token_and_rotates_matching_service_credentials():
    client = _client()
    account = SimpleNamespace(status_code=200, text="&&&START&&&" + json.dumps({
        "code": 0, "userId": "123", "passToken": "new-pass", "ssecurity": "new-security",
        "nonce": "nonce", "location": "https://sts.api.io.mi.com/sts?sid=xiaomiio",
    }))
    service = SimpleNamespace(status_code=200, cookies={"serviceToken": "new-service"})
    session = FakeSession(account, service)
    client._session = session

    assert client.refresh_if_due() is True

    state = client.get_auth_state()
    assert state["service_token"] == "new-service"
    assert state["ssecurity"] == "new-security"
    assert state["pass_token"] == "new-pass"
    assert state["session_refreshed_at"] > time.time() - 5
    assert session.calls[0][1]["cookies"]["passToken"] == "old-pass"
    assert "clientSign=" in session.calls[1][0]
    assert all("secret" not in str(call) for call in session.calls)
    assert client.refresh_if_due() is False


def test_rejected_refresh_preserves_previous_session():
    client = _client()
    before = client.get_auth_state()
    client._session = FakeSession(
        SimpleNamespace(status_code=200, text='&&&START&&&{"code": 70016}'),
        None,
    )

    with pytest.raises(RuntimeError, match="manual re-authentication"):
        client.refresh_session()

    assert client.get_auth_state() == before
    assert len(client._session.calls) == 1


def test_scheduled_failure_is_throttled_for_one_hour():
    client = _client()
    client._session = FakeSession(
        SimpleNamespace(status_code=200, text='&&&START&&&{"code": 70016}'),
        None,
    )
    with pytest.raises(RuntimeError, match="manual re-authentication"):
        client.refresh_if_due()
    assert client.refresh_if_due() is False
    assert len(client._session.calls) == 1


def test_legacy_state_stays_valid_without_proactive_refresh():
    client = MiHomeCloud("user@example.invalid", "secret")
    client.restore_auth_state({"user_id": "123", "ssecurity": "old-security",
                               "service_token": "old-service", "client_id": "stable-device-id"})
    assert client.is_logged_in
    assert client.refresh_if_due() is False


def test_rpc_retries_at_most_once_after_rejection(monkeypatch):
    client = _client()
    responses = [SimpleNamespace(status_code=401, text="SERVICETOKEN_EXPIRED"),
                 SimpleNamespace(status_code=401, text="SERVICETOKEN_EXPIRED")]
    client._session = SimpleNamespace(post=lambda *_args, **_kwargs: responses.pop(0))
    refreshed = []
    monkeypatch.setattr(client, "refresh_session", lambda: refreshed.append(True))
    monkeypatch.setattr(cloud_module, "_enc_params", lambda *_args: {"_nonce": "unused"})
    monkeypatch.setattr(cloud_module, "_signed_nonce", lambda *_args: "unused")

    with pytest.raises(RuntimeError, match="rejected the renewed session"):
        client._rpc("https://de.api.io.mi.com/app/test", {})

    assert refreshed == [True]
    assert responses == []


def test_rpc_renews_with_pass_token_without_password_login(monkeypatch):
    client = _client()
    responses = [SimpleNamespace(status_code=401, text="SERVICETOKEN_EXPIRED"),
                 SimpleNamespace(status_code=200, text="encrypted")]
    client._session = SimpleNamespace(post=lambda *_args, **_kwargs: responses.pop(0))
    renewed = []
    monkeypatch.setattr(client, "refresh_session", lambda: renewed.append(True))
    monkeypatch.setattr(client, "login", lambda: pytest.fail("password login was used"))
    monkeypatch.setattr(cloud_module, "_enc_params", lambda *_args: {"_nonce": "unused"})
    monkeypatch.setattr(cloud_module, "_signed_nonce", lambda *_args: "unused")
    monkeypatch.setattr(cloud_module, "_rc4_decrypt", lambda *_args: b'{"code":0}')

    assert client._rpc("https://de.api.io.mi.com/app/test", {}) == {"code": 0}
    assert renewed == [True]
    assert responses == []


def test_interactive_auth_state_contains_captured_account_session():
    auth = XiaomiAuth()
    auth._capture_pass_token({"passToken": "private-pass"})
    auth.service_token = "service"
    auth.ssecurity = "security"
    auth.user_id = "123"
    state = auth.get_state()
    assert state["pass_token"] == "private-pass"
    assert state["session_refreshed_at"] > time.time() - 5


def test_password_login_captures_pass_token_for_later_renewal():
    class LoginSession:
        def __init__(self):
            self.cookies = RequestsCookieJar()
            self.get_count = 0

        def get(self, _url, **_kwargs):
            self.get_count += 1
            if self.get_count == 1:
                return SimpleNamespace(text='&&&START&&&{"_sign":"sign"}')
            return SimpleNamespace(cookies={"serviceToken": "service"})

        def post(self, _url, **_kwargs):
            return SimpleNamespace(text="&&&START&&&" + json.dumps({
                "location": "https://sts.api.io.mi.com/sts", "userId": "123",
                "ssecurity": "security", "passToken": "account-session",
            }))

    client = MiHomeCloud("user@example.invalid", "secret")
    client._session = LoginSession()
    client.login()
    state = client.get_auth_state()
    assert state["pass_token"] == "account-session"
    assert state["service_token"] == "service"
    assert state["session_refreshed_at"] > time.time() - 5
