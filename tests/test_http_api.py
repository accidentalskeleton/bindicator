"""Offline HTTP API security and behaviour checks (no Hue or Zoho network)."""
from __future__ import annotations

import http.client
import json
import threading
from datetime import datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from bindicator import api
from bindicator.app import BindicatorError
from bindicator.controls import set_paused
from test_cli_preview import make_files
from test_bin_preview import ICS_COLLECTIONS

TOKEN = "1234567890" + "abcdefghijklmnopqrstuvwxyzABCDEF"  # Synthetic test token


class FakeOps:
    def __init__(self):
        self.actions = []
        self.errors = {}
        self.calls = 0

    def status(self):
        self.calls += 1
        return {"paused": False, "active_collection_date": None, "indicators": []}

    def next_collection(self):
        self.calls += 1
        return {
            "date": "2026-11-17", "weekday": "Tuesday",
            "collections": ["Household waste", "Garden Waste"],
            "colours": ["orange", "green"],
        }

    def bins_out(self):
        self.calls += 1
        self.actions.append(("bins-out", {}))
        return {"ok": True, "acknowledged": True, "restored": True}

    def command(self, action, body):
        self.calls += 1
        self.actions.append((action, body))
        if action in self.errors:
            raise self.errors[action]
        return {"ok": True, "action": action}


@pytest.fixture
def live_api():
    ops = FakeOps()
    with ThreadingHTTPServer(("127.0.0.1", 0), api.make_handler(ops, TOKEN)) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server.server_port, ops
        finally:
            server.shutdown()
            thread.join(timeout=3)


def request(port, method, path, *, token=TOKEN, body=None, content_type=True, host=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    headers = {}
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    if host is not None:
        headers["Host"] = host
    if body is not None and content_type:
        headers["Content-Type"] = "application/json"
    payload = json.dumps(body) if isinstance(body, dict) else body
    try:
        conn.request(method, path, body=payload, headers=headers)
        response = conn.getresponse()
        result = json.loads(response.read())
        return response.status, result, response.getheader("Cache-Control")
    finally:
        conn.close()


def test_health_requires_no_token_but_discloses_nothing(live_api):
    port, ops = live_api
    status, body, cache = request(
        port, "GET", "/api/v1/health", token=None,
    )
    assert status == 200
    assert body == {"status": "ok"}
    assert cache == "no-store"
    assert ops.calls == 0


def test_read_endpoints_require_authentication(live_api):
    port, ops = live_api
    for path in ("/api/v1/status", "/api/v1/collections/next"):
        for wrong in (None, "", TOKEN + "wrong"):
            status, result, _ = request(port, "GET", path, token=wrong)
            assert status == 401
            assert result == {"error": "Authentication required."}
    assert ops.calls == 0


def test_authorized_read_endpoints(live_api):
    port, ops = live_api
    assert request(port, "GET", "/api/v1/status")[1]["paused"] is False
    response = request(port, "GET", "/api/v1/collections/next")
    assert response[0] == 200
    assert response[1]["colours"] == ["orange", "green"]
    assert response[1]["collections"] == ["Household waste", "Garden Waste"]
    assert ops.calls == 2


@pytest.mark.parametrize("action", ["pause", "resume", "toggle", "alerts/next"])
def test_authenticated_write_actions(live_api, action):
    port, ops = live_api
    status, body, _ = request(port, "POST", "/api/v1/" + action, body={})
    assert status == 200
    assert body["action"] == action
    assert ops.actions == [(action, {})]


def test_actions_refuse_unauthenticated_calls(live_api):
    port, ops = live_api
    status, _, _ = request(
        port, "POST", "/api/v1/pause", token="wrong", body={},
    )
    assert status == 401
    assert ops.actions == []


@pytest.mark.parametrize("bad", [
    "abc", "[]", '{"broken":',
])
def test_malformed_or_nonobject_json_refused(live_api, bad):
    port, ops = live_api
    status, _, _ = request(port, "POST", "/api/v1/pause", body=bad)
    assert status == 400
    assert ops.actions == []


def test_rejects_non_json_and_oversized_body(live_api):
    port, ops = live_api
    assert request(
        port, "POST", "/api/v1/pause", body="{}", content_type=False
    )[0] == 415
    assert request(
        port, "POST", "/api/v1/pause", body="{" + "a" * 600 + "}"
    )[0] == 413
    assert ops.actions == []


def test_host_validation_prevents_dns_rebinding(live_api):
    port, ops = live_api
    status, _, _ = request(
        port, "GET", "/api/v1/health", token=None,
        host="evil.example",
    )
    assert status == 400
    assert ops.calls == 0


def test_query_parameters_and_unknown_paths_rejected(live_api):
    port, ops = live_api
    assert request(port, "GET", "/api/v1/status?secret=1")[0] == 400
    assert request(port, "POST", "/api/v1/unknown", body={})[0] == 404
    assert ops.calls == 0


def test_no_cors_headers_or_browser_cross_origin_support(live_api):
    port, _ = live_api
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        conn.request("GET", "/api/v1/health")
        r = conn.getresponse()
        assert r.getheader("Access-Control-Allow-Origin") is None
        assert r.getheader("X-Content-Type-Options") == "nosniff"
        r.read()
    finally:
        conn.close()


def test_api_operations_return_safe_generic_error_on_backend_failure(live_api):
    port, ops = live_api
    ops.errors["pause"] = BindicatorError("private secret = do not disclose")
    status, body, _ = request(port, "POST", "/api/v1/pause", body={})
    assert status == 503
    assert "private secret" not in json.dumps(body)


def test_status_reads_persisted_control_and_reminder_state(tmp_path):
    config, secrets, state = make_files(tmp_path)
    state.mkdir()
    set_paused(state, True)
    (state / "state.json").write_text(json.dumps({
        "date": "2026-11-17",
        "manual_until": "2026-11-17",
        "lights": {
            "office/lamp-uuid": {
                "applied_xy": {"x": 0.57, "y": 0.39},
                "color_name": "orange",
                "original_on": False,
            }
        },
    }))
    controller = api.BindicatorAPI(config, secrets, state)
    result = controller.status()
    assert result["paused"] is True
    assert result["active_collection_date"] == "2026-11-17"
    assert result["manual_until"] == "2026-11-17"
    assert result["indicator_count"] == 1
    assert result["indicators"] == [
        {"light": "office/lamp-uuid", "colour": "orange"}
    ]


def test_next_collection_uses_existing_calendar_matching(
    tmp_path, monkeypatch,
):
    config, secrets, state = make_files(tmp_path)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 10, 15, tzinfo=ZoneInfo("Europe/London"))

    monkeypatch.setattr(api, "datetime", FixedDatetime)
    monkeypatch.setattr(
        api.Bindicator, "calendar_data", lambda self: ICS_COLLECTIONS,
    )
    result = api.BindicatorAPI(config, secrets, state).next_collection()
    assert result == {
        "date": "2026-11-17",
        "weekday": "Tuesday",
        "collections": ["Household waste", "Garden Waste"],
        "colours": ["orange", "green"],
    }


@pytest.mark.parametrize("action, body, expected_args", [
    ("pause", {}, ["--pause"]),
    ("resume", {}, ["--resume"]),
    ("toggle", {}, ["--toggle"]),
    ("alerts/next", {}, ["--next-collection"]),
    ("alerts/next", {"seconds": 10}, ["--next-collection", "--seconds", "10"]),
])
def test_actions_delegate_to_trusted_cli_not_shell(
    tmp_path, monkeypatch, action, body, expected_args,
):
    config, secrets, state = make_files(tmp_path)
    observed = []

    def fake_run(cmd, **kwargs):
        observed.append((cmd, kwargs))
        return SimpleNamespace(returncode=0, stdout="Bindicator ACTIVE", stderr="")

    monkeypatch.setattr(api.subprocess, "run", fake_run)
    result = api.BindicatorAPI(config, secrets, state).command(action, body)
    assert result == {
        "ok": True, "action": action, "message": "Bindicator ACTIVE"
    }
    assert len(observed) == 1
    cmd, kwargs = observed[0]
    assert cmd[:3] == [api.sys.executable, "-m", "bindicator.cli"]
    assert cmd[-len(expected_args):] == expected_args
    assert kwargs["stdin"] == api.subprocess.DEVNULL
    assert kwargs["timeout"] == 90
    assert "shell" not in kwargs


@pytest.mark.parametrize("body", [
    {"seconds": 0}, {"seconds": 61}, {"seconds": True},
    {"seconds": "10"}, {"seconds": None}, {"seconds": 1, "cmd": "sh"},
])
def test_action_argument_validation_prevents_untrusted_cli_calls(
    tmp_path, monkeypatch, body,
):
    config, secrets, state = make_files(tmp_path)
    monkeypatch.setattr(
        api.subprocess, "run",
        lambda *args, **kwargs: pytest.fail("must reject before invoking CLI"),
    )
    with pytest.raises(api.APIError) as exc:
        api.BindicatorAPI(config, secrets, state).command("alerts/next", body)
    assert exc.value.status == 400


def test_mutation_failure_sanitized_for_http(tmp_path, monkeypatch):
    config, secrets, state = make_files(tmp_path)
    monkeypatch.setattr(
        api.subprocess, "run",
        lambda cmd, **kw: SimpleNamespace(
            returncode=1, stdout="", stderr="ERROR: private token here",
        ),
    )
    with pytest.raises(api.APIError) as exc:
        api.BindicatorAPI(config, secrets, state).command("pause", {})
    assert exc.value.status == 409
    assert "private token" not in exc.value.message


def test_token_file_is_required_and_validated(tmp_path):
    token_path = tmp_path / "token"
    with pytest.raises(BindicatorError):
        api.load_api_token(token_path)
    token_path.write_text("short")
    with pytest.raises(BindicatorError):
        api.load_api_token(token_path)
    token_path.write_text(TOKEN + "\n")
    assert api.load_api_token(token_path) == TOKEN



def test_real_http_next_collection_replaces_cross_user_cache_without_chmod(
    tmp_path, monkeypatch,
):
    """CLI-owned iCal cache must not cause a 500 in the bindicator API service."""
    from bindicator import app as app_module
    from test_bin_preview import ICS_COLLECTIONS
    from types import SimpleNamespace

    config, secrets, state = make_files(tmp_path)
    state.mkdir()
    cache = state / "calendar.ics"
    cache.write_bytes(b"previous cached feed")
    original_inode = cache.stat().st_ino

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 10, 18, 18, tzinfo=ZoneInfo("Europe/London"))

    monkeypatch.setattr(api, "datetime", FixedDatetime)
    monkeypatch.setenv(
        "BINDICATOR_ICAL_URL", "https://calendar.zoho.com/private-calendar.ics",
    )
    monkeypatch.setattr(
        app_module.requests, "get",
        lambda url, timeout, allow_redirects=False: SimpleNamespace(
            content=ICS_COLLECTIONS, is_redirect=False, raise_for_status=lambda: None,
        ),
    )

    real_chmod = app_module.os.chmod
    def refuse_chmod_on_existing_cache(path, mode, *args, **kwargs):
        if Path(path) == cache:
            raise PermissionError("Only the cache file owner may chmod it")
        return real_chmod(path, mode, *args, **kwargs)
    monkeypatch.setattr(app_module.os, "chmod", refuse_chmod_on_existing_cache)

    ops = api.BindicatorAPI(config, secrets, state)
    with ThreadingHTTPServer(("127.0.0.1", 0), api.make_handler(ops, TOKEN)) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, data, _ = request(
                server.server_port, "GET", "/api/v1/collections/next",
            )
        finally:
            server.shutdown()
            thread.join(timeout=3)

    assert status == 200
    assert data["date"] == "2026-11-17"
    assert data["colours"] == ["orange", "green"]
    assert cache.read_bytes() == ICS_COLLECTIONS
    assert cache.stat().st_ino != original_inode
    assert (cache.stat().st_mode & 0o777) == 0o660


def test_unwritable_cache_returns_controlled_503_not_internal_500(
    tmp_path, monkeypatch,
):
    from bindicator import app as app_module
    from test_bin_preview import ICS_COLLECTIONS
    from types import SimpleNamespace

    config, secrets, state = make_files(tmp_path)
    state.mkdir()
    monkeypatch.setenv(
        "BINDICATOR_ICAL_URL", "https://calendar.zoho.com/private-calendar.ics",
    )
    monkeypatch.setattr(
        app_module.requests, "get",
        lambda url, timeout, allow_redirects=False: SimpleNamespace(
            content=ICS_COLLECTIONS, is_redirect=False, raise_for_status=lambda: None,
        ),
    )
    monkeypatch.setattr(
        app_module, "atomic_bytes_save",
        lambda path, content: (_ for _ in ()).throw(PermissionError("cache denied")),
    )
    ops = api.BindicatorAPI(config, secrets, state)
    with ThreadingHTTPServer(("127.0.0.1", 0), api.make_handler(ops, TOKEN)) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, data, _ = request(
                server.server_port, "GET", "/api/v1/collections/next",
            )
        finally:
            server.shutdown()
            thread.join(timeout=3)
    assert status == 503
    assert "cache denied" not in json.dumps(data)


def test_bins_out_endpoint_requires_auth_and_empty_json(live_api):
    port, ops = live_api
    for missing in (None, "wrong"):
        status, _, _ = request(port, "POST", "/api/v1/bins-out", token=missing, body={})
        assert status == 401
    assert request(port, "GET", "/api/v1/bins-out")[0] == 404
    assert request(port, "POST", "/api/v1/bins-out", body={"force": True})[0] == 400
    assert ops.calls == 0
    status, body, _ = request(port, "POST", "/api/v1/bins-out", body={})
    assert status == 200
    assert body == {"ok": True, "acknowledged": True, "restored": True}
    assert ops.actions == [("bins-out", {})]


def test_bins_out_endpoint_obeys_run_lock(tmp_path, monkeypatch):
    import fcntl
    config, secrets, state = make_files(tmp_path)
    state.mkdir()
    controller = api.BindicatorAPI(config, secrets, state)
    lock_path = state / "run.lock"
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(api.APIError) as exc:
            controller.bins_out()
    assert exc.value.status == 409
