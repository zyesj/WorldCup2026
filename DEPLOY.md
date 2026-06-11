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
- `GET /api/leaderboard`: user leaderboard
- `GET /api/update-status`: updater status
- `POST /api/users`: create or reuse nickname
- `POST /api/picks`: save user pick
- `POST /api/results`: admin-only result finalization

## Update cadence

The MVP scheduler is built in:

- Normal pre-match: every 3 hours
- Within 24 hours of a fixture: every 1 hour
- Matchday/full model update: every 5 minutes

The current data adapter reruns the local model and updates JSON files. A paid live-score/news/odds API can be connected later without changing the frontend contract.

## Required production settings

Set these environment variables in Render/Railway:

- `ADMIN_TOKEN`: long random secret used to finalize match results.
- `ALLOWED_ORIGIN`: your public site URL, for example `https://your-app.onrender.com`.
- `DB_PATH`: persistent SQLite path. On Render, attach a Persistent Disk and use a path on that disk, for example `/var/data/worldcup.db`.

If no persistent disk is attached, users, picks, and results can be lost after redeploys or instance restarts.

## Security behavior

- Nicknames remain customizable, but are limited to 20 characters and restricted to Chinese characters, letters, numbers, spaces, underscores, and hyphens.
- User picks require `user_id + token`, so a user cannot edit another user's picks just by guessing an id.
- Picks are locked at each match's `lock_at`. Current fixture data only has dates, so the MVP locks at `YYYY-MM-DDT00:00:00Z`; replace this with official kickoff timestamps when connected.
- Basic in-memory rate limits protect nickname creation, picks, results, and general GET traffic.
