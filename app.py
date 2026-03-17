"""
Flask web application for March Madness Bracket Predictor.
Features: user auth, bracket submission with lock, live results, groups, leaderboards.
"""

import json
import os
import secrets
import threading
import time
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, jsonify, request, session, redirect, url_for

from predictor import generate_full_bracket, get_matchup_probability
from bracket_analyzer import analyze_bracket, bracket_health
from ml_predictor import (
    init_model, get_model, generate_ml_bracket,
    get_ml_matchup_probability, fetch_all_team_analytics,
)
from data.historical_data import SAMPLE_TEAMS, SEED_STRENGTH
from models import (
    init_db, init_results, is_locked, get_lock_time,
    create_user, authenticate_user,
    save_bracket, update_bracket, get_user_brackets, get_bracket,
    create_group, join_group, get_user_groups, get_group_leaderboard,
    set_group_bracket,
    get_all_results, set_game_result, set_final_four_result, set_championship_result,
    SCORING,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

# Initialize database on startup
init_db()
init_results()

# Initialize ML model in background (avoid blocking startup / health probes)
_ml_model = get_model()  # untrained fallback; will be replaced once init finishes

def _init_ml_background():
    global _ml_model
    try:
        _ml_model = init_model()
    except Exception as e:
        print(f"[ML] Failed to initialize model: {e}")

threading.Thread(target=_init_ml_background, daemon=True).start()


# --- Auth helpers ---

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            if request.is_json:
                return jsonify({"error": "Login required"}), 401
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("username") != "admin":
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated


# --- Pages ---

@app.route("/")
def index():
    return render_template("index.html",
                         teams=SAMPLE_TEAMS,
                         user=session.get("username"),
                         user_id=session.get("user_id"))


@app.route("/login")
def login_page():
    if "user_id" in session:
        return redirect(url_for("index"))
    return render_template("auth.html", mode="login")


@app.route("/register")
def register_page():
    if "user_id" in session:
        return redirect(url_for("index"))
    return render_template("auth.html", mode="register")


# --- Auth API ---

@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")

    if not username or len(username) < 3 or len(username) > 30:
        return jsonify({"error": "Username must be 3-30 characters"}), 400
    if not password or len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400

    user_id = create_user(username, password)
    if user_id is None:
        return jsonify({"error": "Username already taken"}), 409

    session["user_id"] = user_id
    session["username"] = username
    return jsonify({"user_id": user_id, "username": username})


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")

    user = authenticate_user(username, password)
    if user is None:
        return jsonify({"error": "Invalid username or password"}), 401

    session["user_id"] = user["id"]
    session["username"] = user["username"]
    return jsonify({"user_id": user["id"], "username": user["username"]})


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/me")
def me():
    if "user_id" in session:
        return jsonify({
            "user_id": session["user_id"],
            "username": session["username"],
            "logged_in": True,
        })
    return jsonify({"logged_in": False})


# --- Tournament status ---

@app.route("/api/status")
def tournament_status():
    return jsonify({
        "locked": is_locked(),
        "lock_time": get_lock_time(),
        "scoring": SCORING,
    })


# --- Bracket API ---

@app.route("/api/predict", methods=["POST"])
def predict():
    data = request.get_json(silent=True) or {}
    chaos_factor = max(0.0, min(1.0, float(data.get("chaos_factor", 0.3))))
    use_ml = data.get("use_ml", True)
    teams = data.get("teams", None)
    if teams is not None:
        for region, seeds in teams.items():
            if not isinstance(seeds, dict):
                return jsonify({"error": f"Invalid team data for region {region}"}), 400
            teams[region] = {int(k): v for k, v in seeds.items()}

    if use_ml and _ml_model.ready:
        bracket = generate_ml_bracket(_ml_model, teams=teams, chaos_factor=chaos_factor)
    else:
        bracket = generate_full_bracket(teams=teams, chaos_factor=chaos_factor)
    return jsonify(bracket)


@app.route("/api/brackets", methods=["POST"])
@login_required
def create_bracket_api():
    if is_locked():
        return jsonify({"error": "Tournament has started. Brackets are locked."}), 403
    data = request.get_json(silent=True) or {}
    picks = data.get("picks")
    name = data.get("name", "My Bracket")
    if not picks:
        return jsonify({"error": "Picks are required"}), 400
    bracket_id = save_bracket(session["user_id"], json.dumps(picks), name)
    if bracket_id is None:
        return jsonify({"error": "Tournament has started. Brackets are locked."}), 403
    return jsonify({"bracket_id": bracket_id, "name": name})


@app.route("/api/brackets", methods=["GET"])
@login_required
def list_brackets():
    brackets = get_user_brackets(session["user_id"])
    for b in brackets:
        b["picks"] = json.loads(b["picks"])
    return jsonify(brackets)


@app.route("/api/brackets/<int:bracket_id>", methods=["GET"])
def get_bracket_api(bracket_id):
    bracket = get_bracket(bracket_id)
    if not bracket:
        return jsonify({"error": "Bracket not found"}), 404
    bracket["picks"] = json.loads(bracket["picks"])
    return jsonify(bracket)


@app.route("/api/brackets/<int:bracket_id>", methods=["PUT"])
@login_required
def update_bracket_api(bracket_id):
    if is_locked():
        return jsonify({"error": "Tournament has started. Brackets are locked."}), 403
    data = request.get_json(silent=True) or {}
    picks = data.get("picks")
    name = data.get("name")
    if not picks:
        return jsonify({"error": "Picks are required"}), 400
    ok = update_bracket(bracket_id, session["user_id"], json.dumps(picks), name)
    if not ok:
        return jsonify({"error": "Could not update bracket"}), 400
    return jsonify({"ok": True})


# --- Groups API ---

@app.route("/api/groups", methods=["POST"])
@login_required
def create_group_api():
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    if not name or len(name) > 50:
        return jsonify({"error": "Group name must be 1-50 characters"}), 400
    group = create_group(name, session["user_id"])
    return jsonify(group)


@app.route("/api/groups", methods=["GET"])
@login_required
def list_groups():
    groups = get_user_groups(session["user_id"])
    return jsonify(groups)


@app.route("/api/groups/join", methods=["POST"])
@login_required
def join_group_api():
    data = request.get_json(silent=True) or {}
    code = data.get("invite_code", "").strip()
    if not code:
        return jsonify({"error": "Invite code required"}), 400
    group = join_group(code, session["user_id"])
    if not group:
        return jsonify({"error": "Invalid invite code"}), 404
    return jsonify(group)


@app.route("/api/groups/<int:group_id>/bracket", methods=["GET"])
@login_required
def get_group_bracket_api(group_id):
    conn = __import__('models').get_db()
    row = conn.execute(
        "SELECT bracket_id FROM group_members WHERE group_id = ? AND user_id = ?",
        (group_id, session["user_id"]),
    ).fetchone()
    conn.close()
    return jsonify({"bracket_id": row["bracket_id"] if row else None})


@app.route("/api/groups/<int:group_id>/bracket", methods=["POST"])
@login_required
def set_group_bracket_api(group_id):
    from models import TOURNAMENT_LOCK
    if datetime.now() >= TOURNAMENT_LOCK:
        return jsonify({"error": "Brackets are locked! The tournament has started."}), 403
    data = request.get_json(silent=True) or {}
    bracket_id = data.get("bracket_id")
    if not bracket_id:
        return jsonify({"error": "bracket_id required"}), 400
    set_group_bracket(group_id, session["user_id"], bracket_id)
    return jsonify({"ok": True})


@app.route("/api/groups/<int:group_id>/leaderboard")
def group_leaderboard(group_id):
    lb = get_group_leaderboard(group_id)
    return jsonify(lb)


# --- Results API ---

@app.route("/api/results")
def results():
    return jsonify(get_all_results())


@app.route("/api/results", methods=["POST"])
@login_required
@admin_required
def update_result():
    data = request.get_json(silent=True) or {}
    region = data.get("region")
    round_num = data.get("round")
    game_index = data.get("game_index")
    winner = data.get("winner")

    if not all([region, round_num is not None, game_index is not None, winner]):
        return jsonify({"error": "region, round, game_index, and winner required"}), 400

    if region == "Final Four" and round_num == 6:
        ok = set_championship_result(winner)
    elif region == "Final Four" and round_num == 5:
        ok = set_final_four_result(game_index, winner)
    else:
        ok = set_game_result(region, round_num, game_index, winner)

    if not ok:
        return jsonify({"error": "Could not update result"}), 400
    return jsonify({"ok": True})


# --- Matchup calculator ---

@app.route("/api/matchup")
def matchup():
    try:
        seed_a = int(request.args.get("seed_a", 1))
        seed_b = int(request.args.get("seed_b", 16))
        round_num = int(request.args.get("round", 1))
        region = request.args.get("region", "East")
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid seed or round values"}), 400
    if not (1 <= seed_a <= 16 and 1 <= seed_b <= 16):
        return jsonify({"error": "Seeds must be between 1 and 16"}), 400

    # Use ML model if ready; resolve team names from region
    if _ml_model.ready and region in SAMPLE_TEAMS:
        team_a_name = SAMPLE_TEAMS[region].get(seed_a, f"#{seed_a} Seed")
        team_b_name = SAMPLE_TEAMS[region].get(seed_b, f"#{seed_b} Seed")
        return jsonify(get_ml_matchup_probability(
            _ml_model, team_a_name, team_b_name,
            seed_a, seed_b, round_num,
        ))
    return jsonify(get_matchup_probability(seed_a, seed_b, round_num))


@app.route("/api/team/<team_name>")
def team_rating(team_name):
    """Get ML analytics summary for a specific team."""
    if not _ml_model.ready:
        return jsonify({"error": "ML model not ready"}), 503
    rating = _ml_model.get_team_rating(team_name)
    if not rating:
        return jsonify({"error": "Team not found"}), 404
    return jsonify(rating)


@app.route("/api/model/status")
def model_status():
    """Check if the ML model is trained and ready."""
    return jsonify({
        "ready": _ml_model.ready,
        "model": "ml" if _ml_model.ready else "seed-based",
    })


@app.route("/api/model/refresh", methods=["POST"])
def model_refresh():
    """Re-fetch ESPN data and retrain the model."""
    global _ml_model
    try:
        data = fetch_all_team_analytics(force=True)
        _ml_model.train(data)
        return jsonify({"ok": True, "teams_with_stats": sum(1 for t in data.values() if t.get("stats"))})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/teams")
def get_teams():
    return jsonify(SAMPLE_TEAMS)


# --- Bracket Analysis ---

@app.route("/api/brackets/<int:bracket_id>/analyze")
def analyze_bracket_api(bracket_id):
    """Risk score & confidence report for a bracket."""
    bracket = get_bracket(bracket_id)
    if not bracket:
        return jsonify({"error": "Bracket not found"}), 404
    picks = json.loads(bracket["picks"])
    analysis = analyze_bracket(picks)
    analysis["bracket_name"] = bracket["name"]
    return jsonify(analysis)


@app.route("/api/brackets/<int:bracket_id>/health")
def bracket_health_api(bracket_id):
    """Live bracket health tracker."""
    bracket = get_bracket(bracket_id)
    if not bracket:
        return jsonify({"error": "Bracket not found"}), 404
    picks = json.loads(bracket["picks"])
    raw_results = get_all_results()
    # Transform flat list into nested dict for bracket_health
    results_dict = {"regions": {}, "final_four": {}}
    for r in raw_results:
        region = r["region"]
        rnd = str(r["round"])
        gi = str(r["game_index"])
        winner = r.get("winner")
        if region in ("Final Four", "Championship"):
            # Map to final_four structure
            if rnd == "5":
                key = f"semifinal_{int(gi) + 1}"
                results_dict["final_four"][key] = winner
            elif rnd == "6":
                results_dict["final_four"]["champion"] = winner
        else:
            if region not in results_dict["regions"]:
                results_dict["regions"][region] = {}
            if rnd not in results_dict["regions"][region]:
                results_dict["regions"][region][rnd] = {}
            results_dict["regions"][region][rnd][gi] = winner
    health = bracket_health(picks, results_dict)
    health["bracket_name"] = bracket["name"]
    return jsonify(health)


# --- Live Result Sync ---

_last_sync = {"time": None, "stats": None}

@app.route("/api/sync", methods=["POST"])
def trigger_sync():
    """Manually trigger an ESPN results sync."""
    from result_sync import sync_results
    stats = sync_results()
    _last_sync["time"] = time.time()
    _last_sync["stats"] = stats
    return jsonify(stats)


@app.route("/api/sync/status")
def sync_status():
    return jsonify({
        "last_sync": _last_sync["time"],
        "stats": _last_sync["stats"],
    })


def _background_sync_loop():
    """Background thread that syncs results from ESPN every 2 minutes."""
    while True:
        time.sleep(120)  # 2 minutes
        try:
            from result_sync import sync_results
            stats = sync_results()
            _last_sync["time"] = time.time()
            _last_sync["stats"] = stats
            if stats["updated"] > 0:
                print(f"[auto-sync] Updated {stats['updated']} game(s)")
        except Exception as e:
            print(f"[auto-sync] Error: {e}")


# Start background sync thread on import (works with gunicorn too)
sync_thread = threading.Thread(target=_background_sync_loop, daemon=True)
sync_thread.start()

if __name__ == "__main__":
    app.run(debug=True, port=5050, use_reloader=False)
