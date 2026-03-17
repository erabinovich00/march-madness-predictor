"""
ML-based March Madness prediction engine.

Fetches real team analytics from ESPN's public API and uses a logistic
regression model to predict matchup outcomes with team-specific features
instead of relying solely on seed-based historical averages.

Falls back to seed-based predictions when ESPN data is unavailable.
"""

import json
import math
import os
import random
import time
import urllib.request
import urllib.error
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression

from data.historical_data import (
    SAMPLE_TEAMS,
    HISTORICAL_MATCHUPS,
    SEED_STRENGTH,
    ROUND_UPSET_FACTOR,
)

# ---------------------------------------------------------------------------
# ESPN team-ID mapping (bracket name -> ESPN numeric ID)
# ---------------------------------------------------------------------------
_ESPN_IDS: dict[str, int] = {}  # populated lazily by _build_espn_id_map()

# Hard-coded overrides for names ESPN can't fuzzy-match
_ESPN_ID_OVERRIDES = {
    "Queens": 2511,
}

_CACHE_DIR = Path(__file__).parent / "cache"
_TEAM_CACHE_FILE = _CACHE_DIR / "espn_team_stats.json"
_CACHE_MAX_AGE = 6 * 3600  # 6 hours

# ---------------------------------------------------------------------------
# Feature columns used by the model (per team, so matchup has 2× these)
# ---------------------------------------------------------------------------
_STAT_FEATURES = [
    # Offensive
    "avgPoints",
    "fieldGoalPct",
    "threePointFieldGoalPct",
    "freeThrowPct",
    "avgAssists",
    "avgTurnovers",
    "avgOffensiveRebounds",
    "scoringEfficiency",
    # Defensive
    "avgDefensiveRebounds",
    "avgBlocks",
    "avgSteals",
    # General
    "avgRebounds",
    "assistTurnoverRatio",
]

# Supplemental features from the team profile
_PROFILE_FEATURES = [
    "wins",
    "losses",
    "avgPointsFor",
    "avgPointsAgainst",
    "pointDifferential",
    "strengthOfSchedule",  # derived
]


# ===================================================================
#  ESPN data fetching
# ===================================================================

def _fetch_json(url: str, timeout: int = 12) -> dict | None:
    """Fetch JSON from a URL, return None on error."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MarchMadnessPredictor/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _build_espn_id_map() -> dict[str, int]:
    """Build our bracket-name -> ESPN-ID map by fetching the full team list."""
    global _ESPN_IDS
    if _ESPN_IDS:
        return _ESPN_IDS

    data = _fetch_json(
        "https://site.api.espn.com/apis/site/v2/sports/basketball/"
        "mens-college-basketball/teams?limit=500"
    )
    if not data:
        return {}

    # Index every team by several name forms
    lookup: dict[str, int] = {}
    try:
        espn_teams = data["sports"][0]["leagues"][0]["teams"]
    except (KeyError, IndexError):
        return {}

    for entry in espn_teams:
        td = entry.get("team", entry)
        tid = int(td["id"])
        for key in ("displayName", "location", "shortDisplayName", "nickname",
                     "abbreviation", "name"):
            val = td.get(key, "")
            if val:
                lookup[val.lower()] = tid

    # Resolve each bracket team
    for region, seeds in SAMPLE_TEAMS.items():
        for seed, name in seeds.items():
            if name in _ESPN_ID_OVERRIDES:
                _ESPN_IDS[name] = _ESPN_ID_OVERRIDES[name]
                continue
            n = name.lower()
            eid = lookup.get(n)
            if not eid:
                # Substring match
                for lk, lid in lookup.items():
                    if n in lk or lk in n:
                        eid = lid
                        break
            if eid:
                _ESPN_IDS[name] = eid

    return _ESPN_IDS


def _fetch_team_stats(espn_id: int) -> dict | None:
    """Fetch season statistics for a single team."""
    data = _fetch_json(
        f"https://site.api.espn.com/apis/site/v2/sports/basketball/"
        f"mens-college-basketball/teams/{espn_id}/statistics"
    )
    if not data:
        return None
    try:
        categories = data["results"]["stats"]["categories"]
    except (KeyError, TypeError):
        return None

    flat: dict[str, float] = {}
    for cat in categories:
        for s in cat.get("stats", []):
            flat[s["name"]] = float(s.get("value", 0))
    return flat


def _fetch_team_profile(espn_id: int) -> dict | None:
    """Fetch team profile (W-L record, point differential)."""
    data = _fetch_json(
        f"https://site.api.espn.com/apis/site/v2/sports/basketball/"
        f"mens-college-basketball/teams/{espn_id}"
    )
    if not data:
        return None
    team = data.get("team", {})
    profile: dict[str, float] = {}
    try:
        overall = team["record"]["items"][0]  # "total" record
        summary = overall.get("summary", "0-0")
        w, l = summary.split("-")
        profile["wins"] = float(w)
        profile["losses"] = float(l)
        for s in overall.get("stats", []):
            profile[s["name"]] = float(s.get("value", 0))
    except Exception:
        pass
    return profile


# ===================================================================
#  Caching layer
# ===================================================================

def _load_cache() -> dict | None:
    """Return cached team data if fresh enough."""
    if not _TEAM_CACHE_FILE.exists():
        return None
    try:
        raw = json.loads(_TEAM_CACHE_FILE.read_text(encoding="utf-8"))
        if time.time() - raw.get("ts", 0) < _CACHE_MAX_AGE:
            return raw["teams"]
    except Exception:
        pass
    return None


def _save_cache(teams: dict) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _TEAM_CACHE_FILE.write_text(
        json.dumps({"ts": time.time(), "teams": teams}),
        encoding="utf-8",
    )


# ===================================================================
#  Build the analytics dataset for all 64 teams
# ===================================================================

def fetch_all_team_analytics(force: bool = False) -> dict:
    """
    Fetch and return analytics for every team in SAMPLE_TEAMS.

    Returns dict keyed by team name -> { "seed": int, "region": str, 
        "stats": {...}, "profile": {...}, "features": [...] }
    """
    if not force:
        cached = _load_cache()
        if cached:
            return cached

    id_map = _build_espn_id_map()
    all_teams: dict = {}

    for region, seeds in SAMPLE_TEAMS.items():
        for seed, name in seeds.items():
            espn_id = id_map.get(name)
            entry: dict = {"seed": seed, "region": region, "stats": {}, "profile": {}}
            if espn_id:
                stats = _fetch_team_stats(espn_id)
                if stats:
                    entry["stats"] = stats
                profile = _fetch_team_profile(espn_id)
                if profile:
                    entry["profile"] = profile
                time.sleep(0.05)  # be polite to the API
            all_teams[name] = entry

    # Compute derived features
    _compute_derived_features(all_teams)
    _save_cache(all_teams)
    return all_teams


def _compute_derived_features(all_teams: dict) -> None:
    """Add derived features to each team entry."""
    # Compute average opponent quality proxy (strength of schedule)
    # Use the point differential across all teams as a baseline
    diffs = []
    for name, t in all_teams.items():
        ppg = t["profile"].get("avgPointsFor", t["stats"].get("avgPoints", 0))
        papg = t["profile"].get("avgPointsAgainst", 0)
        diffs.append(ppg - papg)

    mean_diff = np.mean(diffs) if diffs else 0
    std_diff = np.std(diffs) if diffs else 1
    if std_diff == 0:
        std_diff = 1

    for name, t in all_teams.items():
        ppg = t["profile"].get("avgPointsFor", t["stats"].get("avgPoints", 0))
        papg = t["profile"].get("avgPointsAgainst", 0)
        diff = ppg - papg
        t["profile"]["pointDifferential"] = diff
        # Normalize SOS as z-score of opponent quality estimate
        wins = t["profile"].get("wins", 0)
        losses = t["profile"].get("losses", 0)
        total_games = wins + losses
        win_pct = wins / total_games if total_games > 0 else 0.5
        # SOS estimate: teams with high point differential *and* many wins are stronger
        t["profile"]["strengthOfSchedule"] = (diff - mean_diff) / std_diff
        t["profile"]["winPct"] = win_pct

    # Build normalised feature vectors
    all_feature_names = _STAT_FEATURES + _PROFILE_FEATURES
    raw_vectors = {}
    for name, t in all_teams.items():
        vec = []
        for feat in all_feature_names:
            val = t["stats"].get(feat, t["profile"].get(feat, 0.0))
            vec.append(float(val))
        raw_vectors[name] = vec

    # Z-score normalise each column so the model trains on comparable scales
    matrix = np.array(list(raw_vectors.values()))
    means = matrix.mean(axis=0)
    stds = matrix.std(axis=0)
    stds[stds == 0] = 1

    for name in all_teams:
        raw = np.array(raw_vectors[name])
        normed = ((raw - means) / stds).tolist()
        all_teams[name]["features"] = normed
        all_teams[name]["raw_features"] = raw_vectors[name]

    # Compute composite power rating (0-100 scale) for each team
    _compute_power_ratings(all_teams)


def _compute_power_ratings(all_teams: dict) -> None:
    """
    Compute a single composite power rating (0-100) for each team.
    Uses a weighted combination of key performance indicators.
    """
    # Collect raw metrics for percentile ranking
    metrics = {}
    names = list(all_teams.keys())
    for name in names:
        t = all_teams[name]
        stats = t.get("stats", {})
        profile = t.get("profile", {})
        metrics[name] = {
            "point_diff": float(profile.get("pointDifferential", 0)),
            "win_pct": float(profile.get("winPct", 0.5)),
            "off_eff": float(stats.get("scoringEfficiency", 0)),
            "fg_pct": float(stats.get("fieldGoalPct", 0)),
            "three_pct": float(stats.get("threePointFieldGoalPct", 0)),
            "ast_to": float(stats.get("assistTurnoverRatio", 0)),
            "rebounds": float(stats.get("avgRebounds", 0)),
            "steals": float(stats.get("avgSteals", 0)),
            "blocks": float(stats.get("avgBlocks", 0)),
            "turnovers": float(stats.get("avgTurnovers", 0)),  # lower is better
        }

    # Percentile-rank each metric across all 64 teams
    metric_names = list(next(iter(metrics.values())).keys())
    percentiles: dict[str, dict[str, float]] = {n: {} for n in names}

    for m in metric_names:
        vals = [(name, metrics[name][m]) for name in names]
        vals.sort(key=lambda x: x[1], reverse=(m != "turnovers"))
        for rank, (name, _) in enumerate(vals):
            percentiles[name][m] = 1.0 - rank / max(len(vals) - 1, 1)

    # Weighted composite — seed is included because the selection committee
    # already accounts for strength of schedule, eye test, and other factors
    # that raw stats can't capture (prevents small-conference stat inflation)
    weights = {
        "point_diff": 0.13,
        "win_pct": 0.09,
        "off_eff": 0.09,
        "fg_pct": 0.05,
        "three_pct": 0.03,
        "ast_to": 0.03,
        "rebounds": 0.04,
        "steals": 0.03,
        "blocks": 0.02,
        "turnovers": 0.04,
    }
    # Seed accounts for the remaining 45% — captures SOS, expert evaluation
    seed_weight = 0.45

    for name in names:
        stat_rating = sum(percentiles[name][m] * w for m, w in weights.items())
        # Seed factor: 1-seed gets 1.0, 16-seed gets ~0.0
        seed = all_teams[name]["seed"]
        seed_factor = (17 - seed) / 16.0
        rating = (stat_rating + seed_weight * seed_factor) * 100
        all_teams[name]["power_rating"] = float(round(rating, 1))


# ===================================================================
#  ML Model — Logistic Regression trained on historical matchup data
#  augmented with the team-specific analytics gap
# ===================================================================

class MarchMadnessModel:
    """
    Prediction model that blends:
      1. Historical seed matchup probabilities (60% weight — tournament variance is high)
      2. Power-rating-based probabilities from ESPN analytics (40% weight)
    
    The power rating is a composite of offensive/defensive efficiency, point
    differential, win percentage, rebounding, turnovers, and shooting.
    A logistic function converts the power rating difference into a probability.
    """

    _HISTORY_WEIGHT = 0.65  # how much to trust historical seed matchup rates
    _ANALYTICS_WEIGHT = 0.35  # how much to trust current-season analytics

    def __init__(self):
        self._team_data: dict = {}
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    def train(self, team_data: dict | None = None) -> None:
        if team_data is None:
            team_data = fetch_all_team_analytics()
        self._team_data = team_data
        # No sklearn model needed — we use a direct logistic formula + blending
        self._ready = any("power_rating" in t for t in team_data.values())

    def predict_matchup(self, team_a: str, team_b: str,
                        seed_a: int, seed_b: int,
                        round_number: int = 1) -> float:
        """Predict P(team_a wins) by blending historical + analytics."""
        historical = _seed_based_prob(seed_a, seed_b, round_number)

        if not self._ready:
            return historical

        ta = self._team_data.get(team_a, {})
        tb = self._team_data.get(team_b, {})
        pr_a = ta.get("power_rating", SEED_STRENGTH.get(seed_a, 50))
        pr_b = tb.get("power_rating", SEED_STRENGTH.get(seed_b, 50))

        # Logistic function on power rating difference (scaled for ~0-100 range)
        diff = pr_a - pr_b
        analytics_prob = 1.0 / (1.0 + math.exp(-diff / 12.0))

        # Blend: trust history for the base rate, analytics for differentiation
        blended = (self._HISTORY_WEIGHT * historical +
                   self._ANALYTICS_WEIGHT * analytics_prob)

        return max(0.02, min(0.98, blended))

    def get_team_rating(self, team_name: str) -> dict | None:
        """Return a human-readable analytics summary for a team."""
        t = self._team_data.get(team_name)
        if not t:
            return None

        stats = t.get("stats", {})
        profile = t.get("profile", {})

        def _f(val, ndigits=1):
            return float(round(float(val), ndigits))

        return {
            "team": team_name,
            "seed": t["seed"],
            "region": t["region"],
            "power_rating": _f(t.get("power_rating", 0)),
            "record": f"{int(profile.get('wins', 0))}-{int(profile.get('losses', 0))}",
            "ppg": _f(stats.get("avgPoints", 0)),
            "opp_ppg": _f(profile.get("avgPointsAgainst", 0)),
            "point_diff": _f(profile.get("pointDifferential", 0)),
            "fg_pct": _f(stats.get("fieldGoalPct", 0)),
            "three_pct": _f(stats.get("threePointFieldGoalPct", 0)),
            "ft_pct": _f(stats.get("freeThrowPct", 0)),
            "rebounds": _f(stats.get("avgRebounds", 0)),
            "assists": _f(stats.get("avgAssists", 0)),
            "turnovers": _f(stats.get("avgTurnovers", 0)),
            "steals": _f(stats.get("avgSteals", 0)),
            "blocks": _f(stats.get("avgBlocks", 0)),
            "sos": _f(profile.get("strengthOfSchedule", 0), 2),
            "win_pct": _f(profile.get("winPct", 0) * 100),
        }


# ===================================================================
#  Helpers
# ===================================================================

def _seed_based_prob(seed_a: int, seed_b: int, round_number: int = 1) -> float:
    """Fallback seed-only probability from historical data."""
    higher = min(seed_a, seed_b)
    lower = max(seed_a, seed_b)
    key = (higher, lower)
    if key in HISTORICAL_MATCHUPS:
        base = HISTORICAL_MATCHUPS[key]
    else:
        sa = SEED_STRENGTH.get(seed_a, 50)
        sb = SEED_STRENGTH.get(seed_b, 50)
        diff = sa - sb
        base = 1.0 / (1.0 + 10 ** (-diff / 15.0))
        if seed_a > seed_b:
            base = 1.0 - base

    # Round upset factor
    uf = ROUND_UPSET_FACTOR.get(round_number, 1.0)
    if seed_a < seed_b:
        base = base - (base - 0.5) * (uf - 1.0)
    else:
        base = base + (0.5 - base) * (uf - 1.0)

    if seed_a > seed_b:
        base = 1.0 - base if key in HISTORICAL_MATCHUPS else base

    return max(0.01, min(0.99, base))


def _guess_round(seed_a: int, seed_b: int) -> int:
    """Estimate what round two seeds would typically meet."""
    if (seed_a + seed_b) == 17:
        return 1
    s = min(seed_a, seed_b)
    if s <= 2 and max(seed_a, seed_b) <= 4:
        return 4  # Elite 8
    if s <= 4:
        return 3  # Sweet 16
    return 2  # Round of 32


# ===================================================================
#  Bracket simulation using the ML model
# ===================================================================

def simulate_matchup_ml(model: MarchMadnessModel,
                        team_a: dict, team_b: dict,
                        round_number: int = 1,
                        chaos_factor: float = 0.0):
    """Simulate a matchup using the ML model.

    chaos_factor controls how much randomness affects outcomes:
      0.0 = chalk (favorites always win)
      1.0 = true probability-based draws (realistic March Madness)
    The upset chance scales proportionally to the actual win probability,
    so a 1-vs-16 upset stays far rarer than a 5-vs-12 upset at any level.
    """
    prob_a = model.predict_matchup(
        team_a["name"], team_b["name"],
        team_a["seed"], team_b["seed"],
        round_number,
    )
    # Scale upset likelihood by chaos: at 0 favorite always wins,
    # at 1 the true probability is used for the random draw.
    if prob_a >= 0.5:
        effective = 1.0 - (1.0 - prob_a) * chaos_factor
    else:
        effective = prob_a * chaos_factor
    effective = max(0.01, min(0.99, effective))

    if random.random() < effective:
        return team_a, prob_a  # report the true model probability
    else:
        return team_b, 1.0 - prob_a


def simulate_region_ml(model: MarchMadnessModel, teams: dict,
                       chaos_factor: float = 0.0):
    """Simulate an entire region using the ML model."""
    first_round_matchups = [
        (1, 16), (8, 9), (5, 12), (4, 13),
        (6, 11), (3, 14), (7, 10), (2, 15),
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
            ta = current_teams[i]
            tb = current_teams[i + 1]
            winner, probability = simulate_matchup_ml(
                model, ta, tb, round_number, chaos_factor,
            )
            round_results.append({
                "team_a": ta,
                "team_b": tb,
                "winner": winner,
                "probability": round(probability * 100, 1),
            })
            next_round.append(winner)

        rounds.append({
            "round_number": round_number,
            "round_name": _round_name(round_number),
            "matchups": round_results,
        })
        current_teams = next_round
        round_number += 1

    return rounds, current_teams[0]


def simulate_final_four_ml(model: MarchMadnessModel, region_winners: dict,
                           chaos_factor: float = 0.0):
    """Simulate Final Four + Championship with the ML model."""
    semifinal_matchups = [("East", "South"), ("West", "Midwest")]
    rounds = []

    semifinal_results = []
    finalists = []
    for region_a, region_b in semifinal_matchups:
        ta = region_winners[region_a]
        tb = region_winners[region_b]
        winner, probability = simulate_matchup_ml(model, ta, tb, 5, chaos_factor)
        semifinal_results.append({
            "team_a": ta, "team_b": tb, "winner": winner,
            "probability": round(probability * 100, 1),
            "label": f"{region_a} vs {region_b}",
        })
        finalists.append(winner)

    rounds.append({"round_number": 5, "round_name": "Final Four",
                    "matchups": semifinal_results})

    champion, probability = simulate_matchup_ml(
        model, finalists[0], finalists[1], 6, chaos_factor,
    )
    rounds.append({
        "round_number": 6, "round_name": "Championship",
        "matchups": [{
            "team_a": finalists[0], "team_b": finalists[1],
            "winner": champion, "probability": round(probability * 100, 1),
            "label": "Championship",
        }],
    })
    return rounds, champion


def generate_ml_bracket(model: MarchMadnessModel, teams=None,
                        chaos_factor: float = 0.7) -> dict:
    """Generate a complete bracket using the ML model."""
    if teams is None:
        teams = SAMPLE_TEAMS

    bracket = {"regions": {}, "final_four": None, "champion": None,
               "model": "ml" if model.ready else "seed-based"}
    region_winners = {}

    for region_name, region_teams in teams.items():
        rounds, winner = simulate_region_ml(model, region_teams, chaos_factor)
        bracket["regions"][region_name] = {"rounds": rounds, "winner": winner}
        region_winners[region_name] = winner

    ff_rounds, champion = simulate_final_four_ml(model, region_winners, chaos_factor)
    bracket["final_four"] = ff_rounds
    bracket["champion"] = champion
    return bracket


def get_ml_matchup_probability(model: MarchMadnessModel,
                               team_a_name: str, team_b_name: str,
                               seed_a: int, seed_b: int,
                               round_number: int = 1) -> dict:
    """Public API: get matchup probability for two specific teams."""
    prob = model.predict_matchup(team_a_name, team_b_name,
                                 seed_a, seed_b, round_number)
    rating_a = model.get_team_rating(team_a_name)
    rating_b = model.get_team_rating(team_b_name)
    return {
        "seed_a": seed_a,
        "seed_b": seed_b,
        "team_a": team_a_name,
        "team_b": team_b_name,
        "probability_a": round(prob * 100, 1),
        "probability_b": round((1 - prob) * 100, 1),
        "rating_a": rating_a,
        "rating_b": rating_b,
        "model": "ml" if model.ready else "seed-based",
    }


def _round_name(n: int) -> str:
    return {1: "Round of 64", 2: "Round of 32", 3: "Sweet 16",
            4: "Elite 8", 5: "Final Four", 6: "Championship"}.get(n, f"Round {n}")


# ===================================================================
#  Singleton model instance for the app
# ===================================================================
_model_instance: MarchMadnessModel | None = None


def get_model() -> MarchMadnessModel:
    """Get or create the global model instance."""
    global _model_instance
    if _model_instance is None:
        _model_instance = MarchMadnessModel()
    return _model_instance


def init_model() -> MarchMadnessModel:
    """Initialize and train the model (call at startup)."""
    model = get_model()
    if not model.ready:
        print("[ML] Fetching ESPN analytics for all 64 teams...")
        team_data = fetch_all_team_analytics()
        print(f"[ML] Got analytics for {sum(1 for t in team_data.values() if t.get('stats'))} teams")
        print("[ML] Training logistic regression model...")
        model.train(team_data)
        print("[ML] Model ready!")
    return model
