#!/usr/bin/env bash
# This script is run by Render on every new deployment.
# exit on error
set -o errexit

echo "Running database initializations..."
python init_database.py
echo "Database initialization complete."

echo "Starting Gunicorn server..."
gunicorn --worker-class eventlet -w 1 app:socketio