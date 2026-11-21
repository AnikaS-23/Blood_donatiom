"""
app/sockets/events.py
─────────────────────
Flask-SocketIO event handlers.
Clients join a room on connection so we can target pushes.
"""

from flask_socketio import emit, join_room, leave_room
from flask_login import current_user
from app import socketio


@socketio.on("connect")
def handle_connect():
    if current_user.is_authenticated and current_user.entity_id:
        room = f"{current_user.role}_{current_user.entity_id}"
        join_room(room)
        emit("connected", {"room": room})


@socketio.on("disconnect")
def handle_disconnect():
    pass  # Flask-SocketIO handles room cleanup automatically


@socketio.on("join_room")
def handle_join(data):
    """Allow explicit room joining (e.g. admin monitoring)."""
    room = data.get("room")
    if room:
        join_room(room)
        emit("joined", {"room": room})
