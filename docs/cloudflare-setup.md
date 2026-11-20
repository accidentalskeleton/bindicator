# Cloudflare setup for Bindicator

## Contents

- [Architecture](#architecture)
- [Tunnel on Debian](#tunnel-on-debian)
- [Access security and hostname](#access-security-and-hostname)
- [Verify without AWS](#verify-without-aws)
- [Related docs](#related-docs)

This guide configures the protected API endpoint independently of AWS Lambda.
For installation of the Cloudflare management CLI and CLI commands for
**creating, inspecting or rotating** Access resources, see
[Cloudflare CLI reference](cloudflare-cli.md).

> **Port migration (18740 → 18050):** If the tunnel already exists, update its
> published application's origin service URL to `http://127.0.0.1:18050`
> and its HTTP Host Header override to `127.0.0.1:18050` in the Cloudflare
> dashboard. Reinstalling Bindicator does **not** edit remotely managed
> Cloudflare tunnel settings. Leave the LAN management UI on port 18051
> private; do not add it as a public tunnel route.

## Architecture

`https://bins.example.com` → Cloudflare Access (**Service Auth**) →
`bindicator-tunnel` tunnel on the Bindicator host → `http://127.0.0.1:18050` →
Bindicator API (**separate Bearer token**). Do not configure router forwarding,
public listening interfaces or an Access Bypass/Everyone policy.

## Tunnel on Debian

Install Cloudflare's official `cloudflared` Debian package:

```bash
sudo mkdir -p -m 0755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
  | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' \
  | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt-get update
sudo apt-get install -y cloudflared
```

Create a remotely managed tunnel named `bindicator-tunnel` under **Zero Trust →
Networking → Tunnels**. On the Bindicator host, run Cloudflare's generated connector
installation command; **never share the tunnel token**. Verify:

```bash
sudo systemctl is-enabled cloudflared
sudo systemctl is-active cloudflared
sudo journalctl -u cloudflared -n 30 --no-pager -l
```

Look for registered QUIC/HTTP2 connections. No inbound EE Hub ports are needed.

## Access security and hostname

**Create Access protection before publishing the route**:

1. **Access controls → Service credentials → Service tokens**: create
   `bindicator-alexa`. Save its Client ID and Client Secret in a password manager.
2. **Access controls → Applications**: create a **Self-hosted** application for
   `bins.example.com`. Choose a descriptive application display name, such as `Bindicator Alexa`
   (display name and hostname are separate settings).
3. Attach policy `Bindicator Alexa`, action **Service Auth**, with **Include →
   Service Token → bindicator-alexa**; no additional Require or Exclude conditions.
4. **Networking → Tunnels → bindicator-tunnel → Published applications**:
   publish `bins.example.com` with upstream
   `http://127.0.0.1:18050`, no path restriction; set **HTTP Host Header**
   override to `127.0.0.1:18050`. This override is required by the API's
   localhost Host check.

See [CLI reference](cloudflare-cli.md) for ways to create and verify these
resources programmatically. The CLI does not replace `cloudflared` itself.

## Verify without AWS

```bash
curl -i http://127.0.0.1:18050/api/v1/health
curl -sS -o /dev/null -w 'Unauthenticated HTTP %{http_code}\n' \
  https://bins.example.com/api/v1/status
```

The local health endpoint should return HTTP 200. An unauthenticated public
status request must be rejected by Cloudflare (typically 401/403).

Enter credentials **without printing them**; do not use `curl -v` because it
logs request headers, including the secret:

```bash
read -r -p 'Cloudflare Client ID: ' CF_CLIENT_ID
read -r -s -p 'Cloudflare Client Secret: ' CF_CLIENT_SECRET; echo
read -r API_TOKEN < /etc/bindicator/api.token

curl -sS -w '\nHTTP %{http_code}\n' \
  -H "CF-Access-Client-Id: $CF_CLIENT_ID" \
  -H "CF-Access-Client-Secret: $CF_CLIENT_SECRET" \
  -H "Authorization: Bearer $API_TOKEN" \
  https://bins.example.com/api/v1/collections/next

unset CF_CLIENT_ID CF_CLIENT_SECRET API_TOKEN
```

Expected: HTTP 200 with a JSON collection date, event names and colours.
If Cloudflare returns an HTML 401, check its service-token authentication and
Access logs. A JSON 401 from the application means Access has passed but
Bindicator's Bearer token was missing/invalid. `Server: cloudflare` can appear
on **proxied origin responses**, so inspect content type and response body too.

## Related docs

- [Documentation index](README.md)
- [Project README](../README.md)
- [LAN management](lan-management.md)
- [Cloudflare CLI — install, creation, inspection and rotation](cloudflare-cli.md)
- [Cloudflare configuration as code and Terraform migration](cloudflare-iac.md)
- [Local Bindicator HTTP API](local-api.md)
- [Alexa deployment](../alexa/README.md)
