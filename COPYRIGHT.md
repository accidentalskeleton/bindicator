# Copyright and artwork provenance

Copyright © 2026 Stuart Roberts and Bindicator contributors.

The original Bindicator application source code, tests, documentation,
and maintainer-created user-interface graphics are distributed under the
[GNU General Public License, version 3](LICENSE), except where a file
explicitly identifies another licence or copyright holder.

## Included artwork

| Asset | Purpose | Evidence and release assessment |
| --- | --- | --- |
| `src/bindicator/static/bindicator-soft-banner.webp` | Web-dashboard header illustration | Committed by the project maintainer on 16 November 2026 with the description “Blend new softer Bindicator artwork into the full-width web header” (commit `5756ecf`); author asserts it is original. External image-source provenance has not been independently established. |
| `src/bindicator/static/favicon-32.png` | Web-dashboard favicon | Committed by the project maintainer on 16 November 2026 as “Add retro Bindicator logo and favicon to LAN web app” (commit `d4eaad1`); author asserts it is original. External image-source provenance has not been independently established. |
| `alexa/echo_show.json` (the `BindicatorMark`, `BinGarden`, `BinRecycling`, `BinHousehold` and `BinOther` AVG definitions) | Echo Show mascot and bin silhouettes | Inspectable local vector path definitions, with no external images or asset URLs. Developed in the Bindicator feature branch. |
| `src/bindicator/web_ui.py` | Interface layout, built-in SVG rendering and CSS | Inspectable repository source; uses application assets above and no downloaded UI image library. |

The repository commit history establishes **when the assets entered this project**;
it does not independently prove that an image is original or free of third-party
rights. Before a public release, the maintainer should inspect both raster
assets visually, confirm their creative origin and rights, and check for any
third-party reference art, stock elements, logos or fonts that need permission
or attribution. The two raster images could not be visually inspected by the
GitHub text-only audit.

The project does **not** claim copyright or trademark rights in Amazon Alexa,
Philips Hue, Cloudflare, AWS, Zoho, Google, Microsoft, or other third-party
product names and marks.

## Third-party software

The application installs independent third-party Python libraries under their
own licences, and the optional Lambda packaging process includes Alexa SDK
dependencies. They are **not** relicensed by this project. Consult
[Third-party notices](THIRD_PARTY_NOTICES.md) for names, licence identifiers,
links and redistribution guidance.

The licence and copyright terms above apply to content the listed copyright
holders actually own, and do not override dependencies' original licences.
