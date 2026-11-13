# 0001: Talking voice agent in front of the planner

- **Status:** accepted (2026-11-14)
- **Context:** students wanted to talk to the assistant the way they talk to ChatGPT or Claude voice mode, not just
  dictate text. Constraints: free services only, Chrome/Edge acceptable, English first, demo-ready quickly.

## Decision

A small **voice agent** handles each spoken turn and hands real calendar work to the existing **planner workflow**.

- The browser does speech-to-text (Web Speech recognition) and text-to-speech (`speechSynthesis`). Free, no audio
  leaves for our server.
- `POST /api/voice/turn` sends the transcript to a fast model (`gpt-oss-20b` on Groq) that returns one structured
  choice: `none`, `read_schedule`, `find_free_time`, `delegate`, `approve`, `reject` or `cancel`, plus a short sentence.
- **Code, not the model, performs the action.** Schedule and free-time answers are built from database data. Planner
  requests go through `run_service.enqueue`/`resume`, so all existing validation and approval rules apply.
- **Spoken approval** is allowed only when exactly one draft is waiting, the words are a clear "yes" without a "no",
  and the draft only adds events. Drafts that change or remove events need a tap on Approve.
- Tap-to-talk by default; optional hands-free mode listens again after each reply (headphones recommended).
- Planner progress is narrated from fixed templates (no extra model calls), to stay inside Groq's free token limit.

## Options considered

| Option | Why not chosen now |
|---|---|
| Server-side speech-to-text (Groq Whisper) | Works in every browser but sends audio out and costs quota; planned as a later upgrade |
| Realtime speech-to-speech APIs (OpenAI Realtime, Gemini Live) | Most natural, but paid and needs a streaming server |
| Let the model call calendar tools directly | Faster to write, but the model could then write or misstate calendar data |

## Consequences

- Works in Chrome and Edge only; other browsers keep typing.
- Two layers (voice agent, planner) means two prompts to maintain, but safety rules stay in one place.
- Voice turns are stored as normal messages in the same conversation, so history shows them.
