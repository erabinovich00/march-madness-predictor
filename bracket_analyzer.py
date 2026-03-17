"""
Bracket Risk Score & Live Health Tracker.

Analyzes a user's bracket picks against historical seed-based probabilities
to produce a risk score, identify bold/safe picks, and during the tournament
track which upcoming games matter most.
"""

from data.historical_data import (
    HISTORICAL_MATCHUPS,
    SEED_STRENGTH,
    SAMPLE_TEAMS,
    CHAMPIONSHIP_RATES,
    FINAL_FOUR_RATES,
)
from predictor import get_win_probability

# Round names for display
ROUND_NAMES = {
    1: "Round of 64",
    2: "Round of 32",
    3: "Sweet 16",
    4: "Elite 8",
    5: "Final Four",
    6: "Championship",
}

# Standard bracket matchup order (seeds)
FIRST_ROUND_MATCHUPS = [
    (1, 16), (8, 9), (5, 12), (4, 13),
    (6, 11), (3, 14), (7, 10), (2, 15),
]


def _seed_for_team(region, team_name):
    """Look up a team's seed from the bracket data."""
    teams = SAMPLE_TEAMS.get(region, {})
    for seed, name in teams.items():
        if name == team_name:
            return seed
    return None


def _matchup_probability(seed_a, seed_b, round_number):
    """Get the probability that seed_a beats seed_b."""
    return get_win_probability(seed_a, seed_b, round_number)


def _build_game_tree(picks, region):
    """
    Walk through the picks for a region and build a list of
    (round, game_index, winner_name, winner_seed, loser_seed, win_prob)
    for each picked game.
    """
    region_picks = picks.get(region)
    if not region_picks or not isinstance(region_picks, list):
        return []

    teams = SAMPLE_TEAMS.get(region, {})
    games = []

    # Round 1 (index 0): matchups are known from seeds
    r1 = region_picks[0] if len(region_picks) > 0 else []
    for game_idx, (seed_a, seed_b) in enumerate(FIRST_ROUND_MATCHUPS):
        if game_idx >= len(r1) or not r1[game_idx]:
            continue
        winner_name = r1[game_idx]
        winner_seed = _seed_for_team(region, winner_name)
        if winner_seed == seed_a:
            loser_seed = seed_b
        else:
            loser_seed = seed_a
        loser_name = teams.get(loser_seed, f"#{loser_seed} seed")
        prob = _matchup_probability(winner_seed, loser_seed, 1)
        games.append({
            "round": 1,
            "round_name": ROUND_NAMES[1],
            "game": game_idx,
            "region": region,
            "winner": winner_name,
            "winner_seed": winner_seed,
            "loser": loser_name,
            "loser_seed": loser_seed,
            "win_prob": prob,
        })

    # Rounds 2-4: derive matchup opponents from previous round picks
    for round_idx in range(1, min(4, len(region_picks))):
        round_picks = region_picks[round_idx]
        prev_picks = region_picks[round_idx - 1]
        round_num = round_idx + 1

        for game_idx in range(len(round_picks) if round_picks else 0):
            winner_name = round_picks[game_idx]
            if not winner_name:
                continue

            # The two teams in this game come from previous round games 2*game_idx and 2*game_idx+1
            team_a_idx = game_idx * 2
            team_b_idx = game_idx * 2 + 1
            team_a = prev_picks[team_a_idx] if team_a_idx < len(prev_picks) else None
            team_b = prev_picks[team_b_idx] if team_b_idx < len(prev_picks) else None

            if not team_a or not team_b:
                continue

            winner_seed = _seed_for_team(region, winner_name)
            loser_name = team_b if winner_name == team_a else team_a
            loser_seed = _seed_for_team(region, loser_name)

            if winner_seed is None or loser_seed is None:
                continue

            prob = _matchup_probability(winner_seed, loser_seed, round_num)
            games.append({
                "round": round_num,
                "round_name": ROUND_NAMES[round_num],
                "game": game_idx,
                "region": region,
                "winner": winner_name,
                "winner_seed": winner_seed,
                "loser": loser_name,
                "loser_seed": loser_seed,
                "win_prob": prob,
            })

    return games


def analyze_bracket(picks):
    """
    Produce a full risk analysis of a bracket.

    Returns dict with:
      - risk_score: 0-100 (0 = pure chalk, 100 = maximum chaos)
      - risk_label: "Chalk" / "Mild" / "Bold" / "Reckless"
      - percentile: estimated percentile of riskiness
      - total_games: number of games analyzed
      - upset_count: number of upsets (lower seed beating higher seed)
      - expected_points: estimated points based on pick probabilities
      - max_possible: maximum possible points
      - boldest_picks: top 5 riskiest picks
      - safest_picks: top 5 most likely picks
      - region_risk: per-region risk breakdown
      - champion_analysis: analysis of champion pick
    """
    all_games = []
    region_data = {}

    for region in ["East", "South", "West", "Midwest"]:
        games = _build_game_tree(picks, region)
        all_games.extend(games)
        region_data[region] = games

    if not all_games:
        return {"error": "No picks found to analyze"}

    # === Risk Score Calculation ===
    # Each pick is weighted by round importance
    # Risk = average (1 - win_prob), weighted by round
    ROUND_WEIGHT = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6}
    total_weight = 0
    weighted_risk = 0
    upset_count = 0
    expected_points = 0
    max_possible = 0

    SCORING = {1: 10, 2: 20, 3: 40, 4: 80, 5: 160, 6: 320}

    for g in all_games:
        rd = g["round"]
        weight = ROUND_WEIGHT.get(rd, 1)
        risk = 1.0 - g["win_prob"]
        weighted_risk += risk * weight
        total_weight += weight

        # Is this an upset? (higher seed number = worse seed)
        if g["winner_seed"] > g.get("loser_seed", g["winner_seed"]):
            upset_count += 1

        # Expected points for this pick
        points = SCORING.get(rd, 10)
        expected_points += points * g["win_prob"]
        max_possible += points

    # Final Four & Championship analysis
    ff = picks.get("final_four", {})
    ff_games = []

    # Semifinal 1 - East winner vs South winner
    sf1_winner = ff.get("semifinal_1")
    # Semifinal 2 - West winner vs Midwest winner
    sf2_winner = ff.get("semifinal_2")
    champion = ff.get("champion")

    # Get region winners from Elite 8 picks
    region_winners = {}
    for region in ["East", "South", "West", "Midwest"]:
        rp = picks.get(region)
        if rp and len(rp) >= 4 and rp[3] and len(rp[3]) > 0 and rp[3][0]:
            region_winners[region] = rp[3][0]

    # Analyze semifinal 1
    if sf1_winner and "East" in region_winners and "South" in region_winners:
        east_seed = _seed_for_team("East", region_winners["East"])
        south_seed = _seed_for_team("South", region_winners["South"])
        if east_seed and south_seed:
            sf1_loser = region_winners["South"] if sf1_winner == region_winners["East"] else region_winners["East"]
            prob = _matchup_probability(
                _seed_for_team("East", sf1_winner) or east_seed,
                south_seed if sf1_winner == region_winners["East"] else east_seed,
                5
            )
            ff_game = {
                "round": 5, "round_name": "Final Four", "game": 0,
                "region": "Final Four",
                "winner": sf1_winner,
                "winner_seed": _seed_for_team("East", sf1_winner) or _seed_for_team("South", sf1_winner),
                "loser": sf1_loser,
                "loser_seed": south_seed if sf1_winner == region_winners["East"] else east_seed,
                "win_prob": prob,
            }
            ff_games.append(ff_game)
            weight = ROUND_WEIGHT[5]
            weighted_risk += (1.0 - prob) * weight
            total_weight += weight
            expected_points += SCORING[5] * prob
            max_possible += SCORING[5]

    # Analyze semifinal 2
    if sf2_winner and "West" in region_winners and "Midwest" in region_winners:
        west_seed = _seed_for_team("West", region_winners["West"])
        midwest_seed = _seed_for_team("Midwest", region_winners["Midwest"])
        if west_seed and midwest_seed:
            sf2_loser = region_winners["Midwest"] if sf2_winner == region_winners["West"] else region_winners["West"]
            prob = _matchup_probability(
                _seed_for_team("West", sf2_winner) or west_seed,
                midwest_seed if sf2_winner == region_winners["West"] else west_seed,
                5
            )
            ff_game = {
                "round": 5, "round_name": "Final Four", "game": 1,
                "region": "Final Four",
                "winner": sf2_winner,
                "winner_seed": _seed_for_team("West", sf2_winner) or _seed_for_team("Midwest", sf2_winner),
                "loser": sf2_loser,
                "loser_seed": midwest_seed if sf2_winner == region_winners["West"] else west_seed,
                "win_prob": prob,
            }
            ff_games.append(ff_game)
            weight = ROUND_WEIGHT[5]
            weighted_risk += (1.0 - prob) * weight
            total_weight += weight
            expected_points += SCORING[5] * prob
            max_possible += SCORING[5]

    # Championship
    if champion and sf1_winner and sf2_winner:
        champ_seed = None
        opponent_seed = None
        for region in ["East", "South", "West", "Midwest"]:
            s = _seed_for_team(region, champion)
            if s:
                champ_seed = s
                break
        opp = sf2_winner if champion == sf1_winner else sf1_winner
        for region in ["East", "South", "West", "Midwest"]:
            s = _seed_for_team(region, opp)
            if s:
                opponent_seed = s
                break

        if champ_seed and opponent_seed:
            prob = _matchup_probability(champ_seed, opponent_seed, 6)
            ff_game = {
                "round": 6, "round_name": "Championship", "game": 0,
                "region": "Final Four",
                "winner": champion,
                "winner_seed": champ_seed,
                "loser": opp,
                "loser_seed": opponent_seed,
                "win_prob": prob,
            }
            ff_games.append(ff_game)
            weight = ROUND_WEIGHT[6]
            weighted_risk += (1.0 - prob) * weight
            total_weight += weight
            expected_points += SCORING[6] * prob
            max_possible += SCORING[6]

    all_games.extend(ff_games)

    # Final risk score (0-100)
    raw_risk = (weighted_risk / total_weight) if total_weight > 0 else 0
    risk_score = round(min(100, raw_risk * 130), 1)  # Scale up slightly

    if risk_score < 20:
        risk_label = "Chalk"
        risk_emoji = "📋"
        risk_desc = "You're playing it very safe. High floor, lower ceiling."
    elif risk_score < 40:
        risk_label = "Calculated"
        risk_emoji = "🧮"
        risk_desc = "A smart mix of favorites and value picks."
    elif risk_score < 60:
        risk_label = "Bold"
        risk_emoji = "🔥"
        risk_desc = "You're swinging for the fences with some risky calls."
    elif risk_score < 80:
        risk_label = "Fearless"
        risk_emoji = "⚡"
        risk_desc = "High risk, high reward. You need chaos to win big."
    else:
        risk_label = "Reckless"
        risk_emoji = "💀"
        risk_desc = "Maximum madness. You're betting against history."

    # Percentile estimate (sigmoid mapping of risk score)
    import math
    percentile = round(100 / (1 + math.exp(-0.06 * (risk_score - 50))), 0)

    # Sort for boldest and safest
    sorted_by_risk = sorted(all_games, key=lambda g: g["win_prob"])
    boldest = sorted_by_risk[:5]
    safest = sorted_by_risk[-5:][::-1]

    # Per-region risk
    region_risk = {}
    for region in ["East", "South", "West", "Midwest"]:
        rg = region_data.get(region, [])
        if rg:
            avg = sum(1 - g["win_prob"] for g in rg) / len(rg)
            region_risk[region] = {
                "risk": round(avg * 100, 1),
                "upsets": sum(1 for g in rg if g["winner_seed"] > g.get("loser_seed", g["winner_seed"])),
                "games": len(rg),
            }

    # Champion analysis
    champ_analysis = None
    if champion:
        champ_seed = None
        champ_region = None
        for region in ["East", "South", "West", "Midwest"]:
            s = _seed_for_team(region, champion)
            if s:
                champ_seed = s
                champ_region = region
                break
        if champ_seed:
            hist_rate = CHAMPIONSHIP_RATES.get(champ_seed, 0)
            champ_analysis = {
                "name": champion,
                "seed": champ_seed,
                "region": champ_region,
                "historical_rate": round(hist_rate * 100, 1),
                "rating": SEED_STRENGTH.get(champ_seed, 50),
            }

    return {
        "risk_score": risk_score,
        "risk_label": risk_label,
        "risk_emoji": risk_emoji,
        "risk_desc": risk_desc,
        "percentile": int(percentile),
        "total_games": len(all_games),
        "upset_count": upset_count,
        "expected_points": round(expected_points, 0),
        "max_possible": max_possible,
        "boldest_picks": boldest,
        "safest_picks": safest,
        "all_games": all_games,
        "region_risk": region_risk,
        "champion": champ_analysis,
    }


def bracket_health(picks, results):
    """
    Compute live bracket health during the tournament.

    Args:
        picks: the user's bracket picks
        results: dict from get_all_results() with actual game outcomes

    Returns dict with:
      - alive: bool (can still win)
      - correct / incorrect / pending counts
      - current_points / max_remaining
      - survival_pct: estimated probability bracket stays competitive
      - critical_games: upcoming games that matter most for this bracket
      - busted_picks: picks that were wrong
      - correct_picks: picks that were right
    """
    SCORING = {1: 10, 2: 20, 3: 40, 4: 80, 5: 160, 6: 320}

    correct = 0
    incorrect = 0
    pending = 0
    current_points = 0
    busted = []
    correct_list = []
    max_remaining = 0
    critical_games = []

    # Surviving probability accumulation
    survival_product = 1.0

    # Check region picks
    for region in ["East", "South", "West", "Midwest"]:
        region_picks = picks.get(region)
        region_results = results.get("regions", {}).get(region, {})
        if not region_picks or not isinstance(region_picks, list):
            continue

        for round_idx, round_picks in enumerate(region_picks):
            round_num = round_idx + 1
            points = SCORING.get(round_num, 10)
            result_key = str(round_num)
            round_results = region_results.get(result_key, {})

            if not round_picks:
                continue

            for game_idx, winner_pick in enumerate(round_picks):
                if not winner_pick:
                    continue

                game_key = str(game_idx)
                actual_winner = round_results.get(game_key)

                if actual_winner is None:
                    # Game hasn't been played yet
                    pending += 1
                    max_remaining += points

                    # Is this pick still alive? Check if the team survived prior rounds
                    pick_seed = _seed_for_team(region, winner_pick)
                    if pick_seed:
                        # Calculate how critical this game is
                        # Use seed-based probability as an estimate
                        # Higher round + lower prob = more critical
                        prob = 0.5  # default if we can't determine opponent
                        critical_games.append({
                            "round": round_num,
                            "round_name": ROUND_NAMES.get(round_num, f"Round {round_num}"),
                            "region": region,
                            "team": winner_pick,
                            "seed": pick_seed,
                            "points_at_stake": points,
                            "estimated_prob": round(prob * 100, 1),
                        })
                elif actual_winner == winner_pick:
                    correct += 1
                    current_points += points
                    correct_list.append({
                        "round": round_num,
                        "round_name": ROUND_NAMES.get(round_num, f"Round {round_num}"),
                        "region": region,
                        "team": winner_pick,
                        "points": points,
                    })
                else:
                    incorrect += 1
                    busted.append({
                        "round": round_num,
                        "round_name": ROUND_NAMES.get(round_num, f"Round {round_num}"),
                        "region": region,
                        "picked": winner_pick,
                        "actual": actual_winner,
                        "points_lost": points,
                    })
                    # This pick was wrong - reduce survival
                    survival_product *= 0.85  # penalty per incorrect pick

    # Check Final Four / Championship
    ff_picks = picks.get("final_four", {})
    ff_results = results.get("final_four", {})

    for sf_name, round_num in [("semifinal_1", 5), ("semifinal_2", 5)]:
        winner_pick = ff_picks.get(sf_name)
        if not winner_pick:
            continue
        actual = ff_results.get(sf_name)
        points = SCORING[round_num]

        if actual is None:
            pending += 1
            max_remaining += points
            pick_seed = None
            for region in ["East", "South", "West", "Midwest"]:
                s = _seed_for_team(region, winner_pick)
                if s:
                    pick_seed = s
                    break
            critical_games.append({
                "round": round_num,
                "round_name": "Final Four",
                "region": "Final Four",
                "team": winner_pick,
                "seed": pick_seed,
                "points_at_stake": points,
                "estimated_prob": 50.0,
            })
        elif actual == winner_pick:
            correct += 1
            current_points += points
            correct_list.append({
                "round": round_num, "round_name": "Final Four",
                "region": "Final Four", "team": winner_pick, "points": points,
            })
        else:
            incorrect += 1
            busted.append({
                "round": round_num, "round_name": "Final Four",
                "region": "Final Four", "picked": winner_pick,
                "actual": actual, "points_lost": points,
            })
            survival_product *= 0.7

    # Championship
    champ_pick = ff_picks.get("champion")
    if champ_pick:
        actual_champ = ff_results.get("champion")
        points = SCORING[6]
        if actual_champ is None:
            pending += 1
            max_remaining += points
            champ_seed = None
            for region in ["East", "South", "West", "Midwest"]:
                s = _seed_for_team(region, champ_pick)
                if s:
                    champ_seed = s
                    break
            critical_games.append({
                "round": 6, "round_name": "Championship",
                "region": "Championship", "team": champ_pick,
                "seed": champ_seed, "points_at_stake": points,
                "estimated_prob": 50.0,
            })
        elif actual_champ == champ_pick:
            correct += 1
            current_points += points
            correct_list.append({
                "round": 6, "round_name": "Championship",
                "region": "Championship", "team": champ_pick, "points": points,
            })
        else:
            incorrect += 1
            busted.append({
                "round": 6, "round_name": "Championship",
                "region": "Championship", "picked": champ_pick,
                "actual": actual_champ, "points_lost": points,
            })
            survival_product *= 0.5

    # Sort critical games by points at stake (descending)
    critical_games.sort(key=lambda g: g["points_at_stake"], reverse=True)

    total_games = correct + incorrect + pending
    survival_pct = round(survival_product * 100, 1) if total_games > 0 else 100.0

    # Health label
    if incorrect == 0 and correct > 0:
        health_label = "Perfect"
        health_emoji = "💎"
    elif survival_pct >= 80:
        health_label = "Strong"
        health_emoji = "💪"
    elif survival_pct >= 50:
        health_label = "Alive"
        health_emoji = "🟢"
    elif survival_pct >= 25:
        health_label = "On Life Support"
        health_emoji = "🟡"
    else:
        health_label = "Busted"
        health_emoji = "💔"

    return {
        "correct": correct,
        "incorrect": incorrect,
        "pending": pending,
        "current_points": current_points,
        "max_remaining": max_remaining,
        "ceiling": current_points + max_remaining,
        "survival_pct": survival_pct,
        "health_label": health_label,
        "health_emoji": health_emoji,
        "critical_games": critical_games[:8],
        "busted_picks": busted,
        "correct_picks": correct_list,
    }
