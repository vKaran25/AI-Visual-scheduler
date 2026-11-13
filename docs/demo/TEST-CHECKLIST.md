# Demo test suite

Two parts: a **one-command check** that proves the backend works, and a **manual checklist** for the things only a
person can judge (microphone, voice, how the screen looks). Do both before the demo.

## Part 1: one command

Terminal 1 (leave running):

```powershell
.\.venv\Scripts\python.exe scripts\dev.py seed   # reset the demo week
.\.venv\Scripts\python.exe scripts\dev.py up
```

Terminal 2:

```powershell
.\.venv\Scripts\python.exe scripts\dev.py check          # about 30 seconds, no AI
.\.venv\Scripts\python.exe scripts\dev.py check --ai     # about 4 minutes, uses about 15 AI requests
```

| Check | Proves |
|---|---|
| App healthy, pages load, sign-in | The server and demo account work |
| Demo week is on the calendar | Seeding worked |
| Add by hand, overlap refused, delete | Manual calendar and conflict rules |
| Unsafe colour rejected | Input validation |
| Find free time | Availability search |
| Voice endpoint rejects empty speech | Voice API validation |
| MCP server lists tools and proposes | The MCP integration answers over the real protocol |
| AI: "schedule 9 am review of project" | Goes straight to a 9 to 10 AM draft with the assumption shown |
| AI: approve saves, reject saves nothing | The approval safety rule |
| AI: "schedule gym at 7" | Asks only for AM or PM |
| Voice agent | Reads the schedule, adds an event, saves it on "yes" |

Everything it creates is removed afterwards. The deeper automated suite is `scripts\dev.py test` (110 tests, about
10 minutes) and the browser run is `python tests\browser_smoke.py --base-url http://127.0.0.1:8000`.

## Part 2: manual checklist (Chrome or Edge, http://127.0.0.1:8000/home)

Tick each box. Notes in *italics* are what you should see.

### Sign-in and first look
- [ ] Sign in as `student@example.com`. *The month view shows classes, lunch, gym, a part-time job.*
- [ ] Press **Month / Week / Day**. *Each view shows the same events; week view has a red "now" line.*
- [ ] Click **+N more** in a busy day. *Opens that day with every event.*
- [ ] Toggle the sun icon. *Light and dark themes both readable.*
- [ ] Resize the window narrow. *No sideways scrolling; the Tools panel becomes a slide-over.*

### Adding events by hand
- [ ] Type `Study group tomorrow at 6pm for 1 hour` and click **Fill details**. *Dialog opens filled in.*
- [ ] Click **Add to calendar**. *Toast says added; event appears tomorrow at 6 PM.*
- [ ] Add another event overlapping it. *Refused with a message naming the clash.*
- [ ] Click an event, change the time, **Save**; then delete it. *Updates and disappears.*
- [ ] Press Tab through the page. *A visible focus ring appears on every control.*

### Talking assistant (needs microphone and sound)
- [ ] Open **AI Planner**, press **Talk**, allow the microphone. *Button turns red "Stop".*
- [ ] Say "What's on my calendar tomorrow?" *You hear the answer; the same words appear in the chat.*
- [ ] Say "Add a review of my project tomorrow at 9 AM". *"On it", then it reads the draft, including "length assumed", and asks to save.*
- [ ] Say "Yes, save it". *"Done. It's on your calendar." The event appears on the calendar.*
- [ ] Say "Add gym at 7". *It asks about AM or PM. Answer "7 PM". A draft follows.*
- [ ] Say "No" to a draft. *"Okay, nothing was changed." Calendar unchanged.*
- [ ] While it is talking, press **Stop talking**. *It stops at once.*
- [ ] Tick **Hands-free** (use headphones). *It listens again after each reply.*
- [ ] Type a request instead of speaking. *Works the same way.*

### Approval safety (the point of the product)
- [ ] Type `schedule 9 am review of project` and press **Ask assistant**. *Draft card, not an event yet; note says "Length assumed: 1h".*
- [ ] Press **Reject**. *Nothing is added.*
- [ ] Type `Plan 4 hours of calculus revision this week`. *Draft with four sessions on separate days.*
- [ ] Press **Approve**, then **View saved event**. *Events appear; jumps to the day.*

### Claude and the MCP server
- [ ] Register it (commands are in `docs/demo/DEMO-SCRIPT.md`) and restart Claude.
- [ ] Ask "Using Predestination, what is free on Tuesday evening?" *It answers from the real calendar.*
- [ ] Ask it to propose, then create, a 2 hour revision block. *Refresh the web app: the event is there.*

### Failure drills (do these once so nothing surprises you)
- [ ] Stop the app, reload the page. *Page shows an error, not a blank screen.* Restart with `scripts\dev.py up`.
- [ ] Open the app in Firefox or Safari. *Talk is disabled with a note; typing works.*
- [ ] Deny the microphone. *A clear message; typing works.*

### Right before the demo
- [ ] `scripts\dev.py seed`, then `scripts\dev.py check` all green.
- [ ] Wait at least 30 to 60 seconds between AI requests (Groq's free limit).
- [ ] Sound on, microphone allowed, notifications off, page zoom 110%.
