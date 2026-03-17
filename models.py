"""
Database models and helpers for the March Madness Bracket app.
Uses SQLite via sqlite3 for zero-dependency persistence.
"""

import sqlite3
import os
import hashlib
import secrets
from datetime import datetime

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "madness.db"))

# Tournament lock time: March 19, 2026 9:15 AM ET (first game tip-off)
TOURNAMENT_LOCK = datetime(2026, 3, 19, 9, 15, 0)

# Standard bracket matchup slots for 63 games
# Each game has an ID: R1G1 through R1G32 (Round of 64), R2G1-R2G16, etc.
# For user picks, we store which team name they pick for each "slot"
ROUND_NAMES = {
    1: "Round of 64",
    2: "Round of 32",
    3: "Sweet 16",
    4: "Elite 8",
    5: "Final Four",
    6: "Championship",
}

# Scoring: points per correct pick per round
SCORING = {
    1: 10,   # Round of 64
    2: 20,   # Round of 32
    3: 40,   # Sweet 16
    4: 80,   # Elite 8
    5: 160,  # Final Four
    6: 320,  # Championship
}


def get_db():
    """Get a database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all tables if they don't exist."""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS brackets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL DEFAULT 'My Bracket',
            picks TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            invite_code TEXT UNIQUE NOT NULL,
            created_by INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (created_by) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS group_members (
            group_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            bracket_id INTEGER,
            joined_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (group_id, user_id),
            FOREIGN KEY (group_id) REFERENCES groups(id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (bracket_id) REFERENCES brackets(id)
        );

        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            region TEXT NOT NULL,
            round INTEGER NOT NULL,
            game_index INTEGER NOT NULL,
            team_a TEXT NOT NULL,
            seed_a INTEGER NOT NULL,
            team_b TEXT NOT NULL,
            seed_b INTEGER NOT NULL,
            winner TEXT,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(region, round, game_index)
        );

        CREATE TABLE IF NOT EXISTS tournament_config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)
    # Set default lock time if not exists
    cur = conn.execute(
        "SELECT value FROM tournament_config WHERE key='lock_time'"
    )
    if cur.fetchone() is None:
        conn.execute(
            "INSERT INTO tournament_config (key, value) VALUES (?, ?)",
            ("lock_time", TOURNAMENT_LOCK.isoformat()),
        )
    conn.commit()
    conn.close()


def hash_password(password, salt=None):
    """Hash a password with a salt using SHA-256."""
    if salt is None:
        salt = secrets.token_hex(16)
    hashed = hashlib.sha256((salt + password).encode()).hexdigest()
    return hashed, salt


def create_user(username, password):
    """Create a new user. Returns user id or None if username taken."""
    conn = get_db()
    password_hash, salt = hash_password(password)
    try:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, salt) VALUES (?, ?, ?)",
            (username, password_hash, salt),
        )
        conn.commit()
        user_id = cur.lastrowid
        conn.close()
        return user_id
    except sqlite3.IntegrityError:
        conn.close()
        return None


def authenticate_user(username, password):
    """Check credentials. Returns user dict or None."""
    conn = get_db()
    row = conn.execute(
        "SELECT id, username, password_hash, salt FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    hashed, _ = hash_password(password, row["salt"])
    if hashed == row["password_hash"]:
        return {"id": row["id"], "username": row["username"]}
    return None


def is_locked():
    """Check if bracket submissions are locked (tournament has started)."""
    conn = get_db()
    row = conn.execute(
        "SELECT value FROM tournament_config WHERE key='lock_time'"
    ).fetchone()
    conn.close()
    if row:
        lock_time = datetime.fromisoformat(row["value"])
        return datetime.now() >= lock_time
    return False


def get_lock_time():
    """Get the tournament lock time."""
    conn = get_db()
    row = conn.execute(
        "SELECT value FROM tournament_config WHERE key='lock_time'"
    ).fetchone()
    conn.close()
    if row:
        return row["value"]
    return TOURNAMENT_LOCK.isoformat()


def save_bracket(user_id, picks_json, name="My Bracket"):
    """Save a bracket for a user. Returns bracket id or None if locked."""
    if is_locked():
        return None
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO brackets (user_id, name, picks) VALUES (?, ?, ?)",
        (user_id, name, picks_json),
    )
    conn.commit()
    bracket_id = cur.lastrowid
    conn.close()
    return bracket_id


def update_bracket(bracket_id, user_id, picks_json, name=None):
    """Update an existing bracket. Returns True if updated."""
    if is_locked():
        return False
    conn = get_db()
    if name:
        conn.execute(
            "UPDATE brackets SET picks = ?, name = ? WHERE id = ? AND user_id = ?",
            (picks_json, name, bracket_id, user_id),
        )
    else:
        conn.execute(
            "UPDATE brackets SET picks = ? WHERE id = ? AND user_id = ?",
            (picks_json, bracket_id, user_id),
        )
    conn.commit()
    changes = conn.total_changes
    conn.close()
    return changes > 0


def get_user_brackets(user_id):
    """Get all brackets for a user."""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, name, picks, created_at FROM brackets WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_bracket(bracket_id):
    """Get a single bracket by id."""
    conn = get_db()
    row = conn.execute(
        "SELECT b.id, b.user_id, b.name, b.picks, b.created_at, u.username "
        "FROM brackets b JOIN users u ON b.user_id = u.id WHERE b.id = ?",
        (bracket_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# --- Groups ---

def create_group(name, user_id):
    """Create a new group. Returns group dict."""
    invite_code = secrets.token_urlsafe(8)
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO groups (name, invite_code, created_by) VALUES (?, ?, ?)",
        (name, invite_code, user_id),
    )
    group_id = cur.lastrowid
    # Creator auto-joins
    conn.execute(
        "INSERT INTO group_members (group_id, user_id) VALUES (?, ?)",
        (group_id, user_id),
    )
    conn.commit()
    conn.close()
    return {"id": group_id, "name": name, "invite_code": invite_code}


def join_group(invite_code, user_id):
    """Join a group by invite code. Returns group dict or None."""
    conn = get_db()
    group = conn.execute(
        "SELECT id, name, invite_code FROM groups WHERE invite_code = ?",
        (invite_code,),
    ).fetchone()
    if not group:
        conn.close()
        return None
    try:
        conn.execute(
            "INSERT INTO group_members (group_id, user_id) VALUES (?, ?)",
            (group["id"], user_id),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass  # Already a member
    conn.close()
    return dict(group)


def set_group_bracket(group_id, user_id, bracket_id):
    """Set which bracket a user is using for a group."""
    conn = get_db()
    conn.execute(
        "UPDATE group_members SET bracket_id = ? WHERE group_id = ? AND user_id = ?",
        (bracket_id, group_id, user_id),
    )
    conn.commit()
    conn.close()


def get_user_groups(user_id):
    """Get all groups a user belongs to."""
    conn = get_db()
    rows = conn.execute(
        "SELECT g.id, g.name, g.invite_code, g.created_by, gm.bracket_id, b.name AS bracket_name "
        "FROM groups g JOIN group_members gm ON g.id = gm.group_id "
        "LEFT JOIN brackets b ON gm.bracket_id = b.id "
        "WHERE gm.user_id = ?",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_group_leaderboard(group_id):
    """Get leaderboard for a group with scores."""
    conn = get_db()
    members = conn.execute(
        "SELECT gm.user_id, u.username, gm.bracket_id "
        "FROM group_members gm JOIN users u ON gm.user_id = u.id "
        "WHERE gm.group_id = ?",
        (group_id,),
    ).fetchall()

    results_rows = conn.execute(
        "SELECT region, round, game_index, winner FROM results WHERE winner IS NOT NULL"
    ).fetchall()
    conn.close()

    # Build set of actual winners: (region, round, game_index) -> winner
    actual_winners = {}
    for r in results_rows:
        actual_winners[(r["region"], r["round"], r["game_index"])] = r["winner"]

    leaderboard = []
    for m in members:
        score = 0
        correct = 0
        champion = None
        total_decided = len(actual_winners)
        if m["bracket_id"]:
            bracket = get_bracket(m["bracket_id"])
            if bracket:
                import json
                picks = json.loads(bracket["picks"])
                score, correct = calculate_score(picks, actual_winners)
                ff = picks.get("final_four") or {}
                champion = ff.get("champion") if isinstance(ff, dict) else None
        leaderboard.append({
            "user_id": m["user_id"],
            "username": m["username"],
            "bracket_id": m["bracket_id"],
            "score": score,
            "correct": correct,
            "total_decided": total_decided,
            "champion": champion,
        })

    leaderboard.sort(key=lambda x: x["score"], reverse=True)
    return leaderboard


def calculate_score(picks, actual_winners):
    """
    Calculate score for a bracket picks dict against actual results.

    picks format: {
        "East": {"1": ["Duke", "Duke", "Duke", "Duke"], ...},
        ...
        "final_four": {"semifinal_1": "Duke", "semifinal_2": "Arizona", "champion": "Duke"}
    }

    We map each pick to (region, round, game_index) and compare.
    """
    score = 0
    correct = 0

    for region in ["East", "South", "West", "Midwest"]:
        region_picks = picks.get(region, {})
        # region_picks is a list of round arrays
        # round 1: 8 winners, round 2: 4 winners, round 3: 2 winners, round 4: 1 winner
        if isinstance(region_picks, list):
            for round_idx, round_picks in enumerate(region_picks):
                round_num = round_idx + 1
                if isinstance(round_picks, list):
                    for game_idx, winner_name in enumerate(round_picks):
                        key = (region, round_num, game_idx)
                        if key in actual_winners:
                            if actual_winners[key] == winner_name:
                                score += SCORING.get(round_num, 10)
                                correct += 1

    # Final Four picks
    ff = picks.get("final_four", {})
    if isinstance(ff, dict):
        for game_idx, key_name in enumerate(["semifinal_1", "semifinal_2"]):
            pick = ff.get(key_name)
            result_key = ("Final Four", 5, game_idx)
            if pick and result_key in actual_winners:
                if actual_winners[result_key] == pick:
                    score += SCORING[5]
                    correct += 1
        champ_pick = ff.get("champion")
        result_key = ("Final Four", 6, 0)
        if champ_pick and result_key in actual_winners:
            if actual_winners[result_key] == champ_pick:
                score += SCORING[6]
                correct += 1

    return score, correct


# --- Live Results ---

def init_results():
    """Initialize the results table with all tournament matchups."""
    from data.historical_data import SAMPLE_TEAMS

    conn = get_db()

    # Check if already initialized
    count = conn.execute("SELECT COUNT(*) as c FROM results").fetchone()["c"]
    if count > 0:
        conn.close()
        return

    first_round_matchups = [
        (1, 16), (8, 9), (5, 12), (4, 13),
        (6, 11), (3, 14), (7, 10), (2, 15)
    ]

    for region_name, region_teams in SAMPLE_TEAMS.items():
        for game_idx, (seed_a, seed_b) in enumerate(first_round_matchups):
            conn.execute(
                "INSERT OR IGNORE INTO results (region, round, game_index, team_a, seed_a, team_b, seed_b) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (region_name, 1, game_idx, region_teams[seed_a], seed_a, region_teams[seed_b], seed_b),
            )

    conn.commit()
    conn.close()


def get_all_results():
    """Get all tournament results."""
    conn = get_db()
    rows = conn.execute(
        "SELECT region, round, game_index, team_a, seed_a, team_b, seed_b, winner "
        "FROM results ORDER BY region, round, game_index"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_game_result(region, round_num, game_index, winner):
    """
    Set the winner of a game and auto-advance to next round.
    Returns True if successful.
    """
    conn = get_db()

    # Get the game
    game = conn.execute(
        "SELECT * FROM results WHERE region = ? AND round = ? AND game_index = ?",
        (region, round_num, game_index),
    ).fetchone()

    if not game:
        conn.close()
        return False

    # Validate winner is one of the teams
    if winner not in (game["team_a"], game["team_b"]):
        conn.close()
        return False

    winner_seed = game["seed_a"] if winner == game["team_a"] else game["seed_b"]

    # Set winner
    conn.execute(
        "UPDATE results SET winner = ?, updated_at = datetime('now') "
        "WHERE region = ? AND round = ? AND game_index = ?",
        (winner, region, round_num, game_index),
    )

    # Auto-advance winner to next round
    next_round = round_num + 1
    if next_round <= 4:
        # Regional rounds (1-4)
        next_game_index = game_index // 2
        # Determine if this team goes to team_a or team_b slot
        is_top = (game_index % 2 == 0)

        existing = conn.execute(
            "SELECT * FROM results WHERE region = ? AND round = ? AND game_index = ?",
            (region, next_round, next_game_index),
        ).fetchone()

        if existing:
            if is_top:
                conn.execute(
                    "UPDATE results SET team_a = ?, seed_a = ? "
                    "WHERE region = ? AND round = ? AND game_index = ?",
                    (winner, winner_seed, region, next_round, next_game_index),
                )
            else:
                conn.execute(
                    "UPDATE results SET team_b = ?, seed_b = ? "
                    "WHERE region = ? AND round = ? AND game_index = ?",
                    (winner, winner_seed, region, next_round, next_game_index),
                )
        else:
            if is_top:
                conn.execute(
                    "INSERT INTO results (region, round, game_index, team_a, seed_a, team_b, seed_b) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (region, next_round, next_game_index, winner, winner_seed, "TBD", 0),
                )
            else:
                conn.execute(
                    "INSERT INTO results (region, round, game_index, team_a, seed_a, team_b, seed_b) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (region, next_round, next_game_index, "TBD", 0, winner, winner_seed),
                )

    elif next_round == 5:
        # Region winner goes to Final Four
        # East(0) vs South(1), West(2) vs Midwest(3)
        region_to_ff = {"East": 0, "South": 1, "West": 2, "Midwest": 3}
        ff_slot = region_to_ff.get(region, 0)
        ff_game = ff_slot // 2
        is_top = (ff_slot % 2 == 0)

        existing = conn.execute(
            "SELECT * FROM results WHERE region = 'Final Four' AND round = 5 AND game_index = ?",
            (ff_game,),
        ).fetchone()

        if existing:
            if is_top:
                conn.execute(
                    "UPDATE results SET team_a = ?, seed_a = ? "
                    "WHERE region = 'Final Four' AND round = 5 AND game_index = ?",
                    (winner, winner_seed, ff_game),
                )
            else:
                conn.execute(
                    "UPDATE results SET team_b = ?, seed_b = ? "
                    "WHERE region = 'Final Four' AND round = 5 AND game_index = ?",
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

    conn.commit()
    conn.close()
    return True


def set_final_four_result(game_index, winner):
    """Set Final Four or Championship result."""
    conn = get_db()

    game = conn.execute(
        "SELECT * FROM results WHERE region = 'Final Four' AND round = 5 AND game_index = ?",
        (game_index,),
    ).fetchone()

    if not game or winner not in (game["team_a"], game["team_b"]):
        conn.close()
        return False

    winner_seed = game["seed_a"] if winner == game["team_a"] else game["seed_b"]

    conn.execute(
        "UPDATE results SET winner = ?, updated_at = datetime('now') "
        "WHERE region = 'Final Four' AND round = 5 AND game_index = ?",
        (winner, game_index),
    )

    # Advance to championship
    is_top = (game_index == 0)
    existing = conn.execute(
        "SELECT * FROM results WHERE region = 'Final Four' AND round = 6 AND game_index = 0"
    ).fetchone()

    if existing:
        if is_top:
            conn.execute(
                "UPDATE results SET team_a = ?, seed_a = ? "
                "WHERE region = 'Final Four' AND round = 6 AND game_index = 0",
                (winner, winner_seed),
            )
        else:
            conn.execute(
                "UPDATE results SET team_b = ?, seed_b = ? "
                "WHERE region = 'Final Four' AND round = 6 AND game_index = 0",
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

    conn.commit()
    conn.close()
    return True


def set_championship_result(winner):
    """Set championship game result."""
    conn = get_db()
    game = conn.execute(
        "SELECT * FROM results WHERE region = 'Final Four' AND round = 6 AND game_index = 0"
    ).fetchone()
    if not game or winner not in (game["team_a"], game["team_b"]):
        conn.close()
        return False
    conn.execute(
        "UPDATE results SET winner = ?, updated_at = datetime('now') "
        "WHERE region = 'Final Four' AND round = 6 AND game_index = 0",
        (winner,),
    )
    conn.commit()
    conn.close()
    return True
