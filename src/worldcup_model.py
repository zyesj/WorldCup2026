from __future__ import annotations

import csv
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable


RESULTS_PATH = Path("data/raw/results.csv")


IMPORTANCE = {
    "FIFA World Cup": 60,
    "FIFA World Cup qualification": 40,
    "UEFA Euro": 45,
    "UEFA Euro qualification": 30,
    "Copa America": 45,
    "AFC Asian Cup": 38,
    "African Cup of Nations": 38,
    "CONCACAF Gold Cup": 34,
    "Oceania Nations Cup": 28,
    "UEFA Nations League": 28,
    "Friendly": 18,
}


@dataclass(frozen=True)
class Match:
    date: date
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    tournament: str
    country: str
    neutral: bool


@dataclass(frozen=True)
class TeamForm:
    matches: int
    goals_for: float
    goals_against: float
    points_per_match: float
    weighted_goal_diff: float


@dataclass(frozen=True)
class Prediction:
    home_team: str
    away_team: str
    home_win: float
    draw: float
    away_win: float
    expected_home_goals: float
    expected_away_goals: float
    most_likely_scores: list[tuple[str, float]]
    home_elo: float
    away_elo: float
    home_form: TeamForm
    away_form: TeamForm
    upset_score: float


def load_matches(path: Path = RESULTS_PATH) -> list[Match]:
    matches: list[Match] = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["home_score"] == "NA" or row["away_score"] == "NA":
                continue
            matches.append(
                Match(
                    date=datetime.strptime(row["date"], "%Y-%m-%d").date(),
                    home_team=row["home_team"],
                    away_team=row["away_team"],
                    home_score=int(row["home_score"]),
                    away_score=int(row["away_score"]),
                    tournament=row["tournament"],
                    country=row["country"],
                    neutral=row["neutral"].strip().upper() == "TRUE",
                )
            )
    return sorted(matches, key=lambda m: m.date)


def match_importance(tournament: str) -> int:
    return IMPORTANCE.get(tournament, 24)


def result_score(goals_for: int, goals_against: int) -> float:
    if goals_for > goals_against:
        return 1.0
    if goals_for == goals_against:
        return 0.5
    return 0.0


def goal_diff_multiplier(goal_diff: int, elo_diff: float) -> float:
    if goal_diff <= 1:
        return 1.0
    return math.log(goal_diff + 1.0) * (2.2 / ((abs(elo_diff) * 0.001) + 2.2))


def build_elo(matches: Iterable[Match], as_of: date) -> dict[str, float]:
    ratings: dict[str, float] = defaultdict(lambda: 1500.0)
    for match in matches:
        if match.date >= as_of:
            break

        home = ratings[match.home_team]
        away = ratings[match.away_team]
        home_adv = 0.0 if match.neutral else 75.0
        expected_home = 1.0 / (1.0 + 10 ** (-(home + home_adv - away) / 400.0))
        actual_home = result_score(match.home_score, match.away_score)
        gd_mult = goal_diff_multiplier(abs(match.home_score - match.away_score), home - away)
        k = match_importance(match.tournament) * gd_mult
        delta = k * (actual_home - expected_home)
        ratings[match.home_team] = home + delta
        ratings[match.away_team] = away - delta
    return dict(ratings)


def recent_form(matches: Iterable[Match], team: str, as_of: date, max_matches: int = 12) -> TeamForm:
    team_matches = [
        m
        for m in matches
        if m.date < as_of and (m.home_team == team or m.away_team == team)
    ][-max_matches:]

    if not team_matches:
        return TeamForm(0, 1.2, 1.2, 1.0, 0.0)

    weighted_for = weighted_against = weighted_points = weighted_gd = weight_total = 0.0
    for idx, match in enumerate(team_matches, start=1):
        recency_weight = idx / len(team_matches)
        importance_weight = match_importance(match.tournament) / 30.0
        weight = recency_weight * importance_weight
        if match.home_team == team:
            gf, ga = match.home_score, match.away_score
        else:
            gf, ga = match.away_score, match.home_score
        weighted_for += gf * weight
        weighted_against += ga * weight
        weighted_points += (3 if gf > ga else 1 if gf == ga else 0) * weight
        weighted_gd += (gf - ga) * weight
        weight_total += weight

    return TeamForm(
        matches=len(team_matches),
        goals_for=weighted_for / weight_total,
        goals_against=weighted_against / weight_total,
        points_per_match=weighted_points / weight_total,
        weighted_goal_diff=weighted_gd / weight_total,
    )


def poisson_pmf(lam: float, goals: int) -> float:
    return (math.exp(-lam) * lam**goals) / math.factorial(goals)


def score_distribution(home_lam: float, away_lam: float, max_goals: int = 7) -> dict[tuple[int, int], float]:
    dist = {}
    total = 0.0
    for home_goals in range(max_goals + 1):
        for away_goals in range(max_goals + 1):
            p = poisson_pmf(home_lam, home_goals) * poisson_pmf(away_lam, away_goals)
            dist[(home_goals, away_goals)] = p
            total += p
    return {score: p / total for score, p in dist.items()}


def predict_match(
    matches: list[Match],
    home_team: str,
    away_team: str,
    match_date: date,
    host_country: str,
    neutral: bool,
    manual_home_adjust: float = 0.0,
    manual_away_adjust: float = 0.0,
    market_home: float | None = None,
    market_draw: float | None = None,
    market_away: float | None = None,
    market_weight: float = 0.35,
) -> Prediction:
    ratings = build_elo(matches, match_date)
    home_elo = ratings.get(home_team, 1500.0)
    away_elo = ratings.get(away_team, 1500.0)
    home_form = recent_form(matches, home_team, match_date)
    away_form = recent_form(matches, away_team, match_date)

    home_adv = 0.0 if neutral else 60.0
    if host_country == home_team:
        home_adv += 45.0
    if host_country == away_team:
        home_adv -= 45.0

    elo_edge = (home_elo + home_adv + manual_home_adjust) - (away_elo + manual_away_adjust)

    home_share = 1.0 / (1.0 + 10 ** (-elo_edge / 520.0))
    total_goals = 2.38 + min(0.32, abs(elo_edge) / 1200.0)

    form_edge = (home_form.weighted_goal_diff - away_form.weighted_goal_diff) * 0.05
    home_attack = max(0.88, min(1.14, 1.0 + (home_form.goals_for - 1.35) * 0.06))
    away_attack = max(0.88, min(1.14, 1.0 + (away_form.goals_for - 1.20) * 0.06))
    home_def = max(0.88, min(1.14, 1.0 + (home_form.goals_against - 1.15) * 0.05))
    away_def = max(0.88, min(1.14, 1.0 + (away_form.goals_against - 1.15) * 0.05))

    expected_home_goals = max(0.35, total_goals * home_share * home_attack * away_def + form_edge)
    expected_away_goals = max(0.25, total_goals * (1.0 - home_share) * away_attack * home_def - form_edge)

    dist = score_distribution(expected_home_goals, expected_away_goals)
    home_win = sum(p for (h, a), p in dist.items() if h > a)
    draw = sum(p for (h, a), p in dist.items() if h == a)
    away_win = sum(p for (h, a), p in dist.items() if h < a)
    if market_home is not None and market_draw is not None and market_away is not None:
        total_market = market_home + market_draw + market_away
        m_home = market_home / total_market
        m_draw = market_draw / total_market
        m_away = market_away / total_market
        weight = max(0.0, min(0.8, market_weight))
        home_win = home_win * (1.0 - weight) + m_home * weight
        draw = draw * (1.0 - weight) + m_draw * weight
        away_win = away_win * (1.0 - weight) + m_away * weight
    most_likely = sorted(
        ((f"{h}-{a}", p) for (h, a), p in dist.items()),
        key=lambda item: item[1],
        reverse=True,
    )[:5]

    favorite_prob = max(home_win, away_win)
    underdog_prob = min(home_win, away_win)
    draw_pressure = draw * 35
    upset_score = min(100.0, underdog_prob * 100 + draw_pressure + max(0.0, 75 - abs(elo_edge)) * 0.12)

    return Prediction(
        home_team=home_team,
        away_team=away_team,
        home_win=home_win,
        draw=draw,
        away_win=away_win,
        expected_home_goals=expected_home_goals,
        expected_away_goals=expected_away_goals,
        most_likely_scores=most_likely,
        home_elo=home_elo,
        away_elo=away_elo,
        home_form=home_form,
        away_form=away_form,
        upset_score=upset_score,
    )


def format_pct(value: float) -> str:
    return f"{value * 100:.1f}%"
