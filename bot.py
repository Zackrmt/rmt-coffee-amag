import os
import time
import logging
from datetime import datetime
import pytz
import asyncio
import sys
from urllib import parse as url
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes, ConversationHandler
import json
from PIL import Image, ImageDraw, ImageFont
import io
from pathlib import Path

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Constants
TOKEN = "7514176467:AAER30CBSwtfin_zUV-QFYubHEV0dJIHIac"  # Correct - in quotes
STUDY_DATA_FILE = 'study_data.json'
QUESTIONS_FILE = 'questions.json'

# Conversation states
SUBJECT_SELECTION = 1
QUESTION_TEXT = 2
CHOICES = 3
CORRECT_ANSWER = 4
EXPLANATION = 5

# Ensure data directory exists
if not os.path.exists('data'):
    os.makedirs('data')

# Initialize or load study data
def load_study_data():
    if os.path.exists(STUDY_DATA_FILE):
        with open(STUDY_DATA_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_study_data(data):
    with open(STUDY_DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

# Load or initialize questions data
def load_questions():
    if os.path.exists(QUESTIONS_FILE):
        with open(QUESTIONS_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_questions(questions):
    with open(QUESTIONS_FILE, 'w') as f:
        json.dump(questions, f, indent=4)

# Global variables
study_data = load_study_data()
questions = load_questions()

class ImageGenerator:
    def __init__(self):
        self.width = 1080
        self.height = 1080
        self.background_color = "#1a1a1a"
        self.font_path = "fonts/arial.ttf"
        self.subject_colors = {
            'CC': '#FF5733',
            'BACTE': '#33FF57',
            'VIRO': '#3357FF',
            'MYCO': '#FF33E9',
            'PARA': '#33FFE9',
            'CM': '#FFB533',
            'HISTO': '#8B4513',
            'MTLAWS': '#808080',
            'HEMA': '#FF0000',
            'IS': '#4B0082',
            'BB': '#FF69B4',
            'MOLBIO': '#32CD32',
            'AUTOPSY': '#363636',
            'GENBOOKS': '#DAA520',
            'RECALLS': '#9370DB'
        }

    def create_dashboard(self, user_data, telegram_username):
        img = Image.new('RGB', (self.width, self.height), self.background_color)
        draw = ImageDraw.Draw(img)

        # Load fonts
        title_font = ImageFont.truetype(self.font_path, 24)
        subtitle_font = ImageFont.truetype(self.font_path, 14)
        stats_font = ImageFont.truetype(self.font_path, 14)
        footer_font = ImageFont.truetype(self.font_path, 24)

        # Draw header
        header_bg = Image.new('RGB', (self.width - 30, 100), "#2d2d2d")
        img.paste(header_bg, (15, 15))
        draw.text((35, 25), "Study Progress Dashboard - MTLE 2025", fill="white", font=title_font)
        
        # Current timestamp
        current_time = datetime.now(pytz.UTC).strftime('%Y-%m-%d %H:%M:%S UTC')
        draw.text((35, 55), f"Generated at: {current_time}", fill="#888888", font=subtitle_font)
        draw.text((35, 75), "Study bot created by Eli", fill="#888888", font=subtitle_font)

        # Calculate grid layout
        start_y = 130
        card_width = (self.width - 45) // 2
        card_height = 180
        padding = 15

        # Draw subject cards
        x_positions = [15, card_width + 30]
        y_position = start_y
        card_count = 0

        for subject, data in user_data.items():
            if not isinstance(data, dict) or 'study_time' not in data:
                continue

            x = x_positions[card_count % 2]
            y = y_position

            # Draw card background
            card_bg = Image.new('RGB', (card_width, card_height), "#2d2d2d")
            img.paste(card_bg, (x, y))

            # Draw subject title
            subject_color = self.subject_colors.get(subject, '#FFFFFF')
            draw.text((x + 20, y + 20), f"{subject} {self.get_subject_emoji(subject)}", 
                     fill=subject_color, font=title_font)

            # Draw progress bar
            goal_hours = data.get('goal_hours', 20)
            study_hours = data['study_time'] / 3600
            progress = min(study_hours / goal_hours * 100, 100)

            bar_width = card_width - 40
            bar_height = 20
            bar_x = x + 20
            bar_y = y + 55

            # Background bar
            draw.rectangle([bar_x, bar_y, bar_x + bar_width, bar_y + bar_height], fill="#3d3d3d")
            # Progress bar
            progress_width = int(bar_width * progress / 100)
            draw.rectangle([bar_x, bar_y, bar_x + progress_width, bar_y + bar_height], 
                         fill=subject_color)
            # Progress text
            draw.text((bar_x + bar_width - 30, bar_y + 4), f"{int(progress)}%", 
                     fill="white", font=subtitle_font)

            # Draw stats
            stats_start_y = y + 90
            stats = [
                (f"Set Goal:", f"{goal_hours} hours"),
                ("Total Study Time:", f"{study_hours:.1f} hours"),
                ("Break Time:", f"{data.get('break_time', 0) / 3600:.1f} hours"),
                ("Study/Break Ratio:", f"{study_hours / max(data.get('break_time', 1) / 3600, 0.1):.1f}:1")
            ]

            for i, (label, value) in enumerate(stats):
                draw.text((x + 20, stats_start_y + i * 20), label, fill="#cccccc", font=stats_font)
                draw.text((x + card_width - 20 - draw.textlength(value, font=stats_font),
                          stats_start_y + i * 20), value, fill="#cccccc", font=stats_font)

            card_count += 1
            if card_count % 2 == 0:
                y_position += card_height + padding

        # Draw footer
        footer_bg = Image.new('RGB', (self.width - 30, 64), "#2d2d2d")
        footer_y = self.height - 79
        img.paste(footer_bg, (15, footer_y))
        
        # Draw username in footer
        footer_text = f"Name: {telegram_username}, RMT"
        draw.text((self.width // 2 - draw.textlength(footer_text, font=footer_font) // 2,
                  footer_y + 20), footer_text, fill="white", font=footer_font)

        return img

    def get_subject_emoji(self, subject):
        emoji_map = {
            'CC': '🧪',
            'BACTE': '🦠',
            'VIRO': '👾',
            'MYCO': '🍄',
            'PARA': '🪱',
            'CM': '🚽💩',
            'HISTO': '🧻🗳️',
            'MTLAWS': '⚖️',
            'HEMA': '🩸',
            'IS': '⚛',
            'BB': '🩹',
            'MOLBIO': '🧬',
            'AUTOPSY': '☠',
            'GENBOOKS': '📚',
            'RECALLS': '🤔💭'
        }
        return emoji_map.get(subject, '')

    def save_dashboard(self, user_data, telegram_username, filename="dashboard.png"):
        img = self.create_dashboard(user_data, telegram_username)
        img.save(filename)
        return filename

# Study session handling
class StudySession:
    def __init__(self):
        self.active_sessions = {}
        self.break_sessions = {}

    def start_study(self, user_id, subject):
        self.active_sessions[user_id] = {
            'subject': subject,
            'start_time': time.time(),
            'breaks': []
        }

    def start_break(self, user_id):
        if user_id in self.active_sessions:
            self.break_sessions[user_id] = time.time()
            return True
        return False

    def end_break(self, user_id):
        if user_id in self.break_sessions:
            break_start = self.break_sessions.pop(user_id)
            break_duration = time.time() - break_start
            self.active_sessions[user_id]['breaks'].append(break_duration)
            return break_duration
        return 0

    def end_study(self, user_id):
        if user_id in self.active_sessions:
            session = self.active_sessions.pop(user_id)
            study_duration = time.time() - session['start_time']
            break_duration = sum(session['breaks'])
            return session['subject'], study_duration, break_duration
        return None, 0, 0

    def get_active_session(self, user_id):
        return self.active_sessions.get(user_id)

    def is_on_break(self, user_id):
        return user_id in self.break_sessions

# Initialize study session manager
study_session = StudySession()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send initial welcome message with main options."""
    keyboard = [
        [
            InlineKeyboardButton("START STUDYING", callback_data="start_studying"),
            InlineKeyboardButton("START CREATING QUESTION", callback_data="start_creating")
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Welcome to MTLE Study Bot! Choose an option:",
        reply_markup=reply_markup
    )

def get_subject_keyboard(include_back=True):
    """Generate subject selection keyboard."""
    keyboard = [
        [InlineKeyboardButton("CC 🧪", callback_data="subject_CC")],
        [InlineKeyboardButton("BACTE 🦠", callback_data="subject_BACTE")],
        [InlineKeyboardButton("VIRO 👾", callback_data="subject_VIRO")],
        [InlineKeyboardButton("MYCO 🍄", callback_data="subject_MYCO")],
        [InlineKeyboardButton("PARA 🪱", callback_data="subject_PARA")],
        [InlineKeyboardButton("CM 🚽💩", callback_data="subject_CM")],
        [InlineKeyboardButton("HISTO 🧻🗳️", callback_data="subject_HISTO")],
        [InlineKeyboardButton("MT Laws ⚖️", callback_data="subject_MTLAWS")],
        [InlineKeyboardButton("HEMA 🩸", callback_data="subject_HEMA")],
        [InlineKeyboardButton("IS ⚛", callback_data="subject_IS")],
        [InlineKeyboardButton("BB 🩹", callback_data="subject_BB")],
        [InlineKeyboardButton("MolBio 🧬", callback_data="subject_MOLBIO")],
        [InlineKeyboardButton("Autopsy ☠", callback_data="subject_AUTOPSY")],
        [InlineKeyboardButton("General Books 📚", callback_data="subject_GENBOOKS")],
        [InlineKeyboardButton("RECALLS 🤔💭", callback_data="subject_RECALLS")]
    ]
    if include_back:
        keyboard.append([InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="back_to_main")])
    return keyboard

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all callback queries."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    username = query.from_user.username or "Unknown"

    if query.data == "start_studying":
        keyboard = get_subject_keyboard()
        await query.edit_message_text(
            "Choose a subject to study:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data == "start_creating":
        keyboard = get_subject_keyboard(include_back=False)
        await query.edit_message_text(
            "Select the subject for your question:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return SUBJECT_SELECTION

    elif query.data.startswith("subject_"):
        subject = query.data.split("_")[1]
        if context.user_data.get('creating_question'):
            context.user_data['question_subject'] = subject
            await query.edit_message_text(
                "Enter your question text.\n\n"
                "Then, enter all choices (A to D) separated by new lines.\n"
                "Example:\nChoice A\nChoice B\nChoice C\nChoice D",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ Cancel", callback_data="cancel_creation")
                ]])
            )
            return CHOICES
        else:
            study_session.start_study(user_id, subject)
            # Delete previous message and send new one without buttons
            await query.edit_message_text(
                f"📚 {username} started studying {subject}."
            )

    elif query.data == "take_break":
        if study_session.start_break(user_id):
            session = study_session.get_active_session(user_id)
            await query.edit_message_text(
                f"☕ {username} started their break."
            )

    elif query.data == "end_break":
        if study_session.is_on_break(user_id):
            break_duration = study_session.end_break(user_id)
            await query.edit_message_text(
                f"⏰ {username} ended their break and resumed studying."
            )

    elif query.data == "end_session":
        subject, study_time, break_time = study_session.end_study(user_id)
        if subject:
            if user_id not in study_data:
                study_data[user_id] = {}
            if subject not in study_data[user_id]:
                study_data[user_id][subject] = {'study_time': 0, 'break_time': 0}
            
            study_data[user_id][subject]['study_time'] += study_time
            study_data[user_id][subject]['break_time'] += break_time
            save_study_data(study_data)

            # Generate and send dashboard
            image_gen = ImageGenerator()
            dashboard = image_gen.save_dashboard(study_data[user_id], username)
            
            with open(dashboard, 'rb') as photo:
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=photo,
                    caption=f"Study session ended!\nTotal study time: {study_time/3600:.1f} hours\n"
                            f"Total break time: {break_time/3600:.1f} hours"
                )
            os.remove(dashboard)  # Clean up the image file

    elif query.data == "back_to_main":
        await start(update, context)

    elif query.data == "cancel_creation":
        context.user_data.clear()
        await query.edit_message_text(
            "Question creation cancelled. /start to begin again."
        )
        return ConversationHandler.END

async def handle_choices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle receiving all choices at once."""
    if not update.message.text:
        await update.message.reply_text(
            "Please send text choices.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data="cancel_creation")
            ]])
        )
        return CHOICES

    # Split text into lines and validate
    lines = update.message.text.strip().split('\n')
    if len(lines) != 4:
        await update.message.reply_text(
            "Please provide exactly 4 choices (A to D), one per line.\nExample:\nChoice A\nChoice B\nChoice C\nChoice D",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data="cancel_creation")
            ]])
        )
        return CHOICES

    context.user_data['choices'] = lines
    
    # Create keyboard for correct answer selection
    keyboard = [
        [InlineKeyboardButton(f"Choice {letter}", callback_data=f"correct_{i}")]
        for i, letter in enumerate(['A', 'B', 'C', 'D'])
    ]
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_creation")])

    await update.message.reply_text(
        "Select the correct answer:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CORRECT_ANSWER

async def handle_correct_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle correct answer selection."""
    query = update.callback_query
    await query.answer()

    if query.data == "cancel_creation":
        context.user_data.clear()
        await query.edit_message_text("Question creation cancelled. /start to begin again.")
        return ConversationHandler.END

    correct_index = int(query.data.split('_')[1])
    context.user_data['correct_answer'] = correct_index

    await query.edit_message_text(
        "Enter the explanation for the correct answer:",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_creation")
        ]])
    )
    return EXPLANATION

async def handle_explanation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle explanation and save the question."""
    if not update.message.text:
        await update.message.reply_text(
            "Please send a text explanation.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data="cancel_creation")
            ]])
        )
        return EXPLANATION

    # Save the complete question
    question_data = {
        'subject': context.user_data['question_subject'],
        'choices': context.user_data['choices'],
        'correct_answer': context.user_data['correct_answer'],
        'explanation': update.message.text,
        'created_by': update.effective_user.username or "Unknown",
        'created_at': datetime.now(pytz.UTC).strftime('%Y-%m-%d %H:%M:%S UTC')
    }

    # Generate unique question ID
    question_id = str(int(time.time() * 1000))
    if 'questions' not in context.bot_data:
        context.bot_data['questions'] = {}
    context.bot_data['questions'][question_id] = question_data
    save_questions(context.bot_data['questions'])

    # Display the created question
    question_text = (
        f"Subject: {question_data['subject']}\n\n"
        f"Question created by: {question_data['created_by']}\n"
        f"Created at: {question_data['created_at']}\n\n"
        "Choices:\n"
    )
    for i, choice in enumerate(question_data['choices']):
        letter = chr(65 + i)  # Convert 0,1,2,3 to A,B,C,D
        question_text += f"{letter}. {choice}\n"

    keyboard = [
        [
            InlineKeyboardButton("🗑️ DELETE QUESTION", callback_data=f"delete_{question_id}"),
            InlineKeyboardButton("➕ START NEW QUESTION", callback_data="start_creating")
        ]
    ]

    await update.message.reply_text(
        question_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    context.user_data.clear()
    return ConversationHandler.END

async def handle_answer_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle when user answers a question."""
    query = update.callback_query
    await query.answer()

    if query.data.startswith("answer_"):
        _, question_id, answer_index = query.data.split("_")
        question_data = context.bot_data['questions'].get(question_id)
        
        if not question_data:
            await query.edit_message_text("Question not found.")
            return

        answer_index = int(answer_index)
        correct_index = question_data['correct_answer']
        
        # Prepare result message with effects
        if answer_index == correct_index:
            result = "✨ CORRECT! ✨\n\n"
            effect = "🌟 Great job! 🌟"
        else:
            result = "❌ INCORRECT ❌\n\n"
            effect = "💫 Keep trying! 💫"

        result += (
            f"{effect}\n\n"
            f"Explanation:\n{question_data['explanation']}\n\n"
            f"Correct answer: {chr(65 + correct_index)}. {question_data['choices'][correct_index]}"
        )

        await query.edit_message_text(
            result,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Next Question", callback_data="next_question")
            ]])
        )

async def delete_question_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle question deletion confirmation."""
    query = update.callback_query
    await query.answer()

    if query.data.startswith("delete_"):
        question_id = query.data.split("_")[1]
        keyboard = [
            [
                InlineKeyboardButton("✅ Yes, delete", callback_data=f"confirm_delete_{question_id}"),
                InlineKeyboardButton("❌ No, keep", callback_data=f"keep_{question_id}")
            ]
        ]
        await query.edit_message_text(
            "Are you sure you want to delete this question?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def handle_delete_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process question deletion confirmation."""
    query = update.callback_query
    await query.answer()

    if query.data.startswith("confirm_delete_"):
        question_id = query.data.split("_")[2]
        if question_id in context.bot_data['questions']:
            del context.bot_data['questions'][question_id]
            save_questions(context.bot_data['questions'])
            await query.edit_message_text("Question deleted successfully.")
    elif query.data.startswith("keep_"):
        await query.edit_message_text("Question deletion cancelled.")

  # Error handlers
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log Errors caused by Updates."""
    logger.warning('Update "%s" caused error "%s"', update, context.error)
    try:
        # Send error message to user
        await update.message.reply_text(
            "Sorry, something went wrong. Please try again or use /start to restart."
        )
    except:
        pass

async def main() -> None:
    """Start the bot."""
    # Create the Application
    application = Application.builder().token(TOKEN).build()

    # Add conversation handler for question creation
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_callback, pattern='^start_creating$')],
        states={
            SUBJECT_SELECTION: [
                CallbackQueryHandler(handle_callback, pattern='^subject_')
            ],
            CHOICES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_choices),
                CallbackQueryHandler(handle_callback, pattern='^cancel_creation$')
            ],
            CORRECT_ANSWER: [
                CallbackQueryHandler(handle_callback, pattern='^correct_\d+$'),
                CallbackQueryHandler(handle_callback, pattern='^cancel_creation$')
            ],
            EXPLANATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_explanation),
                CallbackQueryHandler(handle_callback, pattern='^cancel_creation$')
            ]
        },
        fallbacks=[
            CommandHandler('start', start),
            CallbackQueryHandler(handle_callback, pattern='^cancel_creation$')
        ],
        per_message=True
    )

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    # Add error handler
    application.add_error_handler(error_handler)

    # Get environment variables
    webhook_url = os.getenv('WEBHOOK_URL')
    port = int(os.getenv('PORT', 10000))

    if webhook_url:
        # Use webhook
        await application.bot.set_webhook(url=webhook_url)
        webhook_path = url.parse.urlparse(webhook_url).path
        
        # Start webhook
        await application.start()
        print(f"Starting webhook on port {port}")
        await application.run_webhook(
            listen="0.0.0.0",
            port=port,
            webhook_url=webhook_url
        )
    else:
        # Use polling
        await application.bot.delete_webhook()
        await application.start()
        print("Starting polling")
        await application.run_polling(allowed_updates=Update.ALL_TYPES)

def format_duration(seconds):
    """Format duration in seconds to human-readable string."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours:.0f}h {minutes:.0f}m"

def get_formatted_timestamp():
    """Return the current timestamp in consistent format."""
    return "2025-06-05 08:35:19 UTC"

def get_current_user():
    """Get current user's login."""
    return "Zackrmt"

def update_dashboard_timestamp(draw, font, x, y):
    """Update dashboard timestamp with current datetime."""
    timestamp_text = f"Generated at: {get_formatted_timestamp()}"
    creator_text = f"Study bot created by {get_current_user()}"
    
    draw.text((x, y), timestamp_text, fill="#888888", font=font)
    draw.text((x, y + 20), creator_text, fill="#888888", font=font)

def create_dashboard_metadata():
    """Create metadata for dashboard."""
    return {
        'generated_at': "2025-06-05 08:35:19",
        'user': "Zackrmt",
        'timezone': 'UTC'
    }

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('Bot stopped gracefully')
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)

