# Bin Buddy — Alexa spoken-command cheat sheet

The **displayed skill name** is **Bin Indicator**. Say **Bin Buddy** to invoke it.
Every command begins with **“Alexa, …”**.

| What you want | What to say |
| --- | --- |
| Open the skill | **“Alexa, open Bin Buddy.”** |
| Next collection | **“Alexa, ask Bin Buddy what bins are next.”** |
| Next collection date | “Alexa, ask Bin Buddy when is the next bin collection.” |
| Reminder status | “Alexa, ask Bin Buddy are reminders enabled.” |
| Pause reminders | “Alexa, ask Bin Buddy to pause bin reminders.” |
| Resume reminders | “Alexa, ask Bin Buddy to resume reminders.” |
| Toggle reminders | “Alexa, ask Bin Buddy to toggle reminders.” |
| Confirm bins put out | **“Alexa, tell Bin Buddy the bins are out.”** |
| Alternative bins-out command | “Alexa, ask Bin Buddy, I have put the bins out.” |
| Preview Hue lights for 10 seconds | **“Alexa, ask Bin Buddy to show the next bins for ten seconds.”** |
| Preview for another duration | “Alexa, ask Bin Buddy to show the next bins for twenty seconds.” |
| Keep bin colours until collection morning | “Alexa, ask Bin Buddy to show the bins until collection day.” |
| Help | “Alexa, ask Bin Buddy for help.” |
| End the skill | “Alexa, stop.” |

Notes:

- **Bins out** acknowledges the currently active reminder and restores the lights
  where safe; it does **not** disable later collection reminders. Without an
  active reminder, it reports that there is nothing to clear.
- **Pause** disables reminders until they are resumed. It is different from
  acknowledging just this collection.
- The short preview accepts **1–60 seconds**. A missing or invalid duration
  does not accidentally activate the persistent reminder.
- The persistent Hue indication is deliberately separate and lasts until the
  collection morning, subject to Bindicator's normal scheduling and controls.
- On supported Echo Show devices, asking about the next bins displays a
  Bindicator-themed APL screen. The **“I've put the bins out”** screen button
  is enabled only while an active reminder can be acknowledged.
- The skill reads the real configured Bindicator collection feed; Alexa's own
  unrelated answers are not a reliable indication of this skill's calendar.
