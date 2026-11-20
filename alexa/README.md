# Bindicator private Alexa skill

## Contents

- [Before deploying](#before-deploying)
- [Create the Alexa skill](#create-the-alexa-skill)
- [Build the Lambda deployment archive](#build-the-lambda-deployment-archive)
- [Optional S3 upload and Lambda deployment](#optional-s3-upload-and-lambda-deployment)
- [Echo Show visual interface](#echo-show-visual-interface)
- [Spoken-command cheat sheet](#spoken-command-cheat-sheet)
- [Test safely](#test-safely)
- [Diagnostics](#diagnostics)
- [Security notes](#security-notes)
- [Related documentation](#related-documentation)

This adapter is an **optional** AWS Lambda custom skill. It does not replace
the Bindicator service on the Bindicator host. The optional AWS CLI deployment
uses temporary browser-login credentials stored by AWS CLI on that host;
Lambda-only API/Cloudflare credentials stay in the Lambda environment.

## Before deploying

The private Alexa Custom Skill runs in AWS Lambda and calls the local
Bindicator API through **Cloudflare Access and Tunnel**, with separate
service-token and API bearer-token authentication.

1. Check `bindicator-api.service` on the Bindicator host:
   `curl http://127.0.0.1:18050/api/v1/health`.
2. Follow [Cloudflare setup](../docs/cloudflare-setup.md) to install the
   tunnel, configure Access protection and verify the two-layer HTTPS API.
3. See [Cloudflare CLI reference](../docs/cloudflare-cli.md) for Node.js/`cf`
   installation, resource creation and inspection, and credential rotation.
4. Prepare the Amazon developer account and AWS Lambda (independent of
   Cloudflare setup).

Keep the API bound to localhost, and never expose Hue keys, the private
iCalendar feed URL or Access service secrets.

## Create the Alexa skill

Open https://developer.amazon.com/alexa/console/ask and create a **Custom**
skill in the `en-GB` locale, invoking **bin buddy** (the displayed skill name can remain **Bin Indicator**). Open
**Interaction Model → JSON Editor** and paste the whole content of
`alexa/interaction-model-en-GB.json`, then save and build the model.

**Changing the invocation name on an existing skill:** in the Alexa Developer
Console, open **Build → Interaction Model → JSON Editor** for English (UK),
replace the model with this updated file, select **Save Model** and then
**Build Model**. Keep the existing skill ID, Lambda ARN, endpoint and
Cloudflare settings. An invocation-name-only change does **not** require
rebuilding or uploading the Lambda ZIP. After the build, test
"open bin buddy" in the simulator and on the enrolled Echo device.

The utterances are mapped to these handlers (examples are command fragments;
see the exact complete spoken phrases in [COMMANDS.md](COMMANDS.md)):

| Spoken command fragment | Intent |
| --- | --- |
| "pause bin reminders" | PauseIntent |
| "resume reminders" | ResumeIntent |
| "toggle reminders" | ToggleIntent |
| "tell me the next bins" | NextCollectionIntent |
| "status" / "what is the status" | StatusIntent |
| "I have put the bins out" | BinsOutIntent |
| "show the next bins for ten seconds" | ShowNextIntent |
| "show the bins until collection day" | ShowPersistentIntent |

The **persistent** command is deliberately explicit; if Alexa misses a
duration slot, it asks for clarification rather than activating a potentially
week-long lighting notification.

## Build the Lambda deployment archive

On the Bindicator host, the ZIP can be built without accessing AWS:

```bash
cd ~/code/bindicator
sudo apt-get install -y zip python3-pip
bash alexa/build.sh
unzip -l dist/bindicator-alexa.zip | grep 'alexa/lambda_function.py'
```

`dist/bindicator-alexa.zip` is the ZIP to upload to AWS Lambda. The handler
name is exactly `alexa.lambda_function.lambda_handler`. Use a supported
Python Lambda runtime compatible with the ZIP build environment. For the
existing Bindicator installation this is Python 3.13, x86_64 in eu-north-1. Set the Lambda timeout to around **8 seconds**, with 128 MB
or more of RAM. The API request timeout is four seconds.

Create the AWS Lambda function and upload the ZIP using the AWS Console or
AWS CLI. Add an **Alexa Skills Kit trigger** limited to the specific skill
ID, and paste the Lambda function ARN into the Alexa skill's Endpoint page.
The adapter **also verifies** `ALEXA_SKILL_ID` using the ASK SDK's skill-ID
verification. Do not configure a public Lambda Function URL.

Configure these AWS Lambda environment variables, preferably using
an appropriately scoped secret manager/KMS rather than embedding values
in the source or interaction model:

- `ALEXA_SKILL_ID`: the exact skill ID shown in Alexa Developer Console
- `BINDICATOR_API_URL`: `https://bins.example.com` (replace with your Cloudflare Access-protected hostname; HTTPS only)
- `BINDICATOR_API_TOKEN`: contents of `/etc/bindicator/api.token` on the Bindicator host
- `CF_ACCESS_CLIENT_ID`: Cloudflare Access service-token Client ID (ends in `.access`)
- `CF_ACCESS_CLIENT_SECRET`: matching Access service token secret

Limit read access to the Lambda configuration to authorised AWS principals.
Never use the Hue Bridge keys or private iCalendar feed URL in Lambda.

**Important:** Lambda must have outbound network access to HTTPS on port
443. If you attach it to a private VPC, configure appropriate NAT egress;
for this small adapter a VPC is not necessary.

## Optional S3 upload and Lambda deployment

For the full verified installation guide, authentication, AWS permissions,
verification, troubleshooting and rollback, see
[AWS/S3 deployment operations](../docs/aws-deployment.md).
For AWS accounts that support CLI browser login, use
`aws login --profile bindicator` to obtain temporary credentials. Other
accounts can use suitable temporary AWS CLI credentials or IAM Identity Center.

The `--deploy` shortcut has been exercised successfully for the original
installation. For a new deployment, create your own resources and confirm
their IDs, Region, Lambda status and Alexa behaviour before relying on it.



The build is **local-only by default**, so running `bash alexa/build.sh` will
never upload or deploy anything. For convenient updates, install and configure
[AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
on the Bindicator host. Create a **private** S3 bucket in the **same AWS Region** as
your existing Lambda function, with public access blocked and bucket
versioning recommended. Keep AWS credentials out of the repository.

### One-command deploy for the existing Bindicator AWS installation

Copy `alexa/deploy.example.conf` to the Git-ignored `alexa/deploy.local.conf`
and fill in your own profile, account, Region, private bucket and Lambda name.
For migration from the older private branch, **copy** the tracked
`alexa/deploy.conf` to `alexa/deploy.local.conf` **before** switching branches.
See [migration instructions](../docs/aws-deployment.md#existing-installation).
The checked-in example is not deployable as-is. Authentication remains
managed by AWS CLI and no AWS credentials belong in the file.

From your Bindicator host:

```bash
cd ~/code/bindicator
bash alexa/build.sh --deploy
```

This builds the ZIP, uploads it to the private bucket, updates the configured
Lambda, and waits for completion. Before building it checks the AWS account
ID and Region; it rejects a different bucket or Lambda target when using
`--deploy`. If your AWS browser-login session has expired, run
`aws login --profile bindicator` and retry.

Plain `bash alexa/build.sh` **still only builds locally**. The explicit
`--s3-bucket` and `--lambda-function` options below remain available for
other installations.

First confirm the intended AWS identity and region with
`aws sts get-caller-identity --profile YOUR_PROFILE` and
`aws configure list --profile YOUR_PROFILE`. For another installation,
select that installation's own AWS profile and Region.

```bash
cd ~/code/bindicator

# Build locally (unchanged default).
bash alexa/build.sh

# Build and upload only: does NOT deploy the Lambda.
bash alexa/build.sh --s3-bucket YOUR_PRIVATE_BUCKET

# Build, upload, then explicitly update the existing Lambda function.
bash alexa/build.sh --s3-bucket YOUR_PRIVATE_BUCKET \
  --lambda-function YOUR_EXISTING_LAMBDA_FUNCTION

# Optional, specify a fixed destination object key if required.
bash alexa/build.sh --s3-bucket YOUR_PRIVATE_BUCKET \
  --s3-key bindicator/alexa/testing.zip
```

By default uploaded objects use a SHA256-based unique filename within
`bindicator/alexa/` to avoid silently overwriting earlier builds.
The upload uses `aws s3 cp`; when `--lambda-function` is provided, it
then calls `aws lambda update-function-code` with the uploaded bucket and
key. **An S3 upload alone does not update the function.** <https://docs.aws.amazon.com/cli/latest/reference/lambda/update-function-code.html>

The AWS principal used to upload needs `s3:PutObject` on the chosen prefix.
An explicit Lambda deployment additionally requires
`lambda:UpdateFunctionCode` on the target function and permission for
Lambda to retrieve the bucket object. S3 and Lambda must be in the same
AWS Region; a customer-managed KMS key may require additional permissions.
The build does not create buckets, configure IAM, modify the runtime, or
change the skill's endpoint, triggers or environment variables.

After deploying, check Lambda's last-update status in AWS, and test the
skill on the actual Echo Show before treating the deployment as verified.
See [verification and rollback](../docs/aws-deployment.md#verify-and-test)
for copy-and-paste commands and a recovery procedure.

## Echo Show visual interface

The Echo Show interface uses **Alexa Presentation Language (APL)** and the
existing Bindicator web dashboard visual style: dark navy background,
mint-green action accent, a new native vector mascot-style bin-girl logo
in the header, and the same four wheelie-bin graphic shapes and waste-category
colours. The main screen now uses forest-green instead of blue-tinted panels;
Recycling stays blue as a waste-type identifier. The logo and banner are drawn locally by APL, requiring no publicly hosted
images or additional network calls. The mascot mark is an original vector
interpretation, not the exact website artwork; matching that asset would
need a separately hosted HTTPS image. The next date, collection types, countdown, active
indicator state and acknowledgement state come from the authenticated local
Bindicator API. No arbitrary URLs, secrets, Hue IDs or calendar feeds are
included in the APL datasource.

**Before testing APL:**
1. Update the Bindicator service on the Bindicator host using the repository's
   normal install/upgrade procedure. The authenticated status API now returns
   an extra `acknowledged_date` field, used only for display.
2. In Alexa Developer Console, open the **Build** tab and enable
   **Alexa Presentation Language** under **Interfaces**; save the interfaces
   and rebuild the interaction model if the console requests it.
3. For the verified installation, run `bash alexa/build.sh --deploy`
   after passing tests (or build and manually upload the ZIP).
   Preserve the skill ID, ARN, trigger, environment variables and Cloudflare
   Access setup. This updates Lambda code, not the the Bindicator host API.
4. Enable **Development** testing, invoke **"Alexa, ask Bin Buddy what bins
   are next"** on a supported Echo Show, and inspect the visual layout.
   Voice-only devices still use the spoken response and supported SimpleCard.
5. Only while an active reminder is displayed, try the touchscreen
   **"I've put the bins out"** button. This uses the same authenticated
   bins-out action as the spoken command, respecting Hue restoration safeguards.
   No action is sent when the button is disabled.

The APL layout is stored in `alexa/echo_show.json`; its data mapping and
touch-event validation are in `alexa/apl.py`. It is bundled into the Lambda
ZIP automatically. APL is an **on-invocation** visual, not a permanently
pinned or always-on Echo Show dashboard. Visual availability depends on
device support and the skill interface being enabled. Do not publish
secrets or turn on a public API endpoint to support the display.

## Spoken-command cheat sheet

See [COMMANDS.md](COMMANDS.md) for all current **Bin Buddy** phrases,
including next collection, status, pause/resume, previews, and bins-out
acknowledgement.

## Test safely

First run the local tests. The Alexa tests mock AWS/Cloudflare/Bindicator
calls and do not modify Hue lights; the full suite also exercises the
local application and docs checks:

```bash
cd ~/code/bindicator
.venv/bin/python -m pytest -q -rs
```

In the Alexa Developer Console's **Test** tab (enable skill testing
for development):

1. "Open Bin Buddy" — welcome/help only.
2. "Ask Bin Buddy what bins are next" — read-only next collection from the active provider.
3. "Ask Bin Buddy if reminders are enabled" — read-only status.
4. "Ask Bin Buddy to pause bin reminders" — changes Bindicator state,
   restores a previous alert if one is active.
5. "Ask Bin Buddy to resume bin reminders".
6. "Ask Bin Buddy, I have put the bins out" — acknowledges the current alert, restores previous light appearance where unchanged, and leaves future reminders enabled.
7. "Ask Bin Buddy to show the next bins for ten seconds" —
   launches the background preview and restores afterwards.
8. Only after verifying the above, try "show the bins until collection day".
   That lasts until the collection morning; "pause" restores it.

For personal Echo devices, enable **Development** testing in the Alexa
Developer Console Test tab and use the same Amazon account as your Echo.

The skill stays in development for your own Alexa devices; there is no
need to publish it in the Alexa Skills Store for personal testing.
You must use the Alexa account enrolled as a tester/developer.

## Alexa app visual cards and project link

The current recommended UK English Alexa skill listing text, including the
public source/download URL, is maintained in
[SKILL_METADATA.md](SKILL_METADATA.md). Changing that file does not
automatically update the Alexa Developer Console; copy the descriptions
to Distribution → Skill Preview and save them.


The Lambda includes a **SimpleCard** with each spoken intent response, so
compatible Alexa companion-app activity views can display the same collection
date, collection type or action confirmation that Alexa says. The cards do not
make additional Bindicator API requests. Actual card visibility varies with
Alexa app version and device; this is not an APL Echo Show layout.

To tell potential users where to find the software, put a concise project
reference in **Distribution → Skill Preview → Detailed Description**, for
example: "Bindicator is self-hosted software. Source code and installation
instructions: https://github.com/accidentalskeleton/bindicator".
This is informational listing text, not a guaranteed tappable custom link.
Do not mislabel the project URL as the privacy-policy or terms-of-use URL.
The repository must be public (or each reader given GitHub access) before
other people can actually view, clone or review it. Beta testers may see
the listing metadata, but a beta skill is not a public download catalogue.
Also note that users cannot operate your personal Bindicator cloud endpoint
as their own system: the current Lambda is configured for your own server.

After deploying the updated Lambda, ask what bins are next and inspect the
Alexa app's recent skill activity/card view to check presentation. Standard
Alexa cards are separate from optional APL for Echo Show devices.

## Diagnostics

Check Cloudflare Tunnel status, Access request logs, Lambda CloudWatch logs
and `journalctl -u bindicator-api.service -n 50 --no-pager` on the Bindicator host.

In AWS Lambda select **Monitor → View CloudWatch logs**, open the log stream
for the failed invocation, and search for `Bindicator Alexa API`. The adapter
logs only controlled failure categories: `configuration invalid`, HTTP
`status` plus `response_type` (`html`, `json`, or `other`), network `kind`
(`timeout` or `connection`), and invalid/oversized JSON response. The
`response_type` is a diagnostic clue, not proof of which layer rejected the
request. Logs intentionally omit request URLs, secrets, headers, response
bodies and raw exception strings; the spoken response remains generic.

After updating the Lambda ZIP, the same Alexa test request generates the
new diagnostic entries. You do **not** need to rebuild the Alexa interaction
model or reconfigure its endpoint. If a Cloudflare token or Bindicator token
was exposed in a terminal or screenshot, rotate the credential and update
its matching Lambda environment variable before further use.

The Lambda returns brief spoken error messages without disclosing secrets,
internal Hue UUIDs, raw calendar URLs, or long traceback details. An HTML HTTP 401/403 usually indicates a Cloudflare Access policy/token issue; a JSON HTTP 401 can indicate the Bindicator Bearer token is missing. HTTP 400 from
Bindicator often means its Host header was not rewritten; HTTP 409 means
Bindicator refused the action (for example paused, busy, or an existing alert).

## Security notes

The skill runs as a cloud Lambda, not locally on the Echo. Only the
Bindicator HTTP API is local to the Bindicator host. Keep Cloudflare Access in front
of it; do not forward router ports, change Bindicator's bind address,
or use public API keys.

Revoke Cloudflare Access tokens and rotate the Bindicator token if either
is exposed. Once Lambda has been updated with new credentials, the old
token should no longer work.

## Related documentation

- [Documentation index](../docs/README.md)
- [Bindicator overview and installation](../README.md)
- [Local API contract and testing](../docs/local-api.md)
- [LAN Calendars and Mapping controls](../docs/lan-management.md)
- [Cloudflare Tunnel/Access setup](../docs/cloudflare-setup.md)
