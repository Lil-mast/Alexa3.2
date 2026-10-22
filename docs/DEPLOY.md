# Deploying Alexa

The frontend is a static build on Vercel. The API, the MCP endpoint, and Google
sign-in run as one Docker service on Render, with Postgres for accounts. The house
state, the trace, and the audit chain stay in memory, so a redeploy resets the house
and keeps every account.

```
browser ──► Vercel (static React app, dist/)
              │  fetch with Authorization: Bearer, CORS
              ▼
           Render web service (FastAPI: /api, /health, /mcp, OAuth callback)
              │  DATABASE_URL
              ▼
           Render Postgres (users, sessions, OAuth state, exchange codes)
```

The files that make this work:

| File | Purpose |
|---|---|
| `render.yaml` | Render blueprint: the Postgres database and the Docker web service |
| `backend/Dockerfile` | The API image. Render builds it from `backend/` |
| `vercel.json` | Vercel build settings and security headers for the static app |

Nothing in those files is a secret or a real hostname. Every real value is entered
in the Render or Vercel dashboard.

## 0. Before you start

1. Push the repository to GitHub. `backend/.env` is ignored and must stay that way.
2. Scan what you are about to push:

   ```bash
   python3 scripts/check_leaks.py --all
   ```

3. Create a private token for MCP clients and the browser's API calls. Keep the
   output. You will paste it into Render as `ALEXA_TOKENS_JSON`.

   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

   The variable is a JSON object keyed by that token. Use this shape, with your
   token in place of the placeholder and your own subject name:

   ```json
   {"<your-token>": {"subject": "household-1", "client_id": "alexa-mcp", "scopes": ["home:timers:write", "home:lights:write", "home:climate:write", "booking:rooms:write", "privacy:settings:write"]}}
   ```

   The API refuses to start on a public address while the shipped development
   token is still in place, so this step cannot be skipped.

## 1. Render: the API and the database

1. In Render choose **New > Blueprint** and select this repository.
2. Render shows the two resources from `render.yaml`: `alexa-db` and `alexa-api`.
   Enter the values it asks for:
   - `ALEXA_TOKENS_JSON`: the JSON from step 0.
   - `ALEXA_PUBLIC_URL`: `https://<api-name>.onrender.com`, using the name Render
     gives the service. Check the exact URL on the service page.
   - `ALEXA_ALLOWED_HOSTS`: the same host without `https://`, for example
     `<api-name>.onrender.com`. This re-enables the DNS-rebinding guard on `/mcp`.
   - `ALEXA_FRONTEND_URL`, `ALEXA_CORS_ORIGINS`, and `ALEXA_OAUTH_REDIRECT_URI`: you
     can leave these blank for now. Section 3 fills them in.
   - `ALEXA_GOOGLE_CLIENT_ID` and `ALEXA_GOOGLE_CLIENT_SECRET`: optional at this
     stage. Without them the sign-in button stays disabled.
   - `ALEXA_ELEVENLABS_API_KEY`: optional. Without it the house uses the browser's
     own voice.
3. Apply. The first build takes a few minutes.
4. Check the health endpoint. It must answer with `"status":"ok"`:

   ```bash
   curl https://<api-host>/health
   ```

## 2. Vercel: the frontend

1. In Vercel choose **Add New > Project** and import the same repository.
2. Leave the root directory as the repository root. `vercel.json` sets the install
   command (`pnpm install --frozen-lockfile`), the build command (`pnpm build`), and
   the output directory (`dist`).
3. Under **Environment Variables**, add for Production:

   ```
   VITE_API_BASE = https://<api-host>
   ```

   This value is compiled into the bundle at build time. If you change it, redeploy.
   It must not include a trailing slash.
4. Deploy. Note the Vercel domain it gives you, for example `https://<project>.vercel.app`.

The app uses hash routing, so Vercel needs no rewrite rules.

## 3. Connect the two

Back in Render, on the `alexa-api` service, set:

| Variable | Value |
|---|---|
| `ALEXA_FRONTEND_URL` | `https://<your-vercel-domain>` |
| `ALEXA_CORS_ORIGINS` | `https://<your-vercel-domain>` |
| `ALEXA_OAUTH_REDIRECT_URI` | `https://<api-host>/api/auth/callback/google` |

Save, and let Render redeploy. Several origins can be listed in
`ALEXA_CORS_ORIGINS`, separated by commas. Keep `http://localhost:5173` out of the
production value unless you want local development to reach production.

## 4. Google sign-in (needed for public accounts)

1. In Google Cloud Console, create an OAuth client of type **Web application**.
2. Add the authorized redirect URI: `https://<api-host>/api/auth/callback/google`.
3. Copy the client ID and secret into Render as `ALEXA_GOOGLE_CLIENT_ID` and
   `ALEXA_GOOGLE_CLIENT_SECRET`, then redeploy.
4. Until the consent screen is published, only the test users you add can sign in.

## 5. Checks after deployment

Run these against the production hosts. Each line should match the result shown.

```bash
curl -s https://<api-host>/health                     # status "ok"
curl -s https://<api-host>/api/auth/config            # enabled true once Google is set, dev_login false
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://<api-host>/api/auth/dev-login   # 404
curl -s -o /dev/null -w "%{http_code}\n" https://<api-host>/api/state                   # 401 without a token
```

Then in a browser:

1. Open `https://<your-vercel-domain>/`. The landing page loads and the header says
   "Try the house".
2. Sign in with Google. You should land on `#/house` with the four rooms.
3. Say or type "set a ten minute timer". The timer appears.

For MCP clients, connect to `https://<api-host>/mcp` with
`Authorization: Bearer <your-token>`. The Host header must be the Render host, so do
not connect from a different hostname.

## 6. Limits to know before you share the link

- **Spin-down.** Render's free web service sleeps after a period without traffic.
  The first request after that is slow, and the house resets. Accounts survive
  because they are in Postgres. A paid instance avoids both.
- **Database expiry.** Render's free Postgres has an expiry date set by the plan.
  Check the database page before you rely on it, and export or upgrade before then.
- **No Alexa+ connection yet.** The MCP endpoint works for MCP clients, but Alexa+
  registration is separate work.
- **Voice cost.** Every spoken reply is billed once an ElevenLabs key is set.
  Set a spending limit first. See the earlier note on limits.
- **Simulated devices.** Lights, timers, thermostat, and bookings are simulated. Say
  so to anyone who uses the house.

## 7. Rollback

- Render: open the service, go to **Deploys**, and choose **Rollback** on the last
  good deploy.
- Vercel: open **Deployments**, find the last good one, and choose **Promote to
  Production**.

## 8. What was checked locally

These checks ran against the production configuration on a local machine, with
placeholder hostnames and a generated token. They use the same uvicorn flags as the
Dockerfile:

- the API refuses to start with the shipped development token on a public address;
- health, auth config, and the house state respond as described in section 5;
- dev login returns 404 outside a local address;
- a browser origin that is not listed gets no CORS header, and the listed origin
  does;
- `/mcp` rejects an unknown Host header with 421;
- `/mcp` accepts an `initialize` request with the token and the right Host;
- the frontend installs from the frozen lockfile and builds with `VITE_API_BASE`.

Docker, the Render service, and the Vercel project were not run from the development
machine. Run section 5 after your first deploy.
