# Deploy the demo on Render and Neon

The Blueprint creates one **Free** Render web service. FastAPI serves the planner and API from the same HTTPS URL. The startup script migrates Neon, then starts the API and the assistant worker. The MCP server runs separately on your computer.

## 1. Prepare Neon

1. Open the [Neon Console](https://console.neon.tech/) and create a Free project for the demo, or use a dedicated demo branch in an existing Free project.
2. Open **Connect** and select that branch, database, and role. The role must be able to create tables and run migrations.
3. Copy the connection string with **Connection pooling** enabled for `DATABASE_URL`. Toggle pooling off and copy the direct string for `DATABASE_DIRECT_URL`. Use the same branch, database, and role for both. Keep the TLS options Neon supplies.
4. Keep both URLs private and enter them only in Render. The app creates its schema during startup.

## 2. Deploy on Render

1. From the repository root, commit and push the deployment files to GitHub on `demo-prototype`:

   ```powershell
   git branch --show-current
   git add -- .gitignore README.md render.yaml scripts/start_render.py docs/deployment.md docs/demo-architecture.md
   git diff --cached --stat
   git commit -m "Prepare Predestination demo for Render"
   git push origin demo-prototype
   ```

2. In the [Render Dashboard](https://dashboard.render.com/), select **New → Blueprint** and connect the scheduler repository through GitHub.
3. Select **demo-prototype** as the Blueprint branch and use the root `render.yaml`. Confirm the preview shows one **Free** web service named `predestination-demo`.
4. Enter the two Neon connection strings when prompted, then deploy. If Render does not prompt for a value, add it under the service's **Environment** page before redeploying.
5. For AI features, enter your `GROQ_API_KEY` when the Blueprint prompts for it. On an existing service, add it under **Environment**. The Blueprint selects Groq and uses `openai/gpt-oss-120b` for the worker, evaluator, and fallback.

   Save and deploy. The first deploy can run manual scheduling while you finish configuring the AI key. The Blueprint generates `JWT_SECRET_KEY` and enables secure cookies. The app uses Render's public HTTPS URL for its allowed browser origin. If you add a custom domain later, set `APP_BASE_URL` to that HTTPS origin and include it in `CORS_ORIGINS` if you override that setting.

## 3. Verify the hosted demo

1. Wait for the service to show **Live**. Open its public URL followed by `/health` and check that it returns `{"status":"ok"}`.
2. Open `/home` on that same URL. Create a fresh demo account and confirm the calendar timezone.
3. Add a manual event, refresh the page, and verify it stayed on the calendar.
4. Submit a typed assistant request. Review the proposed event, approve it, and refresh to confirm it was saved once. Repeat the flow with microphone permission enabled in desktop Chrome.
5. If the app fails to start, check **Logs** for a migration failure or a worker exit. If a request stays queued, check that the worker is running. If it fails during planning, check the provider key and model availability.

## Redeploy or pause

Push new commits to `demo-prototype`, then use **Manual Deploy → Deploy latest commit**. The Blueprint disables deploys on every push. Render Free services spin down after idle time, so open the URL before the demo. You can suspend the web service from its Settings page and resume it when needed. The calendar stays in Neon.

See [Render's Free plan limits](https://render.com/docs/free) and [Neon's Free plan](https://neon.com/pricing) for usage and billing details.
