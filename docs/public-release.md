# Preparing a public Bindicator release

## Contents

- [Release decision](#release-decision)
- [Current findings](#current-findings)
- [Run local checks](#run-local-checks)
- [Safest publication route](#safest-publication-route)
- [Review before publishing](#review-before-publishing)

## Release decision

**Do not switch the existing private GitHub repository to Public yet.**
The private development history includes installation-specific AWS
and Cloudflare resource identifiers. Earlier branches, commits, PRs and
workflow logs remain discoverable if repository visibility changes. Removing
identifiers from the latest files does not erase Git history.

The `security/public-release-readiness` branch separates per-installation
configuration from distributable example files. It is **not** a guarantee
that the entire private repository is safe to publish, since it retains
its original private Git ancestry.

## Current findings

- Previously tracked `alexa/deploy.conf` specified a real AWS account ID,
  S3 bucket, Region and Lambda target. It is now replaced in this branch by
  `alexa/deploy.example.conf`; actual settings go in the Git-ignored
  `alexa/deploy.local.conf`.
- `deploy/cloudflare/desired-state.json` and documentation contained
  real Cloudflare account/resource IDs, a personal tunnel/domain and the
  local host name; this branch uses placeholders.
- The loopback API requires a bearer token, but the LAN dashboard deliberately
  lacks independent authentication. Its security depends on network isolation.
- GPL-3.0-only has been selected to match Lyrion Carousel and the
  full licence and copyright/third-party notice files are present.
  The maintainer still needs to review rights to each original raster asset
  before publishing.
- The automatic GitHub Actions test triggers are disabled in the current
  workflow. Re-enable suitable read-only checks when billing is available.
- Application graphics and third-party content should be reviewed for
  redistribution rights. This audit cannot establish artwork ownership.
- The 20 November full-history Gitleaks scan checked 429 commits and returned
  six `generic-api-key` hits: five synthetic test fixtures, and one old
  Cloudflare **service token ID** (a resource identifier rather than the
  authentication secret). All are retained in the original private history.
- The initial source-only Gitleaks scan returned five synthetic fixture hits;
  the tests were refactored without changing their assertions. Run the scans
  again on the new review-branch head before confirming a clean source snapshot.
- These Gitleaks findings are not evidence of a currently exposed secret, but
  automated scans cannot prove that no sensitive material exists. Keep the
  original development history private and publish only a newly reviewed,
  clean-history repository.
- Package versions use broad ranges in `pyproject.toml` and
  `alexa/requirements.txt`. A release should record tested resolutions
  and run a dependency vulnerability scan (for example
  `python -m pip install pip-audit` followed by `pip-audit` inside
  the project venv); exact reproducible release-locking is not yet in place.
- The generic iCalendar URL validation checks resolved IP addresses before
  issuing a separate `requests.get`. A user-controlled domain can change
  its DNS response between those operations (DNS rebinding/time-of-check
  versus time-of-use). Arbitrary-source fetching therefore deserves
  security testing and ideally connection-time address enforcement before
  treating the URL validation as a strong SSRF barrier. The web UI remains
  LAN-only and accepts input only from users who can reach that interface.
- The local HTTPS management UI uses inline script/style permissions and
  no account login. Its intended trusted-LAN boundary must be enforced
  by the operator's firewall or VLAN rules; browser-side Host/Origin checks
  are not a substitute for user authentication.

## Run local checks

Work in a **separate clone**, not the live Bindicator checkout, so the
local AWS deployment stays untouched:

```bash
git clone --no-single-branch --filter=blob:none \
  git@github.com:accidentalskeleton/bindicator.git \
  ~/code/bindicator-public-review
cd ~/code/bindicator-public-review
git fetch --all --tags
git switch security/public-release-readiness

python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q -rs

# Build ZIP locally without --deploy (no AWS uploads)
bash alexa/build.sh
.venv/bin/python tools/check_lambda_licenses.py dist/bindicator-alexa.zip

# Check resolved packages for known vulnerabilities.
.venv/bin/python -m pip install pip-audit
.venv/bin/python -m pip_audit

# Install current Gitleaks from its official release, then:
# Gitleaks >= 8.19:
gitleaks git --redact --log-opts="--all" .
gitleaks dir --redact .

# Older versions of Gitleaks instead support:
# gitleaks detect --redact --source . --log-opts="--all"
# gitleaks detect --redact --no-git --source .

# Either CLI is also supported automatically by:
# bash tools/public_release_preflight.sh
```

The ZIP checker verifies the project licence files and dependency metadata
embedded in the actual archive. It reports missing metadata; it cannot prove
artwork originality or the licence compliance of all transitive packages.

Also review all branches/tags, commit authors' email addresses, old pull
request discussions, GitHub Actions logs, assets' EXIF metadata and
configurations created outside Git. Gitleaks looks for *secrets*; it will
not reliably flag a personal hostname, property ID or unrelated private
details. Never paste raw secret-scan findings into a public issue.

Run `bash tools/public_release_preflight.sh` after the artwork, dependency
and history review. The GPL v3 licence has already been added. **It deliberately fails on the original private
history** where `alexa/deploy.conf` was tracked.

## Safest publication route

Recommended: keep this original repository **private** as the development
archive and create a **new public repository from a clean snapshot with a
new root commit**. This avoids publishing old private commits and PRs.

Prepare the public candidate by extracting only the reviewed branch's
tracked snapshot, without .git objects:

```bash
cd ~/code/bindicator-public-review
mkdir -p ~/code/bindicator-public-candidate
git archive security/public-release-readiness | \
  tar -x -C ~/code/bindicator-public-candidate
cd ~/code/bindicator-public-candidate
git init -b main
# Keep the reviewed LICENSE, COPYRIGHT.md and third-party notices.
git add .
git status --short
git commit -m "Initial public Bindicator release"
```

Then rerun Gitleaks on the **new repository** and check no
`alexa/deploy.local.conf`, `.env`, `*.tfstate`, tokens, personal hostnames
or property IDs made it into the fresh commit. Configure the new remote
only after reviewing its name and permissions, and publish only with
explicit approval.

If you wish to retain the exact public URL
`accidentalskeleton/bindicator`, plan a separate **rename of the old private
repository** before creating the new public one. This can affect existing
remotes and links, so do not rename or change visibility automatically.

History rewriting in-place is possible but has subtle interactions with
GitHub pull requests, references, cached objects and collaborators. A fresh
public repository is easier to reason about for this project.

## Review before publishing

- Confirm no real AWS, Cloudflare, Hue, calendar or Alexa credentials
  are present, including in binary assets or generated files.
- Confirm non-secret installation details you are happy disclosing
  (domains, IPs, AWS account IDs, names, commit author email addresses).
- Verify the GPL-3.0-only terms, third-party notice coverage, and rights to
  all bundled images and dependencies.
- Ensure every public installation command uses examples and does not
  overwrite an existing user's AWS resources.
- Enable Dependabot, secret scanning/push protection (where available),
  a private vulnerability reporting path, and read-only CI before
  soliciting external contributions.
- Verify a **new-user install** from the clean snapshot on a test machine.

Also see [security policy](../SECURITY.md), [AWS deployment](aws-deployment.md)
and [Cloudflare configuration as code](cloudflare-iac.md).
