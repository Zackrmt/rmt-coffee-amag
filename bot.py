import logging
import os
from datetime import datetime, timezone, timedelta
import pytz
import io
from PIL import Image, ImageDraw, ImageFont
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
from dotenv import load_dotenv
from healthcheck import start_health_server

# Load environment variables
load_dotenv()

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states
CHOOSING_MAIN_MENU = 0
SETTING_GOAL = 1
SETTING_CUSTOM_GOAL = 2
CHOOSING_SUBJECT = 3
STUDYING = 4
ON_BREAK = 5
CREATING_QUESTION = 6
CONFIRMING_QUESTION = 7
SETTING_CHOICES = 8
SETTING_CORRECT_ANSWER = 9
SETTING_EXPLANATION = 10

# Subject definitions with emojis
SUBJECTS = {
    "Math": "📐",
    "Science": "🔬",
    "English": "📚",
    "History": "📜",
    "Geography": "🌍",
    "Computer": "💻",
    "Physics": "⚡",
    "Chemistry": "🧪",
    "Biology": "🧬",
    "Language": "🗣️",
    "Economics": "📊",
    "Business": "💼",
    "Art": "🎨",
    "Music": "🎵",
    "Physical Ed": "⚽",
    "Other": "📝"
}

# Subject colors for progress image
SUBJECT_COLORS = {
    "Math": "#FF6B6B",
    "Science": "#4ECDC4",
    "English": "#45B7D1",
    "History": "#96CEB4",
    "Geography": "#FFEEAD",
    "Computer": "#4D96FF",
    "Physics": "#FFD93D",
    "Chemistry": "#6C5CE7",
    "Biology": "#A8E6CF",
    "Language": "#FF8B94",
    "Economics": "#98DDCA",
    "Business": "#D4A5A5",
    "Art": "#FFB6B9",
    "Music": "#957DAD",
    "Physical Ed": "#9ADCFF",
    "Other": "#B5EAEA"
}

class StudySession:
    def __init__(self):
        self.start_time = None
        self.end_time = None
        self.subject = None
        self.goal_time = None
        self.breaks = []
        self.current_break = None
        self.permanent_messages = []
        self.thread_id = None

    def start(self, subject, goal_time=None):
        """Start a new study session."""
        self.start_time = datetime.now(timezone.utc)
        self.subject = subject
        self.goal_time = goal_time
        self.breaks = []
        self.current_break = None
        self.permanent_messages = []

    def end(self):
        """End the current study session."""
        self.end_time = datetime.now(timezone.utc)

    def start_break(self):
        """Start a break."""
        self.current_break = {
            'start': datetime.now(timezone.utc),
            'end': None
        }

    def end_break(self):
        """End the current break."""
        if self.current_break:
            self.current_break['end'] = datetime.now(timezone.utc)
            self.breaks.append(self.current_break)
            self.current_break = None

    @property
    def total_study_time(self):
        """Calculate total study time excluding breaks."""
        if not self.start_time:
            return timedelta()

        end = self.end_time or datetime.now(timezone.utc)
        total = end - self.start_time

        # Subtract break times
        break_time = self.total_break_time
        return total - break_time

    @property
    def total_break_time(self):
        """Calculate total break time."""
        total = timedelta()
        
        # Add completed breaks
        for break_period in self.breaks:
            total += break_period['end'] - break_period['start']

        # Add current break if exists
        if self.current_break:
            current_end = datetime.now(timezone.utc)
            total += current_end - self.current_break['start']

        return total

    @property
    def study_break_ratio(self):
        """Calculate the ratio of study time to break time."""
        study_seconds = self.total_study_time.total_seconds()
        break_seconds = self.total_break_time.total_seconds()

        if break_seconds == 0:
            return study_seconds if study_seconds > 0 else 0
        return round(study_seconds / break_seconds, 2)

    def get_manila_time(self, dt):
        """Convert UTC time to Manila time."""
        manila_tz = pytz.timezone('Asia/Manila')
        return dt.astimezone(manila_tz)

class Question:
    def __init__(self, user_id, username):
        self.user_id = user_id
        self.username = username
        self.question_text = None
        self.choices = []
        self.correct_answer = None
        self.explanation = None
        self.thread_id = None
        self.user_messages = []

    def add_user_message(self, message_id):
        """Add a message ID to be cleaned up later."""
        self.user_messages.append(message_id)

    def format_for_display(self):
        """Format the question for display."""
        if not self.question_text or not self.choices:
            return "Question not fully formed"

        choices_text = "\n".join(f"{chr(65+i)}. {choice}" 
                               for i, choice in enumerate(self.choices))
        return f"{self.question_text}\n\n{choices_text}"

class TelegramBot:
    def __init__(self):
        """Initialize the bot with necessary containers."""
        self.study_sessions = {}  # {user_id: StudySession}
        self.current_questions = {}  # {user_id: Question}
        self.questions = {}  # {message_id: Question}
        self.permanent_messages = {}  # {user_id: [message_ids]}

    async def cleanup_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Clean up old messages to keep chat tidy."""
        user_id = update.effective_user.id
        
        # Clean up permanent messages
        if user_id in self.permanent_messages:
            for msg_id in self.permanent_messages[user_id]:
                try:
                    await context.bot.delete_message(
                        chat_id=update.effective_chat.id,
                        message_id=msg_id
                    )
                except Exception as e:
                    logger.error(f"Error deleting message: {str(e)}")
            self.permanent_messages[user_id] = []

        # Clean up question messages
        question = self.current_questions.get(user_id)
        if question:
            for msg_id in question.user_messages:
                try:
                    await context.bot.delete_message(
                        chat_id=update.effective_chat.id,
                        message_id=msg_id
                    )
                except Exception as e:
                    logger.error(f"Error deleting question message: {str(e)}")
            question.user_messages = []

    async def send_bot_message(self, context, chat_id, text, reply_markup=None):
        """Send a message and store it for cleanup."""
        message = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            message_thread_id=context.user_data.get('thread_id')
        )
        
        user_id = chat_id  # In private chats, chat_id is the same as user_id
        if user_id not in self.permanent_messages:
            self.permanent_messages[user_id] = []
        self.permanent_messages[user_id].append(message.message_id)
        
        return message

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Start the bot conversation."""
        user = update.effective_user
        
        # Store the thread_id if message is in a forum topic
        if update.message and update.message.is_topic_message:
            context.user_data['thread_id'] = update.message.message_thread_id

        # Clean up any existing messages
        await self.cleanup_messages(update, context)

        # Create keyboard for main menu
        keyboard = [
            [InlineKeyboardButton("Start Studying 📚", callback_data='start_studying')],
            [InlineKeyboardButton("Create Questions ❓", callback_data='create_question')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Send welcome message
        welcome_text = (
            f"Hello {user.first_name}! 👋\n\n"
            "I'm your study assistant bot. I can help you:\n"
            "📚 Track your study sessions\n"
            "⏰ Manage your breaks\n"
            "❓ Create and practice with questions\n\n"
            "What would you like to do?"
        )

        await self.send_bot_message(
            context,
            update.effective_chat.id,
            welcome_text,
            reply_markup=reply_markup
        )

        return CHOOSING_MAIN_MENU

    async def cancel_operation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancel the current operation and return to main menu."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        user_id = update.effective_user.id
        
        # Clean up any active sessions or questions
        if user_id in self.study_sessions:
            del self.study_sessions[user_id]
        if user_id in self.current_questions:
            del self.current_questions[user_id]

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

    async def start_studying(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Start studying process by asking for goal."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        keyboard = [
            [InlineKeyboardButton("30 minutes", callback_data='goal_1')],
            [InlineKeyboardButton("1 hour", callback_data='goal_2')],
            [InlineKeyboardButton("2 hours", callback_data='goal_3')],
            [InlineKeyboardButton("3 hours", callback_data='goal_4')],
            [InlineKeyboardButton("4 hours", callback_data='goal_5')],
            [InlineKeyboardButton("5 hours", callback_data='goal_6')],
            [InlineKeyboardButton("Custom Goal ⚡", callback_data='goal_custom')],
            [InlineKeyboardButton("No Goal 🎯", callback_data='no_goal')],
            [InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Let's set a study goal! How long do you plan to study?",
            reply_markup=reply_markup
        )

        return SETTING_GOAL

    async def handle_goal_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the goal selection and move to subject selection."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        user = update.effective_user
        goal_data = query.data

        # Initialize study session
        session = StudySession()
        self.study_sessions[user.id] = session
        session.thread_id = context.user_data.get('thread_id')

        # Set goal time based on selection
        if goal_data == 'no_goal':
            goal_time = None
        else:
            goal_hours = {
                'goal_1': 0.5,
                'goal_2': 1,
                'goal_3': 2,
                'goal_4': 3,
                'goal_5': 4,
                'goal_6': 5
            }.get(goal_data)
            if goal_hours:
                goal_time = timedelta(hours=goal_hours)
            else:
                return SETTING_CUSTOM_GOAL

        # Create subject selection keyboard
        keyboard = [
            [InlineKeyboardButton(f"{subject} {emoji}", callback_data=f'subject_{subject}')]
            for subject, emoji in SUBJECTS.items()
        ]
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation')])
        reply_markup = InlineKeyboardMarkup([row for row in keyboard])

        goal_text = (
            "No specific goal set."
            if goal_time is None
            else f"Goal set: {goal_time.total_seconds()/3600:.1f} hours"
        )

        await self.send_bot_message(
            context,
            update.effective_chat.id,
            f"{goal_text}\nNow, choose your subject:",
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
            "Enter your goal time in minutes:",
            reply_markup=reply_markup
        )

        return SETTING_CUSTOM_GOAL

    async def process_custom_goal(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Process the custom goal time input."""
        try:
            minutes = int(update.message.text)
            if minutes <= 0:
                raise ValueError("Time must be positive")
            
            user = update.effective_user
            session = StudySession()
            self.study_sessions[user.id] = session
            session.thread_id = context.user_data.get('thread_id')

            # Create subject selection keyboard
            keyboard = [
                [InlineKeyboardButton(f"{subject} {emoji}", callback_data=f'subject_{subject}')]
                for subject, emoji in SUBJECTS.items()
            ]
            keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation')])
            reply_markup = InlineKeyboardMarkup([row for row in keyboard])

            await self.cleanup_messages(update, context)
            
            goal_hours = minutes / 60
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"Goal set: {goal_hours:.1f} hours\nNow, choose your subject:",
                reply_markup=reply_markup
            )

            return CHOOSING_SUBJECT

        except ValueError:
            keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation')]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Please enter a valid number of minutes:",
                reply_markup=reply_markup
            )

            return SETTING_CUSTOM_GOAL

    async def handle_subject_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle subject selection and start the study session."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        user = update.effective_user
        subject = query.data.replace('subject_', '')
        session = self.study_sessions.get(user.id)

        if not session:
            return await self.cancel_operation(update, context)

        # Start the session with selected subject
        session.start(subject, session.goal_time)

        keyboard = [
            [InlineKeyboardButton("Take Break ☕", callback_data='take_break')],
            [InlineKeyboardButton("End Session 🏁", callback_data='end_session')],
            [InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        study_message = (
            f"📚 Studying {subject} {SUBJECTS[subject]}\n"
            f"Started at: {session.get_manila_time(session.start_time).strftime('%I:%M %p')}\n"
        )

        if session.goal_time:
            study_message += f"Goal: {session.goal_time.total_seconds()/3600:.1f} hours"

        await self.send_bot_message(
            context,
            update.effective_chat.id,
            study_message,
            reply_markup=reply_markup
        )

        return STUDYING

    async def handle_break(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle break time during study session."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        user = update.effective_user
        session = self.study_sessions.get(user.id)

        if not session:
            return await self.cancel_operation(update, context)

        session.start_break()

        keyboard = [
            [InlineKeyboardButton("Resume Studying 📚", callback_data='resume_studying')],
            [InlineKeyboardButton("End Session 🏁", callback_data='end_session')],
            [InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        break_message = (
            f"☕ Break Time!\n"
            f"Study time so far: {int(session.total_study_time.total_seconds() // 3600)}h "
            f"{int((session.total_study_time.total_seconds() % 3600) // 60)}m\n"
            f"Break started at: {session.get_manila_time(session.current_break['start']).strftime('%I:%M %p')}"
        )

        await self.send_bot_message(
            context,
            update.effective_chat.id,
            break_message,
            reply_markup=reply_markup
        )

        return ON_BREAK

    async def resume_studying(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Resume studying after a break."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        user = update.effective_user
        session = self.study_sessions.get(user.id)

        if not session:
            return await self.cancel_operation(update, context)

        session.end_break()

        keyboard = [
            [InlineKeyboardButton("Take Break ☕", callback_data='take_break')],
            [InlineKeyboardButton("End Session 🏁", callback_data='end_session')],
            [InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        resume_message = (
            f"📚 Resuming {session.subject} {SUBJECTS[session.subject]}\n"
            f"Total study time: {int(session.total_study_time.total_seconds() // 3600)}h "
            f"{int((session.total_study_time.total_seconds() % 3600) // 60)}m\n"
            f"Total break time: {int(session.total_break_time.total_seconds() // 3600)}h "
            f"{int((session.total_break_time.total_seconds() % 3600) // 60)}m"
        )

        await self.send_bot_message(
            context,
            update.effective_chat.id,
            resume_message,
            reply_markup=reply_markup
        )

        return STUDYING

    async def end_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """End the current study session and display statistics."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        user = update.effective_user
        session = self.study_sessions.get(user.id)
        
        if not session:
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "No active study session found."
            )
            return ConversationHandler.END

        # End the session and get statistics
        session.end()
        study_time = session.total_study_time
        break_time = session.total_break_time

        try:
            # Generate progress image
            image_data = await self.generate_progress_image(
                user.first_name,
                study_time,
                break_time,
                session
            )

            # Send final statistics with image
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=image_data,
                caption=(
                    f"Session ended!\n\n"
                    f"Subject: {session.subject}\n"
                    f"Total Study Time: {int(study_time.total_seconds() // 3600)}h "
                    f"{int((study_time.total_seconds() % 3600) // 60)}m\n"
                    f"Total Break Time: {int(break_time.total_seconds() // 3600)}h "
                    f"{int((break_time.total_seconds() % 3600) // 60)}m\n"
                    f"Study/Break Ratio: {session.study_break_ratio:.1f}:1"
                ),
                message_thread_id=context.user_data.get('thread_id')
            )

            # Clean up session
            del self.study_sessions[user.id]

            # Return to main menu
            keyboard = [
                [InlineKeyboardButton("Start New Session 📚", callback_data='start_studying')],
                [InlineKeyboardButton("Create Questions ❓", callback_data='create_question')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "What would you like to do next?",
                reply_markup=reply_markup
            )

            return CHOOSING_MAIN_MENU

        except Exception as e:
            logging.error(f"Error ending session: {str(e)}")
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "An error occurred while ending the session. Please try again."
            )
            return STUDYING

    async def create_question(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Start the question creation process."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        user = update.effective_user
        question = Question(user.id, user.username)
        self.current_questions[user.id] = question
        question.thread_id = context.user_data.get('thread_id')

        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation')]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Please enter your question:",
            reply_markup=reply_markup
        )

        return CREATING_QUESTION

    async def process_question_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Process the question text and ask for choices."""
        user = update.effective_user
        question = self.current_questions.get(user.id)

        if not question:
            return await self.cancel_operation(update, context)

        question.question_text = update.message.text
        question.add_user_message(update.message.message_id)

        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation')]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await self.cleanup_messages(update, context)
        await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Enter your choices one by one. Send 'done' when finished:",
            reply_markup=reply_markup
        )

        return SETTING_CHOICES

    async def process_choice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Process each choice for the question."""
        user = update.effective_user
        question = self.current_questions.get(user.id)

        if not question:
            return await self.cancel_operation(update, context)

        choice_text = update.message.text.strip()
        question.add_user_message(update.message.message_id)

        if choice_text.lower() == 'done':
            if len(question.choices) < 2:
                await self.send_bot_message(
                    context,
                    update.effective_chat.id,
                    "Please provide at least 2 choices."
                )
                return SETTING_CHOICES

            # Create keyboard for selecting correct answer
            keyboard = [
                [InlineKeyboardButton(
                    f"{chr(65+i)}. {choice}", 
                    callback_data=f'correct_{i}'
                )]
                for i, choice in enumerate(question.choices)
            ]
            keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation')])
            reply_markup = InlineKeyboardMarkup(keyboard)

            await self.cleanup_messages(update, context)
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"Your question:\n\n{question.format_for_display()}\n\nSelect the correct answer:",
                reply_markup=reply_markup
            )

            return SETTING_CORRECT_ANSWER

        question.choices.append(choice_text)
        
        # Show current choices
        choices_text = "\n".join(f"{chr(65+i)}. {choice}" 
                               for i, choice in enumerate(question.choices))
        
        await self.cleanup_messages(update, context)
        await self.send_bot_message(
            context,
            update.effective_chat.id,
            f"Current choices:\n{choices_text}\n\nEnter next choice or 'done' to finish:"
        )

        return SETTING_CHOICES

    async def set_correct_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Set the correct answer and ask for explanation."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        user = update.effective_user
        question = self.current_questions.get(user.id)

        if not question:
            return await self.cancel_operation(update, context)

        correct_index = int(query.data.replace('correct_', ''))
        question.correct_answer = correct_index

        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data='cancel_operation')]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Please provide an explanation for the correct answer:",
            reply_markup=reply_markup
        )

        return SETTING_EXPLANATION

    async def finalize_question(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Finalize the question creation process."""
        user = update.effective_user
        question = self.current_questions.get(user.id)

        if not question:
            return await self.cancel_operation(update, context)

        question.explanation = update.message.text
        question.add_user_message(update.message.message_id)

        # Store the question
        message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=(
                f"Question by @{question.username}:\n\n"
                f"{question.question_text}\n\n"
                f"Choices:\n" +
                "\n".join(f"{chr(65+i)}. {choice}" 
                         for i, choice in enumerate(question.choices)) +
                f"\n\nCorrect Answer: {chr(65+question.correct_answer)}\n\n"
                f"Explanation:\n{question.explanation}"
            ),
            message_thread_id=context.user_data.get('thread_id')
        )

        self.questions[message.message_id] = question
        del self.current_questions[user.id]

        # Return to main menu
        keyboard = [
            [InlineKeyboardButton("Start Studying 📚", callback_data='start_studying')],
            [InlineKeyboardButton("Create Another Question ❓", callback_data='create_question')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await self.cleanup_messages(update, context)
        await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Question created successfully! What would you like to do next?",
            reply_markup=reply_markup
        )

        return CHOOSING_MAIN_MENU

    async def generate_progress_image(self, username, study_time, break_time, session):
        """Generate a progress image for the study session."""
        try:
            # Create a new image with a white background
            width, height = 1200, 630
            image = Image.new('RGB', (width, height), 'white')
            draw = ImageDraw.Draw(image)

            # Load fonts
            try:
                title_font = ImageFont.truetype("/usr/share/fonts/truetype/poppins/Poppins-Bold.ttf", 48)
                subtitle_font = ImageFont.truetype("/usr/share/fonts/truetype/poppins/Poppins-SemiBold.ttf", 36)
                regular_font = ImageFont.truetype("/usr/share/fonts/truetype/poppins/Poppins-Light.ttf", 32)
            except Exception as e:
                logging.error(f"Error loading fonts: {str(e)}")
                # Fallback to default font
                title_font = ImageFont.load_default()
                subtitle_font = ImageFont.load_default()
                regular_font = ImageFont.load_default()

            # Draw title
            title_text = f"{username}'s Study Session"
            title_bbox = draw.textbbox((0, 0), title_text, font=title_font)
            title_width = title_bbox[2] - title_bbox[0]
            draw.text(((width - title_width) // 2, 50), title_text, font=title_font, fill='black')

            # Draw subject with emoji
            subject_text = f"Subject: {session.subject} {SUBJECTS[session.subject]}"
            subject_bbox = draw.textbbox((0, 0), subject_text, font=subtitle_font)
            subject_width = subject_bbox[2] - subject_bbox[0]
            draw.text(((width - subject_width) // 2, 150), subject_text, font=subtitle_font, fill='black')

            # Draw time information
            start_time = session.get_manila_time(session.start_time)
            end_time = session.get_manila_time(session.end_time or datetime.now(timezone.utc))
            
            time_text = (
                f"Started: {start_time.strftime('%I:%M %p')}\n"
                f"Ended: {end_time.strftime('%I:%M %p')}\n"
                f"Study Time: {int(study_time.total_seconds() // 3600)}h "
                f"{int((study_time.total_seconds() % 3600) // 60)}m\n"
                f"Break Time: {int(break_time.total_seconds() // 3600)}h "
                f"{int((break_time.total_seconds() % 3600) // 60)}m"
            )

            # Draw colored box for statistics
            stats_box_height = 200
            stats_box_y = 250
            box_color = SUBJECT_COLORS.get(session.subject, "#B5EAEA")
            draw.rectangle(
                [(100, stats_box_y), (width-100, stats_box_y+stats_box_height)],
                fill=box_color
            )

            # Draw time information inside box
            time_bbox = draw.textbbox((0, 0), time_text, font=regular_font)
            time_height = time_bbox[3] - time_bbox[1]
            draw.text(
                (150, stats_box_y + (stats_box_height - time_height) // 2),
                time_text,
                font=regular_font,
                fill='black'
            )

            # Draw footer
            footer_text = "Generated by Study Session Bot 📚"
            footer_bbox = draw.textbbox((0, 0), footer_text, font=regular_font)
            footer_width = footer_bbox[2] - footer_bbox[0]
            draw.text(
                ((width - footer_width) // 2, height - 100),
                footer_text,
                font=regular_font,
                fill='black'
            )

            # Save image to bytes
            img_byte_arr = io.BytesIO()
            image.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)

            return img_byte_arr

        except Exception as e:
            logging.error(f"Error generating progress image: {str(e)}")
            raise

def main():
    """Start the bot."""
    # Start health check server
    start_health_server(int(os.getenv('HEALTH_CHECK_PORT', 10001)))

    # Create the Application and pass it your bot's token
    application = Application.builder().token(os.getenv('TELEGRAM_TOKEN')).build()

    # Create an instance of your bot
    bot = TelegramBot()

    # Create conversation handler
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', bot.start),
            CallbackQueryHandler(bot.start_studying, pattern='^start_studying$'),
            CallbackQueryHandler(bot.create_question, pattern='^create_question$')
        ],
        states={
            CHOOSING_MAIN_MENU: [
                CallbackQueryHandler(bot.start_studying, pattern='^start_studying$'),
                CallbackQueryHandler(bot.create_question, pattern='^create_question$')
            ],
            SETTING_GOAL: [
                CallbackQueryHandler(bot.handle_goal_selection, pattern='^goal_'),
                CallbackQueryHandler(bot.handle_custom_goal, pattern='^goal_custom$'),
                CallbackQueryHandler(bot.cancel_operation, pattern='^cancel_operation$')
            ],
            SETTING_CUSTOM_GOAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.process_custom_goal),
                CallbackQueryHandler(bot.cancel_operation, pattern='^cancel_operation$')
            ],
            CHOOSING_SUBJECT: [
                CallbackQueryHandler(bot.handle_subject_selection, pattern='^subject_'),
                CallbackQueryHandler(bot.cancel_operation, pattern='^cancel_operation$')
            ],
            STUDYING: [
                CallbackQueryHandler(bot.handle_break, pattern='^take_break$'),
                CallbackQueryHandler(bot.end_session, pattern='^end_session$'),
                CallbackQueryHandler(bot.cancel_operation, pattern='^cancel_operation$')
            ],
            ON_BREAK: [
                CallbackQueryHandler(bot.resume_studying, pattern='^resume_studying$'),
                CallbackQueryHandler(bot.end_session, pattern='^end_session$'),
                CallbackQueryHandler(bot.cancel_operation, pattern='^cancel_operation$')
            ],
            CREATING_QUESTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.process_question_text),
                CallbackQueryHandler(bot.cancel_operation, pattern='^cancel_operation$')
            ],
            SETTING_CHOICES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.process_choice),
                CallbackQueryHandler(bot.cancel_operation, pattern='^cancel_operation$')
            ],
            SETTING_CORRECT_ANSWER: [
                CallbackQueryHandler(bot.set_correct_answer, pattern='^correct_'),
                CallbackQueryHandler(bot.cancel_operation, pattern='^cancel_operation$')
            ],
            SETTING_EXPLANATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.finalize_question),
                CallbackQueryHandler(bot.cancel_operation, pattern='^cancel_operation$')
            ]
        },
        fallbacks=[CommandHandler('cancel', bot.cancel_operation)]
    )

    # Add handlers
    application.add_handler(conv_handler)

    # Start the Bot
    application.run_polling()

if __name__ == '__main__':
    main()

