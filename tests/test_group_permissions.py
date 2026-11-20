"""Trusted non-root user access and file-permission regressions."""
from __future__ import annotations

import os
import stat
from pathlib import Path

from bindicator.app import json_save, load_config
from bindicator.bridge_setup import _atomic_text
from bindicator.light_selection import write_selected_config


def test_atomic_key_edit_allows_trusted_group_user_without_chown(
    monkeypatch, tmp_path
):
    secret = tmp_path / "secrets.env"
    secret.write_text('BINDICATOR_ICAL_URL="https://example.invalid"\n')
    secret.chmod(0o660)

    # Mock only the privilege/ownership decision, while the test remains
    # running in its existing CI identity. We must not need to chown-to-root.
    import bindicator.bridge_setup as bridge_setup
    monkeypatch.setattr(bridge_setup.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(
        bridge_setup.os, "fchown",
        lambda *args: (_ for _ in ()).throw(
            AssertionError("Non-root users cannot chown to root")
        ),
    )
    _atomic_text(secret, 'BINDICATOR_ICAL_URL="https://different.example"\n',
                 private=True)
    assert stat.S_IMODE(secret.stat().st_mode) == 0o660
    assert "different.example" in secret.read_text()


def test_nonroot_light_selection_writer_does_not_require_chown(
    monkeypatch, tmp_path
):
    sample = Path(__file__).resolve().parents[1] / "config.example.yaml"
    target = tmp_path / "config.yaml"
    target.write_text(sample.read_text())
    target.chmod(0o660)
    import bindicator.light_selection as light_selection

    monkeypatch.setattr(light_selection.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(
        light_selection.os, "fchown",
        lambda *args: (_ for _ in ()).throw(
            AssertionError("Non-root users cannot chown to root")
        ),
    )
    selection = [{"bridge": "office", "id": "26584554-24d6-4d4c-bbad-0ac099f243f2"}]
    # Add a configured Bridge so load_config can check the selection.
    from bindicator.bridge_setup import save_bridge_config
    save_bridge_config(target, "office", "192.168.1.180")
    write_selected_config(target, selection)
    assert load_config(target)["hue"]["lights"] == selection
    assert stat.S_IMODE(target.stat().st_mode) == 0o660


def test_saved_runtime_state_is_group_readable(tmp_path):
    path = tmp_path / "state.json"
    json_save(path, {"date": None, "lights": {}})
    assert stat.S_IMODE(path.stat().st_mode) == 0o660


def test_installer_and_unit_use_restricted_shared_group():
    root = Path(__file__).resolve().parents[1]
    install = (root / "deploy" / "install.sh").read_text()
    unit = (root / "deploy" / "bindicator.service").read_text()
    assert "chmod 2770 /var/lib/bindicator /etc/bindicator" in install
    assert "chmod 0660 /etc/bindicator/config.yaml /etc/bindicator/secrets.env" in install
    assert "StateDirectoryMode=2770" in unit
    assert "UMask=0007" in unit
