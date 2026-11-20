# Third-party software and attribution

Bindicator itself is licensed under **GPL-3.0-only** (see [LICENSE](LICENSE)
and [copyright information](COPYRIGHT.md)). The dependencies below are
separate works, retaining their own copyrights and licences; including them
here **does not** claim that Bindicator owns or relicenses them.

This inventory is based on the *direct dependencies declared* in
`pyproject.toml` and `alexa/requirements.txt` as of November 2026, plus
the separate tools/services referenced by the project. The precise installed
dependency set can vary because ranges are currently used. **Transitive
dependencies and their exact licence notices must be checked from the built
packages before distributing prebuilt installation images or Lambda bundles.**

## Python runtime dependencies

| Package | Licence identified | Project / licence source | Use |
| --- | --- | --- | --- |
| icalendar | BSD-2-Clause | [PyPI](https://pypi.org/project/icalendar/) | Parse iCalendar feeds |
| recurring-ical-events | LGPL-3.0-or-later | [PyPI](https://pypi.org/project/recurring-ical-events/) | Expand repeating calendar events |
| PyYAML | MIT | [PyPI](https://pypi.org/project/PyYAML/) | Load application configuration |
| Requests | Apache-2.0 | [PyPI](https://pypi.org/project/requests/) | HTTPS calendar and council requests |
| Beautiful Soup 4 | MIT | [PyPI](https://pypi.org/project/beautifulsoup4/) | Parse council collection HTML |
| ruamel.yaml | MIT | [PyPI](https://pypi.org/project/ruamel.yaml/) | Edit YAML while preserving layout |
| zeroconf (python-zeroconf) | LGPL-2.1-or-later | [PyPI](https://pypi.org/project/zeroconf/) | Discover Hue bridges |

## Python build-system dependencies

| Package | Licence identified | Source | Use |
| --- | --- | --- | --- |
| setuptools (77 or later) | MIT | [PyPI](https://pypi.org/project/setuptools/) | Build and package Bindicator, including SPDX licence metadata |
| wheel | MIT | [PyPI](https://pypi.org/project/wheel/) | Build distribution wheels |

These are declared build requirements in `pyproject.toml` and need not be
bundled with the deployed runtime. When redistributing build tooling or
prebuilt environments, retain the upstream notices.

## Alexa / Lambda and test dependencies

| Package | Licence identified | Source | Use |
| --- | --- | --- | --- |
| ask-sdk-core | Apache-2.0 | [PyPI](https://pypi.org/project/ask-sdk-core/) | Alexa request handling; included in Lambda bundle |
| ask-sdk-model | Apache-2.0 | [PyPI](https://pypi.org/project/ask-sdk-model/) | Alexa request/response models; included in Lambda bundle |
| python-dateutil | BSD-3-Clause OR Apache-2.0 (project is dual-licensed) | [PyPI](https://pypi.org/project/python-dateutil/) | Date handling; included in Lambda bundle |
| pytest | MIT | [PyPI](https://pypi.org/project/pytest/) | Local and CI test runner |

The Alexa SDK also brings **transitive dependencies**, for example
`ask-sdk-runtime`, `requests`, `urllib3`, `certifi`, `idna`,
`charset-normalizer` and `six`. Their licences must be retained
from the actual installed wheel metadata; this list is not a definitive
software bill of materials.

The LGPL libraries are dynamically used as standard Python dependencies,
not copied into or modified within the application's own source tree.
Distributors must respect the particular LGPL version and any applicable
source, relinking/replacement and notice obligations. The package's
inclusion in this table is **not** a legal compatibility certification.

## Licences included in distributed packages

`deploy/install.sh` installs Python libraries from PyPI into an
environment; their upstream package metadata and licence files remain
the authoritative source for those separately installed libraries.

`alexa/build.sh` builds a **redistributable deployment ZIP** using `pip
--target`. It copies the Bindicator GPL text, copyright document and this
inventory into the ZIP. The pip installation should also carry the
individual distribution metadata directories (including any upstream
`LICENSE`, `COPYING` and `NOTICE` files packaged by those projects).
These may have additional distribution requirements, especially Apache-2.0
notices. **Check the actual ZIP**, rather than relying on this summary,
before distributing it to third parties:

```bash
bash alexa/build.sh
unzip -l dist/bindicator-alexa.zip |
  grep -Ei '(license|licence|copying|notice|dist-info|copyright)'
```

For redistribution, retain all original copyright/attribution statements
and required licence texts. If any dependency's distribution omits needed
notices, add them from that dependency's upstream licensed release before
publishing a prebuilt ZIP. Do not strip `*.dist-info` contents from the
package without a replacement notice strategy.

## External services / APIs (not bundled)

The following names identify optional services or systems Bindicator
interoperates with, **not** libraries included in its source code:

- [Philips Hue](https://developers.meethue.com/) — Bridge and lighting API;
  Hue and Philips are marks of their respective owners.
- [Amazon Alexa Skills Kit](https://developer.amazon.com/en-US/alexa/alexa-skills-kit)
  and [AWS Lambda](https://aws.amazon.com/lambda/) — optional skill and hosting.
- [Cloudflare Tunnel / Access](https://developers.cloudflare.com/cloudflare-one/)
  — optional private HTTPS access.
- Zoho, Google Calendar, Microsoft Outlook and North Yorkshire Council —
  optional calendar sources; no provider's branding or software is
  distributed through the Python dependency inventory.

## Review status

Direct-dependency licence names have been cross-checked against upstream
project or PyPI metadata. This is a **direct-dependency attribution review,
not a full automated SBOM or licence-compliance attestation**.
Perform a dependency lock, source-package notice check and resolved-dependency
scan before a public binary release.

See [Public-release checklist](docs/public-release.md) for outstanding
history, binary-artwork and security checks.
