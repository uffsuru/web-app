from app import socketio

# The 'application' variable is what Gunicorn and other WSGI servers look for by default.
# We point it to our socketio object, which wraps the Flask app and handles real-time events.
application = socketio
