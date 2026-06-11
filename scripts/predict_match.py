from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.worldcup_model import format_pct, load_matches, predict_match


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", required=True)
    parser.add_argument("--away", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--host-country", required=True)
    parser.add_argument("--neutral", action="store_true")
    parser.add_argument("--home-adjust", type=float, default=0.0)
    parser.add_argument("--away-adjust", type=float, default=0.0)
    parser.add_argument("--market-home", type=float)
    parser.add_argument("--market-draw", type=float)
    parser.add_argument("--market-away", type=float)
    parser.add_argument("--market-weight", type=float, default=0.35)
    parser.add_argument("--out", default="outputs/latest_prediction.json")
    args = parser.parse_args()

    matches = load_matches()
    match_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    prediction = predict_match(
        matches=matches,
        home_team=args.home,
        away_team=args.away,
        match_date=match_date,
        host_country=args.host_country,
        neutral=args.neutral,
        manual_home_adjust=args.home_adjust,
        manual_away_adjust=args.away_adjust,
        market_home=args.market_home,
        market_draw=args.market_draw,
        market_away=args.market_away,
        market_weight=args.market_weight,
    )

    payload = {
        "match": f"{prediction.home_team} vs {prediction.away_team}",
        "match_date": args.date,
        "probabilities": {
            "home_win": prediction.home_win,
            "draw": prediction.draw,
            "away_win": prediction.away_win,
        },
        "expected_goals": {
            "home": prediction.expected_home_goals,
            "away": prediction.expected_away_goals,
        },
        "most_likely_scores": [
            {"score": score, "probability": probability}
            for score, probability in prediction.most_likely_scores
        ],
        "ratings": {
            "home_elo": prediction.home_elo,
            "away_elo": prediction.away_elo,
        },
        "form": {
            "home": prediction.home_form.__dict__,
            "away": prediction.away_form.__dict__,
        },
        "upset_score": prediction.upset_score,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"{prediction.home_team} vs {prediction.away_team}")
    print(f"Home win: {format_pct(prediction.home_win)}")
    print(f"Draw:     {format_pct(prediction.draw)}")
    print(f"Away win: {format_pct(prediction.away_win)}")
    print(f"xG:       {prediction.expected_home_goals:.2f} - {prediction.expected_away_goals:.2f}")
    print(f"Elo:      {prediction.home_elo:.0f} - {prediction.away_elo:.0f}")
    print(f"Upset:    {prediction.upset_score:.1f}/100")
    print("Scores:   " + ", ".join(f"{s} {format_pct(p)}" for s, p in prediction.most_likely_scores))


if __name__ == "__main__":
    main()
