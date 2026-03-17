"""
Historical March Madness data and seed-based statistics.
Based on real NCAA tournament historical upset rates and seed performance.
"""

# Historical win rates by seed (1-16) through Round of 64, based on real tournament data
# Format: seed -> overall tournament win percentage in Round of 64
SEED_WIN_RATES_ROUND_OF_64 = {
    1: 0.993,  # 1 seeds almost never lose to 16 seeds
    2: 0.943,
    3: 0.855,
    4: 0.793,
    5: 0.643,
    6: 0.625,
    7: 0.607,
    8: 0.500,
    9: 0.500,
    10: 0.393,
    11: 0.375,
    12: 0.357,
    13: 0.207,
    14: 0.145,
    15: 0.057,
    16: 0.007,
}

# Historical matchup data: (higher_seed, lower_seed) -> higher_seed_win_rate
# Based on actual NCAA tournament results from 1985-2024
HISTORICAL_MATCHUPS = {
    (1, 16): 0.993,
    (2, 15): 0.943,
    (3, 14): 0.855,
    (4, 13): 0.793,
    (5, 12): 0.643,
    (6, 11): 0.625,
    (7, 10): 0.607,
    (8, 9): 0.500,
    (1, 8): 0.800,
    (1, 9): 0.830,
    (2, 7): 0.710,
    (2, 10): 0.750,
    (3, 6): 0.580,
    (3, 11): 0.650,
    (4, 5): 0.550,
    (4, 12): 0.700,
    (1, 4): 0.720,
    (1, 5): 0.780,
    (2, 3): 0.560,
    (2, 6): 0.660,
    (1, 2): 0.550,
    (1, 3): 0.620,
}

# Typical team strength ratings by seed (0-100 scale, approximate KenPom-style)
SEED_STRENGTH = {
    1: 95,
    2: 90,
    3: 85,
    4: 80,
    5: 75,
    6: 72,
    7: 69,
    8: 66,
    9: 64,
    10: 62,
    11: 60,
    12: 58,
    13: 52,
    14: 48,
    15: 42,
    16: 35,
}

# Round multipliers for upset likelihood (upsets become more likely in later rounds
# as remaining teams are more evenly matched)
ROUND_UPSET_FACTOR = {
    1: 1.0,   # Round of 64
    2: 1.05,  # Round of 32
    3: 1.10,  # Sweet 16
    4: 1.15,  # Elite 8
    5: 1.20,  # Final Four
    6: 1.25,  # Championship
}

# 2026 NCAA Tournament teams by region and seed (from official bracket)
# First Four winners are represented by the higher-seeded team as placeholder
SAMPLE_TEAMS = {
    "East": {
        1: "Duke", 2: "UConn", 3: "Michigan St", 4: "Kansas",
        5: "St. John's", 6: "Louisville", 7: "UCLA", 8: "Ohio State",
        9: "TCU", 10: "UCF", 11: "South Florida", 12: "Northern Iowa",
        13: "CA Baptist", 14: "N Dakota St", 15: "Furman", 16: "Siena",
    },
    "South": {
        1: "Florida", 2: "Houston", 3: "Illinois", 4: "Nebraska",
        5: "Vanderbilt", 6: "North Carolina", 7: "Saint Mary's", 8: "Clemson",
        9: "Iowa", 10: "Texas A&M", 11: "VCU", 12: "McNeese",
        13: "Troy", 14: "Penn", 15: "Idaho", 16: "Lehigh",
    },
    "West": {
        1: "Arizona", 2: "Purdue", 3: "Gonzaga", 4: "Arkansas",
        5: "Wisconsin", 6: "BYU", 7: "Miami (FL)", 8: "Villanova",
        9: "Utah State", 10: "Missouri", 11: "Texas", 12: "High Point",
        13: "Hawai'i", 14: "Kennesaw St", 15: "Queens", 16: "LIU",
    },
    "Midwest": {
        1: "Michigan", 2: "Iowa State", 3: "Virginia", 4: "Alabama",
        5: "Texas Tech", 6: "Tennessee", 7: "Kentucky", 8: "Georgia",
        9: "Saint Louis", 10: "Santa Clara", 11: "SMU", 12: "Akron",
        13: "Hofstra", 14: "Wright State", 15: "Tennessee St", 16: "Howard",
    }
}

# Historical Final Four appearance rates by seed
FINAL_FOUR_RATES = {
    1: 0.42,
    2: 0.17,
    3: 0.10,
    4: 0.06,
    5: 0.04,
    6: 0.03,
    7: 0.02,
    8: 0.03,
    9: 0.01,
    10: 0.02,
    11: 0.04,
    12: 0.01,
    13: 0.00,
    14: 0.00,
    15: 0.00,
    16: 0.00,
}

# Championship win rates by seed
CHAMPIONSHIP_RATES = {
    1: 0.58,
    2: 0.17,
    3: 0.10,
    4: 0.04,
    5: 0.02,
    6: 0.02,
    7: 0.02,
    8: 0.03,
    9: 0.00,
    10: 0.00,
    11: 0.01,
    12: 0.00,
    13: 0.00,
    14: 0.00,
    15: 0.00,
    16: 0.00,
}
