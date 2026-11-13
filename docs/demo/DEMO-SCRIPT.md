# Demo script: 7 minutes for teachers

**One-line pitch:** "Predestination is a calendar for students. You tell it what you need to get done, by typing
or speaking, and it finds the time around your classes. It never changes your calendar until you approve."

Run it from your laptop (not the deployed site): it avoids cold starts and Wi-Fi problems, and the MCP part only
works locally.

## 30 minutes before

1. `scripts\dev.py seed`, then `scripts\dev.py up`. Wait for "Predestination is starting".
2. In **Chrome or Edge**, open `http://127.0.0.1:8000/home` (not `localhost`) and sign in as `student@example.com`.
3. Click **AI Planner**, press **Speak** once and allow the microphone. Say a few words, then press **Stop**.
4. Zoom the page to 110% and close notifications. Keep the **Month** view open.
5. Open Claude and check the Predestination tools are connected (see "MCP setup" below).
6. **Go easy on AI rehearsals.** With Groq (free plan) you get about 1,000 requests and 200K tokens a day per model, which is
   roughly 20 add-event runs. With OpenRouter free models you get only about 50 requests a day (3 to 6 per run). Both
   reset daily at 05:30 IST (00:00 UTC).
7. Have a screen recording of a good run ready as a backup.

## The 7 minutes

| Time | Show | Say |
|---|---|---|
| 0:00 | Month view with the seeded week | "This is a student's week: lectures, lab, gym, a part-time job. Everything is hand-built, no calendar library." |
| 0:45 | Type `Study group tomorrow at 6pm for 1 hour` in the bar, click **Fill details** | "It reads the sentence and asks me to confirm AM or PM and the length. It never guesses times." Click **Add to calendar**. |
| 1:45 | Switch to **Week** and **Day** views | "Same events, different views. Overlaps are rejected, and weekly classes repeat." |
| 2:15 | Open **AI Planner**, press **Speak**, say: "Add a study group tomorrow at 6 PM for one hour called Algorithms review", press **Stop** | "Voice becomes text first and is never sent automatically. I can edit it." Then press **Ask assistant**. |
| 2:45 | While it works (a few seconds on Groq, about 40 on OpenRouter free models), watch the stage text | "The model only suggests. Code checks the times, overlaps and total hours." Mention that free models are slow. |
| 3:30 | Approval card appears | "This is exactly what will change. Nothing is saved yet." Click **Approve**, then **View saved event**. |
| 4:15 | Type: `Add a chemistry lab report session on Saturday` | "It asks what is missing instead of guessing." Answer: `4 PM for 2 hours`. When the card appears, click **Reject**. "Nothing was added. The human stays in control." |
| 5:15 | Switch to Claude. Ask: "Using Predestination, what is free on Tuesday evening?" Then "Propose a 2 hour calculus revision at 5pm on Tuesday." Then "Create it." | "The same calendar is available to any AI app through MCP. It proposes first and only saves when I agree." Refresh the web calendar to show the new event. |
| 6:15 | `docs/demo-architecture.md` diagram | "Free tools only. Next steps: Google Calendar, accounts, deployment." |
| 6:45 | Questions | |

Keep the **Fill details** path as your safe path. It does not use the AI and always works.

## If something breaks

| Problem | Do this |
|---|---|
| The assistant takes more than 90 seconds, or shows "could not complete" | Say "free models are busy sometimes", press **Cancel request**, and show **Fill details** instead. Start a new request rather than pressing Retry. |
| Voice does not work | Say "voice depends on the browser", type the same sentence, and carry on. |
| Browser microphone prompt appears | Click **Allow** (you did this in step 3). |
| Page shows "Sign in again" | Sign in again. Sessions last 12 hours here. |
| Saves fail with a 403 error | You opened `localhost`. Use `127.0.0.1`. |
| Claude does not list the tools | Skip the MCP step and say it is a local integration. Show the architecture diagram instead. |
| Calendar looks empty | Run `scripts\dev.py seed` in a second terminal, then refresh. |

## MCP setup (Claude)

Claude Code:

```bash
claude mcp add predestination -- C:/Users/91729/Desktop/scheduler/.venv/Scripts/python.exe C:/Users/91729/Desktop/scheduler/scripts/dev.py mcp
```

Claude Desktop: add this to `claude_desktop_config.json`, then restart Claude.

```json
{
  "mcpServers": {
    "predestination": {
      "command": "C:/Users/91729/Desktop/scheduler/.venv/Scripts/python.exe",
      "args": ["C:/Users/91729/Desktop/scheduler/scripts/dev.py", "mcp"]
    }
  }
}
```

The database must be running (`scripts\dev.py up` keeps it running). The MCP server acts as the account in
`MCP_USER_EMAIL` in `.env`.

## Likely questions

- **Does the AI write to my calendar by itself?** No. Every change is a draft you approve, and approval is tied to
  that exact draft.
- **What if two people edit at once?** Each change re-checks the latest calendar and is saved in one transaction.
- **Why free models?** The prototype must cost nothing. They are slower and less reliable, so paid models are the
  first change planned.
- **What about privacy?** Event titles go to the model provider. A privacy policy and no-training models are on the
  roadmap.
