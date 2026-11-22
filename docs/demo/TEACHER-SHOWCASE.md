# Teacher showcase: how to run it and what to show

## 1. Start the app so other devices on the Wi-Fi can open it

In a terminal in the project folder:

```bash
.venv\Scripts\python.exe scripts\dev.py seed
.venv\Scripts\python.exe scripts\dev.py up --lan
```

Leave that terminal open. It prints the address other devices should use, for example
`http://192.168.0.111:8000/home`. The address can change when the Wi-Fi reconnects; run `ipconfig` to check.

**One-time Windows step (you run this, in PowerShell as Administrator).** Windows blocks incoming connections
on public networks, so allow port 8000 on the private profile and mark the Wi-Fi network as Private
(Settings > Network & internet > Wi-Fi > your network > Private):

```powershell
New-NetFirewallRule -DisplayName "Predestination demo" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Private
```

Remove it after the demo with `Remove-NetFirewallRule -DisplayName "Predestination demo"`.

## 2. Demo account

| Field | Value |
|---|---|
| Address to open | `http://<laptop address>:8000/home` (on the laptop itself: `http://127.0.0.1:8000/home`) |
| Email | `student@example.com` |
| Password | `predestination-demo` |

This is a fake student account with fake events. Do not use it for anything real. Anyone on the same Wi-Fi who
knows the address can sign in while the app runs, so stop `dev.py up` after the demo.

Use **Chrome or Edge**. Save requests need the laptop address, so do not open the app through `localhost`.

## 3. Fill the calendar with AI requests (optional, uses Groq's free quota)

The seeded week already has lectures, a lab, gym, a club and a part-time job. To add a few AI-made study
blocks as well, run the teacher suite in a second terminal:

```bash
set DEMO_AI=1
.venv\Scripts\python.exe -m pytest -m teacher_demo -q
```

It takes about five minutes because it waits 35 seconds between AI requests. Without `DEMO_AI=1` only the
fast checks run. Run `dev.py seed` again before a second run, or the same events will clash.

These are the requests, in the order the suite sends them:

| # | Type this | What should happen |
|---|---|---|
| 1 | Study group tomorrow at 6pm for 1 hour | Draft at 6 to 7 PM tomorrow. Approve it. |
| 2 | Add a review of my project tomorrow at 9 am | Draft 9 to 10 AM, with "length assumed: 1 hour". Approve it. |
| 3 | Schedule a 2 hour Python practice on Sunday at 10 am | Draft on Sunday 10 to 12. Approve it. |
| 4 | Add a dentist appointment on Friday at 3 pm for 1 hour | Draft on Friday 3 to 4 PM. Approve it. |
| 5 | Study session on Wednesday at 8 pm for 90 minutes | Draft on Wednesday 8 to 9:30 PM. Approve it. |
| 6 | schedule gym at 7 on Saturday | Asks "AM or PM?" and saves nothing. Cancel it, or answer PM and reject the draft. |

The suite runs the first five and checks each one with approve or reject. Request 6 checks the clarifying
question. Expect 3 to 10 seconds per request. Do not chain several AI requests without a 30 to 60 second
gap, or the free limit will fail one.

Multi-session plans such as "Plan 4 hours of calculus revision this week" make several AI calls and often hit
the free limit. Leave them out of the live demo.

## 4. What to show the teacher (about 6 minutes)

| Time | Show | Say |
|---|---|---|
| 0:00 | Month view with the seeded week | "This is a student's week: lectures, a lab, gym, a part-time job. I need to find study time around all of it." |
| 0:45 | Type `Study group tomorrow at 6pm for 1 hour`, click **Fill details**, then **Add to calendar** | "I type it in plain words. It asks me to confirm AM or PM, and it never guesses a time." |
| 1:45 | Switch to Week and Day views | "Same events, different views. Overlaps are rejected, and weekly classes repeat." |
| 2:15 | AI Planner: press **Talk**, say "What's on my calendar tomorrow?" | "It answers from my real calendar, out loud." |
| 2:45 | Press **Talk**: "Add a review of my project tomorrow at 9 AM" | "It fills in the obvious and tells me what it assumed." |
| 3:30 | Press **Talk**: "Yes, save it" | "Nothing is saved until I say yes. A spoken yes works for new events only." |
| 4:15 | Type `schedule gym at 7`, answer `PM`, then click **Reject** | "It only asks when something is truly unclear. I can say no, and nothing changes." |
| 5:15 | Open Claude and ask: "Using Predestination, what is free on Tuesday evening?" | "The same calendar works in other AI apps through MCP. It proposes first, and saves only when I agree." |
| 6:00 | Show `docs/demo-architecture.md` | "Free tools only. Next: Google Calendar, accounts, putting it online." |

Keep the **Fill details** path as the safe fallback. It does not use AI and always works.

## 5. If something breaks

| Problem | What to do |
|---|---|
| The assistant takes more than 90 seconds | Say "free AI models are busy sometimes", press **Cancel request**, and carry on with **Fill details**. |
| Voice does not work | Type the same sentence and say "voice depends on the browser". |
| Saves fail or show "Untrusted request origin" | You opened the app through `localhost`. Use the laptop address shown by `dev.py up --lan`. |
| Another device cannot connect | Check the firewall rule, that the Wi-Fi is Private, and the address from `ipconfig`. |
| Calendar looks empty | Run `dev.py seed` in a second terminal and refresh. |

## 6. Likely questions

- **Can the AI change my calendar by itself?** No. Every change is a draft you approve, and approval applies to that exact draft.
- **Who can see my data?** Only someone who signs in. For the demo, the data is fake and stays on this laptop. Event titles are sent to the AI provider (Groq).
- **Why free models?** The prototype must cost nothing. They are slower and less reliable, so paid models are the first upgrade.
