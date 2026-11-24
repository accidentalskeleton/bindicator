#!/usr/bin/env bash
# Install Bindicator on Debian 13. Run with: sudo bash deploy/install.sh
set -euo pipefail

if [[ "$EUID" -ne 0 ]]; then
    echo "Run with sudo: sudo bash deploy/install.sh" >&2
    exit 1
fi
SRC_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
command -v python3 >/dev/null || { echo "python3 is required." >&2; exit 1; }
command -v systemctl >/dev/null || { echo "systemd is required." >&2; exit 1; }

# Debian splits the ensurepip module out into a version-specific -venv package.
# Check before creating any files so missing dependencies fail cleanly.
VENV_PACKAGE="$(python3 -c 'import sys; print(f"python{sys.version_info.major}.{sys.version_info.minor}-venv")')"
if ! python3 -c 'import ensurepip' >/dev/null 2>&1; then
    echo "Missing Python virtual-environment support." >&2
    echo "Install it with: sudo apt update && sudo apt install -y $VENV_PACKAGE" >&2
    exit 1
fi

if ! getent group bindicator >/dev/null; then
    groupadd --system bindicator
fi
if ! id bindicator >/dev/null 2>&1; then
    useradd --system --no-create-home --home-dir /var/lib/bindicator \
        --shell /usr/sbin/nologin --gid bindicator bindicator
fi

install -d -m 0755 /opt/bindicator
# Shared access is restricted to explicit members of the bindicator group.
# setgid keeps new files in the same trusted group.
install -d -o bindicator -g bindicator -m 2770 /var/lib/bindicator
install -d -o root -g bindicator -m 2770 /etc/bindicator
chmod 2770 /var/lib/bindicator /etc/bindicator
cp -a "$SRC_DIR/src" /opt/bindicator/
install -m 0644 "$SRC_DIR/pyproject.toml" /opt/bindicator/pyproject.toml
# PEP 639 license-files metadata requires the file in the build root.
install -m 0644 "$SRC_DIR/LICENSE" /opt/bindicator/LICENSE

# Record the exact source commit INSIDE the installed Python package, since
# /opt/bindicator contains no .git directory. Git is optional for tarball users.
# Use an explicit safe.directory for root installing a user-owned checkout.
SOURCE_COMMIT=""
if command -v git >/dev/null 2>&1; then
    REPO_ROOT="$(git -c safe.directory="$SRC_DIR" -C "$SRC_DIR" rev-parse --show-toplevel 2>/dev/null || true)"
    if [[ "$REPO_ROOT" == "$SRC_DIR" ]]; then
        SOURCE_COMMIT="$(git -c safe.directory="$SRC_DIR" -C "$SRC_DIR" rev-parse --verify HEAD 2>/dev/null || true)"
    fi
fi
if [[ "$SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]]; then
    printf '{"commit":"%s"}\n' "$SOURCE_COMMIT" > /opt/bindicator/src/bindicator/_build_info.json
else
    # Never keep a stale commit from a previous install.
    rm -f /opt/bindicator/src/bindicator/_build_info.json
fi
if [[ -f /opt/bindicator/src/bindicator/_build_info.json ]]; then
    chmod 0644 /opt/bindicator/src/bindicator/_build_info.json
fi

if [[ ! -f /etc/bindicator/config.yaml ]]; then
    install -o root -g bindicator -m 0660 \
        "$SRC_DIR/config.example.yaml" /etc/bindicator/config.yaml
fi
if [[ ! -f /etc/bindicator/secrets.env ]]; then
    install -o root -g bindicator -m 0660 \
        "$SRC_DIR/secrets.example.env" /etc/bindicator/secrets.env
fi

# Migrate existing installations to group access; only approved local users
# should be added to the bindicator group, since it controls Hue lights and
# can read private calendar URLs, provider configuration and Hue keys.
chown root:bindicator /etc/bindicator/config.yaml /etc/bindicator/secrets.env
chmod 0660 /etc/bindicator/config.yaml /etc/bindicator/secrets.env
for file in /var/lib/bindicator/state.json /var/lib/bindicator/calendar.ics /var/lib/bindicator/run.lock /var/lib/bindicator/control.json; do
    if [[ -f "$file" ]]; then
        chgrp bindicator "$file"
        chmod 0660 "$file"
    fi
done

# Generate a strong, stable token for the optional localhost HTTP API.
# Never output it in the installer logs; preserve it across upgrades.
API_TOKEN=/etc/bindicator/api.token
if [[ -e "$API_TOKEN" || -L "$API_TOKEN" ]]; then
    if [[ ! -f "$API_TOKEN" || -L "$API_TOKEN" ]]; then
        echo "Refusing unsafe API token path: $API_TOKEN" >&2
        exit 1
    fi
else
    TOKEN_TEMP="$(mktemp /etc/bindicator/.api-token.XXXXXXXX)"
    python3 -c 'import secrets; print(secrets.token_urlsafe(48))' > "$TOKEN_TEMP"
    install -o root -g bindicator -m 0640 "$TOKEN_TEMP" "$API_TOKEN"
    rm -f "$TOKEN_TEMP"
fi
chown root:bindicator "$API_TOKEN"
chmod 0640 "$API_TOKEN"

# A previous failed installation may have left a partial venv without pip.
if [[ -d /opt/bindicator/.venv && ! -x /opt/bindicator/.venv/bin/pip ]]; then
    echo "Removing incomplete Bindicator virtual environment."
    rm -rf /opt/bindicator/.venv
fi
if ! python3 -m venv /opt/bindicator/.venv; then
    echo "Could not create Bindicator virtual environment; check $VENV_PACKAGE." >&2
    exit 1
fi
/opt/bindicator/.venv/bin/pip install --disable-pip-version-check --no-cache-dir /opt/bindicator
ln -sfn /opt/bindicator/.venv/bin/bindicator /usr/local/bin/bindicator
install -m 0644 "$SRC_DIR/deploy/bindicator.service" /etc/systemd/system/bindicator.service
install -m 0644 "$SRC_DIR/deploy/bindicator.timer" /etc/systemd/system/bindicator.timer
install -m 0644 "$SRC_DIR/deploy/bindicator-scheduler.service" /etc/systemd/system/bindicator-scheduler.service
install -m 0644 "$SRC_DIR/deploy/bindicator-api.service" /etc/systemd/system/bindicator-api.service
install -m 0644 "$SRC_DIR/deploy/bindicator-web.service" /etc/systemd/system/bindicator-web.service
install -m 0644 "$SRC_DIR/deploy/bindicator-council-refresh.service" /etc/systemd/system/bindicator-council-refresh.service
install -m 0644 "$SRC_DIR/deploy/bindicator-council-refresh.timer" /etc/systemd/system/bindicator-council-refresh.timer
systemctl daemon-reload

# Configure the LAN HTTPS endpoint before enabling the web unit. On hosts
# without an assigned private LAN address, leave the web service disabled.
WEB_READY=false
if ! command -v openssl >/dev/null || ! command -v ip >/dev/null; then
    if command -v apt-get >/dev/null; then
        apt-get install -y openssl iproute2 || echo "WARNING: Could not install LAN web prerequisites." >&2
    fi
fi
if command -v openssl >/dev/null && command -v ip >/dev/null; then
    if bash "$SRC_DIR/deploy/setup-lan-web.sh"; then
        WEB_READY=true
    else
        echo "WARNING: LAN management TLS setup failed; web service not enabled." >&2
    fi
else
    echo "WARNING: LAN management web prerequisites unavailable; web service not enabled." >&2
fi

# New installs and upgrades should be operational without manual systemctl
# commands. Restart running services to load upgraded application code.
systemctl enable bindicator-api.service bindicator.timer bindicator-council-refresh.timer
systemctl restart bindicator-api.service bindicator.timer bindicator-council-refresh.timer
if [[ "$WEB_READY" == true ]]; then
    systemctl enable bindicator-web.service
    systemctl restart bindicator-web.service
fi

echo
echo "Bindicator service status:"
for unit in bindicator.timer bindicator-api.service bindicator-web.service bindicator-council-refresh.timer; do
    printf '  %-27s enabled=%-9s active=%s\n' "$unit" \
        "$(systemctl is-enabled "$unit" 2>/dev/null || true)" \
        "$(systemctl is-active "$unit" 2>/dev/null || true)"
done

echo
echo "Installed Bindicator. Next:"
echo "  sudo usermod -aG bindicator YOUR_USERNAME    # Authorise a trusted local user"
echo "  newgrp bindicator                           # Or sign out and back in"
echo "  sudo bindicator --setup                     # auto-discover, pair, select lamps"
echo "  sudo bindicator --setup --fresh             # replace existing Hue configuration"
echo "  sudo -u bindicator bindicator --list-lights"
echo "  sudoedit /etc/bindicator/config.yaml          # Check calendar mappings and Hue settings"
echo "  sudoedit /etc/bindicator/secrets.env          # Set private iCalendar URL (if used)"
echo "  sudo -u bindicator bindicator --check-calendar"
echo "  bindicator --pause / --resume / --toggle    # Temporarily protect Hue scenes"
echo "  bindicator --status                         # Check current pause state"
echo "  curl -fsS http://127.0.0.1:18050/api/v1/health  # Readiness probe"
echo "  See docs/lan-management.md for LAN HTTPS management security and setup."
echo "The timers and API are enabled and started; the LAN web UI is enabled when HTTPS setup succeeds."
