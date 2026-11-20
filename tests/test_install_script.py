"""Regression test: installer status display must not split shell commands."""
from pathlib import Path
import subprocess


def test_installer_service_status_works_with_mock_systemctl():
    script = (Path(__file__).resolve().parents[1] / "deploy" / "install.sh").read_text()
    start = script.index("for unit in bindicator.timer bindicator-api.service bindicator-web.service bindicator-council-refresh.timer; do")
    end = script.index("\ndone", start) + len("\ndone")
    snippet = script[start:end]
    command = '''set -e
systemctl() {
    case "$1" in
        is-enabled) printf "enabled" ;;
        is-active) printf "active" ;;
        *) return 1 ;;
    esac
}
''' + snippet
    checked = subprocess.run(["bash", "-n"], input=command, text=True, capture_output=True)
    assert checked.returncode == 0, checked.stderr
    result = subprocess.run(["bash", "-c", command], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert len(lines) == 4
    assert all("enabled=enabled" in line and "active=active" in line for line in lines)
    assert [line.split()[0] for line in lines] == [
        "bindicator.timer", "bindicator-api.service", "bindicator-web.service",
        "bindicator-council-refresh.timer"
    ]


def test_installer_copies_license_required_by_package_metadata():
    root = Path(__file__).resolve().parents[1]
    script = (root / "deploy" / "install.sh").read_text()
    package = (root / "pyproject.toml").read_text()
    assert 'license = "GPL-3.0-only"' in package
    assert 'license-files = ["LICENSE"]' in package
    assert 'install -m 0644 "$SRC_DIR/LICENSE" /opt/bindicator/LICENSE' in script
    assert script.index('install -m 0644 "$SRC_DIR/LICENSE" /opt/bindicator/LICENSE') < script.index(
        '/opt/bindicator/.venv/bin/pip install'
    )
