import os
import logging
import datetime
from datetime import timezone
import asyncio
import signal
import sys
import pytz
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

# Update timestamps
CURRENT_USER = "Zackrmt"
STARTUP_TIME = "2025-06-06 09:36:29"

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
 CONFIRMING_QUESTION, SETTING_CORRECT_ANSWER, SETTING_EXPLANATION) = range(12)

# Subject emojis and codes
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

# Subject-specific colors
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
        self.permanent_messages = []  # Track messages that should never be deleted
        self.temp_messages = []      # Track messages that should be deleted on new session
        self.thread_id = None
        self.study_break_ratio = None  # Track study/break ratio

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
        self.startup_time = "2025-06-06 09:39:20"  # Current timestamp
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
        """Ask user to set a study goal."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        keyboard = [
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
            [InlineKeyboardButton("Custom Goal ⚡", callback_data='goal_custom')],
            [InlineKeyboardButton("No Goal 🎯", callback_data='no_goal')],
            [InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await self.send_bot_message(
            context,
            update.effective_chat.id,
            'Set your study goal:',
            reply_markup=reply_markup
        )
        return SETTING_GOAL

    async def handle_goal_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the selected study goal."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        choice = query.data
        if choice == 'no_goal':
            context.user_data['goal'] = None
        else:
            hours = choice.split('_')[1]
            context.user_data['goal'] = hours

        keyboard = [
            [InlineKeyboardButton(f"{subject}", callback_data=f'subject_{code}')]
            for subject, code in SUBJECTS.items()
        ]
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation')])
        reply_markup = InlineKeyboardMarkup(keyboard)

        await self.send_bot_message(
            context,
            update.effective_chat.id,
            'Choose your subject:',
            reply_markup=reply_markup
        )
        return CHOOSING_SUBJECT

    async def handle_custom_goal(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle custom goal selection."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation')]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await self.send_bot_message(
            context,
            update.effective_chat.id,
            'Enter your custom goal in hours (e.g., "2.5" for 2 hours and 30 minutes):',
            reply_markup=reply_markup
        )
        return SETTING_CUSTOM_GOAL

    async def process_custom_goal(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Process the custom goal input."""
        try:
            goal = float(update.message.text)
            if goal <= 0:
                raise ValueError("Goal must be positive")
            context.user_data['goal'] = str(goal)
            
            keyboard = [
                [InlineKeyboardButton(f"{subject}", callback_data=f'subject_{code}')]
                for subject, code in SUBJECTS.items()
            ]
            keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation')])
            reply_markup = InlineKeyboardMarkup(keyboard)

            await self.send_bot_message(
                context,
                update.effective_chat.id,
                'Choose your subject:',
                reply_markup=reply_markup
            )
            return CHOOSING_SUBJECT

        except ValueError:
            keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation')]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await self.send_bot_message(
                context,
                update.effective_chat.id,
                'Please enter a valid number of hours (e.g., "2.5"):',
                reply_markup=reply_markup
            )
            return SETTING_CUSTOM_GOAL

    async def start_studying(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Start a study session."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        user = update.effective_user
        subject_code = query.data.replace('subject_', '')

        # Initialize new study session
        session = StudySession()
        session.start(subject_code, context.user_data.get('goal'))
        session.thread_id = context.user_data.get('thread_id')
        self.study_sessions[user.id] = session

        # Create control buttons
        keyboard = [
            [InlineKeyboardButton("Start Break ☕", callback_data='start_break')],
            [InlineKeyboardButton("End Session 🔚", callback_data='end_session')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Format and send start message
        goal_text = f"\nGoal: {session.goal_time} hours" if session.goal_time else ""
        message = await self.send_bot_message(
            context,
            update.effective_chat.id,
            f"Started studying {subject_code}{goal_text}\n"
            f"Started at: {session.get_manila_time(session.start_time).strftime('%I:%M %p')}\n"
            f"Use the buttons below to manage your session.",
            reply_markup=reply_markup,
            is_permanent=True
        )

        if message:
            session.permanent_messages.append(message)

        return STUDYING

    async def handle_break(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle break start/end."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        user = update.effective_user
        session = self.study_sessions.get(user.id)
        if not session:
            return ConversationHandler.END

        if query.data == 'start_break':
            session.start_break()
            keyboard = [
                [InlineKeyboardButton("End Break ⏹", callback_data='end_break')],
                [InlineKeyboardButton("End Session 🔚", callback_data='end_session')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            break_start = session.get_manila_time(session.current_break['start'])
            message = await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"Break started at: {break_start.strftime('%I:%M %p')}",
                reply_markup=reply_markup,
                is_permanent=True
            )
            
            if message:
                session.permanent_messages.append(message)
            return ON_BREAK

        elif query.data == 'end_break':
            session.end_break()
            keyboard = [
                [InlineKeyboardButton("Start Break ☕", callback_data='start_break')],
                [InlineKeyboardButton("End Session 🔚", callback_data='end_session')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            break_data = session.breaks[-1]
            break_start = session.get_manila_time(break_data['start'])
            break_end = session.get_manila_time(break_data['end'])
            break_duration = break_data['end'] - break_data['start']
            
            message = await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"Break ended\n"
                f"Duration: {int(break_duration.total_seconds() // 60)} minutes\n"
                f"Started: {break_start.strftime('%I:%M %p')}\n"
                f"Ended: {break_end.strftime('%I:%M %p')}",
                reply_markup=reply_markup,
                is_permanent=True
            )
            
            if message:
                session.permanent_messages.append(message)
            return STUDYING

    async def cancel_operation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancel current operation and return to main menu."""
        query = update.callback_query
        if query:
            await query.answer()
        
        await self.cleanup_messages(update, context)
        
        user = update.effective_user
        if user.id in self.study_sessions:
            del self.study_sessions[user.id]
        if user.id in self.current_questions:
            del self.current_questions[user.id]

        keyboard = [
            [InlineKeyboardButton("Start Studying 📚", callback_data='start_studying')],
            [InlineKeyboardButton("Create Questions ❓", callback_data='create_question')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await self.send_bot_message(
            context,
            update.effective_chat.id,
            'Operation cancelled. What would you like to do?',
            reply_markup=reply_markup
        )
        
        return CHOOSING_MAIN_MENU

    async def start_creating_question(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Start the question creation process."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        keyboard = [
            [InlineKeyboardButton(f"{subject}", callback_data=f'qsubject_{code}')]
            for subject, code in SUBJECTS.items()
        ]
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation')])
        reply_markup = InlineKeyboardMarkup(keyboard)

        await self.send_bot_message(
            context,
            update.effective_chat.id,
            'Select the subject for your question:',
            reply_markup=reply_markup
        )
        return CHOOSING_SUBJECT

    async def handle_subject_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle subject selection for question creation."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        subject = query.data.replace('qsubject_', '')
        context.user_data['subject'] = subject

        user = update.effective_user
        question = Question(user.id, user.first_name)
        question.thread_id = context.user_data.get('thread_id')
        self.current_questions[user.id] = question

        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation')]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await self.send_bot_message(
            context,
            update.effective_chat.id,
            'Enter your question text:',
            reply_markup=reply_markup
        )
        return CREATING_QUESTION

    async def handle_question_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the question text input."""
        user = update.effective_user
        question = self.current_questions.get(user.id)
        if not question:
            return ConversationHandler.END

        question.question_text = update.message.text
        question.add_user_message(update.message.message_id)

        keyboard = [
            [InlineKeyboardButton("✅ Confirm", callback_data='confirm_question')],
            [InlineKeyboardButton("🔄 Try Again", callback_data='retry_question')],
            [InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await self.send_bot_message(
            context,
            update.effective_chat.id,
            f"Review your question:\n\n{question.question_text}\n\nIs this correct?",
            reply_markup=reply_markup
        )
        return CONFIRMING_QUESTION

    async def handle_question_confirmation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle question confirmation."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        if query.data == 'retry_question':
            keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation')]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await self.send_bot_message(
                context,
                update.effective_chat.id,
                'Enter your question text again:',
                reply_markup=reply_markup
            )
            return CREATING_QUESTION

        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation')]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await self.send_bot_message(
            context,
            update.effective_chat.id,
            'Enter four choices for your question, one per line:',
            reply_markup=reply_markup
        )
        return SETTING_CHOICES

    async def generate_progress_image(
        self,
        user_name: str,
        study_time: datetime.timedelta,
        break_time: datetime.timedelta,
        session: StudySession
    ) -> io.BytesIO:
        """Generate a progress image matching the HTML layout."""
        # Create a square canvas (1080x1080)
        width = height = 1080
        image = Image.new('RGB', (width, height), "#1a1a1a")  # Dark background
        draw = ImageDraw.Draw(image)

        try:
            # Load fonts (with fallbacks)
            try:
                title_font = ImageFont.truetype("/usr/share/fonts/truetype/poppins/Poppins-Bold.ttf", 48)
                header_font = ImageFont.truetype("/usr/share/fonts/truetype/poppins/Poppins-Bold.ttf", 40)
                subtitle_font = ImageFont.truetype("/usr/share/fonts/truetype/poppins/Poppins-SemiBold.ttf", 28)
                body_font = ImageFont.truetype("/usr/share/fonts/truetype/poppins/Poppins-Light.ttf", 24)
            except Exception as e:
                logger.error(f"Error loading fonts: {str(e)}")
                title_font = ImageFont.load_default()
                header_font = title_font
                subtitle_font = title_font
                body_font = title_font

            # Draw header section (20px padding)
            header_height = 120
            draw.rectangle(
                [20, 20, width-20, header_height],
                fill="#2d2d2d",
                outline="#404040",
                width=1
            )

            # Draw title
            title_text = "Study Progress Dashboard"
            draw.text(
                (40, 35),
                title_text,
                font=title_font,
                fill="#ffffff"
            )

            # Draw timestamp
            current_time = datetime.datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            draw.text(
                (40, 85),
                f"Generated at: {current_time}",
                font=body_font,
                fill="#888888"
            )

            # Draw main content card (subject info)
            card_y = header_height + 40
            card_height = 400
            draw.rectangle(
                [20, card_y, width-20, card_y + card_height],
                fill="#2d2d2d",
                outline="#404040",
                width=1
            )

            # Draw subject title with emoji
            subject_color = SUBJECT_COLORS.get(session.subject, "#ffffff")
            draw.text(
                (40, card_y + 20),
                f"{session.subject} {SUBJECTS.get(session.subject, '')}",
                font=header_font,
                fill=subject_color
            )

            # Draw progress bar
            progress_y = card_y + 80
            progress_height = 20
            progress_width = width - 80
            
            # Calculate progress if goal is set
            if session.goal_time:
                goal_hours = float(session.goal_time)
                study_hours = study_time.total_seconds() / 3600
                progress = min(study_hours / goal_hours * 100, 100)
            else:
                progress = 100  # Full bar if no goal set

            # Draw progress bar background
            draw.rectangle(
                [40, progress_y, 40 + progress_width, progress_y + progress_height],
                fill="#3d3d3d",
                outline=None
            )

            # Draw progress bar fill
            draw.rectangle(
                [40, progress_y, 40 + (progress_width * progress / 100), progress_y + progress_height],
                fill=subject_color,
                outline=None
            )

            # Draw progress percentage
            progress_text = f"{int(progress)}%"
            draw.text(
                (40 + progress_width - 50, progress_y + 2),
                progress_text,
                font=body_font,
                fill="#ffffff"
            )

            # Draw statistics
            stats_y = progress_y + 40
            stats_data = [
                ("Set Goal:", f"{session.goal_time} hours" if session.goal_time else "No goal set"),
                ("Total Study Time:", f"{int(study_time.total_seconds() // 3600)}h {int((study_time.total_seconds() % 3600) // 60)}m"),
                ("Break Time:", f"{int(break_time.total_seconds() // 3600)}h {int((break_time.total_seconds() % 3600) // 60)}m"),
                ("Study/Break Ratio:", f"{session.study_break_ratio}:1" if session.study_break_ratio else "N/A")
            ]

            for label, value in stats_data:
                draw.text((40, stats_y), label, font=subtitle_font, fill="#cccccc")
                draw.text((width/2, stats_y), value, font=subtitle_font, fill="#ffffff")
                stats_y += 40

            # Draw footer
            footer_y = height - 80
            draw.rectangle(
                [20, footer_y - 20, width-20, footer_y + 40],
                fill="#2d2d2d",
                outline="#404040",
                width=1
            )
            draw.text(
                (width/2, footer_y),
                f"Name: {user_name}, RMT",
                font=header_font,
                fill="#ffffff",
                anchor="mm"
            )

            # Save and return image
            img_byte_arr = io.BytesIO()
            image.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            return img_byte_arr

        except Exception as e:
            logger.error(f"Error generating progress image: {str(e)}")
            # Return a simple error image
            draw.text((width/2, height/2), "Error generating image", font=body_font, fill="#ffffff", anchor="mm")
            img_byte_arr = io.BytesIO()
            image.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            return img_byte_arr

    async def handle_choices_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the choices input."""
        user = update.effective_user
        question = self.current_questions.get(user.id)
        if not question:
            return ConversationHandler.END

        choices = update.message.text.strip().split('\n')
        question.add_user_message(update.message.message_id)

        if len(choices) != 4:
            keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation')]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await self.send_bot_message(
                context,
                update.effective_chat.id,
                'Please enter exactly 4 choices, one per line:',
                reply_markup=reply_markup
            )
            return SETTING_CHOICES

        question.choices = choices

        keyboard = [
            [InlineKeyboardButton(f"{chr(65+i)}", callback_data=f'correct_{i}')]
            for i in range(len(choices))
        ]
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation')])
        reply_markup = InlineKeyboardMarkup(keyboard)

        choices_text = "\n".join(f"{chr(65+i)}. {choice}" for i, choice in enumerate(choices))
        await self.send_bot_message(
            context,
            update.effective_chat.id,
            f"Select the correct answer:\n\n{choices_text}",
            reply_markup=reply_markup
        )
        return SETTING_CORRECT_ANSWER

    async def handle_correct_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle correct answer selection."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        user = update.effective_user
        question = self.current_questions.get(user.id)
        if not question:
            return ConversationHandler.END

        correct_index = int(query.data.split('_')[1])
        question.correct_answer = correct_index

        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation')]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await self.send_bot_message(
            context,
            update.effective_chat.id,
            'Enter an explanation for the correct answer:',
            reply_markup=reply_markup
        )
        return SETTING_EXPLANATION

    async def handle_explanation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle explanation input and save question."""
        user = update.effective_user
        question = self.current_questions.get(user.id)
        question.explanation = update.message.text
        
        # Store user's message for cleanup
        question.add_user_message(update.message.message_id)

        try:
            # Format the question for display
            choices_text = "\n".join(f"{chr(65+i)}. {choice}" 
                               for i, choice in enumerate(question.choices))
        
            # Create keyboard with answer choices
            keyboard = [[InlineKeyboardButton(chr(65+i), callback_data=f'answer_{i}')] 
                       for i in range(len(question.choices))]
            reply_markup = InlineKeyboardMarkup(keyboard)
        
            # Send the final question
            message = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=question.format_for_display(),
                reply_markup=reply_markup,
                message_thread_id=context.user_data.get('thread_id')
            )
        
            # Store the question with the message ID as key
            self.questions[message.message_id] = question
        
            # Clean up and return to main menu
            del self.current_questions[user.id]
        
            keyboard = [
                [InlineKeyboardButton("Create Another Question ❓", callback_data='create_question')],
                [InlineKeyboardButton("Start Studying 📚", callback_data='start_studying')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
        
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Question created successfully! What would you like to do next?",
                reply_markup=reply_markup
            )
        
            return CHOOSING_MAIN_MENU
        
        except Exception as e:
            logger.error(f"Error saving question: {str(e)}")
            return ConversationHandler.END

    async def handle_answer_attempt(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle answer attempts for questions."""
        query = update.callback_query
        await query.answer()

        question = self.questions.get(query.message.message_id)
        if not question:
            return

        answer_index = int(query.data.split('_')[1])
        is_correct = answer_index == question.correct_answer

        response_text = (
            f"{'✅ Correct!' if is_correct else '❌ Incorrect!'}\n\n"
            f"Explanation:\n{question.explanation}"
        )

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=response_text,
            message_thread_id=context.user_data.get('thread_id')
        )

def main() -> None:
    """Start the bot."""
    # Create the Application and pass it your bot's token
    application = Application.builder().token(os.environ["TELEGRAM_TOKEN"]).build()

    # Initialize bot instance
    bot = TelegramBot()

    # Add conversation handler
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

    application.add_handler(conv_handler)

    # Start health check server
    start_health_server()

    # Start the Bot
    application.run_polling()

if __name__ == '__main__':
    main()

