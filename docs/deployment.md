# Deployment and operations

## Render and Netlify

The blueprint defines a Render API and persistent worker sharing the same Neon database and secrets. The API release command runs migrations. Deploy the API/migration step before starting a worker for a new schema.

Configure these secrets/settings:

- Neon pooled `DATABASE_URL` and direct `DATABASE_DIRECT_URL`
- Stable private `JWT_SECRET_KEY`
- `OPENROUTER_API_KEY` and free worker/evaluator/fallback model IDs
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and a Fernet `GOOGLE_TOKEN_ENCRYPTION_KEY`
- Public Netlify `APP_BASE_URL` and exact `CORS_ORIGINS`
- Google callback: `https://YOUR-NETLIFY-SITE/api/google/oauth/callback`

Generate an encryption key with:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Keep this key stable; changing it without re-encrypting stored credentials requires users to reconnect Google.

Netlify serves `frontend/` and proxies `/api/*` to Render before the SPA fallback. Update the proxy target if the Render service URL changes. The browser uses relative API paths, so cookies and polling share the frontend origin. `/home` serves the welcome page.

## Release verification

1. Apply migrations to staging and run `alembic check`.
2. Run the PostgreSQL, graph recovery, provider-boundary, and frontend suites.
3. Run offline evaluations.
4. With configured keys, run labeled live evaluation and Google OAuth/import/export smoke tests.
5. Verify login, month/week/day views, themes, panels, manual entry, assistant questions, approval, cancellation, and reload recovery.
6. Deploy matching frontend/API/worker versions, then verify production.

Local automated tests mock OpenRouter and Google network calls. They do not establish live free-model availability or validate a production OAuth configuration.

## Monitoring and recovery

Inspect run statuses and progress events, model attempt counts, active execution time, evaluation reports, and synchronization failures. Provider secrets and raw provider exceptions are not returned to browsers.

Workers renew leases and reclaim expired runs. Checkpoint and domain writes verify lease ownership. A completed domain operation has a durable outcome and can be replayed after a checkpoint failure.

Google jobs use stable remote event IDs, bounded retries, and persisted mappings. Failed jobs remain available for retry; reconnect Google when authorization expires.

Checkpoint threads record a graph version. Incompatible saved runs are terminated with an explanation rather than resumed through incompatible code.

Keep the previous release available during staging. Once PostgreSQL has new user records, rollback must preserve that database. Do not switch users back to SQLite.

## Browser verification

Run an isolated development API, then execute `python tests/browser_smoke.py --base-url http://127.0.0.1:8000`.
The script uses installed Edge by default. On Linux, run `python -m playwright install --with-deps chromium` and set `BROWSER_CHANNEL=chromium`.
It verifies real signup/manual-calendar behavior and a mocked asynchronous approval protocol, including page-reload recovery.
The graph's real PostgreSQL checkpoint and commit recovery are verified separately by the integration suite.
