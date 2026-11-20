# Security policy

## Supported versions

Security fixes are intended for the current default branch and the latest
published release. Older releases may not receive backports.

## Reporting a vulnerability

**Do not open a public GitHub issue with credentials, private iCalendar
URLs, Hue application keys, Cloudflare service tokens, AWS temporary
credentials, property identifiers, or exploit details.**

Use the repository's GitHub **Report a vulnerability** / private
security-advisory feature, if enabled, or contact the maintainer
privately via the contact method listed on the GitHub profile.
Do not include secret values in screenshots or logs. If you suspect
credentials were exposed, revoke or rotate them immediately rather than
waiting for a report to be processed.

## Security model

- The local API binds to `127.0.0.1:18050` and requires a bearer token
  except for its minimal health endpoint.
- Cloudflare Tunnel and **Service Auth Access** may protect the optional
  Alexa HTTPS entry point, with the separate local API token providing a
  second layer. Never configure an Access Bypass or Everyone rule.
- The LAN HTTPS dashboard on port `18051` deliberately has **no separate
  login**. Anyone able to reach it can control Hue indicators and change
  Bindicator settings. Restrict access to trusted LAN clients and never
  forward this port or route it through Cloudflare.
- Hue Bridge pairing requires physical authorisation. Local trusted
  `bindicator` group members can access configuration, secrets and
  control APIs.
- AWS CLI and Cloudflare CLI credentials must stay in user-local protected
  storage, not Git. Terraform state can contain credentials and must be
  protected separately.
- Bindicator parses iCalendar feeds and can fetch HTTPS calendars. Only
  configure trusted sources. Treat third-party calendar-provider plugins as
  executable code.
- Never paste `/etc/bindicator/secrets.env`, `api.token`, Cloudflare
  service token secrets, AWS login cache files, private UPRNs or
  `alexa/deploy.local.conf` into public support reports.

For the full audit and publication process see [Public-release checklist](docs/public-release.md).

## Publish checklist

Before changing a **private** repository to **public**, inspect **all Git
history and branches**, not just the latest working tree, for secrets and
personal configuration. Deleting a file in a new commit does not remove it
from prior commits or GitHub PR diffs.

A public-release copy made from a **clean, reviewed snapshot with new
history** is the safest starting point when the private repository has
previously contained personal deployment identifiers. Keep the original
private; never make it public merely because the latest checkout looks
clean.

Review every asset's distribution rights, choose and add an appropriate
`LICENSE`, consider enabling GitHub secret scanning / push protection,
and verify security advisories are enabled before announcing the release.
Third-party dependencies and artistic provenance are covered in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and
[COPYRIGHT.md](COPYRIGHT.md).
