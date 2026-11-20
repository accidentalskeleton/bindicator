# AWS deployment for the Bindicator Alexa skill

## Contents

- [Existing installation](#existing-installation)
- [Prerequisites and authentication](#prerequisites-and-authentication)
- [Check the private S3 bucket](#check-the-private-s3-bucket)
- [Build and deploy](#build-and-deploy)
- [Verify and test](#verify-and-test)
- [Troubleshooting](#troubleshooting)
- [Rollback](#rollback)
- [Security and operational boundaries](#security-and-operational-boundaries)

The Alexa skill uses an **AWS Lambda function** that calls the protected
Bindicator API on the Bindicator host via Cloudflare Access. AWS S3 stores ZIP deployment
archives; S3 is **not** the music/calendar data store, and uploads alone do
not change the live Lambda. Deployment does not edit the Alexa interaction
model, enable APL, install Bindicator on the Bindicator host, or configure Cloudflare.

## Existing installation

The values below are **illustrative examples**, not your installation's real
credentials or infrastructure identifiers. Copy
[`alexa/deploy.example.conf`](../alexa/deploy.example.conf) to the Git-ignored
`alexa/deploy.local.conf` and customise it for your own account:

| Resource | Verified setting |
| --- | --- |
| AWS profile | `bindicator` (example) |
| Account ID | `123456789012` (replace) |
| Region | `eu-west-2` (example only) |
| Lambda function | `bindicator-alexa` |
| Lambda runtime / architecture | `python3.13` / `x86_64` (example) |
| S3 bucket | `example-private-lambda-deployments` (replace) |
| Lambda handler | `alexa.lambda_function.lambda_handler` |

Ensure your own bucket is in the same Region as Lambda and has all four S3 Block
Public Access options enabled. Verify a fresh installation rather than assuming
the example settings are already provisioned.

For a different AWS installation, do not reuse these targets. Configure
the appropriate profile, account, Region, bucket and function and review
the fail-closed checks in the build script.

**Migration from the original private Bindicator branch:** before checking out a
public-release build that removes the formerly tracked `alexa/deploy.conf`,
preserve your existing non-secret target identifiers locally:

```bash
cd ~/code/bindicator
cp alexa/deploy.conf alexa/deploy.local.conf
chmod 600 alexa/deploy.local.conf
```

For a fresh installation, start with the public template:

```bash
cp alexa/deploy.example.conf alexa/deploy.local.conf
chmod 600 alexa/deploy.local.conf
# Edit your real AWS profile, account, region, bucket and Lambda function:
${EDITOR:-nano} alexa/deploy.local.conf
```

The local file is Git-ignored and not distributed; `--deploy` fails
closed when it is absent. Do not store AWS access keys or bearer tokens
in the file.

## Prerequisites and authentication

On the Bindicator host, install AWS CLI **v2**, the system `zip` utility, Python
venv and project dependencies. The build script uses
`~/code/bindicator/.venv/bin/python` and installs requirements into
a temporary directory before assembling the ZIP. Python wheel architecture
must match Lambda; this installation was verified as x86_64, Python 3.13.

For a fresh Debian 13 x86-64 host, use the official AWS CLI v2 archive:

```bash
uname -m                         # Expect x86_64 for this archive
sudo apt-get update
sudo apt-get install -y curl unzip zip
cd /tmp
curl -fsSLo awscliv2.zip \
  https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip
unzip -q awscliv2.zip
sudo ./aws/install                 # Initial installation
aws --version
```

If AWS CLI v2 is **already installed**, do not reinstall it just to deploy.
For an official update, use the documented installer update flags appropriate
to the existing installation, and check `aws --version` afterwards.
The `aws login` command requires AWS CLI v2.32.0 or later.

The existing project venv is prepared as follows if not already present:

```bash
cd ~/code/bindicator
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
```

```bash
aws --version
aws configure list --profile bindicator
aws sts get-caller-identity --profile bindicator
```

AWS CLI browser login is supported on eligible AWS accounts. If your AWS account
uses IAM Identity Center or another authentication method, configure a
suitable AWS CLI profile instead. The configured profile
gets **temporary** login credentials; don't create AWS root access keys.

When the session expires (AWS CLI can refresh cached short-term credentials
for a limited session, typically up to 12 hours):

```bash
aws login --profile bindicator
aws sts get-caller-identity --profile bindicator \
  --query Account --output text
```

Follow the browser-authorisation prompt. Never share an authentication
link containing a one-time token or the cached AWS CLI credential files.
Any broad deployment role is risky; minimise access to the
host and investigate a restricted deployment role if the project offers
the necessary IAM functionality. A profile alias is **not** a permissions
boundary.

To end the browser-login session on the host, run
`aws logout --profile bindicator`. Protect `~/.aws/login/cache` and use
only your regular unprivileged Linux account for AWS CLI commands.

## Check the private S3 bucket

The Lambda and bucket must use the **same AWS Region**. The existing
bucket is private; do not turn off S3 Block Public Access or make the
ZIP public.

```bash
BUCKET=example-private-lambda-deployments
aws s3api get-public-access-block \
  --bucket "$BUCKET" --profile bindicator
aws s3api get-bucket-location \
  --bucket "$BUCKET" --profile bindicator
```

All four `PublicAccessBlockConfiguration` values should be `true`,
and `LocationConstraint` should match your selected Lambda Region.
Bucket versioning is recommended but was **not** confirmed by the above
checks. To inspect it without modifying anything:

```bash
aws s3api get-bucket-versioning \
  --bucket "$BUCKET" --profile bindicator
```

## Build and deploy

From your checked-out Bindicator branch:

```bash
cd ~/code/bindicator
git status --short --branch
git pull --ff-only
.venv/bin/python -m pytest -q -rs
```

To build **without touching AWS**:

```bash
bash alexa/build.sh
```

To use the configured one-command deployment, **after reviewing the
target settings and tests**:

```bash
bash alexa/build.sh --deploy
```

To also update the **existing UK English Alexa skill listing** with the
public Bindicator GitHub link, first configure the Amazon ASK CLI separately
(`ask configure`), then add `DEPLOY_ALEXA_SKILL_ID` and optionally
`DEPLOY_ASK_PROFILE` to your **private** `alexa/deploy.local.conf`. Run:

```bash
bash alexa/build.sh --deploy --update-skill-metadata
```

This option submits only `en-GB` publishing description and summary changes
using the complete skill manifest fetched from Amazon, after the verified
Lambda update. It preserves all other live skill settings and backs up the
previous manifest in a local, private directory. See
[Alexa metadata instructions](../alexa/README.md#update-alexa-skill-listing-metadata).
The ordinary `--deploy` command continues to update Lambda **only**.

This performs all of the following, stopping on an error:

1. Reads the private `alexa/deploy.local.conf` (non-secret target identifiers).
2. Sets the default AWS profile and Region, then verifies the actual
   account ID through STS. It rejects conflicting Region, bucket and
   Lambda target values in `--deploy` mode.
3. Builds `dist/bindicator-alexa.zip` with the ASK SDK and bundled APL
   document and icon graphics.
4. Uploads the ZIP under `bindicator/alexa/` using an object key ending
   in the first 16 characters of the local ZIP's SHA256 digest.
5. Calls `aws lambda update-function-code` with that S3 bucket and key.
6. Waits for `aws lambda wait function-updated` to complete.

The SHA-derived object key separates differing byte contents; it is
**not** a cryptographic signature, a substitute for reproducible builds,
or a release version number. Keeping or deleting old S3 objects is a
separate retention decision.

For **other installations**, the explicit options are still available:

```bash
# Only upload; Lambda is NOT changed.
AWS_PROFILE=YOUR_PROFILE AWS_DEFAULT_REGION=YOUR_REGION \
  bash alexa/build.sh --s3-bucket YOUR_PRIVATE_BUCKET

# Upload and update a nominated existing Lambda.
AWS_PROFILE=YOUR_PROFILE AWS_DEFAULT_REGION=YOUR_REGION \
  bash alexa/build.sh \
  --s3-bucket YOUR_PRIVATE_BUCKET \
  --lambda-function YOUR_LAMBDA_FUNCTION
```

A custom `--s3-key` may also be provided, but using a fixed key can
overwrite a previous object; prefer the generated unique key. Passing
`--deploy` does **not** permit overriding its verified bucket/function.

## Verify and test

The build script's Lambda waiter returning successfully means the code
update has completed. Confirm the final state separately:

```bash
aws lambda get-function-configuration \
  --function-name bindicator-alexa \
  --profile bindicator --region eu-west-2 \
  --query '{Runtime:Runtime,Architectures:Architectures,LastModified:LastModified,LastUpdateStatus:LastUpdateStatus,State:State}' \
  --output json
```

Expect `Runtime=python3.13`, `Architectures=["x86_64"]`,
`LastUpdateStatus=Successful`, and `State=Active`.
Check the latest Lambda CloudWatch logs if a request fails; keep log
output clear of tokens.

To validate functionality, say **"Alexa, ask Bin Buddy what bins are next"**
and verify both the spoken response and the Echo Show APL card.
The APL view is shown **when invoked**, not as a permanent Alexa home
screen. Check the banner, date, countdown, waste-type icons, status
and screen fit; confirm the voice-only fallback separately.
Only test the **"I've put the bins out"** touch control while a
real active reminder is present, as it changes live Hue state.
The reminder acknowledgement API must be deployed on the Bindicator host
(`sudo bash deploy/install.sh`) separately from the Lambda ZIP.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| `aws: command not found` | Install AWS CLI v2 on the Bindicator host and check `aws --version` |
| AWS login expired or credentials missing | Run `aws login --profile bindicator`, then `aws sts get-caller-identity --profile bindicator` |
| Account/Region/target mismatch | Verify profile, `alexa/deploy.local.conf`, bucket Region and Lambda name; do not bypass the guard |
| S3 `AccessDenied` | Check profile permissions, S3 ownership, bucket policy, encryption/KMS restrictions and prefix |
| Lambda update `AccessDenied` | Check `lambda:UpdateFunctionCode` for the target and Lambda's access to the S3 object |
| `ResourceConflictException` | Check for a previous Lambda update still running; wait and retry |
| `InvalidParameterValueException` / cannot read S3 | Ensure bucket and function are in the same Region and the object exists |
| Lambda import error | Check ZIP structure, installed ASK SDK dependencies, handler, runtime and architecture |
| Alexa speaks but no APL appears | Confirm APL is enabled in the Alexa skill Interfaces and test a compatible Echo Show |
| Alexa cannot reach Bindicator | Confirm local API, Cloudflare Access service-token headers, Lambda env vars and outbound HTTPS |

Useful **read-only** checks:

```bash
aws lambda get-function-configuration \
  --function-name bindicator-alexa --profile bindicator --region eu-west-2 \
  --query '[State,LastUpdateStatus,LastUpdateStatusReason]' --output json

curl -fsS http://127.0.0.1:18050/api/v1/health
systemctl is-active bindicator-api.service
```

## Rollback

If a new Lambda version fails, find the object key of a previously
working ZIP in the private S3 bucket; do **not** guess which hash
corresponds to a known-good release. List candidates:

```bash
aws s3 ls \
  s3://example-private-lambda-deployments/bindicator/alexa/ \
  --profile bindicator
```

With an identified known-good ZIP object, replace
`KNOWN_GOOD_OBJECT_KEY` in this **intentional code-changing command**:

```bash
aws lambda update-function-code \
  --function-name bindicator-alexa \
  --s3-bucket example-private-lambda-deployments \
  --s3-key KNOWN_GOOD_OBJECT_KEY \
  --profile bindicator --region eu-west-2

aws lambda wait function-updated \
  --function-name bindicator-alexa \
  --profile bindicator --region eu-west-2
```

Then repeat the Lambda configuration check and a read-only Alexa
collection query. S3 restoration affects Lambda **code only**;
it does not undo local Bindicator service or configuration changes.
Keep a record of the tested deployment's S3 key if rollback is important.

## Security and operational boundaries

- `alexa/deploy.local.conf` stores local account, profile, Region, bucket
  and function names; **never** add access keys or bearer tokens to it.
- S3 archives and Lambda environment variables may contain sensitive
  code/configuration; use private buckets and tightly scoped permissions.
- The only public-facing Bindicator endpoint is the **Cloudflare Access
  protected API hostname**. Don't publish the LAN management page.
- Running `bash alexa/build.sh` alone has no AWS side effects;
  `--s3-bucket` uploads, and `--deploy` explicitly updates live code.
- Source changes, a successful upload and successful local tests do not
  prove that the deployed Echo Show visuals or Hue acknowledgement work;
  perform the live verification above.

See [Alexa skill and Echo Show guide](../alexa/README.md),
[local API](local-api.md) and
[Cloudflare access configuration](cloudflare-setup.md).
