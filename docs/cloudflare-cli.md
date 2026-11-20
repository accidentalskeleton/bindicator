# Cloudflare `cf` CLI reference

## Contents

- [Install Node.js 24 and cf](#install-nodejs-24-and-cf)
- [Inspect the existing configuration (read-only)](#inspect-the-existing-configuration-read-only)
- [Create resources with the CLI](#create-resources-with-the-cli)
- [Get or rotate a Client Secret](#get-or-rotate-a-client-secret)
- [Testing and troubleshooting](#testing-and-troubleshooting)
- [Related documentation](#related-documentation)

`cf` is Cloudflare's **beta management CLI** (not the
`cloudflared` connector). The steps below describe Debian 13 / the Bindicator host
using `cf v1.0.0-beta.29`. The CLI is generated from Cloudflare's API and
flags can change: check `--help` and `cf schema` for the installed version
**before running write commands**.

## Install Node.js 24 and cf

`cf` requires Node.js 22.18 or later. On the Bindicator host:

```bash
sudo apt-get update
sudo apt-get install -y curl ca-certificates gnupg
curl -fsSL https://deb.nodesource.com/setup_24.x | sudo -E bash -
sudo apt-get install -y nodejs
node --version
npm --version
sudo npm install --global cf
cf --version
cf auth login --no-browser
cf auth whoami
```

The SSH-friendly login prints a URL and one-time code for authorisation
from another computer. The resulting OAuth credentials live under the user's
`~/.config/cloudflare/`; treat them as secrets. `cf auth whoami` is verbose:
it includes account details, permissions, and token metadata.

## Inspect the existing configuration (read-only)

**These exact list commands were exercised against `cf v1.0.0-beta.29`.**
Do not add `--account-id` to them: that flag was rejected in this version.

```bash
cf zero-trust access applications list
cf zero-trust access policies list
cf zero-trust access service-tokens list
```

Check that:

- The self-hosted application covers `bins.example.com`.
- The attached `Bindicator Alexa` policy uses `decision: non_identity`
  (API representation of **Service Auth**) and has an Include rule of type
  `service_token`, with no Require/Exclude rules.
- Its `token_id` matches the enabled `bindicator-alexa` service token's
  `id`, and `expires_at` is in the future.

Example resource identifiers to discover in your own account (do not use these placeholders in API requests):

| Resource | ID |
| --- | --- |
| Cloudflare account | `YOUR_CLOUDFLARE_ACCOUNT_ID` |
| Access application | `YOUR_ACCESS_APPLICATION_ID` |
| Reusable policy | `YOUR_ACCESS_POLICY_ID` |
| Service token | `YOUR_SERVICE_TOKEN_ID` |

## Create resources with the CLI

The CLI supports create commands for service tokens, reusable policies and
Access applications. **Creation has not been exercised against this account**;
do not create duplicates of the already working Bindicator resources.

Use the installed version's schemas to discover the exact required flags,
input JSON fields, positional arguments and account selection:

```bash
cf cli search "create Access service token"
cf cli search "create reusable Access policy"
cf cli search "create Access application"
cf cli search "create Access application policy"
cf cli search "create Cloudflare tunnel"
cf cli search "add tunnel public hostname route"

cf zero-trust access service-tokens create --help
cf zero-trust access policies create --help
cf zero-trust access applications create --help
cf zero-trust access applications policies create --help

cf schema zero-trust access service-tokens create
cf schema zero-trust access policies create
cf schema zero-trust access applications create
```

For new installations, create resources in this order:

1. **Service token**: name `bindicator-alexa`, enabled, limited expiration
   appropriate for your rotation practice. **Creation returns a Client Secret
   only once**: save it securely, avoid terminal capture/logging.
2. **Reusable policy**: `Bindicator Alexa`, decision `non_identity`, Include
   `{"service_token":{"token_id":"<new-token-UUID>"}}`, empty Require and
   Exclude arrays.
3. **Self-hosted application**: domain `bins.example.com`, attach the
   policy ID. Verify `policies` on the returned application before publishing.
4. **Tunnel and hostname route**: connector on the Bindicator host, HTTP upstream
   `127.0.0.1:18050`, HTTP Host override `127.0.0.1:18050`. Verify the
   tunnel and route through the CLI or dashboard.

These are **configuration values**, not copy/paste executable create commands:
the exact command flags are obtained from `--help`/`cf schema` to avoid
accidentally writing malformed or unauthenticated resources. For reproducible
unattended provisioning, use Cloudflare's documented Access APIs or Terraform
and protect the state file, which contains secrets.

## Get or rotate a Client Secret

**Yes, via CLI/API for a new or rotated secret.** Cloudflare **does not let
you retrieve the existing secret** using a read/list/get call.

Discover the write command and arguments:

```bash
cf zero-trust access service-tokens update --help
cf schema zero-trust access service-tokens update
cf zero-trust access service-tokens create --help
```

Cloudflare's [service-token API](https://developers.cloudflare.com/api/resources/zero_trust/subresources/access/subresources/service_tokens/)
rotates the secret by **incrementing `client_secret_version` on Update**,
optionally controlling the old secret's grace period with
`previous_client_secret_expires_at`. The updated secret is shown in the
write response; store it securely and update AWS Lambda's
`CF_ACCESS_CLIENT_SECRET` before retiring the previous version.
Alternatively create a **new token**, attach its ID to the policy and test,
then revoke the old token. For leaked secrets, avoid any grace period.

**Do not mistake this for `service-tokens refresh`: `refresh` extends token
expiration and does not rotate the secret.** Likewise, `get` or `list`
cannot recover the original secret. Do not paste write-command output into
tickets, chats, screenshots or GitHub.

For UI rotation, use **Access controls → Service credentials → Service
tokens**, select the token and rotate its Client Secret.

## Testing and troubleshooting

See the [Cloudflare setup guide](cloudflare-setup.md) for safe `curl`
requests through both security layers. Do not use `curl -v` with credential
headers: verbose traces expose the Client Secret. Never disable Access to
diagnose an authentication problem.

Official references:
[Cloudflare CLI](https://developers.cloudflare.com/cf/),
[CLI resource management](https://developers.cloudflare.com/cf/get-started/resources/),
[Service tokens](https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/).

## Related documentation

For repeatable configuration, see [Cloudflare infrastructure as code](cloudflare-iac.md).
The current desired-state JSON is an inventory, not yet executable Terraform.


- [Documentation index](README.md)
- [Bindicator setup](../README.md)
- [Cloudflare Tunnel/Access guide](cloudflare-setup.md)
- [Authenticated local API](local-api.md)
- [Alexa integration](../alexa/README.md)
