"""Guard links and key entry points in the maintained documentation."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DOCS = [
    ROOT / "README.md",
    ROOT / "docs" / "README.md",
    ROOT / "docs" / "lan-management.md",
    ROOT / "docs" / "local-api.md",
    ROOT / "docs" / "calendar-providers.md",
    ROOT / "docs" / "cloudflare-setup.md",
    ROOT / "docs" / "cloudflare-cli.md",
    ROOT / "alexa" / "README.md",
    ROOT / "docs" / "aws-deployment.md",
    ROOT / "docs" / "cloudflare-iac.md",
]


def test_all_maintained_guides_have_contents_and_valid_relative_links():
    for path in DOCS:
        text = path.read_text(encoding="utf-8")
        assert text.startswith("# "), f"Missing title: {path}"
        assert "## Contents" in text, f"Missing table of contents: {path}"
        # Check real markdown links, excluding external URLs, mailto and anchor-only.
        for target in re.findall(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", text):
            if target.startswith(("https://", "http://", "mailto:", "#")):
                continue
            local = target.split("#", 1)[0]
            assert (path.parent / local).is_file(), f"{path}: broken link to {target}"


def test_readme_describes_current_install_and_eight_tab_ui():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "git switch main" in text
    assert "feat/initial-implementation" not in text
    assert "does not enable the timer" not in text
    assert "North Yorkshire Council" in text and "iCalendar" in text
    assert all(tab in text for tab in
               ("Status", "Testing", "Lighting", "Colours", "Calendars", "Mapping", "Help", "Coffee"))
    assert "docs/calendar-providers.md" in text


def test_unused_png_logos_are_retired_but_active_branding_is_preserved():
    static = ROOT / "src" / "bindicator" / "static"
    for legacy in ("bindicator-logo.png", "bindicator-wide-logo.png"):
        assert not (static / legacy).exists()
    assert (static / "bindicator-soft-banner.webp").is_file()
    assert (static / "favicon-32.png").is_file()

def test_aws_deployment_guide_matches_verified_shortcut_and_api_contract():
    root = (ROOT / "README.md").read_text(encoding="utf-8")
    index = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    guide = (ROOT / "docs" / "aws-deployment.md").read_text(encoding="utf-8")
    alexa = (ROOT / "alexa" / "README.md").read_text(encoding="utf-8")
    api = (ROOT / "docs" / "local-api.md").read_text(encoding="utf-8")
    config = (ROOT / "alexa" / "deploy.example.conf").read_text(encoding="utf-8")
    for target in ("docs/aws-deployment.md", "alexa/COMMANDS.md"):
        assert target in root
    assert "aws-deployment.md" in index
    assert "bash alexa/build.sh --deploy" in guide
    assert "bash alexa/build.sh --deploy" in alexa
    assert "Temporary" in guide or "temporary" in guide
    assert "123456789012" in config
    assert "eu-west-2" in config
    assert "bindicator-alexa" in config
    assert "/api/v1/bins-out" in api
    assert "acknowledged_date" in api
    assert "Eight-tab UI" in index


def test_cloudflare_desired_state_preserves_private_lan_and_access():
    import json
    path = ROOT / "deploy" / "cloudflare" / "desired-state.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    assert state["tunnel"]["origin_service"] == "http://127.0.0.1:18050"
    assert state["tunnel"]["http_host_header"] == "127.0.0.1:18050"
    assert state["tunnel"]["lan_dashboard_must_remain_private"] is True
    assert state["access"]["policy_decision"] == "non_identity"
    assert state["access"]["must_not_allow_everyone_or_bypass"] is True
    assert state["access"]["require_rules"] == []
    assert state["access"]["exclude_rules"] == []
    assert "client_secret" not in path.read_text(encoding="utf-8").lower()


def test_public_release_has_only_example_installation_identifiers():
    import json
    import re
    root = ROOT
    check_paths = [
        root / "alexa" / "deploy.example.conf",
        root / "deploy" / "cloudflare" / "desired-state.json",
        root / "docs" / "aws-deployment.md",
        root / "docs" / "cloudflare-cli.md",
        root / "docs" / "cloudflare-iac.md",
        root / "docs" / "cloudflare-setup.md",
        root / "alexa" / "README.md",
    ]
    for path in check_paths:
        content = path.read_text(encoding="utf-8")
        assert not re.search(r"(?<!\d)(?!123456789012)\d{12}(?!\d)", content), path
        assert "bins.example.com" in content or path.name in ("deploy.example.conf", "aws-deployment.md")
    assert not (root / "alexa" / "deploy.conf").exists()
    assert "alexa/deploy.local.conf" in (root / ".gitignore").read_text()
    state = json.loads((root / "deploy/cloudflare/desired-state.json").read_text())
    assert state["account_id"] == "YOUR_CLOUDFLARE_ACCOUNT_ID"
    assert state["hostname"] == "bins.example.com"
    assert state["access"]["must_not_allow_everyone_or_bypass"] is True


def test_gpl_v3_and_third_party_notices_ship_with_sources():
    root = ROOT
    license_text = (root / "LICENSE").read_text(encoding="utf-8")
    assert license_text.startswith("GNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007")
    assert "END OF TERMS AND CONDITIONS" in license_text
    assert 'license = "GPL-3.0-only"' in (root / "pyproject.toml").read_text()
    copyright_text = (root / "COPYRIGHT.md").read_text(encoding="utf-8")
    assert "Copyright © 2026 Stuart Roberts" in copyright_text
    assert "bindicator-soft-banner.webp" in copyright_text
    assert "favicon-32.png" in copyright_text
    assert "alexa/echo_show.json" in copyright_text
    notices = (root / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    for library in (
        "icalendar", "recurring-ical-events", "PyYAML", "Requests",
        "Beautiful Soup 4", "ruamel.yaml", "zeroconf",
        "ask-sdk-core", "ask-sdk-model", "python-dateutil", "pytest",
    ):
        assert library in notices
    assert "LGPL-3.0-or-later" in notices
    assert "LGPL-2.1-or-later" in notices
    assert "not a full automated SBOM" in notices
