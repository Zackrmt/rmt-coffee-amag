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

# Add specific user and time information
CURRENT_USER = "Zackrmt"
STARTUP_TIME = "2025-06-06 15:28:14"  # Updated to current UTC time

# Set timezone configurations
MANILA_TZ = pytz.timezone('Asia/Manila')
PST_TZ = pytz.timezone('US/Pacific')

logger = logging.getLogger(__name__)

# States for conversation handler
(CHOOSING_MAIN_MENU, SETTING_GOAL, CONFIRMING_GOAL, CHOOSING_SUBJECT,
 STUDYING, ON_BREAK, CREATING_QUESTION, SETTING_CHOICES,
 CONFIRMING_QUESTION, SETTING_CORRECT_ANSWER, SETTING_EXPLANATION,
 CHOOSING_DESIGN) = range(12)

# Helper function to create button grid with 3 columns
def create_button_grid(buttons, columns=3):
    """Create a grid of buttons with specified number of columns."""
    return [buttons[i:i + columns] for i in range(0, len(buttons), columns)]

# Subject emojis (now will be displayed in 3 columns)
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

def load_fonts():
    """Load fonts with proper fallback mechanism."""
    try:
        # Try system fonts (installed by render.yaml)
        font_paths = [
            "/usr/share/fonts/truetype/poppins/Poppins-Bold.ttf",
            "/usr/share/fonts/truetype/poppins/Poppins-SemiBold.ttf",
            "/usr/share/fonts/truetype/poppins/Poppins-Light.ttf"
        ]
        
        # Try alternative paths if main paths fail
        alt_paths = [
            "./fonts/Poppins-Bold.ttf",
            "./fonts/Poppins-SemiBold.ttf",
            "./fonts/Poppins-Light.ttf"
        ]
        
        for main_path, alt_path in zip(font_paths, alt_paths):
            try:
                font = ImageFont.truetype(main_path, 60)
            except:
                try:
                    font = ImageFont.truetype(alt_path, 60)
                except:
                    raise
        
        title_font = ImageFont.truetype(font_paths[0], 60)
        subtitle_font = ImageFont.truetype(font_paths[1], 40)
        body_font = ImageFont.truetype(font_paths[2], 32)
        
        logger.info("Successfully loaded system fonts")
        return title_font, subtitle_font, body_font
    except Exception as e:
        logger.warning(f"Error loading system fonts: {e}")
        # Fallback to default font
        default_font = ImageFont.load_default()
        logger.info("Using default font as fallback")
        return default_font, default_font, default_font

# Load fonts at startup
title_font, subtitle_font, body_font = load_fonts()

# Signal handler for graceful shutdown
def signal_handler(sig, frame):
    logger.info("Received shutdown signal, cleaning up...")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

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
        self.design_choice = 'modern'
        self.thread_id = None

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

    def add_message_to_delete(self, message_id: int):
        """Add a message ID to the list of messages to be deleted."""
        if message_id not in self.messages_to_delete:
            self.messages_to_delete.append(message_id)

    def add_message_to_keep(self, message_id: int):
        """Add a message ID to the list of messages to be kept."""
        if message_id not in self.messages_to_keep:
            self.messages_to_keep.append(message_id)

    def should_delete_message(self, message_id: int) -> bool:
        """Check if a message should be deleted."""
        return (message_id in self.messages_to_delete and 
                message_id not in self.messages_to_keep)


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

    def cleanup_messages(self, messages_to_exclude: List[int] = None) -> List[int]:
        """Get list of messages to clean up, excluding specified messages."""
        if messages_to_exclude is None:
            messages_to_exclude = []
            
        return [msg_id for msg_id in self.messages_to_delete 
                if msg_id not in messages_to_exclude]

class TelegramBot:
    def __init__(self):
        self.study_sessions: Dict[int, StudySession] = {}
        self.questions: Dict[int, Question] = {}
        self.current_questions: Dict[int, Question] = {}
        self.startup_time = "2025-06-06 15:31:11"  # UTC
        self.current_user = "Zackrmt"
        self._start = None

    async def cleanup_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Clean up any existing messages."""
        if 'messages_to_delete' in context.user_data:
            for msg_id in context.user_data['messages_to_delete']:
                try:
                    await context.bot.delete_message(
                        chat_id=update.effective_chat.id,
                        message_id=msg_id
                    )
                except Exception as e:
                    logger.debug(f"Error deleting message {msg_id}: {str(e)}")
            context.user_data['messages_to_delete'] = []

    async def send_bot_message(
        self, context: ContextTypes.DEFAULT_TYPE, 
        chat_id: int, text: str, 
        reply_markup: InlineKeyboardMarkup = None,
        should_delete: bool = True
    ) -> int:
        """Send a message and return its ID."""
        try:
            message = await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                message_thread_id=context.user_data.get('thread_id')
            )
            
            if should_delete:
                if 'messages_to_delete' not in context.user_data:
                    context.user_data['messages_to_delete'] = []
                context.user_data['messages_to_delete'].append(message.message_id)
            
            return message.message_id
            
        except Exception as e:
            logger.error(f"Error sending message: {str(e)}")
            return None

    @property
    def start(self):
        """Property to ensure start method is always available."""
        if self._start is None:
            async def _start_impl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
                await self.cleanup_messages(update, context)
                
                if update.message and update.message.message_thread_id:
                    context.user_data['thread_id'] = update.message.message_thread_id
                    logger.info(f"Starting bot in topic {update.message.message_thread_id}")

                # Create 3-column layout for main menu
                buttons = [
                    InlineKeyboardButton("Start Studying 📚", callback_data='start_studying'),
                    InlineKeyboardButton("Create Questions ❓", callback_data='create_question')
                ]
                keyboard = create_button_grid(buttons)
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

    async def mark_button_clicked(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Mark a button as clicked for cleanup."""
        if update.callback_query and update.callback_query.message:
            if 'clicked_buttons' not in context.user_data:
                context.user_data['clicked_buttons'] = []
            context.user_data['clicked_buttons'].append(
                update.callback_query.message.message_id
            )

    async def delete_message_callback(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Callback for deleting messages after a delay."""
        job = context.job
        try:
            await context.bot.delete_message(
                chat_id=job.data['chat_id'],
                message_id=job.data['message_id']
            )
        except Exception as e:
            logger.debug(f"Error deleting message: {str(e)}")

    async def cancel_operation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle cancellation of any ongoing operation."""
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
        
        # Return to main menu with 3-column layout
        buttons = [
            InlineKeyboardButton("Start Studying 📚", callback_data='start_studying'),
            InlineKeyboardButton("Create Questions ❓", callback_data='create_question')
        ]
        keyboard = create_button_grid(buttons)
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Operation cancelled. What would you like to do?",
            reply_markup=reply_markup
        )
        
        return CHOOSING_MAIN_MENU

    async def ask_goal(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Start study session with goal setting."""
        query = update.callback_query
        if query:
            await query.answer()
            await self.cleanup_messages(update, context)

        # Create 3-column layout for goal selection
        buttons = [
            InlineKeyboardButton("1 hour", callback_data='goal_1'),
            InlineKeyboardButton("2 hours", callback_data='goal_2'),
            InlineKeyboardButton("3 hours", callback_data='goal_3'),
            InlineKeyboardButton("4 hours", callback_data='goal_4'),
            InlineKeyboardButton("5 hours", callback_data='goal_5'),
            InlineKeyboardButton("6 hours", callback_data='goal_6'),
            InlineKeyboardButton("No Goal", callback_data='no_goal'),
            InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation')
        ]
        keyboard = create_button_grid(buttons, 3)  # 3 columns
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

    async def handle_goal_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the selected study goal time."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        user = update.effective_user
        session = self.study_sessions.get(user.id)
        
        if query.data == 'no_goal':
            goal_time = None
        else:
            hours = int(query.data.split('_')[1])
            goal_time = f"{hours}"

        # Create subject selection keyboard with 3 columns
        buttons = []
        for subject, code in SUBJECTS.items():
            buttons.append(InlineKeyboardButton(subject, callback_data=f"subject_{code}"))
        buttons.append(InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation'))
        
        keyboard = create_button_grid(buttons, 3)  # 3 columns
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
        """Start the study session."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        subject_code = query.data.replace('subject_', '')
        user = update.effective_user
        session = self.study_sessions[user.id]
        
        # Start session
        session.start(subject_code)

        # Create 3-column layout for study controls
        buttons = [
            InlineKeyboardButton("Start Break ☕", callback_data='start_break'),
            InlineKeyboardButton("End Study Session 🎯", callback_data='end_session')
        ]
        keyboard = create_button_grid(buttons, 3)  # 3 columns
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
                should_delete=False  # Keep this message
            )
            
            # Store message ID to remove buttons later
            if 'button_messages' not in context.user_data:
                context.user_data['button_messages'] = []
            context.user_data['button_messages'].append(message_id)
            
            return STUDYING
            
        except Exception as e:
            logger.error(f"Error starting study session: {str(e)}")
            return ConversationHandler.END

    async def handle_break(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle break actions with button cleanup."""
        query = update.callback_query
        await query.answer()
        
        # Remove buttons from previous message
        if 'button_messages' in context.user_data:
            for msg_id in context.user_data['button_messages']:
                try:
                    await context.bot.edit_message_reply_markup(
                        chat_id=update.effective_chat.id,
                        message_id=msg_id,
                        reply_markup=None
                    )
                except Exception as e:
                    logger.debug(f"Error removing buttons: {str(e)}")
            context.user_data['button_messages'] = []

        user = update.effective_user
        session = self.study_sessions.get(user.id)
        
        if query.data == 'start_break':
            session.start_break()
            buttons = [
                InlineKeyboardButton("End Break ⏰", callback_data='end_break'),
                InlineKeyboardButton("End Study Session 🎯", callback_data='end_session')
            ]
            keyboard = create_button_grid(buttons, 3)  # 3 columns
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                message_id = await self.send_bot_message(
                    context,
                    update.effective_chat.id,
                    f"☕ {user.first_name} started their break.",
                    reply_markup=reply_markup,
                    should_delete=False
                )
                context.user_data['button_messages'].append(message_id)
                return ON_BREAK
                
            except Exception as e:
                logger.error(f"Error starting break: {str(e)}")
                return ConversationHandler.END
                
        else:  # end_break
            session.end_break()
            buttons = [
                InlineKeyboardButton("Start Break ☕", callback_data='start_break'),
                InlineKeyboardButton("End Study Session 🎯", callback_data='end_session')
            ]
            keyboard = create_button_grid(buttons, 3)  # 3 columns
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                message_id = await self.send_bot_message(
                    context,
                    update.effective_chat.id,
                    f"⏰ {user.first_name} ended their break and resumed studying.",
                    reply_markup=reply_markup,
                    should_delete=False
                )
                context.user_data['button_messages'].append(message_id)
                return STUDYING
                
            except Exception as e:
                logger.error(f"Error ending break: {str(e)}")
                return ConversationHandler.END

    async def start_creating_question(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Start question creation with subject selection."""
        query = update.callback_query
        if query:
            await query.answer()
            await self.cleanup_messages(update, context)

        # Create subject selection keyboard with 3 columns
        buttons = []
        for subject, code in SUBJECTS.items():
            buttons.append(InlineKeyboardButton(subject, callback_data=f"qsubject_{code}"))
        buttons.append(InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation'))
        keyboard = create_button_grid(buttons, 3)  # 3 columns
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                "What subject is this question for?",
                reply_markup=reply_markup
            )
            
            # Initialize new question
            user = update.effective_user
            question = Question(user.id, user.first_name)
            question.thread_id = context.user_data.get('thread_id')
            self.current_questions[user.id] = question
            
            return CREATING_QUESTION
        except Exception as e:
            logger.error(f"Error starting question creation: {str(e)}")
            return ConversationHandler.END

    async def handle_subject_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle subject selection for question creation."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        subject_code = query.data.replace('qsubject_', '')
        context.user_data['current_subject'] = subject_code

        buttons = [InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation')]
        keyboard = create_button_grid(buttons, 3)  # 3 columns
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"Creating a question for {subject_code}. Please type your question:",
                reply_markup=reply_markup
            )
            return CREATING_QUESTION
        except Exception as e:
            logger.error(f"Error handling subject selection: {str(e)}")
            return ConversationHandler.END

    async def handle_question_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle question text input with confirmation."""
        user = update.effective_user
        question = self.current_questions.get(user.id)
        question.question_text = update.message.text
        
        # Store user's message for cleanup
        question.add_user_message(update.message.message_id)

        # Create 3-column layout for confirmation
        buttons = [
            InlineKeyboardButton("Yes", callback_data='confirm_question'),
            InlineKeyboardButton("No", callback_data='retry_question'),
            InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation')
        ]
        keyboard = create_button_grid(buttons, 3)  # 3 columns
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"Is this your question?\n\n{question.question_text}",
                reply_markup=reply_markup
            )
            return CONFIRMING_QUESTION
        except Exception as e:
            logger.error(f"Error handling question text: {str(e)}")
            return ConversationHandler.END

    async def handle_question_confirmation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle question confirmation."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        if query.data == 'retry_question':
            buttons = [InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation')]
            keyboard = create_button_grid(buttons, 3)  # 3 columns
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Please type your question again:",
                reply_markup=reply_markup
            )
            return CREATING_QUESTION

        # If confirmed, proceed to choices
        buttons = [InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation')]
        keyboard = create_button_grid(buttons, 3)  # 3 columns
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Please enter your choices, one per line:\nExample:\nChoice 1\nChoice 2\nChoice 3\nChoice 4",
            reply_markup=reply_markup
        )
        return SETTING_CHOICES

    async def handle_choices_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle multiple choice input at once."""
        user = update.effective_user
        question = self.current_questions.get(user.id)
        
        # Split the message into lines for choices
        choices = [choice.strip() for choice in update.message.text.split('\n') if choice.strip()]
        
        # Store user's message for cleanup
        question.add_user_message(update.message.message_id)
        
        if len(choices) < 2:
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Please provide at least 2 choices. Enter your choices again (one per line):"
            )
            return SETTING_CHOICES
        
        # Store choices
        question.choices = choices
        
        # Show choices for confirmation with 3-column layout
        choices_text = "\n".join(f"{chr(65+i)}. {choice}" 
                               for i, choice in enumerate(choices))
        
        # Create 3-column layout for answer selection
        buttons = [InlineKeyboardButton(chr(65+i), callback_data=f'correct_{i}') 
                  for i in range(len(choices))]
        buttons.append(InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation'))
        keyboard = create_button_grid(buttons, 3)  # 3 columns
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_id = await self.send_bot_message(
            context,
            update.effective_chat.id,
            f"Select the correct answer:\n\n{choices_text}",
            reply_markup=reply_markup
        )
        return SETTING_CORRECT_ANSWER

    async def handle_correct_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle correct answer selection and proceed to explanation."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        user = update.effective_user
        question = self.current_questions.get(user.id)
        
        # Store correct answer
        answer_index = int(query.data.split('_')[1])
        question.correct_answer = answer_index

        # Create 3-column layout for cancel button
        buttons = [InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation')]
        keyboard = create_button_grid(buttons, 3)
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Please provide an explanation for the correct answer:",
            reply_markup=reply_markup
        )
        return SETTING_EXPLANATION

    async def handle_explanation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle explanation input and finalize question creation."""
        user = update.effective_user
        question = self.current_questions.get(user.id)
        question.explanation = update.message.text
        
        # Store user's message for cleanup
        question.add_user_message(update.message.message_id)

        # Format the complete question for preview
        choices_text = "\n".join(f"{chr(65+i)}. {choice}" 
                               for i, choice in enumerate(question.choices))
        preview = (
            f"Question Preview:\n\n"
            f"{question.question_text}\n\n"
            f"{choices_text}\n\n"
            f"Correct Answer: {chr(65 + question.correct_answer)}\n\n"
            f"Explanation:\n{question.explanation}"
        )

        # Create 3-column layout for final actions
        buttons = [
            InlineKeyboardButton("✅ Save", callback_data='save_question'),
            InlineKeyboardButton("🔄 Start Over", callback_data='create_question'),
            InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation')
        ]
        keyboard = create_button_grid(buttons, 3)
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                preview,
                reply_markup=reply_markup
            )
            return CHOOSING_DESIGN
        except Exception as e:
            logger.error(f"Error handling explanation: {str(e)}")
            return ConversationHandler.END

    async def handle_design_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Save the question and show it with the selected design."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        user = update.effective_user
        question = self.current_questions.get(user.id)
        
        try:
            # Format the question for display
            choices_text = "\n".join(f"{chr(65+i)}. {choice}" 
                                   for i, choice in enumerate(question.choices))
            
            # Create 3-column layout for answer choices
            buttons = [InlineKeyboardButton(chr(65+i), callback_data=f'answer_{i}') 
                      for i in range(len(question.choices))]
            keyboard = create_button_grid(buttons, 3)
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
            
            # Create 3-column layout for next actions
            buttons = [
                InlineKeyboardButton("Create Another Question ❓", callback_data='create_question'),
                InlineKeyboardButton("Start Studying 📚", callback_data='start_studying')
            ]
            keyboard = create_button_grid(buttons, 3)
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
        """Handle question answering with effects and timed deletion."""
        query = update.callback_query
        await query.answer()

        try:
            question_id = int(query.message.message_id)
            question = self.questions.get(question_id)
            if not question:
                return

            answer_index = int(query.data.split('_')[1])
            user = query.from_user
            
            # Convert PST time to Manila time for display
            manila_time = datetime.datetime.now(PST_TZ).astimezone(MANILA_TZ)
            time_str = manila_time.strftime("%I:%M %p")
            
            # Send effect message based on correctness
            if answer_index == question.correct_answer:
                effect_message = await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"🎉 Congratulations! [{time_str}]\nNag-aral ka no {user.first_name}!?",
                    message_thread_id=context.user_data.get('thread_id')
                )
            else:
                effect_message = await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"💥 Boom! [{time_str}]\nYou need to study more {user.first_name}!",
                    message_thread_id=context.user_data.get('thread_id')
                )

            # Schedule effect message deletion after 5 seconds
            context.job_queue.run_once(
                self.delete_message_callback,
                5,
                data={
                    'chat_id': update.effective_chat.id,
                    'message_id': effect_message.message_id
                }
            )

            # Wait 3 seconds before showing explanation
            await asyncio.sleep(3)

            # Send explanation with Manila time
            explanation_message = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"Explanation [{time_str}]:\n{question.explanation}",
                message_thread_id=context.user_data.get('thread_id')
            )

            # Schedule explanation deletion
            context.job_queue.run_once(
                self.delete_message_callback,
                8,  # Delete after 8 seconds (5 seconds display + 3 seconds delay)
                data={
                    'chat_id': update.effective_chat.id,
                    'message_id': explanation_message.message_id
                }
            )

        except Exception as e:
            logger.error(f"Error handling answer attempt: {str(e)}")

    async def end_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """End study session and show progress."""
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

        # Format break times
        break_texts = []
        for break_session in manila_times['breaks']:
            break_start = break_session['start'].strftime("%I:%M %p")
            break_end = break_session['end'].strftime("%I:%M %p")
            break_texts.append(f"Break: {break_start} - {break_end}")

        # Create summary message
        summary = [
            f"📚 Study Session Summary",
            f"Subject: {session.subject}",
            f"Started: {start_time}",
            f"Ended: {end_time}",
            f"\nTotal Study Time: {int(study_time.total_seconds() // 3600)}h {int((study_time.total_seconds() % 3600) // 60)}m",
            f"Total Break Time: {int(break_time.total_seconds() // 3600)}h {int((break_time.total_seconds() % 3600) // 60)}m"
        ]

        if session.goal_time:
            goal_hours = int(session.goal_time)
            goal_minutes = goal_hours * 60
            actual_minutes = study_time.total_seconds() / 60
            progress = (actual_minutes / goal_minutes) * 100
            summary.append(f"\nGoal Progress: {min(100, int(progress))}%")

        if break_texts:
            summary.append("\nBreak Details:")
            summary.extend(break_texts)

        # Store times in context for progress image
        context.user_data['study_time'] = study_time
        context.user_data['break_time'] = break_time

        # Create 3-column layout for end session options
        buttons = [
            InlineKeyboardButton("Share Progress 📊", callback_data='share_progress'),
            InlineKeyboardButton("Start New Session 📚", callback_data='start_studying')
        ]
        keyboard = create_button_grid(buttons, 3)
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            # Send summary message
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "\n".join(summary),
                reply_markup=reply_markup,
                should_delete=False
            )

            # Clean up session
            del self.study_sessions[user.id]
            return CHOOSING_DESIGN

        except Exception as e:
            logger.error(f"Error ending session: {str(e)}")
            return ConversationHandler.END

    async def generate_progress_image(
        self, user_name: str, 
        study_time: datetime.timedelta, 
        break_time: datetime.timedelta
    ) -> io.BytesIO:
        """Generate a square progress image suitable for Instagram."""
        # Create a square canvas (1080x1080 for Instagram)
        width = height = 1080
        image = Image.new('RGB', (width, height))
        draw = ImageDraw.Draw(image)

        try:
            # Try to use system fonts (installed by render.yaml)
            title_font = ImageFont.truetype("/usr/share/fonts/truetype/poppins/Poppins-Bold.ttf", 60)
            subtitle_font = ImageFont.truetype("/usr/share/fonts/truetype/poppins/Poppins-SemiBold.ttf", 40)
            body_font = ImageFont.truetype("/usr/share/fonts/truetype/poppins/Poppins-Light.ttf", 32)
        except Exception as e:
            logger.warning(f"Error loading system fonts: {e}")
            # Final fallback to default font
            title_font = ImageFont.load_default()
            subtitle_font = title_font
            body_font = title_font
            
        # Background colors (dark theme)
        background_color = "#1a1a1a"
        card_color = "#2d2d2d"
        border_color = "#404040"
        text_color = "#ffffff"
        accent_color = "#3d3d3d"

        # Fill background
        draw.rectangle([0, 0, width, height], fill=background_color)

        # Header section (top 20%)
        header_height = height * 0.2
        draw.rectangle([20, 20, width-20, header_height], 
                      fill=card_color, outline=border_color, width=1)

        # Draw title
        draw.text((width/2, 50), "Study Progress Dashboard - MTLE 2025",
                 font=title_font, fill=text_color, anchor="mt")

        # Convert PST to Manila time
        manila_time = datetime.datetime.now(PST_TZ).astimezone(MANILA_TZ)
        time_str = manila_time.strftime("%Y-%m-%d %I:%M %p")

        # Draw timestamp and creator
        draw.text((width/2, 100), f"Generated at: {time_str} (Manila)",
                 font=subtitle_font, fill="#888888", anchor="mt")
        draw.text((width/2, 140), "Study bot created by Eli",
                 font=body_font, fill="#888888", anchor="mt")

        # Progress section (middle 60%)
        progress_start = header_height + 40
        progress_height = height * 0.6

        # Format study times
        study_hours = int(study_time.total_seconds() // 3600)
        study_minutes = int((study_time.total_seconds() % 3600) // 60)
        break_hours = int(break_time.total_seconds() // 3600)
        break_minutes = int((break_time.total_seconds() % 3600) // 60)

        # Study statistics card
        stats_card_height = 200
        draw.rectangle([20, progress_start, width-20, progress_start + stats_card_height],
                      fill=card_color, outline=border_color, width=1)

        # Study time progress bar
        progress_bar_height = 20
        progress_bar_y = progress_start + 80
        draw.rectangle([40, progress_bar_y, width-40, progress_bar_y + progress_bar_height],
                      fill=accent_color)
        
        # Calculate progress (example: based on 4-hour standard)
        target_hours = 4
        progress = min(study_time.total_seconds() / (target_hours * 3600), 1.0)
        progress_width = (width - 80) * progress
        
        # Draw progress bar
        draw.rectangle([40, progress_bar_y, 40 + progress_width, progress_bar_y + progress_bar_height],
                      fill="#FF5733")

        # Study statistics
        stats_y = progress_start + 120
        draw.text((40, stats_y), f"Study Time: {study_hours:02d}:{study_minutes:02d}",
                 font=body_font, fill=text_color)
        draw.text((width-40, stats_y), f"Break Time: {break_hours:02d}:{break_minutes:02d}",
                 font=body_font, fill=text_color, anchor="ra")

        # Footer section (bottom 20%)
        footer_start = height - (height * 0.2)
        draw.rectangle([20, footer_start, width-20, height-20],
                      fill=card_color, outline=border_color, width=1)
        
        # Draw user name
        draw.text((width/2, footer_start + 40), f"Name: {user_name}, RMT",
                 font=subtitle_font, fill=text_color, anchor="mm")

        # Save image
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)

        return img_byte_arr

    async def show_progress_image(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Show progress image with Manila time."""
        query = update.callback_query
        await query.answer()

        user = update.effective_user
        study_time = context.user_data.get('study_time', datetime.timedelta())
        break_time = context.user_data.get('break_time', datetime.timedelta())

        try:
            # Generate image
            img_bytes = await self.generate_progress_image(
                user.first_name,
                study_time,
                break_time
            )

            # Send progress image
            photo_message = await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=img_bytes,
                caption=f"📊 Study Progress for {user.first_name}",
                message_thread_id=context.user_data.get('thread_id')
            )

            # Store message ID for potential cleanup
            if 'messages_to_keep' not in context.user_data:
                context.user_data['messages_to_keep'] = []
            context.user_data['messages_to_keep'].append(photo_message.message_id)

            # Create 3-column layout for next action
            buttons = [InlineKeyboardButton("Start New Study Session 📚", callback_data='start_studying')]
            keyboard = create_button_grid(buttons, 3)
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Ready to start another study session?",
                reply_markup=reply_markup
            )
            
            return CHOOSING_MAIN_MENU

        except Exception as e:
            logger.error(f"Error generating/sending image: {str(e)}")
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Sorry, there was an error generating your progress image. Please try again."
            )
            return ConversationHandler.END


def main():
    """Start the bot."""
    # Add startup logging with current timestamp
    startup_time = "2025-06-06 15:37:42"  # Current UTC time
    current_user = "Zackrmt"
    
    logger.info(f"Bot starting at {startup_time} UTC")
    logger.info(f"Started by user: {current_user}")
    logger.info("Initializing bot application...")
    
    # Health check server setup
    try:
        port = int(os.getenv('HEALTH_CHECK_PORT', 10001))
        start_health_server(port)
        logger.info(f"Health check server started on port {port}")
    except Exception as e:
        logger.error(f"Error starting health check server: {str(e)}")
        # Continue anyway as this is not critical

    # Initialize bot with token from environment
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        logger.error("No TELEGRAM_TOKEN provided")
        sys.exit(1)

    application = Application.builder().token(token).build()
    bot = TelegramBot()
    logger.info("Setting up conversation handlers...")
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', lambda u, c: bot.start(u, c))],
        states={
            CHOOSING_MAIN_MENU: [
                CallbackQueryHandler(bot.ask_goal, pattern='^start_studying$'),
                CallbackQueryHandler(bot.start_creating_question, pattern='^create_question$')
            ],
            SETTING_GOAL: [
                CallbackQueryHandler(bot.handle_goal_selection, pattern='^goal_'),
                CallbackQueryHandler(bot.handle_goal_selection, pattern='^no_goal$'),
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
                CallbackQueryHandler(bot.show_progress_image, pattern='^share_progress$'),
                CallbackQueryHandler(bot.cancel_operation, pattern='^cancel_operation$')
            ]
        },
        fallbacks=[
            CommandHandler('start', lambda u, c: bot.start(u, c)),
            CallbackQueryHandler(bot.cancel_operation, pattern='^cancel_operation$'),
            CallbackQueryHandler(bot.show_progress_image, pattern='^share_progress$'),
            CallbackQueryHandler(bot.handle_answer_attempt, pattern='^answer_')
        ],
        per_message=True,  # Changed to True to handle callbacks properly
        per_chat=True,
        name="main_conversation"  # Added name for better logging
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
    webhook_url = os.getenv('WEBHOOK_URL')
    port = int(os.getenv('PORT', 10000))
    
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

