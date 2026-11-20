# Bindicator documentation

This index covers the maintained documentation for the checked-out revision.
Start with the [project README](../README.md) for an overview and installation.

## Contents

- [User and operator guides](#user-and-operator-guides)
- [Calendar integrations and development](#calendar-integrations-and-development)
- [Optional voice and remote integrations](#optional-voice-and-remote-integrations)
- [Security boundaries](#security-boundaries)

## User and operator guides

| Guide | Purpose |
| --- | --- |
| [Installation and upgrade](../README.md#install-and-upgrade) | Current Debian deployment procedure and service units |
| [First-time configuration](../README.md#first-time-configuration) | Guided Hue Bridge pairing and selected lights |
| [LAN dashboard](lan-management.md) | Eight-tab UI, calendar source setup, colour mappings, Hue controls, status and diagnostics |
| [CLI operations](../README.md#command-line-operations) | Common checks, setup, test previews and pause/resume |
| [Local HTTP API](local-api.md) | Authenticated loopback API on port 18050 |

## Calendar integrations and development

| Guide | Purpose |
| --- | --- |
| [Calendar sources and refresh](lan-management.md#calendars-source-selection-and-refresh) | North Yorkshire and generic iCal selection, test access, previews, refresh interval |
| [Calendar provider architecture](calendar-providers.md) | Normalised collection-event contract and shared engine |
| [Add a new council adapter](calendar-providers.md#walkthrough-add-a-new-council-provider) | Example plugin package, tests, installation, configuration and rollback |
| [Provider security](calendar-providers.md#2-replace-the-demonstration-data-with-a-real-council-lookup) | Input validation, secret handling and resilient parsing |

## Optional voice and remote integrations

| Guide | Purpose |
| --- | --- |
| [Alexa custom skill](../alexa/README.md) | Skill setup, Echo Show APL, voice commands, test and troubleshooting |
| [Bin Buddy command cheat sheet](../alexa/COMMANDS.md) | Exact supported utterances from the Alexa interaction model |
| [AWS/S3 Lambda deployment](aws-deployment.md) | Browser login, account verification, one-command deploy, S3 privacy, verification and rollback |
| [Cloudflare Tunnel and Access](cloudflare-setup.md) | Secure access to the **API only**, with service credentials |
| [Cloudflare `cf` CLI](cloudflare-cli.md) | Inspect, create and rotate Access resources |
| [Cloudflare configuration as code](cloudflare-iac.md) | Non-secret desired-state inventory, Terraform import safeguards and future provisioning design |
| [Public-release security](public-release.md) | Audit results, Git history checks, clean-snapshot publication procedure |

## Security boundaries

- The LAN HTTPS dashboard is accessible only to trusted local network
  clients on port **18051**. It does not have per-user logins.
- The authenticated loopback API listens on **127.0.0.1:18050**.
- The optional Cloudflare tunnel routes to the API **only**, never the dashboard.
- Keep iCal URLs, provider identifiers, Hue application keys, API credentials
  and Cloudflare service secrets in restricted local storage.
- Third-party provider packages execute Python within the Bindicator service
  environment and should be installed only from trusted sources.

For full instructions see [LAN management security](lan-management.md#security-and-network-isolation)
and [provider security](calendar-providers.md#registration).
