import os
import logging
import datetime
from datetime import timezone
import asyncio
import signal
import sys
import pytz  # For timezone handling
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ContextTypes, filters, ConversationHandler
)
from PIL import Image, ImageDraw, ImageFont
import io
from typing import Dict, List, Optional
from healthcheck import start_health_server

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Add specific user and time information
CURRENT_USER = "Zackrmt"
STARTUP_TIME = "2025-06-06 08:49:59"

# Set timezone configurations
MANILA_TZ = pytz.timezone('Asia/Manila')
PST_TZ = pytz.timezone('US/Pacific')

logger = logging.getLogger(__name__)

try:
    # Try to use installed Poppins fonts
    title_font = ImageFont.truetype("/usr/share/fonts/truetype/poppins/Poppins-Bold.ttf", 80)
    main_font = ImageFont.truetype("/usr/share/fonts/truetype/poppins/Poppins-Light.ttf", 60)
except Exception as e:
    logger.warning(f"Error loading Poppins fonts: {e}")
    # Fallback to default system font if Poppins is not available
    title_font = ImageFont.load_default()
    main_font = ImageFont.load_default()
    
# Signal handler for graceful shutdown
def signal_handler(sig, frame):
    logger.info("Received shutdown signal, cleaning up...")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# States for conversation handler
(CHOOSING_MAIN_MENU, SETTING_GOAL, SETTING_CUSTOM_GOAL, CONFIRMING_GOAL, 
 CHOOSING_SUBJECT, STUDYING, ON_BREAK, CREATING_QUESTION, SETTING_CHOICES, 
 CONFIRMING_QUESTION, SETTING_CORRECT_ANSWER, SETTING_EXPLANATION,
 CHOOSING_DESIGN) = range(13)  # Added SETTING_CUSTOM_GOAL state

# Subject emojis
SUBJECTS = {
    "CC 🧪": "CC",
    "BACTE 🦠": "BACTE",
    "VIRO 👾": "VIRO",
    "MYCO 🍄": "MYCO",
    "PARA 🪱": "PARA",
    "CM 🚽💩": "CM",
    "HISTO 🧻🗳️": "HISTO",
    "MT Laws ⚖️": "MT Laws",
    "HEMA 🩸": "HEMA",
    "IS ⚛": "IS",
    "BB 🩹": "BB",
    "MolBio 🧬": "MolBio",
    "Autopsy ☠": "Autopsy",
    "General Books 📚": "General Books",
    "RECALLS 🤔💭": "RECALLS"
}

# Subject-specific colors for dashboard
SUBJECT_COLORS = {
    'CC': '#FF5733',
    'BACTE': '#33FF57',
    'VIRO': '#3357FF',
    'MYCO': '#8833FF',
    'PARA': '#FF33E9',
    'CM': '#FFB533',
    'HISTO': '#33FFE9',
    'MT Laws': '#A5FF33',
    'HEMA': '#FF3333',
    'IS': '#33A5FF',
    'BB': '#FF33A5',
    'MolBio': '#33FFA5',
    'Autopsy': '#A533FF',
    'General Books': '#FFD700',
    'RECALLS': '#C0C0C0'
}

# Image design templates (updated for new dashboard)
DESIGNS = {
    'modern': {
        'name': 'Study Progress Dashboard',
        'colors': {
            'background': '#1a1a1a',
            'card': '#2d2d2d',
            'border': '#404040',
            'text': '#ffffff',
            'accent': '#3d3d3d',
            'progress': '#FF5733',
            'subtitle': '#888888'
        },
        'fonts': {
            'title': ('Poppins-Bold', 60),
            'subtitle': ('Poppins-SemiBold', 40),
            'body': ('Poppins-Light', 32)
        },
        'layout': {
            'header_height': 0.2,  # 20% of total height
            'progress_height': 0.6,  # 60% of total height
            'footer_height': 0.2,   # 20% of total height
            'padding': 20,
            'progress_bar_height': 20
        }
    }
}

class StudySession:
    def __init__(self):
        self.start_time = None
        self.end_time = None
        self.subject = None
        self.goal_time = None
        self.breaks: List[Dict[str, datetime.datetime]] = []
        self.current_break = None
        self.messages_to_delete = []
        self.messages_to_keep = []
        self.permanent_messages = []  # New: Track messages that should never be deleted
        self.temp_messages = []      # New: Track messages that should be deleted on new session
        self.design_choice = 'modern'
        self.thread_id = None
        self.study_break_ratio = None  # New: Track study/break ratio

    def start(self, subject: str, goal_time: Optional[str] = None):
        """Start a new study session with PST time."""
        self.start_time = datetime.datetime.now(PST_TZ)
        self.subject = subject
        self.goal_time = goal_time

    def start_break(self):
        """Start a break using PST time."""
        self.current_break = {'start': datetime.datetime.now(PST_TZ)}

    def end_break(self):
        """End current break."""
        if self.current_break:
            self.current_break['end'] = datetime.datetime.now(PST_TZ)
            self.breaks.append(self.current_break)
            self.current_break = None

    def end(self):
        """End the study session."""
        self.end_time = datetime.datetime.now(PST_TZ)
        # Calculate study/break ratio
        study_time = self.get_total_study_time().total_seconds()
        break_time = self.get_total_break_time().total_seconds()
        if break_time > 0:
            self.study_break_ratio = round(study_time / break_time, 1)
        else:
            self.study_break_ratio = float('inf')

    def get_total_study_time(self) -> datetime.timedelta:
        """Calculate total study time excluding breaks."""
        if not self.start_time or not self.end_time:
            return datetime.timedelta()
        total_time = self.end_time - self.start_time
        break_time = self.get_total_break_time()
        return total_time - break_time

    def get_total_break_time(self) -> datetime.timedelta:
        """Calculate total break time."""
        total_break = datetime.timedelta()
        for break_session in self.breaks:
            total_break += break_session['end'] - break_session['start']
        return total_break

    def get_manila_time(self, dt: datetime.datetime) -> datetime.datetime:
        """Convert PST time to Manila time."""
        if dt is None:
            return None
        return dt.astimezone(MANILA_TZ)

    def get_formatted_manila_times(self) -> dict:
        """Get all times formatted in Manila timezone."""
        times = {
            'start': self.get_manila_time(self.start_time),
            'end': self.get_manila_time(self.end_time),
            'breaks': []
        }
        
        for break_session in self.breaks:
            times['breaks'].append({
                'start': self.get_manila_time(break_session['start']),
                'end': self.get_manila_time(break_session['end'])
            })
        
        return times

class Question:
    def __init__(self, creator_id: int, creator_name: str):
        self.creator_id = creator_id
        self.creator_name = creator_name
        self.question_text = None
        self.choices = []
        self.correct_answer = None
        self.explanation = None
        self.messages_to_delete = []
        self.thread_id = None
        self.user_messages = []
        self.creation_time = datetime.datetime.now(PST_TZ)

    def add_message_to_delete(self, message_id: int):
        """Add a message ID to the list of messages to be deleted."""
        if message_id not in self.messages_to_delete:
            self.messages_to_delete.append(message_id)

    def add_user_message(self, message_id: int):
        """Add a user message ID for tracking."""
        if message_id not in self.user_messages:
            self.user_messages.append(message_id)

    def get_manila_creation_time(self) -> datetime.datetime:
        """Get the question creation time in Manila timezone."""
        return self.creation_time.astimezone(MANILA_TZ)

    def format_for_display(self) -> str:
        """Format the question for display with proper Manila time."""
        manila_time = self.get_manila_creation_time()
        time_str = manila_time.strftime("%Y-%m-%d %I:%M %p")
        
        choices_text = "\n".join(f"{chr(65+i)}. {choice}" 
                               for i, choice in enumerate(self.choices))
        
        return (
            f"Question created on {time_str} (Manila Time)\n\n"
            f"{self.question_text}\n\n"
            f"{choices_text}\n\n"
            f"Created by {self.creator_name}"
        )

class TelegramBot:
    def __init__(self):
        self.study_sessions: Dict[int, StudySession] = {}
        self.questions: Dict[int, Question] = {}
        self.current_questions: Dict[int, Question] = {}
        self.startup_time = "2025-06-06 09:03:46"  # Updated timestamp
        self.current_user = "Zackrmt"
        self._start = None

    async def cleanup_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Enhanced cleanup of messages."""
        # Clean up temporary messages
        if 'temp_messages' in context.user_data:
            for msg_id in context.user_data['temp_messages']:
                try:
                    await context.bot.delete_message(
                        chat_id=update.effective_chat.id,
                        message_id=msg_id
                    )
                except Exception as e:
                    logger.debug(f"Error deleting temp message {msg_id}: {str(e)}")
            context.user_data['temp_messages'] = []

        # Clean up button messages
        if 'button_messages' in context.user_data:
            for msg_id in context.user_data['button_messages']:
                try:
                    await context.bot.edit_message_reply_markup(
                        chat_id=update.effective_chat.id,
                        message_id=msg_id,
                        reply_markup=None
                    )
                except Exception as e:
                    logger.debug(f"Error removing buttons {msg_id}: {str(e)}")
            context.user_data['button_messages'] = []

    async def send_bot_message(
        self, context: ContextTypes.DEFAULT_TYPE, 
        chat_id: int, text: str, 
        reply_markup: InlineKeyboardMarkup = None,
        should_delete: bool = True,
        is_permanent: bool = False
    ) -> int:
        """Enhanced message sending with permanent message support."""
        try:
            message = await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                message_thread_id=context.user_data.get('thread_id')
            )
            
            if should_delete and not is_permanent:
                if 'temp_messages' not in context.user_data:
                    context.user_data['temp_messages'] = []
                context.user_data['temp_messages'].append(message.message_id)
            
            if is_permanent:
                if 'permanent_messages' not in context.user_data:
                    context.user_data['permanent_messages'] = []
                context.user_data['permanent_messages'].append(message.message_id)
            
            return message.message_id
            
        except Exception as e:
            logger.error(f"Error sending message: {str(e)}")
            return None

    @property
    def start(self):
        """Enhanced start method with improved message handling."""
        if self._start is None:
            async def _start_impl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
                # Clean up any existing state
                await self.cleanup_messages(update, context)
                
                if update.effective_user.id in self.study_sessions:
                    del self.study_sessions[update.effective_user.id]
                
                if update.message and update.message.message_thread_id:
                    context.user_data['thread_id'] = update.message.message_thread_id
                    logger.info(f"Starting bot in topic {update.message.message_thread_id}")

                keyboard = [
                    [InlineKeyboardButton("Start Studying 📚", callback_data='start_studying')],
                    [InlineKeyboardButton("Create Questions ❓", callback_data='create_question')]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                try:
                    await self.send_bot_message(
                        context,
                        update.effective_chat.id,
                        'Welcome to MTLE Study Bot! Choose an option:',
                        reply_markup=reply_markup
                    )
                    return CHOOSING_MAIN_MENU
                except Exception as e:
                    logger.error(f"Error in start command: {str(e)}")
                    return ConversationHandler.END

            self._start = _start_impl
        return self._start

    async def ask_goal(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Start study session with enhanced goal setting."""
        query = update.callback_query
        if query:
            await query.answer()
            await self.cleanup_messages(update, context)

        keyboard = [
            [
                InlineKeyboardButton("1 hour", callback_data='goal_1'),
                InlineKeyboardButton("2 hours", callback_data='goal_2'),
                InlineKeyboardButton("3 hours", callback_data='goal_3')
            ],
            [
                InlineKeyboardButton("4 hours", callback_data='goal_4'),
                InlineKeyboardButton("5 hours", callback_data='goal_5'),
                InlineKeyboardButton("6 hours", callback_data='goal_6')
            ],
            [InlineKeyboardButton("CUSTOM ⚙️", callback_data='goal_custom')],  # New custom option
            [InlineKeyboardButton("No Goal", callback_data='no_goal')],
            [InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                "How long do you plan to study?",
                reply_markup=reply_markup
            )
            
            # Initialize new session
            session = StudySession()
            session.thread_id = context.user_data.get('thread_id')
            self.study_sessions[update.effective_user.id] = session
            
            return SETTING_GOAL

        except Exception as e:
            logger.error(f"Error in ask_goal: {str(e)}")
            return ConversationHandler.END

    async def handle_custom_goal(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle custom goal input."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Please enter your custom study goal in hours (e.g., '8' for 8 hours):",
            reply_markup=reply_markup
        )
        
        return SETTING_CUSTOM_GOAL

    async def process_custom_goal(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Process custom goal input."""
        try:
            hours = float(update.message.text)
            if hours <= 0:
                raise ValueError("Hours must be positive")
            
            user = update.effective_user
            session = self.study_sessions.get(user.id)
            session.goal_time = str(int(hours))
            
            # Add message to cleanup list
            if 'temp_messages' not in context.user_data:
                context.user_data['temp_messages'] = []
            context.user_data['temp_messages'].append(update.message.message_id)
            
            # Continue to subject selection
            keyboard = []
            for subject, code in SUBJECTS.items():
                keyboard.append([InlineKeyboardButton(subject, callback_data=f"subject_{code}")])
            keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation')])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"You set a goal of {hours} hours. Now, what subject will you study?",
                reply_markup=reply_markup
            )
            return CHOOSING_SUBJECT
            
        except ValueError:
            keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Please enter a valid number of hours (e.g., '8' for 8 hours):",
                reply_markup=reply_markup
            )
            return SETTING_CUSTOM_GOAL

    async def handle_goal_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle goal selection with custom option support."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        user = update.effective_user
        session = self.study_sessions.get(user.id)

        if query.data == 'goal_custom':
            return await self.handle_custom_goal(update, context)
        elif query.data == 'no_goal':
            goal_time = None
        else:
            hours = int(query.data.split('_')[1])
            goal_time = f"{hours}"

        # Create subject selection keyboard
        keyboard = []
        for subject, code in SUBJECTS.items():
            keyboard.append([InlineKeyboardButton(subject, callback_data=f"subject_{code}")])
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation')])
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            if goal_time:
                message = f"You set a goal of {goal_time} hours. Now, what subject will you study?"
            else:
                message = "What subject will you study?"

            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                message,
                reply_markup=reply_markup
            )
            
            # Store goal time in session
            session.goal_time = goal_time
            
            return CHOOSING_SUBJECT

        except Exception as e:
            logger.error(f"Error handling goal selection: {str(e)}")
            return ConversationHandler.END

    async def start_studying(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Start the study session with enhanced message handling."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        subject_code = query.data.replace('subject_', '')
        user = update.effective_user
        session = self.study_sessions[user.id]
        
        # Start session
        session.start(subject_code)

        keyboard = [
            [InlineKeyboardButton("Start Break ☕", callback_data='start_break')],
            [InlineKeyboardButton("End Study Session 🎯", callback_data='end_session')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            # Send study start message with goal time if set
            if session.goal_time:
                message = (f"📚 {user.first_name} started studying {subject_code}\n"
                         f"Goal: {session.goal_time} hours")
            else:
                message = f"📚 {user.first_name} started studying {subject_code}"

            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                message,
                reply_markup=reply_markup,
                is_permanent=True  # Keep this message permanently
            )
            
            return STUDYING
            
        except Exception as e:
            logger.error(f"Error starting study session: {str(e)}")
            return ConversationHandler.END

    async def handle_break(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle break actions with improved button cleanup."""
        query = update.callback_query
        await query.answer()
        
        # Delete the message with buttons
        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=query.message.message_id
            )
        except Exception as e:
            logger.debug(f"Error deleting message: {str(e)}")

        user = update.effective_user
        session = self.study_sessions.get(user.id)
        
        if query.data == 'start_break':
            session.start_break()
            keyboard = [
                [InlineKeyboardButton("End Break ⏰", callback_data='end_break')],
                [InlineKeyboardButton("End Study Session 🎯", callback_data='end_session')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                message_id = await self.send_bot_message(
                    context,
                    update.effective_chat.id,
                    f"☕ {user.first_name} started their break.",
                    reply_markup=reply_markup,
                    should_delete=True  # This message will be deleted on next action
                )
                return ON_BREAK
                
            except Exception as e:
                logger.error(f"Error starting break: {str(e)}")
                return ConversationHandler.END
                
        else:  # end_break
            session.end_break()
            keyboard = [
                [InlineKeyboardButton("Start Break ☕", callback_data='start_break')],
                [InlineKeyboardButton("End Study Session 🎯", callback_data='end_session')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                message_id = await self.send_bot_message(
                    context,
                    update.effective_chat.id,
                    f"⏰ {user.first_name} ended their break and resumed studying.",
                    reply_markup=reply_markup,
                    should_delete=True  # This message will be deleted on next action
                )
                return STUDYING
                
            except Exception as e:
                logger.error(f"Error ending break: {str(e)}")
                return ConversationHandler.END

    async def delete_message_callback(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Callback for deleting messages after a delay."""
        job = context.job
        try:
            await context.bot.delete_message(
                chat_id=job.data['chat_id'],
                message_id=job.data['message_id']
            )
        except Exception as e:
            logger.debug(f"Error in delete_message_callback: {str(e)}")

    async def cancel_operation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Enhanced cancel operation with better cleanup."""
        query = update.callback_query
        if query:
            await query.answer()
        
        # Clean up all temporary messages
        await self.cleanup_messages(update, context)
        
        # Clear any ongoing session or question data
        user_id = update.effective_user.id
        if user_id in self.study_sessions:
            del self.study_sessions[user_id]
        if user_id in self.current_questions:
            del self.current_questions[user_id]
        
        # Return to main menu
        keyboard = [
            [InlineKeyboardButton("Start Studying 📚", callback_data='start_studying')],
            [InlineKeyboardButton("Create Questions ❓", callback_data='create_question')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Operation cancelled. What would you like to do?",
            reply_markup=reply_markup
        )
        
        return CHOOSING_MAIN_MENU

    async def end_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """End study session with separated messages."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        user = update.effective_user
        session = self.study_sessions.get(user.id)
        if not session:
            return ConversationHandler.END

        # End session and calculate times
        session.end()
        study_time = session.get_total_study_time()
        break_time = session.get_total_break_time()

        # Convert times to Manila timezone for display
        manila_times = session.get_formatted_manila_times()
        start_time = manila_times['start'].strftime("%I:%M %p")
        end_time = manila_times['end'].strftime("%I:%M %p")

        try:
            # Message 1 (permanent) - Basic info with image to be attached
            msg1 = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"📚 Study Session Summary\nSubject: {session.subject}",
                message_thread_id=context.user_data.get('thread_id')
            )

            # Message 2 (permanent) - Study time
            msg2 = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"Total Study Time: {int(study_time.total_seconds() // 3600)}h {int((study_time.total_seconds() % 3600) // 60)}m",
                message_thread_id=context.user_data.get('thread_id')
            )

            # Message 3 (temporary) - Session times
            msg3 = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"Started: {start_time}\nEnded: {end_time}",
                message_thread_id=context.user_data.get('thread_id')
            )
            if 'temp_messages' not in context.user_data:
                context.user_data['temp_messages'] = []
            context.user_data['temp_messages'].append(msg3.message_id)

            # Message 4 (permanent) - Break time
            msg4 = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"Total Break Time: {int(break_time.total_seconds() // 3600)}h {int((break_time.total_seconds() % 3600) // 60)}m",
                message_thread_id=context.user_data.get('thread_id')
            )

            # Message 5 (temporary) - Break details if there were breaks
            if session.breaks:
                break_details = ["Break Details:"]
                for break_session in manila_times['breaks']:
                    break_start = break_session['start'].strftime("%I:%M %p")
                    break_end = break_session['end'].strftime("%I:%M %p")
                    break_details.append(f"Break: {break_start} - {break_end}")
                
                msg5 = await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="\n".join(break_details),
                    message_thread_id=context.user_data.get('thread_id')
                )
                context.user_data['temp_messages'].append(msg5.message_id)

            # Generate and send progress image
            img_bytes = await self.generate_progress_image(
                user.first_name,
                study_time,
                break_time,
                session
            )

            # Send image as reply to the first message
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=img_bytes,
                reply_to_message_id=msg1.message_id,
                message_thread_id=context.user_data.get('thread_id')
            )

            # Add button for new session only
            keyboard = [[InlineKeyboardButton("Start New Session 📚", callback_data='start_studying')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Ready to start another session?",
                reply_markup=reply_markup
            )

            # Clean up session
            del self.study_sessions[user.id]
            return CHOOSING_MAIN_MENU

        except Exception as e:
            logger.error(f"Error ending session: {str(e)}")
            return ConversationHandler.END

    async def generate_progress_image(
        self,
        user_name: str,
        study_time: datetime.timedelta,
        break_time: datetime.timedelta,
        session: StudySession
    ) -> io.BytesIO:
        """Generate an enhanced progress image with new layout."""
        # Create a square canvas (1080x1080 for Instagram)
        width = height = 1080
        image = Image.new('RGB', (width, height))
        draw = ImageDraw.Draw(image)

        try:
            # Load fonts
            title_font = ImageFont.truetype("/usr/share/fonts/truetype/poppins/Poppins-Bold.ttf", 60)
            subtitle_font = ImageFont.truetype("/usr/share/fonts/truetype/poppins/Poppins-SemiBold.ttf", 40)
            body_font = ImageFont.truetype("/usr/share/fonts/truetype/poppins/Poppins-Light.ttf", 32)
        except Exception as e:
            logger.error(f"Error loading fonts: {str(e)}")
            title_font = ImageFont.load_default()
            subtitle_font = title_font
            body_font = title_font

        # Get colors from design template
        colors = DESIGNS['modern']['colors']
        
        # Fill background
        draw.rectangle([0, 0, width, height], fill=colors['background'])

        # Draw header section
        header_height = int(height * 0.2)
        draw.rectangle(
            [20, 20, width-20, header_height],
            fill=colors['card'],
            outline=colors['border'],
            width=1
        )

        # Draw title (now properly contained in the box)
        title_text = "Study Progress Dashboard - MTLE 2025"
        title_bbox = draw.textbbox((0, 0), title_text, font=title_font)
        title_width = title_bbox[2] - title_bbox[0]
        title_x = (width - title_width) // 2
        draw.text(
            (title_x, 40),
            title_text,
            font=title_font,
            fill=colors['text']
        )

        # Convert to Manila time and format timestamp
        manila_time = datetime.datetime.now(PST_TZ).astimezone(MANILA_TZ)
        time_str = manila_time.strftime("%Y-%m-%d %I:%M %p")

        # Draw subject and statistics
        stats_y = header_height + 40
        draw.text((40, stats_y), f"Subject: {session.subject}", font=subtitle_font, fill=colors['text'])
        
        # Draw goal and actual times
        if session.goal_time:
            stats_y += 60
            draw.text((40, stats_y), f"Goal: {session.goal_time} hours", font=body_font, fill=colors['text'])
        
        stats_y += 60
        study_hours = int(study_time.total_seconds() // 3600)
        study_minutes = int((study_time.total_seconds() % 3600) // 60)
        draw.text((40, stats_y), f"Total Study Time: {study_hours}h {study_minutes}m", 
                 font=body_font, fill=colors['text'])

        stats_y += 60
        break_hours = int(break_time.total_seconds() // 3600)
        break_minutes = int((break_time.total_seconds() % 3600) // 60)
        draw.text((40, stats_y), f"Break Time: {break_hours}h {break_minutes}m",
                 font=body_font, fill=colors['text'])

        # Draw study/break ratio if applicable
        if session.study_break_ratio:
            stats_y += 60
            draw.text((40, stats_y), f"Study/Break Ratio: {session.study_break_ratio}:1",
                     font=body_font, fill=colors['text'])

        # Draw footer with user name
        footer_start = height - 100
        draw.text((width/2, footer_start), f"Name: {user_name}, RMT",
                 font=subtitle_font, fill=colors['text'], anchor="mm")

        # Save and return image
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        return img_byte_arr

def main():
    """Start the bot with enhanced configuration."""
    # Add startup logging
    startup_time = "2025-06-06 09:09:38"  # Current UTC time
    current_user = "Zackrmt"
    
    logger.info(f"Bot starting at {startup_time} UTC")
    logger.info(f"Started by user: {current_user}")
    logger.info("Initializing bot application...")
    
    # Health check server setup
    port = int(os.environ.get('PORT', 10000))
    try:
        start_health_server()
        logger.info("Health check server started successfully")
    except Exception as e:
        logger.error(f"Error starting health check server: {str(e)}")
        # Continue anyway as this is not critical

    # Create the Application and pass it your bot's token.
    application = Application.builder().token(os.environ["TELEGRAM_TOKEN"]).build()
    
    bot = TelegramBot()
    logger.info("Setting up conversation handlers...")
    
    # Updated conversation handler with all features
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', lambda u, c: bot.start(u, c))],
        states={
            CHOOSING_MAIN_MENU: [
                CallbackQueryHandler(bot.ask_goal, pattern='^start_studying$'),
                CallbackQueryHandler(bot.start_creating_question, pattern='^create_question$')
            ],
            SETTING_GOAL: [
                CallbackQueryHandler(bot.handle_goal_selection, pattern='^goal_[1-6]$'),
                CallbackQueryHandler(bot.handle_custom_goal, pattern='^goal_custom$'),
                CallbackQueryHandler(bot.handle_goal_selection, pattern='^no_goal$'),
                CallbackQueryHandler(bot.cancel_operation, pattern='^cancel_operation$')
            ],
            SETTING_CUSTOM_GOAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.process_custom_goal),
                CallbackQueryHandler(bot.cancel_operation, pattern='^cancel_operation$')
            ],
            CHOOSING_SUBJECT: [
                CallbackQueryHandler(bot.start_studying, pattern='^subject_'),
                CallbackQueryHandler(bot.handle_subject_selection, pattern='^qsubject_'),
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
            ],
            CREATING_QUESTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_question_text),
                CallbackQueryHandler(bot.cancel_operation, pattern='^cancel_operation$')
            ],
            CONFIRMING_QUESTION: [
                CallbackQueryHandler(bot.handle_question_confirmation, pattern='^confirm_question$'),
                CallbackQueryHandler(bot.handle_question_confirmation, pattern='^retry_question$'),
                CallbackQueryHandler(bot.cancel_operation, pattern='^cancel_operation$')
            ],
            SETTING_CHOICES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_choices_input),
                CallbackQueryHandler(bot.cancel_operation, pattern='^cancel_operation$')
            ],
            SETTING_CORRECT_ANSWER: [
                CallbackQueryHandler(bot.handle_correct_answer, pattern='^correct_'),
                CallbackQueryHandler(bot.cancel_operation, pattern='^cancel_operation$')
            ],
            SETTING_EXPLANATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_explanation),
                CallbackQueryHandler(bot.cancel_operation, pattern='^cancel_operation$')
            ],
            CHOOSING_DESIGN: [
                CallbackQueryHandler(bot.handle_design_selection, pattern='^save_question$'),
                CallbackQueryHandler(bot.start_creating_question, pattern='^create_question$'),
                CallbackQueryHandler(bot.cancel_operation, pattern='^cancel_operation$')
            ]
        },
        fallbacks=[
            CommandHandler('start', lambda u, c: bot.start(u, c)),
            CallbackQueryHandler(bot.cancel_operation, pattern='^cancel_operation$'),
            CallbackQueryHandler(bot.handle_answer_attempt, pattern='^answer_')
        ],
        per_message=False,
        per_chat=True
    )

    # Add handlers
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(bot.handle_answer_attempt, pattern='^answer_'))
    
    # Error handler
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Log errors caused by Updates."""
        logger.error("Exception while handling an update:", exc_info=context.error)
        if isinstance(update, Update) and update.effective_message:
            error_message = "An error occurred while processing your request. Please try again."
            try:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=error_message,
                    message_thread_id=context.user_data.get('thread_id')
                )
            except Exception as e:
                logger.error(f"Error sending error message: {str(e)}")

    # Add error handler
    application.add_error_handler(error_handler)

    # Start the Bot with webhook if URL is provided, otherwise use polling
    webhook_url = os.environ.get('WEBHOOK_URL')
    if webhook_url:
        application.run_webhook(
            listen="0.0.0.0",
            port=port,
            webhook_url=webhook_url
        )
    else:
        application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()

