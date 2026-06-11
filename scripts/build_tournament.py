from __future__ import annotations

import csv
import json
import math
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.worldcup_model import load_matches, predict_match


GROUPS = {
    "A": ["Mexico", "South Africa", "South Korea", "Czech Republic"],
    "B": ["Canada", "Bosnia and Herzegovina", "Qatar", "Switzerland"],
    "C": ["Brazil", "Morocco", "Haiti", "Scotland"],
    "D": ["United States", "Paraguay", "Australia", "Turkey"],
    "E": ["Germany", "Curaçao", "Ivory Coast", "Ecuador"],
    "F": ["Netherlands", "Japan", "Sweden", "Tunisia"],
    "G": ["Belgium", "Egypt", "Iran", "New Zealand"],
    "H": ["Spain", "Cape Verde", "Saudi Arabia", "Uruguay"],
    "I": ["France", "Senegal", "Iraq", "Norway"],
    "J": ["Argentina", "Algeria", "Austria", "Jordan"],
    "K": ["Portugal", "DR Congo", "Uzbekistan", "Colombia"],
    "L": ["England", "Croatia", "Ghana", "Panama"],
}


MARKET_TEAM_PRIORS = {
    "Spain": 0.16,
    "France": 0.13,
    "England": 0.11,
    "Argentina": 0.10,
    "Portugal": 0.07,
    "Brazil": 0.065,
    "Germany": 0.055,
    "Netherlands": 0.045,
}

MATCH_ADJUSTMENTS = {
    ("Mexico", "South Africa"): {"home": -35.0, "away": 25.0},
}

MATCH_MARKETS = {
    ("Mexico", "South Africa"): {"home": 0.722, "draw": 0.213, "away": 0.111, "weight": 0.45},
}


ROUND32_PATTERN = [
    ("A1", "C3"),
    ("B1", "F3"),
    ("C1", "A3"),
    ("D1", "G2"),
    ("E1", "B3"),
    ("F1", "E2"),
    ("G1", "D2"),
    ("H1", "I3"),
    ("I1", "H3"),
    ("J1", "L3"),
    ("K1", "J2"),
    ("L1", "K2"),
    ("A2", "B2"),
    ("C2", "D3"),
    ("E3", "F2"),
    ("H2", "G3"),
]


def load_fixtures() -> list[dict]:
    fixtures = []
    with Path("data/raw/results.csv").open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row["tournament"] == "FIFA World Cup" and row["date"].startswith("2026"):
                fixtures.append(row)
    return fixtures


def group_for(team: str) -> str:
    for group, teams in GROUPS.items():
        if team in teams:
            return group
    raise KeyError(team)


def fixture_id(row: dict) -> str:
    return (
        f"{row['date']}-{row['home_team']}-{row['away_team']}"
        .lower()
        .replace(" ", "-")
        .replace("ç", "c")
    )


def predicted_points(home_win: float, draw: float, away_win: float) -> tuple[float, float]:
    return home_win * 3 + draw, away_win * 3 + draw


def fair_knockout_prob(pred: dict) -> tuple[float, float]:
    home = pred["probabilities"]["home_win"]
    draw = pred["probabilities"]["draw"]
    away = pred["probabilities"]["away_win"]
    decisive_total = max(0.01, home + away)
    home_extra = home / decisive_total
    away_extra = away / decisive_total
    return home + draw * home_extra, away + draw * away_extra


def round_prob(prediction, home_seed: float = 0.0, away_seed: float = 0.0) -> tuple[float, float]:
    home = prediction.home_win
    draw = prediction.draw
    away = prediction.away_win
    decisive_total = max(0.01, home + away)
    home_adv = home / decisive_total
    away_adv = away / decisive_total
    home_p = home + draw * home_adv
    away_p = away + draw * away_adv
    if home_seed or away_seed:
        home_p = max(0.01, min(0.99, home_p + home_seed - away_seed))
        away_p = 1.0 - home_p
    return home_p, away_p


def team_market_adjust(team: str) -> float:
    prior = MARKET_TEAM_PRIORS.get(team, 0.015)
    return math.log(max(0.005, prior) / 0.03) * 18


def make_match_payload(row: dict, prediction) -> dict:
    return {
        "id": fixture_id(row),
        "date": row["date"],
        "group": group_for(row["home_team"]),
        "city": row["city"],
        "country": row["country"],
        "home": row["home_team"],
        "away": row["away_team"],
        "probabilities": {
            "home_win": prediction.home_win,
            "draw": prediction.draw,
            "away_win": prediction.away_win,
        },
        "expected_goals": {
            "home": prediction.expected_home_goals,
            "away": prediction.expected_away_goals,
        },
        "scoreline": prediction.most_likely_scores[0][0],
        "upset_score": prediction.upset_score,
    }


def rank_group(table: dict[str, dict]) -> list[dict]:
    return sorted(
        table.values(),
        key=lambda r: (r["points"], r["goal_diff"], r["goals_for"], r["rating"]),
        reverse=True,
    )


def seed_lookup(group_tables: dict[str, list[dict]]) -> dict[str, str]:
    lookup = {}
    thirds = []
    for group, rows in group_tables.items():
        lookup[f"{group}1"] = rows[0]["team"]
        lookup[f"{group}2"] = rows[1]["team"]
        thirds.append(rows[2] | {"seed": f"{group}3"})
    best_thirds = sorted(
        thirds,
        key=lambda r: (r["points"], r["goal_diff"], r["goals_for"], r["rating"]),
        reverse=True,
    )[:8]
    for row in best_thirds:
        lookup[row["seed"]] = row["team"]
    for row in thirds:
        lookup.setdefault(row["seed"], row["team"])
    return lookup


def play_knockout_round(matches, historical_matches, round_name: str) -> tuple[list[dict], list[str]]:
    out = []
    winners = []
    for idx, (home, away) in enumerate(matches, start=1):
        prediction = predict_match(
            historical_matches,
            home,
            away,
            datetime.strptime("2026-06-28", "%Y-%m-%d").date(),
            host_country="",
            neutral=True,
            manual_home_adjust=team_market_adjust(home),
            manual_away_adjust=team_market_adjust(away),
        )
        home_adv, away_adv = round_prob(prediction)
        winner = home if home_adv >= away_adv else away
        winners.append(winner)
        out.append(
            {
                "round": round_name,
                "match_no": idx,
                "home": home,
                "away": away,
                "home_advance": home_adv,
                "away_advance": away_adv,
                "winner": winner,
                "scoreline": prediction.most_likely_scores[0][0],
            }
        )
    return out, winners


def pair_adjacent(teams: list[str]) -> list[tuple[str, str]]:
    return [(teams[i], teams[i + 1]) for i in range(0, len(teams), 2)]


def main() -> None:
    historical_matches = load_matches()
    fixtures = load_fixtures()
    match_predictions = []
    tables = {
        group: {
            team: {
                "team": team,
                "group": group,
                "points": 0.0,
                "goals_for": 0.0,
                "goals_against": 0.0,
                "goal_diff": 0.0,
                "rating": 0.0,
            }
            for team in teams
        }
        for group, teams in GROUPS.items()
    }

    for row in fixtures:
        match_date = datetime.strptime(row["date"], "%Y-%m-%d").date()
        home, away = row["home_team"], row["away_team"]
        adjustment = MATCH_ADJUSTMENTS.get((home, away), {"home": 0.0, "away": 0.0})
        market = MATCH_MARKETS.get((home, away), {})
        prediction = predict_match(
            historical_matches,
            home,
            away,
            match_date,
            host_country=row["country"],
            neutral=row["neutral"].upper() == "TRUE",
            manual_home_adjust=team_market_adjust(home) + adjustment["home"],
            manual_away_adjust=team_market_adjust(away) + adjustment["away"],
            market_home=market.get("home"),
            market_draw=market.get("draw"),
            market_away=market.get("away"),
            market_weight=market.get("weight", 0.0),
        )
        match_predictions.append(make_match_payload(row, prediction))
        group = group_for(home)
        home_pts, away_pts = predicted_points(prediction.home_win, prediction.draw, prediction.away_win)
        tables[group][home]["points"] += home_pts
        tables[group][away]["points"] += away_pts
        tables[group][home]["goals_for"] += prediction.expected_home_goals
        tables[group][home]["goals_against"] += prediction.expected_away_goals
        tables[group][away]["goals_for"] += prediction.expected_away_goals
        tables[group][away]["goals_against"] += prediction.expected_home_goals
        tables[group][home]["rating"] = prediction.home_elo
        tables[group][away]["rating"] = prediction.away_elo

    group_tables = {}
    for group, rows in tables.items():
        for row in rows.values():
            row["goal_diff"] = row["goals_for"] - row["goals_against"]
        group_tables[group] = rank_group(rows)

    seeds = seed_lookup(group_tables)
    round32_pairs = [(seeds[a], seeds[b]) for a, b in ROUND32_PATTERN]
    bracket = []
    r32, r32_winners = play_knockout_round(round32_pairs, historical_matches, "Round of 32")
    bracket.extend(r32)
    r16, r16_winners = play_knockout_round(pair_adjacent(r32_winners), historical_matches, "Round of 16")
    bracket.extend(r16)
    qf, qf_winners = play_knockout_round(pair_adjacent(r16_winners), historical_matches, "Quarter-finals")
    bracket.extend(qf)
    sf, sf_winners = play_knockout_round(pair_adjacent(qf_winners), historical_matches, "Semi-finals")
    bracket.extend(sf)
    final, final_winner = play_knockout_round(pair_adjacent(sf_winners), historical_matches, "Final")
    bracket.extend(final)

    payload = {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "model_version": "v0.1-elo-poisson-market-prior",
        "note": "Round-of-32 third-place pairings are approximated for v0.1; probabilities are pre-match model outputs, not live odds.",
        "champion": final_winner[0],
        "groups": GROUPS,
        "group_tables": group_tables,
        "matches": match_predictions,
        "bracket": bracket,
    }
    out = Path("outputs/tournament_predictions.json")
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {out}")
    print(f"Champion: {payload['champion']}")


if __name__ == "__main__":
    main()
