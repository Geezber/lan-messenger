import socketio
from flask import Flask

sio = socketio.Server(async_mode='eventlet', cors_allowed_origins='*')
app = Flask(__name__)

# Store connected clients
clients = {}

@sio.event
def connect(sid, environ):
    print(f"Client connected: {sid}")

@sio.event
def register(sid, data):
    """Register user with unique ID"""
    user_id = data.get('user_id')
    username = data.get('username')
    if user_id:
        clients[user_id] = sid
        print(f"Registered: {user_id} ({username})")
        return {"status": "success"}
    return {"status": "error"}

@sio.event
def text_message(sid, data):
    """Broadcast text message to all clients"""
    sio.emit('new_text', data, skip_sid=sid)
    print(f"Broadcast text from {data.get('sender')}")

@sio.event
def voice_message(sid, data):
    """Broadcast voice message to all clients"""
    sio.emit('new_voice', data, skip_sid=sid)
    print(f"Broadcast voice from {data.get('sender')}")

@sio.event
def disconnect(sid):
    """Handle client disconnect"""
    for user_id, client_sid in list(clients.items()):
        if client_sid == sid:
            del clients[user_id]
            print(f"Client disconnected: {user_id}")
            break

if __name__ == '__main__':
    import eventlet
    eventlet.wsgi.server(eventlet.listen(('', 10000)), app)