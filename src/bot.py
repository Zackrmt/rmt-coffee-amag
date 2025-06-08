import os
import sys
import logging
import asyncio
import datetime
import threading
import time
import signal
import atexit
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, Optional, Set
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters
)

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log')
    ]
)
logger = logging.getLogger(__name__)

# Reduce HTTP request logging verbosity
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telegram.request').setLevel(logging.WARNING)

# Timezone configurations
PST_TZ = pytz.timezone('America/Los_Angeles')
MANILA_TZ = pytz.timezone('Asia/Manila')

# Current date and user information
CURRENT_DATE = "2025-06-08"
CURRENT_USER = "Zackrmt"

# Process ID file for single instance check
PID_FILE = "/tmp/rmt_study_bot.pid"

# Shared state
class SharedState:
    def __init__(self):
        self.is_shutting_down = False
        self.telegram_bot = None

# Create shared state object
shared_state = SharedState()

# Conversation states
(
    CHOOSING_MAIN_MENU,
    SETTING_GOAL,
    CHOOSING_SUBJECT,
    STUDYING,
    ON_BREAK,
    SETTING_CUSTOM_GOAL,
    CONFIRMING_CANCEL,
) = range(7)

# Subject mapping
SUBJECTS = {
    "CC 🧪": "CC",
    "BACTE 🦠": "BACTE",
    "VIRO 👾": "VIRO",
    "MYCO 🍄": "MYCO",
    "PARA 🪱": "PARA",
    "CM 🚽💩": "CM",
    "HISTO 🧻🗳️": "HISTO",
    "MT Laws ⚖️": "MT_LAWS",
    "HEMA 🩸": "HEMA",
    "IS ⚛": "IS",
    "BB 🩹": "BB",
    "MolBio 🧬": "MOLBIO",
    "Autopsy ☠": "AUTOPSY",
    "General Books 📚": "GB",
    "RECALLS 🤔💭": "RECALLS",
    "ANKI 🎟️": "ANKI",
    "Others🤓": "OTHERS"
}

# ================== SINGLE INSTANCE CHECK ==================
def ensure_single_instance():
    """Ensure only one instance of the bot is running."""
    try:
        # Check if PID file exists
        if os.path.exists(PID_FILE):
            with open(PID_FILE, 'r') as f:
                old_pid = int(f.read().strip())
            
            # Check if process with this PID exists and it's our script
            try:
                # Send signal 0 to check if process exists without actually sending a signal
                os.kill(old_pid, 0)
                
                # Process exists, let's check if it's a Python process (very rough check)
                # This might not work on all platforms but good enough for Render
                import psutil
                if psutil.pid_exists(old_pid):
                    proc = psutil.Process(old_pid)
                    if 'python' in proc.name().lower() or 'python' in ' '.join(proc.cmdline()).lower():
                        logger.warning(f"Another instance is already running with PID {old_pid}. Exiting.")
                        sys.exit(1)
            except OSError:
                # Process doesn't exist
                logger.info(f"Stale PID file found. Previous instance (PID {old_pid}) is not running.")
        
        # Write our PID to the file
        with open(PID_FILE, 'w') as f:
            f.write(str(os.getpid()))
        logger.info(f"PID {os.getpid()} written to {PID_FILE}")
        
        # Register cleanup to remove PID file on exit
        def cleanup_pid_file():
            try:
                if os.path.exists(PID_FILE):
                    os.remove(PID_FILE)
                    logger.info(f"Removed PID file {PID_FILE}")
            except Exception as e:
                logger.error(f"Error removing PID file: {e}")
        
        atexit.register(cleanup_pid_file)
        
    except Exception as e:
        logger.error(f"Error checking/creating PID file: {e}")

# ================== RESOURCE MONITOR ==================
class ResourceMonitor:
    @staticmethod
    def get_status():
        try:
            import psutil
            return {
                "cpu": psutil.cpu_percent(),
                "memory": psutil.virtual_memory().percent,
                "boot_time": datetime.datetime.fromtimestamp(psutil.boot_time()).isoformat(),
                "process_uptime": time.time() - psutil.Process().create_time(),
                "threads": threading.active_count()
            }
        except Exception as e:
            logger.error(f"Resource monitoring error: {e}")
            return {
                "cpu": "N/A",
                "memory": "N/A",
                "boot_time": "N/A",
                "process_uptime": "N/A",
                "threads": "N/A"
            }

# ================== KEEPALIVE SERVER ==================
class KeepaliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health' or self.path == '/':  # Add root path for UptimeRobot
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'OK')
        elif self.path == '/ping':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(f"pong {datetime.datetime.now().isoformat()}".encode())
        elif self.path == '/status':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            resources = ResourceMonitor.get_status()
            
            # Handle case where telegram_bot might not be initialized yet
            active_sessions = 0
            pending_sessions = 0
            last_activity_time = datetime.datetime.now()
            
            if shared_state.telegram_bot:
                active_sessions = len(shared_state.telegram_bot.study_sessions)
                pending_sessions = len(shared_state.telegram_bot.pending_sessions)
                last_activity_time = shared_state.telegram_bot.last_activity
            
            status = "Running" if not shared_state.is_shutting_down else "Shutting Down"
            status_class = "good" if not shared_state.is_shutting_down else "warning"
            
            status_html = f"""
            <html>
                <head>
                    <title>RMT Study Bot Status</title>
                    <meta http-equiv="refresh" content="60">
                    <style>
                        body {{ font-family: Arial, sans-serif; margin: 20px; }}
                        h1 {{ color: #2c3e50; }}
                        .status-box {{ 
                            border: 1px solid #ddd; 
                            padding: 15px; 
                            margin-bottom: 20px; 
                            border-radius: 5px;
                            background-color: #f9f9f9;
                        }}
                        .metric {{ margin-bottom: 10px; }}
                        .metric-name {{ font-weight: bold; }}
                        .session-list {{ margin-top: 20px; }}
                        .good {{ color: green; }}
                        .warning {{ color: orange; }}
                        .bad {{ color: red; }}
                    </style>
                </head>
                <body>
                    <h1>📚 RMT Study Bot Status</h1>
                    <div class="status-box">
                        <h2>System Health</h2>
                        <div class="metric">
                            <span class="metric-name">Status:</span> 
                            <span class="{status_class}">{status}</span>
                        </div>
                        <div class="metric">
                            <span class="metric-name">Last Activity:</span> 
                            {last_activity_time.strftime('%Y-%m-%d %H:%M:%S')}
                        </div>
                        <div class="metric">
                            <span class="metric-name">Active Sessions:</span> 
                            {active_sessions}
                        </div>
                        <div class="metric">
                            <span class="metric-name">Pending Sessions:</span> 
                            {pending_sessions}
                        </div>
                        <div class="metric">
                            <span class="metric-name">CPU Usage:</span> 
                            {resources['cpu']}%
                        </div>
                        <div class="metric">
                            <span class="metric-name">Memory Usage:</span> 
                            {resources['memory']}%
                        </div>
                        <div class="metric">
                            <span class="metric-name">System Uptime:</span> 
                            {resources['boot_time']}
                        </div>
                        <div class="metric">
                            <span class="metric-name">Process Uptime:</span> 
                            {int(resources['process_uptime'])} seconds
                        </div>
                        <div class="metric">
                            <span class="metric-name">Process ID:</span> 
                            {os.getpid()}
                        </div>
                        <div class="metric">
                            <span class="metric-name">Active Threads:</span> 
                            {resources['threads']}
                        </div>
                        <div class="metric">
                            <span class="metric-name">Current Date and Time:</span> 
                            {datetime.datetime.now(MANILA_TZ).strftime('%Y-%m-%d %H:%M:%S %Z')}
                        </div>
                        <div class="metric">
                            <span class="metric-name">User:</span> 
                            {CURRENT_USER}
                        </div>
                        <div class="metric">
                            <span class="metric-name">Environment:</span> 
                            {'Production' if os.getenv('RENDER') else 'Development'}
                        </div>
                    </div>
                </body>
            </html>
            """
            self.wfile.write(status_html.encode())
        elif self.path == '/shutdown':
            # Security: In a real production app, you would add authentication here
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Shutting down...')
            
            # Initiate shutdown
            shared_state.is_shutting_down = True
            threading.Thread(target=self.shutdown_application).start()
        else:
            self.send_response(404)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Not Found')

    def shutdown_application(self):
        """Shut down the application gracefully."""
        time.sleep(1)  # Give the response time to complete
        os.kill(os.getpid(), signal.SIGTERM)

    # Override all methods to handle UptimeRobot requests
    def do_HEAD(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        
    def do_POST(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'OK')
        
    def do_PUT(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'OK')
        
    def do_DELETE(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'OK')

    def log_message(self, format, *args):
        if args[0].startswith(('GET /health', 'GET /ping', 'GET / HTTP')):
            return  # Don't log health check requests
        logger.info("%s - - [%s] %s" % (self.client_address[0], self.log_date_time_string(), format % args))

class KeepaliveServer:
    def __init__(self):
        self.server = None
        self.thread = None
        
    def start(self):
        """Start the health check server in a separate thread."""
        # Use HEALTH_CHECK_PORT if available, otherwise fall back to PORT, then to default 10001
        port = int(os.getenv('HEALTH_CHECK_PORT', os.getenv('PORT', 10001)))
        self.server = HTTPServer(('0.0.0.0', port), KeepaliveHandler)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()
        logger.info(f"Keepalive server started on port {port}")
        
    def stop(self):
        """Stop the server gracefully."""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            logger.info("Keepalive server stopped")

# ================== STUDY SESSION CLASS ==================
class StudySession:
    def __init__(self, user_id: int, subject: str, goal_time: Optional[str] = None):
        self.user_id = user_id
        self.subject = subject
        self.goal_time = goal_time
        self.start_time = datetime.datetime.now(PST_TZ)
        self.end_time = None
        self.break_periods = []
        self.break_start = None
        self.is_on_break = False

    def start_break(self):
        """Start a break period."""
        if not self.is_on_break:
            self.break_start = datetime.datetime.now(PST_TZ)
            self.is_on_break = True

    def end_break(self):
        """End a break period."""
        if self.is_on_break and self.break_start:
            break_end = datetime.datetime.now(PST_TZ)
            self.break_periods.append({
                'start': self.break_start,
                'end': break_end
            })
            self.break_start = None
            self.is_on_break = False

    def end(self):
        """End the study session."""
        if self.is_on_break:
            self.end_break()
        self.end_time = datetime.datetime.now(PST_TZ)

    def get_total_study_time(self) -> datetime.timedelta:
        """Calculate total study time excluding breaks."""
        if not self.end_time:
            current_time = datetime.datetime.now(PST_TZ)
        else:
            current_time = self.end_time

        total_duration = current_time - self.start_time
        break_duration = self.get_total_break_time()
        return total_duration - break_duration

    def get_total_break_time(self) -> datetime.timedelta:
        """Calculate total break time."""
        total_break = datetime.timedelta()
        
        for break_period in self.break_periods:
            total_break += break_period['end'] - break_period['start']
        
        if self.is_on_break and self.break_start:
            current_time = datetime.datetime.now(PST_TZ)
            total_break += current_time - self.break_start
        
        return total_break

    def get_study_break_ratio(self) -> str:
        """Calculate the study to break ratio."""
        study_time = self.get_total_study_time()
        break_time = self.get_total_break_time()
        
        study_minutes = int(study_time.total_seconds() / 60)
        break_minutes = int(break_time.total_seconds() / 60)
        
        if break_minutes == 0:
            return f"{study_minutes}:0"
        
        def gcd(a, b):
            while b:
                a, b = b, a % b
            return a
        
        divisor = gcd(study_minutes, break_minutes)
        return f"{study_minutes//divisor}:{break_minutes//divisor}"

    def get_progress_percentage(self) -> int:
        """Calculate progress percentage based on goal."""
        if not self.goal_time:
            return 0
        
        try:
            if ':' in self.goal_time:
                hours, minutes = map(int, self.goal_time.split(':'))
                goal_minutes = hours * 60 + minutes
            else:
                goal_minutes = int(self.goal_time) * 60
        except ValueError:
            return 0

        study_time = self.get_total_study_time()
        actual_minutes = study_time.total_seconds() / 60
        progress = (actual_minutes / goal_minutes) * 100
        return min(100, int(progress))

    def get_formatted_manila_times(self) -> dict:
        """Get all times formatted in Manila timezone."""
        times = {
            'start': self.start_time.astimezone(MANILA_TZ),
            'end': self.end_time.astimezone(MANILA_TZ) if self.end_time else None,
            'breaks': []
        }
        
        for break_period in self.break_periods:
            times['breaks'].append({
                'start': break_period['start'].astimezone(MANILA_TZ),
                'end': break_period['end'].astimezone(MANILA_TZ)
            })
            
        return times

# ================== PENDING SESSION CLASS ==================
class PendingSession:
    def __init__(self, user_id: int, chat_id: int, message_ids: list, start_time: datetime.datetime):
        self.user_id = user_id
        self.chat_id = chat_id
        self.message_ids = message_ids
        self.start_time = start_time
        self.thread_id = None

# ================== TELEGRAM BOT CLASS ==================
class TelegramBot:
    def __init__(self):
        self.study_sessions: Dict[int, StudySession] = {}
        self.pending_sessions: Dict[int, PendingSession] = {}
        self.last_activity = datetime.datetime.now()
        self.start_command_handlers: Set[int] = set()  # Track users who have already triggered /start
        self.application = None

    async def cleanup_all_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Clean up ALL messages including those marked to keep."""
        messages_to_delete = context.user_data.get('messages_to_delete', [])
        messages_to_keep = context.user_data.get('messages_to_keep', [])
        
        all_messages = messages_to_delete + messages_to_keep
        
        for message_id in all_messages:
            try:
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id,
                    message_id=message_id
                )
            except Exception as e:
                logger.error(f"Error deleting message {message_id}: {e}")
        
        context.user_data['messages_to_delete'] = []
        context.user_data['messages_to_keep'] = []
    
    async def cleanup_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Clean up messages that should be deleted."""
        messages_to_delete = context.user_data.get('messages_to_delete', [])
        
        for message_id in messages_to_delete:
            try:
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id,
                    message_id=message_id
                )
            except Exception as e:
                logger.error(f"Error deleting message {message_id}: {e}")
        
        context.user_data['messages_to_delete'] = []
        
        # Also remove this user from pending sessions if they exist
        user_id = update.effective_user.id
        if user_id in self.pending_sessions:
            del self.pending_sessions[user_id]

    async def send_bot_message(
        self, 
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        text: str,
        reply_markup: InlineKeyboardMarkup = None,
        should_delete: bool = True
    ) -> int:
        """Send a bot message and track it for cleanup if needed."""
        # Update last activity timestamp
        self.record_activity()
        
        thread_id = None
        if 'thread_id' in context.user_data:
            thread_id = context.user_data['thread_id']
        elif context.user_data.get('current_thread_id'):
            thread_id = context.user_data['current_thread_id']

        message = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            message_thread_id=thread_id
        )
        
        if should_delete:
            if 'messages_to_delete' not in context.user_data:
                context.user_data['messages_to_delete'] = []
            context.user_data['messages_to_delete'].append(message.message_id)
        
        return message.message_id

    def record_activity(self):
        """Update last activity timestamp"""
        self.last_activity = datetime.datetime.now()

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Start the conversation and ask if user wants to study."""
        # Fix for duplicate welcome message
        user_id = update.effective_user.id
        
        # Check if this user has already triggered the /start command
        if user_id in self.start_command_handlers:
            # If they have, just return without doing anything
            return ConversationHandler.END
        
        # Add user to the set of users who have triggered /start
        self.start_command_handlers.add(user_id)
        
        # Clear the set after a brief delay to allow future /start commands
        asyncio.create_task(self.clear_start_handler(user_id, 5))  # 5 seconds delay
        
        await self.cleanup_messages(update, context)
        self.record_activity()
        
        # Store the thread_id if the message is in a topic
        if update.message and update.message.is_topic_message:
            context.user_data['thread_id'] = update.message.message_thread_id
        
        buttons = [
            [InlineKeyboardButton("Start Studying 📚", callback_data='start_studying')]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)
        
        welcome_text = "Welcome to RMT Study Bot! 📚✨"
        
        message = await self.send_bot_message(
            context,
            update.effective_chat.id,
            welcome_text,
            reply_markup=reply_markup,
            should_delete=False
        )
        
        # Store this message to keep it
        if 'messages_to_keep' not in context.user_data:
            context.user_data['messages_to_keep'] = []
        context.user_data['messages_to_keep'].append(message)
        
        # Add this user to pending sessions
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        thread_id = update.message.message_thread_id if update.message and update.message.is_topic_message else None
        
        # Create a pending session
        self.pending_sessions[user_id] = PendingSession(
            user_id=user_id,
            chat_id=chat_id,
            message_ids=[message],
            start_time=datetime.datetime.now()
        )
        self.pending_sessions[user_id].thread_id = thread_id
        
        # Schedule cleanup task for this pending session
        asyncio.create_task(self.schedule_pending_session_cleanup(user_id))
        
        return CHOOSING_MAIN_MENU

    async def clear_start_handler(self, user_id: int, delay: int):
        """Clear a user from the start handler set after a delay."""
        await asyncio.sleep(delay)
        if user_id in self.start_command_handlers:
            self.start_command_handlers.remove(user_id)

    async def schedule_pending_session_cleanup(self, user_id: int):
        """Schedule cleanup of a pending session after 30 minutes."""
        try:
            await asyncio.sleep(30 * 60)  # 30 minutes
            
            # Check if this pending session still exists and hasn't been completed
            if user_id in self.pending_sessions and self.application:
                pending_session = self.pending_sessions[user_id]
                
                # Delete all associated messages
                for message_id in pending_session.message_ids:
                    try:
                        await self.application.bot.delete_message(
                            chat_id=pending_session.chat_id,
                            message_id=message_id
                        )
                    except Exception as e:
                        logger.error(f"Error deleting pending session message {message_id}: {e}")
                
                # Notify the user
                try:
                    thread_id = pending_session.thread_id
                    await self.application.bot.send_message(
                        chat_id=pending_session.chat_id,
                        text="Your study session setup was automatically cancelled due to inactivity (30 minutes timeout).",
                        message_thread_id=thread_id
                    )
                except Exception as e:
                    logger.error(f"Error sending cleanup notification: {e}")
                
                # Remove the pending session
                del self.pending_sessions[user_id]
                logger.info(f"Cleaned up pending session for user {user_id} after timeout")
        
        except Exception as e:
            logger.error(f"Error in pending session cleanup: {e}")

    async def ask_goal(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Ask user to set a study goal."""
        self.record_activity()
        context.user_data['previous_state'] = CHOOSING_MAIN_MENU
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        buttons = [
            [
                InlineKeyboardButton("1 Hour", callback_data='goal_1'),
                InlineKeyboardButton("2 Hours", callback_data='goal_2'),
                InlineKeyboardButton("3 Hours", callback_data='goal_3')
            ],
            [
                InlineKeyboardButton("4 Hours", callback_data='goal_4'),
                InlineKeyboardButton("5 Hours", callback_data='goal_5'),
                InlineKeyboardButton("6 Hours", callback_data='goal_6')
            ],
            [
                InlineKeyboardButton("✨ Custom Goal (HH:MM) ✨", callback_data='goal_custom')
            ],
            [
                InlineKeyboardButton("No Goal ❌", callback_data='no_goal'),
                InlineKeyboardButton("Cancel ⬅️", callback_data='cancel_operation')
            ]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)
        
        message_id = await self.send_bot_message(
            context,
            update.effective_chat.id,
            "How long would you like to study? 🎯\nChoose a goal or set a custom duration (HH:MM):",
            reply_markup=reply_markup
        )
        
        # Update pending session for this user
        user_id = update.effective_user.id
        if user_id in self.pending_sessions:
            self.pending_sessions[user_id].message_ids.append(message_id)
        
        try:
            await query.message.delete()
        except Exception as e:
            logger.error(f"Error deleting message: {e}")
        
        return SETTING_GOAL

    async def handle_goal_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle goal selection or prompt for custom goal."""
        self.record_activity()
        query = update.callback_query
        await query.answer()
        
        try:
            await query.message.delete()
        except Exception as e:
            logger.error(f"Error deleting message: {e}")

        if query.data == 'goal_custom':
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Please enter your study goal in HH:MM format (e.g., 01:30 for 1 hour 30 minutes):"
            )
            
            # Update pending session for this user
            user_id = update.effective_user.id
            if user_id in self.pending_sessions:
                self.pending_sessions[user_id].message_ids.append(message_id)
                
            return SETTING_CUSTOM_GOAL
        
        goal_time = query.data.split('_')[1] if query.data != 'no_goal' else None
        context.user_data['goal_time'] = goal_time
        
        return await self.show_subject_selection(update, context)

    async def handle_custom_goal(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle custom goal time input."""
        self.record_activity()
        try:
            goal_input = update.message.text.strip()
            hours, minutes = map(int, goal_input.split(':'))
            
            if hours < 0 or minutes < 0 or minutes >= 60:
                raise ValueError
                
            context.user_data['goal_time'] = goal_input
            
            try:
                await update.message.delete()
            except Exception as e:
                logger.error(f"Error deleting message: {e}")
            
            return await self.show_subject_selection(update, context)
            
        except ValueError:
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                "⚠️ Please enter a valid time in HH:MM format (e.g., 01:30 for 1 hour 30 minutes):"
            )
            
            # Update pending session for this user
            user_id = update.effective_user.id
            if user_id in self.pending_sessions:
                self.pending_sessions[user_id].message_ids.append(message_id)
                
            return SETTING_CUSTOM_GOAL

    async def show_subject_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Show subject selection buttons."""
        self.record_activity()
        context.user_data['previous_state'] = SETTING_GOAL
        buttons = []
        current_row = []
        
        for subject_name, subject_code in SUBJECTS.items():
            current_row.append(InlineKeyboardButton(
                subject_name, 
                callback_data=f'subject_{subject_code}'
            ))
            
            if len(current_row) == 3:
                buttons.append(current_row)
                current_row = []
        
        if current_row:
            buttons.append(current_row)
            
        buttons.append([InlineKeyboardButton("Cancel ⬅️", callback_data='cancel_operation')])
        
        reply_markup = InlineKeyboardMarkup(buttons)
        
        message_id = await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Choose your subject: 📚",
            reply_markup=reply_markup,
            should_delete=True
        )
        
        # Update pending session for this user
        user_id = update.effective_user.id
        if user_id in self.pending_sessions:
            self.pending_sessions[user_id].message_ids.append(message_id)
        
        return CHOOSING_SUBJECT

    async def start_studying(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Start a study session for the selected subject."""
        self.record_activity()
        query = update.callback_query
        await query.answer()
        
        try:
            await query.message.delete()
        except Exception as e:
            logger.error(f"Error deleting message: {e}")

        user = update.effective_user
        subject_code = query.data.split('_')[1]
        subject_name = next((name for name, code in SUBJECTS.items() if code == subject_code), subject_code)
        
        self.study_sessions[user.id] = StudySession(
            user_id=user.id,
            subject=subject_name,
            goal_time=context.user_data.get('goal_time')
        )
        
        session_start_time = self.study_sessions[user.id].start_time.astimezone(MANILA_TZ)
        
        user_name = user.first_name or user.username or "User"
        await self.send_bot_message(
            context,
            update.effective_chat.id,
            f"🚀 {user_name} started a new session!",
            should_delete=False
        )
        
        await self.send_bot_message(
            context,
            update.effective_chat.id,
            f"Subject: {subject_name}",
            should_delete=False
        )
        
        await self.send_bot_message(
            context,
            update.effective_chat.id,
            f"Started at: {session_start_time.strftime('%I:%M %p')}",
            should_delete=True
        )
        
        if context.user_data.get('goal_time'):
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"Goal: {context.user_data['goal_time']}h",
                should_delete=True
            )

        buttons = [
            [
                InlineKeyboardButton("Take a Break ☕", callback_data='start_break'),
                InlineKeyboardButton("End Session ⏹️", callback_data='end_session')
            ],
            [InlineKeyboardButton("Cancel ⬅️", callback_data='cancel_operation')]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)

        await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Session Controls:",
            reply_markup=reply_markup,
            should_delete=True
        )
        
        # Remove this user from pending sessions as they've completed setup
        if user.id in self.pending_sessions:
            del self.pending_sessions[user.id]
        
        return STUDYING

    async def handle_break(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle break start/end."""
        self.record_activity()
        query = update.callback_query
        await query.answer()
        
        try:
            await query.message.delete()
        except Exception as e:
            logger.error(f"Error deleting message: {e}")

        user = update.effective_user
        session = self.study_sessions.get(user.id)
        
        if not session:
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "No active study session found. Start a new session?"
            )
            return await self.start(update, context)

        if query.data == 'start_break':
            session.start_break()
            buttons = [
                [
                    InlineKeyboardButton("End Break ▶️", callback_data='end_break'),
                    InlineKeyboardButton("End Session ⏹️", callback_data='end_session')
                ],
                [InlineKeyboardButton("Cancel ⬅️", callback_data='cancel_operation')]
            ]
            reply_markup = InlineKeyboardMarkup(buttons)
            
            break_start_time = datetime.datetime.now(PST_TZ).astimezone(MANILA_TZ)
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"☕ Break started at {break_start_time.strftime('%I:%M %p')}",
                reply_markup=reply_markup,
                should_delete=False
            )
            return ON_BREAK
                
        elif query.data == 'end_break':
            session.end_break()
            buttons = [
                [
                    InlineKeyboardButton("Take a Break ☕", callback_data='start_break'),
                    InlineKeyboardButton("End Session ⏹️", callback_data='end_session')
                ],
                [InlineKeyboardButton("Cancel ⬅️", callback_data='cancel_operation')]
            ]
            reply_markup = InlineKeyboardMarkup(buttons)
            
            break_end_time = datetime.datetime.now(PST_TZ).astimezone(MANILA_TZ)
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"▶️ Break ended at {break_end_time.strftime('%I:%M %p')}\nBack to studying!",
                reply_markup=reply_markup,
                should_delete=False
            )
            return STUDYING

    async def end_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """End the study session and show summary."""
        self.record_activity()
        query = update.callback_query
        await query.answer()
        
        try:
            await query.message.delete()
        except Exception as e:
            logger.error(f"Error deleting message: {e}")

        user = update.effective_user
        session = self.study_sessions.get(user.id)
        
        if not session:
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "No active study session found. Start a new session?"
            )
            return await self.start(update, context)

        session.end()
        manila_times = session.get_formatted_manila_times()
        
        try:
            user_name = user.first_name or user.username or "User"
            summary_msg = await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"🚧 {user_name} ended the session 🚧",
                should_delete=False
            )
            
            if 'messages_to_keep' not in context.user_data:
                context.user_data['messages_to_keep'] = []
            context.user_data['messages_to_keep'].append(summary_msg)

            study_time = session.get_total_study_time()
            study_time_msg = await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"Total Study Time: {int(study_time.total_seconds() // 3600)}h {int((study_time.total_seconds() % 3600) // 60)}m",
                should_delete=False
            )
            context.user_data['messages_to_keep'].append(study_time_msg)

            session_info = [
                f"Started: {manila_times['start'].strftime('%I:%M %p')}",
                f"Ended: {manila_times['end'].strftime('%I:%M %p')}"
            ]
            
            if context.user_data.get('goal_time'):
                progress_percentage = session.get_progress_percentage()
                session_info.append("")
                session_info.append(f"Goal Progress: {progress_percentage}%")
            
            if session.break_periods:
                session_info.append("")
                session_info.append("Break Details:")
                for break_period in manila_times['breaks']:
                    session_info.append(
                        f"Break: {break_period['start'].strftime('%I:%M %p')} - "
                        f"{break_period['end'].strftime('%I:%M %p')}"
                    )
            
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "\n".join(session_info),
                should_delete=True
            )

            celebration_msg = await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"🎉",
                should_delete=False
            )
            context.user_data['messages_to_keep'].append(celebration_msg)

            await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"꧁RMT KA NA SA AUGUST꧂",
                should_delete=True
            )

            buttons = [[InlineKeyboardButton("Start New Study Session 📚", callback_data='start_studying')]]
            reply_markup = InlineKeyboardMarkup(buttons)
            
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Ready to start another study session?",
                reply_markup=reply_markup
            )

        except Exception as e:
            logger.error(f"Error in end_session: {e}")
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "There was an error ending your session. Please try again."
            )

        del self.study_sessions[user.id]
        return CHOOSING_MAIN_MENU

    async def cancel_operation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Show cancel confirmation dialog."""
        self.record_activity()
        query = update.callback_query
        if query:
            await query.answer()
            
            try:
                await query.message.delete()
            except Exception as e:
                logger.error(f"Error deleting message: {e}")

        buttons = [
            [
                InlineKeyboardButton("Yes ✅", callback_data='confirm_cancel'),
                InlineKeyboardButton("No ❌", callback_data='reject_cancel')
            ]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)
        
        message_id = await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Are you sure you want to cancel?",
            reply_markup=reply_markup,
            should_delete=True
        )
        
        # Update pending session for this user
        user_id = update.effective_user.id
        if user_id in self.pending_sessions:
            self.pending_sessions[user_id].message_ids.append(message_id)
        
        return CONFIRMING_CANCEL

    async def handle_cancel_confirmation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the cancel confirmation response."""
        self.record_activity()
        query = update.callback_query
        await query.answer()
        
        try:
            await query.message.delete()
        except Exception as e:
            logger.error(f"Error deleting message: {e}")

        if query.data == 'confirm_cancel':
            user = update.effective_user
            if user.id in self.study_sessions:
                del self.study_sessions[user.id]
            
            # Also remove from pending sessions
            if user.id in self.pending_sessions:
                del self.pending_sessions[user_id]
            
            await self.cleanup_messages(update, context)
            return await self.start(update, context)
            
        else:
            return context.user_data.get('previous_state', CHOOSING_MAIN_MENU)

# ================== ERROR HANDLER ==================
async def error_handler(update, context):
    """Handle errors in the telegram bot."""
    if isinstance(context.error, telegram.error.Conflict):
        logger.error("Conflict error detected: Another instance is running. Shutting down this instance.")
        shared_state.is_shutting_down = True
        os._exit(1)  # Force exit to allow Render to restart a fresh instance
    else:
        logger.error(f"Exception while handling an update: {context.error}")

# ================== SELF-PING FUNCTION ==================
def self_ping():
    """Ping our own health endpoint to keep the service alive."""
    try:
        import urllib.request
        port = int(os.getenv('HEALTH_CHECK_PORT', os.getenv('PORT', 10001)))
        urllib.request.urlopen(f"http://localhost:{port}/health", timeout=10)
    except Exception as e:
        logger.warning(f"Self-ping failed: {e}")

# ================== RELIABILITY IMPROVEMENTS ==================
async def run_bot_with_retries():
    """Run the bot with automatic retries and permanent operation"""
    keepalive_server = KeepaliveServer()
    keepalive_server.start()
    
    max_retries = 10
    retry_delay = 30
    
    for attempt in range(max_retries):
        if shared_state.is_shutting_down:
            logger.info("Shutdown signal received. Exiting...")
            break
            
        try:
            # Create application with proper token
            token = os.getenv('TELEGRAM_BOT_TOKEN')
            if not token:
                logger.error("No TELEGRAM_BOT_TOKEN provided in environment variables")
                sys.exit(1)
                
            # Set up proper drop_pending_updates to avoid handling old messages
            application = Application.builder().token(token).build()
            
            telegram_bot = TelegramBot()
            telegram_bot.application = application
            
            # Store in shared state
            shared_state.telegram_bot = telegram_bot
            
            # Add start command handler
            application.add_handler(CommandHandler('start', telegram_bot.start))
            
            conv_handler = ConversationHandler(
                entry_points=[CallbackQueryHandler(telegram_bot.ask_goal, pattern='^start_studying$')],
                states={
                    CONFIRMING_CANCEL: [
                        CallbackQueryHandler(telegram_bot.handle_cancel_confirmation, pattern='^confirm_cancel$'),
                        CallbackQueryHandler(telegram_bot.handle_cancel_confirmation, pattern='^reject_cancel$')
                    ],
                    CHOOSING_MAIN_MENU: [
                        CallbackQueryHandler(telegram_bot.ask_goal, pattern='^start_studying$')
                    ],
                    SETTING_GOAL: [
                        CallbackQueryHandler(telegram_bot.handle_goal_selection, pattern='^goal_'),
                        CallbackQueryHandler(telegram_bot.handle_goal_selection, pattern='^no_goal$'),
                        CallbackQueryHandler(telegram_bot.cancel_operation, pattern='^cancel_operation$')
                    ],
                    SETTING_CUSTOM_GOAL: [
                        MessageHandler(filters.TEXT & ~filters.COMMAND, telegram_bot.handle_custom_goal),
                        CallbackQueryHandler(telegram_bot.cancel_operation, pattern='^cancel_operation$')
                    ],
                    CHOOSING_SUBJECT: [
                        CallbackQueryHandler(telegram_bot.start_studying, pattern='^subject_'),
                        CallbackQueryHandler(telegram_bot.cancel_operation, pattern='^cancel_operation$')
                    ],
                    STUDYING: [
                        CallbackQueryHandler(telegram_bot.handle_break, pattern='^start_break$'),
                        CallbackQueryHandler(telegram_bot.end_session, pattern='^end_session$'),
                        CallbackQueryHandler(telegram_bot.cancel_operation, pattern='^cancel_operation$')
                    ],
                    ON_BREAK: [
                        CallbackQueryHandler(telegram_bot.handle_break, pattern='^end_break$'),
                        CallbackQueryHandler(telegram_bot.end_session, pattern='^end_session$'),
                        CallbackQueryHandler(telegram_bot.cancel_operation, pattern='^cancel_operation$')
                    ]
                },
                fallbacks=[
                    CallbackQueryHandler(telegram_bot.cancel_operation, pattern='^cancel_operation$')
                ],
                per_message=False,
                per_chat=True,
                name="main_conversation"
            )

            application.add_handler(conv_handler)
            application.add_error_handler(error_handler)
            
            # First try to delete any existing webhook
            await application.bot.delete_webhook(drop_pending_updates=True)
            
            # Initialize and start the application
            await application.initialize()
            await application.start()
            
            # Start polling with critical fix: force drop_pending_updates=True
            # This fixes the "terminated by other getUpdates request" error
            await application.updater.start_polling(
                poll_interval=3,
                timeout=30,
                drop_pending_updates=True,
                read_timeout=30,
                write_timeout=30
            )
            
            logger.info("Bot is now running and polling 24/7")

            # Self-healing watchdog
            last_health_check = datetime.datetime.now()
            while not shared_state.is_shutting_down:
                current_time = datetime.datetime.now()
                
                # Check for inactivity and perform health check
                inactive_time = (current_time - telegram_bot.last_activity).total_seconds()
                health_check_due = (current_time - last_health_check).total_seconds() > 300  # Every 5 minutes
                
                if inactive_time > 3600:  # 1 hour inactivity threshold
                    logger.warning(f"No activity for {inactive_time//60} minutes, performing health check...")
                    try:
                        await application.bot.get_me()
                        logger.info("Health check passed despite inactivity")
                        telegram_bot.last_activity = current_time  # Reset activity timer
                    except Exception as e:
                        logger.error(f"Health check failed after inactivity: {e}")
                        raise RuntimeError("Activity timeout and health check failure")
                
                # Periodic health check regardless of activity
                if health_check_due:
                    try:
                        await application.bot.get_me()
                        logger.debug("Periodic health check passed")
                        last_health_check = current_time
                    except Exception as e:
                        logger.error(f"Periodic health check failed: {e}")
                        raise RuntimeError("Health check failure")
                
                # Perform a self-ping to keep Render instance alive
                if current_time.minute % 10 == 0 and current_time.second < 10:
                    try:
                        self_ping()
                        logger.debug("Self-ping performed")
                    except Exception as e:
                        logger.warning(f"Self-ping failed: {e}")
                
                await asyncio.sleep(10)  # Check more frequently
            
            # Clean shutdown if we get here
            logger.info("Shutting down bot gracefully...")
            await application.stop()
            await application.shutdown()
            break
            
        except telegram.error.Conflict as e:
            logger.error(f"Conflict error: {e}. Another instance is likely running.")
            shared_state.is_shutting_down = True
            break
            
        except Exception as e:
            logger.error(f"Attempt {attempt + 1} failed: {str(e)}")
            if attempt < max_retries - 1 and not shared_state.is_shutting_down:
                logger.info(f"Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 1.5, 300)  # Exponential backoff, max 5 minutes
            else:
                logger.error("Max retries reached or shutdown requested. Exiting...")
                break
    
    # Stop the keepalive server
    keepalive_server.stop()
    
    if shared_state.is_shutting_down:
        logger.info("Process is shutting down.")
    else:
        logger.error("Bot failed to start after maximum retries.")

# ================== SIGNAL HANDLERS ==================
def handle_sigterm(signum, frame):
    """Handle SIGTERM gracefully."""
    logger.info("Received SIGTERM signal. Initiating shutdown...")
    shared_state.is_shutting_down = True

# ================== MAIN ENTRY POINT ==================
def main():
    """Main entry point with reliability enhancements"""
    try:
        # Register signal handlers
        signal.signal(signal.SIGTERM, handle_sigterm)
        signal.signal(signal.SIGINT, handle_sigterm)
        
        # Try to ensure we're the only instance running
        try:
            ensure_single_instance()
        except Exception as e:
            logger.error(f"Error in single instance check: {e}")
        
        # Add version and startup info
        logger.info(f"Starting RMT Study Bot v1.0.5 - 24/7 Edition")
        logger.info(f"Current Date and Time: {datetime.datetime.now(MANILA_TZ).strftime('%Y-%m-%d %H:%M:%S %Z')}")
        logger.info(f"User: {CURRENT_USER}")
        logger.info(f"Process ID: {os.getpid()}")
        
        # Run the bot with retries
        asyncio.run(run_bot_with_retries())
        
        logger.info("Bot has shutdown gracefully.")
        sys.exit(0)
        
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        sys.exit(1)

if __name__ == '__main__':
    main()
