# Presentation plan: Predestination (5 to 7 minutes, for teachers)

**One sentence:** a calendar for students that you can talk to. It plans around your classes, and it never changes
your calendar until you say yes.

The longer version with exact lines is `DEMO-SCRIPT.md`; the pre-demo tick list is `TEST-CHECKLIST.md`.

## Before you walk in (10 minutes)

1. `scripts\dev.py seed`, then `scripts\dev.py up`. Leave it running.
2. In Chrome or Edge open `http://127.0.0.1:8000/home` and sign in as `student@example.com`.
3. Open **AI Planner**, tap **Talk** once and allow the microphone. Turn the sound on.
4. Run `scripts\dev.py check` in a second terminal. All green means you are ready.
5. Have this plan, the architecture diagram (`docs/demo-architecture.md`) and a backup screen recording ready.

## The five beats

| # | Minutes | Show | Say |
|---|---|---|---|
| 1 | 0:00 to 0:45 | The month view | "This is a student's week: lectures, a lab, gym, a job. The problem: finding time for study around all that." |
| 2 | 0:45 to 2:00 | Type "Study group tomorrow at 6pm for 1 hour", click **Fill details**, then **Add to calendar** | "Add things by hand in seconds. It checks overlaps and asks me to confirm AM or PM; it never guesses a time." |
| 3 | 2:00 to 4:30 | **AI Planner**: tap **Talk**, say "What's on my calendar tomorrow?" Then: "Add a review of my project tomorrow at 9 AM." Then: "Yes, save it." | "I can talk to it. It answers from my real calendar, fills in the obvious (a 1 hour meeting) and tells me what it assumed. Nothing is saved until I say yes." |
| 4 | 4:30 to 5:30 | Type "Plan 4 hours of calculus revision this week". Read the draft, click **Reject** | "For bigger goals it proposes a plan. I can reject it, and nothing changes. The human always decides." |
| 5 | 5:30 to 6:30 | Switch to Claude: "Using Predestination, what's free on Tuesday evening?" | "The same calendar works inside other AI apps through MCP, an open standard for connecting AI to tools." |

Close (30 seconds): show the architecture diagram. "Built with free tools only. Next: Google Calendar sync, student
accounts, and putting it online."

## If something goes wrong

- The AI is slow or errors: say "free AI models are busy sometimes", press **Cancel request**, and carry on with
  **Fill details**, which never uses AI.
- Voice does not work: type the same sentence. Say "voice needs Chrome and a microphone".
- Wait 30 to 60 seconds between AI requests; the free plan has a per-minute limit.
- Do not rehearse the AI more than once.

## Questions teachers may ask

| Question | Answer |
|---|---|
| Can the AI delete my calendar? | No. It can only propose. Saving needs your approval, and removals need a tap, not just a spoken yes. |
| What does it cost? | Nothing to run today: free AI models and free tools. |
| Where is my data? | On this laptop for the demo. Event titles are sent to the AI provider (Groq); a privacy policy is planned. |
| Is it tested? | Yes: 110 automated tests plus a one-command demo check. |
| What's next? | Google Calendar sync, accounts, putting it online, rebalancing a plan after a missed session. |
