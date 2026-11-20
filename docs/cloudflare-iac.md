# Cloudflare configuration as code for Bindicator

## Contents

- [Current setup](#current-setup)
- [CLI and Terraform](#cli-and-terraform)
- [Existing deployment inventory](#existing-deployment-inventory)
- [Read-only preflight](#read-only-preflight)
- [Provisioning design](#provisioning-design)
- [Importing existing resources](#importing-existing-resources)
- [Secrets and manual steps](#secrets-and-manual-steps)
- [Verification](#verification)

## Current setup

For an existing installation, Cloudflare Tunnel and Access may already work.
Do **not** create duplicate tunnels, Access applications or service tokens.

A generic, non-secret, machine-readable example and security contract is in
[`deploy/cloudflare/desired-state.json`](../deploy/cloudflare/desired-state.json).
This is **not** an executable Terraform configuration. It records what
an eventual Terraform configuration must preserve; applying Terraform to
live Cloudflare resources requires further provider-specific work and imports.

## CLI and Terraform

- Cloudflare's [`cf` CLI](https://developers.cloudflare.com/cf/) (currently
  beta) supports inspecting and manipulating Access resources. It differs from
  the `cloudflared` tunnel connector that runs on the Bindicator host.
  See [the version-tested CLI guide](cloudflare-cli.md).
- [Cloudflare Terraform provider](https://developers.cloudflare.com/tunnel/guides/terraform/)
  supports tunnels, configurations, DNS and Zero Trust Access resources.
  This is preferable for the **desired state** of repeatable installations.
- [`cf-terraforming`](https://github.com/cloudflare/cf-terraforming) can
  help generate import statements/configurations for existing resources, but
  its output still requires a careful review and provider-schema validation.

The Cloudflare provider v5 has breaking resource names and schema changes
from v4. Existing inline and reusable Access policies may need special
care during migration: never blindly apply generated Terraform.

## Existing deployment inventory

| Resource | Current value |
| --- | --- |
| Cloudflare account | `YOUR_CLOUDFLARE_ACCOUNT_ID` |
| Public hostname | `bins.example.com` |
| Tunnel name | `bindicator-tunnel` |
| Access application ID | `YOUR_ACCESS_APPLICATION_ID` |
| Access reusable policy ID | `YOUR_ACCESS_POLICY_ID` |
| Access service token ID | `YOUR_SERVICE_TOKEN_ID` |
| Origin service | `http://127.0.0.1:18050` |
| Origin HTTP Host header override | `127.0.0.1:18050` |
| LAN dashboard | Port `18051`, **not public** |

The Access application must use a Service Auth (`non_identity`) policy
restricted to the intended service token. The local Bindicator API has a
second, independent bearer-token check.

## Read-only preflight

```bash
cd ~/code/bindicator
python3 -m json.tool deploy/cloudflare/desired-state.json >/dev/null
cf --version
cf zero-trust access applications list
cf zero-trust access policies list
cf zero-trust access service-tokens list
```

The three list commands were exercised on `cf v1.0.0-beta.29`; check the
installed CLI's `--help` and `cf schema` before writing to Cloudflare.
Discover the existing **tunnel ID, DNS zone ID, application policies and
origin settings** before generating import statements. They are not all
present in the checked-in inventory; do not invent them.

## Provisioning design

The eventual unified installer should have the following controlled phases:

1. **Preflight**: check Debian/Python/Terraform/Cloudflare/AWS/ASK CLI
   versions; confirm AWS account, Cloudflare account/zone and Alexa vendor.
2. **Adopt or create Cloudflare resources**: tunnel, connector, DNS
   hostname, Access service token, policy and application. Secure Access
   before publishing the hostname. Never tunnel port `18051`.
3. **Adopt or create AWS resources**: private S3 bucket, least-privilege
   Lambda execution role, Lambda function and permission for **the
   specific Alexa skill ID** to invoke it.
4. **Alexa skill**: use Amazon ASK CLI/SMAPI for skill manifest, interaction
   model, APL interface and endpoint. Alexa is not currently represented
   by a maintained official Terraform provider; keep it in a separate
   declarative skill package rather than assuming Terraform can manage it.
5. **Secure credentials**: place service-token secrets, the Bindicator
   API token and skill ID in the appropriate restricted locations.
6. **Verify**: local loopback API, denied unauthenticated Cloudflare
   route, authenticated read-only route, Lambda status and Echo Show output.

The **current repository does not yet implement** all these phases.
This document describes a planned installer, not a command that can
be executed unattended today. Provisioning must be **idempotent**, adopt
existing resources, show a no-write plan and request explicit approval
before writes.

## Importing existing resources

For this working installation, start by exporting an inventory and
checking **Terraform state ownership**. Import each resource before
attempting a first `terraform apply`. An import does not change the
remote object, but a subsequent apply **can** replace it if the authored
configuration differs from the deployed object.

Terraform can store service token secrets and other sensitive values in
its state. Use an encrypted, access-controlled backend; do not commit
`*.tfstate`, plan files, provider credentials or generated token secrets.
A local `.gitignore` is not a substitute for restricted state access.

Before any future apply, require `terraform plan` review. Do not apply
a plan containing **destroy/replace** on the existing tunnel, DNS, Access
application, token or Lambda without an explicit migration decision.

## Secrets and manual steps

Authentication still requires user consent: AWS browser login,
Cloudflare authentication and Amazon Developer OAuth for ASK CLI.
Hue Bridge pairing requires pressing the physical link button.

Cloudflare returns a service token's Client Secret when created or
rotated, not through a later normal read. Importing an existing token
does not recover the secret. Do not automatically rotate a working token
just to populate Terraform state. The secret can remain managed in a
separate restricted secret store, and Lambda environment configuration
should avoid leaking it via CLI output.

## Verification

```bash
curl -fsS http://127.0.0.1:18050/api/v1/health
curl -sS -o /dev/null -w 'Unauthenticated status HTTP %{http_code}\n' \
  https://bins.example.com/api/v1/status
```

Expect the first request to succeed and the second to be denied by
Cloudflare Access (typically 401/403). Only the protected API, not the
passwordless LAN management page, should be publicly routed.

See [Cloudflare CLI](cloudflare-cli.md), [Cloudflare setup](cloudflare-setup.md),
[AWS deployment](aws-deployment.md) and [Alexa skill](../alexa/README.md).
