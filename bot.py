import os
import logging
from datetime import datetime, timedelta
from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup,
    MessageEntity
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters
)
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states
CHOOSING_MAIN_MENU = 'CHOOSING_MAIN_MENU'
SETTING_GOAL = 'SETTING_GOAL'
CONFIRMING_GOAL = 'CONFIRMING_GOAL'
CHOOSING_SUBJECT = 'CHOOSING_SUBJECT'
STUDYING = 'STUDYING'
ON_BREAK = 'ON_BREAK'
CHOOSING_QUESTION_SUBJECT = 'CHOOSING_QUESTION_SUBJECT'
CREATING_QUESTION = 'CREATING_QUESTION'
SETTING_CHOICES = 'SETTING_CHOICES'
CONFIRMING_CHOICES = 'CONFIRMING_CHOICES'
SETTING_CORRECT_ANSWER = 'SETTING_CORRECT_ANSWER'
CONFIRMING_CORRECT_ANSWER = 'CONFIRMING_CORRECT_ANSWER'
SETTING_EXPLANATION = 'SETTING_EXPLANATION'
CONFIRMING_EXPLANATION = 'CONFIRMING_EXPLANATION'
CONFIRMING_DELETE = 'CONFIRMING_DELETE'

# Health check server
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'OK')

def start_health_server():
    server = HTTPServer(('0.0.0.0', 8080), HealthCheckHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()

class Question:
    def __init__(self, creator_id: int, creator_name: str):
        self.creator_id = creator_id
        self.creator_name = creator_name
        self.subject = None
        self.question_text = None
        self.choices = []
        self.correct_answer = None
        self.explanation = None
        self.image = None
        self.messages_to_delete = []
        self.thread_id = None
        self.user_messages = []

    def add_message_to_delete(self, message_id: int):
        self.messages_to_delete.append(message_id)

    def add_user_message(self, message_id: int):
        self.user_messages.append(message_id)

class TelegramBot:
    def __init__(self):
        self.current_questions = {}  # Store questions being created: user_id -> Question
        self.questions = {}  # Store completed questions: question_id -> Question
        self.study_sessions = {}  # Store active study sessions: user_id -> session_info
        self.messages_to_delete = {}  # Store messages to clean up: user_id -> [message_ids]

    async def cleanup_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Clean up temporary messages."""
        user_id = update.effective_user.id
        
        # Clean up stored messages
        if user_id in self.messages_to_delete:
            for msg_id in self.messages_to_delete[user_id]:
                try:
                    await context.bot.delete_message(
                        chat_id=update.effective_chat.id,
                        message_id=msg_id
                    )
                except Exception as e:
                    logger.error(f"Error deleting message: {e}")
            self.messages_to_delete[user_id] = []

        # Clean up user messages if there's an active question
        if user_id in self.current_questions:
            question = self.current_questions[user_id]
            for msg_id in question.user_messages:
                try:
                    await context.bot.delete_message(
                        chat_id=update.effective_chat.id,
                        message_id=msg_id
                    )
                except Exception as e:
                    logger.error(f"Error deleting user message: {e}")
            question.user_messages = []

    async def send_bot_message(self, context, chat_id, text, reply_markup=None):
        """Send a bot message and store its ID for cleanup."""
        message = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            message_thread_id=context.user_data.get('thread_id')
        )
        
        user_id = chat_id  # In private chats, chat_id is the same as user_id
        if user_id not in self.messages_to_delete:
            self.messages_to_delete[user_id] = []
        self.messages_to_delete[user_id].append(message.message_id)
        
        return message.message_id

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
        """Start the conversation and ask if user wants to study or create questions."""
        keyboard = [
            [InlineKeyboardButton("Start Studying 📚", callback_data='start_studying')],
            [InlineKeyboardButton("Create Question ❓", callback_data='create_question')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_id = await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Welcome to RMT Study Bot! What would you like to do?",
            reply_markup=reply_markup
        )
        return CHOOSING_MAIN_MENU

    async def ask_goal(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
        """Ask if the user wants to set a study goal."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        keyboard = [
            [
                InlineKeyboardButton("Set Goal ⭐", callback_data='set_goal'),
                InlineKeyboardButton("Skip Goal ➡️", callback_data='skip_goal')
            ],
            [InlineKeyboardButton("Cancel ❌", callback_data='cancel_study')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_id = await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Would you like to set a study goal for this session?",
            reply_markup=reply_markup
        )
        return SETTING_GOAL

    async def handle_goal_response(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
        """Handle the user's response to setting a goal."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        if query.data == 'set_goal':
            keyboard = [[InlineKeyboardButton("Cancel ❌", callback_data='cancel_study')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Please type your study goal for this session:",
                reply_markup=reply_markup
            )
            return CONFIRMING_GOAL
        elif query.data == 'skip_goal':
            context.user_data['study_goal'] = "NO SET GOAL"
            return await self.show_subject_selection(update, context)
        else:
            return await self.cancel_study_session(update, context)

    async def confirm_goal(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
        """Confirm the typed goal."""
        goal_text = update.message.text
        context.user_data['temp_goal'] = goal_text

        keyboard = [
            [
                InlineKeyboardButton("Confirm Goal ✅", callback_data='confirm_goal'),
                InlineKeyboardButton("Set New Goal 🔄", callback_data='set_goal')
            ],
            [InlineKeyboardButton("Cancel ❌", callback_data='cancel_study')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_id = await self.send_bot_message(
            context,
            update.effective_chat.id,
            f"Your study goal:\n{goal_text}\n\nIs this correct?",
            reply_markup=reply_markup
        )
        return CONFIRMING_GOAL

    async def show_subject_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
        """Show subject selection buttons."""
        query = update.callback_query
        if query:
            await query.answer()
        await self.cleanup_messages(update, context)

        # Save confirmed goal if exists
        if 'temp_goal' in context.user_data:
            context.user_data['study_goal'] = context.user_data.pop('temp_goal')

        keyboard = [
            [InlineKeyboardButton("CC 🧪", callback_data='subject_cc')],
            [InlineKeyboardButton("BACTE 🦠", callback_data='subject_bacte')],
            [InlineKeyboardButton("VIRO 👾", callback_data='subject_viro')],
            [InlineKeyboardButton("MYCO 🍄", callback_data='subject_myco')],
            [InlineKeyboardButton("PARA 🪱", callback_data='subject_para')],
            [InlineKeyboardButton("CM 🚽💩", callback_data='subject_cm')],
            [InlineKeyboardButton("HISTO 🧻🗳️", callback_data='subject_histo')],
            [InlineKeyboardButton("MT Laws ⚖️", callback_data='subject_mtlaws')],
            [InlineKeyboardButton("HEMA 🩸", callback_data='subject_hema')],
            [InlineKeyboardButton("IS ⚛", callback_data='subject_is')],
            [InlineKeyboardButton("BB 🩹", callback_data='subject_bb')],
            [InlineKeyboardButton("MolBio 🧬", callback_data='subject_molbio')],
            [InlineKeyboardButton("Autopsy ☠", callback_data='subject_autopsy')],
            [InlineKeyboardButton("General Books 📚", callback_data='subject_general')],
            [InlineKeyboardButton("RECALLS 🤔💭", callback_data='subject_recalls')],
            [InlineKeyboardButton("Cancel ❌", callback_data='cancel_study')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_id = await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Choose a subject to study:",
            reply_markup=reply_markup
        )
        return CHOOSING_SUBJECT

    async def start_studying(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
        """Start the study session for the selected subject."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        subject = query.data.split('_')[1].capitalize()
        user_id = update.effective_user.id
        
        # Initialize study session
        self.study_sessions[user_id] = {
            'subject': subject,
            'start_time': datetime.now(),
            'goal': context.user_data.get('study_goal', 'NO SET GOAL')
        }

        # Create study session message
        study_text = (
            f"📚 Study Session Started!\n\n"
            f"Subject: {subject}\n"
            f"Goal: {self.study_sessions[user_id]['goal']}\n"
            f"Time: {self.study_sessions[user_id]['start_time'].strftime('%H:%M')}"
        )

        keyboard = [
            [InlineKeyboardButton("Take Break ☕", callback_data='take_break')],
            [InlineKeyboardButton("End Session 🔚", callback_data='end_session')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_id = await self.send_bot_message(
            context,
            update.effective_chat.id,
            study_text,
            reply_markup=reply_markup
        )
        return STUDYING

    async def take_break(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
        """Handle break time during study session."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        user_id = update.effective_user.id
        if user_id in self.study_sessions:
            session = self.study_sessions[user_id]
            session['break_start'] = datetime.now()

            keyboard = [
                [InlineKeyboardButton("Resume Studying 📚", callback_data='resume_study')],
                [InlineKeyboardButton("End Session 🔚", callback_data='end_session')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Break time started! Take a rest and come back refreshed. ☕",
                reply_markup=reply_markup
            )
            return ON_BREAK
        else:
            return await self.start(update, context)

    async def resume_study(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
        """Resume study session after break."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        user_id = update.effective_user.id
        if user_id in self.study_sessions:
            session = self.study_sessions[user_id]
            break_duration = datetime.now() - session['break_start']
            
            study_text = (
                f"📚 Study Session Resumed!\n\n"
                f"Subject: {session['subject']}\n"
                f"Goal: {session['goal']}\n"
                f"Break Duration: {break_duration.seconds // 60} minutes"
            )

            keyboard = [
                [InlineKeyboardButton("Take Break ☕", callback_data='take_break')],
                [InlineKeyboardButton("End Session 🔚", callback_data='end_session')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                study_text,
                reply_markup=reply_markup
            )
            return STUDYING
        else:
            return await self.start(update, context)

    async def end_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
        """End the study session and show summary."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        user_id = update.effective_user.id
        if user_id in self.study_sessions:
            session = self.study_sessions[user_id]
            end_time = datetime.now()
            duration = end_time - session['start_time']
            
            summary_text = (
                f"📊 Study Session Summary\n\n"
                f"Subject: {session['subject']}\n"
                f"Duration: {duration.seconds // 3600} hours {(duration.seconds % 3600) // 60} minutes\n"
                f"Goal: {session['goal']}\n\n"
                f"Great job! Keep up the good work! 🌟"
            )

            keyboard = [
                [InlineKeyboardButton("New Session 📚", callback_data='start_studying')],
                [InlineKeyboardButton("Main Menu 🏠", callback_data='main_menu')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                summary_text,
                reply_markup=reply_markup
            )
            
            # Clear session data
            del self.study_sessions[user_id]
            return CHOOSING_MAIN_MENU
        else:
            return await self.start(update, context)

    async def cancel_study_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
        """Cancel the study session setup."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        # Clear any temporary data
        context.user_data.pop('temp_goal', None)
        context.user_data.pop('study_goal', None)
        
        return await self.start(update, context)

    async def start_creating_question(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
        """Start the question creation process."""
        query = update.callback_query
        if query:
            await query.answer()
        await self.cleanup_messages(update, context)

        user_id = update.effective_user.id
        user_name = update.effective_user.first_name
        
        # Initialize new question
        self.current_questions[user_id] = Question(user_id, user_name)
        
        keyboard = [
            [InlineKeyboardButton("CC 🧪", callback_data='create_cc')],
            [InlineKeyboardButton("BACTE 🦠", callback_data='create_bacte')],
            [InlineKeyboardButton("VIRO 👾", callback_data='create_viro')],
            [InlineKeyboardButton("MYCO 🍄", callback_data='create_myco')],
            [InlineKeyboardButton("PARA 🪱", callback_data='create_para')],
            [InlineKeyboardButton("CM 🚽💩", callback_data='create_cm')],
            [InlineKeyboardButton("HISTO 🧻🗳️", callback_data='create_histo')],
            [InlineKeyboardButton("MT Laws ⚖️", callback_data='create_mtlaws')],
            [InlineKeyboardButton("HEMA 🩸", callback_data='create_hema')],
            [InlineKeyboardButton("IS ⚛", callback_data='create_is')],
            [InlineKeyboardButton("BB 🩹", callback_data='create_bb')],
            [InlineKeyboardButton("MolBio 🧬", callback_data='create_molbio')],
            [InlineKeyboardButton("Autopsy ☠", callback_data='create_autopsy')],
            [InlineKeyboardButton("General Books 📚", callback_data='create_general')],
            [InlineKeyboardButton("RECALLS 🤔💭", callback_data='create_recalls')],
            [InlineKeyboardButton("Cancel ❌", callback_data='cancel_create')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_id = await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Select the subject for your question:",
            reply_markup=reply_markup
        )
        return CHOOSING_QUESTION_SUBJECT

    async def handle_question_subject(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
        """Handle subject selection for question creation."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        if query.data == 'cancel_create':
            # Clean up and return to main menu
            user_id = update.effective_user.id
            if user_id in self.current_questions:
                del self.current_questions[user_id]
            return await self.start(update, context)

        user_id = update.effective_user.id
        subject = query.data.split('_')[1].upper()
        self.current_questions[user_id].subject = subject

        keyboard = [[InlineKeyboardButton("Cancel ❌", callback_data='cancel_create')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_id = await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Please type your question text. You can also send an image with your question:",
            reply_markup=reply_markup
        )
        return CREATING_QUESTION

    async def handle_question_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
        """Handle the question text and optional image."""
        user_id = update.effective_user.id
        question = self.current_questions.get(user_id)
        
        if not question:
            return await self.start(update, context)

        # Store the message ID for later cleanup
        question.add_user_message(update.message.message_id)

        # Handle image if present
        if update.message.photo:
            question.image = update.message.photo[-1].file_id
            question.question_text = update.message.caption or ""
        else:
            question.question_text = update.message.text

        keyboard = [
            [
                InlineKeyboardButton("Continue ➡️", callback_data='continue_choices'),
                InlineKeyboardButton("Retype ✍️", callback_data='retype_question')
            ],
            [InlineKeyboardButton("Cancel ❌", callback_data='cancel_create')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        preview_text = (
            f"Preview of your question:\n\n"
            f"Subject: {question.subject}\n"
            f"Question: {question.question_text}\n\n"
            f"Would you like to continue with this question?"
        )
        
        message_id = await self.send_bot_message(
            context,
            update.effective_chat.id,
            preview_text,
            reply_markup=reply_markup
        )
        return SETTING_CHOICES

    async def handle_choices(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
        """Handle setting up multiple choice options."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        if query.data == 'retype_question':
            keyboard = [[InlineKeyboardButton("Cancel ❌", callback_data='cancel_create')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Please retype your question text:",
                reply_markup=reply_markup
            )
            return CREATING_QUESTION
        elif query.data == 'cancel_create':
            return await self.cancel_question_creation(update, context)

        keyboard = [[InlineKeyboardButton("Cancel ❌", callback_data='cancel_create')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_id = await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Please enter your multiple choice options, one per line:\nFormat: A) Option text",
            reply_markup=reply_markup
        )
        return CONFIRMING_CHOICES

    async def confirm_choices(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
        """Confirm the multiple choice options."""
        user_id = update.effective_user.id
        question = self.current_questions.get(user_id)
        
        if not question:
            return await self.start(update, context)

        # Store the message ID for later cleanup
        question.add_user_message(update.message.message_id)

        # Parse choices
        choices = update.message.text.split('\n')
        question.choices = choices

        keyboard = [
            [
                InlineKeyboardButton("Continue ➡️", callback_data='continue_answer'),
                InlineKeyboardButton("Retype Choices ✍️", callback_data='retype_choices')
            ],
            [InlineKeyboardButton("Cancel ❌", callback_data='cancel_create')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        preview_text = (
            f"Preview of your choices:\n\n"
            f"{chr(10).join(question.choices)}\n\n"
            f"Would you like to continue?"
        )
        
        message_id = await self.send_bot_message(
            context,
            update.effective_chat.id,
            preview_text,
            reply_markup=reply_markup
        )
        return SETTING_CORRECT_ANSWER

    async def handle_correct_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
        """Handle setting the correct answer."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        if query.data == 'retype_choices':
            keyboard = [[InlineKeyboardButton("Cancel ❌", callback_data='cancel_create')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Please retype your multiple choice options, one per line:",
                reply_markup=reply_markup
            )
            return CONFIRMING_CHOICES
        elif query.data == 'cancel_create':
            return await self.cancel_question_creation(update, context)

        user_id = update.effective_user.id
        question = self.current_questions.get(user_id)
        
        if not question:
            return await self.start(update, context)

        keyboard = [[InlineKeyboardButton("Cancel ❌", callback_data='cancel_create')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_id = await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Please type the letter of the correct answer (e.g., 'A'):",
            reply_markup=reply_markup
        )
        return CONFIRMING_CORRECT_ANSWER

    async def confirm_correct_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
        """Confirm the correct answer selection."""
        user_id = update.effective_user.id
        question = self.current_questions.get(user_id)
        
        if not question:
            return await self.start(update, context)

        # Store the message ID for later cleanup
        question.add_user_message(update.message.message_id)

        correct_answer = update.message.text.strip().upper()
        if len(correct_answer) != 1 or not correct_answer.isalpha():
            keyboard = [[InlineKeyboardButton("Cancel ❌", callback_data='cancel_create')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Invalid input. Please enter just one letter (A, B, C, etc.):",
                reply_markup=reply_markup
            )
            return CONFIRMING_CORRECT_ANSWER

        question.correct_answer = correct_answer

        keyboard = [
            [
                InlineKeyboardButton("Continue ➡️", callback_data='continue_explanation'),
                InlineKeyboardButton("Change Answer ✍️", callback_data='change_answer')
            ],
            [InlineKeyboardButton("Cancel ❌", callback_data='cancel_create')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_id = await self.send_bot_message(
            context,
            update.effective_chat.id,
            f"Correct answer set to {correct_answer}. Would you like to continue?",
            reply_markup=reply_markup
        )
        return SETTING_EXPLANATION

    async def handle_explanation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
        """Handle setting the explanation."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        if query.data == 'change_answer':
            keyboard = [[InlineKeyboardButton("Cancel ❌", callback_data='cancel_create')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Please type the letter of the correct answer (e.g., 'A'):",
                reply_markup=reply_markup
            )
            return CONFIRMING_CORRECT_ANSWER
        elif query.data == 'cancel_create':
            return await self.cancel_question_creation(update, context)

        keyboard = [[InlineKeyboardButton("Cancel ❌", callback_data='cancel_create')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_id = await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Please type the explanation for the correct answer:",
            reply_markup=reply_markup
        )
        return CONFIRMING_EXPLANATION

    async def confirm_explanation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
        """Confirm and save the complete question."""
        user_id = update.effective_user.id
        question = self.current_questions.get(user_id)
        
        if not question:
            return await self.start(update, context)

        # Store the message ID for later cleanup
        question.add_user_message(update.message.message_id)

        question.explanation = update.message.text

        # Format final preview
        preview_text = (
            f"Final Question Preview:\n\n"
            f"Subject: {question.subject}\n"
            f"Question: {question.question_text}\n\n"
            f"Choices:\n{chr(10).join(question.choices)}\n\n"
            f"Correct Answer: {question.correct_answer}\n"
            f"Explanation: {question.explanation}\n\n"
            f"Would you like to save this question?"
        )

        keyboard = [
            [
                InlineKeyboardButton("Save Question ✅", callback_data='save_question'),
                InlineKeyboardButton("Start Over 🔄", callback_data='create_question')
            ],
            [InlineKeyboardButton("Cancel ❌", callback_data='cancel_create')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_id = await self.send_bot_message(
            context,
            update.effective_chat.id,
            preview_text,
            reply_markup=reply_markup
        )
        return CONFIRMING_EXPLANATION

    async def save_question(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
        """Save the question and return to main menu."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        user_id = update.effective_user.id
        if user_id in self.current_questions:
            question = self.current_questions[user_id]
            # Save question to database or storage here
            # For now, just store in memory
            self.questions[len(self.questions) + 1] = question
            del self.current_questions[user_id]

            keyboard = [
                [InlineKeyboardButton("Create Another Question ❓", callback_data='create_question')],
                [InlineKeyboardButton("Main Menu 🏠", callback_data='main_menu')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Question saved successfully! 🎉",
                reply_markup=reply_markup
            )
            return CHOOSING_MAIN_MENU
        else:
            return await self.start(update, context)

    async def cancel_question_creation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
        """Cancel the question creation process."""
        query = update.callback_query
        await query.answer()
        await self.cleanup_messages(update, context)

        user_id = update.effective_user.id
        if user_id in self.current_questions:
            del self.current_questions[user_id]

        return await self.start(update, context)

def main() -> None:
    """Start the bot."""
    # Create the Application and pass it your bot's token.
    application = Application.builder().token(os.environ["TELEGRAM_TOKEN"]).build()

    bot = TelegramBot()

    # Setup conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", bot.start)],
        states={
            CHOOSING_MAIN_MENU: [
                CallbackQueryHandler(bot.ask_goal, pattern='^start_studying$'),
                CallbackQueryHandler(bot.start_creating_question, pattern='^create_question$')
            ],
            SETTING_GOAL: [
                CallbackQueryHandler(bot.handle_goal_response, pattern='^set_goal$'),
                CallbackQueryHandler(bot.handle_goal_response, pattern='^skip_goal$'),
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
                CallbackQueryHandler(bot.resume_study, pattern='^resume_study$'),
                CallbackQueryHandler(bot.end_session, pattern='^end_session$')
            ],
            CHOOSING_QUESTION_SUBJECT: [
                CallbackQueryHandler(bot.handle_question_subject, pattern='^create_'),
                CallbackQueryHandler(bot.cancel_question_creation, pattern='^cancel_create$')
            ],
            CREATING_QUESTION: [
                MessageHandler(filters.TEXT | filters.PHOTO, bot.handle_question_text),
                CallbackQueryHandler(bot.cancel_question_creation, pattern='^cancel_create$')
            ],
            SETTING_CHOICES: [
                CallbackQueryHandler(bot.handle_choices, pattern='^continue_choices$'),
                CallbackQueryHandler(bot.handle_choices, pattern='^retype_question$'),
                CallbackQueryHandler(bot.cancel_question_creation, pattern='^cancel_create$')
            ],
            CONFIRMING_CHOICES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.confirm_choices),
                CallbackQueryHandler(bot.cancel_question_creation, pattern='^cancel_create$')
            ],
            SETTING_CORRECT_ANSWER: [
                CallbackQueryHandler(bot.handle_correct_answer, pattern='^continue_answer$'),
                CallbackQueryHandler(bot.handle_correct_answer, pattern='^retype_choices$'),
                CallbackQueryHandler(bot.cancel_question_creation, pattern='^cancel_create$')
            ],
            CONFIRMING_CORRECT_ANSWER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.confirm_correct_answer),
                CallbackQueryHandler(bot.cancel_question_creation, pattern='^cancel_create$')
            ],
            SETTING_EXPLANATION: [
                CallbackQueryHandler(bot.handle_explanation, pattern='^continue_explanation$'),
                CallbackQueryHandler(bot.handle_explanation, pattern='^change_answer$'),
                CallbackQueryHandler(bot.cancel_question_creation, pattern='^cancel_create$')
            ],
            CONFIRMING_EXPLANATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.confirm_explanation),
                CallbackQueryHandler(bot.save_question, pattern='^save_question$'),
                CallbackQueryHandler(bot.start_creating_question, pattern='^create_question$'),
                CallbackQueryHandler(bot.cancel_question_creation, pattern='^cancel_create$'),
                CallbackQueryHandler(bot.start, pattern='^main_menu$')
            ]
        },
        fallbacks=[CommandHandler("start", bot.start)],
        name="rmt_study_bot",
        persistent=True
    )

    # Add ConversationHandler to application
    application.add_handler(conv_handler)

    # Start health check server
    start_health_server()

    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()

