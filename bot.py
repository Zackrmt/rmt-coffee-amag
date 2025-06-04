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
STARTUP_TIME = "2025-06-04 19:01:29"

logger = logging.getLogger(__name__)

# Signal handler for graceful shutdown
def signal_handler(sig, frame):
    logger.info("Received shutdown signal, cleaning up...")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# States for conversation handler
(CHOOSING_MAIN_MENU, SETTING_GOAL, CONFIRMING_GOAL, CHOOSING_SUBJECT, 
 STUDYING, ON_BREAK, CREATING_QUESTION, SETTING_CHOICES, 
 CONFIRMING_QUESTION, SETTING_CORRECT_ANSWER, SETTING_EXPLANATION,
 CHOOSING_DESIGN) = range(12)  # Added CHOOSING_DESIGN state

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

# Image design templates
DESIGNS = {
    'modern': {
        'name': 'Modern Gradient',
        'description': 'Sleek gradient design with modern typography',
        'colors': {
            'background_start': '#1a2a6c',
            'background_end': '#b21f1f',
            'title': '#ffffff',
            'text': '#f0f0f0',
            'accent': '#00ff00'
        }
    },
    'minimal': {
        'name': 'Minimal Dark',
        'description': 'Clean dark theme with bold typography',
        'colors': {
            'background': '#000000',
            'title': '#ffffff',
            'text': '#cccccc',
            'accent': '#ff5733'
        }
    },
    'classic': {
        'name': 'Classic Blue',
        'description': 'Professional blue theme with traditional layout',
        'colors': {
            'background': '#1B4F72',
            'title': '#ffffff',
            'text': '#ecf0f1',
            'accent': '#f4d03f'
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
        self.design_choice = 'modern'  # Default design
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
             InlineKeyboardButton("Skip", callback_data='skip_goal')]
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
                 InlineKeyboardButton("No", callback_data='set_goal')]
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

    async def show_subject_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Show subject selection buttons."""
        query = update.callback_query
        if query:
            await query.answer()
            await self.cleanup_messages(update, context)

        keyboard = [[InlineKeyboardButton(subject, callback_data=f"subject_{code}")] 
                   for subject, code in SUBJECTS.items()]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                "What subject are you studying?",
                reply_markup=reply_markup
            )
            return CHOOSING_SUBJECT
        except Exception as e:
            logger.error(f"Error sending message: {str(e)}")
            return ConversationHandler.END

    async def generate_progress_image(self, user_name: str, study_time: datetime.timedelta, 
                                    break_time: datetime.timedelta, design: str,
                                    goal_time: Optional[str] = None) -> io.BytesIO:
        """Generate a progress image using the specified design."""
        width = 1080
        height = 1350
        image = Image.new('RGB', (width, height))
        draw = ImageDraw.Draw(image)
        
        design_template = DESIGNS.get(design, DESIGNS['modern'])
        colors = design_template['colors']

        # Apply background based on design
        if design == 'modern':
            # Create gradient background
            for y in range(height):
                r = int(int(colors['background_start'][1:3], 16) + (y * (int(colors['background_end'][1:3], 16) - int(colors['background_start'][1:3], 16)) / height))
                g = int(int(colors['background_start'][3:5], 16) + (y * (int(colors['background_end'][3:5], 16) - int(colors['background_start'][3:5], 16)) / height))
                b = int(int(colors['background_start'][5:7], 16) + (y * (int(colors['background_end'][5:7], 16) - int(colors['background_start'][5:7], 16)) / height))
                draw.line([(0, y), (width, y)], fill=(r, g, b))
        else:
            # Solid background
            draw.rectangle([0, 0, width, height], fill=colors['background'])

        try:
            title_font = ImageFont.truetype("Arial Bold.ttf", 80)
            main_font = ImageFont.truetype("Arial.ttf", 60)
        except:
            title_font = ImageFont.load_default()
            main_font = ImageFont.load_default()

        # Draw decorative elements based on design
        if design == 'modern':
            # Add modern geometric shapes
            draw.polygon([(0, 0), (width/3, 0), (0, height/3)], fill=colors['accent']+'40')
            draw.polygon([(width, height), (width-width/3, height), (width, height-height/3)], fill=colors['accent']+'40')
        elif design == 'minimal':
            # Add minimal lines
            draw.line([(50, 50), (width-50, 50)], fill=colors['accent'], width=2)
            draw.line([(50, height-50), (width-50, height-50)], fill=colors['accent'], width=2)
        elif design == 'classic':
            # Add classic border
            draw.rectangle([30, 30, width-30, height-30], outline=colors['accent'], width=3)

        # Draw title with shadow effect
        shadow_offset = 3
        draw.text((width/2 + shadow_offset, 150 + shadow_offset), "MTLE 2025", 
                 font=title_font, fill='#333333', anchor="mm")
        draw.text((width/2, 150), "MTLE 2025", 
                 font=title_font, fill=colors['title'], anchor="mm")

        # Format times
        study_hours = int(study_time.total_seconds() // 3600)
        study_minutes = int((study_time.total_seconds() % 3600) // 60)
        break_hours = int(break_time.total_seconds() // 3600)
        break_minutes = int((break_time.total_seconds() % 3600) // 60)

        # Draw study information with design-specific styling
        y_position = 400
        texts = [
            ("Study Session Progress", colors['text']),
            (f"Study Time: {study_hours:02d}:{study_minutes:02d}", colors['accent']),
            (f"Break Time: {break_hours:02d}:{break_minutes:02d}", colors['text'])
        ]

        if goal_time:
            texts.insert(1, (f"Goal: {goal_time}", colors['accent']))

        for text, color in texts:
            if design == 'minimal':
                # Add underline effect for minimal design
                text_width = main_font.getsize(text)[0]
                text_x = width/2 - text_width/2
                draw.text((width/2, y_position), text, font=main_font, fill=color, anchor="mm")
                draw.line([(text_x, y_position+5), (text_x+text_width, y_position+5)], fill=color, width=1)
            else:
                draw.text((width/2, y_position), text, font=main_font, fill=color, anchor="mm")
            y_position += 150

        # Save image
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)

        return img_byte_arr

    async def show_design_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Show design selection buttons."""
        query = update.callback_query
        if query:
            await query.answer()
            await self.cleanup_messages(update, context)

        keyboard = []
        for design_id, design_info in DESIGNS.items():
            keyboard.append([InlineKeyboardButton(
                f"{design_info['name']} - {design_info['description']}", 
                callback_data=f'design_{design_id}'
            )])

        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_id = await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Choose a design for your progress image:",
            reply_markup=reply_markup
        )
        return CHOOSING_DESIGN

    async def handle_design_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the selection of an image design."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        design = query.data.replace('design_', '')
        user = update.effective_user
        
        try:
            # Generate and send image with selected design
            img_bytes = await self.generate_progress_image(
                user.first_name,
                context.user_data['study_time'],
                context.user_data['break_time'],
                design,
                context.user_data.get('goal_time')
            )
            
            keyboard = [
                [InlineKeyboardButton("Share to Instagram", callback_data='share_instagram'),
                 InlineKeyboardButton("Share to Facebook", callback_data='share_facebook')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Send image with sharing options
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=img_bytes,
                caption="Here's your study progress! Share it on your social media:",
                reply_markup=reply_markup,
                message_thread_id=context.user_data.get('thread_id')
            )
            
            # Return to main menu
            keyboard = [
                [InlineKeyboardButton("Start New Study Session 📚", callback_data='start_studying')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Ready to start another study session?",
                reply_markup=reply_markup
            )
            return CHOOSING_MAIN_MENU
            
        except Exception as e:
            logger.error(f"Error generating/sending image: {str(e)}")
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
        session.start(subject_code, context.user_data.get('goal_time'))

        keyboard = [
            [InlineKeyboardButton("Start Break ☕", callback_data='start_break')],
            [InlineKeyboardButton("End Study Session 🎯", callback_data='end_session')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"📚 {user.first_name} started studying {subject_code}.",
                reply_markup=reply_markup,
                should_delete=False  # Keep this message
            )
            session.add_message_to_keep(message_id)
            return STUDYING
        except Exception as e:
            logger.error(f"Error starting study session: {str(e)}")
            return ConversationHandler.END

    async def handle_break(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle break actions."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

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
                    should_delete=False  # Keep break messages
                )
                session.add_message_to_keep(message_id)
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
                    should_delete=False  # Keep break messages
                )
                session.add_message_to_keep(message_id)
                return STUDYING
            except Exception as e:
                logger.error(f"Error ending break: {str(e)}")
                return ConversationHandler.END

    async def end_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """End the study session and show summary."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        user = update.effective_user
        session = self.study_sessions.get(user.id)
        session.end()

        try:
            # Message 1 (permanent)
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"📚 {user.first_name} ended their review on {session.subject}. "
                f"Congrats {user.first_name}!",
                should_delete=False
            )

            # Calculate times
            study_time = session.get_total_study_time()
            break_time = session.get_total_break_time()
            context.user_data['study_time'] = study_time
            context.user_data['break_time'] = break_time

            # Format study time
            study_hours = int(study_time.total_seconds() // 3600)
            study_minutes = int((study_time.total_seconds() % 3600) // 60)
            
            # Format break time
            break_hours = int(break_time.total_seconds() // 3600)
            break_minutes = int((break_time.total_seconds() % 3600) // 60)

            # Message 2 (permanent) - Study time
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"Your total study time: {study_hours:02d}:{study_minutes:02d}",
                should_delete=False
            )

            # Message 3 (permanent) - Break time
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"Your total break time: {break_hours:02d}:{break_minutes:02d}",
                should_delete=False
            )

            # Message 4 (if goal was set)
            if session.goal_time:
                await self.send_bot_message(
                    context,
                    update.effective_chat.id,
                    f"Your goal study time was: {session.goal_time}",
                    should_delete=False
                )

            # Message 5 - Design selection prompt
            keyboard = [
                [InlineKeyboardButton("Choose Design", callback_data='share_progress'),
                 InlineKeyboardButton("Skip Sharing", callback_data='no_share')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Would you like to create and share a progress image?",
                reply_markup=reply_markup
            )

            # Clean up session
            del self.study_sessions[user.id]
            return CHOOSING_MAIN_MENU

        except Exception as e:
            logger.error(f"Error ending session: {str(e)}")
            return ConversationHandler.END

    async def start_creating_question(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Start the question creation process."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        keyboard = [[InlineKeyboardButton("Cancel", callback_data='cancel_question')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Please type your question:",
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

    async def handle_question_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the question text input."""
        user = update.effective_user
        question = self.current_questions.get(user.id)
        question.question_text = update.message.text
        
        # Store user's message for cleanup
        question.add_user_message(update.message.message_id)

        keyboard = [
            [InlineKeyboardButton("Yes", callback_data='confirm_question'),
             InlineKeyboardButton("No", callback_data='retry_question')]
        ]
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
        """Handle the confirmation of the question text."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        if query.data == 'confirm_question':
            try:
                message_id = await self.send_bot_message(
                    context,
                    update.effective_chat.id,
                    "Please enter your choices, one per message. Send 'DONE' when finished."
                )
                return SETTING_CHOICES
            except Exception as e:
                logger.error(f"Error confirming question: {str(e)}")
                return ConversationHandler.END
        else:  # retry_question
            try:
                message_id = await self.send_bot_message(
                    context,
                    update.effective_chat.id,
                    "Please type your question again:"
                )
                return CREATING_QUESTION
            except Exception as e:
                logger.error(f"Error retrying question: {str(e)}")
                return ConversationHandler.END

    async def handle_choice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the choices input."""
        user = update.effective_user
        question = self.current_questions.get(user.id)
        
        # Store user's message for cleanup
        question.add_user_message(update.message.message_id)
        
        if update.message.text.upper() == 'DONE':
            if len(question.choices) < 2:
                message_id = await self.send_bot_message(
                    context,
                    update.effective_chat.id,
                    "Please provide at least 2 choices. Continue entering choices:"
                )
                return SETTING_CHOICES
            
            # Show choices for confirmation
            choices_text = "\n".join(f"{chr(65+i)}. {choice}" 
                                   for i, choice in enumerate(question.choices))
            keyboard = [[InlineKeyboardButton(chr(65+i), callback_data=f'correct_{i}')] 
                       for i in range(len(question.choices))]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"Select the correct answer:\n\n{choices_text}",
                reply_markup=reply_markup
            )
            return SETTING_CORRECT_ANSWER
        else:
            question.choices.append(update.message.text)
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"Choice {chr(64+len(question.choices))} added. "
                "Enter next choice or send 'DONE' when finished."
            )
            return SETTING_CHOICES

    async def handle_correct_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the selection of correct answer."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        user = update.effective_user
        question = self.current_questions.get(user.id)
        correct_index = int(query.data.split('_')[1])
        question.correct_answer = correct_index

        message_id = await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Please provide an explanation for why this is the correct answer:"
        )
        return SETTING_EXPLANATION

    async def handle_explanation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the explanation input and finalize question creation."""
        user = update.effective_user
        question = self.current_questions.get(user.id)
        question.explanation = update.message.text
        
        # Store user's message for cleanup
        question.add_user_message(update.message.message_id)

        # Create the final question message
        choices_text = "\n".join(f"{chr(65+i)}. {choice}" 
                               for i, choice in enumerate(question.choices))
        question_text = (
            f"{question.question_text}\n\n{choices_text}\n\n"
            f"Question created by {question.creator_name}"
        )

        keyboard = [[InlineKeyboardButton(chr(65+i), callback_data=f'answer_{i}')]
                   for i in range(len(question.choices))]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            # Store question and clean up
            self.questions[len(self.questions)] = question
            del self.current_questions[user.id]

            # Send the final question
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=question_text,
                reply_markup=reply_markup,
                message_thread_id=context.user_data.get('thread_id')
            )

            # Return to main menu
            keyboard = [
                [InlineKeyboardButton("Create Another Question ❓", callback_data='create_question')],
                [InlineKeyboardButton("Start Studying 📚", callback_data='start_studying')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Question created successfully! What would you like to do next?",
                reply_markup=reply_markup
            )
            return CHOOSING_MAIN_MENU
            
        except Exception as e:
            logger.error(f"Error finalizing question: {str(e)}")
            return ConversationHandler.END

    async def handle_social_share(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle sharing to social media platforms."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        if query.data == 'share_instagram':
            platform = "Instagram"
        else:  # share_facebook
            platform = "Facebook"

        # Return to main menu
        keyboard = [
            [InlineKeyboardButton("Start New Study Session 📚", callback_data='start_studying')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"To share on {platform}, save the image above and upload it to your {platform} account.",
                reply_markup=reply_markup
            )
            return CHOOSING_MAIN_MENU
        except Exception as e:
            logger.error(f"Error handling {platform} share: {str(e)}")
            return ConversationHandler.END
    
    # ADD THE NEW METHOD HERE
    async def handle_share_response(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the user's response to sharing their progress."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        if query.data == 'no_share':
            # Return to main menu without sharing
            keyboard = [
                [InlineKeyboardButton("Start New Study Session 📚", callback_data='start_studying')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                message_id = await self.send_bot_message(
                    context,
                    update.effective_chat.id,
                    "Ready to start another study session?",
                    reply_markup=reply_markup
                )
                return CHOOSING_MAIN_MENU
            except Exception as e:
                logger.error(f"Error returning to main menu: {str(e)}")
                return ConversationHandler.END
        else:  # share_progress
            # Show design selection
            return await self.show_design_selection(update, context)
      
    async def handle_answer_attempt(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle when someone attempts to answer a question."""
        query = update.callback_query
        await query.answer()

        try:
            question_id = int(query.message.message_id)
            question = self.questions.get(question_id)
            if not question:
                return

            answer_index = int(query.data.split('_')[1])
            user = query.from_user
            
            if answer_index == question.correct_answer:
                await self.send_bot_message(
                    context,
                    update.effective_chat.id,
                    f"✅ Correct, {user.first_name}!",
                    should_delete=False
                )
            else:
                await self.send_bot_message(
                    context,
                    update.effective_chat.id,
                    f"❌ Sorry {user.first_name}, the correct answer is "
                    f"{chr(65+question.correct_answer)}.",
                    should_delete=False
                )

            # Show explanation after a delay
            await asyncio.sleep(5)
            keyboard = [[InlineKeyboardButton("Done Reading", callback_data='done_reading')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"Explanation:\n{question.explanation}",
                reply_markup=reply_markup,
                should_delete=False
            )
        except Exception as e:
            logger.error(f"Error handling answer attempt: {str(e)}")

def main():
    """Start the bot."""
    # Add startup logging
    logger.info(f"Bot starting at {STARTUP_TIME} UTC")
    logger.info(f"Started by user: {CURRENT_USER}")
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
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', bot.start)],
        states={
            CHOOSING_MAIN_MENU: [
                CallbackQueryHandler(bot.ask_goal, pattern='^start_studying$'),
                CallbackQueryHandler(bot.start_creating_question, pattern='^create_question$')
            ],
            SETTING_GOAL: [
                CallbackQueryHandler(bot.handle_goal_response, pattern='^set_goal$'),
                CallbackQueryHandler(bot.handle_goal_response, pattern='^skip_goal$')
            ],
            CONFIRMING_GOAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.confirm_goal),
                CallbackQueryHandler(bot.show_subject_selection, pattern='^confirm_goal$'),
                CallbackQueryHandler(bot.handle_goal_response, pattern='^set_goal$')
            ],
            CHOOSING_SUBJECT: [
                CallbackQueryHandler(bot.start_studying, pattern='^subject_')
            ],
            STUDYING: [
                CallbackQueryHandler(bot.handle_break, pattern='^start_break$'),
                CallbackQueryHandler(bot.end_session, pattern='^end_session$')
            ],
            ON_BREAK: [
                CallbackQueryHandler(bot.handle_break, pattern='^end_break$'),
                CallbackQueryHandler(bot.end_session, pattern='^end_session$')
            ],
            CREATING_QUESTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_question_text),
                CallbackQueryHandler(bot.start, pattern='^cancel_question$')
            ],
            CONFIRMING_QUESTION: [
                CallbackQueryHandler(bot.handle_question_confirmation, pattern='^confirm_question$'),
                CallbackQueryHandler(bot.handle_question_confirmation, pattern='^retry_question$')
            ],
            SETTING_CHOICES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_choice)
            ],
            SETTING_CORRECT_ANSWER: [
                CallbackQueryHandler(bot.handle_correct_answer, pattern='^correct_')
            ],
            SETTING_EXPLANATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_explanation)
            ],
            CHOOSING_DESIGN: [
                CallbackQueryHandler(bot.handle_design_selection, pattern='^design_')
            ]
        },
        fallbacks=[
            CommandHandler('start', bot.start),
            CallbackQueryHandler(bot.show_design_selection, pattern='^share_progress$'),
            CallbackQueryHandler(bot.handle_share_response, pattern='^no_share$'),
            CallbackQueryHandler(bot.handle_answer_attempt, pattern='^answer_')
        ],
        per_message=False,
        per_chat=True
    )

    # Add handlers
    application.add_handler(conv_handler)
    
    # Add standalone handlers
    application.add_handler(CallbackQueryHandler(bot.handle_answer_attempt, pattern='^answer_'))
    application.add_handler(CallbackQueryHandler(bot.handle_share_response, pattern='^(share_progress|no_share)$'))
    application.add_handler(CallbackQueryHandler(bot.show_design_selection, pattern='^share_progress$'))
    application.add_handler(CallbackQueryHandler(bot.handle_social_share, pattern='^share_(instagram|facebook)$'))
    application.add_handler(CallbackQueryHandler(lambda u, c: None, pattern='^done_reading$'))
    
    # Error handler
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Log errors caused by Updates."""
        logger.error("Exception while handling an update:", exc_info=context.error)
        if isinstance(update, Update) and update.effective_message:
            error_message = "An error occurred while processing your request. Please try again."
            try:
                await bot.cleanup_messages(update, context)
                message_id = await bot.send_bot_message(
                    context,
                    update.effective_chat.id,
                    error_message
                )
            except Exception as e:
                logger.error(f"Error sending error message: {str(e)}")

    # Add error handler
    application.add_error_handler(error_handler)

    # Start the Bot with drop_pending_updates
    logger.info("Starting bot polling...")
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
        logger.info("Bot polling started successfully")
    except Exception as e:
        logger.error(f"Error starting bot: {str(e)}")
        raise

if __name__ == '__main__':
    main()
