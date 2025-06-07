import os
import sys
import logging
import asyncio
import datetime
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, Optional
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
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Timezone configurations
PST_TZ = pytz.timezone('America/Los_Angeles')
MANILA_TZ = pytz.timezone('Asia/Manila')

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

# Health Check Handler
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'OK')
        else:
            self.send_response(404)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Not Found')

    def log_message(self, format, *args):
        # Suppress logging of health check requests
        pass

def start_health_server(port):
    """Start the health check server in a separate thread."""
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    logger.info("Health check server started on port %d", port)

class StudySession:
    def __init__(self, user_id: int, subject: str, goal_time: Optional[str] = None):
        self.user_id = user_id
        self.subject = subject
        self.goal_time = goal_time  # Can now be in HH:MM format
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
        
        # Add completed breaks
        for break_period in self.break_periods:
            total_break += break_period['end'] - break_period['start']
        
        # Add current break if on break
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
        
        # Find the GCD for simplification
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
        
        # Parse goal time (now supports HH:MM format)
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

class TelegramBot:
    def __init__(self):
        self.study_sessions: Dict[int, StudySession] = {}
        
    async def cleanup_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Clean up messages that should be deleted."""
        # Get list of messages to delete from context
        messages_to_delete = context.user_data.get('messages_to_delete', [])
        
        # Delete each message
        for message_id in messages_to_delete:
            try:
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id,
                    message_id=message_id
                )
            except Exception as e:
                logger.error(f"Error deleting message {message_id}: {e}")
        
        # Clear the list
        context.user_data['messages_to_delete'] = []

    async def send_bot_message(
        self, 
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        text: str,
        reply_markup: InlineKeyboardMarkup = None,
        should_delete: bool = True
    ) -> int:
        """Send a bot message and track it for cleanup if needed."""
        # Set thread_id from the update if available
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

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Start the conversation and ask if user wants to study."""
        await self.cleanup_messages(update, context)
        
        # Store the thread_id if the message is in a topic
        if update.message and update.message.is_topic_message:
            context.user_data['thread_id'] = update.message.message_thread_id
        
        buttons = [
            [InlineKeyboardButton("Start Studying 📚", callback_data='start_studying')]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)
        
        # Simplified welcome message
        welcome_text = "Welcome to RMT Study Bot! 📚✨"
        
        await self.send_bot_message(
            context,
            update.effective_chat.id,
            welcome_text,
            reply_markup=reply_markup,
            should_delete=False  # Keep the welcome message
        )
        
        return CHOOSING_MAIN_MENU

    async def ask_goal(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Ask user to set a study goal."""
        context.user_data['previous_state'] = CHOOSING_MAIN_MENU
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        # Create buttons for preset hours and custom option
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
        
        await self.send_bot_message(
            context,
            update.effective_chat.id,
            "How long would you like to study? 🎯\nChoose a goal or set a custom duration (HH:MM):",
            reply_markup=reply_markup
        )
        
        # Delete the clicked button's message
        try:
            await query.message.delete()
        except Exception as e:
            logger.error(f"Error deleting message: {e}")
        
        return SETTING_GOAL

    async def handle_goal_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle goal selection or prompt for custom goal."""
        query = update.callback_query
        await query.answer()
        
        # Delete the clicked button's message
        try:
            await query.message.delete()
        except Exception as e:
            logger.error(f"Error deleting message: {e}")

        if query.data == 'goal_custom':
            # Prompt for custom goal input
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Please enter your study goal in HH:MM format (e.g., 01:30 for 1 hour 30 minutes):"
            )
            return SETTING_CUSTOM_GOAL
        
        goal_time = query.data.split('_')[1] if query.data != 'no_goal' else None
        context.user_data['goal_time'] = goal_time
        
        return await self.show_subject_selection(update, context)

    async def handle_custom_goal(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle custom goal time input."""
        try:
            # Validate input format (HH:MM)
            goal_input = update.message.text.strip()
            hours, minutes = map(int, goal_input.split(':'))
            
            if hours < 0 or minutes < 0 or minutes >= 60:
                raise ValueError
                
            context.user_data['goal_time'] = goal_input
            
            # Delete the user's input message
            try:
                await update.message.delete()
            except Exception as e:
                logger.error(f"Error deleting message: {e}")
            
            return await self.show_subject_selection(update, context)
            
        except ValueError:
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "⚠️ Please enter a valid time in HH:MM format (e.g., 01:30 for 1 hour 30 minutes):"
            )
            return SETTING_CUSTOM_GOAL

    async def show_subject_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Show subject selection buttons."""
        context.user_data['previous_state'] = SETTING_GOAL
        # Create buttons for subjects in a 3-column grid
        buttons = []
        current_row = []
        
        for subject_name, subject_code in SUBJECTS.items():
            current_row.append(InlineKeyboardButton(
                subject_name, 
                callback_data=f'subject_{subject_code}'
            ))
            
            if len(current_row) == 3:  # Three buttons per row
                buttons.append(current_row)
                current_row = []
        
        if current_row:  # Add any remaining buttons
            buttons.append(current_row)
            
        # Add cancel button at the bottom
        buttons.append([InlineKeyboardButton("Cancel ⬅️", callback_data='cancel_operation')])
        
        reply_markup = InlineKeyboardMarkup(buttons)
        
        await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Choose your subject: 📚",
            reply_markup=reply_markup,
            should_delete=True
        )
        
        return CHOOSING_SUBJECT

    async def start_studying(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Start a study session for the selected subject."""
        query = update.callback_query
        await query.answer()
        
        # Delete the clicked button's message
        try:
            await query.message.delete()
        except Exception as e:
            logger.error(f"Error deleting message: {e}")

        user = update.effective_user
        subject_code = query.data.split('_')[1]
        subject_name = next((name for name, code in SUBJECTS.items() if code == subject_code), subject_code)
        
        # Create new study session
        self.study_sessions[user.id] = StudySession(
            user_id=user.id,
            subject=subject_name,
            goal_time=context.user_data.get('goal_time')
        )
        
        session_start_time = self.study_sessions[user.id].start_time.astimezone(MANILA_TZ)
        
        # Message 1 (Keep forever)
        await self.send_bot_message(
            context,
            update.effective_chat.id,
            f"📚 Study Session Started!\nSubject: {subject_name}",
            should_delete=False
        )
        
        # Message 2 (Delete after new session)
        await self.send_bot_message(
            context,
            update.effective_chat.id,
            f"Started at: {session_start_time.strftime('%I:%M %p')}",
            should_delete=True
        )
        
        # Message 3 (Delete after new session)
        if context.user_data.get('goal_time'):
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"Goal: {context.user_data['goal_time']}h",
                should_delete=True
            )

        # Create buttons for study controls
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
        
        return STUDYING

    async def handle_break(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle break start/end."""
        query = update.callback_query
        await query.answer()
        
        # Delete the clicked button's message
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
            
            # Break start message (keep forever)
            break_start_time = datetime.datetime.now(PST_TZ).astimezone(MANILA_TZ)
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"☕ Break started at {break_start_time.strftime('%I:%M %p')}",
                reply_markup=reply_markup,
                should_delete=False  # Keep break message forever
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
            
            # Break end message (keep forever)
            break_end_time = datetime.datetime.now(PST_TZ).astimezone(MANILA_TZ)
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"▶️ Break ended at {break_end_time.strftime('%I:%M %p')}\nBack to studying!",
                reply_markup=reply_markup,
                should_delete=False  # Keep break message forever
            )
            return STUDYING

    async def end_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """End the study session and show summary."""
        query = update.callback_query
        await query.answer()
        
        # Delete the clicked button's message
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
            # Message 1: Summary (keep forever)
            summary_msg = await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"📚 Study Session Summary\nSubject: {session.subject}",
                should_delete=False
            )
            
            # Store message ID as one to keep
            if 'messages_to_keep' not in context.user_data:
                context.user_data['messages_to_keep'] = []
            context.user_data['messages_to_keep'].append(summary_msg)

            # Message 2: Total Study Time (keep forever)
            study_time = session.get_total_study_time()
            study_time_msg = await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"Total Study Time: {int(study_time.total_seconds() // 3600)}h {int((study_time.total_seconds() % 3600) // 60)}m",
                should_delete=False
            )
            context.user_data['messages_to_keep'].append(study_time_msg)

            # Message 3: Session Times (delete on new session)
            session_times_msg = await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"Started: {manila_times['start'].strftime('%I:%M %p')}\n"
                f"Ended: {manila_times['end'].strftime('%I:%M %p')}",
                should_delete=True
            )

            # Message 4: Total Break Time (keep forever)
            break_time = session.get_total_break_time()
            break_time_msg = await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"Total Break Time: {int(break_time.total_seconds() // 3600)}h {int((break_time.total_seconds() % 3600) // 60)}m",
                should_delete=False
            )
            context.user_data['messages_to_keep'].append(break_time_msg)

            # Message 5: Break Details (delete on new session)
            if session.break_periods:
                break_details = ["Break Details:"]
                for break_period in manila_times['breaks']:
                    break_details.append(
                        f"Break: {break_period['start'].strftime('%I:%M %p')} - "
                        f"{break_period['end'].strftime('%I:%M %p')}"
                    )
                await self.send_bot_message(
                    context,
                    update.effective_chat.id,
                    "\n".join(break_details),
                    should_delete=True
                )

            # Create buttons for next action
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

        # Clear the session
        del self.study_sessions[user.id]
        return CHOOSING_MAIN_MENU

    async def cancel_operation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Show cancel confirmation dialog."""
        query = update.callback_query
        if query:
            await query.answer()
            
            # Delete the clicked button's message
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
        
        await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Are you sure you want to cancel?",
            reply_markup=reply_markup,
            should_delete=True
        )
        
        return CONFIRMING_CANCEL

    async def handle_cancel_confirmation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the cancel confirmation response."""
        query = update.callback_query
        await query.answer()
        
        # Delete the confirmation message
        try:
            await query.message.delete()
        except Exception as e:
            logger.error(f"Error deleting message: {e}")

        if query.data == 'confirm_cancel':
            # Clean up any current operations
            user = update.effective_user
            if user.id in self.study_sessions:
                del self.study_sessions[user.id]
                
            await self.cleanup_messages(update, context)
            return await self.start(update, context)
        else:  # reject_cancel
            # Return to previous state
            return context.user_data.get('previous_state', CHOOSING_MAIN_MENU)

def main() -> None:
    """Start the bot."""
    # Add startup logging with current timestamp
    startup_time = "2025-06-06 20:34:51"  # Current UTC time
    current_user = "Zackrmt"
    
    logger.info(f"Bot starting at {startup_time} UTC")
    logger.info(f"Started by user: {current_user}")
    logger.info("Initializing bot application...")

    # Create the Application and pass it your bot's token
    application = Application.builder().token(os.getenv('TELEGRAM_BOT_TOKEN')).build()

    # Health check server setup
    try:
        port = int(os.getenv('HEALTH_CHECK_PORT', 10001))
        start_health_server(port)
    except Exception as e:
        logger.error(f"Error starting health check server: {str(e)}")

    logger.info("Setting up conversation handlers...")
    
    # Initialize bot instance
    bot = TelegramBot()
    
    # Set up conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', lambda u, c: bot.start(u, c))],
        states={
            CONFIRMING_CANCEL: [
                CallbackQueryHandler(bot.handle_cancel_confirmation, pattern='^confirm_cancel$'),
                CallbackQueryHandler(bot.handle_cancel_confirmation, pattern='^reject_cancel$')
            ],
            CHOOSING_MAIN_MENU: [
                CallbackQueryHandler(bot.ask_goal, pattern='^start_studying$')
            ],
            SETTING_GOAL: [
                CallbackQueryHandler(bot.handle_goal_selection, pattern='^goal_'),
                CallbackQueryHandler(bot.handle_goal_selection, pattern='^no_goal$'),
                CallbackQueryHandler(bot.cancel_operation, pattern='^cancel_operation$')
            ],
            SETTING_CUSTOM_GOAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_custom_goal),
                CallbackQueryHandler(bot.cancel_operation, pattern='^cancel_operation$')
            ],
            CHOOSING_SUBJECT: [
                CallbackQueryHandler(bot.start_studying, pattern='^subject_'),
                CallbackQueryHandler(bot.cancel_operation, pattern='^cancel_operation$')
            ],
            STUDYING: [
                CallbackQueryHandler(bot.handle_break, pattern='^start_break$'),
                CallbackQueryHandler(bot.end_session, pattern='^end_session$'),
                CallbackQueryHandler(bot.cancel_operation, pattern='^cancel_operation$')
            ],
            ON_BREAK: [
                CallbackQueryHandler(bot.handle_break, pattern='^end_break$'),
                CallbackQueryHandler(bot.end_session, pattern='^end_session$'),
                CallbackQueryHandler(bot.cancel_operation, pattern='^cancel_operation$')
            ]
        },
        fallbacks=[
            CommandHandler('start', lambda u, c: bot.start(u, c)),
            CallbackQueryHandler(bot.cancel_operation, pattern='^cancel_operation$')
        ],
        per_message=False,
        per_chat=True,
        name="main_conversation"
    )

    # Add handlers
    application.add_handler(conv_handler)

    # Start the Bot
    application.run_polling()

if __name__ == '__main__':
    main()
