# Calendar providers and normalised collection events

## Contents

- [Core contract](#core-contract)
- [Registration](#registration)
- [Walkthrough: add a new council provider](#walkthrough-add-a-new-council-provider)
  - [1. Create an installable Python package](#1-create-an-installable-python-package)
  - [2. Replace the demonstration data with a real council lookup](#2-replace-the-demonstration-data-with-a-real-council-lookup)
  - [3. Test before installing](#3-test-before-installing)
  - [4. Install as a trusted plugin on mrlazy](#4-install-as-a-trusted-plugin-on-mrlazy)
  - [5. Configure and activate the provider](#5-configure-and-activate-the-provider)
  - [6. Compatibility checklist](#6-compatibility-checklist)
- [Shared refresh and caching](#shared-refresh-and-caching)

Bindicator's calendar engine separates **data acquisition** from **collection
mapping, scheduling and Hue lighting**. Built-in providers are registered in
`src/bindicator/calendar_providers.py`. The application never imports or executes
unknown provider modules from configuration or a calendar response.

## Core contract

Each adapter implements:

- `id`, `name`, and `config_fields`: stable identifier, display name and
  declarative fields for the Calendars source selector
- `configured(config)`: whether its provider-specific local settings are complete
- `identity(config)`: opaque cache identity that changes if provider settings
  change; **never return secrets**, including iCal tokens or UPRNs
- `fetch(config, state_dir) -> bytes`: a verified iCalendar stream for the
  existing scheduling, Alexa and reminder services
- `events(config, state_dir, start, end) -> list[CollectionEvent]`: provider-
  neutral collection occurrences for connectivity tests and date previews
- `discover_titles(config, state_dir)`: titles available for the Mapping tab

`CollectionEvent` is an immutable event with UK-local `date`,
`title` (mapping key), `source_id`, `original_title` (as returned by the
provider), and optional `event_id`. It has **no colour**: colours are mapped
by Bindicator after normalisation. For example, a council may call a collection
"Household waste" while its configured title is "BinDay – Household waste".

A provider may read HTML, JSON, or ICS internally; the engine only sees its
standard interface. A new council adapter should own its HTTP, parsing,
property lookup, bin-type normalisation and timezone handling. It must enforce
timeouts, validate redirects and unrecognised types, never silently guess
colours or expose credentials.

## Registration

A trusted provider can be supplied by a separately installed Python package
that declares the `bindicator.calendar_providers` entry-point group. Bindicator
loads only entry points from packages already installed by the administrator;
calendar data, incoming web requests and YAML cannot cause arbitrary imports.

For example, an adapter distributed as a Python package can declare:

```toml
[project.entry-points."bindicator.calendar_providers"]
example = "example_council.provider:ExampleCouncil"
```

The entry point must resolve to a provider class (constructed without arguments)
or provider instance implementing the contract. Install into Bindicator's
virtual environment as the trusted administrator, then restart its services.
**Installing a Python plugin executes code with Bindicator's privileges**:
only install packages you have reviewed and trust. A provider name by itself
is not a Python module name and cannot trigger arbitrary imports.

The existing built-ins are `council` (North Yorkshire) and `ical`
(generic iCalendar). A newly installed and registered adapter does **not** require edits to the
common date preview, source selection, refresh timer, ICS cache, or reminder
engine. The shared engine discovers it through the registry.

Provider-specific settings may be stored as an appropriately permissioned
YAML section, or exposed through an explicit trusted configuration handler;
`config_fields` describes the fields to the user interface. Do **not** use
raw arbitrary YAML or direct reflection to accept secrets from the browser.

Example adapter sketch:

```python
from bindicator.calendar_providers import CollectionEvent, register_provider

class ExampleCouncil:
    id = "example"
    name = "Example Council"
    config_fields = ({"key": "uprn", "label": "UPRN", "type": "secret_text"},)

    def configured(self, config):
        return bool(config.get("example", {}).get("uprn"))

    def identity(self, config):
        # Return a one-way digest of provider settings, never the secret.
        ...

    def fetch(self, config, state_dir):
        # Fetch council collections and produce valid ICS bytes.
        ...

    def events(self, config, state_dir, start, end):
        # Return CollectionEvent instances, with source_id="example".
        ...

    def discover_titles(self, config, state_dir):
        ...

 # In a packaged plugin, export ExampleCouncil via an entry point instead.
```

Set `calendar_source: example` after registration and configuration.
For existing installations, omitting this key continues to use the legacy
`north_yorkshire.enabled` setting, so switching an existing installation does
not require changes to its Hue configuration, calendar mapping or saved secrets.

## Walkthrough: add a new council provider

This example implements an **offline demonstration provider**. It is deliberately
not a live council scraper: replace the sample collection records with a tested,
read-only council API/HTML adapter once you know that council's actual interface.
It demonstrates the package layout and every method needed for a working plugin.

### 1. Create an installable Python package

On a development machine (or in a separate directory on `mrlazy`):

```text
bindicator-example-council/
├── pyproject.toml
├── example_council/
│   ├── __init__.py
│   └── provider.py
└── tests/
    └── test_provider.py
```

Use this minimal `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "bindicator-example-council"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["bindicator>=0.1.0,<1"]

[project.entry-points."bindicator.calendar_providers"]
example_council = "example_council.provider:ExampleCouncil"

[tool.setuptools.packages.find]
include = ["example_council*"]
```

Create an empty `example_council/__init__.py`, then add
`example_council/provider.py`:

```python
from dataclasses import dataclass
from datetime import date, timedelta
from hashlib import sha256
from pathlib import Path

from icalendar import Calendar, Event

from bindicator.calendar_providers import CollectionEvent


@dataclass(frozen=True)
class ExampleCouncil:
    id: str = "example_council"
    name: str = "Example Council"
    config_fields: tuple[dict, ...] = (
        {"key": "uprn", "label": "Property UPRN", "type": "secret_text"},
    )

    def configured(self, config: dict) -> bool:
        return bool(config.get(self.id, {}).get("uprn"))

    def identity(self, config: dict) -> str:
        # This changes when the selected property changes. Do not return the UPRN.
        uprn = config[self.id]["uprn"]
        return sha256(uprn.encode("utf-8")).hexdigest()

    def _records(self, config: dict) -> list[tuple[date, str]]:
        # DEMO ONLY: replace this with a validated HTTPS council lookup.
        # Produce actual collection dates in the Europe/London calendar.
        tomorrow = date.today() + timedelta(days=1)
        return [(tomorrow, "Recycling"), (tomorrow + timedelta(days=7), "Household waste")]

    def events(self, config: dict, state_dir: Path,
               start: date, end: date) -> list[CollectionEvent]:
        result = []
        for day, name in self._records(config):
            if start <= day < end:
                result.append(CollectionEvent(
                    date=day,
                    title=f"ExampleCouncil - {name}",
                    source_id=self.id,
                    original_title=name,
                    event_id=f"{day.isoformat()}:{name}",
                ))
        return result

    def fetch(self, config: dict, state_dir: Path) -> bytes:
        # The current shared refresh engine stores validated ICS bytes.
        calendar = Calendar()
        calendar.add("prodid", "-//Bindicator Example Council//EN")
        calendar.add("version", "2.0")
        for day, name in self._records(config):
            event = Event()
            event.add("uid", f"{day.isoformat()}-{name.replace(' ', '-')}@example.local")
            event.add("dtstart", day)
            event.add("summary", f"ExampleCouncil - {name}")
            calendar.add_component(event)
        return calendar.to_ical()

    def discover_titles(self, config: dict, state_dir: Path) -> list[str]:
        return sorted({f"ExampleCouncil - {name}" for _, name in self._records(config)})
```

The provider methods must agree on the **exact mapped title**: the
`CollectionEvent.title` emitted by `events()`, the ICS `SUMMARY` emitted by
`fetch()`, and the title returned by `discover_titles()`. Otherwise date
previews may work while automatic reminders do not match configured colours.

`original_title` is the council's human-friendly bin name; `source_id` is
always the registered provider ID. The example uses UK-local `date` values;
real adapters should convert timezone-aware timestamps to `Europe/London`
before taking the date. The range contract is **start inclusive, end exclusive**.

### 2. Replace the demonstration data with a real council lookup

A production adapter should implement the council's actual supported lookup,
such as a UPRN-based HTTPS API, and normalise its result into collection dates
and descriptive titles. Use the existing
`src/bindicator/north_yorkshire.py` for a real HTML/AJAX adapter example.

- Accept only the council's intended public HTTPS endpoints. Validate URL
  schemes, hostnames and redirects; never fetch arbitrary hostnames from
  an untrusted configuration value.
- Use bounded network timeouts and response-size limits. Handle malformed
  dates, error pages, empty calendars and unrecognised bin types explicitly.
- Never log access tokens, full private calendar URLs, property identifiers
  or returned personal-address details.
- Give each collection occurrence a stable identity; avoid silently guessing
  an unknown bin type or mapping it to an existing colour.
- Keep provider network operations read-only. No Hue calls, timer management,
  user-interface rendering or colour decisions belong in an adapter.
- Avoid reliance on an HTML parser without regression fixtures: council page
  markup can change without notice.

For council sources, the app currently uses `config["calendar"]["events"]`
to map event titles to indicator colours. Each title returned by the provider
must appear under **Mapping → Calendar event mappings** before reminders can
activate the appropriate colour.

### 3. Test before installing

Unit-test the adapter offline with fixed council responses, including failures.
This minimal contract test exercises the demonstration implementation:

```python
from datetime import date, timedelta
from icalendar import Calendar
from example_council.provider import ExampleCouncil

def test_provider_contract():
    provider = ExampleCouncil()
    config = {"example_council": {"uprn": "12345678901"}}
    assert provider.configured(config)
    assert provider.identity(config) != config["example_council"]["uprn"]
    data = provider.fetch(config, None)
    assert any(event.name == "VEVENT" for event in Calendar.from_ical(data).walk())
    start = date.today()
    occurrences = provider.events(config, None, start, start + timedelta(days=20))
    assert len(occurrences) == 2
    assert all(event.source_id == provider.id for event in occurrences)
    assert all(event.title in provider.discover_titles(config, None) for event in occurrences)
```

Run it from the plugin source directory:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ../bindicator 'pytest>=8,<10'
.venv/bin/pip install --no-deps -e .
.venv/bin/python -m pytest -q
```

This example assumes a sibling `../bindicator` checkout; adapt that path
if Bindicator is installed elsewhere. The plugin may instead be tested
against any compatible Bindicator installation. Do not test with real private credentials in CI.

Also test duplicate collection dates, multiple bins on the same day,
cancellations, bank-holiday moves, network failures and cache invalidation
when a property setting changes. Check that a failed manual refresh does not
overwrite the last good cache.

### 4. Install as a trusted plugin on `mrlazy`

Review the plugin source before installation. With the package copied into
`~/code/bindicator-example-council`, install into the **existing** Bindicator
virtual environment (not the system Python):

```bash
cd ~/code/bindicator-example-council
sudo /opt/bindicator/.venv/bin/python -m pip install .
```

Verify that the entry point is present:

```bash
/opt/bindicator/.venv/bin/python -c \
  'from bindicator.calendar_providers import registered_providers; print([(p.id, p.name) for p in registered_providers()])'
```

The expected list includes `example_council`. An entry-point load failure
is logged and that provider will not appear. **A third-party plugin runs
Python code with Bindicator's local permissions**, so installing an arbitrary
package is not equivalent to adding a harmless calendar URL.

### 5. Configure and activate the provider

A provider is *not* automatically usable through a configuration form merely
because it advertises `config_fields`: the current Calendars UI uses that
metadata in the source list but still has hardcoded forms for North Yorkshire
and iCalendar. Third-party settings must currently be entered explicitly in
`/etc/bindicator/config.yaml`, or implemented using a reviewed provider-
specific management handler. Don't expose generic YAML editing in the browser.

Back up the configuration, then add a provider section with appropriate
permissions:

```yaml
example_council:
  uprn: "YOUR_PROPERTY_UPRN"

# Optional: explicitly select the new provider once verified.
calendar_source: example_council

# Use the existing shared calendar refresh schedule.
calendar_refresh:
  days: 7

calendar:
  events:
    "ExampleCouncil - Recycling": blue
    "ExampleCouncil - Household waste": orange
```

The `calendar.events` example is **illustrative**: merge these titles into
your existing mappings and retain all your current Hue, colours, bridge and
other configuration settings. Do not overwrite the whole configuration file
with this snippet. The supplied UPRN should remain on the local machine and
must not be committed to GitHub. In production, treat provider credentials as
secrets and keep them in the restricted secrets environment or an equivalent
local protected store, rather than a publicly readable file.

Before enabling a new provider, verify dates by calling its read-only
`events()` method or inspecting the ICS output. The current **Calendars**
page supplies Test access and Preview dates controls for the built-in
North Yorkshire and iCalendar sources only; it does not automatically
create those buttons for third-party plugins. Confirm both the returned
bin types and the Mapping tab's colour assignments. The available provider
selector is populated from installed providers.

Restart all long-running Bindicator processes so they can discover the new
entry point and settings:

```bash
sudo systemctl restart bindicator-api.service bindicator-web.service
sudo systemctl restart bindicator-council-refresh.timer
```

The existing timer name is retained for upgrade compatibility but it checks
the **active** source. For the next scheduled check, use:

```bash
systemctl list-timers bindicator-council-refresh.timer
```

A simple read-only way to confirm configuration is accepted:

```bash
sudo -u bindicator /opt/bindicator/.venv/bin/python -c \
  'from pathlib import Path; from bindicator.app import load_config; \
c=load_config(Path("/etc/bindicator/config.yaml")); \
print("Loaded provider:", c.get("calendar_source", "(legacy selection)"))'
```

To roll back, restore the previous `calendar_source` value (or remove the
key to use the legacy source setting), restart the services, and leave the
previous verified caches intact. Do not uninstall a provider while it is
still selected in `calendar_source`; the config loader checks that the
selected provider is registered.

### 6. Compatibility checklist

Before submitting a new council provider, verify:

- A unique, stable `id`, friendly `name`, valid `config_fields` and all
  five required methods
- `identity()` changes when settings affecting results change, without
  returning property details
- Valid, bounded ICS output from `fetch()`, including an event `UID`,
  `DTSTART` and `SUMMARY`
- Matching titles from `events()`, `fetch()`, `discover_titles()` and
  existing Bindicator event mappings
- Correct UK-local dates, recurring/changed collections and combined-bin days
- Safe error behaviour, no unnecessary logs of identifiers and no secret
  leakage to web responses
- Works in Python 3.11 and 3.13, handles unavailable council responses,
  and does not interfere with North Yorkshire or generic iCalendar

The core engine and cache policy should **not** need changes to add a new
provider. Optional provider-specific **configuration UI** is still separate
work and may require an explicit reviewed implementation.

## Shared refresh and caching

`calendar_engine.py` handles all provider refreshes using a shared 1–90 day
interval (7 by default), one locked cache per provider, atomic writes, the
existing 72-hour outage grace, and explicit errors for failed manual refreshes.
The existing timer still uses
`bindicator-council-refresh.timer` for compatibility, but dispatches to the
active registered provider.

The legacy `north-yorkshire-v2.ics`, `north-yorkshire-refresh.json`,
`ical-source.ics` and `ical-refresh.json` files are still read and written
by the shared cache engine. Cache identities include source configuration,
so changing an address or iCal URL cannot reuse another property's dates.
The `council_refresh.py` and `ical_refresh.py` modules remain as wrappers
for older internal callers and tests.

Calendar events are normalised before mapping to colours, combining collection
days, calculating reminders and generating responses. Recurrence, cancellation
and timezone expansion use one `ical_events()` parser.
