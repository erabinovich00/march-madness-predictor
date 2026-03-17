#!/bin/bash
# Azure App Service startup script

# Create persistent data directory
mkdir -p /home/data

# Set DB path to persistent storage
export DB_PATH=/home/data/madness.db

# Generate a stable secret key (persisted so sessions survive restarts)
if [ ! -f /home/data/.secret_key ]; then
    python -c "import secrets; print(secrets.token_hex(32))" > /home/data/.secret_key
fi
export SECRET_KEY=$(cat /home/data/.secret_key)

cd /home/site/wwwroot

# Activate the Oryx virtual environment
if [ -d "antenv" ]; then
    source antenv/bin/activate
fi

# Start gunicorn
gunicorn --bind=0.0.0.0:8000 --workers=2 --timeout=120 app:app
