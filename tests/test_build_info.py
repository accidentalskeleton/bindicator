"""Regression checks for installed version + commit provenance."""
import json
from pathlib import Path

from bindicator.build_info import installed_commit, display_version


def test_full_sha_displays_short_revision(tmp_path):
    info = tmp_path / "build.json"
    sha = "0123456789abcdef0123456789abcdef01234567"
    info.write_text(json.dumps({"commit": sha}), encoding="utf-8")
    assert installed_commit(info) == "0123456"
    assert display_version(info) == "0.1.0 (0123456)"


def test_invalid_or_unavailable_commit_never_leaks_untrusted_data(tmp_path):
    info = tmp_path / "build.json"
    assert installed_commit(info) is None
    assert display_version(info) == "0.1.0"
    for value in (
        {"commit": "not-a-sha"},
        {"commit": "<script>alert(1)</script>"},
        {"commit": "a" * 41},
        {"commit": 123},
        {"commit": ""},
        ["a" * 40],
    ):
        info.write_text(json.dumps(value), encoding="utf-8")
        assert installed_commit(info) is None
    info.write_text("{invalid", encoding="utf-8")
    assert installed_commit(info) is None


def test_installer_captures_source_git_sha_before_packaging():
    root = Path(__file__).resolve().parents[1]
    script = (root / "deploy" / "install.sh").read_text()
    assert 'git -c safe.directory="$SRC_DIR" -C "$SRC_DIR" rev-parse --verify HEAD' in script
    assert 'SOURCE_COMMIT" =~ ^[0-9a-f]{40}$' in script
    assert '/opt/bindicator/src/bindicator/_build_info.json' in script
    assert script.index('_build_info.json') < script.index('/opt/bindicator/.venv/bin/pip install')
    assert 'rm -f /opt/bindicator/src/bindicator/_build_info.json' in script
    assert '"_build_info.json"' in (root / "pyproject.toml").read_text()
