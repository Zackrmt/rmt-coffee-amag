import os
import sys
import logging
import asyncio
import datetime
import io
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, List, Optional
from PIL import Image, ImageDraw, ImageFont
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
    CREATING_QUESTION,
    CONFIRMING_QUESTION,
    SETTING_CHOICES,
    SETTING_CORRECT_ANSWER,
    SETTING_EXPLANATION,
    CHOOSING_DESIGN,
    SETTING_CUSTOM_GOAL,  # New state for custom goal input
) = range(12)

# Subject mapping
SUBJECTS = {
    "Clinical Chemistry 🧪": "CC",
    "Bacteriology 🦠": "BACTE",
    "Virology 🧬": "VIRO",
    "Parasitology 🦟": "PARA",
    "Mycology 🍄": "MYCO",
    "Immunology 🔬": "IMMUNO",
    "Blood Banking 🏥": "BB",
    "Hematology 🔴": "HEMA",
    "Histopathology 🔍": "HISTO",
    "Cytology 🧫": "CYTO",
    "UA/BF/SF 💉": "UA",
    "General Books 📚": "GB"
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


class Question:
    def __init__(self, user_id: int, user_name: str):
        self.user_id = user_id
        self.user_name = user_name
        self.question_text = None
        self.choices = []
        self.correct_answer = None
        self.explanation = None
        self.thread_id = None
        self.user_messages = []  # Store message IDs for cleanup

    def add_user_message(self, message_id: int):
        """Add a user message ID for later cleanup."""
        self.user_messages.append(message_id)

    def format_for_display(self) -> str:
        """Format the question for display in chat."""
        choices_text = "\n".join(f"{chr(65+i)}. {choice}" 
                               for i, choice in enumerate(self.choices))
        return f"Question by {self.user_name}:\n\n{self.question_text}\n\n{choices_text}"

class TelegramBot:
    def __init__(self):
        self.study_sessions: Dict[int, StudySession] = {}
        self.current_questions: Dict[int, Question] = {}
        self.questions: Dict[int, Question] = {}
        
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

    async def delete_message_callback(self, context: ContextTypes.DEFAULT_TYPE):
        """Callback for deleting messages after a delay."""
        job = context.job
        try:
            await context.bot.delete_message(
                chat_id=job.data['chat_id'],
                message_id=job.data['message_id']
            )
        except Exception as e:
            logger.error(f"Error in delete_message_callback: {e}")

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Start the conversation and ask if user wants to study."""
        await self.cleanup_messages(update, context)
        
        buttons = [
            [
                InlineKeyboardButton("Start Studying 📚", callback_data='start_studying'),
                InlineKeyboardButton("Create Question ❓", callback_data='create_question')
            ]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)
        
        welcome_text = (
            "Welcome to MTLE Study Bot! 📚✨\n\n"
            "I'm here to help you track your study sessions and create review questions.\n\n"
            "What would you like to do?"
        )
        
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
        # Create buttons for subjects in a grid
        buttons = []
        current_row = []
        
        for subject_name, subject_code in SUBJECTS.items():
            current_row.append(InlineKeyboardButton(
                subject_name, 
                callback_data=f'subject_{subject_code}'
            ))
            
            if len(current_row) == 2:  # Two buttons per row
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
            reply_markup=reply_markup
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
        
        # Create buttons for study controls
        buttons = [
            [
                InlineKeyboardButton("Take a Break ☕", callback_data='start_break'),
                InlineKeyboardButton("End Session ⏹️", callback_data='end_session')
            ],
            [InlineKeyboardButton("Cancel ⬅️", callback_data='cancel_operation')]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)
        
        # Format goal message
        goal_msg = ""
        if context.user_data.get('goal_time'):
            if ':' in context.user_data['goal_time']:
                hours, minutes = map(int, context.user_data['goal_time'].split(':'))
                goal_msg = f"\nGoal: {hours}h {minutes}m"
            else:
                goal_msg = f"\nGoal: {context.user_data['goal_time']}h"

        session_start_time = self.study_sessions[user.id].start_time.astimezone(MANILA_TZ)
        message = (
            f"📚 Study Session Started!\n"
            f"Subject: {subject_name}\n"
            f"Started at: {session_start_time.strftime('%I:%M %p')}"
            f"{goal_msg}"
        )
        
        await self.send_bot_message(
            context,
            update.effective_chat.id,
            message,
            reply_markup=reply_markup
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
            
            break_start_time = datetime.datetime.now(PST_TZ).astimezone(MANILA_TZ)
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"☕ Break started at {break_start_time.strftime('%I:%M %p')}",
                reply_markup=reply_markup
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
                reply_markup=reply_markup
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
        
        # Generate progress image
        try:
            img_bytes = await self.generate_progress_image(
                user.first_name,
                session.get_total_study_time(),
                session.get_total_break_time(),
                session.subject,
                session.goal_time,
                session.get_study_break_ratio()
            )
            
            # Message 1: Summary with image (keep forever)
            photo_message = await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=img_bytes,
                caption=f"📚 Study Session Summary\nSubject: {session.subject}",
                message_thread_id=context.user_data.get('thread_id')
            )
            
            # Store message ID as one to keep
            if 'messages_to_keep' not in context.user_data:
                context.user_data['messages_to_keep'] = []
            context.user_data['messages_to_keep'].append(photo_message.message_id)

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

    async def generate_progress_image(
        self,
        user_name: str,
        study_time: datetime.timedelta,
        break_time: datetime.timedelta,
        subject: str = None,
        goal_time: str = None,
        study_break_ratio: str = None
    ) -> bytes:
        """Generate a progress image with improved layout."""
        # Create a new image with a dark background
        width, height = 1080, 1080
        image = Image.new('RGB', (width, height), '#1a1a1a')
        draw = ImageDraw.Draw(image)

        # Get the directory of the current file
        current_dir = os.path.dirname(os.path.abspath(__file__))

        try:
            # Load fonts from local directory
            title_font = ImageFont.truetype(os.path.join(current_dir, "fonts", "ARIBLK.TTF"), 60)
            subtitle_font = ImageFont.truetype(os.path.join(current_dir, "fonts", "arial.ttf"), 40)
            body_font = ImageFont.truetype(os.path.join(current_dir, "fonts", "arial.ttf"), 32)
            logger.info("Successfully loaded custom fonts")
        except Exception as e:
            logger.warning(f"Error loading custom fonts: {e}")
            # Fallback to default font
            title_font = subtitle_font = body_font = ImageFont.load_default()
            logger.info("Using default font as fallback")

        # Draw header background
        header_height = 125
        draw.rectangle([20, 20, width-20, header_height], fill='#2d2d2d', outline='#404040')

        # Draw header text (ensuring it stays within bounds)
        header_text = "Study Progress Dashboard"
        text_width = draw.textlength(header_text, font=title_font)
        text_x = (width - text_width) / 2
        draw.text((text_x, 40), header_text, fill='white', font=title_font)

        # Draw timestamp
        timestamp = f"Generated at: {datetime.datetime.now(MANILA_TZ).strftime('%Y-%m-%d %I:%M:%S %p')}"
        draw.text((40, 100), timestamp, fill='#888888', font=body_font)

        # Draw creator text
        creator_text = "Study bot created by Eli"
        creator_text_width = draw.textlength(creator_text, font=body_font)
        creator_x = width - creator_text_width - 40  # 40 pixels from right edge
        draw.text((creator_x, 100), creator_text, fill='#888888', font=body_font)

        # Draw main content box
        content_top = header_height + 40
        draw.rectangle([20, content_top, width-20, height-100], fill='#2d2d2d', outline='#404040')

        # Draw statistics
        y_position = content_top + 40
        stats_data = [
            ("Subject", subject if subject else "Not specified"),
            ("Set Goal", f"{goal_time}h" if goal_time else "No goal set"),
            ("Total Study Time", f"{int(study_time.total_seconds()//3600)}h {int((study_time.total_seconds()%3600)//60)}m"),
            ("Total Break Time", f"{int(break_time.total_seconds()//3600)}h {int((break_time.total_seconds()%3600)//60)}m"),
            ("Study/Break Ratio", study_break_ratio if study_break_ratio else "N/A")
        ]

        for label, value in stats_data:
            draw.text((40, y_position), f"{label}:", fill='#cccccc', font=subtitle_font)
            draw.text((400, y_position), value, fill='white', font=subtitle_font)
            y_position += 80

        # Draw footer with user name
        draw.rectangle([20, height-80, width-20, height-20], fill='#2d2d2d', outline='#404040')
        footer_text = f"Name: {user_name}"
        text_width = draw.textlength(footer_text, font=subtitle_font)
        text_x = (width - text_width) / 2
        draw.text((text_x, height-65), footer_text, fill='white', font=subtitle_font)

        # Convert to bytes
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        return img_byte_arr.getvalue()

    async def start_creating_question(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Start the question creation process."""
        query = update.callback_query
        await query.answer()
        
        # Delete the clicked button's message
        try:
            await query.message.delete()
        except Exception as e:
            logger.error(f"Error deleting message: {e}")

        user = update.effective_user
        self.current_questions[user.id] = Question(user.id, user.first_name)
        
        # Show subject selection for the question
        buttons = []
        current_row = []
        
        for subject_name, subject_code in SUBJECTS.items():
            current_row.append(InlineKeyboardButton(
                subject_name, 
                callback_data=f'qsubject_{subject_code}'
            ))
            
            if len(current_row) == 2:
                buttons.append(current_row)
                current_row = []
        
        if current_row:
            buttons.append(current_row)
            
        buttons.append([InlineKeyboardButton("Cancel ⬅️", callback_data='cancel_operation')])
        
        reply_markup = InlineKeyboardMarkup(buttons)
        
        await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Select the subject for your question:",
            reply_markup=reply_markup
        )
        
        return CHOOSING_SUBJECT

    async def handle_subject_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle subject selection for question creation."""
        query = update.callback_query
        await query.answer()
        
        # Delete the clicked button's message
        try:
            await query.message.delete()
        except Exception as e:
            logger.error(f"Error deleting message: {e}")

        subject_code = query.data.split('_')[1]
        context.user_data['current_subject'] = subject_code
        
        await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Please enter your question text:"
        )
        
        return CREATING_QUESTION

    async def handle_question_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the question text input."""
        user = update.effective_user
        question = self.current_questions.get(user.id)
        
        if not question:
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Error: No question being created. Please start over."
            )
            return await self.start(update, context)

        # Delete user's message
        try:
            await update.message.delete()
        except Exception as e:
            logger.error(f"Error deleting message: {e}")

        question.question_text = update.message.text
        
        # Show confirmation buttons
        buttons = [
            [
                InlineKeyboardButton("✅ Confirm", callback_data='confirm_question'),
                InlineKeyboardButton("🔄 Try Again", callback_data='retry_question')
            ],
            [InlineKeyboardButton("Cancel ⬅️", callback_data='cancel_operation')]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)
        
        await self.send_bot_message(
            context,
            update.effective_chat.id,
            f"Preview your question:\n\n{update.message.text}\n\nIs this correct?",
            reply_markup=reply_markup
        )
        
        return CONFIRMING_QUESTION

    async def handle_question_confirmation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle question confirmation."""
        query = update.callback_query
        await query.answer()
        
        # Delete the clicked button's message
        try:
            await query.message.delete()
        except Exception as e:
            logger.error(f"Error deleting message: {e}")

        if query.data == 'retry_question':
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Please enter your question text again:"
            )
            return CREATING_QUESTION
            
        await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Please enter 4 choices for your question, one per line:"
        )
        
        return SETTING_CHOICES

    async def handle_choices_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the choices input."""
        user = update.effective_user
        question = self.current_questions.get(user.id)
        
        if not question:
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Error: No question being created. Please start over."
            )
            return await self.start(update, context)

        # Delete user's message
        try:
            await update.message.delete()
        except Exception as e:
            logger.error(f"Error deleting message: {e}")

        # Split choices by newline and take first 4
        choices = update.message.text.strip().split('\n')[:4]
        
        if len(choices) != 4:
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Please provide exactly 4 choices, one per line:"
            )
            return SETTING_CHOICES
            
        question.choices = choices
        
        # Create buttons for choosing correct answer
        buttons = []
        for i, choice in enumerate(choices):
            buttons.append([InlineKeyboardButton(
                f"{chr(65+i)}. {choice}", 
                callback_data=f'correct_{i}'
            )])
        
        buttons.append([InlineKeyboardButton("Cancel ⬅️", callback_data='cancel_operation')])
        reply_markup = InlineKeyboardMarkup(buttons)
        
        await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Select the correct answer:",
            reply_markup=reply_markup
        )
        
        return SETTING_CORRECT_ANSWER

    async def handle_correct_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle correct answer selection."""
        query = update.callback_query
        await query.answer()
        
        # Delete the clicked button's message
        try:
            await query.message.delete()
        except Exception as e:
            logger.error(f"Error deleting message: {e}")

        user = update.effective_user
        question = self.current_questions.get(user.id)
        
        if not question:
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Error: No question being created. Please start over."
            )
            return await self.start(update, context)
            
        correct_index = int(query.data.split('_')[1])
        question.correct_answer = correct_index
        
        await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Please provide an explanation for the correct answer:"
        )
        
        return SETTING_EXPLANATION

    async def handle_explanation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle explanation input and finalize question creation."""
        user = update.effective_user
        question = self.current_questions.get(user.id)
        
        if not question:
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Error: No question being created. Please start over."
            )
            return await self.start(update, context)

        # Delete user's message
        try:
            await update.message.delete()
        except Exception as e:
            logger.error(f"Error deleting message: {e}")

        question.explanation = update.message.text
        
        # Store the completed question
        self.questions[len(self.questions) + 1] = question
        
        # Create answer buttons for the final question display
        buttons = []
        for i, choice in enumerate(question.choices):
            button_text = f"{chr(65+i)}. {choice}"
            callback_data = f'answer_{len(self.questions)}_{i}'
            buttons.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
            
        reply_markup = InlineKeyboardMarkup(buttons)
        
        # Send the final question
        await self.send_bot_message(
            context,
            update.effective_chat.id,
            question.format_for_display(),
            reply_markup=reply_markup,
            should_delete=False  # Keep the question message
        )
        
        # Cleanup
        del self.current_questions[user.id]
        
        # Return to main menu
        buttons = [[InlineKeyboardButton("Start New Study Session 📚", callback_data='start_studying')]]
        reply_markup = InlineKeyboardMarkup(buttons)
        
        await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Question created successfully! Would you like to start studying?",
            reply_markup=reply_markup
        )
        
        return CHOOSING_MAIN_MENU

    async def cancel_operation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancel the current operation and return to start."""
        query = update.callback_query
        if query:
            await query.answer()
            # Delete the clicked button's message
            try:
                await query.message.delete()
            except Exception as e:
                logger.error(f"Error deleting message: {e}")

        # Clean up any current operations
        user = update.effective_user
        if user.id in self.study_sessions:
            del self.study_sessions[user.id]
        if user.id in self.current_questions:
            del self.current_questions[user.id]
            
        await self.cleanup_messages(update, context)
        
        return await self.start(update, context)

    async def handle_answer_attempt(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle answer attempts for created questions."""
        query = update.callback_query
        await query.answer()
        
        try:
            # Parse callback data
            _, question_id, answer_index = query.data.split('_')
            question_id = int(question_id)
            answer_index = int(answer_index)
            
            question = self.questions.get(question_id)
            if not question:
                await self.send_bot_message(
                    context,
                    update.effective_chat.id,
                    "Sorry, I couldn't find this question."
                )
                return
                
            # Check if the answer is correct
            is_correct = answer_index == question.correct_answer
            
            # Prepare the response message
            response = (
                f"{'✅ Correct!' if is_correct else '❌ Incorrect!'}\n\n"
                f"Explanation:\n{question.explanation}"
            )
            
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                response,
                should_delete=False  # Keep the explanation
            )
            
        except Exception as e:
            logger.error(f"Error handling answer attempt: {e}")
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Sorry, there was an error processing your answer."
            )


def main() -> None:
    """Start the bot."""
    # Add startup logging with current timestamp
    startup_time = "2025-06-06 16:14:21"  # Current UTC time
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
            CHOOSING_MAIN_MENU: [
                CallbackQueryHandler(bot.ask_goal, pattern='^start_studying$'),
                CallbackQueryHandler(bot.start_creating_question, pattern='^create_question$')
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
        per_chat=True,
        name="main_conversation"
    )

    # Add handlers
    application.add_handler(conv_handler)
    
    # Add separate handler for answer attempts
    answer_handler = CallbackQueryHandler(bot.handle_answer_attempt, pattern='^answer_')
    application.add_handler(answer_handler)

    # Start the Bot
    application.run_polling()

if __name__ == '__main__':
    main()

