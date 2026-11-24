# Changelog

Notable changes to Bindicator are recorded here. Dates are in YYYY-MM-DD format.
Version numbers follow the Python package version in `pyproject.toml`.
The Help tab also reports the exact installed Git revision when available.

## [Unreleased]

Nothing recorded yet.

## [0.1.0] - 2026-11-24

First public source release, published from a reviewed clean-history repository.

### Added

- Self-hosted Philips Hue bin collection reminders for Debian/Linux, with
  multiple Hue Bridges and colour priority, spread and cycle modes.
- Gradient-aware lights, configurable colour mappings, timed previews,
  persistent alerts and state restoration that respects manual changes.
- Calendar providers for North Yorkshire Council and HTTPS iCalendar feeds,
  including recurring events, provider selection, verified cache fallback,
  configurable refresh intervals and extension points for other trusted sources.
- LAN-only HTTPS management dashboard with Status, Testing, Lighting, Colours,
  Calendars, Mapping, Help and Coffee tabs.
- Authenticated loopback HTTP API, systemd service and timer units, and an
  installer that enables/restarts services while preserving local settings,
  credentials and state across upgrades.
- Optional private Alexa custom skill invoked as **Bin Buddy**, including
  next-collection queries, reminder controls, bins-out acknowledgement and
  Echo Show APL visuals. Deployment documentation and optional Lambda/skill
  metadata tooling are included.
- Installer-recorded Git commit identification in the Help tab, displayed
  alongside package version where Git metadata is available.
- Public project documentation, GPL-3.0-only licensing, copyright and
  third-party notices, security guidance and pull-request regression checks.

### Release notes

- Requires a self-hosted installation; the GitHub project does not provide a
  hosted reminder service.
- Alexa, Cloudflare Tunnel/Access and AWS are optional integrations requiring
  separate account and infrastructure configuration. The project's private
  skill and Lambda are not shared infrastructure for other installations.
- The HTTPS dashboard is intended for trusted LAN devices, does not provide
  an independent login and must not be exposed publicly.
- The source installer is the supported installation method for this release;
  no `.deb` or APT repository is provided.
- This entry describes the first public snapshot, not a historical list of
  development releases.

[Unreleased]: https://github.com/accidentalskeleton/bindicator/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/accidentalskeleton/bindicator/releases/tag/v0.1.0
