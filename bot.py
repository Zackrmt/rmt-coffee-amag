import os
import logging
import datetime
import asyncio
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
logger = logging.getLogger(__name__)

# States for conversation handler
(CHOOSING_MAIN_MENU, SETTING_GOAL, CONFIRMING_GOAL, CHOOSING_SUBJECT, 
 STUDYING, ON_BREAK, CREATING_QUESTION, SETTING_CHOICES, 
 CONFIRMING_QUESTION, SETTING_CORRECT_ANSWER, SETTING_EXPLANATION) = range(11)

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

class Question:
    def __init__(self, creator_id: int, creator_name: str):
        self.creator_id = creator_id
        self.creator_name = creator_name
        self.question_text = None
        self.choices = []
        self.correct_answer = None
        self.explanation = None
        self.messages_to_delete = []

    def add_message_to_delete(self, message_id: int):
        self.messages_to_delete.append(message_id)

class TelegramBot:
    def __init__(self):
        self.study_sessions: Dict[int, StudySession] = {}
        self.questions: Dict[int, Question] = {}
        self.current_questions: Dict[int, Question] = {}

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Send main menu message when the command /start is issued."""
        keyboard = [
            [InlineKeyboardButton("Start Studying 📚", callback_data='start_studying')],
            [InlineKeyboardButton("Start Creating Questions ❓", callback_data='create_question')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        message = await update.message.reply_text(
            'Welcome to MTLE Study Bot! Choose an option:',
            reply_markup=reply_markup
        )
        
        # Store message ID for later deletion
        if update.effective_user.id in self.study_sessions:
            self.study_sessions[update.effective_user.id].add_message_to_delete(message.message_id)
        
        return CHOOSING_MAIN_MENU

    async def ask_goal(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Ask if user wants to set a study goal."""
        query = update.callback_query
        await query.answer()
        await query.message.delete()

        keyboard = [
            [InlineKeyboardButton("Yes", callback_data='set_goal'),
             InlineKeyboardButton("Skip", callback_data='skip_goal')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        message = await query.message.reply_text(
            "Would you like to set a study goal for this session?",
            reply_markup=reply_markup
        )
        
        # Create new study session
        self.study_sessions[update.effective_user.id] = StudySession()
        self.study_sessions[update.effective_user.id].add_message_to_delete(message.message_id)
        
        return SETTING_GOAL

    async def handle_goal_response(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the response to setting a goal."""
        query = update.callback_query
        await query.answer()
        await query.message.delete()

        if query.data == 'set_goal':
            message = await query.message.reply_text(
                "Please enter your study goal in HH:MM format (e.g., 02:30 for 2 hours and 30 minutes):"
            )
            self.study_sessions[update.effective_user.id].add_message_to_delete(message.message_id)
            return CONFIRMING_GOAL
        else:  # skip_goal
            return await self.show_subject_selection(update, context)

    async def confirm_goal(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Confirm the entered study goal."""
        goal_time = update.message.text
        try:
            # Validate time format
            datetime.datetime.strptime(goal_time, '%H:%M')
            context.user_data['goal_time'] = goal_time
            
            keyboard = [
                [InlineKeyboardButton("Yes", callback_data='confirm_goal'),
                 InlineKeyboardButton("No", callback_data='set_goal')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            message = await update.message.reply_text(
                f"Is {goal_time} your study goal for this session?",
                reply_markup=reply_markup
            )
            self.study_sessions[update.effective_user.id].add_message_to_delete(message.message_id)
            return CONFIRMING_GOAL
        except ValueError:
            message = await update.message.reply_text(
                "Invalid time format. Please enter your goal in HH:MM format (e.g., 02:30):"
            )
            self.study_sessions[update.effective_user.id].add_message_to_delete(message.message_id)
            return CONFIRMING_GOAL

    async def show_subject_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Show subject selection buttons."""
        query = update.callback_query
        if query:
            await query.answer()
            await query.message.delete()

        keyboard = [[InlineKeyboardButton(subject, callback_data=f"subject_{code}")] 
                   for subject, code in SUBJECTS.items()]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="What subject are you studying?",
            reply_markup=reply_markup
        )
        self.study_sessions[update.effective_user.id].add_message_to_delete(message.message_id)
        return CHOOSING_SUBJECT

    async def start_studying(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Start the study session."""
        query = update.callback_query
        await query.answer()
        await query.message.delete()

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
        
        message = await query.message.reply_text(
            f"📚 {user.first_name} started studying {subject_code}.",
            reply_markup=reply_markup
        )
        session.add_message_to_delete(message.message_id)
        return STUDYING

    async def handle_break(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle break actions."""
        query = update.callback_query
        await query.answer()
        await query.message.delete()

        user = update.effective_user
        session = self.study_sessions.get(user.id)
        
        if query.data == 'start_break':
            session.start_break()
            keyboard = [
                [InlineKeyboardButton("End Break ⏰", callback_data='end_break')],
                [InlineKeyboardButton("End Study Session 🎯", callback_data='end_session')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            message = await query.message.reply_text(
                f"☕ {user.first_name} started their break.",
                reply_markup=reply_markup
            )
            session.add_message_to_delete(message.message_id)
            return ON_BREAK
        else:  # end_break
            session.end_break()
            keyboard = [
                [InlineKeyboardButton("Start Break ☕", callback_data='start_break')],
                [InlineKeyboardButton("End Study Session 🎯", callback_data='end_session')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            message = await query.message.reply_text(
                f"⏰ {user.first_name} ended their break and resumed studying.",
                reply_markup=reply_markup
            )
            session.add_message_to_delete(message.message_id)
            return STUDYING

    async def generate_progress_image(self, user_name: str, study_time: datetime.timedelta, 
                                   break_time: datetime.timedelta, goal_time: Optional[str] = None) -> io.BytesIO:
        """Generate a progress image for social media sharing."""
        # Create a new image with a white background
        width = 1080  # Instagram vertical post width
        height = 1350  # Instagram vertical post height (4:5 ratio)
        image = Image.new('RGB', (width, height), 'white')
        draw = ImageDraw.Draw(image)
        
        try:
            # Load fonts (you'll need to provide your own font files)
            title_font = ImageFont.truetype("arial.ttf", 60)
            main_font = ImageFont.truetype("arial.ttf", 40)
        except:
            # Fallback to default font
            title_font = ImageFont.load_default()
            main_font = ImageFont.load_default()

        # Draw title
        draw.text((width/2, 100), "MTLE 2025", font=title_font, fill='black', anchor="mm")
        
        # Format times
        study_hours = int(study_time.total_seconds() // 3600)
        study_minutes = int((study_time.total_seconds() % 3600) // 60)
        break_hours = int(break_time.total_seconds() // 3600)
        break_minutes = int((break_time.total_seconds() % 3600) // 60)
        
        # Draw study information
        y_position = 300
        draw.text((width/2, y_position), f"Study Session Progress", font=main_font, fill='black', anchor="mm")
        y_position += 100
        
        if goal_time:
            draw.text((width/2, y_position), f"Goal: {goal_time}", font=main_font, fill='black', anchor="mm")
            y_position += 100
            
        draw.text((width/2, y_position), 
                 f"Study Time: {study_hours:02d}:{study_minutes:02d}", 
                 font=main_font, fill='black', anchor="mm")
        y_position += 100
        
        draw.text((width/2, y_position),
                 f"Break Time: {break_hours:02d}:{break_minutes:02d}",
                 font=main_font, fill='black', anchor="mm")
        
        # Save image to bytes
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        
        return img_byte_arr

    async def end_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """End the study session and show summary."""
        query = update.callback_query
        await query.answer()
        await query.message.delete()

        user = update.effective_user
        session = self.study_sessions.get(user.id)
        session.end()

        # Message 1 (permanent)
        await query.message.reply_text(
            f"📚 {user.first_name} ended their review on {session.subject}. "
            f"Congrats {user.first_name}!"
        )

        # Message 2 (temporary)
        if session.goal_time:
            goal_msg = await query.message.reply_text(
                f"Your goal study time for this session was: {session.goal_time}"
            )
            session.add_message_to_delete(goal_msg.message_id)

        # Message 3 (permanent)
        study_time = session.get_total_study_time()
        hours, remainder = divmod(study_time.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        await query.message.reply_text(
            f"Your total study time for this session: {hours:02d}:{minutes:02d}"
        )

        # Message 4 (temporary)
        break_time = session.get_total_break_time()
        hours, remainder = divmod(break_time.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        break_msg = await query.message.reply_text(
            f"Your total break time: {hours:02d}:{minutes:02d}"
        )
        session.add_message_to_delete(break_msg.message_id)

        # Message 5 (temporary)
        keyboard = [
            [InlineKeyboardButton("Yes", callback_data='share_progress'),
             InlineKeyboardButton("No", callback_data='no_share')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        share_msg = await query.message.reply_text(
            "Wanna share your progress on your social media?",
            reply_markup=reply_markup
        )
        session.add_message_to_delete(share_msg.message_id)

        # Store session data in context for sharing
        context.user_data['study_time'] = study_time
        context.user_data['break_time'] = break_time

        # Clean up
        del self.study_sessions[user.id]
        return CHOOSING_MAIN_MENU

    async def handle_share_response(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the response to sharing progress."""
        query = update.callback_query
        await query.answer()

        if query.data == 'share_progress':
            # Generate and send image
            img_bytes = await self.generate_progress_image(
                query.from_user.first_name,
                context.user_data['study_time'],
                context.user_data['break_time'],
                context.user_data.get('goal_time')
            )
            
            keyboard = [
                [InlineKeyboardButton("Share to Instagram", callback_data='share_instagram'),
                 InlineKeyboardButton("Share to Facebook", callback_data='share_facebook')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.message.reply_photo(
                photo=img_bytes,
                caption="Here's your study progress! Share it on your social media:",
                reply_markup=reply_markup
            )
        else:  # no_share
            await query.message.delete()

        # Message 6
        keyboard = [
            [InlineKeyboardButton("Start Studying 📚", callback_data='start_studying')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(
            "If you want to start a study session again, just click the button below.",
            reply_markup=reply_markup
        )
        return CHOOSING_MAIN_MENU

    async def start_creating_question(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Start the question creation process."""
        query = update.callback_query
        await query.answer()
        await query.message.delete()

        keyboard = [[InlineKeyboardButton("Cancel", callback_data='cancel_question')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        message = await query.message.reply_text(
            "Please type your question:",
            reply_markup=reply_markup
        )
        
        # Initialize new question
        user = update.effective_user
        self.current_questions[user.id] = Question(user.id, user.first_name)
        self.current_questions[user.id].add_message_to_delete(message.message_id)
        return CREATING_QUESTION

    async def handle_question_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the question text input."""
        user = update.effective_user
        question = self.current_questions.get(user.id)
        question.question_text = update.message.text

        keyboard = [
            [InlineKeyboardButton("Yes", callback_data='confirm_question'),
             InlineKeyboardButton("No", callback_data='retry_question')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        message = await update.message.reply_text(
            f"Is this your question?\n\n{question.question_text}",
            reply_markup=reply_markup
        )
        question.add_message_to_delete(message.message_id)
        return CONFIRMING_QUESTION

    async def handle_question_confirmation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the confirmation of the question text."""
        query = update.callback_query
        await query.answer()
        await query.message.delete()

        if query.data == 'confirm_question':
            message = await query.message.reply_text(
                "Please enter your choices, one per message. Send 'DONE' when finished."
            )
            self.current_questions[update.effective_user.id].add_message_to_delete(message.message_id)
            return SETTING_CHOICES
        else:  # retry_question
            message = await query.message.reply_text("Please type your question again:")
            self.current_questions[update.effective_user.id].add_message_to_delete(message.message_id)
            return CREATING_QUESTION

    async def handle_choice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the choices input."""
        user = update.effective_user
        question = self.current_questions.get(user.id)
        
        if update.message.text.upper() == 'DONE':
            if len(question.choices) < 2:
                message = await update.message.reply_text(
                    "Please provide at least 2 choices. Continue entering choices:"
                )
                question.add_message_to_delete(message.message_id)
                return SETTING_CHOICES
            
            # Show choices for confirmation
            choices_text = "\n".join(f"{chr(65+i)}. {choice}" 
                                   for i, choice in enumerate(question.choices))
            keyboard = [[InlineKeyboardButton(chr(65+i), callback_data=f'correct_{i}')] 
                       for i in range(len(question.choices))]
            reply_markup = InlineKeyboardMarkup(keyboard)
            message = await update.message.reply_text(
                f"Select the correct answer:\n\n{choices_text}",
                reply_markup=reply_markup
            )
            question.add_message_to_delete(message.message_id)
            return SETTING_CORRECT_ANSWER
        else:
            question.choices.append(update.message.text)
            message = await update.message.reply_text(
                f"Choice {chr(64+len(question.choices))} added. "
                "Enter next choice or send 'DONE' when finished."
            )
            question.add_message_to_delete(message.message_id)
            return SETTING_CHOICES

    async def handle_correct_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the selection of correct answer."""
        query = update.callback_query
        await query.answer()
        await query.message.delete()

        user = update.effective_user
        question = self.current_questions.get(user.id)
        correct_index = int(query.data.split('_')[1])
        question.correct_answer = correct_index

        message = await query.message.reply_text(
            "Please provide an explanation for why this is the correct answer:"
        )
        question.add_message_to_delete(message.message_id)
        return SETTING_EXPLANATION

    async def handle_explanation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the explanation input and finalize question creation."""
        user = update.effective_user
        question = self.current_questions.get(user.id)
        question.explanation = update.message.text

        # Delete all messages related to question creation
        for msg_id in question.messages_to_delete:
            try:
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id,
                    message_id=msg_id
                )
            except Exception as e:
                logger.error(f"Error deleting message {msg_id}: {str(e)}")

        # Create the final question message
        choices_text = "\n".join(f"{chr(65+i)}. {choice}" 
                               for i, range(question.choices))
        question_text = (
            f"{question.question_text}\n\n{choices_text}\n\n"
            f"Question created by {question.creator_name}"
        )

        keyboard = [[InlineKeyboardButton(chr(65+i), callback_data=f'answer_{i}')]
                   for i in range(len(question.choices))]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Store question and clean up
        self.questions[len(self.questions)] = question
        del self.current_questions[user.id]

        # Send the final question
        await update.message.reply_text(question_text, reply_markup=reply_markup)
        return CHOOSING_MAIN_MENU

    async def handle_answer_attempt(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle when someone attempts to answer a question."""
        query = update.callback_query
        await query.answer()

        question_id = int(query.message.message_id)
        question = self.questions.get(question_id)
        if not question:
            return

        answer_index = int(query.data.split('_')[1])
        user = query.from_user
        
        if answer_index == question.correct_answer:
            message = await query.message.reply_text(
                f"✅ Correct, {user.first_name}!"
            )
        else:
            message = await query.message.reply_text(
                f"❌ Sorry {user.first_name}, the correct answer is "
                f"{chr(65+question.correct_answer)}."
            )

        # Wait 5 seconds and show explanation
        await asyncio.sleep(5)
        keyboard = [[InlineKeyboardButton("Done Reading", callback_data='done_reading')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(
            f"Explanation:\n{question.explanation}",
            reply_markup=reply_markup
        )

def main():
    """Start the bot."""
    # Add startup logging
    startup_time = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    logger.info(f"Bot starting at {startup_time}")
    logger.info("Initializing bot application...")
    
    # Start health check server
    start_health_server()
    
    # Create the Application and pass it your bot's token.
    application = Application.builder().token(os.environ["TELEGRAM_TOKEN"]).build()
    
    bot = TelegramBot()
    logger.info("Setting up conversation handlers...")
    
    # Create conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', bot.start)],
        states={
            CHOOSING_MAIN_MENU: [
                CallbackQueryHandler(bot.ask_goal, pattern='^start_studying$'),
                CallbackQueryHandler(bot.start_creating_question, pattern='^create_question$')
            ],
            SETTING_GOAL: [
                CallbackQueryHandler(bot.handle_goal_response, pattern='^(set_goal|skip_goal)$')
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
                CallbackQueryHandler(bot.handle_question_confirmation)
            ],
            SETTING_CHOICES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_choice)
            ],
            SETTING_CORRECT_ANSWER: [
                CallbackQueryHandler(bot.handle_correct_answer, pattern='^correct_')
            ],
            SETTING_EXPLANATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_explanation)
            ]
        },
        fallbacks=[CommandHandler('start', bot.start)]
    )

    logger.info("Adding handlers to application...")
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(bot.handle_answer_attempt, pattern='^answer_'))
    application.add_handler(CallbackQueryHandler(bot.handle_share_response, pattern='^(share_progress|no_share)$'))
    
    logger.info("Starting bot polling...")
    try:
        application.run_polling()
        logger.info("Bot polling started successfully")
    except Exception as e:
        logger.error(f"Error starting bot: {str(e)}")
        raise

if __name__ == '__main__':
    main()
