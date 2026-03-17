# March Madness Bracket Predictor

A web app that predicts NCAA March Madness tournament brackets using historical seed data and probabilistic algorithms.

## Features

- **Full bracket generation** — simulates all 63 games across 4 regions, Final Four, and Championship
- **Upset factor slider** — adjust from "chalk" (favorites win) to "chaos" (upsets galore)
- **Seed matchup calculator** — check historical win probabilities for any seed vs seed matchup
- **Historical data engine** — predictions powered by real NCAA tournament results from 1985–2024

## How It Works

The prediction engine uses:

1. **Historical matchup probabilities** — real win rates for every seed combination (e.g., 1 vs 16 seeds: 99.3% favorite win rate)
2. **Logistic strength model** — for matchups without direct historical data, a logistic function models win probability based on seed strength ratings
3. **Round adjustment factors** — later rounds slightly increase upset probability since remaining teams are more evenly matched
4. **Configurable chaos factor** — slides probability toward 50/50 to simulate more unpredictable brackets

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the app
python app.py
```

Open [http://localhost:5000](http://localhost:5000) in your browser.

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/predict` | POST | Generate full bracket. Body: `{"chaos_factor": 0.3}` |
| `/api/matchup` | GET | Check seed matchup. Params: `seed_a`, `seed_b`, `round` |
| `/api/teams` | GET | Get default team pool |
| `/api/strength` | GET | Get seed strength ratings |

## Project Structure

```
march-madness-predictor/
├── app.py                    # Flask web server and API routes
├── predictor.py              # Prediction engine and bracket simulation
├── data/
│   └── historical_data.py    # Historical win rates and team data
├── templates/
│   └── index.html            # Main page template
├── static/
│   ├── css/style.css         # Styling
│   └── js/app.js             # Frontend logic
├── requirements.txt
└── README.md
```
