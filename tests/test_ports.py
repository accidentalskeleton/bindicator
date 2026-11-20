"""Keep Bindicator API, LAN UI and deployment service ports aligned."""
from pathlib import Path

from bindicator.api import DEFAULT_PORT as API_PORT
from bindicator.web import DEFAULT_PORT as WEB_PORT

ROOT = Path(__file__).resolve().parents[1]


def test_trafalgar_ports():
    assert API_PORT == 18050
    assert WEB_PORT == 18051
    assert API_PORT != WEB_PORT


def test_systemd_services_use_declared_ports():
    api = (ROOT / "deploy/bindicator-api.service").read_text()
    web = (ROOT / "deploy/bindicator-web.service").read_text()
    assert "--port 18050" in api
    assert "--port 18051" in web
    assert "EnvironmentFile=/etc/bindicator/web.env" in web


def test_installer_and_lan_setup_use_new_ports():
    installer = (ROOT / "deploy/install.sh").read_text()
    lan_setup = (ROOT / "deploy/setup-lan-web.sh").read_text()
    assert "127.0.0.1:18050/api/v1/health" in installer
    assert ":18051/" in lan_setup
