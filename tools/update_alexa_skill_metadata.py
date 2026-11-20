#!/usr/bin/env python3
"""Safely update only en-GB Alexa skill listing text using ASK CLI.

Fetches the COMPLETE live development manifest, updates two fields, saves a
private backup, submits the complete manifest, then verifies the result.
No skill ID, account credentials or live manifest is committed to Git.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LISTING = PROJECT_ROOT / "alexa" / "skill_listing.en-GB.json"
SKILL_ID_PATTERN = re.compile(r"^amzn1\\.ask\\.skill\\.[0-9a-fA-F-]{36}$")


def ask_cli(*arguments):
    result = subprocess.run(
        ["ask", "api", *arguments], capture_output=True, text=True, check=False
    )
    if result.returncode:
        raise RuntimeError(
            "ASK CLI request failed (exit %s): %s"
            % (result.returncode, result.stderr.strip() or "inspect ASK CLI login")
        )
    return result.stdout


def fetch_manifest(skill_id, profile):
    output = ask_cli(
        "get-skill", "--skill-id", skill_id,
        "--stage", "development", "--profile", profile
    )
    data = json.loads(output)
    if not isinstance(data, dict) or not isinstance(data.get("manifest"), dict):
        raise ValueError("Unexpected ASK CLI manifest response (missing manifest object)")
    if data.get("skillId") not in (None, skill_id):
        raise ValueError("Returned manifest belongs to a different skill ID")
    return data


def desired_listing():
    listing = json.loads(LISTING.read_text(encoding="utf-8"))
    if set(listing) != {"summary", "description"}:
        raise ValueError("Expected only summary and description in listing data")
    for key in ("summary", "description"):
        if not isinstance(listing[key], str) or not listing[key].strip():
            raise ValueError("Empty or invalid Alexa listing: " + key)
    if len(listing["summary"]) > 160:
        raise ValueError("Alexa short description exceeds 160 characters")
    if "https://github.com/accidentalskeleton/bindicator" not in listing["description"]:
        raise ValueError("Alexa detailed description is missing public repository link")
    return listing


def update_manifest(data, listing):
    # Deliberately do not create a new locale, overwrite other locale descriptions
    # or modify any endpoints / permissions / privacy metadata.
    try:
        locale = data["manifest"]["publishingInformation"]["locales"]["en-GB"]
    except (KeyError, TypeError) as exc:
        raise ValueError("Existing skill has no en-GB publishing locale") from exc
    if not isinstance(locale, dict):
        raise ValueError("Invalid en-GB publishing locale")
    changed = dict(locale)
    changed.update(listing)
    new_data = json.loads(json.dumps(data))
    new_data["manifest"]["publishingInformation"]["locales"]["en-GB"] = changed
    # ASK CLI update-skill takes the full skill MANIFEST object (no skillId
    # or top-level metadata returned by get-skill).
    return {"manifest": new_data["manifest"]}


def secure_backup(data, directory):
    directory = Path(directory).expanduser()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if directory.is_symlink() or directory.stat().st_mode & 0o077:
        raise PermissionError("Manifest backup directory must be private (mode 0700)")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    fd, filename = tempfile.mkstemp(prefix="manifest-" + stamp + "-", suffix=".json", dir=directory)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(data, stream, indent=2)
        stream.write("\n")
    return Path(filename)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-id", required=True)
    parser.add_argument("--profile", default="default")
    parser.add_argument("--check", action="store_true",
                        help="Preview changes, without uploading to Amazon")
    parser.add_argument("--backup-dir", default=str(Path.home() / ".local/state/bindicator/alexa-manifests"))
    args = parser.parse_args(argv)

    if not SKILL_ID_PATTERN.fullmatch(args.skill_id):
        parser.error("Expected Alexa skill ID amzn1.ask.skill.<UUID>")
    listing = desired_listing()
    old = fetch_manifest(args.skill_id, args.profile)
    new = update_manifest(old, listing)
    original_locale = old["manifest"]["publishingInformation"]["locales"]["en-GB"]
    if all(original_locale.get(key) == val for key, val in listing.items()):
        print("Alexa en-GB skill metadata already matches the repository.")
        return 0
    print("Will update ONLY en-GB publishing summary and description.")
    if args.check:
        print("Preview OK; no Alexa changes made.")
        return 0

    backup = secure_backup(old, args.backup_dir)
    print("Backed up current skill manifest to:", backup)

    # A private temporary directory prevents complete manifest data from
    # being included in project build products or Git staging.
    with tempfile.TemporaryDirectory(prefix="bindicator-ask-") as tmpdir:
        manifest_file = Path(tmpdir) / "manifest.json"
        manifest_file.write_text(json.dumps(new, indent=2) + "\n", encoding="utf-8")
        manifest_file.chmod(0o600)
        ask_cli(
            "update-skill", "--skill-id", args.skill_id,
            "--stage", "development", "--profile", args.profile,
            "--file", str(manifest_file)
        )

    for attempt in range(5):
        actual = fetch_manifest(args.skill_id, args.profile)
        loc = actual["manifest"]["publishingInformation"]["locales"]["en-GB"]
        if all(loc.get(key) == val for key, val in listing.items()):
            print("Verified Alexa en-GB listing metadata updated in development.")
            return 0
        if attempt != 4:
            time.sleep(2)
    raise RuntimeError(
        "Amazon accepted the update but its latest development manifest has "
        "not yet reflected the changes. Inspect the Developer Console; backup: "
        + str(backup)
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print("Alexa metadata update failed:", exc, file=sys.stderr)
        sys.exit(1)
