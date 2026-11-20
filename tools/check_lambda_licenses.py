#!/usr/bin/env python3
"""Offline audit of an already-built Alexa Lambda ZIP; never deploys to AWS."""
from __future__ import annotations

import argparse
from email.parser import Parser
from pathlib import Path
import sys
from zipfile import ZipFile, BadZipFile

REQUIRED = {"LICENSE", "COPYRIGHT.md", "THIRD_PARTY_NOTICES.md",
            "alexa/lambda_function.py", "alexa/apl.py", "alexa/echo_show.json"}
REQUIRED_PACKAGES = {"ask-sdk-core", "ask-sdk-model", "ask-sdk-runtime",
                     "python-dateutil", "requests", "urllib3", "certifi",
                     "idna", "charset-normalizer", "six"}


def normalize(value: str) -> str:
    return value.lower().replace("_", "-").replace(".", "-")


def check(path: Path) -> int:
    if not path.is_file():
        print(f"ERROR: Lambda bundle not found: {path}", file=sys.stderr)
        return 2
    problems: list[str] = []
    with ZipFile(path) as z:
        names = set(z.namelist())
        for filename in sorted(REQUIRED - names):
            problems.append(f"Missing project licence/source notice: {filename}")
        for filename in names:
            if filename.startswith((".env", ".aws/", ".terraform/")) or filename in (
                "secrets.env", "alexa/deploy.conf", "alexa/deploy.local.conf",
                "config.yaml", "api.token"
            ):
                problems.append(f"Private configuration in bundle: {filename}")
        packages = {}
        for filename in sorted(names):
            if filename.endswith(".dist-info/METADATA") and "/" in filename:
                try:
                    raw = z.read(filename).decode("utf-8", "replace")
                    meta = Parser().parsestr(raw, headersonly=True)
                    name = meta.get("Name", "").strip()
                    license_info = (meta.get("License-Expression") or
                                    meta.get("License") or
                                    ", ".join(meta.get_all("Classifier", [])))
                    if not name:
                        problems.append(f"Missing package name in {filename}")
                        continue
                    packages[normalize(name)] = (meta.get("Version", ""), license_info)
                    if not license_info:
                        problems.append(f"No licence metadata for {name}: review upstream wheel")
                except (KeyError, ValueError) as exc:
                    problems.append(f"Unreadable metadata {filename}: {exc}")
        for package in sorted(REQUIRED_PACKAGES - set(packages)):
            problems.append(f"Missing required dependency metadata: {package}")
        print(f"Bundle: {path}")
        print(f"Distributions found: {len(packages)}")
        for package, (version, license_info) in sorted(packages.items()):
            licence = license_info[:105].replace("\n", " ") if license_info else "UNSPECIFIED"
            print(f"  {package} {version}: {licence}")
        if problems:
            for problem in problems:
                print("REVIEW: " + problem, file=sys.stderr)
            print("NOT CLEARED: inspect notices and package metadata before redistribution")
            return 1
        print("Structural and package-metadata check passed.")
        print("This does not certify all transitive notices or licence compliance.")
        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", nargs="?", type=Path,
                        default=Path("dist/bindicator-alexa.zip"))
    args = parser.parse_args()
    try:
        raise SystemExit(check(args.archive))
    except BadZipFile as exc:
        parser.exit(2, f"ERROR: invalid ZIP archive: {exc}\n")
