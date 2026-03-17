"""
March Madness Bracket Prediction Engine.
Uses seed-based historical probabilities, strength ratings,
and configurable upset factors to simulate tournament outcomes.
"""

import random
from data.historical_data import (
    HISTORICAL_MATCHUPS,
    SEED_STRENGTH,
    ROUND_UPSET_FACTOR,
    SAMPLE_TEAMS,
)


def get_win_probability(seed_a, seed_b, round_number=1):
    """
    Calculate the probability that seed_a beats seed_b using historical data.

    Uses direct historical matchup data when available, otherwise falls back
    to a logistic model based on seed strength ratings.
    """
    higher_seed = min(seed_a, seed_b)
    lower_seed = max(seed_a, seed_b)

    # Check for direct historical matchup data
    matchup_key = (higher_seed, lower_seed)
    if matchup_key in HISTORICAL_MATCHUPS:
        base_prob = HISTORICAL_MATCHUPS[matchup_key]
    else:
        # Logistic model based on strength difference
        strength_a = SEED_STRENGTH.get(seed_a, 50)
        strength_b = SEED_STRENGTH.get(seed_b, 50)
        diff = strength_a - strength_b
        base_prob = 1.0 / (1.0 + 10 ** (-diff / 15.0))
        if seed_a > seed_b:
            base_prob = 1.0 - base_prob

    # Apply round upset factor (slightly increase upset chances in later rounds)
    upset_factor = ROUND_UPSET_FACTOR.get(round_number, 1.0)
    if seed_a < seed_b:
        # seed_a is favored - pull probability slightly toward 0.5
        adjusted = base_prob - (base_prob - 0.5) * (upset_factor - 1.0)
    else:
        # seed_a is underdog - pull probability slightly toward 0.5
        adjusted = base_prob + (0.5 - base_prob) * (upset_factor - 1.0)

    return max(0.01, min(0.99, adjusted))


def simulate_matchup(team_a, team_b, round_number=1, chaos_factor=0.0):
    """
    Simulate a single matchup between two teams.

    Args:
        team_a: dict with 'name' and 'seed'
        team_b: dict with 'name' and 'seed'
        round_number: tournament round (1-6)
        chaos_factor: 0.0 (chalk) to 1.0 (maximum chaos) - increases upset likelihood

    Returns:
        winner dict and win probability
    """
    prob_a = get_win_probability(team_a["seed"], team_b["seed"], round_number)

    # Scale upset likelihood by chaos: at 0 favorite always wins,
    # at 1 the true probability is used for the random draw.
    if prob_a >= 0.5:
        effective = 1.0 - (1.0 - prob_a) * chaos_factor
    else:
        effective = prob_a * chaos_factor
    effective = max(0.01, min(0.99, effective))

    if random.random() < effective:
        return team_a, prob_a
    else:
        return team_b, 1.0 - prob_a


def simulate_region(teams, chaos_factor=0.0):
    """
    Simulate an entire region of the bracket (16 teams -> 1 winner).

    Args:
        teams: dict mapping seed (int) -> team_name (str)
        chaos_factor: upset likelihood modifier

    Returns:
        List of rounds, each containing matchup results
    """
    # Standard bracket matchup order for seeds
    first_round_matchups = [
        (1, 16), (8, 9), (5, 12), (4, 13),
        (6, 11), (3, 14), (7, 10), (2, 15)
    ]

    current_teams = []
    for seed_a, seed_b in first_round_matchups:
        current_teams.append({"name": teams[seed_a], "seed": seed_a})
        current_teams.append({"name": teams[seed_b], "seed": seed_b})

    rounds = []
    round_number = 1

    while len(current_teams) > 1:
        round_results = []
        next_round = []

        for i in range(0, len(current_teams), 2):
            team_a = current_teams[i]
            team_b = current_teams[i + 1]
            winner, probability = simulate_matchup(
                team_a, team_b, round_number, chaos_factor
            )
            round_results.append({
                "team_a": team_a,
                "team_b": team_b,
                "winner": winner,
                "probability": round(probability * 100, 1),
            })
            next_round.append(winner)

        rounds.append({
            "round_number": round_number,
            "round_name": get_round_name(round_number),
            "matchups": round_results,
        })

        current_teams = next_round
        round_number += 1

    return rounds, current_teams[0]


def simulate_final_four(region_winners, chaos_factor=0.0):
    """
    Simulate the Final Four and Championship.

    Args:
        region_winners: dict mapping region_name -> winner team dict
        chaos_factor: upset likelihood modifier

    Returns:
        Final Four round results and champion
    """
    # 2026 Final Four matchups: East vs South, West vs Midwest
    semifinal_matchups = [
        ("East", "South"),
        ("West", "Midwest"),
    ]

    rounds = []

    # Final Four (Round 5)
    semifinal_results = []
    finalists = []
    for region_a, region_b in semifinal_matchups:
        team_a = region_winners[region_a]
        team_b = region_winners[region_b]
        winner, probability = simulate_matchup(team_a, team_b, 5, chaos_factor)
        semifinal_results.append({
            "team_a": team_a,
            "team_b": team_b,
            "winner": winner,
            "probability": round(probability * 100, 1),
            "label": f"{region_a} vs {region_b}",
        })
        finalists.append(winner)

    rounds.append({
        "round_number": 5,
        "round_name": "Final Four",
        "matchups": semifinal_results,
    })

    # Championship (Round 6)
    champion, probability = simulate_matchup(
        finalists[0], finalists[1], 6, chaos_factor
    )
    championship_result = {
        "team_a": finalists[0],
        "team_b": finalists[1],
        "winner": champion,
        "probability": round(probability * 100, 1),
        "label": "Championship",
    }

    rounds.append({
        "round_number": 6,
        "round_name": "Championship",
        "matchups": [championship_result],
    })

    return rounds, champion


def generate_full_bracket(teams=None, chaos_factor=0.7):
    """
    Generate a complete tournament bracket prediction.

    Args:
        teams: dict of regions -> seed -> team_name (uses sample data if None)
        chaos_factor: 0.0 (pure chalk/favorites) to 1.0 (maximum upsets)

    Returns:
        Complete bracket prediction with all rounds and the champion
    """
    if teams is None:
        teams = SAMPLE_TEAMS

    bracket = {"regions": {}, "final_four": None, "champion": None}
    region_winners = {}

    for region_name, region_teams in teams.items():
        rounds, winner = simulate_region(region_teams, chaos_factor)
        bracket["regions"][region_name] = {
            "rounds": rounds,
            "winner": winner,
        }
        region_winners[region_name] = winner

    ff_rounds, champion = simulate_final_four(region_winners, chaos_factor)
    bracket["final_four"] = ff_rounds
    bracket["champion"] = champion

    return bracket


def get_round_name(round_number):
    """Map round numbers to their common names."""
    names = {
        1: "Round of 64",
        2: "Round of 32",
        3: "Sweet 16",
        4: "Elite 8",
        5: "Final Four",
        6: "Championship",
    }
    return names.get(round_number, f"Round {round_number}")


def get_matchup_probability(seed_a, seed_b, round_number=1):
    """Public API for getting win probability between two seeds."""
    prob = get_win_probability(seed_a, seed_b, round_number)
    return {
        "seed_a": seed_a,
        "seed_b": seed_b,
        "probability_a": round(prob * 100, 1),
        "probability_b": round((1 - prob) * 100, 1),
    }
