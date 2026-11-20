"""Safe Alexa publishing tests. No Amazon/AWS network requests."""
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tools" / "update_alexa_skill_metadata.py"
spec = importlib.util.spec_from_file_location("alexa_skill_metadata", SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
SKILL_ID = "amzn1.ask.skill.11111111-2222-3333-4444-555555555555"


def existing():
    return {
        "skillId": SKILL_ID,
        "vendorId": "VENDOR",
        "manifest": {
            "publishingInformation": {
                "locales": {
                    "en-GB": {
                        "name": "Bin Indicator",
                        "summary": "Original summary",
                        "description": "Original description",
                        "examplePhrases": ["Alexa, open bin buddy"],
                        "privacyPolicyUrl": "https://example.org/privacy",
                    },
                    "en-US": {"summary": "US summary", "description": "US description"},
                },
                "isAvailableWorldwide": False,
            },
            "apis": {"custom": {"endpoint": {"uri": "arn:aws:lambda:example"}}},
            "permissions": [{"name": "alexa::devices:all:address:country_and_postal_code:read"}],
        },
    }


def test_listing_has_correct_public_repo_and_description_limit():
    listing = module.desired_listing()
    assert "https://github.com/accidentalskeleton/bindicator" in listing["description"]
    assert len(listing["summary"]) <= 160
    assert module.SKILL_ID_PATTERN.fullmatch(SKILL_ID)


def test_only_uk_summary_and_description_change():
    old = existing()
    changed = module.update_manifest(old, module.desired_listing())
    manifest = changed["manifest"]
    assert "skillId" not in changed
    assert manifest["apis"] == old["manifest"]["apis"]
    assert manifest["permissions"] == old["manifest"]["permissions"]
    assert manifest["publishingInformation"]["locales"]["en-US"] == (
        old["manifest"]["publishingInformation"]["locales"]["en-US"]
    )
    uk = manifest["publishingInformation"]["locales"]["en-GB"]
    assert uk["name"] == "Bin Indicator"
    assert uk["privacyPolicyUrl"] == "https://example.org/privacy"
    assert uk["examplePhrases"] == ["Alexa, open bin buddy"]
    assert old["manifest"]["publishingInformation"]["locales"]["en-GB"]["summary"] == "Original summary"


def test_missing_en_gb_locale_fails_closed():
    old = existing()
    del old["manifest"]["publishingInformation"]["locales"]["en-GB"]
    with pytest.raises(ValueError, match="no en-GB"):
        module.update_manifest(old, module.desired_listing())


def test_dry_run_does_not_write_to_amazon(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(module, "fetch_manifest", lambda skill, profile: existing())
    monkeypatch.setattr(module, "ask_cli", lambda *args: pytest.fail("Unexpected Amazon write"))
    assert module.main(["--skill-id", SKILL_ID, "--check", "--backup-dir", str(tmp_path)]) == 0
    assert list(tmp_path.iterdir()) == []
    assert "no Alexa changes made" in capsys.readouterr().out


def test_publish_preserves_manifest_and_saves_private_backup(monkeypatch, tmp_path):
    old = existing()
    captured = {"manifest": old, "updates": []}

    def fake_ask(*args):
        if args[0] == "get-skill":
            return json.dumps(captured["manifest"])
        if args[0] == "update-skill":
            idx = args.index("--file") + 1
            updated = json.loads(Path(args[idx]).read_text())
            captured["updates"].append(updated)
            captured["manifest"] = {"skillId": SKILL_ID, "manifest": updated["manifest"]}
            return "{}"
        pytest.fail("Unrecognised ASK command")

    monkeypatch.setattr(module, "ask_cli", fake_ask)
    assert module.main(["--skill-id", SKILL_ID, "--backup-dir", str(tmp_path)]) == 0
    assert len(captured["updates"]) == 1
    assert captured["updates"][0]["manifest"]["apis"] == old["manifest"]["apis"]
    backups = list(tmp_path.glob("manifest-*.json"))
    assert len(backups) == 1
    assert backups[0].stat().st_mode & 0o077 == 0
    assert json.loads(backups[0].read_text()) == old


def test_invalid_skill_id_rejected_before_ask(monkeypatch):
    monkeypatch.setattr(module, "ask_cli", lambda *args: pytest.fail("Called ASK for invalid ID"))
    with pytest.raises(SystemExit):
        module.main(["--skill-id", "wrong"])


def test_build_only_rejects_metadata_flag_before_network():
    script = ROOT / "alexa" / "build.sh"
    result = subprocess.run(
        ["bash", str(script), "--update-skill-metadata"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2
    assert "--update-skill-metadata requires --deploy" in result.stderr
