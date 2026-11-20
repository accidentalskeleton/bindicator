#!/usr/bin/env bash
# Prepare Bindicator's optional LAN HTTPS management interface.
# Called by install.sh after creating /etc/bindicator and the bindicator group.
# The installer enables/starts the service after HTTPS setup succeeds.
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root." >&2
  exit 1
fi

CONFIG_DIR="${BINDICATOR_WEB_CONFIG_DIR:-/etc/bindicator}"
command -v ip >/dev/null || { echo "iproute2 is required to detect the LAN IP." >&2; exit 1; }
command -v openssl >/dev/null || { echo "openssl is required for LAN HTTPS." >&2; exit 1; }

# Prefer the IPv4 source address for the default route. This is discovery
# only: the address must also exist on an interface and be RFC1918.
DETECTED_LAN_IP="$(ip -j -4 addr show scope global | python3 -c '
import ipaddress, json, sys
items = json.load(sys.stdin)
valid = []
for dev in items:
    if dev.get("ifname", "").startswith(("docker", "br-", "veth", "virbr", "tailscale", "tun", "wg")):
        continue
    for a in dev.get("addr_info", []):
        try:
            ip = ipaddress.IPv4Address(a["local"])
        except (KeyError, ValueError):
            continue
        if ip in ipaddress.ip_network("10.0.0.0/8") or ip in ipaddress.ip_network("172.16.0.0/12") or ip in ipaddress.ip_network("192.168.0.0/16"):
            valid.append(str(ip))
print(valid[0] if valid else "")
')"

LAN_IP="${BINDICATOR_LAN_IP:-$DETECTED_LAN_IP}"
if [[ -z "$LAN_IP" ]]; then
  echo "No RFC1918 LAN IPv4 address found. Web UI remains unconfigured." >&2
  exit 1
fi

# Reject an override that is not an assigned private IPv4.
if ! ip -j -4 addr show scope global | python3 -c '
import ipaddress, json, sys
try:
    ip = ipaddress.IPv4Address(sys.argv[1])
    valid = any(ip in n for n in (
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16")))
    assigned = any(str(ip) == a.get("local") for iface in json.load(sys.stdin)
        for a in iface.get("addr_info", []))
    sys.exit(0 if valid and assigned else 1)
except ValueError:
    sys.exit(1)
' "$LAN_IP"; then
    echo "LAN IP must be an RFC1918 address assigned to mrlazy." >&2
    exit 1
fi

# Only a local, single-label machine hostname is admitted to the Host allowlist.
LAN_HOSTNAME="$(hostname -s | tr '[:upper:]' '[:lower:]')"
if [[ ! "$LAN_HOSTNAME" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$ ]]; then
  echo "Invalid local hostname; refusing LAN management configuration." >&2
  exit 1
fi

mkdir -p "$CONFIG_DIR"
ENV_FILE="$CONFIG_DIR/web.env"
CRT_FILE="$CONFIG_DIR/web.crt"
KEY_FILE="$CONFIG_DIR/web.key"

# Refuse symlinks and unexpected existing files before modifying anything.
for p in "$ENV_FILE" "$CRT_FILE" "$KEY_FILE"; do
  if [[ -L "$p" || ( -e "$p" && ! -f "$p" ) ]]; then
    echo "Unsafe LAN web configuration file: $p" >&2
    exit 1
  fi
done

# Avoid clobbering certificates unless they are missing, expired, mismatched
# to the detected address, or have a mismatched/invalid key.
RENEW=false
if [[ ! -s "$CRT_FILE" || ! -s "$KEY_FILE" ]]; then
  RENEW=true
elif ! openssl x509 -in "$CRT_FILE" -noout -checkend 2592000 >/dev/null 2>&1; then
  RENEW=true
elif ! openssl x509 -in "$CRT_FILE" -noout -ext subjectAltName 2>/dev/null | grep -Fq "IP Address:$LAN_IP"; then
  RENEW=true
elif ! openssl x509 -in "$CRT_FILE" -noout -ext subjectAltName 2>/dev/null | grep -Fq "DNS:$LAN_HOSTNAME"; then
  RENEW=true
elif ! openssl x509 -in "$CRT_FILE" -noout -pubkey 2>/dev/null | cmp -s - <(openssl pkey -in "$KEY_FILE" -pubout 2>/dev/null); then
  RENEW=true
fi

if [[ "$RENEW" == true ]]; then
  tmpdir="$(mktemp -d "$CONFIG_DIR/.web-tls.XXXXXXXX")"
  trap 'rm -rf -- "$tmpdir"' EXIT
  openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 825 \
    -keyout "$tmpdir/web.key" -out "$tmpdir/web.crt" \
    -subj "/CN=$LAN_HOSTNAME" -addext "subjectAltName=IP:$LAN_IP,DNS:$LAN_HOSTNAME" >/dev/null 2>&1
  install -o root -g bindicator -m 0640 "$tmpdir/web.key" "$KEY_FILE"
  install -o root -g bindicator -m 0644 "$tmpdir/web.crt" "$CRT_FILE"
  rm -rf -- "$tmpdir"
  trap - EXIT
  echo "Generated LAN HTTPS certificate for $LAN_IP."
else
  chown root:bindicator "$CRT_FILE" "$KEY_FILE"
  chmod 0644 "$CRT_FILE"
  chmod 0640 "$KEY_FILE"
  echo "Reusing existing LAN HTTPS certificate for $LAN_IP."
fi

tmpenv="$(mktemp "$CONFIG_DIR/.web-env.XXXXXXXX")"
trap 'rm -f -- "$tmpenv"' EXIT
printf 'BINDICATOR_LAN_IP=%s\nBINDICATOR_LAN_HOSTNAME=%s\n' "$LAN_IP" "$LAN_HOSTNAME" > "$tmpenv"
install -o root -g bindicator -m 0640 "$tmpenv" "$ENV_FILE"
rm -f -- "$tmpenv"
trap - EXIT

echo "LAN management configured at https://$LAN_IP:18051/ and https://$LAN_HOSTNAME:18051/ (self-signed HTTPS)."
echo "LAN HTTPS configuration ready for the installer to enable bindicator-web.service."
