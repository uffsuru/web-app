#!/usr/bin/env bash
# This script is run by Render on every new deployment.
# exit on error
set -o errexit

echo "Running database initializations..."
# Apply database migrations to bring the schema up to date
flask db upgrade

# Seed the database with sample data (optional, safe to run multiple times)
python seed.py

echo "Starting Gunicorn server..."
gunicorn --workers 3 --bind 0.0.0.0:$PORT --access-logfile - --error-logfile - --log-level info "wsgi:application"
