"""Detached timed preview launch contract and worker safety tests."""
from __future__ import annotations

import fcntl
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from bindicator.app import BindicatorError
from bindicator.bin_preview import launch_detached_preview
from bindicator import preview_worker


def test_spawn_detached_inherits_lock_and_logs_privately(monkeypatch, tmp_path):
    import bindicator.bin_preview as bp

    lock_path = tmp_path / "run.lock"
    observed = {}

    class FakePopen:
        def __init__(self, command, **kwargs):
            observed["command"] = command
            observed["kwargs"] = kwargs
            self.pid = 4242

    monkeypatch.setattr(bp.subprocess, "Popen", FakePopen)
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        pid = launch_detached_preview(
            config_path=tmp_path / "config.yaml",
            secrets_path=tmp_path / "secrets.env",
            state_dir=tmp_path,
            colours=["orange", "green"],
            seconds=10,
            lock_fd=lock.fileno(),
        )
    assert pid == 4242
    command = observed["command"]
    assert command[:3] == [sys.executable, "-m", "bindicator.preview_worker"]
    assert "--seconds" in command
    assert command[command.index("--colours") + 1] == "orange,green"
    assert observed["kwargs"]["start_new_session"] is True
    assert observed["kwargs"]["pass_fds"]
    assert observed["kwargs"]["stdin"] == bp.subprocess.DEVNULL
    assert observed["kwargs"]["stderr"] == bp.subprocess.STDOUT
    log = tmp_path / "preview.log"
    assert log.exists()
    assert (log.stat().st_mode & 0o007) == 0  # never world-readable; group may read


@pytest.mark.parametrize("seconds", [0, 61, -3])
def test_detached_preview_invalid_duration_does_not_spawn(tmp_path, seconds):
    with pytest.raises(BindicatorError, match="between 1 and 60"):
        launch_detached_preview(
            config_path=tmp_path / "config",
            secrets_path=tmp_path / "secret",
            state_dir=tmp_path,
            colours=["blue"],
            seconds=seconds,
            lock_fd=4,
        )


def test_detached_worker_releases_lock_and_runs_exact_preview(
    monkeypatch, tmp_path,
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("unused")
    secrets_path = tmp_path / "secrets.env"
    secrets_path.write_text("")
    lock_path = tmp_path / "run.lock"
    observed = []

    monkeypatch.setattr(preview_worker, "load_config", lambda p: {
        "hue": {"lights": []}, "colors": {"blue": {"x": 0.1, "y": 0.2}},
    })
    monkeypatch.setattr(preview_worker, "load_secrets", lambda p: None)
    monkeypatch.setattr(preview_worker, "BridgePool", lambda config: "pool")
    monkeypatch.setattr(
        preview_worker, "preview_lights",
        lambda pool, config, colours, seconds: observed.append(
            (pool, colours, seconds)
        ),
    )

    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        copy_fd = os.dup(lock.fileno())
        assert preview_worker.main([
            "--config", str(config_path),
            "--secrets-file", str(secrets_path),
            "--state-dir", str(tmp_path),
            "--lock-fd", str(copy_fd),
            "--seconds", "5",
            "--colours", "blue",
        ]) == 0
    assert observed == [("pool", ["blue"], 5)]


def test_worker_refuses_unknown_colour_without_hue(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("unused")
    monkeypatch.setattr(preview_worker, "load_config", lambda p: {
        "hue": {"lights": []}, "colors": {"blue": {"x": 0.1, "y": 0.2}},
    })
    monkeypatch.setattr(preview_worker, "load_secrets", lambda p: None)
    monkeypatch.setattr(
        preview_worker, "BridgePool",
        lambda *args: pytest.fail("Must reject before touching Hue"),
    )
    lock_path = tmp_path / "run.lock"
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        dup_fd = os.dup(lock.fileno())
        assert preview_worker.main([
            "--config", str(config_path),
            "--secrets-file", str(tmp_path / "secrets.env"),
            "--state-dir", str(tmp_path),
            "--lock-fd", str(dup_fd),
            "--seconds", "10",
            "--colours", "unknown",
        ]) == 1
