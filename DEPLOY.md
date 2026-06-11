# Deploy

This MVP runs as a single Python web service.

## Render

1. Push this project to a GitHub repository.
2. Create a Render Web Service from that repository.
3. Use:
   - Build command: `pip install -r requirements.txt`
   - Start command: `PYTHONDONTWRITEBYTECODE=1 python3 backend_server.py`
4. Render will provide the public URL.

The server reads `PORT` from the environment, so it works on Render/Railway-style hosts.

## Runtime behavior

- `GET /web/index.html`: dashboard
- `GET /api/tournament`: latest model output
- `GET /api/live`: live match scores/status from the configured provider
- `GET /api/leaderboard`: user leaderboard
- `GET /api/update-status`: updater status plus live-data connection status
- `POST /api/users`: create or reuse nickname
- `POST /api/picks`: save user pick
- `POST /api/live`: admin-only manual live score/status override
- `POST /api/results`: admin-only result finalization

## Update cadence

The MVP scheduler is built in:

- Normal pre-match: every 3 hours
- Within 24 hours of a fixture: every 1 hour
- Matchday/full model update: every 5 minutes

The model adapter reruns the local model and updates JSON files. Live scores are read through `/api/live` and cached server-side.

## Required production settings

Set these environment variables in Render/Railway:

- `ADMIN_TOKEN`: long random secret used to finalize match results.
- `ALLOWED_ORIGIN`: your public site URL, for example `https://your-app.onrender.com`.
- `DB_PATH`: SQLite path. Free Render deployment can use `data/worldcup.db`; this is not guaranteed to survive restarts.
- `LIVE_DATA_PROVIDER`: currently `football-data`.
- `FOOTBALL_DATA_TOKEN`: football-data.org API token. Keep this secret in Render; do not commit it.
- `FOOTBALL_DATA_COMPETITION`: defaults to `WC` for FIFA World Cup.
- `LIVE_CACHE_SECONDS`: live API cache window, defaults to `60`.

If no persistent disk is attached, users, picks, and results can be lost after redeploys or instance restarts. This is fine for a free preview; use Render Persistent Disk or Postgres/Supabase for a serious leaderboard.

## Security behavior

- Nicknames remain customizable, but are limited to 20 characters and restricted to Chinese characters, letters, numbers, spaces, underscores, and hyphens.
- User picks require `user_id + token`, so a user cannot edit another user's picks just by guessing an id.
- Picks are locked at each match's `lock_at`. Current fixture data only has dates, so the MVP locks at `YYYY-MM-DDT00:00:00Z`; replace this with official kickoff timestamps when connected.
- Basic in-memory rate limits protect nickname creation, picks, results, and general GET traffic.

## Live match data

The live-score adapter currently supports football-data.org v4. It calls `/v4/matches` with the `WC` competition code, today's date range, and the `X-Auth-Token` header. It also requests unfolded goals and bookings when the provider plan allows them.

Without `FOOTBALL_DATA_TOKEN`, the site still runs and shows model updates, but the live-match panel will clearly say that live scores are not connected.

You can also push manual live updates with the admin token. Manual entries override provider data for the same match and are useful if the provider key is not ready or a feed is delayed:

```bash
curl -X POST "https://your-app.onrender.com/api/live" \
  -H "Content-Type: application/json" \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -d '{
    "match_id": "2026-06-11-mexico-south-africa",
    "status": "IN_PLAY",
    "minute": 63,
    "home_score": 1,
    "away_score": 0,
    "note": "Second half"
  }'
```

Use `status: "FINISHED"` and the final score when the match ends. Use `POST /api/results` as well if you want the leaderboard to score user picks.
