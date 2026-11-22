# API contracts

All API records are scoped to the authenticated cookie user. Authenticated responses use `Cache-Control: no-store`. Mutating browser requests are restricted to configured origins.

## Durable assistant

- `POST /api/agent/chat`: prompt, optional session_id/start_after/slack/request_id; returns HTTP 202.
- `GET /api/agent/runs/{id}?cursor=N`: status, stage, progress events, pending interrupt, draft, final result or error.
- `POST /api/agent/runs/{id}/resume`: interrupt_id, response, request_id; returns 202.
- `POST /api/agent/runs/{id}/cancel`: prevents future work without reversing committed outcomes.
- `POST /api/agent/runs/{id}/retry`: retries a failed saved run without resetting its model budget.
- `POST /api/agent/confirm` or `reject`: session_id, draft_id, revision; returns 202.
- `GET /api/agent/drafts`: owned pending draft previews.
- Session list, messages, and runs are available under `/api/agent/sessions`.

Statuses: queued, running, awaiting_input, awaiting_approval, completed, failed, cancelled.

The frontend polls only active work. Clarification and approval wait for the user. A duplicate request_id returns the existing run; stale decisions return 409. Legacy `/api/chat`, `/api/chat/accept`, and `/api/chat/reject` are aliases to the asynchronous contract.

Draft calendar overlays have negative display IDs and include run/draft revisions. They are read-only previews and are excluded from coded availability and conflict calculations.

## Calendar

Existing `/api/slots`, `/api/slots/range`, `/api/free`, preset, and custom-preset routes retain their calendar-facing shape. Fixed-event responses include revision and timezone. Google imports are read-only.

`PUT /api/me/timezone` confirms an IANA timezone. Changing timezone after events exist requires a separate conversion; it is rejected rather than silently shifting recorded times.

## Memory and synchronization

- `GET /api/memory-proposals`: pending suggestions.
- `POST /api/memory-proposals/{id}/decision`: `{"accept":true}` or false.
- Existing memory routes support explicit preference management.
- Google OAuth routes use the configured redirect URI (`GOOGLE_OAUTH_REDIRECT_URI`).

Google writes are asynchronous. Failed outbox jobs can be inspected and retried through the synchronization endpoints. Local success and remote synchronization are separate statuses.

`GET /api/evals/metrics` returns tenant-scoped run counts, model attempts, validation outcomes, repair results, recovered operations, and Google job statuses.
