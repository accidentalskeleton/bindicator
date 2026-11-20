#!/usr/bin/env bash
# Conservative release gate. Read-only: never removes history, secrets or tags.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
failed=0

echo "Checking public-release working tree..."
if [[ -n "$(git status --porcelain)" ]]; then
    echo "FAIL: working tree is not clean; commit or discard intended changes." >&2
    failed=1
fi

if [[ ! -f LICENSE && ! -f LICENSE.md ]]; then
    echo "FAIL: choose and add an open-source LICENSE before publication." >&2
    failed=1
fi

for path in alexa/deploy.conf secrets.env config.yaml .env; do
    if git ls-files --error-unmatch "$path" >/dev/null 2>&1; then
        echo "FAIL: tracked installation-specific file: $path" >&2
        failed=1
    fi
done

# The original private branch tracked personally identifying AWS deployment
# targets. Their deletion in later commits does not remove prior Git objects.
if [[ -n "$(git rev-list --all -- alexa/deploy.conf)" ]]; then
    echo "FAIL: private deployment config exists in repository history." >&2
    echo "Publish a fresh reviewed snapshot with new history instead." >&2
    failed=1
fi

if ! command -v gitleaks >/dev/null 2>&1; then
    echo "FAIL: install Gitleaks and run full history + working tree scans." >&2
    failed=1
elif gitleaks git --help >/dev/null 2>&1 && gitleaks dir --help >/dev/null 2>&1; then
    echo "Scanning Git history with modern Gitleaks (redacted output)..."
    if ! gitleaks git --redact --log-opts="--all" "$ROOT"; then
        echo "FAIL: Gitleaks Git-history scan was not clean." >&2
        failed=1
    fi
    echo "Scanning current files with modern Gitleaks (redacted output)..."
    if ! gitleaks dir --redact "$ROOT"; then
        echo "FAIL: Gitleaks directory scan was not clean." >&2
        failed=1
    fi
elif gitleaks detect --help >/dev/null 2>&1; then
    echo "Scanning Git history with legacy Gitleaks (redacted output)..."
    if ! gitleaks detect --redact --source "$ROOT" --log-opts="--all"; then
        echo "FAIL: Gitleaks Git-history scan was not clean." >&2
        failed=1
    fi
    echo "Scanning current files with legacy Gitleaks (redacted output)..."
    if ! gitleaks detect --redact --no-git --source "$ROOT"; then
        echo "FAIL: Gitleaks directory scan was not clean." >&2
        failed=1
    fi
else
    echo "FAIL: unsupported Gitleaks CLI; inspect gitleaks --help." >&2
    failed=1
fi

if ((failed)); then
    echo "BLOCKED: not ready to make public. See SECURITY.md." >&2
    exit 1
fi
echo "Automated checks passed. Still review code, commit metadata, binaries,"
echo "distribution rights, pull requests and GitHub repository settings manually."
echo "This script does not grant a publication approval."
