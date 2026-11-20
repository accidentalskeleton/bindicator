"""Offline unit tests for licence scanning of Lambda deployment archives."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "lambda_licence_check", ROOT / "tools" / "check_lambda_licenses.py"
)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def _archive(path: Path, *, secret: bool = False, missing: str = "") -> None:
    with ZipFile(path, "w") as z:
        for name in checker.REQUIRED:
            if name != missing:
                z.writestr(name, "test fixture")
        for package in checker.REQUIRED_PACKAGES:
            metadata = f"Metadata-Version: 2.3\nName: {package}\nVersion: 1.0.0\nLicense-Expression: MIT\n"
            z.writestr(
                f"{package.replace('-', '_')}-1.0.0.dist-info/METADATA",
                metadata,
            )
        if secret:
            z.writestr("alexa/deploy.local.conf", "DEPLOY_ACCOUNT_ID=000000000000")


def test_complete_synthetic_lambda_archive_passes(tmp_path):
    archive = tmp_path / "lambda.zip"
    _archive(archive)
    assert checker.check(archive) == 0


def test_missing_project_license_fails(tmp_path):
    archive = tmp_path / "lambda.zip"
    _archive(archive, missing="LICENSE")
    assert checker.check(archive) == 1


def test_private_config_in_bundle_fails(tmp_path):
    archive = tmp_path / "lambda.zip"
    _archive(archive, secret=True)
    assert checker.check(archive) == 1


def test_missing_archive_fails(tmp_path):
    assert checker.check(tmp_path / "missing.zip") == 2
