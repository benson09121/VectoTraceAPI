# VectoTrace — Frontend

Next.js 16 (App Router) + Tailwind v4 + shadcn/ui.

## Running

The Django API must be up first (see the repo root). Then:

```bash
cp .env.example .env.local     # points at http://localhost:8000
npm install
npm run dev                    # http://localhost:3000
```

The API's `CORS_ALLOWED_ORIGINS` already includes `localhost:3000`.

## Routes

| Route | Rendering | Notes |
|---|---|---|
| `/login`, `/register` | client | JWT pair stored in localStorage |
| `/monitors` | client | live status via SSE |
| `/monitors/[id]` | client | uptime windows + check history |
| `/incidents`, `/incidents/[id]` | client | timeline, post update, resolve |
| `/status-pages` | client | create pages, attach/detach monitors |
| `/settings` | client | members, alert channels, API tokens |
| `/status/[slug]` | **server** | public page — no auth, no cache |

## Why `/status/[slug]` is server-rendered

It is the one page unauthenticated people load, usually while something is
broken. Rendering it on the server means:

- **Link unfurls work.** A status URL pasted into Slack shows
  "Acme Status — Major outage" instead of an empty card, because
  `generateMetadata` fills `<title>` and `og:description` from live data.
- **It is indexable**, so "is acme down" finds it.
- **It renders without JavaScript.** Verify with
  `curl -s localhost:3000/status/<slug> | grep operational`.

`export const dynamic = "force-dynamic"` — a cached status page during an
outage is worse than no status page.

## Architecture notes

**`src/lib/api.ts`** is the only place that talks to the backend. A 401
triggers one silent token refresh before the caller sees an error; if that
fails the user is bounced to `/login`. Refresh tokens rotate on use, so the new
one is stored on every refresh.

**`src/lib/useMonitorEvents.ts`** subscribes to `/orgs/{id}/events/` over
`EventSource`. Because `EventSource` cannot set an `Authorization` header, the
access token is passed as a query parameter — acceptable only because those
tokens live 15 minutes. The backend explicitly rejects refresh tokens on that
endpoint. The handler is held in a ref so re-renders don't drop the stream.

Live events patch rows in place rather than refetching. The incidents list is
the exception: an incident opening or resolving changes which rows belong in
the list at all, so it refetches.

**Write vs read types.** `MonitorWrite` / `StatusPageWrite` in `api.ts` exist
because the API accepts bare ids for nested collections (`monitors: [1, 2]`)
but returns expanded objects.

## Known gaps

- No test suite. The backend has 215 tests; this app has none.
- Monitors are create/archive only — no edit form for headers, body, timeout,
  or regions, though the API supports all of them.
- `/status/[slug]` does not live-update; it renders per request.
- `npm audit` reports advisories in `postcss` and `sharp`. Both are transitive
  dependencies of Next 16 itself and the suggested "fix" downgrades to Next 9,
  so they are left alone pending an upstream release.
