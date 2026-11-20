#!/usr/bin/env bash
# Build Alexa Lambda ZIP; optionally publish to private S3 and deploy to Lambda.
set -euo pipefail

usage() {
    cat <<'HELP'
Usage: bash alexa/build.sh [--deploy] [--s3-bucket BUCKET [--s3-key KEY]] [--lambda-function NAME]
       bash alexa/build.sh --help

Without flags, build dist/bindicator-alexa.zip only.
--deploy               Build/upload/update the verified Bindicator Lambda using local alexa/deploy.local.conf.
--s3-bucket BUCKET     Upload the built archive to this existing private bucket.
--s3-key KEY           Optional S3 object key. Default: a SHA256-based unique key.
--lambda-function NAME Update this Lambda from the uploaded S3 object (requires --s3-bucket).

Use your existing AWS CLI credentials/profile and region (e.g. AWS_PROFILE,
AWS_REGION, AWS_DEFAULT_REGION). No AWS credentials are written to the ZIP.
The bucket must be in the same AWS Region as the Lambda function.
HELP
}

S3_BUCKET=""
S3_KEY=""
LAMBDA_FUNCTION=""
DEPLOY=false
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
while (($#)); do
    case "$1" in
        --help|-h)
            usage; exit 0 ;;
        --deploy)
            DEPLOY=true; shift ;;
        --s3-bucket|--s3-key|--lambda-function)
            option="$1"
            if (($# < 2)) || [[ -z "$2" || "$2" == --* ]]; then
                echo "Missing value for $option" >&2
                usage >&2
                exit 2
            fi
            case "$option" in
                --s3-bucket) S3_BUCKET="$2" ;;
                --s3-key) S3_KEY="$2" ;;
                --lambda-function) LAMBDA_FUNCTION="$2" ;;
            esac
            shift 2 ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 2 ;;
    esac
done

if [[ "$DEPLOY" == true ]]; then
    # Locally configured target identifiers. AWS credentials come from AWS CLI.
    DEPLOY_CONFIG="${BINDICATOR_DEPLOY_CONFIG:-$ROOT/alexa/deploy.local.conf}"
    if [[ ! -f "$DEPLOY_CONFIG" ]]; then
        echo "Missing private deployment configuration: $DEPLOY_CONFIG" >&2
        echo "Copy alexa/deploy.example.conf to alexa/deploy.local.conf and configure it first." >&2
        exit 2
    fi
    # Local configuration is trusted shell syntax. Only source a file you control.
    source "$DEPLOY_CONFIG"
    S3_BUCKET="${S3_BUCKET:-$DEPLOY_S3_BUCKET}"
    LAMBDA_FUNCTION="${LAMBDA_FUNCTION:-$DEPLOY_LAMBDA_FUNCTION}"
    if [[ "$S3_BUCKET" != "$DEPLOY_S3_BUCKET" || "$LAMBDA_FUNCTION" != "$DEPLOY_LAMBDA_FUNCTION" ]]; then
        echo "Refusing --deploy: target differs from configured local deployment settings." >&2
        exit 2
    fi
    export AWS_PROFILE="${AWS_PROFILE:-$DEPLOY_PROFILE}"
    export AWS_DEFAULT_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-$DEPLOY_REGION}}"
    if [[ "$AWS_DEFAULT_REGION" != "$DEPLOY_REGION" ]]; then
        echo "Refusing --deploy: configured AWS region is not $DEPLOY_REGION." >&2
        exit 2
    fi
fi

if [[ -n "$S3_KEY" && -z "$S3_BUCKET" ]]; then
    echo "--s3-key requires --s3-bucket." >&2
    exit 2
fi
if [[ -n "$LAMBDA_FUNCTION" && -z "$S3_BUCKET" ]]; then
    echo "--lambda-function requires --s3-bucket." >&2
    exit 2
fi
if [[ -n "$S3_BUCKET" ]] && [[ ! "$S3_BUCKET" =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ ]]; then
    echo "Invalid S3 bucket name." >&2
    exit 2
fi
if [[ -n "$S3_KEY" ]] && { [[ "$S3_KEY" == /* ]] || [[ "$S3_KEY" == *$'\n'* ]] || [[ "$S3_KEY" == *$'\r'* ]]; }; then
    echo "Invalid S3 key." >&2
    exit 2
fi
if [[ -n "$S3_BUCKET" ]] && ! command -v aws >/dev/null 2>&1; then
    echo "AWS CLI is required for S3 upload; install/configure aws first." >&2
    exit 2
fi

if [[ "$DEPLOY" == true ]]; then
    identity="$(aws sts get-caller-identity --query Account --output text)" || {
        echo "AWS login unavailable; run aws login --profile $AWS_PROFILE." >&2
        exit 1
    }
    if [[ "$identity" != "$DEPLOY_ACCOUNT_ID" ]]; then
        echo "Refusing --deploy: AWS account $identity is not $DEPLOY_ACCOUNT_ID." >&2
        exit 2
    fi
fi

OUT="$ROOT/dist"
TEMP="$(mktemp -d)"
trap 'rm -rf -- "$TEMP"' EXIT

# Use the project venv on Debian 13 (system Python enforces PEP 668).
if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
    echo "Create ~/code/bindicator/.venv and install pip first." >&2
    echo "  python3 -m venv .venv" >&2
    exit 1
fi
"$ROOT/.venv/bin/python" -m pip install --disable-pip-version-check \
  --no-cache-dir -r "$ROOT/alexa/requirements.txt" --target "$TEMP"
mkdir -p "$TEMP/alexa" "$OUT"
cp "$ROOT/LICENSE" "$ROOT/COPYRIGHT.md" "$ROOT/THIRD_PARTY_NOTICES.md" "$TEMP/"
cp "$ROOT/alexa/__init__.py" "$ROOT/alexa/logic.py" \
  "$ROOT/alexa/lambda_function.py" "$ROOT/alexa/apl.py" \
  "$ROOT/alexa/echo_show.json" "$TEMP/alexa/"
(
    cd "$TEMP"
    zip -qr "$OUT/bindicator-alexa.zip" .
)
echo "Built $OUT/bindicator-alexa.zip"
echo "AWS Lambda handler: alexa.lambda_function.lambda_handler"

if [[ -n "$S3_BUCKET" ]]; then
    if [[ -z "$S3_KEY" ]]; then
        archive_sha="$(sha256sum "$OUT/bindicator-alexa.zip" | cut -c1-16)"
        S3_KEY="bindicator/alexa/bindicator-alexa-$archive_sha.zip"
    fi
    S3_URI="s3://$S3_BUCKET/$S3_KEY"
    echo "Uploading Lambda package to $S3_URI"
    aws s3 cp "$OUT/bindicator-alexa.zip" "$S3_URI" --only-show-errors
    echo "Uploaded $S3_URI"
    if [[ -n "$LAMBDA_FUNCTION" ]]; then
        echo "Updating Lambda function $LAMBDA_FUNCTION from S3"
        aws lambda update-function-code \
            --function-name "$LAMBDA_FUNCTION" \
            --s3-bucket "$S3_BUCKET" \
            --s3-key "$S3_KEY" \
            --query '[FunctionName,LastUpdateStatus]' \
            --output text
        aws lambda wait function-updated --function-name "$LAMBDA_FUNCTION"
        echo "Lambda code update completed for $LAMBDA_FUNCTION"
    fi
fi
