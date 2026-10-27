# Running the backend on the university PC

**Goal:** `https://ctscannr.com` (frontend, hosted on Vercel) sends its `/api/...` requests to the FastAPI backend running on the university PC, which has the good hardware.

**The problem:** the PC is only reachable from the university network or its VPN. Visitors' browsers (and Vercel) can't reach it, and we can't open firewall ports on the university network.

**The solution, in one line:** have the PC open an **outbound tunnel** to a public HTTPS address, then point the frontend at that address.

```
 visitor's browser
   │  loads the page               │  calls the API (fetch, <img>, EventSource)
   ▼                               ▼
 ctscannr.com (Vercel)        https://sybil-pc.<tailnet>.ts.net   ← public HTTPS URL
                                   │
                                   │  tunnel, opened outward by the PC
                                   │  (no inbound ports, no VPN, no IT firewall change)
                                   ▼
                     ┌───── university PC ─────┐
                     │ tailscaled (funnel)     │
                     │      │                  │
                     │      ▼                  │
                     │ uvicorn 127.0.0.1:8000  │
                     │ (backend/app/main.py)   │
                     └─────────────────────────┘
```

Because the PC opens the connection itself, it works behind the university NAT and firewall the same way a browser on that PC can load websites.

---

## Why this approach

| Option | Verdict |
|---|---|
| Open a port or get a public IP from university IT | Slow, needs approval, and is often refused. |
| Make visitors use the university VPN | Not possible for a public website. |
| **Tunnel (Tailscale Funnel or Cloudflare Tunnel)** | **Free, outbound only, HTTPS included, about 15 minutes to set up.** ✅ |

We use **Tailscale Funnel** because it's the easiest: it needs no DNS changes and gives us a stable HTTPS URL. If you'd rather have `api.ctscannr.com`, see [Alternative: Cloudflare Tunnel](#alternative-cloudflare-tunnel).

HTTPS matters here. `ctscannr.com` is served over HTTPS, and browsers block calls from an HTTPS page to a plain `http://` API (mixed content). Both tunnels give us HTTPS for free.

---

## Step 1: Run the backend on the PC

Set up the project on the PC the same way as on a dev machine (see [README.md](README.md)): `.\tasks.ps1 setup`, `weights`, `candidates` and `pool` on Windows, or the matching `make` targets on Linux.

Then run the API **without `--reload`**, bound to localhost only. The tunnel is the only thing that should be able to reach it.

```powershell
cd backend
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Check it: `curl http://127.0.0.1:8000/api/health`

### Keep it running

The PC has to serve requests when nobody is logged in, and after Windows Update reboots it.

- **Windows:** use Task Scheduler → *Create Task*
  - Trigger: *At startup*
  - Run whether the user is logged on or not
  - Action: `powershell.exe -NoProfile -Command "cd 'D:\path\to\SybilTest\backend'; uv run uvicorn app.main:app --host 127.0.0.1 --port 8000"`
  - Settings: *If the task fails, restart every 1 minute*

  [NSSM](https://nssm.cc/) also works if you prefer a real Windows service.
- **Linux:** use a systemd unit with `Restart=always` and `WantedBy=multi-user.target`.
- **Power settings:** turn sleep and hibernate off.

---

## Step 2: Expose the backend with Tailscale Funnel

1. Create a free Tailscale account at https://tailscale.com. Use a shared team account, not one person's.
2. Install Tailscale on the PC and log in. It runs as a system service and starts at boot.
3. Publish port 8000:
   ```powershell
   tailscale funnel --bg 8000
   ```
   The first time you run this, the CLI prints a link to turn on HTTPS and Funnel for your tailnet. Open it, approve, and run the command again.
   `--bg` makes the setting persist across reboots.
4. Find the public URL:
   ```powershell
   tailscale funnel status
   # https://sybil-pc.tail1234.ts.net (Funnel on)
   #  |-- / proxy http://127.0.0.1:8000
   ```
5. Test it from a phone on mobile data, off the university network:
   `https://sybil-pc.tail1234.ts.net/api/health`

**Bonus:** install Tailscale on your laptops too. You can then RDP or SSH into the PC from anywhere without the university VPN.

---

## Step 3: Point the frontend at the PC

Right now every API URL in the frontend is relative (`/api/...`). That works locally because Vite proxies `/api` to port 8000 ([vite.config.ts](frontend/vite.config.ts)). On Vercel, the same relative URL hits Vercel itself, which has no backend.

### 3a. Add an API base URL (about 10 lines of code)

In [frontend/src/lib/api.ts](frontend/src/lib/api.ts):

```ts
/** Empty in local dev (the Vite proxy handles /api); the tunnel URL in production. */
export const API_BASE = import.meta.env.VITE_API_BASE ?? ''
const url = (path: string) => `${API_BASE}${path}`

async function get<T>(path: string): Promise<T> {
  return parse<T>(await fetch(url(path)))
}
// post(): fetch(url(path), { ... })
// exportUrl, sliceUrl, overlayUrl, coronalUrl: wrap their returned strings in url(...)
```

In [frontend/src/hooks/useJobEvents.ts](frontend/src/hooks/useJobEvents.ts):

```ts
import { API_BASE } from '@/lib/api'
const source = new EventSource(`${API_BASE}/api/jobs/${jobId}/events`)
```

Leave `VITE_API_BASE` unset locally, and `pnpm dev` works exactly as before.

### 3b. Set the variable on Vercel

Vercel → Project → Settings → Environment Variables:

```
VITE_API_BASE = https://sybil-pc.tail1234.ts.net
```

Don't add a trailing slash. Then **redeploy**. Vite bakes `VITE_*` variables in at build time, so changing the variable does nothing until the next build.

### 3c. Allow the website in CORS

Our site and the API are now on different domains, so the backend must allow it. In [backend/app/main.py](backend/app/main.py), read the allowed origins from the environment:

```python
allow_origins=os.environ.get(
    "ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
).split(","),
```

On the PC, set:

```
ALLOWED_ORIGINS=https://ctscannr.com,https://www.ctscannr.com,http://localhost:5173
```

Add the Vercel preview domain too if you want preview deployments to work.

---

## Step 4: Check it end to end

1. Open `https://ctscannr.com` from a network outside the university.
2. DevTools → Network: requests should go to `https://sybil-pc...ts.net/api/...` and return 200.
3. Run a person end to end. The progress stepper should advance live, which confirms SSE (server-sent events) works through the tunnel, and the slice and heat-map images should load.
4. Stop the backend and see how the site behaves. The frontend polls `/api/health` every 20 seconds, but it doesn't yet show an explicit "offline" message (see below).

---

## Things to know

- **Ask IT first.** Exposing a service from a university machine may need approval under the acceptable-use policy. It's an outbound HTTPS connection, which IT usually accepts, but get a written "OK" so the PC isn't quarantined mid-demo.
- **The API is public.** Anyone who finds the URL can call it, and CORS doesn't stop `curl`. The damage is limited: there's one inference worker and jobs queue up, and the data is de-identified public NLST data. If abuse shows up, add a simple rate limit (for example `slowapi`) on the two `POST .../run(s)` endpoints.
- **If the PC is off, the analysis is off.** The rest of the site still loads from Vercel. It's worth adding a friendly "analysis server is offline" banner when `health.isError` is true in `App.tsx` and `StoryView.tsx`. The health query already exists; nothing displays its failure yet.
- **The backend also serves the frontend** at `/` if `frontend/dist` exists on the PC. That's harmless, but the real site is the Vercel one.

---

## Alternative: Cloudflare Tunnel

Use this if you want `https://api.ctscannr.com` instead of a `ts.net` address.

1. Move the DNS for `ctscannr.com` to Cloudflare (free plan). Recreate the Vercel records there, with the A/CNAME records set to *DNS only* (grey cloud).
2. On the PC:
   ```
   cloudflared tunnel login
   cloudflared tunnel create sybil
   cloudflared tunnel route dns sybil api.ctscannr.com
   cloudflared service install   # runs at boot
   ```
   Point the tunnel config at `http://127.0.0.1:8000`.
3. Set `VITE_API_BASE=https://api.ctscannr.com`. Everything else is identical.

This takes a little more setup, but gives a nicer URL and lets you add Cloudflare Access or rate limiting later without touching the code.
