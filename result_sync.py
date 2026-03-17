"""
Auto-sync NCAA tournament results from ESPN's public scoreboard API.
Fetches completed game scores and updates the local database.
"""

import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from data.historical_data import SAMPLE_TEAMS
from models import get_db

# ESPN public scoreboard API for men's college basketball
# groups=100 filters to NCAA tournament games
ESPN_SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/"
    "mens-college-basketball/scoreboard?groups=100&limit=100&dates={date}"
)

# Map our team names to possible ESPN names (ESPN may use different abbreviations)
# Build reverse lookup: lowercase ESPN-style name -> our name
_NAME_ALIASES = {
    # Common differences between our names and ESPN
    "uconn": "UConn",
    "connecticut": "UConn",
    "michigan state": "Michigan St",
    "michigan st.": "Michigan St",
    "north dakota st.": "N Dakota St",
    "north dakota state": "N Dakota St",
    "cal baptist": "CA Baptist",
    "california baptist": "CA Baptist",
    "saint john's": "St. John's",
    "st. john's": "St. John's",
    "saint mary's": "Saint Mary's",
    "saint mary's (ca)": "Saint Mary's",
    "texas a&m": "Texas A&M",
    "northern iowa": "Northern Iowa",
    "uni": "Northern Iowa",
    "south florida": "South Florida",
    "usf": "South Florida",
    "miami": "Miami (FL)",
    "miami (fl)": "Miami (FL)",
    "iowa state": "Iowa State",
    "texas tech": "Texas Tech",
    "utah state": "Utah State",
    "santa clara": "Santa Clara",
    "saint louis": "Saint Louis",
    "ohio state": "Ohio State",
    "north carolina": "North Carolina",
    "unc": "North Carolina",
    "kennesaw state": "Kennesaw St",
    "kennesaw st.": "Kennesaw St",
    "wright state": "Wright State",
    "wright st.": "Wright State",
    "tennessee state": "Tennessee St",
    "tennessee st.": "Tennessee St",
    "high point": "High Point",
    "hawai'i": "Hawai'i",
    "hawaii": "Hawai'i",
    "long island": "LIU",
    "long island university": "LIU",
}

# Build a set of all our team names for quick matching
_ALL_OUR_TEAMS = set()
for region_teams in SAMPLE_TEAMS.values():
    for name in region_teams.values():
        _ALL_OUR_TEAMS.add(name)
        _NAME_ALIASES[name.lower()] = name


def _resolve_team_name(espn_name):
    """Map an ESPN team name to our database team name."""
    if not espn_name:
        return None

    # Exact match first
    if espn_name in _ALL_OUR_TEAMS:
        return espn_name

    # Lowercase alias lookup
    lower = espn_name.lower().strip()
    if lower in _NAME_ALIASES:
        return _NAME_ALIASES[lower]

    # Partial match: check if ESPN name contains one of our team names
    for our_name in _ALL_OUR_TEAMS:
        if our_name.lower() in lower or lower in our_name.lower():
            return our_name

    return None


def _fetch_espn_scoreboard(date_str):
    """
    Fetch ESPN scoreboard data for a specific date.
    date_str: YYYYMMDD format
    Returns parsed JSON or None on error.
    """
    url = ESPN_SCOREBOARD_URL.format(date=date_str)
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "MarchMadnessPredictor/1.0",
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        print(f"[result_sync] ESPN fetch error for {date_str}: {e}")
        return None


def _find_game_in_db(conn, team_a_name, team_b_name):
    """Find a game in our results table matching both team names."""
    row = conn.execute(
        "SELECT region, round, game_index, team_a, team_b, winner "
        "FROM results WHERE "
        "(team_a = ? AND team_b = ?) OR (team_a = ? AND team_b = ?)",
        (team_a_name, team_b_name, team_b_name, team_a_name),
    ).fetchone()
    return dict(row) if row else None


def sync_results():
    """
    Fetch live results from ESPN and update the database.
    Checks games from tournament start through today.
    Returns dict with sync stats.
    """
    stats = {"checked": 0, "updated": 0, "errors": [], "skipped": 0}

    # Tournament dates: March 19 through April 6, 2026
    start = datetime(2026, 3, 19)
    end = min(datetime.now() + timedelta(days=1), datetime(2026, 4, 7))

    if datetime.now() < start:
        stats["errors"].append("Tournament hasn't started yet.")
        return stats

    conn = get_db()
    current = start

    while current <= end:
        date_str = current.strftime("%Y%m%d")
        data = _fetch_espn_scoreboard(date_str)

        if data and "events" in data:
            for event in data["events"]:
                stats["checked"] += 1
                try:
                    _process_espn_event(conn, event, stats)
                except Exception as e:
                    stats["errors"].append(f"Error processing event: {e}")

        current += timedelta(days=1)

    conn.commit()
    conn.close()
    return stats


def _process_espn_event(conn, event, stats):
    """Process a single ESPN event (game) and update our DB if completed."""
    competitions = event.get("competitions", [])
    if not competitions:
        return

    comp = competitions[0]
    status = comp.get("status", {})
    state = status.get("type", {}).get("state", "")

    # Only process completed games
    if state != "post":
        stats["skipped"] += 1
        return

    competitors = comp.get("competitors", [])
    if len(competitors) != 2:
        return

    # Extract team info
    teams = []
    for c in competitors:
        team_info = c.get("team", {})
        espn_name = team_info.get("displayName") or team_info.get("shortDisplayName") or team_info.get("name", "")
        our_name = _resolve_team_name(espn_name)
        seed_str = c.get("curatedRank", {}).get("current") or c.get("seed", "0")
        try:
            seed = int(seed_str)
        except (ValueError, TypeError):
            seed = 0
        winner = c.get("winner", False)
        teams.append({
            "espn_name": espn_name,
            "our_name": our_name,
            "seed": seed,
            "winner": winner,
        })

    team_a, team_b = teams[0], teams[1]

    if not team_a["our_name"] or not team_b["our_name"]:
        # Can't map to our teams
        stats["skipped"] += 1
        return

    # Find the game in our DB
    game = _find_game_in_db(conn, team_a["our_name"], team_b["our_name"])
    if not game:
        stats["skipped"] += 1
        return

    # Already has a winner
    if game["winner"]:
        stats["skipped"] += 1
        return

    # Determine winner
    winning_team = None
    for t in teams:
        if t["winner"]:
            winning_team = t["our_name"]
            break

    if not winning_team:
        stats["skipped"] += 1
        return

    # Validate winner is one of the teams in this game
    if winning_team not in (game["team_a"], game["team_b"]):
        stats["errors"].append(f"Winner '{winning_team}' not in game {game}")
        return

    # Get the winner's seed from our DB
    if winning_team == game["team_a"]:
        winner_seed = conn.execute(
            "SELECT seed_a FROM results WHERE region=? AND round=? AND game_index=?",
            (game["region"], game["round"], game["game_index"]),
        ).fetchone()["seed_a"]
    else:
        winner_seed = conn.execute(
            "SELECT seed_b FROM results WHERE region=? AND round=? AND game_index=?",
            (game["region"], game["round"], game["game_index"]),
        ).fetchone()["seed_b"]

    # Set the winner
    conn.execute(
        "UPDATE results SET winner = ?, updated_at = datetime('now') "
        "WHERE region = ? AND round = ? AND game_index = ?",
        (winning_team, game["region"], game["round"], game["game_index"]),
    )

    # Auto-advance winner to next round
    _advance_winner(conn, game["region"], game["round"], game["game_index"],
                    winning_team, winner_seed)

    stats["updated"] += 1


def _advance_winner(conn, region, round_num, game_index, winner, winner_seed):
    """Advance a winner to the next round slot (mirrors models.set_game_result logic)."""
    next_round = round_num + 1

    if region in ("East", "South", "West", "Midwest") and next_round <= 4:
        # Regional rounds
        next_game = game_index // 2
        is_top = (game_index % 2 == 0)

        existing = conn.execute(
            "SELECT * FROM results WHERE region=? AND round=? AND game_index=?",
            (region, next_round, next_game),
        ).fetchone()

        if existing:
            col = "team_a" if is_top else "team_b"
            seed_col = "seed_a" if is_top else "seed_b"
            conn.execute(
                f"UPDATE results SET {col}=?, {seed_col}=? "
                "WHERE region=? AND round=? AND game_index=?",
                (winner, winner_seed, region, next_round, next_game),
            )
        else:
            if is_top:
                conn.execute(
                    "INSERT INTO results (region, round, game_index, team_a, seed_a, team_b, seed_b) "
                    "VALUES (?, ?, ?, ?, ?, 'TBD', 0)",
                    (region, next_round, next_game, winner, winner_seed),
                )
            else:
                conn.execute(
                    "INSERT INTO results (region, round, game_index, team_a, seed_a, team_b, seed_b) "
                    "VALUES (?, ?, ?, 'TBD', 0, ?, ?)",
                    (region, next_round, next_game, winner, winner_seed),
                )

    elif region in ("East", "South", "West", "Midwest") and next_round == 5:
        # Region winner -> Final Four
        region_to_ff = {"East": 0, "South": 1, "West": 2, "Midwest": 3}
        ff_slot = region_to_ff.get(region, 0)
        ff_game = ff_slot // 2
        is_top = (ff_slot % 2 == 0)

        existing = conn.execute(
            "SELECT * FROM results WHERE region='Final Four' AND round=5 AND game_index=?",
            (ff_game,),
        ).fetchone()

        if existing:
            col = "team_a" if is_top else "team_b"
            seed_col = "seed_a" if is_top else "seed_b"
            conn.execute(
                f"UPDATE results SET {col}=?, {seed_col}=? "
                "WHERE region='Final Four' AND round=5 AND game_index=?",
                (winner, winner_seed, ff_game),
            )
        else:
            if is_top:
                conn.execute(
                    "INSERT INTO results (region, round, game_index, team_a, seed_a, team_b, seed_b) "
                    "VALUES ('Final Four', 5, ?, ?, ?, 'TBD', 0)",
                    (ff_game, winner, winner_seed),
                )
            else:
                conn.execute(
                    "INSERT INTO results (region, round, game_index, team_a, seed_a, team_b, seed_b) "
                    "VALUES ('Final Four', 5, ?, 'TBD', 0, ?, ?)",
                    (ff_game, winner, winner_seed),
                )

    elif region == "Final Four" and round_num == 5:
        # FF winner -> Championship
        is_top = (game_index == 0)
        existing = conn.execute(
            "SELECT * FROM results WHERE region='Final Four' AND round=6 AND game_index=0"
        ).fetchone()

        if existing:
            col = "team_a" if is_top else "team_b"
            seed_col = "seed_a" if is_top else "seed_b"
            conn.execute(
                f"UPDATE results SET {col}=?, {seed_col}=? "
                "WHERE region='Final Four' AND round=6 AND game_index=0",
                (winner, winner_seed),
            )
        else:
            if is_top:
                conn.execute(
                    "INSERT INTO results (region, round, game_index, team_a, seed_a, team_b, seed_b) "
                    "VALUES ('Final Four', 6, 0, ?, ?, 'TBD', 0)",
                    (winner, winner_seed),
                )
            else:
                conn.execute(
                    "INSERT INTO results (region, round, game_index, team_a, seed_a, team_b, seed_b) "
                    "VALUES ('Final Four', 6, 0, 'TBD', 0, ?, ?)",
                    (winner, winner_seed),
                )
