import socketio
import eventlet
from flask import Flask
import logging
import threading
import time
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LANRelay")

# Initialize Socket.IO server
sio = socketio.Server(
    async_mode='eventlet',
    cors_allowed_origins='*',
    logger=True,
    engineio_logger=True
)
app = Flask(__name__)

# Store connected clients
clients = {}

# Add health check endpoint
@app.route('/ping')
def ping():
    """Health check endpoint for Render"""
    return "pong", 200

@app.route('/')
def home():
    """Root endpoint to prevent cold-start delays"""
    return "LAN Messenger Relay Server", 200

@sio.event
def connect(sid, environ):
    logger.info(f"Client connected: {sid}")

@sio.event
def register(sid, data):
    """Register user with unique ID"""
    user_id = data.get('user_id')
    username = data.get('username')
    if user_id:
        clients[user_id] = sid
        logger.info(f"Registered: {user_id} ({username})")
        return {"status": "success"}
    return {"status": "error"}

@sio.event
def text_message(sid, data):
    """Broadcast text message to all clients"""
    sio.emit('new_text', data, skip_sid=sid)
    logger.info(f"Broadcast text from {data.get('sender')}")

@sio.event
def voice_message(sid, data):
    """Broadcast voice message to all clients"""
    sio.emit('new_voice', data, skip_sid=sid)
    logger.info(f"Broadcast voice from {data.get('sender')}")

@sio.event
def disconnect(sid):
    """Handle client disconnect"""
    for user_id, client_sid in list(clients.items()):
        if client_sid == sid:
            del clients[user_id]
            logger.info(f"Client disconnected: {user_id}")
            break

def keep_alive():
    """Ping service to prevent Render spin-down"""
    while True:
        try:
            # Self-ping every 4 minutes
            if os.environ.get('RENDER'):
                import requests
                requests.get(f"https://{os.environ.get('RENDER_SERVICE_NAME')}.onrender.com/ping", timeout=5)
                logger.info("Keep-alive ping sent")
        except:
            pass
        time.sleep(240)  # 4 minutes

if __name__ == '__main__':
    # Start keep-alive thread in production
    if os.environ.get('RENDER'):
        threading.Thread(target=keep_alive, daemon=True).start()
    
    # Create Socket.IO app with explicit path
    app = socketio.WSGIApp(sio, app, socketio_path='socket.io')
    
    # Get port from environment or default
    port = int(os.environ.get('PORT', 10000))
    logger.info(f"Starting server on port {port}")
    
    # Start server
    eventlet.wsgi.server(eventlet.listen(('0.0.0.0', port)), app)
