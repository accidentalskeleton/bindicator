"""Authenticated localhost HTTP API for Bindicator.

No external web server dependency, no shell execution, and no public bind
address. All write operations delegate to the existing CLI so run.lock,
Hue restoration safeguards and pause behaviour remain authoritative.
"""
from __future__ import annotations

import argparse
import fcntl
import hmac
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .app import (
    DEFAULT_CONFIG, DEFAULT_SECRETS, DEFAULT_STATE_DIR, TZ,
    Bindicator, BindicatorError, collection_events_in_range,
    load_config, load_secrets,
)
from .bin_preview import next_collection
from .bridges import BridgePool
from .controls import is_paused

LOG = logging.getLogger("bindicator.api")
HOST = "127.0.0.1"
DEFAULT_PORT = 18050
DEFAULT_TOKEN_FILE = Path("/etc/bindicator/api.token")
MAX_BODY = 512


class APIError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


def load_api_token(path: Path) -> str:
    """Require an already-generated strong token; never log its contents."""
    try:
        token = path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as exc:
        raise BindicatorError("Could not read API authentication token.") from exc
    if not 32 <= len(token) <= 256 or not token.isascii() or any(c.isspace() for c in token):
        raise BindicatorError("Invalid API authentication token.")
    return token


class BindicatorAPI:
    """Small operation layer; state is read per call rather than cached."""

    def __init__(self, config_path: Path, secrets_path: Path, state_dir: Path):
        self.config_path = config_path
        self.secrets_path = secrets_path
        self.state_dir = state_dir

    def _app(self) -> Bindicator:
        config = load_config(self.config_path)
        load_secrets(self.secrets_path)
        return Bindicator(config, self.state_dir, BridgePool(config["hue"]))

    def status(self) -> dict:
        app = self._app()
        return {
            "paused": is_paused(self.state_dir),
            "active_collection_date": app.state.get("date"),
            "acknowledged_date": app.state.get("acknowledged_date"),
            "manual_until": app.state.get("manual_until"),
            "indicator_count": len(app.state["lights"]),
            "indicators": [
                {"light": rid, "colour": record.get("color_name")}
                for rid, record in app.state["lights"].items()
            ],
        }

    def next_collection(self) -> dict:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with (self.state_dir / "run.lock").open("a+") as lock:
            # A timed preview or scheduled check holds the same lock.
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise APIError(409, "Bindicator is busy; retry shortly.") from exc
            app = self._app()
            feed = app.calendar_data()
            collection_day, colours = next_collection(
                app.config, feed, datetime.now(TZ)
            )
            # Match actual Zoho events on this date, rather than guessing
            # titles from colours (several bin types may share a colour).
            events = collection_events_in_range(
                feed, collection_day, collection_day + timedelta(days=1),
                app.config["calendar"]["events"],
            ).get(collection_day, [])
            collection_types = [
                event["title"].split(" - ", 1)[-1]
                if " - " in event["title"] else event["title"]
                for event in events
            ]
            return {
                "date": collection_day.isoformat(),
                "weekday": collection_day.strftime("%A"),
                "collections": collection_types,
                "colours": colours,
            }

    def bins_out(self) -> dict:
        """Acknowledge the active reminder without disabling future schedules."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with (self.state_dir / "run.lock").open("a+") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise APIError(409, "Bindicator is busy; retry shortly.") from exc
            app = self._app()
            result = app.acknowledge_bins_out()
            return {"ok": True, **result}

    def command(self, action: str, body: dict) -> dict:
        args = {
            "pause": ["--pause"],
            "resume": ["--resume"],
            "toggle": ["--toggle"],
            "alerts/next": ["--next-collection"],
        }[action].copy()
        if action == "alerts/next":
            if set(body) - {"seconds"}:
                raise APIError(400, "Only 'seconds' is accepted for this operation.")
            if "seconds" in body:
                seconds = body["seconds"]
                if type(seconds) is not int or not 1 <= seconds <= 60:
                    raise APIError(400, "'seconds' must be an integer from 1 to 60.")
                args.extend(["--seconds", str(seconds)])
        elif body:
            raise APIError(400, "This operation takes an empty JSON object.")

        # Fixed arguments only; no shell, user-specified commands or paths.
        cmd = [
            sys.executable, "-m", "bindicator.cli",
            "--config", str(self.config_path),
            "--secrets-file", str(self.secrets_path),
            "--state-dir", str(self.state_dir),
            *args,
        ]
        try:
            result = subprocess.run(
                cmd, stdin=subprocess.DEVNULL, capture_output=True,
                text=True, timeout=90, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise APIError(504, "Bindicator command exceeded the time limit.") from exc
        except OSError as exc:
            raise APIError(500, "Could not start Bindicator command.") from exc
        if result.returncode:
            # Do not return arbitrary stderr from config/network libraries;
            # useful diagnostics remain in the service journal.
            LOG.warning("Bindicator operation %s failed (exit %d): %s",
                        action, result.returncode, result.stderr[-600:])
            raise APIError(409, "Bindicator refused the action; check its state or service log.")
        return {
            "ok": True,
            "action": action,
            "message": result.stdout.strip()[-1000:],
        }


def make_handler(api: BindicatorAPI, token: str):
    """Build the handler without global mutable service state."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "BindicatorAPI"
        sys_version = ""

        def log_message(self, fmt: str, *args) -> None:
            LOG.info("HTTP %s", fmt % args)

        def _json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            headers = self.headers.get_all("Authorization", [])
            if len(headers) != 1:
                return False
            value = headers[0]
            prefix = "Bearer "
            return (
                value.startswith(prefix)
                and hmac.compare_digest(value[len(prefix):], token)
            )

        def _route(self) -> str:
            # Bind only to loopback, and reject DNS-rebinding Host headers.
            port = self.server.server_port
            allowed = {f"{HOST}:{port}", f"localhost:{port}"}
            if self.headers.get("Host") not in allowed:
                raise APIError(400, "Invalid Host header.")
            path = urlsplit(self.path)
            if path.query or path.fragment:
                raise APIError(400, "Query parameters are not supported.")
            return path.path

        def _handle(self, method: str) -> None:
            try:
                route = self._route()
                if route == "/api/v1/health" and method == "GET":
                    self._json(200, {"status": "ok"})
                    return
                if not self._authorized():
                    self._json(401, {"error": "Authentication required."})
                    return
                if method == "GET":
                    if route == "/api/v1/status":
                        response = api.status()
                    elif route == "/api/v1/collections/next":
                        response = api.next_collection()
                    else:
                        raise APIError(404, "Endpoint not found.")
                else:
                    actions = {
                        "/api/v1/pause": "pause",
                        "/api/v1/resume": "resume",
                        "/api/v1/toggle": "toggle",
                        "/api/v1/alerts/next": "alerts/next",
                    }
                    action = actions.get(route)
                    if route == "/api/v1/bins-out":
                        action = "bins-out"
                    if action is None:
                        raise APIError(404, "Endpoint not found.")
                    if self.headers.get("Content-Type", "").split(";", 1)[0].lower() != "application/json":
                        raise APIError(415, "Content-Type must be application/json.")
                    length_str = self.headers.get("Content-Length")
                    if not length_str or not length_str.isdecimal():
                        raise APIError(411, "Content-Length required.")
                    length = int(length_str)
                    if length > MAX_BODY:
                        raise APIError(413, "Request body too large.")
                    try:
                        body = json.loads(self.rfile.read(length))
                    except (UnicodeError, ValueError) as exc:
                        raise APIError(400, "Invalid JSON body.") from exc
                    if not isinstance(body, dict):
                        raise APIError(400, "JSON object required.")
                    if action == "bins-out":
                        if body:
                            raise APIError(400, "This operation takes an empty JSON object.")
                        response = api.bins_out()
                    else:
                        response = api.command(action, body)
                self._json(200, response)
            except APIError as exc:
                self._json(exc.status, {"error": exc.message})
            except BindicatorError as exc:
                # Do not expose private secrets, paths or Hue identifiers to
                # HTTP clients; details remain in the local journal.
                LOG.warning("Bindicator API operation failed: %s", exc)
                self._json(503, {"error": "Bindicator operation unavailable; check service logs."})
            except Exception:
                LOG.exception("Unexpected Bindicator API error.")
                self._json(500, {"error": "Internal API error."})

        def do_GET(self) -> None:
            self._handle("GET")

        def do_POST(self) -> None:
            self._handle("POST")

    return Handler


def serve(
    config_path: Path = DEFAULT_CONFIG,
    secrets_path: Path = DEFAULT_SECRETS,
    state_dir: Path = DEFAULT_STATE_DIR,
    token_file: Path = DEFAULT_TOKEN_FILE,
    port: int = DEFAULT_PORT,
) -> None:
    if not 1 <= port <= 65535:
        raise BindicatorError("Invalid HTTP API port.")
    token = load_api_token(token_file)
    api = BindicatorAPI(config_path, secrets_path, state_dir)
    # Force loopback even if arguments/environment are manipulated.
    with ThreadingHTTPServer((HOST, port), make_handler(api, token)) as server:
        server.daemon_threads = True
        LOG.info("Bindicator HTTP API listening on %s:%d (loopback only)", HOST, port)
        server.serve_forever(poll_interval=0.25)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bindicator loopback HTTP API")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--secrets-file", type=Path, default=DEFAULT_SECRETS)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    parser.add_argument("--token-file", type=Path, default=DEFAULT_TOKEN_FILE)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    os.umask(0o007)
    try:
        serve(
            args.config, args.secrets_file, args.state_dir,
            args.token_file, args.port,
        )
        return 0
    except (BindicatorError, OSError) as exc:
        LOG.error("Could not start Bindicator API: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
