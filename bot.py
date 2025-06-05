import os
import logging
import datetime
import asyncio
import signal
import sys
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
STARTUP_TIME = "2025-06-05 03:54:11"

logger = logging.getLogger(__name__)

# Signal handler for graceful shutdown
def signal_handler(sig, frame):
    logger.info("Received shutdown signal, cleaning up...")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# States for conversation handler
(CHOOSING_MAIN_MENU, SETTING_GOAL, CONFIRMING_GOAL, CHOOSING_SUBJECT, 
 STUDYING, ON_BREAK, CHOOSING_QUESTION_SUBJECT, CREATING_QUESTION, 
 SETTING_CHOICES, CONFIRMING_CHOICES, SETTING_CORRECT_ANSWER, 
 CONFIRMING_CORRECT_ANSWER, SETTING_EXPLANATION, CONFIRMING_EXPLANATION) = range(14)

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
        self.thread_id = None  # Store the topic ID

    def start(self, subject: str, goal_time: Optional[str] = None):
        self.start_time = datetime.datetime.now(datetime.UTC)
        self.subject = subject
        self.goal_time = goal_time

    def start_break(self):
        self.current_break = {'start': datetime.datetime.now(datetime.UTC)}

    def end_break(self):
        if self.current_break:
            self.current_break['end'] = datetime.datetime.now(datetime.UTC)
            self.breaks.append(self.current_break)
            self.current_break = None

    def end(self):
        self.end_time = datetime.datetime.now(datetime.UTC)

    def get_total_study_time(self) -> datetime.timedelta:
        if not self.start_time or not self.end_time:
            return datetime.timedelta()
        total_time = self.end_time - self.start_time
        break_time = self.get_total_break_time()
        return total_time - break_time

    def get_total_break_time(self) -> datetime.timedelta:
        total_break = datetime.timedelta()
        for break_session in self.breaks:
            total_break += break_session['end'] - break_session['start']
        return total_break

    def add_message_to_delete(self, message_id: int):
        self.messages_to_delete.append(message_id)

    def add_message_to_keep(self, message_id: int):
        self.messages_to_keep.append(message_id)

class Question:
    def __init__(self, creator_id: int, creator_name: str):
        self.creator_id = creator_id
        self.creator_name = creator_name
        self.question_text = None
        self.choices = []
        self.correct_answer = None
        self.explanation = None
        self.subject = None  # Added subject field
        self.messages_to_delete = []
        self.thread_id = None  # Store the topic ID
        self.user_messages = []  # Store user message IDs

    def add_message_to_delete(self, message_id: int):
        self.messages_to_delete.append(message_id)

    def add_user_message(self, message_id: int):
        self.user_messages.append(message_id)

class TelegramBot:
    def __init__(self):
        self.study_sessions: Dict[int, StudySession] = {}
        self.questions: Dict[int, Question] = {}
        self.current_questions: Dict[int, Question] = {}

    async def cleanup_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Clean up any existing messages."""
        # Clean up previous messages marked for deletion
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

        # Clean up user messages if they exist
        if 'user_messages' in context.user_data:
            for msg_id in context.user_data['user_messages']:
                try:
                    await context.bot.delete_message(
                        chat_id=update.effective_chat.id,
                        message_id=msg_id
                    )
                except Exception as e:
                    logger.debug(f"Error deleting user message {msg_id}: {str(e)}")
            context.user_data['user_messages'] = []

    async def send_bot_message(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int, 
                             text: str, reply_markup=None, should_store_id=True, 
                             should_delete=True) -> Optional[int]:
        """Helper method to send messages with proper thread_id and message tracking."""
        try:
            message = await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                message_thread_id=context.user_data.get('thread_id')
            )
            
            if should_store_id:
                if should_delete:
                    if 'messages_to_delete' not in context.user_data:
                        context.user_data['messages_to_delete'] = []
                    context.user_data['messages_to_delete'].append(message.message_id)
                else:
                    if 'messages_to_keep' not in context.user_data:
                        context.user_data['messages_to_keep'] = []
                    context.user_data['messages_to_keep'].append(message.message_id)
            
            return message.message_id
        except Exception as e:
            logger.error(f"Error sending message: {str(e)}")
            return None

    async def generate_progress_image(self, user_name: str, subject: str, study_time: datetime.timedelta, 
                                    break_time: datetime.timedelta, goal_time: Optional[str] = None) -> io.BytesIO:
        """Generate a progress image matching the provided HTML/CSS design."""
        width = 1080
        height = 1080
        image = Image.new('RGB', (width, height))
        draw = ImageDraw.Draw(image)

        # Background gradient (135deg, #16213e, #0f3460)
        for y in range(height):
            for x in range(width):
                pos = (x + y) / (width + height)
                r = int(22 + (15 - 22) * pos)
                g = int(33 + (52 - 33) * pos)
                b = int(62 + (96 - 62) * pos)
                draw.point((x, y), fill=(r, g, b))

        try:
            title_font = ImageFont.truetype("Poppins-Bold.ttf", 120)
            name_font = ImageFont.truetype("Poppins-Bold.ttf", 80)  # New font for name
            subtitle_font = ImageFont.truetype("Poppins-Light.ttf", 42)
            label_font = ImageFont.truetype("Poppins-SemiBold.ttf", 28)
            text_font = ImageFont.truetype("Poppins-Light.ttf", 20)
        except:
            title_font = ImageFont.load_default()
            name_font = title_font
            subtitle_font = title_font
            label_font = title_font
            text_font = title_font

        # Draw user name
        draw.text((width/2, 80), f"NAME: {user_name}, RMT",
                  font=name_font, fill='#eaeaea', anchor="mm")

        # Draw title (MTLE 2025)
        draw.text((width/2, 140), "MTLE 2025", 
                  font=title_font, fill='#eaeaea', anchor="mm")
        
        # Draw subject with "SUBJECT:" prefix
        draw.text((width/2, 220), f"SUBJECT: {subject}",
                  font=subtitle_font, fill='#a0b8ff', anchor="mm")

        # Calculate progress circles
        circle_radius = 125
        circle_thickness = 20
        circle_y = 450  # Adjusted position
        spacing = 300

        # Function to draw progress circle
        def draw_progress_circle(center_x: int, percentage: float, color: str, 
                               label: str, value: str):
            # Background circle
            draw.arc((center_x - circle_radius, circle_y - circle_radius,
                     center_x + circle_radius, circle_y + circle_radius),
                    0, 360, fill='#2e4057', width=circle_thickness)

            # Progress arc
            if percentage > 0:
                angle = int(360 * percentage)
                draw.arc((center_x - circle_radius, circle_y - circle_radius,
                         center_x + circle_radius, circle_y + circle_radius),
                        -90, angle-90, fill=color, width=circle_thickness)

            # Labels
            draw.text((center_x, circle_y - 20), label,
                     font=label_font, fill='#ffffff', anchor="mm")
            draw.text((center_x, circle_y + 20), value,
                     font=text_font, fill='#a3abcc', anchor="mm")

        # Calculate and draw progress circles
        study_hours = int(study_time.total_seconds() // 3600)
        study_minutes = int((study_time.total_seconds() % 3600) // 60)
        
        if goal_time:
            goal_hours, goal_minutes = map(int, goal_time.split(':'))
            total_goal_minutes = goal_hours * 60 + goal_minutes
            total_study_minutes = study_hours * 60 + study_minutes
            progress = min(1.0, total_study_minutes / total_goal_minutes if total_goal_minutes > 0 else 0)
            
            draw_progress_circle(width//2 - spacing, 1.0, '#43e97b',
                               "Study Goal", f"Goal Hours: {goal_hours:02d}")
            draw_progress_circle(width//2, progress, '#4facfe',
                               "Studied", f"Total Hours: {study_hours:02d}")
        else:
            # Draw all three circles even without goal
            draw_progress_circle(width//2 - spacing, 1.0, '#43e97b',
                               "Study Goal", "NO SET GOAL")
            draw_progress_circle(width//2, 1.0, '#4facfe',
                               "Studied", f"Total Hours: {study_hours:02d}")

        break_hours = int(break_time.total_seconds() // 3600)
        break_minutes = int((break_time.total_seconds() % 3600) // 60)
        draw_progress_circle(width//2 + spacing, 1.0, '#f76c6c',
                           "Break Time", f"Hours: {break_hours:02d}")

        # Bottom section with less space
        draw.line([(80, height-100), (width-80, height-100)],
                 fill='#2e4057', width=1)
        draw.text((80, height-70),
                 f"Created by: {user_name}",
                 font=text_font, fill='#a3abcc', anchor="lm")

        # Save image
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)

        return img_byte_arr

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Send main menu message when the command /start is issued."""
        await self.cleanup_messages(update, context)
        
        # Store the thread_id if message is in a topic
        if update.message and update.message.message_thread_id:
            context.user_data['thread_id'] = update.message.message_thread_id
            logger.info(f"Starting bot in topic {update.message.message_thread_id}")

        keyboard = [
            [InlineKeyboardButton("Start Studying 📚", callback_data='start_studying')],
            [InlineKeyboardButton("Start Creating Questions ❓", callback_data='create_question')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                'Welcome to MTLE Study Bot! Choose an option:',
                reply_markup=reply_markup,
                should_delete=True
            )
            return CHOOSING_MAIN_MENU
        except Exception as e:
            logger.error(f"Error in start command: {str(e)}")
            return ConversationHandler.END

    async def ask_goal(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Ask if user wants to set a study goal."""
        query = update.callback_query
        if query:
            await query.answer()
            await self.cleanup_messages(update, context)

        # Create new study session
        session = StudySession()
        session.thread_id = context.user_data.get('thread_id')
        self.study_sessions[update.effective_user.id] = session

        keyboard = [
            [InlineKeyboardButton("Yes", callback_data='set_goal'),
             InlineKeyboardButton("Skip", callback_data='skip_goal')],
            [InlineKeyboardButton("Cancel ❌", callback_data='cancel_study')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Would you like to set a study goal for this session?",
                reply_markup=reply_markup
            )
            session.add_message_to_delete(message_id)
            return SETTING_GOAL
        except Exception as e:
            logger.error(f"Error in ask_goal: {str(e)}")
            return ConversationHandler.END

    async def handle_goal_response(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the response to setting a goal."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        if query.data == 'cancel_study':
            return await self.cancel_study_session(update, context)

        if query.data == 'set_goal':
            try:
                message_id = await self.send_bot_message(
                    context,
                    update.effective_chat.id,
                    "Please enter your study goal in HH:MM format (e.g., 02:30 for 2 hours and 30 minutes):"
                )
                return CONFIRMING_GOAL
            except Exception as e:
                logger.error(f"Error sending message: {str(e)}")
                return ConversationHandler.END
        else:  # skip_goal
            return await self.show_subject_selection(update, context)

    async def confirm_goal(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Confirm the entered study goal."""
        goal_time = update.message.text
        
        # Store user's message for cleanup
        if 'user_messages' not in context.user_data:
            context.user_data['user_messages'] = []
        context.user_data['user_messages'].append(update.message.message_id)

        try:
            # Validate time format
            datetime.datetime.strptime(goal_time, '%H:%M')
            context.user_data['goal_time'] = goal_time
            
            keyboard = [
                [InlineKeyboardButton("Yes", callback_data='confirm_goal'),
                 InlineKeyboardButton("No", callback_data='set_goal')],
                [InlineKeyboardButton("Cancel ❌", callback_data='cancel_study')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"Is {goal_time} your study goal for this session?",
                reply_markup=reply_markup
            )
            return CONFIRMING_GOAL
        except ValueError:
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Invalid time format. Please enter your goal in HH:MM format (e.g., 02:30):"
            )
            return CONFIRMING_GOAL

    async def cancel_study_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancel study session and return to main menu."""
        query = update.callback_query
        if query:
            await query.answer()
        await self.cleanup_messages(update, context)

        # Clean up current session
        if update.effective_user.id in self.study_sessions:
            del self.study_sessions[update.effective_user.id]

        keyboard = [
            [InlineKeyboardButton("Start Studying 📚", callback_data='start_studying')],
            [InlineKeyboardButton("Create Question ❓", callback_data='create_question')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_id = await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Study session cancelled. What would you like to do?",
            reply_markup=reply_markup
        )
        return CHOOSING_MAIN_MENU

    async def show_subject_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Show subject selection buttons."""
        query = update.callback_query
        if query:
            await query.answer()

        # Create keyboard with subjects
        keyboard = []
        row = []
        for i, (subject, _) in enumerate(SUBJECTS.items()):
            row.append(InlineKeyboardButton(subject, callback_data=f'subject_{subject}'))
            if len(row) == 2:  # Two buttons per row
                keyboard.append(row)
                row = []
        if row:  # Add any remaining buttons
            keyboard.append(row)
        
        # Add cancel button
        keyboard.append([InlineKeyboardButton("Cancel ❌", callback_data='cancel_study')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Choose your subject:",
                reply_markup=reply_markup
            )
            return CHOOSING_SUBJECT
        except Exception as e:
            logger.error(f"Error showing subject selection: {str(e)}")
            return ConversationHandler.END

    async def start_studying(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Start the study session with the selected subject."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        subject = query.data.replace('subject_', '')
        session = self.study_sessions.get(update.effective_user.id)
        if not session:
            return await self.start(update, context)

        session.start(subject, context.user_data.get('goal_time'))
        
        keyboard = [
            [InlineKeyboardButton("Take Break ☕", callback_data='take_break')],
            [InlineKeyboardButton("End Session 🏁", callback_data='end_session')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"Started studying {subject}! Good luck! 🍀\n\n"
                "You can take breaks or end your session using the buttons below.",
                reply_markup=reply_markup,
                should_delete=False
            )
            session.add_message_to_keep(message_id)
            return STUDYING
        except Exception as e:
            logger.error(f"Error starting study session: {str(e)}")
            return ConversationHandler.END

    async def take_break(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the start of a break."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        session = self.study_sessions.get(update.effective_user.id)
        if not session:
            return await self.start(update, context)

        session.start_break()
        
        keyboard = [[InlineKeyboardButton("End Break ⏱", callback_data='end_break')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Break started! Click the button when you're ready to continue studying.",
                reply_markup=reply_markup
            )
            session.add_message_to_delete(message_id)
            return ON_BREAK
        except Exception as e:
            logger.error(f"Error starting break: {str(e)}")
            return ConversationHandler.END

    async def end_break(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the end of a break."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        session = self.study_sessions.get(update.effective_user.id)
        if not session:
            return await self.start(update, context)

        session.end_break()
        
        keyboard = [
            [InlineKeyboardButton("Take Break ☕", callback_data='take_break')],
            [InlineKeyboardButton("End Session 🏁", callback_data='end_session')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Welcome back! Keep up the good work! 💪",
                reply_markup=reply_markup
            )
            session.add_message_to_delete(message_id)
            return STUDYING
        except Exception as e:
            logger.error(f"Error ending break: {str(e)}")
            return ConversationHandler.END

    async def end_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the end of a study session."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        session = self.study_sessions.get(update.effective_user.id)
        if not session:
            return await self.start(update, context)

        session.end()
        
        try:
            # Generate and send progress image
            progress_image = await self.generate_progress_image(
                update.effective_user.first_name,
                session.subject,
                session.get_total_study_time(),
                session.get_total_break_time(),
                session.goal_time
            )
            
            # Send the image
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=progress_image,
                message_thread_id=context.user_data.get('thread_id')
            )
            
            # Clean up session
            del self.study_sessions[update.effective_user.id]
            
            # Show main menu
            keyboard = [
                [InlineKeyboardButton("Start New Session 📚", callback_data='start_studying')],
                [InlineKeyboardButton("Create Question ❓", callback_data='create_question')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Great job with your study session! What would you like to do next?",
                reply_markup=reply_markup
            )
            return CHOOSING_MAIN_MENU
        except Exception as e:
            logger.error(f"Error ending session: {str(e)}")
            return ConversationHandler.END

    async def start_creating_question(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Start the process of creating a new question."""
        query = update.callback_query
        if query:
            await query.answer()
        await self.cleanup_messages(update, context)

        # Initialize new question
        question = Question(
            update.effective_user.id,
            update.effective_user.first_name
        )
        question.thread_id = context.user_data.get('thread_id')
        self.current_questions[update.effective_user.id] = question

        # Create keyboard with subjects
        keyboard = []
        row = []
        for i, (subject, _) in enumerate(SUBJECTS.items()):
            row.append(InlineKeyboardButton(subject, callback_data=f'qsubject_{subject}'))
            if len(row) == 2:  # Two buttons per row
                keyboard.append(row)
                row = []
        if row:  # Add any remaining buttons
            keyboard.append(row)
        
        # Add cancel button
        keyboard.append([InlineKeyboardButton("Cancel ❌", callback_data='cancel_question')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                "What subject is this question for?",
                reply_markup=reply_markup
            )
            question.add_message_to_delete(message_id)
            return CHOOSING_QUESTION_SUBJECT
        except Exception as e:
            logger.error(f"Error starting question creation: {str(e)}")
            return ConversationHandler.END

    async def handle_question_subject(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the selected subject for the question."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        if query.data == 'cancel_question':
            return await self.cancel_question_creation(update, context)

        subject = query.data.replace('qsubject_', '')
        question = self.current_questions.get(update.effective_user.id)
        if not question:
            return await self.start(update, context)

        question.subject = subject

        keyboard = [
            [InlineKeyboardButton("Cancel ❌", callback_data='cancel_question')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Please type your question:",
                reply_markup=reply_markup
            )
            question.add_message_to_delete(message_id)
            return CREATING_QUESTION
        except Exception as e:
            logger.error(f"Error handling question subject: {str(e)}")
            return ConversationHandler.END

    async def handle_question_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the question text input."""
        user = update.effective_user
        question = self.current_questions.get(user.id)
        
        # Store user's message for cleanup
        question.add_user_message(update.message.message_id)
        
        # Store question text
        question.question_text = update.message.text
        
        keyboard = [
            [InlineKeyboardButton("Continue ➡️", callback_data='continue_to_choices')],
            [InlineKeyboardButton("Cancel ❌", callback_data='cancel_question')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_id = await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Now, please type your choices (one per line):",
            reply_markup=reply_markup
        )
        return SETTING_CHOICES

    async def handle_choices(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the choices input."""
        user = update.effective_user
        question = self.current_questions.get(user.id)
        
        # Store user's message for cleanup
        question.add_user_message(update.message.message_id)
        
        # Split and store choices
        question.choices = update.message.text.strip().split('\n')
        
        if len(question.choices) < 2:
            keyboard = [
                [InlineKeyboardButton("Try Again 🔄", callback_data='retry_choices')],
                [InlineKeyboardButton("Cancel ❌", callback_data='cancel_question')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Please provide at least 2 choices. Try again:",
                reply_markup=reply_markup
            )
            return SETTING_CHOICES
        
        # Show choices for confirmation
        choices_text = "\n".join(f"{chr(65+i)}. {choice}" 
                               for i, choice in enumerate(question.choices))
        text = f"Are these your choices?\n\n{choices_text}"
        
        keyboard = [
            [InlineKeyboardButton("Yes ✅", callback_data='confirm_choices'),
             InlineKeyboardButton("No ❌", callback_data='retry_choices')],
            [InlineKeyboardButton("Cancel ❌", callback_data='cancel_question')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_id = await self.send_bot_message(
            context,
            update.effective_chat.id,
            text,
            reply_markup=reply_markup
        )
        return CONFIRMING_CHOICES

    async def handle_choices_confirmation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the confirmation of choices."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        if query.data == 'cancel_question':
            return await self.cancel_question_creation(update, context)

        if query.data == 'retry_choices':
            keyboard = [
                [InlineKeyboardButton("Cancel ❌", callback_data='cancel_question')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Please type your choices again (one per line):",
                reply_markup=reply_markup
            )
            return SETTING_CHOICES

        # If confirmed, move to setting correct answer
        question = self.current_questions.get(update.effective_user.id)
        choices_text = "\n".join(f"{chr(65+i)}. {choice}" 
                               for i, choice in enumerate(question.choices))
        
        keyboard = [
            [InlineKeyboardButton(chr(65+i), callback_data=f'correct_{i}') 
             for i in range(len(question.choices))],
            [InlineKeyboardButton("Cancel ❌", callback_data='cancel_question')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_id = await self.send_bot_message(
            context,
            update.effective_chat.id,
            f"Select the correct answer:\n\n{choices_text}",
            reply_markup=reply_markup
        )
        return SETTING_CORRECT_ANSWER

    async def handle_correct_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the selection of correct answer."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        if query.data == 'cancel_question':
            return await self.cancel_question_creation(update, context)

        question = self.current_questions.get(update.effective_user.id)
        correct_index = int(query.data.replace('correct_', ''))
        question.correct_answer = correct_index

        # Show confirmation of correct answer
        choices_text = "\n".join(f"{chr(65+i)}. {choice}" + (" ✅" if i == correct_index else "")
                               for i, choice in enumerate(question.choices))
        
        keyboard = [
            [InlineKeyboardButton("Confirm ✅", callback_data='confirm_correct'),
             InlineKeyboardButton("Change ❌", callback_data='change_correct')],
            [InlineKeyboardButton("Cancel ❌", callback_data='cancel_question')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_id = await self.send_bot_message(
            context,
            update.effective_chat.id,
            f"Is this the correct answer?\n\n{choices_text}",
            reply_markup=reply_markup
        )
        return CONFIRMING_CORRECT_ANSWER

    async def handle_correct_answer_confirmation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the confirmation of correct answer."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        if query.data == 'cancel_question':
            return await self.cancel_question_creation(update, context)

        if query.data == 'change_correct':
            question = self.current_questions.get(update.effective_user.id)
            choices_text = "\n".join(f"{chr(65+i)}. {choice}" 
                                   for i, choice in enumerate(question.choices))
            
            keyboard = [
                [InlineKeyboardButton(chr(65+i), callback_data=f'correct_{i}') 
                 for i in range(len(question.choices))],
                [InlineKeyboardButton("Cancel ❌", callback_data='cancel_question')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"Select the correct answer:\n\n{choices_text}",
                reply_markup=reply_markup
            )
            return SETTING_CORRECT_ANSWER

        keyboard = [
            [InlineKeyboardButton("Cancel ❌", callback_data='cancel_question')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_id = await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Please provide an explanation for the correct answer:",
            reply_markup=reply_markup
        )
        return SETTING_EXPLANATION

    async def handle_explanation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the explanation input."""
        user = update.effective_user
        question = self.current_questions.get(user.id)
        
        # Store user's message for cleanup
        question.add_user_message(update.message.message_id)
        
        # Store explanation
        question.explanation = update.message.text
        
        keyboard = [
            [InlineKeyboardButton("Yes ✅", callback_data='confirm_explanation'),
             InlineKeyboardButton("No ❌", callback_data='retry_explanation')],
            [InlineKeyboardButton("Cancel ❌", callback_data='cancel_question')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_id = await self.send_bot_message(
            context,
            update.effective_chat.id,
            f"Is this explanation correct?\n\n{question.explanation}",
            reply_markup=reply_markup
        )
        return CONFIRMING_EXPLANATION

    async def handle_explanation_confirmation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the confirmation of explanation."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        if query.data == 'cancel_question':
            return await self.cancel_question_creation(update, context)

        if query.data == 'retry_explanation':
            keyboard = [
                [InlineKeyboardButton("Cancel ❌", callback_data='cancel_question')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Please provide the explanation again:",
                reply_markup=reply_markup
            )
            return SETTING_EXPLANATION

        # Finalize question creation
        question = self.current_questions.get(update.effective_user.id)
        question_id = len(self.questions)
        self.questions[question_id] = question
        
        return await self.finalize_question(update, context, question_id)

    async def finalize_question(self, update: Update, context: ContextTypes.DEFAULT_TYPE, question_id: int) -> int:
        """Display the final question with all options."""
        question = self.questions.get(question_id)
        
        # Format the final display
        question_text = (
            f"Subject: {question.subject}\n\n"
            f"{question.question_text}\n\n"
            f"Question Created by: {question.creator_name}"
        )

        # Create choice buttons
        keyboard = [
            [InlineKeyboardButton(chr(65+i), callback_data=f'answer_{i}')
             for i in range(len(question.choices))]
        ]
        
        # Add management buttons
        keyboard.append([
            InlineKeyboardButton("Delete Question ❌", callback_data=f'delete_question_{question_id}'),
            InlineKeyboardButton("Create New Question ➕", callback_data='create_question')
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=question_text,
            reply_markup=reply_markup,
            message_thread_id=context.user_data.get('thread_id')
        )
        
        # Clean up current question
        self.current_questions.pop(update.effective_user.id, None)
        return CHOOSING_MAIN_MENU

    async def cancel_question_creation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancel the question creation process."""
        query = update.callback_query
        if query:
            await query.answer()
        await self.cleanup_messages(update, context)

        # Clean up current question
        if update.effective_user.id in self.current_questions:
            del self.current_questions[update.effective_user.id]

        keyboard = [
            [InlineKeyboardButton("Start Studying 📚", callback_data='start_studying')],
            [InlineKeyboardButton("Create Question ❓", callback_data='create_question')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_id = await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Question creation cancelled. What would you like to do?",
            reply_markup=reply_markup
        )
        return CHOOSING_MAIN_MENU

def main() -> None:
    """Start the bot."""
    # Create the Application and pass it your bot's token.
    application = Application.builder().token(os.environ["TELEGRAM_TOKEN"]).build()

    bot = TelegramBot()

    # Add conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', bot.start)],
        states={
            CHOOSING_MAIN_MENU: [
                CallbackQueryHandler(bot.ask_goal, pattern='^start_studying$'),
                CallbackQueryHandler(bot.start_creating_question, pattern='^create_question$')
            ],
            SETTING_GOAL: [
                CallbackQueryHandler(bot.handle_goal_response, pattern='^(set|skip)_goal$'),
                CallbackQueryHandler(bot.cancel_study_session, pattern='^cancel_study$')
            ],
            CONFIRMING_GOAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.confirm_goal),
                CallbackQueryHandler(bot.show_subject_selection, pattern='^confirm_goal$'),
                CallbackQueryHandler(bot.handle_goal_response, pattern='^set_goal$'),
                CallbackQueryHandler(bot.cancel_study_session, pattern='^cancel_study$')
            ],
            CHOOSING_SUBJECT: [
                CallbackQueryHandler(bot.start_studying, pattern='^subject_'),
                CallbackQueryHandler(bot.cancel_study_session, pattern='^cancel_study$')
            ],
            STUDYING: [
                CallbackQueryHandler(bot.take_break, pattern='^take_break$'),
                CallbackQueryHandler(bot.end_session, pattern='^end_session$')
            ],
            ON_BREAK: [
                CallbackQueryHandler(bot.end_break, pattern='^end_break$')
            ],
            CHOOSING_QUESTION_SUBJECT: [
                CallbackQueryHandler(bot.handle_question_subject, pattern='^qsubject_'),
                CallbackQueryHandler(bot.cancel_question_creation, pattern='^cancel_question$')
            ],
            CREATING_QUESTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_question_text),
                CallbackQueryHandler(bot.cancel_question_creation, pattern='^cancel_question$')
            ],
            SETTING_CHOICES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_choices),
                CallbackQueryHandler(bot.cancel_question_creation, pattern='^cancel_question$')
            ],
            CONFIRMING_CHOICES: [
                CallbackQueryHandler(bot.handle_choices_confirmation, pattern='^(confirm|retry)_choices$'),
                CallbackQueryHandler(bot.cancel_question_creation, pattern='^cancel_question$')
            ],
            SETTING_CORRECT_ANSWER: [
                CallbackQueryHandler(bot.handle_correct_answer, pattern='^correct_'),
                CallbackQueryHandler(bot.cancel_question_creation, pattern='^cancel_question$')
            ],
            CONFIRMING_CORRECT_ANSWER: [
                CallbackQueryHandler(bot.handle_correct_answer_confirmation, pattern='^(confirm|change)_correct$'),
                CallbackQueryHandler(bot.cancel_question_creation, pattern='^cancel_question$')
            ],
            SETTING_EXPLANATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_explanation),
                CallbackQueryHandler(bot.cancel_question_creation, pattern='^cancel_question$')
            ],
            CONFIRMING_EXPLANATION: [
                CallbackQueryHandler(bot.handle_explanation_confirmation, pattern='^(confirm|retry)_explanation$'),
                CallbackQueryHandler(bot.cancel_question_creation, pattern='^cancel_question$')
            ]
        },
        fallbacks=[CommandHandler('start', bot.start)],
        per_message=False,
        per_chat=True
    )

    application.add_handler(conv_handler)

    # Start the health check server
    start_health_server()

    # Start the Bot
    application.run_polling()

if __name__ == '__main__':
    main()

