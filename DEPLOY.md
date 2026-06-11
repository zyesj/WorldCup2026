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

## Update cadence

The MVP scheduler is built in:

- Normal pre-match: every 3 hours
- Within 24 hours of a fixture: every 1 hour
- Matchday/full model update: every 5 minutes

The current data adapter reruns the local model and updates JSON files. A paid live-score/news/odds API can be connected later without changing the frontend contract.
