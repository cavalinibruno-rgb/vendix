from flask_socketio import join_room
from flask_login import current_user
from app.socket_instance import socketio


@socketio.on('connect')
def on_connect():
    if current_user.is_authenticated:
        join_room(f'tenant_{current_user.tenant_id}')
