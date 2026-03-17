#!/bin/bash
# Azure App Service startup script
# /home/ is persistent storage on Azure App Service Linux

# Create persistent data directory
mkdir -p /home/data

# Set DB path to persistent storage
export DB_PATH=/home/data/madness.db

# Generate a stable secret key (persisted so sessions survive restarts)
if [ ! -f /home/data/.secret_key ]; then
    python -c "import secrets; print(secrets.token_hex(32))" > /home/data/.secret_key
fi
export SECRET_KEY=$(cat /home/data/.secret_key)

# Start gunicorn with 2 workers (B1 has 1.75GB RAM)
cd /home/site/wwwroot
gunicorn --bind=0.0.0.0:8000 --workers=2 --timeout=120 app:app
