"""Safe CLI checks for optional Alexa S3 publishing (no AWS calls)."""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "alexa" / "build.sh"


def run_build(*args, env=None):
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=ROOT, capture_output=True, text=True, check=False,
        env={**os.environ,
             "BINDICATOR_DEPLOY_CONFIG": str(ROOT / "alexa" / "deploy.example.conf"),
             "AWS_REGION": "eu-west-2", **(env or {})},
    )


def test_build_help_documents_upload_and_deploy():
    result = run_build("--help")
    assert result.returncode == 0
    assert "--s3-bucket" in result.stdout
    assert "--s3-key" in result.stdout
    assert "--lambda-function" in result.stdout


def test_deploy_requires_explicit_bucket_before_installing_dependencies():
    result = run_build("--lambda-function", "bindicator-alexa")
    assert result.returncode == 2
    assert "requires --s3-bucket" in result.stderr
    assert "Collecting" not in result.stdout


def test_key_requires_bucket_before_building():
    result = run_build("--s3-key", "test.zip")
    assert result.returncode == 2
    assert "requires --s3-bucket" in result.stderr


def test_missing_argument_and_unknown_option_fail_closed():
    for args in [("--s3-bucket",), ("--bogus",)]:
        result = run_build(*args)
        assert result.returncode == 2
        assert "Built " not in result.stdout


def test_s3_upload_requires_valid_bucket():
    result = run_build("--s3-bucket", "INVALID_BUCKET!")
    assert result.returncode == 2
    assert "Invalid S3 bucket" in result.stderr


def test_upload_is_opt_in_and_lambda_requires_explicit_selection():
    script = SCRIPT.read_text()
    assert 'if [[ -n "$S3_BUCKET" ]]; then' in script
    assert 'if [[ -n "$LAMBDA_FUNCTION" ]]; then' in script
    assert 'aws s3 cp "$OUT/bindicator-alexa.zip"' in script
    assert "aws lambda update-function-code" in script
    assert "aws lambda wait function-updated" in script
    assert "sha256sum" in script
    assert "--acl public-read" not in script

def test_deploy_shortcut_has_generic_nonsecret_example():
    conf = (ROOT / "alexa" / "deploy.example.conf").read_text()
    assert not (ROOT / "alexa" / "deploy.conf").exists()
    assert "DEPLOY_PROFILE=bindicator" in conf
    assert "DEPLOY_REGION=eu-west-2" in conf
    assert "DEPLOY_ACCOUNT_ID=123456789012" in conf
    assert "DEPLOY_S3_BUCKET=example-private-lambda-deployments" in conf
    assert "DEPLOY_LAMBDA_FUNCTION=bindicator-alexa" in conf
    assert "SECRET" not in conf
    help_result = run_build("--help")
    assert "--deploy" in help_result.stdout


def test_deploy_rejects_wrong_region_before_aws_calls():
    result = run_build("--deploy", env={"AWS_REGION": "eu-north-1"})
    assert result.returncode == 2
    assert "configured AWS region is not eu-west-2" in result.stderr


def test_deploy_rejects_unexpected_targets_before_aws_calls():
    for args in [
        ("--deploy", "--s3-bucket", "another-private-bucket"),
        ("--deploy", "--lambda-function", "wrong-function"),
    ]:
        result = run_build(*args)
        assert result.returncode == 2
        assert "target differs from configured local deployment settings" in result.stderr


def test_no_deploy_when_help_requested():
    result = run_build("--deploy", "--help")
    assert result.returncode == 0
    assert "Uploading Lambda" not in result.stdout


def test_lambda_bundle_contains_project_license_and_notices():
    script = SCRIPT.read_text()
    assert 'cp "$ROOT/LICENSE" "$ROOT/COPYRIGHT.md" "$ROOT/THIRD_PARTY_NOTICES.md" "$TEMP/"' in script
    assert '"$ROOT/alexa/requirements.txt" --target "$TEMP"' in script


def test_no_private_deployment_configuration_enters_lambda_bundle():
    script = SCRIPT.read_text()
    assert 'cp "$ROOT/alexa/deploy.local.conf"' not in script
    assert 'cp "$ROOT/alexa/deploy.conf"' not in script
