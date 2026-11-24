# Bindicator

**Bindicator** is a self-hosted, subscription-free bin collection reminder for
Debian/Linux. It reads collection dates from **North Yorkshire Council**,
**iCalendar (iCal)** feeds (including Zoho, Google Calendar and Outlook), or
other trusted installed calendar-provider plugins. It then uses your chosen
**Philips Hue lights** to indicate the next collection.

The application has a LAN-only HTTPS dashboard, authenticated local API,
optional Alexa integration, multi-Bridge Hue support and a shared calendar
provider engine. It runs on a machine available 24/7, such as the Bindicator host.

## Contents

- [Features](#features)
- [Documentation](#documentation)
- [Releases and changelog](#releases-and-changelog)
- [Install and upgrade](#install-and-upgrade)
- [First-time configuration](#first-time-configuration)
- [Dashboard and calendar sources](#dashboard-and-calendar-sources)
- [Scheduling and refresh](#scheduling-and-refresh)
- [Command-line operations](#command-line-operations)
- [Security](#security)
- [Development and tests](#development-and-tests)
- [Licence and acknowledgements](#licence-and-acknowledgements)

## Features

- **Calendar sources:** North Yorkshire Council (UPRN lookup), generic HTTPS
  iCalendar feeds, and installable trusted Python calendar providers.
- **Provider-neutral engine:** normalised collection events, calendar source
  selection, per-source caches, source checks and date previews.
- **Hue lighting:** multiple Hue Bridges, up to five configured colours,
  priority/spread/cycle modes, gradient-aware lights and saved-state restoration.
- **Calendar mappings:** assign multiple event titles to the same colour;
  order colours by priority.
- **Scheduling:** automatic reminder windows (default: 18:00 the day before,
  restoration at 09:00 on collection day), and a daily calendar refresh check
  governed by a configurable **1–90 day** interval (default **7 days**).
- **Management:** eight-tab LAN-only HTTPS interface with live status, previews,
  lighting setup, colour editing, calendar configuration and mappings.
- **Integrations:** authenticated loopback API and optional private Alexa skill.
- **Safety:** read-only calendar lookups, bounded cache fallback, retained Hue
  state, restricted local credentials, and Python test coverage.

## Documentation

| Guide | What it covers |
| --- | --- |
| [Documentation index](docs/README.md) | All maintained user and developer guides |
| [LAN management](docs/lan-management.md) | Eight-tab dashboard, access controls, calendars, Hue management and diagnostics |
| [Calendar providers](docs/calendar-providers.md) | Normalised model and step-by-step guide to building, testing and installing another council adapter |
| [Local API](docs/local-api.md) | API setup, authenticated endpoints and safe testing |
| [Alexa skill](alexa/README.md) | Bin Buddy voice skill, Echo Show APL and deployment |
| [Bin Buddy spoken commands](alexa/COMMANDS.md) | Supported phrases and confirmation behaviour |
| [AWS deployment](docs/aws-deployment.md) | Private S3 ZIP upload, verified Lambda targets and one-command deploy |
| [Cloudflare setup](docs/cloudflare-setup.md) | Secure tunnel and service authentication for Alexa only |
| [Cloudflare CLI](docs/cloudflare-cli.md) | Optional Cloudflare command-line operations |
| [Cloudflare infrastructure as code](docs/cloudflare-iac.md) | Declarative resource inventory and safe Terraform adoption plan |
| [Public-release security checklist](docs/public-release.md) | Privacy review, secret/history scans, clean-snapshot publication process |

## Releases and changelog

- [Changelog](CHANGELOG.md) — notable changes by version.
- [v0.1.0 release notes](docs/releases/v0.1.0.md) — first public release,
  installation instructions, security considerations and limitations.
- [GitHub releases](https://github.com/accidentalskeleton/bindicator/releases)
  — downloadable source archives and release history.

For reproducible installation after the first release is tagged, check out
`v0.1.0` instead of installing whatever is currently on `main`.
A tagged release identifies a fixed source revision; the Help tab also
reports the installed Git commit when available.

## Install and upgrade

**Requirements:** Debian 13 or compatible Linux with systemd, Python 3.11+,
Python virtual-environment support (`python3-venv` or matching
`python3.X-venv`), network access, and Philips Hue Bridges/lights for
lighting reminders. The installer requires root privileges, sets up a
restricted service account and enables the required systemd units. Make
sure you trust this repository before running the installer as root.
Run from a trusted account on the Bindicator host:

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-venv

git clone https://github.com/accidentalskeleton/bindicator.git ~/code/bindicator
cd ~/code/bindicator
sudo bash deploy/install.sh
```

If already cloned, update using the current main branch:

```bash
cd ~/code/bindicator
git switch main
git pull --ff-only origin main
sudo bash deploy/install.sh
```

The installer installs its own Python virtual environment and dependencies;
no developer `.venv` is needed for the normal service installation.

**The installer enables and starts** `bindicator.timer`,
`bindicator-council-refresh.timer` (legacy name; refreshes any active source),
`bindicator-api.service`, and `bindicator-web.service` when LAN TLS
configuration succeeds. Service units run as the restricted `bindicator` user.
Do not expose the LAN web port publicly.

Important paths:

| Path | Purpose |
| --- | --- |
| `/etc/bindicator/config.yaml` | Hue, mappings, calendar provider and interval settings |
| `/etc/bindicator/secrets.env` | Private iCal URL and Hue application keys |
| `/var/lib/bindicator/` | Operational state and per-provider verified caches |
| `/opt/bindicator/.venv/` | Installed application environment |
| `/etc/systemd/system/bindicator*.service` and `*.timer` | System services |

Upgrades retain your local configuration, secrets and existing verified
calendar caches. When installing from a Git checkout, the installer records
the exact source commit inside the installed package. The Help tab shows,
for example, `0.1.0 (abcdef0)`; tarball installs without Git metadata show
only the package version. This does not require Git at runtime.

## First-time configuration

1. If needed, enrol an authorised local administrator in the `bindicator`
   group (membership grants access to private credentials and light controls).
2. Run `sudo bindicator --setup` in an interactive terminal to discover Hue
   Bridges, pair them by pressing each Bridge's link button, and choose lights.
3. Open the HTTPS dashboard on the host's LAN IP or its configured hostname
   (for example `https://bindicator-host:18051/`). Your browser will initially warn
   about the locally generated self-signed certificate.
4. Under **Calendars**, enter the North Yorkshire UPRN or private iCalendar
   URL; use **Test access** and **Preview dates** to verify the results.
5. Choose the **Active source**, configure refresh cadence (7 days by default),
   and save.
6. Under **Colours**, configure indicator colours; under **Mapping**, assign
   exact source event titles to those colours.
7. Review **Status** and test previews under **Testing**. Check the Hue lights
   restore to their previous appearance.

See [LAN management](docs/lan-management.md) for detailed safe access and
configuration, and [Calendar providers](docs/calendar-providers.md) for
installing an additional source.

## Dashboard and calendar sources

The dashboard has eight tabs in order:

| Tab | Function |
| --- | --- |
| **Status** | Current reminder state, upcoming collection days, bin icons, last calendar refresh |
| **Testing** | Temporarily preview each saved colour or collection alert |
| **Lighting** | Hue Bridges, selected lamps, timing and display options |
| **Colours** | Colour picker and priority order |
| **Calendars** | Active source, shared refresh interval, manual refresh and provider credentials |
| **Mapping** | Searchable event-to-colour multi-select; several titles can share a colour |
| **Help** | Installed Bindicator package version and source Git commit, GitHub project, documentation, releases and issues |
| **☕ Coffee** | Optional Buy Me a Coffee support link, matching Lyrion Carousel |

North Yorkshire and iCalendar are the two built-in sources. Adding a trusted
provider to the [registry](docs/calendar-providers.md) adds it to source
discovery, but **provider-specific settings forms are not automatically
generated** for third-party plugins yet.

## Scheduling and refresh

`bindicator.timer` checks the configured reminder schedule each minute; that
does **not** mean it downloads calendar data every minute. The independent
`bindicator-council-refresh.timer` checks the **active** provider each morning
at roughly **07:10 Europe/London**, plus up to 15 minutes of random delay.
The shared engine fetches only when the configured refresh interval has elapsed
(default **7 days**), or when the user explicitly selects
**Refresh active calendar now**.

A successful response is cached by provider. During a temporary failure, the
previous verified data may be used for up to 72 hours **beyond the configured
refresh due time**. Failed manual refreshes report an error and preserve the
last good data. Changing provider settings invalidates the matching cache.

```bash
systemctl list-timers bindicator.timer bindicator-council-refresh.timer
systemctl is-active bindicator.timer bindicator-api.service bindicator-web.service
sudo -u bindicator bindicator --check-calendar
```

## Command-line operations

```bash
sudo bindicator --setup                  # Guided Hue setup
sudo bindicator --setup --fresh          # Replace Hue setup (confirmation required)
sudo -u bindicator bindicator --list-lights
sudo -u bindicator bindicator --check-calendar
sudo -u bindicator bindicator --list-bin-types
sudo -u bindicator bindicator --dry-run
sudo -u bindicator bindicator --status
bindicator --pause
bindicator --resume
bindicator --toggle
bindicator --next-collection --seconds 10   # Timed preview and restoration
bindicator --test-bin "Recycling" --seconds 10
bindicator --help
```

**Caution:** `--next-collection` without `--seconds` initiates a persistent
reminder rather than a short-lived preview. Configure a finite duration for
testing. Always use a suitably authorised local account.

## Security

- The HTTPS management page is for trusted **LAN devices only**; it has no
  separate user login. Never publish port **18051** through a tunnel.
- The local API binds to `127.0.0.1:18050` and requires its own token for
  protected operations.
- Cloudflare Tunnel/Access and AWS Lambda are **optional Alexa components**,
  not a route to expose the dashboard.
- Keep iCal tokens, Hue application keys and council property identifiers
  out of source control, CI logs and screenshots.
- Third-party calendar provider packages run trusted Python code inside the
  Bindicator environment. Review them before installation.

Read [LAN security](docs/lan-management.md#security-and-network-isolation),
[Cloudflare setup](docs/cloudflare-setup.md), and
[Provider security](docs/calendar-providers.md#2-replace-the-demonstration-data-with-a-real-council-lookup).

## Development and tests

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q
```

A lightweight read-only GitHub Actions job runs on pull requests to `main`
using the standard Linux runner, with an optional manual trigger. It does not
install the service or access real Hue, calendar or AWS credentials. Run the
suite locally before installing or deploying; passing tests do not verify
AWS or Echo Show hardware behaviour.
To build another council integration, start with the
[calendar-provider walkthrough](docs/calendar-providers.md#walkthrough-add-a-new-council-provider).

## Licence and acknowledgements

Copyright © 2026 Stuart Roberts and Bindicator contributors.

Bindicator is released under the [GNU General Public License v3.0](LICENSE)
(`GPL-3.0-only`), consistent with Lyrion Carousel. The bundled Bindicator
artwork is included under the project licence where the project owns the
rights; see [copyright and artwork provenance](COPYRIGHT.md) for the current
verification limits. External Python libraries retain their original terms:
[third-party software and licences](THIRD_PARTY_NOTICES.md).

Philips Hue, Alexa, AWS, Cloudflare, and calendar provider names are trademarks
of their respective owners. This project is not endorsed by those companies.
