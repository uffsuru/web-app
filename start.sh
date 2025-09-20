#!/usr/bin/env bash
# This script is run by Render on every new deployment.

echo "Running database initializations..."
python init_database.py
echo "Database initialization complete."

echo "Starting Gunicorn server..."
gunicorn --worker-class eventlet -w 1 app:socketio