# World Cup 2026 Predictor

Lightweight, explainable prediction pipeline for the 2026 FIFA World Cup.

## Current model

- Historical results: `martj42/international_results`
- Strength layer: Elo replay with match-importance and goal-difference adjustment
- Score layer: calibrated Poisson score distribution
- Calibration layer: optional market/agency probability blend
- Live adjustment layer: manual rating adjustments for news, injuries, lineup and weather until automated feeds are connected

## First prediction

Run:

```bash
python3 scripts/predict_match.py --home Mexico --away 'South Africa' --date 2026-06-11 --host-country Mexico --home-adjust -35 --away-adjust 25 --market-home 0.722 --market-draw 0.213 --market-away 0.111 --market-weight 0.45 --out outputs/mexico_south_africa_news_adjusted.json
```

The output JSON is ready for the future dashboard.

## Notes

This is v0.1. It is intentionally conservative and explainable. The next steps are automated fixtures, group simulation, live news ingestion, and a dashboard API.
