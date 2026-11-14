# Free deployment: Render (one web service) + Neon (PostgreSQL) + Groq

This runs the whole app, including the AI worker, as **one free Render web service**. Use it for demos. For real
users use `render.yaml` (a separate worker on a paid plan).

**Free-plan trade-offs**
- The service sleeps after 15 minutes without traffic. The first visit afterwards takes about a minute.
- 512 MB of memory. If the service restarts during an AI request, the request resumes automatically afterwards.
- Never paste keys or database addresses into chat or commit them. They go only into Render's environment settings.

## 1. Neon (database), about 3 minutes

1. Create a project at https://console.neon.tech. Pick a region near your users (Singapore for India).
2. Open **Connect**. You need **two** connection strings for the same database:
   - **Pooled** (the host contains `-pooler`): this becomes `DATABASE_URL`.
   - **Direct** (turn the Connection pooling toggle off): this becomes `DATABASE_DIRECT_URL`.
3. Keep `sslmode=require` at the end of both.

## 2. Groq key

Create a free key at https://console.groq.com/keys. It becomes `GROQ_API_KEY`.

## 3. Render, new service (recommended)

1. Push the branch (already done): `demo-prototype`.
2. Render dashboard, **New**, **Blueprint**, choose the GitHub repository, branch `demo-prototype`, and set the
   **Blueprint file path** to `render.free.yaml`.
3. When asked for secret values, paste `DATABASE_URL` (pooled), `DATABASE_DIRECT_URL` (direct) and `GROQ_API_KEY`.
4. Apply. The first build takes a few minutes. The start command creates the database tables, then starts the app.
5. Open the service URL, add `/home`, for example `https://predestination-demo.onrender.com/home`.

The app picks up its own public address from Render (`RENDER_EXTERNAL_URL`), so no URL settings are needed.

## 3b. Render, existing service instead

In the existing service's **Settings** and **Environment**:
- Branch: `demo-prototype`.
- Start command: `python -m app.db.migrate && uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
- Add: `RUN_WORKER_IN_PROCESS=true`, `LLM_PROVIDER=groq`, `GROQ_API_KEY`, `GROQ_WORKER_MODEL=openai/gpt-oss-120b`,
  `GROQ_EVALUATOR_MODEL=openai/gpt-oss-20b`, `COOKIE_SECURE=true`.
- If you removed Netlify, delete `APP_BASE_URL` and `CORS_ORIGINS` (or set both to the Render URL).
- If you have a separate worker service, suspend it: two workers would both run requests.

## 4. Check it works

1. `https://<your-service>.onrender.com/health` should show `{"status":"ok"}` (the first call may take a minute).
2. Open `/home`, sign up, confirm the timezone, add an event.
3. In AI Planner, ask: "schedule 9 am review of project". A draft should appear within about 10 seconds.
4. Optional demo data: from your computer, run the seed against Neon with the direct string set only in that
   terminal session (`$env:DATABASE_URL = "<direct string>"`, then `python -m app.demo_seed`).

## If something fails

| Symptom | Likely cause |
|---|---|
| Build fails | Check the build log; the Python version is pinned by `PYTHON_VERSION` |
| Service starts then exits | `DATABASE_URL` or `DATABASE_DIRECT_URL` wrong, or missing `sslmode=require` |
| Sign-up works but saving gives 403 | `APP_BASE_URL` or `CORS_ORIGINS` set to the wrong address; delete them |
| AI says "not connected yet" | `GROQ_API_KEY` missing |
| AI request stays "Queued" | The in-process worker is off: set `RUN_WORKER_IN_PROCESS=true` |
| Out of memory restarts | Free plan limit; use the paid blueprint |

The voice assistant works in Chrome or Edge. The MCP server is local only and is not part of this deployment.
