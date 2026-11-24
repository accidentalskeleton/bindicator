# Alexa skill listing metadata (en-GB)

These are the recommended UK English publishing details for the **Bin Indicator**
Alexa skill (spoken invocation name: **Bin Buddy**). They are not part of the
Lambda package or interaction model. The deployable JSON source is [skill_listing.en-GB.json](skill_listing.en-GB.json).
Editing this document alone **does not** change the live skill in the
Amazon Developer Console. Run `bash alexa/build.sh --deploy --update-skill-metadata`
after configuring ASK CLI and your private skill ID to publish the JSON listing.

## Short description

Find out which bins are next with Bindicator, the open-source Philips Hue
bin reminder.

## Detailed description

Bin Indicator is the Alexa companion to Bindicator, a free, open-source,
self-hosted bin collection reminder for Philips Hue lighting.

Ask Bin Buddy which bins are next, check collection dates, preview reminders
and acknowledge when the bins have been put out. Compatible Echo Show devices
can also display collection information.

Bindicator is released under the GNU General Public License v3. Source code,
installation instructions, documentation and issue reporting are available at:

https://github.com/accidentalskeleton/bindicator

This Alexa skill requires your own configured Bindicator installation and
associated integrations. It is not a hosted bin collection service.

## Skill preview example phrases

Use these three **Example Phrases** for the English (UK) skill listing.
The **displayed skill name** is **Bin Indicator**, but the **spoken invocation
name** is **bin buddy**. Do not use "bin dicator" or "bindicator" as the invocation
name in these examples.

1. **Alexa, ask Bin Buddy what bins are next**
2. **Alexa, ask Bin Buddy when is the next bin collection**
3. **Alexa, tell Bin Buddy the bins are out**

These are full phrases for the Alexa **Distribution → Skill Preview** listing,
not sample utterances to paste into the interaction model. The model already
uses `"invocationName": "bin buddy"` in
[`interaction-model-en-GB.json`](interaction-model-en-GB.json); see
[`COMMANDS.md`](COMMANDS.md) for other supported spoken commands.

## Where to update the Alexa skill

In the [Alexa Developer Console](https://developer.amazon.com/alexa/console/ask):

1. Open your existing **Bin Indicator** skill. Do not create a new skill.
2. Select **Distribution → Skill Preview → English (UK)**.
3. Set **Short Description** and **Detailed Description** to the text above.
4. Replace the three **Example Phrases** with the Bin Buddy phrases above.
5. Save the details; keep the existing skill ID, invocation name, backend
   endpoint, skill icons, privacy fields and other publishing settings.
6. Preview the skill listing in the Alexa app. An unsubmitted development skill
   will not automatically appear as a public Alexa Skills Store listing.

The manifest JSON equivalent of Detailed Description is
`manifest.publishingInformation.locales["en-GB"].description`.
If using ASK CLI / SMAPI to update this property, first fetch and back up the
*complete existing skill manifest*, change only this locale's description and
summary, and retain every other field. Do not overwrite the skill manifest
with a partial example.

The GitHub URL is an informational project reference, not a Privacy Policy
or Terms of Use URL, and Amazon does not guarantee it will be clickable.

## Project security and deployment scope

The downloadable source is public. The personal Bindicator Lambda and
Cloudflare endpoint are **not** a shared hosting service for other people.
Anyone distributing their own skill must configure their own infrastructure
and follow Alexa publication and privacy requirements.
