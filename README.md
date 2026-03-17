# March Madness 2026 Bracket Predictor

A full-featured web app for building, predicting, and competing on NCAA March Madness 2026 brackets. Features ML-powered predictions, multiplayer groups with leaderboards, live ESPN result syncing, and bracket analytics — all in a mobile-first dark UI.

## Features

- **Interactive bracket builder** — pick winners for all 63 games across 4 regions, Final Four, and Championship using the real 2026 field
- **ML-powered predictions** — a scikit-learn logistic regression model trained on historical seed data + live ESPN team analytics (55% historical / 45% analytics blend)
- **Classic prediction engine** — configurable chaos factor slider from "chalk" to "upset city"
- **Multiplayer groups** — create or join groups, set a bracket per group, and compete on leaderboards
- **Live ESPN sync** — automatic result syncing every 2 minutes from ESPN's scoreboard API
- **Bracket insights** — Risk Score & Confidence Report + Live Bracket Health Tracker showing how your picks are holding up
- **Read-only bracket viewer** — share and view any bracket without editing
- **User accounts** — sign up / log in with username & password, manage multiple brackets
- **Tournament lock** — brackets lock at tip-off (March 19, 2026 9:15 AM ET)
- **Mobile-first responsive design** — dark modern theme with 3 breakpoints optimized for iPhone

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the app
python app.py
```

Open [http://localhost:5050](http://localhost:5050) in your browser.

## Tech Stack

- **Backend:** Python 3.12+, Flask, SQLite, gunicorn
- **ML:** scikit-learn, numpy
- **Frontend:** Vanilla JS, CSS (dark theme with orange/cyan accents)
- **Data:** ESPN APIs for team stats and live scores
- **Hosting:** Azure App Service (B1 Linux)

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/predict` | POST | Generate bracket via classic engine. Body: `{"chaos_factor": 0.3}` |
| `/api/predict/ml` | POST | Generate bracket via ML model. Body: `{"chaos_factor": 0.3}` |
| `/api/matchup` | GET | Seed matchup probability. Params: `seed_a`, `seed_b`, `round` |
| `/api/brackets` | GET/POST | List or create brackets (authenticated) |
| `/api/brackets/<id>` | GET/PUT | Get or update a bracket |
| `/api/brackets/<id>/analyze` | GET | Bracket risk score & confidence report |
| `/api/brackets/<id>/health` | GET | Live bracket health vs actual results |
| `/api/groups` | GET/POST | List or create groups |
| `/api/groups/<id>/join` | POST | Join a group |
| `/api/groups/<id>/leaderboard` | GET | Group leaderboard with scores |
| `/api/results/sync` | POST | Manually trigger ESPN result sync |
| `/api/model/status` | GET | ML model training status |

## Project Structure

```
march-madness-predictor/
├── app.py                    # Flask server, all API routes, background sync
├── predictor.py              # Classic prediction engine (seed-based)
├── ml_predictor.py           # ML model (logistic regression + ESPN analytics)
├── bracket_analyzer.py       # Bracket risk score & health tracker
├── models.py                 # SQLite database layer (users, brackets, groups, results)
├── result_sync.py            # ESPN scoreboard sync logic
├── startup.sh                # Azure App Service startup script
├── data/
│   └── historical_data.py    # Historical win rates, seed strengths, 2026 teams
├── templates/
│   ├── index.html            # Main app (bracket builder, groups, insights)
│   └── auth.html             # Login / signup page
├── static/
│   ├── css/style.css         # Dark theme CSS with 3 responsive breakpoints
│   └── js/app.js             # Frontend logic (~1500 lines)
└── requirements.txt
```

## Scoring

| Round | Points per correct pick |
|---|---|
| Round of 64 | 1 |
| Round of 32 | 2 |
| Sweet 16 | 4 |
| Elite 8 | 8 |
| Final Four | 16 |
| Championship | 32 |
