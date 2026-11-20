# LAN-only Bindicator management page

## Contents

- [Security and network isolation](#security-and-network-isolation)
- [Install on the Bindicator host](#install-on-mrlazy)
- [Calendars: source selection and refresh](#calendars-source-selection-and-refresh)
- [North Yorkshire Council source (opt-in)](#north-yorkshire-council-source-opt-in)
- [Tabs](#tabs)
- [Verify deployment and isolation](#verify-deployment-and-isolation)
- [Related docs](#related-docs)

The LAN-only browser interface manages Hue Bridges, lights and colours,
collection calendars, event mappings and reminder previews. It also shows
upcoming collection days and the active provider's refresh status. Calendar
credentials and Hue application keys are never returned to the browser.

This is a **separate HTTPS server** on port **18051**, not the Alexa API
(`127.0.0.1:18050`). The existing Cloudflare route must remain pointed
**only at port 18050**. Do not add 18051 as a tunnel route.

## Security and network isolation

The management webpage is deliberately **passwordless** for a trusted,
single-user LAN. It binds to the detected private IPv4 address on the Bindicator host,
requires local HTTPS, allows only the configured private IP and local machine hostname in the Host header, checks that POST Origin matches the requested host, and uses a
non-simple header for state-changing requests. The application does not
expose Hue credentials or your private iCalendar feed URL.

**Anyone who can reach port 18051 on the LAN can operate lights and change
configuration**. Restrict port 18051 to trusted local devices using your
host firewall or network isolation. Do not forward it on your router, add
it to the Cloudflare Tunnel, or allow access from guest Wi-Fi/untrusted VLANs.

The installer generates a **self-signed** certificate. Browsers will display
a certificate warning until you explicitly trust the certificate.

## Install on the Bindicator host

The installer automatically detects an RFC1918 LAN IPv4 address, creates
`/etc/bindicator/web.env`, and generates a self-signed certificate/key at
`/etc/bindicator/web.crt` and `web.key`. On later runs, it reuses a valid
certificate with both IP and hostname DNS subject-alternative-names, and renews it if needed (including if the IP or machine hostname changes). When upgrading from an IP-only certificate, the first reinstall regenerates the self-signed certificate, so previously trusted certificate exceptions may need renewal. The installer **automatically enables and starts** the LAN management service when HTTPS provisioning succeeds. It also enables and starts the authenticated loopback API and collection timer. If LAN HTTPS provisioning fails, only the web service is skipped.

```bash
sudo apt-get update
sudo apt-get install -y openssl iproute2

cd ~/code/bindicator
git switch main
git fetch origin
git pull --ff-only origin main
sudo bash deploy/install.sh

# Verify detected private LAN IP without displaying any secrets:
sudo cat /etc/bindicator/web.env

# The installer enabled and started the LAN webpage:
systemctl is-enabled bindicator-web.service
sudo systemctl status bindicator-web.service --no-pager
```

Open **`https://bindicator-host:18051/`** (when that hostname resolves on the LAN), or **`https://DETECTED_LAN_IP:18051/`** from a trusted computer on the
same network, replacing `DETECTED_LAN_IP` with the value in `web.env`.
There is no login or password.

If multiple private interfaces are present, the installer picks the first
non-virtual RFC1918 address. Check `web.env` before enabling the service;
if it chose the wrong NIC, rerun setup with a validated override:
`sudo BINDICATOR_LAN_IP=192.168.1.20 bash deploy/setup-lan-web.sh`
(replace the example address with the actual IPv4 of your chosen interface). The certificate must include the chosen address in its SAN.

## Calendars: source selection and refresh

The **Calendars** tab now starts with shared **Active calendar source** settings,
above the provider sections. Choose **North Yorkshire Council** or **iCalendar
(iCal)**, then click **Save active source**. The selected source supplies
collection dates to Status, Hue reminders, manual tests and Alexa. Council selection validates its configured lookup and mappings before switching;
selecting an already-configured iCalendar source does not require a new live
download.

**Automatic refresh interval** applies to *both* sources (7 days by default,
configurable from 1 to 90 days). The existing daily systemd timer checks the
active calendar each morning, independently of whether the webpage is open,
and only downloads when the interval is due. **Refresh active calendar now**
always bypasses the cache, and last-success/next-due dates are displayed for
the active provider. A failed explicit refresh reports an error without
replacing previously verified data. During transient automated failures,
cached information may be used for 72 hours beyond the refresh due time.

Both provider panels use **Test access** (live connectivity and format check)
and **Preview dates** (upcoming collection dates) without changing the selected
source. Their provider-specific **Save settings** buttons never switch the
active source. The North Yorkshire Council panel retains UPRN entry; the
generic iCalendar panel accepts supported public HTTPS iCal feed URLs from
Zoho, Google Calendar, Outlook and other public providers. Secrets are saved
locally and are never returned by the management API. Redirects and
private-network target URLs are rejected.

The daily systemd unit retains its original filename
`bindicator-council-refresh.timer` for seamless upgrades; it now checks both
source types. The legacy council-specific refresh interval is retained in
existing configuration files for compatibility, but the shared
`calendar_refresh.days` value overrides it.

## North Yorkshire Council source (opt-in)

The currently selected calendar remains active until you explicitly switch
to the council. Under **Calendars → North Yorkshire Council**, enter the
property's UPRN, save its settings, then use **Test access** and **Preview dates**
to check the reported dates, collection labels and colour mappings. The lookup contacts only the North Yorkshire Council
website, using an address-selection POST followed by the council's AJAX calendar
response. A council website change may temporarily break the lookup.

The UPRN is saved **only in the local** `/etc/bindicator/config.yaml` and is not
returned from the management API. The source starts disabled; a live lookup and
complete colour mappings for household waste, recycling and garden waste are
required before enabling it. Bindicator matches these collection types to
your existing event titles even when they use different punctuation (such as
an en dash). Update mappings under **Calendar event mappings** if necessary.
Ambiguous mappings and unknown bin descriptions are rejected rather than guessed.

Enabling the council source changes *all* collection consumers—scheduled Hue alerts,
Status/upcoming collections, Alexa and manual next-collection commands—to the
same council data. The iCalendar source remains configured and can be reselected
under **Active calendar source**. The active calendar is checked daily by the independent
`bindicator-council-refresh.timer` (normally around 07:10 UK local time with
up to 15 minutes of jitter), even when the web UI is closed. It downloads
only when its configured interval has elapsed (7 days by default; choose 1–90
days under Calendars). An on-demand reader may refresh sooner if the cache is due.
**Refresh active calendar now** forces a fresh lookup irrespective of the
interval and reports a failure instead of falsely claiming success. Status
shows the last successful update and whether a refresh is due.

Council data can remain in use for 72 hours *beyond its configured due time*
if a scheduled refresh fails; the timer retries each day. After that grace
period a failed refresh causes an explicit error rather than relying on
unverified old data. Changing the UPRN or event mappings invalidates the
cache and requires a new council fetch. Cache and timestamps are stored
in `/var/lib/bindicator/north-yorkshire-v2.ics` and
`/var/lib/bindicator/north-yorkshire-refresh.json` respectively. If no current copy is available,
the system fails closed rather than activating lights from unverified data.
No additional calendar subscription or API key is required.

No real property UPRN is included in the repository or sample config. To
verify the local service after installation, use `https://bindicator-host:18051/`,
then Calendars → North Yorkshire Council → Preview dates. Do not enable
the source until the returned calendar has been compared with the official
council page for the property.

## Tabs

**Status** shows the next bin collection, reminder status and Pause/Resume/Toggle.
The collapsible **Next collection alerts** section lists the next five upcoming
collection dates from the active provider and includes per-date 10-second tests. Manual activation
until collection morning remains explicitly confirmed.

**Testing** contains the collapsible **Test indicator colours** section with
the duration chooser and one colour-coded test button per configured colour.
The original lamp states are restored where safe; previews are refused when
reminders are paused or an alert is already active.

The tabs appear in this order: **Status**, **Testing**, **Lighting**, **Colours**,
**Calendars**, **Mapping**, **Help**, **☕ Coffee**. On narrower screens they wrap onto another line.

**Lighting** contains Hue Bridges, Indicator lights, Reminder timing and Display
settings. All sections are collapsed by default. Saved lamps remain visible
with their Bridge/Hue ID, and reachable lamps display friendly names and capabilities.

**Colours → Indicator colours** provides up to five colours, priority ordering,
RGB pickers and optional advanced Hue CIE xy values.

**Calendars** contains the shared source selector, refresh interval and refresh button, followed by North Yorkshire Council and generic iCalendar provider settings. Both provider sections start collapsed.

**Mapping → Calendar event mappings** displays one searchable multi-select
per indicator colour. Select multiple event titles to map them to the same
colour, remove them using the chips, or add a custom title. **Refresh calendar
events** discovers available titles from registered, configured calendar providers,
including North Yorkshire and the generic iCalendar feed.
Saved mappings remain visible if either source is temporarily unavailable.
Each event title can map to only one colour. Names used by more than one
source are deduplicated into one option.

Changes across the Colours and Mapping tabs share a single unsaved editor. Either
**Save changes** button atomically commits the complete colours, priority,
renames and calendar-event mappings, so renaming a colour cannot orphan its
events. Use **Discard** to revert both sections.

The built-in iCalendar provider supports compatible Zoho, Google Calendar,
Outlook and other permitted public HTTPS iCal feed URLs. Installed trusted
provider packages can also appear in the active-source selector; automatic
configuration forms for third-party provider-specific settings are not yet available.

**Help** shows the installed Bindicator Python package version and links to
the GitHub project, documentation, issues and releases. **☕ Coffee**
provides an optional Buy Me a Coffee link to the same developer support
page used by Lyrion Carousel. Neither tab changes local settings.

**Lighting → Display settings** offers `priority`, `spread` and `cycle`.
Cycle shows one due colour at a time, advancing in priority order once a minute
using the existing scheduler. On a lamp with gradient capability, the
per-lamp "Always multi-colour" option still takes precedence. Bindicator
restores each lamp's original state at the end of the reminder and respects
manual overrides.

## Verify deployment and isolation

```bash
sudo systemctl is-active bindicator-web
sudo ss -ltnp | grep -E ':1805[01]'
# Expected: port 18050 on 127.0.0.1; port 18051 on LAN_IP.

# A local TLS health/authorisation check with an untrusted self-signed cert:
curl -k -o /dev/null -w 'LAN management: %{http_code}\n' \
  "https://$LAN_IP:18051/"
# Expected: HTTP 200 for the unprotected local page.

# This should still be protected by Cloudflare Access:
curl -sS -o /dev/null -w 'Cloudflare API: %{http_code}\n' \
  https://bins.example.com/api/v1/status
# Expected: 401/403 without Cloudflare service credentials.
```

Use firewall policy appropriate to your system (nftables/UFW/router VLANs)
to restrict 18051 to trusted client IPs. **Never port-forward 18051**.

To stop or disable only the browser interface:

```bash
sudo systemctl disable --now bindicator-web.service
```

This does not stop the scheduled reminder timer or the Alexa API.

## Related docs

- [Documentation index](README.md)
- [Project overview](../README.md)
- [Calendar provider development guide](calendar-providers.md)
- [Local API](local-api.md) — loopback API on 18050
- [Cloudflare setup](cloudflare-setup.md) — Access + Tunnel for Alexa only
- [Alexa guide](../alexa/README.md)
- [AWS Lambda and private S3 deployment](aws-deployment.md)
