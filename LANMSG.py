import toga
from toga.style import Pack
from toga.style.pack import COLUMN, ROW
import socket
import threading
import wave
from datetime import datetime
from io import BytesIO
import pyaudio
import struct
import uuid
import platform
import socketio
import time

# ===== CONFIGURATION =====
# Replace with your Render service URL
RENDER_SERVICE_URL = "https://lan-messenger-relay.onrender.com"
# =========================

class NotificationWindow(toga.Window):
    def __init__(self, app, sender, message, on_reply=None):
        super().__init__(title=f"New message from {sender}", size=(300, 150))
        self.app = app
        self.on_reply = on_reply
        
        # Position in bottom-right corner
        screen_width = app.main_window.screen.width
        screen_height = app.main_window.screen.height
        self.position = (screen_width - 320, screen_height - 170)
        
        # Message content
        self.message_label = toga.Label(
            message[:100] + "..." if len(message) > 100 else message,
            style=Pack(padding=5, width=280)
        )
        
        # Reply input
        self.reply_input = toga.TextInput(
            placeholder="Type reply...",
            style=Pack(flex=1, padding=5)
        )
        
        # Buttons
        reply_btn = toga.Button(
            "Reply",
            on_press=self.send_reply,
            style=Pack(width=80, padding=5)
        )
        
        close_btn = toga.Button(
            "Close",
            on_press=self.close_notification,
            style=Pack(width=80, padding=5)
        )
        
        # Layout
        button_box = toga.Box(
            children=[reply_btn, close_btn],
            style=Pack(direction=ROW, padding_top=5)
        )
        
        self.content = toga.Box(
            children=[self.message_label, self.reply_input, button_box],
            style=Pack(direction=COLUMN, padding=10)
        )
        
        # Auto-close after 10 seconds
        self.close_timer = threading.Timer(10.0, self.close_notification)
        self.close_timer.start()
    
    def send_reply(self, widget):
        if self.on_reply and self.reply_input.value:
            self.on_reply(self.reply_input.value)
        self.close_notification()
    
    def close_notification(self, widget=None):
        if self.close_timer:
            self.close_timer.cancel()
        self.close()

class LANMessenger(toga.App):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "LAN Messenger"
        self.is_macos = platform.system() == 'Darwin'
        self.active_notifications = []
        self.internet_mode = False
        self.sio = None
        self.user_id = str(uuid.uuid4())[:8]  # Short unique ID
        self.voice_messages = {}
        self.connections = []
        self.relay_connected = False

    def startup(self):
        # Audio setup
        self.audio = pyaudio.PyAudio()
        self.is_recording = False
        self.frames = []
        self.stream = None
        self.sample_rate = 16000
        
        # Network setup
        self.host = self.get_local_ip()
        self.port = 12345
        self.client_socket = None
        self.server_socket = None
        self.username = f"User{hash(self.host) % 1000}"
        self.admin_mode = False
        
        # Main layout
        self.main_window = toga.MainWindow(title=self.name, size=(800, 600))
        
        # Chat area
        self.chat_display = toga.MultilineTextInput(
            readonly=True,
            style=Pack(flex=1, margin=5)
        )
        
        # Input area
        self.message_input = toga.TextInput(
            placeholder="Type your message...",
            style=Pack(flex=1, margin=5)
        )
        
        # Buttons
        self.record_btn = toga.Button(
            "🎤 Record",
            on_press=self.toggle_recording,
            style=Pack(width=100, margin=5)
        )
        
        send_btn = toga.Button(
            "Send",
            on_press=self.send_text_message,
            style=Pack(width=100, margin=5)
        )
        
        clear_btn = toga.Button(
            "Clear",
            on_press=self.clear_chat,
            style=Pack(width=100, margin=5)
        )
        
        # Internet mode toggle
        self.mode_label = toga.Label(
            "Mode: LAN",
            style=Pack(color="green", font_weight="bold", margin=5)
        )
        
        self.mode_btn = toga.Button(
            "Switch to Internet Mode",
            on_press=self.toggle_internet_mode,
            style=Pack(background_color="#e0e0ff", padding=5)
        )
        
        # Connection status
        self.status_label = toga.Label(
            "Relay: Disconnected",
            style=Pack(color="gray", margin=5)
        )
        
        # Layout
        input_box = toga.Box(
            children=[
                self.message_input,
                self.record_btn,
                send_btn,
                clear_btn
            ],
            style=Pack(direction=ROW, margin=5)
        )
        
        mode_box = toga.Box(
            children=[self.mode_label, self.mode_btn],
            style=Pack(direction=ROW, padding=5)
        )
        
        info_box = toga.Box(
            children=[
                toga.Label(
                    f"Your IP: {self.host} | Port: {self.port} | ID: {self.user_id}",
                    style=Pack(margin=5)
                ),
                self.status_label
            ],
            style=Pack(direction=COLUMN)
        )
        
        main_box = toga.Box(
            children=[
                self.chat_display,
                input_box,
                info_box,
                mode_box
            ],
            style=Pack(direction=COLUMN)
        )
        
        # Menu commands
        self.commands.add(
            toga.Command(
                self.show_connect_dialog,
                text="Connect to Host...",
                shortcut="cmd+c" if self.is_macos else "ctrl+c"
            ),
            toga.Command(
                self.toggle_admin_mode,
                text="Toggle Admin Mode",
                shortcut="cmd+a" if self.is_macos else "ctrl+a"
            ),
            toga.Command(
                self.kick_user,
                text="Kick User",
                enabled=False
            ),
            toga.Command(
                self.admin_broadcast,
                text="Broadcast Message",
                enabled=False
            )
        )
        
        self.main_window.content = main_box
        self.main_window.show()
        self.start_server()
    
    def show_notification(self, sender, message):
        """Show Telegram-style notification popup"""
        # Close any existing notification
        for notification in self.active_notifications:
            notification.close()
        self.active_notifications.clear()
        
        # Create and show new notification
        notification = NotificationWindow(
            self,
            sender,
            message,
            on_reply=self.send_text_message
        )
        notification.show()
        self.active_notifications.append(notification)
        
        # Bring main window to front if notification is clicked
        notification.on_activate = self.main_window.activate
    
    def get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"
    
    def toggle_internet_mode(self, widget):
        """Switch between LAN and Internet relay modes"""
        self.internet_mode = not self.internet_mode
        
        if self.internet_mode:
            self.mode_label.text = "Mode: INTERNET"
            self.mode_label.style.color = "red"
            self.mode_btn.text = "Switch to LAN Mode"
            self.mode_btn.style.background_color = "#ffe0e0"
            self.connect_to_relay()
        else:
            self.mode_label.text = "Mode: LAN"
            self.mode_label.style.color = "green"
            self.mode_btn.text = "Switch to Internet Mode"
            self.mode_btn.style.background_color = "#e0e0ff"
            self.disconnect_from_relay()
            
        self.display_message("System", 
            f"Switched to {'INTERNET' if self.internet_mode else 'LAN'} mode")
    
    def connect_to_relay(self):
        """Connect to the Render relay server"""
        try:
            # Close any existing connection
            if self.sio:
                self.sio.disconnect()
            
            # Create new connection
            self.sio = socketio.Client(reconnection_attempts=5, reconnection_delay=2)
            
            # Setup event handlers
            @self.sio.event
            def connect():
                self.relay_connected = True
                self.status_label.text = "Relay: Connected"
                self.status_label.style.color = "green"
                self.display_message("System", "Connected to relay server")
                
                # Register with the server
                self.sio.emit('register', {
                    'user_id': self.user_id,
                    'username': self.username
                })
            
            @self.sio.event
            def disconnect():
                self.relay_connected = False
                self.status_label.text = "Relay: Disconnected"
                self.status_label.style.color = "red"
                self.display_message("System", "Disconnected from relay server")
            
            @self.sio.on('new_text')
            def handle_text(data):
                sender = data.get('sender', 'Unknown')
                message = data.get('message', '')
                self.display_message(sender, message)
            
            @self.sio.on('new_voice')
            def handle_voice(data):
                msg_id = data.get('msg_id', str(uuid.uuid4()))
                audio_data = data.get('audio_data', '').encode('latin1')
                self.voice_messages[msg_id] = audio_data
                sender = data.get('sender', 'Unknown')
                self.display_message(sender, "Voice message received (click to play)")
            
            # Connection error handler
            @self.sio.event
            def connect_error(data):
                self.status_label.text = "Relay: Connection failed"
                self.status_label.style.color = "orange"
                self.display_message("System", f"Relay connection failed: {str(data)}")
            
            # Reconnect handler
            @self.sio.event
            def reconnect():
                self.status_label.text = "Relay: Reconnected"
                self.status_label.style.color = "green"
                self.display_message("System", "Reconnected to relay server")
                self.sio.emit('register', {
                    'user_id': self.user_id,
                    'username': self.username
                })
            
            # Connect to server
            self.sio.connect(
                RENDER_SERVICE_URL,
                transports=['websocket'],
                namespaces=['/']
            )
            
        except Exception as e:
            self.status_label.text = "Relay: Connection error"
            self.status_label.style.color = "red"
            self.display_message("System", f"Relay connection error: {str(e)}")
    
    def disconnect_from_relay(self):
        """Disconnect from the relay server"""
        if self.sio:
            try:
                self.sio.disconnect()
            except:
                pass
            self.sio = None
            self.relay_connected = False
            self.status_label.text = "Relay: Disconnected"
            self.status_label.style.color = "gray"
            self.display_message("System", "Disconnected from relay server")
    
    def send_via_relay(self, message_type, payload):
        """Send a message through the relay server"""
        if not self.sio or not self.relay_connected:
            self.display_message("System", "Not connected to relay")
            return False
            
        try:
            payload['sender'] = self.username
            self.sio.emit(message_type, payload)
            return True
        except Exception as e:
            self.display_message("System", f"Relay send error: {str(e)}")
            return False
    
    def show_connect_dialog(self, widget):
        self.connect_dialog = toga.Window(title="Connect to Host", size=(300, 150))
        
        ip_input = toga.TextInput(placeholder="Enter host IP")
        connect_btn = toga.Button(
            "Connect",
            on_press=lambda widget: self.connect_to_host(ip_input.value),
            style=Pack(padding=5)
        )
        cancel_btn = toga.Button(
            "Cancel",
            on_press=lambda widget: self.connect_dialog.close(),
            style=Pack(padding=5)
        )
        
        box = toga.Box(
            children=[
                toga.Label("Enter host IP:"),
                ip_input,
                toga.Box(
                    children=[connect_btn, cancel_btn],
                    style=Pack(direction=ROW, padding_top=10)
                )
            ],
            style=Pack(direction=COLUMN, padding=10)
        )
        
        self.connect_dialog.content = box
        self.connect_dialog.show()
    
    def connect_to_host(self, host):
        if self.internet_mode:
            self.display_message("System", "Cannot connect directly in Internet mode")
            return
            
        if host and host != "False":
            try:
                self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.client_socket.connect((host, self.port))
                self.connections.append(self.client_socket)
                threading.Thread(
                    target=self.handle_client,
                    args=(self.client_socket,),
                    daemon=True
                ).start()
                self.display_message("System", f"Connected to {host}")
                self.connect_dialog.close()
            except Exception as e:
                self.display_message("System", f"Connection failed: {str(e)}")
    
    def start_server(self):
        if self.internet_mode:
            return  # No local server in internet mode
            
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            threading.Thread(target=self.accept_connections, daemon=True).start()
            self.display_message("System", f"Server started on {self.host}:{self.port}")
        except Exception as e:
            self.display_message("System", f"Error starting server: {str(e)}")
    
    def accept_connections(self):
        if self.internet_mode:
            return  # No direct connections in internet mode
            
        while True:
            try:
                conn, addr = self.server_socket.accept()
                self.connections.append(conn)
                threading.Thread(target=self.handle_client, args=(conn,), daemon=True).start()
                self.display_message("System", f"Connection from {addr[0]}")
            except Exception as e:
                self.display_message("System", f"Connection error: {str(e)}")
                break
    
    def handle_client(self, conn):
        while True:
            try:
                msg_type = conn.recv(1)
                if not msg_type:
                    break
                    
                if msg_type == b'T':
                    length_bytes = conn.recv(4)
                    if not length_bytes:
                        break
                    length = struct.unpack('>I', length_bytes)[0]
                    
                    data = b''
                    while len(data) < length:
                        packet = conn.recv(min(4096, length - len(data)))
                        if not packet:
                            break
                        data += packet
                        
                    self.display_message("Friend", data.decode('utf-8'))
                    
                elif msg_type == b'V':
                    id_length_bytes = conn.recv(4)
                    if not id_length_bytes:
                        break
                    id_length = struct.unpack('>I', id_length_bytes)[0]
                    
                    msg_id = conn.recv(id_length).decode('utf-8')
                    
                    audio_length_bytes = conn.recv(4)
                    if not audio_length_bytes:
                        break
                    audio_length = struct.unpack('>I', audio_length_bytes)[0]
                    
                    audio_data = b''
                    while len(audio_data) < audio_length:
                        packet = conn.recv(min(4096, audio_length - len(audio_data)))
                        if not packet:
                            break
                        audio_data += packet
                    
                    self.voice_messages[msg_id] = audio_data
                    self.display_message("Friend", "Voice message received (click to play)")
                    
            except Exception as e:
                self.display_message("System", f"Error handling message: {str(e)}")
                break
                
        try:
            conn.close()
            if conn in self.connections:
                self.connections.remove(conn)
            self.display_message("System", "Client disconnected")
        except:
            pass
    
    def display_message(self, sender, message):
        timestamp = datetime.now().strftime("%H:%M")
        current_text = self.chat_display.value
        self.chat_display.value = f"{current_text}[{timestamp}] {sender}: {message}\n"
        
        # Show notification only for incoming messages
        if sender not in ["You", "System", "Admin"]:
            self.show_notification(sender, message)
    
    def send_text_message(self, widget=None, text=None):
        message = text if text else self.message_input.value.strip()
        if not message:
            return
            
        if not text:  # Clear only if coming from main UI
            self.message_input.value = ''
            
        full_message = f"[{datetime.now().strftime('%H:%M')}] {self.username}: {message}"
        
        if self.internet_mode:
            # Send via relay server
            if self.send_via_relay("text_message", {"message": full_message}):
                self.display_message("You", message)
        else:
            # Send directly to LAN peers
            self.display_message("You", message)
            self.send_text_data(full_message)
        
    def send_text_data(self, text):
        try:
            data = text.encode('utf-8')
            message = b'T' + struct.pack('>I', len(data)) + data
            
            for conn in self.connections[:]:
                try:
                    conn.sendall(message)
                except:
                    self.connections.remove(conn)
        except Exception as e:
            self.display_message("System", f"Send error: {str(e)}")
    
    def send_voice_data(self, audio_data):
        try:
            msg_id = str(uuid.uuid4())
            
            if self.internet_mode:
                # Send via relay (convert to latin1 for JSON)
                audio_str = audio_data.decode('latin1')
                if self.send_via_relay("voice_message", {
                    "msg_id": msg_id,
                    "audio_data": audio_str
                }):
                    self.voice_messages[msg_id] = audio_data
                    self.display_message("System", "Voice message sent via relay")
            else:
                # Send directly to LAN peers
                id_bytes = msg_id.encode('utf-8')
                
                message = b'V' 
                message += struct.pack('>I', len(id_bytes))
                message += id_bytes
                message += struct.pack('>I', len(audio_data))
                message += audio_data
                
                for conn in self.connections[:]:
                    try:
                        total_sent = 0
                        while total_sent < len(message):
                            sent = conn.send(message[total_sent:total_sent+4096])
                            if sent == 0:
                                raise RuntimeError("Socket connection broken")
                            total_sent += sent
                        
                        self.voice_messages[msg_id] = audio_data
                        self.display_message("System", "Voice message sent")
                    except Exception as e:
                        self.display_message("System", f"Voice send failed: {str(e)}")
                        self.connections.remove(conn)
        except Exception as e:
            self.display_message("System", f"Send error: {str(e)}")
    
    def toggle_recording(self, widget):
        if not self.is_recording:
            self.is_recording = True
            self.frames = []
            self.record_btn.text = "⏹ Stop"
            self.stream = self.audio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=512,
                stream_callback=self.audio_callback
            )
            self.display_message("System", "Recording started...")
        else:
            self.is_recording = False
            self.record_btn.text = "🎤 Record"
            if self.stream:
                self.stream.stop_stream()
                self.stream.close()
                self.stream = None
            self.display_message("System", "Recording stopped")
            
            audio_data = self.save_audio()
            if audio_data:
                self.display_message("System", "Sending voice message...")
                threading.Thread(target=lambda: self.send_voice_data(audio_data), daemon=True).start()
    
    def audio_callback(self, in_data, frame_count, time_info, status):
        if self.is_recording:
            self.frames.append(in_data)
        return (in_data, pyaudio.paContinue)
    
    def save_audio(self):
        try:
            if not self.frames:
                self.display_message("System", "No audio recorded")
                return None
                
            buffer = BytesIO()
            with wave.open(buffer, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(self.audio.get_sample_size(pyaudio.paInt16))
                wf.setframerate(self.sample_rate)
                wf.writeframes(b''.join(self.frames))
            return buffer.getvalue()
        except Exception as e:
            self.display_message("System", f"Error saving audio: {str(e)}")
            return None
    
    def play_voice_message(self, msg_id):
        if msg_id in self.voice_messages:
            audio_data = self.voice_messages[msg_id]
            threading.Thread(target=self.play_audio, args=(audio_data,), daemon=True).start()
        else:
            self.display_message("System", "Voice message not found")
    
    def play_audio(self, audio_data):
        try:
            if not audio_data:
                self.display_message("System", "No audio data")
                return
                
            with wave.open(BytesIO(audio_data)) as wf:
                p = pyaudio.PyAudio()
                stream = p.open(
                    format=p.get_format_from_width(wf.getsampwidth()),
                    channels=wf.getnchannels(),
                    rate=wf.getframerate(),
                    output=True
                )
                
                chunk_size = 1024
                data = wf.readframes(chunk_size)
                while data:
                    stream.write(data)
                    data = wf.readframes(chunk_size)
                
                stream.stop_stream()
                stream.close()
                p.terminate()
                
            self.display_message("System", "Voice message played")
        except Exception as e:
            self.display_message("System", f"Playback error: {str(e)}")
    
    def clear_chat(self, widget):
        self.chat_display.value = ""
    
    def toggle_admin_mode(self, widget):
        self.admin_mode = not self.admin_mode
        state = self.admin_mode
        for cmd in self.commands:
            if cmd.text in ["Kick User", "Broadcast Message"]:
                cmd.enabled = state
        self.display_message("System", f"Admin mode {'activated' if state else 'deactivated'}")
    
    def kick_user(self, widget):
        if not self.admin_mode:
            return
            
        ip_list = []
        for conn in self.connections:
            try:
                ip_list.append(conn.getpeername()[0])
            except:
                continue
        
        if not ip_list:
            self.display_message("Admin", "No connected users")
            return
            
        self.kick_dialog = toga.Window(title="Kick User", size=(300, 200))
        
        box = toga.Box(style=Pack(direction=COLUMN, padding=10))
        box.add(toga.Label("Select user to kick:"))
        
        for ip in ip_list:
            btn = toga.Button(
                ip,
                on_press=lambda widget, ip=ip: self.perform_kick(ip),
                style=Pack(padding=5)
            )
            box.add(btn)
        
        self.kick_dialog.content = box
        self.kick_dialog.show()
    
    def perform_kick(self, ip):
        if ip and ip != "False":
            for conn in self.connections[:]:
                try:
                    if conn.getpeername()[0] == ip:
                        conn.close()
                        self.connections.remove(conn)
                        self.display_message("Admin", f"Kicked {ip}")
                        self.kick_dialog.close()
                except:
                    continue
    
    def admin_broadcast(self, widget):
        if not self.admin_mode:
            return
            
        self.broadcast_dialog = toga.Window(title="Broadcast Message", size=(300, 150))
        
        message_input = toga.TextInput(placeholder="Enter broadcast message")
        send_btn = toga.Button(
            "Send",
            on_press=lambda widget: self.send_broadcast(message_input.value),
            style=Pack(padding=5)
        )
        cancel_btn = toga.Button(
            "Cancel",
            on_press=lambda widget: self.broadcast_dialog.close(),
            style=Pack(padding=5)
        )
        
        box = toga.Box(
            children=[
                toga.Label("Enter broadcast message:"),
                message_input,
                toga.Box(
                    children=[send_btn, cancel_btn],
                    style=Pack(direction=ROW, padding_top=10)
                )
            ],
            style=Pack(direction=COLUMN, padding=10)
        )
        
        self.broadcast_dialog.content = box
        self.broadcast_dialog.show()
    
    def send_broadcast(self, message):
        if message and message != "False":
            full_message = f"[ADMIN BROADCAST] {message}"
            self.send_text_data(full_message)
            self.display_message("Admin", f"Broadcast: {message}")
            self.broadcast_dialog.close()

def main():
    return LANMessenger(
        formal_name="LAN Messenger",
        app_id="org.beeware.lanmessenger",
        app_name="lanmessenger"
    )

if __name__ == "__main__":
    app = main()
    app.main_loop()