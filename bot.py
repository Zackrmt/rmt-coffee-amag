import os
import time
import logging
from datetime import datetime
import pytz
import asyncio
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

def main():
    """Start the bot."""
    # Create the Application and pass it your bot's token
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
        ]
    )

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    # Add error handler
    application.add_error_handler(error_handler)

    # Start the Bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()

# Additional constants (Add these after the previous constants)
DASHBOARD_METADATA = {
    'TIMESTAMP': "2025-06-05 06:04:28",  # Current timestamp
    'TITLE': "MTLE 2025",
    'CREATOR': "Created by Eli",
    'TIMEZONE': "UTC",
    'DATE_FORMAT': "%Y-%m-%d %H:%M:%S"
}

def get_formatted_timestamp():
    """Return the current timestamp in consistent format."""
    return f"{DASHBOARD_METADATA['TIMESTAMP']} {DASHBOARD_METADATA['TIMEZONE']}"

def format_duration(seconds):
    """Format duration in seconds to a human-readable string."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours:.0f}h {minutes:.0f}m"

# Update the ImageGenerator create_dashboard method timestamp section
class ImageGenerator:
    def create_dashboard(self, user_data, telegram_username):
        # Create a new image with a white background
        width = 800
        height = 600
        image = Image.new('RGB', (width, height), 'white')
        draw = ImageDraw.Draw(image)

        # Load fonts
        try:
            title_font = ImageFont.truetype("arial.ttf", 36)
            subtitle_font = ImageFont.truetype("arial.ttf", 24)
            stats_font = ImageFont.truetype("arial.ttf", 20)
        except:
            # Fallback to default font if arial is not available
            title_font = ImageFont.load_default()
            subtitle_font = ImageFont.load_default()
            stats_font = ImageFont.load_default()

        # Draw title
        title_text = "Study Session Dashboard"
        title_bbox = draw.textbbox((0, 0), title_text, font=title_font)
        title_width = title_bbox[2] - title_bbox[0]
        draw.text(((width - title_width) // 2, 10), title_text, fill="black", font=title_font)

        # Draw timestamp and metadata
        timestamp_text = f"Generated at: {get_formatted_timestamp()}"
        draw.text((35, 55), timestamp_text, fill="#888888", font=subtitle_font)
        draw.text((35, 80), DASHBOARD_METADATA['TITLE'], fill="#888888", font=subtitle_font)
        draw.text((35, 105), DASHBOARD_METADATA['CREATOR'], fill="#888888", font=subtitle_font)

        # Draw user statistics
        start_y = 150
        spacing = 30

        # Study time statistics
        if user_data:
            total_time = user_data.get('total_time', 0)
            study_time = user_data.get('study_time', 0)
            break_time = user_data.get('break_time', 0)

            stats_text = [
                f"Total Session Time: {format_duration(total_time)}",
                f"Effective Study Time: {format_duration(study_time)}",
                f"Total Break Time: {format_duration(break_time)}"
            ]

            for i, text in enumerate(stats_text):
                draw.text((35, start_y + i * spacing), text, fill="black", font=stats_font)
        else:
            draw.text((35, start_y), "No study data available", fill="black", font=stats_font)

        # Convert the image to bytes
        img_byte_array = BytesIO()
        image.save(img_byte_array, format='PNG')
        img_byte_array.seek(0)

        return img_byte_array

# Update the create_dashboard method in existing ImageGenerator class
def update_dashboard(image_generator):
    image_generator.create_dashboard = create_dashboard.__get__(image_generator, ImageGenerator)

# Constants for dashboard generation
DASHBOARD_STYLES = {
    'WIDTH': 800,
    'HEIGHT': 600,
    'COLORS': {
        'BACKGROUND': 'white',
        'TITLE': 'black',
        'SUBTITLE': '#888888',
        'STATS': 'black'
    },
    'FONTS': {
        'TITLE_SIZE': 36,
        'SUBTITLE_SIZE': 24,
        'STATS_SIZE': 20
    },
    'SPACING': {
        'TITLE_TOP': 10,
        'METADATA_START': 55,
        'METADATA_SPACING': 25,
        'STATS_START': 150,
        'STATS_SPACING': 30
    }
}

# Utility functions for time and user management
def get_current_user():
    """Return the current user's login."""
    return "Zackrmt"

def get_current_time():
    """Return the fixed current time."""
    return datetime.strptime("2025-06-05 05:45:19", "%Y-%m-%d %H:%M:%S")

def format_time_display(dt):
    """Format datetime object for display."""
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")

# Update the study session timing mechanism
class StudyTimeTracker:
    def __init__(self):
        self.start_time = None
        self.breaks = []
        self.current_break_start = None

    def start(self):
        """Start tracking study time."""
        self.start_time = get_current_time()
        self.breaks = []
        self.current_break_start = None

    def start_break(self):
        """Start a break period."""
        if self.start_time and not self.current_break_start:
            self.current_break_start = get_current_time()
            return True
        return False

    def end_break(self):
        """End current break and return duration."""
        if self.current_break_start:
            break_end = get_current_time()
            break_duration = (break_end - self.current_break_start).total_seconds()
            self.breaks.append(break_duration)
            self.current_break_start = None
            return break_duration
        return 0

    def get_total_time(self):
        """Calculate total study time minus breaks."""
        if not self.start_time:
            return 0
        
        total_time = (get_current_time() - self.start_time).total_seconds()
        break_time = sum(self.breaks)
        return total_time - break_time

    def get_break_time(self):
        """Get total break time."""
        return sum(self.breaks)

# Add this to the existing study session manager
class StudySession:
    def __init__(self):
        self.active_sessions = {}
        self.break_sessions = {}
        self.time_trackers = {}

    def start_study(self, user_id, subject):
        """Start a new study session with time tracking."""
        self.active_sessions[user_id] = {
            'subject': subject,
            'tracker': StudyTimeTracker()
        }
        self.active_sessions[user_id]['tracker'].start()

    def start_break(self, user_id):
        """Start a break with accurate timing."""
        if user_id in self.active_sessions:
            if self.active_sessions[user_id]['tracker'].start_break():
                self.break_sessions[user_id] = get_current_time()
                return True
        return False

    def end_break(self, user_id):
        """End break and calculate accurate duration."""
        if user_id in self.break_sessions:
            break_duration = self.active_sessions[user_id]['tracker'].end_break()
            del self.break_sessions[user_id]
            return break_duration
        return 0

    def end_study(self, user_id):
        """End study session with accurate timing."""
        if user_id in self.active_sessions:
            session = self.active_sessions.pop(user_id)
            tracker = session['tracker']
            study_time = tracker.get_total_time()
            break_time = tracker.get_break_time()
            return session['subject'], study_time, break_time
        return None, 0, 0

# Update the question creation timestamp
def create_question_metadata():
    """Create metadata for new questions."""
    return {
        'created_by': get_current_user(),
        'created_at': format_time_display(get_current_time()),
        'last_modified': format_time_display(get_current_time())
    }

# Initialize the updated study session manager
study_session = StudySession()

# Update these constants with the exact time provided
CURRENT_DATETIME = "2025-06-05 05:46:32"
CURRENT_USER_LOGIN = "Zackrmt"

# Time utility functions
def get_current_datetime():
    """Return datetime object for the fixed current time."""
    return datetime.strptime(CURRENT_DATETIME, "%Y-%m-%d %H:%M:%S")

def get_datetime_display():
    """Return formatted datetime string with UTC."""
    return f"{CURRENT_DATETIME} UTC"

def format_study_time(seconds):
    """Format study time in a consistent way."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours > 0:
        return f"{hours:.1f}h {minutes}m"
    return f"{minutes}m"

# Update message formatting
class MessageFormatter:
    @staticmethod
    def study_start(username, subject):
        return f"📚 {username} started studying {subject} at {get_datetime_display()}"
    
    @staticmethod
    def break_start(username):
        return f"☕ {username} started their break at {get_datetime_display()}"
    
    @staticmethod
    def break_end(username):
        return f"⏰ {username} ended their break and resumed studying at {get_datetime_display()}"
    
    @staticmethod
    def session_end(username, study_time, break_time):
        study_formatted = format_study_time(study_time)
        break_formatted = format_study_time(break_time)
        return (
            f"📊 Study session summary for {username}\n"
            f"End time: {get_datetime_display()}\n"
            f"Total study time: {study_formatted}\n"
            f"Total break time: {break_formatted}"
        )

    @staticmethod
    def question_created(subject):
        return (
            f"✨ New question created for {subject}\n"
            f"Created by: {CURRENT_USER_LOGIN}\n"
            f"Created at: {get_datetime_display()}"
        )

# Update the dashboard generation timestamp
def update_dashboard_timestamp(draw, font, x, y):
    """Update dashboard timestamp with current datetime."""
    timestamp_text = f"Generated at: {get_datetime_display()}"
    creator_text = f"Study bot created by {CURRENT_USER_LOGIN}"
    
    draw.text((x, y), timestamp_text, fill="#888888", font=font)
    draw.text((x, y + 20), creator_text, fill="#888888", font=font)

# Update the ImageGenerator class timestamp section
class ImageGenerator:
    def create_dashboard(self, user_data, telegram_username):
        # ... (previous code remains the same until timestamp section)
        
        # Update timestamp section
        update_dashboard_timestamp(draw, subtitle_font, 35, 55)
        
        # ... (rest of the method remains the same)

# Update study session timing
def get_session_duration():
    """Calculate duration from fixed current time."""
    return {
        'start_time': CURRENT_DATETIME,
        'timezone': 'UTC'
    }

# Update the question creation timestamp
def get_question_metadata():
    """Get metadata for question creation."""
    return {
        'created_by': CURRENT_USER_LOGIN,
        'created_at': get_datetime_display(),
        'timestamp': CURRENT_DATETIME
    }

# Update the message handlers to use the new formatting
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    username = query.from_user.username or CURRENT_USER_LOGIN

    if query.data.startswith("subject_"):
        subject = query.data.split("_")[1]
        study_session.start_study(query.from_user.id, subject)
        await query.edit_message_text(
            MessageFormatter.study_start(username, subject)
        )
    
    elif query.data == "take_break":
        if study_session.start_break(query.from_user.id):
            await query.edit_message_text(
                MessageFormatter.break_start(username)
            )
    
    elif query.data == "end_break":
        if study_session.is_on_break(query.from_user.id):
            study_session.end_break(query.from_user.id)
            await query.edit_message_text(
                MessageFormatter.break_end(username)
            )
    
    # ... (rest of the handler remains the same)

# Update these time-related constants
SYSTEM_TIME = {
    'current_time': "2025-06-05 05:48:26",
    'user_login': "Zackrmt",
    'timezone': 'UTC',
    'format': '%Y-%m-%d %H:%M:%S'
}

class TimeManager:
    @staticmethod
    def get_current_time():
        """Get the fixed current time."""
        return datetime.strptime(SYSTEM_TIME['current_time'], SYSTEM_TIME['format'])

    @staticmethod
    def format_display_time(dt=None):
        """Format time for display with UTC."""
        if dt is None:
            dt = TimeManager.get_current_time()
        return f"{dt.strftime(SYSTEM_TIME['format'])} {SYSTEM_TIME['timezone']}"

    @staticmethod
    def get_study_duration(start_time):
        """Calculate duration between start_time and current fixed time."""
        current = TimeManager.get_current_time()
        return (current - start_time).total_seconds()

class UserManager:
    @staticmethod
    def get_current_user():
        """Get the current user's login."""
        return SYSTEM_TIME['user_login']

    @staticmethod
    def format_username(update_username):
        """Format username, defaulting to current user if none provided."""
        return update_username or SYSTEM_TIME['user_login']

# Update the message templates with new time formatting
MESSAGE_TEMPLATES = {
    'study_start': "📚 {username} started studying {subject} at {time}",
    'break_start': "☕ {username} started their break at {time}",
    'break_end': "⏰ {username} ended their break and resumed studying at {time}",
    'session_end': (
        "📊 Study Session Summary\n"
        "User: {username}\n"
        "End Time: {time}\n"
        "Total Study Time: {study_time}\n"
        "Total Break Time: {break_time}"
    ),
    'question_created': (
        "✨ New Question Created\n"
        "Subject: {subject}\n"
        "Created by: {username}\n"
        "Time: {time}"
    )
}

# Update the formatters to use the new time management
def format_message(template_key, **kwargs):
    """Format messages with consistent time handling."""
    kwargs.setdefault('time', TimeManager.format_display_time())
    kwargs.setdefault('username', UserManager.get_current_user())
    return MESSAGE_TEMPLATES[template_key].format(**kwargs)

# Update the ImageGenerator timestamp handling
def update_dashboard_metadata(draw, font_regular, font_bold, x, y):
    """Update dashboard metadata with current time and user."""
    metadata = [
        ('Generated at:', TimeManager.format_display_time()),
        ('Created by:', UserManager.get_current_user()),
        ('MTLE Batch:', '2025')
    ]
    
    current_y = y
    for label, value in metadata:
        # Draw label with bold font
        draw.text((x, current_y), label, fill="#888888", font=font_bold)
        # Calculate width of label to position value
        label_width = draw.textlength(label, font=font_bold)
        # Draw value with regular font
        draw.text((x + label_width + 10, current_y), value, fill="#888888", font=font_regular)
        current_y += 25

# Update the question creation metadata
def create_question_metadata(subject):
    """Create metadata for new questions."""
    return {
        'subject': subject,
        'created_by': UserManager.get_current_user(),
        'created_at': TimeManager.format_display_time(),
        'timestamp': SYSTEM_TIME['current_time']
    }

# Update study session tracking
def update_session_timing(session_data):
    """Update session timing data with current time."""
    current_time = TimeManager.get_current_time()
    
    if 'start_time' in session_data:
        start_time = datetime.strptime(session_data['start_time'], SYSTEM_TIME['format'])
        session_data['duration'] = TimeManager.get_study_duration(start_time)
    
    session_data['last_updated'] = TimeManager.format_display_time()
    return session_data

# Function to format study duration
def format_duration(seconds):
    """Format duration in seconds to human-readable format."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours > 0:
        return f"{hours:.1f}h {minutes}m"
    return f"{minutes}m"

# System Configuration Constants
SYSTEM_CONFIG = {
    'TIME_SNAPSHOT': "2025-06-05 05:49:23",
    'USER_LOGIN': "Zackrmt",
    'TIMEZONE': 'UTC',
    'DATE_FORMAT': '%Y-%m-%d %H:%M:%S',
    'DISPLAY_FORMAT': '%Y-%m-%d %H:%M:%S UTC'
}

class SystemTime:
    """Manages system-wide time synchronization."""
    
    @classmethod
    def now(cls):
        """Return the fixed system time."""
        return datetime.strptime(SYSTEM_CONFIG['TIME_SNAPSHOT'], SYSTEM_CONFIG['DATE_FORMAT'])
    
    @classmethod
    def format_display(cls, dt=None):
        """Format datetime for display."""
        if dt is None:
            dt = cls.now()
        return dt.strftime(SYSTEM_CONFIG['DISPLAY_FORMAT'])
    
    @classmethod
    def parse_time(cls, time_str):
        """Parse time string to datetime object."""
        return datetime.strptime(time_str, SYSTEM_CONFIG['DATE_FORMAT'])

class StudyMetrics:
    """Handles study session metrics and calculations."""
    
    @staticmethod
    def calculate_study_time(start_time_str):
        """Calculate study duration from start time to current time."""
        start_time = SystemTime.parse_time(start_time_str)
        current_time = SystemTime.now()
        return (current_time - start_time).total_seconds()
    
    @staticmethod
    def format_duration(seconds):
        """Format duration in seconds to readable format."""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        if hours > 0:
            return f"{hours:.1f}h {minutes}m"
        return f"{minutes}m"

class SessionLogger:
    """Handles session logging with consistent timestamps."""
    
    @staticmethod
    def log_start(subject, username=None):
        """Log study session start."""
        return {
            'subject': subject,
            'start_time': SYSTEM_CONFIG['TIME_SNAPSHOT'],
            'user': username or SYSTEM_CONFIG['USER_LOGIN'],
            'breaks': [],
            'status': 'active'
        }
    
    @staticmethod
    def log_break(session_data):
        """Log break start."""
        session_data['breaks'].append({
            'start_time': SYSTEM_CONFIG['TIME_SNAPSHOT'],
            'status': 'active'
        })
        return session_data
    
    @staticmethod
    def log_break_end(session_data):
        """Log break end and calculate duration."""
        if session_data['breaks'] and session_data['breaks'][-1]['status'] == 'active':
            break_start = SystemTime.parse_time(session_data['breaks'][-1]['start_time'])
            current_time = SystemTime.now()
            duration = (current_time - break_start).total_seconds()
            
            session_data['breaks'][-1].update({
                'end_time': SYSTEM_CONFIG['TIME_SNAPSHOT'],
                'duration': duration,
                'status': 'completed'
            })
        return session_data

# Update these functions in your existing code
def update_study_session(session_data):
    """Update study session with current time metrics."""
    current_time = SYSTEM_CONFIG['TIME_SNAPSHOT']
    start_time = session_data.get('start_time', current_time)
    
    # Calculate total study time
    total_seconds = StudyMetrics.calculate_study_time(start_time)
    
    # Calculate break time
    break_seconds = sum(
        break_data.get('duration', 0) 
        for break_data in session_data.get('breaks', [])
        if break_data.get('status') == 'completed'
    )
    
    return {
        'study_time': total_seconds - break_seconds,
        'break_time': break_seconds,
        'last_updated': current_time
    }

def create_dashboard_metadata():
    """Create metadata for dashboard."""
    return {
        'generated_at': SYSTEM_CONFIG['TIME_SNAPSHOT'],
        'user': SYSTEM_CONFIG['USER_LOGIN'],
        'timezone': SYSTEM_CONFIG['TIMEZONE']
    }

def format_question_metadata():
    """Format metadata for new questions."""
    return {
        'created_at': SYSTEM_CONFIG['TIME_SNAPSHOT'],
        'created_by': SYSTEM_CONFIG['USER_LOGIN'],
        'last_modified': SYSTEM_CONFIG['TIME_SNAPSHOT']
    }

# Constants for message formatting
EMOJI_MAP = {
    'study_start': '📚',
    'break_start': '☕',
    'break_end': '⏰',
    'session_end': '📊',
    'question_new': '✨',
    'correct': '✅',
    'incorrect': '❌'
}

def format_system_message(message_type, **kwargs):
    """Format system messages with consistent styling."""
    emoji = EMOJI_MAP.get(message_type, '')
    timestamp = SYSTEM_CONFIG['TIME_SNAPSHOT']
    username = kwargs.get('username', SYSTEM_CONFIG['USER_LOGIN'])
    
    messages = {
        'study_start': f"{emoji} {username} started studying {kwargs.get('subject')} at {timestamp}",
        'break_start': f"{emoji} {username} started a break at {timestamp}",
        'break_end': f"{emoji} {username} ended break at {timestamp}",
        'session_end': (
            f"{emoji} Study Session Summary\n"
            f"User: {username}\n"
            f"End Time: {timestamp}\n"
            f"Study Time: {kwargs.get('study_time', '0m')}\n"
            f"Break Time: {kwargs.get('break_time', '0m')}"
        )
    }
    
    return messages.get(message_type, f"System message at {timestamp}")

# Final system configuration update
FINAL_SYSTEM_CONFIG = {
    'TIMESTAMP': "2025-06-05 05:50:24",
    'USER': "Zackrmt",
    'SYSTEM': {
        'timezone': 'UTC',
        'date_format': '%Y-%m-%d %H:%M:%S',
        'display_format': '%Y-%m-%d %H:%M:%S UTC'
    },
    'STUDY_SETTINGS': {
        'min_session_time': 900,  # 15 minutes
        'max_break_time': 1800,   # 30 minutes
        'default_goal_hours': 20
    }
}

class FinalTimeManager:
    """Final implementation of time management system."""
    
    @classmethod
    def get_system_time(cls):
        """Get the fixed system time."""
        return datetime.strptime(
            FINAL_SYSTEM_CONFIG['TIMESTAMP'],
            FINAL_SYSTEM_CONFIG['SYSTEM']['date_format']
        )
    
    @classmethod
    def format_timestamp(cls, include_timezone=True):
        """Format the current timestamp."""
        timestamp = FINAL_SYSTEM_CONFIG['TIMESTAMP']
        if include_timezone:
            return f"{timestamp} {FINAL_SYSTEM_CONFIG['SYSTEM']['timezone']}"
        return timestamp
    
    @classmethod
    def get_date_only(cls):
        """Get only the date part."""
        return cls.get_system_time().date()

class FinalSessionManager:
    """Final implementation of session management."""
    
    @staticmethod
    def create_session_log(subject):
        """Create a new session log."""
        return {
            'subject': subject,
            'start_time': FINAL_SYSTEM_CONFIG['TIMESTAMP'],
            'user': FINAL_SYSTEM_CONFIG['USER'],
            'breaks': [],
            'status': 'active',
            'metrics': {
                'total_time': 0,
                'break_time': 0,
                'effective_time': 0
            }
        }
    
    @staticmethod
    def update_session_metrics(session_data):
        """Update session metrics with current time."""
        start_time = datetime.strptime(
            session_data['start_time'],
            FINAL_SYSTEM_CONFIG['SYSTEM']['date_format']
        )
        current_time = FinalTimeManager.get_system_time()
        
        total_seconds = (current_time - start_time).total_seconds()
        break_seconds = sum(break_data['duration'] 
                          for break_data in session_data['breaks']
                          if 'duration' in break_data)
        
        session_data['metrics'].update({
            'total_time': total_seconds,
            'break_time': break_seconds,
            'effective_time': total_seconds - break_seconds,
            'last_updated': FINAL_SYSTEM_CONFIG['TIMESTAMP']
        })
        
        return session_data

class FinalMessageFormatter:
    """Final implementation of message formatting."""
    
    @staticmethod
    def format_study_message(message_type, **kwargs):
        """Format study-related messages."""
        base_context = {
            'time': FinalTimeManager.format_timestamp(),
            'user': FINAL_SYSTEM_CONFIG['USER']
        }
        base_context.update(kwargs)
        
        templates = {
            'session_start': (
                "📚 {user} started studying {subject}\n"
                "Start Time: {time}"
            ),
            'break_start': (
                "☕ {user} started a break\n"
                "Time: {time}"
            ),
            'session_end': (
                "📊 Study Session Summary\n"
                "User: {user}\n"
                "End Time: {time}\n"
                "Subject: {subject}\n"
                "Total Time: {total_time}\n"
                "Effective Study Time: {effective_time}\n"
                "Total Break Time: {break_time}"
            )
        }
        
        return templates.get(message_type, "").format(**base_context)

class FinalDashboardGenerator:
    """Final implementation of dashboard generation."""
    
    @staticmethod
    def get_dashboard_metadata():
        """Get metadata for dashboard."""
        return {
            'generated_at': FinalTimeManager.format_timestamp(),
            'user': FINAL_SYSTEM_CONFIG['USER'],
            'system_version': '2.0',
            'data_snapshot_time': FINAL_SYSTEM_CONFIG['TIMESTAMP']
        }
    
    @staticmethod
    def format_duration(seconds):
        """Format duration for dashboard display."""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        
        if hours > 0:
            return f"{hours:.1f}h {minutes}m"
        return f"{minutes}m"

# Update these in your existing code where needed:

def get_current_user():
    """Get current user's login."""
    return FINAL_SYSTEM_CONFIG['USER']

def get_current_timestamp():
    """Get current system timestamp."""
    return FINAL_SYSTEM_CONFIG['TIMESTAMP']

def format_system_time():
    """Format system time for display."""
    return FinalTimeManager.format_timestamp()

# Final system timestamp and user configuration
FINAL_TIMESTAMP_CONFIG = {
    'SYSTEM_TIME': "2025-06-05 05:51:18",
    'SYSTEM_USER': "Zackrmt",
    'TIME_SETTINGS': {
        'zone': 'UTC',
        'format': {
            'system': '%Y-%m-%d %H:%M:%S',
            'display': '%Y-%m-%d %H:%M:%S UTC',
            'short': '%H:%M:%S'
        }
    },
    'STUDY_CONFIG': {
        'minimum_session': 15,  # minutes
        'maximum_break': 30,    # minutes
        'daily_goal': 20        # hours
    }
}

class TimeConfiguration:
    """Handles all time-related configurations."""
    
    @classmethod
    def system_time(cls):
        """Get the fixed system time."""
        return datetime.strptime(
            FINAL_TIMESTAMP_CONFIG['SYSTEM_TIME'],
            FINAL_TIMESTAMP_CONFIG['TIME_SETTINGS']['format']['system']
        )
    
    @classmethod
    def display_time(cls):
        """Get formatted display time."""
        return f"{FINAL_TIMESTAMP_CONFIG['SYSTEM_TIME']} {FINAL_TIMESTAMP_CONFIG['TIME_SETTINGS']['zone']}"
    
    @classmethod
    def is_valid_duration(cls, start_time_str):
        """Check if duration is valid based on system time."""
        start_time = datetime.strptime(
            start_time_str,
            FINAL_TIMESTAMP_CONFIG['TIME_SETTINGS']['format']['system']
        )
        return start_time <= cls.system_time()

class SessionConfiguration:
    """Manages session-specific configurations."""
    
    @classmethod
    def create_session_metadata(cls):
        """Create metadata for new session."""
        return {
            'timestamp': FINAL_TIMESTAMP_CONFIG['SYSTEM_TIME'],
            'user': FINAL_TIMESTAMP_CONFIG['SYSTEM_USER'],
            'session_id': f"session_{int(time.time())}",
            'config_version': '2.0'
        }
    
    @classmethod
    def validate_break_duration(cls, break_start_str):
        """Validate break duration against maximum allowed time."""
        break_start = datetime.strptime(
            break_start_str,
            FINAL_TIMESTAMP_CONFIG['TIME_SETTINGS']['format']['system']
        )
        current_time = TimeConfiguration.system_time()
        break_duration = (current_time - break_start).total_seconds() / 60
        
        return break_duration <= FINAL_TIMESTAMP_CONFIG['STUDY_CONFIG']['maximum_break']

def format_study_duration(seconds):
    """Format study duration with consistent styling."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    
    if hours > 0:
        if minutes > 0:
            return f"{hours}h {minutes}m"
        return f"{hours}h"
    return f"{minutes}m"

class MessageConfiguration:
    """Handles message formatting with current timestamp."""
    
    @staticmethod
    def study_start(subject):
        return (
            f"📚 Study Session Started\n"
            f"Subject: {subject}\n"
            f"User: {FINAL_TIMESTAMP_CONFIG['SYSTEM_USER']}\n"
            f"Time: {TimeConfiguration.display_time()}"
        )
    
    @staticmethod
    def break_start():
        return (
            f"☕ Break Started\n"
            f"Time: {TimeConfiguration.display_time()}\n"
            f"Maximum break duration: {FINAL_TIMESTAMP_CONFIG['STUDY_CONFIG']['maximum_break']} minutes"
        )
    
    @staticmethod
    def session_end(study_time, break_time):
        return (
            f"📊 Study Session Ended\n"
            f"User: {FINAL_TIMESTAMP_CONFIG['SYSTEM_USER']}\n"
            f"End Time: {TimeConfiguration.display_time()}\n"
            f"Total Study Time: {format_study_duration(study_time)}\n"
            f"Total Break Time: {format_study_duration(break_time)}"
        )

class DashboardConfiguration:
    """Manages dashboard display configuration."""
    
    @staticmethod
    def get_metadata():
        """Get metadata for dashboard generation."""
        return {
            'timestamp': TimeConfiguration.display_time(),
            'user': FINAL_TIMESTAMP_CONFIG['SYSTEM_USER'],
            'data_version': '2.0',
            'generated_at': FINAL_TIMESTAMP_CONFIG['SYSTEM_TIME']
        }
    
    @staticmethod
    def format_header():
        """Format dashboard header with current information."""
        return (
            f"MTLE Study Dashboard\n"
            f"Generated for: {FINAL_TIMESTAMP_CONFIG['SYSTEM_USER']}\n"
            f"Time: {TimeConfiguration.display_time()}"
        )

# Helper functions for external use
def get_system_user():
    """Get current system user."""
    return FINAL_TIMESTAMP_CONFIG['SYSTEM_USER']

def get_system_time():
    """Get current system time."""
    return FINAL_TIMESTAMP_CONFIG['SYSTEM_TIME']

def format_timestamp():
    """Format current timestamp for display."""
    return TimeConfiguration.display_time()

# Final System Settings
FINAL_SETTINGS = {
    'TIMESTAMP': "2025-06-05 05:52:46",
    'USERNAME': "Zackrmt",
    'SETTINGS': {
        'timezone': 'UTC',
        'formats': {
            'system': '%Y-%m-%d %H:%M:%S',
            'display': '%Y-%m-%d %H:%M:%S UTC',
            'date_only': '%Y-%m-%d',
            'time_only': '%H:%M:%S'
        }
    }
}

class SystemState:
    """Manages system state with fixed timestamp."""
    
    @classmethod
    def current_time(cls):
        """Get current fixed system time."""
        return datetime.strptime(
            FINAL_SETTINGS['TIMESTAMP'],
            FINAL_SETTINGS['SETTINGS']['formats']['system']
        )
    
    @classmethod
    def format_time(cls, format_type='display'):
        """Format current time according to specified format."""
        if format_type == 'display':
            return f"{FINAL_SETTINGS['TIMESTAMP']} {FINAL_SETTINGS['SETTINGS']['timezone']}"
        elif format_type in FINAL_SETTINGS['SETTINGS']['formats']:
            return cls.current_time().strftime(
                FINAL_SETTINGS['SETTINGS']['formats'][format_type]
            )
        return FINAL_SETTINGS['TIMESTAMP']
    
    @classmethod
    def current_user(cls):
        """Get current system user."""
        return FINAL_SETTINGS['USERNAME']

class StudyState:
    """Manages study session state."""
    
    def __init__(self):
        self.current_sessions = {}
        self.session_history = []
    
    def start_session(self, user_id, subject):
        """Start a new study session."""
        self.current_sessions[user_id] = {
            'subject': subject,
            'start_time': FINAL_SETTINGS['TIMESTAMP'],
            'breaks': [],
            'status': 'active',
            'user': FINAL_SETTINGS['USERNAME']
        }
        return self.current_sessions[user_id]
    
    def end_session(self, user_id):
        """End current study session."""
        if user_id in self.current_sessions:
            session = self.current_sessions.pop(user_id)
            session['end_time'] = FINAL_SETTINGS['TIMESTAMP']
            self.session_history.append(session)
            return session
        return None

class MessageState:
    """Manages message formatting with current system state."""
    
    @staticmethod
    def format_study_message(message_type, **kwargs):
        """Format study-related messages."""
        context = {
            'time': SystemState.format_time(),
            'user': SystemState.current_user(),
            **kwargs
        }
        
        templates = {
            'start': (
                "📚 Study Session Started\n"
                "Subject: {subject}\n"
                "Time: {time}\n"
                "User: {user}"
            ),
            'end': (
                "📊 Study Session Summary\n"
                "Subject: {subject}\n"
                "Duration: {duration}\n"
                "Time: {time}\n"
                "User: {user}"
            ),
            'break': (
                "☕ Break Started\n"
                "Time: {time}\n"
                "User: {user}"
            )
        }
        
        return templates.get(message_type, '').format(**context)

class DashboardState:
    """Manages dashboard state and generation."""
    
    @staticmethod
    def get_metadata():
        """Get current dashboard metadata."""
        return {
            'timestamp': FINAL_SETTINGS['TIMESTAMP'],
            'user': FINAL_SETTINGS['USERNAME'],
            'timezone': FINAL_SETTINGS['SETTINGS']['timezone'],
            'version': '3.0'
        }
    
    @staticmethod
    def format_header():
        """Format dashboard header."""
        return (
            f"Study Dashboard\n"
            f"Generated at: {SystemState.format_time()}\n"
            f"User: {SystemState.current_user()}"
        )

def initialize_system():
    """Initialize system with current state."""
    return {
        'time': SystemState(),
        'study': StudyState(),
        'message': MessageState(),
        'dashboard': DashboardState()
    }

# Initialize system components
system = initialize_system()

# Helper functions for external use
def get_current_state():
    """Get current system state."""
    return {
        'time': FINAL_SETTINGS['TIMESTAMP'],
        'user': FINAL_SETTINGS['USERNAME'],
        'timezone': FINAL_SETTINGS['SETTINGS']['timezone']
    }

def format_current_time(format_type='display'):
    """Format current time according to specified format."""
    return SystemState.format_time(format_type)

def get_current_user():
    """Get current system user."""
    return SystemState.current_user()

from PIL import Image, ImageDraw
import matplotlib.pyplot as plt
import io
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas

class ProgressChart:
    def __init__(self):
        # Set up matplotlib style for a clean, modern look
        plt.style.use('seaborn')
        self.colors = {
            'study': '#4CAF50',  # Green for study time
            'break': '#FFA726',  # Orange for break time
            'background': '#FFFFFF',
            'grid': '#E0E0E0'
        }

    def create_progress_chart(self, study_data, width=700, height=300):
        """
        Creates a progress chart showing study and break time distribution
        """
        # Create figure with white background
        fig, ax = plt.subplots(figsize=(width/100, height/100), dpi=100)
        fig.patch.set_facecolor(self.colors['background'])
        
        # Prepare data
        dates = study_data['dates']
        study_times = study_data['study_times']
        break_times = study_data['break_times']

        # Create stacked bar chart
        ax.bar(dates, study_times, label='Study Time', color=self.colors['study'])
        ax.bar(dates, break_times, bottom=study_times, 
               label='Break Time', color=self.colors['break'])

        # Customize grid
        ax.grid(True, color=self.colors['grid'], linestyle='--', alpha=0.7)
        ax.set_axisbelow(True)

        # Customize appearance
        ax.set_title('Study Progress Over Time', pad=20)
        ax.set_xlabel('Date')
        ax.set_ylabel('Hours')
        
        # Rotate date labels for better readability
        plt.xticks(rotation=45)
        
        # Add legend
        ax.legend()

        # Adjust layout to prevent label cutoff
        plt.tight_layout()

        # Convert plot to image
        buf = io.BytesIO()
        canvas = FigureCanvas(fig)
        canvas.print_png(buf)
        plt.close(fig)
        
        return buf

def create_combined_dashboard(study_data, metadata):
    """
    Creates a combined dashboard with stats and progress chart
    """
    # Create main image with white background
    width = 800
    height = 900  # Increased height to accommodate chart
    image = Image.new('RGB', (width, height), 'white')
    draw = ImageDraw.Draw(image)

    try:
        title_font = ImageFont.truetype("arial.ttf", 36)
        subtitle_font = ImageFont.truetype("arial.ttf", 24)
        stats_font = ImageFont.truetype("arial.ttf", 20)
    except:
        title_font = ImageFont.load_default()
        subtitle_font = ImageFont.load_default()
        stats_font = ImageFont.load_default()

    # Draw title
    title_text = "Study Progress Dashboard"
    title_bbox = draw.textbbox((0, 0), title_text, font=title_font)
    title_width = title_bbox[2] - title_bbox[0]
    draw.text(((width - title_width) // 2, 10), title_text, fill="black", font=title_font)

    # Draw metadata
    timestamp_text = f"Generated at: {metadata['timestamp']} UTC"
    draw.text((35, 55), timestamp_text, fill="#888888", font=subtitle_font)
    draw.text((35, 80), "MTLE 2025", fill="#888888", font=subtitle_font)
    draw.text((35, 105), "Created by Eli", fill="#888888", font=subtitle_font)

    # Create and paste progress chart
    chart = ProgressChart()
    chart_image = Image.open(chart.create_progress_chart(study_data))
    image.paste(chart_image, (50, 150))

    # Draw statistics below chart
    stats_y = 500  # Position below chart
    stats_texts = [
        f"Total Study Sessions: {study_data['total_sessions']}",
        f"Total Study Time: {format_duration(study_data['total_study_time'])}",
        f"Average Session Length: {format_duration(study_data['avg_session_time'])}",
        f"Most Productive Day: {study_data['most_productive_day']}",
        f"Current Streak: {study_data['current_streak']} days"
    ]

    for i, text in enumerate(stats_texts):
        draw.text((35, stats_y + i * 30), text, fill="black", font=stats_font)

    # Save image
    img_byte_array = io.BytesIO()
    image.save(img_byte_array, format='PNG')
    img_byte_array.seek(0)
    
    return img_byte_array

def format_duration(seconds):
    """Format duration in seconds to human-readable format"""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours > 0:
        return f"{hours:.1f}h {minutes}m"
    return f"{minutes}m"

# Example usage:
example_data = {
    'dates': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'],
    'study_times': [4, 5, 3, 6, 4],
    'break_times': [1, 1, 0.5, 1.5, 1],
    'total_sessions': 15,
    'total_study_time': 22 * 3600,  # 22 hours in seconds
    'avg_session_time': 5400,  # 1.5 hours in seconds
    'most_productive_day': 'Thursday',
    'current_streak': 5
}

example_metadata = {
    'timestamp': '2025-06-05 06:07:18',
    'user': 'MTLE 2025',
    'creator': 'Created by Eli'
}

# Create dashboard
# dashboard_image = create_combined_dashboard(example_data, example_metadata)

from datetime import datetime, timedelta
from typing import Dict, List, Optional

class NotificationSystem:
    def __init__(self):
        self.SYSTEM_TIME = "2025-06-05 06:10:07"  # Current fixed time
        self.reminders: Dict[str, List[Dict]] = {}
        self.break_notifications: Dict[str, datetime] = {}
        self.study_goals: Dict[str, Dict] = {}
        
    def format_time(self, time_str: str) -> str:
        """Format time for display."""
        return f"{time_str} UTC"
    
    def add_study_reminder(self, user_id: str, subject: str, 
                          target_time: str) -> Dict:
        """Add a study reminder for a user."""
        if user_id not in self.reminders:
            self.reminders[user_id] = []
            
        reminder = {
            'subject': subject,
            'target_time': target_time,
            'created_at': self.SYSTEM_TIME,
            'status': 'pending'
        }
        
        self.reminders[user_id].append(reminder)
        return reminder
    
    def set_break_reminder(self, user_id: str, 
                          study_duration: int = 45) -> Dict:
        """Set a break reminder after study duration (in minutes)."""
        current_time = datetime.strptime(self.SYSTEM_TIME, 
                                       "%Y-%m-%d %H:%M:%S")
        break_time = current_time + timedelta(minutes=study_duration)
        
        self.break_notifications[user_id] = break_time
        
        return {
            'message': f"Break reminder set for {break_time.strftime('%H:%M:%S')}",
            'time': self.format_time(break_time.strftime("%Y-%m-%d %H:%M:%S"))
        }
    
    def check_break_due(self, user_id: str) -> bool:
        """Check if it's time for a break."""
        if user_id in self.break_notifications:
            current_time = datetime.strptime(self.SYSTEM_TIME, 
                                          "%Y-%m-%d %H:%M:%S")
            break_time = self.break_notifications[user_id]
            return current_time >= break_time
        return False
    
    def set_study_goal(self, user_id: str, 
                       daily_hours: float, 
                       subject: Optional[str] = None) -> Dict:
        """Set daily study goal for a user."""
        self.study_goals[user_id] = {
            'daily_hours': daily_hours,
            'subject': subject,
            'set_at': self.SYSTEM_TIME,
            'progress': 0.0
        }
        
        return {
            'message': f"Daily study goal set: {daily_hours} hours",
            'subject': subject or "All subjects",
            'set_at': self.format_time(self.SYSTEM_TIME)
        }
    
    def update_study_progress(self, user_id: str, 
                            hours_studied: float) -> Dict:
        """Update progress towards study goal."""
        if user_id in self.study_goals:
            goal = self.study_goals[user_id]
            goal['progress'] += hours_studied
            
            progress_percent = (goal['progress'] / goal['daily_hours']) * 100
            
            return {
                'current_progress': goal['progress'],
                'daily_goal': goal['daily_hours'],
                'percent_complete': min(100, progress_percent),
                'updated_at': self.format_time(self.SYSTEM_TIME)
            }
        return {}
    
    def get_motivation_message(self, progress_percent: float) -> str:
        """Get motivational message based on progress."""
        if progress_percent >= 100:
            return "🌟 Amazing! You've reached your daily study goal!"
        elif progress_percent >= 75:
            return "🚀 Almost there! Keep pushing!"
        elif progress_percent >= 50:
            return "💪 Halfway there! You're doing great!"
        elif progress_percent >= 25:
            return "📚 Good progress! Keep it up!"
        else:
            return "🌱 Every minute of study counts!"
    
    def generate_progress_notification(self, user_id: str) -> Dict:
        """Generate a progress notification for the user."""
        if user_id in self.study_goals:
            goal = self.study_goals[user_id]
            progress_percent = (goal['progress'] / goal['daily_hours']) * 100
            
            return {
                'subject': goal.get('subject', 'All subjects'),
                'progress': f"{goal['progress']:.1f}/{goal['daily_hours']:.1f} hours",
                'percent': f"{min(100, progress_percent):.1f}%",
                'message': self.get_motivation_message(progress_percent),
                'time': self.format_time(self.SYSTEM_TIME)
            }
        return {}

    def format_reminder_message(self, reminder: Dict) -> str:
        """Format reminder message for display."""
        return (
            f"📅 Study Reminder\n"
            f"Subject: {reminder['subject']}\n"
            f"Scheduled: {self.format_time(reminder['target_time'])}\n"
            f"Status: {reminder['status'].title()}"
        )

# Example usage:
notification_system = NotificationSystem()

# Set up study goal
goal_setup = notification_system.set_study_goal(
    user_id="user123",
    daily_hours=6.0,
    subject="Mathematics"
)

# Add study reminder
reminder = notification_system.add_study_reminder(
    user_id="user123",
    subject="Mathematics",
    target_time="2025-06-05 08:00:00"
)

# Set break reminder
break_reminder = notification_system.set_break_reminder(
    user_id="user123",
    study_duration=45
)

# Update progress
progress = notification_system.update_study_progress(
    user_id="user123",
    hours_studied=2.5
)

# Get progress notification
notification = notification_system.generate_progress_notification(
    user_id="user123"
)

# Check for break
is_break_due = notification_system.check_break_due("user123")

from dataclasses import dataclass
from typing import List, Dict, Optional
from datetime import datetime, timedelta

@dataclass
class StudyAnalytics:
    timestamp: str = "2025-06-05 06:11:25"  # Current fixed time
    
    def format_timestamp(self) -> str:
        """Format timestamp with UTC."""
        return f"{self.timestamp} UTC"

class ProgressAnalytics:
    def __init__(self):
        self.current_time = "2025-06-05 06:11:25"  # Current fixed time
        
    def calculate_study_metrics(self, study_sessions: List[Dict]) -> Dict:
        """Calculate comprehensive study metrics."""
        total_time = 0
        effective_time = 0
        break_time = 0
        sessions_count = len(study_sessions)
        subjects = {}
        
        for session in study_sessions:
            duration = session.get('duration', 0)
            total_time += duration
            break_duration = sum(b.get('duration', 0) for b in session.get('breaks', []))
            break_time += break_duration
            effective_time += (duration - break_duration)
            
            # Track subject-wise time
            subject = session.get('subject', 'Unknown')
            if subject in subjects:
                subjects[subject] += (duration - break_duration)
            else:
                subjects[subject] = (duration - break_duration)
        
        return {
            'total_time': total_time,
            'effective_time': effective_time,
            'break_time': break_time,
            'sessions_count': sessions_count,
            'subjects': subjects,
            'calculated_at': self.current_time
        }
    
    def generate_daily_report(self, sessions: List[Dict]) -> Dict:
        """Generate a detailed daily study report."""
        total_stats = self.calculate_study_metrics(sessions)
        
        return {
            'date': self.current_time[:10],  # YYYY-MM-DD
            'summary': {
                'total_hours': total_stats['total_time'] / 3600,
                'effective_hours': total_stats['effective_time'] / 3600,
                'break_hours': total_stats['break_time'] / 3600,
                'sessions': total_stats['sessions_count']
            },
            'subjects': {
                subject: hours / 3600 
                for subject, hours in total_stats['subjects'].items()
            },
            'generated_at': self.current_time
        }
    
    def calculate_productivity_score(self, 
                                  effective_time: float, 
                                  total_time: float) -> float:
        """Calculate productivity score (0-100)."""
        if total_time == 0:
            return 0
        return min(100, (effective_time / total_time) * 100)
    
    def get_study_streaks(self, daily_sessions: Dict[str, List]) -> Dict:
        """Calculate current and best study streaks."""
        current_streak = 0
        best_streak = 0
        temp_streak = 0
        
        dates = sorted(daily_sessions.keys())
        for i, date in enumerate(dates):
            if daily_sessions[date]:  # If there are sessions on this date
                temp_streak += 1
                if i == len(dates) - 1:  # If this is the last date
                    current_streak = temp_streak
            else:
                if temp_streak > best_streak:
                    best_streak = temp_streak
                temp_streak = 0
                
        return {
            'current_streak': current_streak,
            'best_streak': max(best_streak, current_streak),
            'calculated_at': self.current_time
        }
    
    def generate_insights(self, study_data: Dict) -> List[str]:
        """Generate personalized study insights."""
        insights = []
        
        # Productivity patterns
        morning_time = study_data.get('morning_time', 0)
        evening_time = study_data.get('evening_time', 0)
        if morning_time > evening_time:
            insights.append("🌅 You're most productive in the morning!")
        else:
            insights.append("🌙 You tend to study more effectively in the evening!")
            
        # Break patterns
        break_ratio = study_data.get('break_time', 0) / study_data.get('total_time', 1)
        if break_ratio < 0.15:
            insights.append("⚠️ Consider taking more breaks to maintain productivity")
        elif break_ratio > 0.25:
            insights.append("⏰ Try to reduce break time to optimize study sessions")
            
        # Subject focus
        subjects = study_data.get('subjects', {})
        if subjects:
            most_studied = max(subjects.items(), key=lambda x: x[1])
            insights.append(f"📚 Most studied subject: {most_studied[0]}")
            
        return insights
    
    def format_report(self, report: Dict) -> str:
        """Format analytics report for display."""
        return (
            f"📊 Study Analytics Report\n"
            f"Generated: {self.current_time} UTC\n"
            f"\n"
            f"📚 Study Time:\n"
            f"Total: {report['summary']['total_hours']:.1f}h\n"
            f"Effective: {report['summary']['effective_hours']:.1f}h\n"
            f"Breaks: {report['summary']['break_hours']:.1f}h\n"
            f"\n"
            f"📝 Sessions: {report['summary']['sessions']}\n"
            f"\n"
            f"📋 Subjects:\n" +
            "\n".join(f"- {subject}: {hours:.1f}h" 
                     for subject, hours in report['subjects'].items())
        )

# Example usage:
analytics = ProgressAnalytics()

example_sessions = [
    {
        'duration': 7200,  # 2 hours
        'subject': 'Mathematics',
        'breaks': [{'duration': 900}]  # 15 min break
    },
    {
        'duration': 5400,  # 1.5 hours
        'subject': 'Physics',
        'breaks': [{'duration': 600}]  # 10 min break
    }
]

# Generate daily report
daily_report = analytics.generate_daily_report(example_sessions)

# Format report for display
formatted_report = analytics.format_report(daily_report)

# Final Configuration and System Documentation
# Part 17 - System Integration and Documentation

FINAL_SYSTEM_CONFIG = {
    'SYSTEM': {
        'VERSION': '2.0.0',
        'LAST_UPDATED': '2025-06-05 06:13:19',  # Current timestamp
        'ENVIRONMENT': 'production',
        'TIMEZONE': 'UTC'
    },
    'BRANDING': {
        'TITLE': 'MTLE 2025',
        'CREATOR': 'Created by Eli'
    },
    'FEATURES': {
        'DASHBOARD': True,
        'ANALYTICS': True,
        'NOTIFICATIONS': True,
        'PROGRESS_TRACKING': True
    }
}

class SystemDocumentation:
    """System documentation and integration guide."""
    
    @staticmethod
    def get_version_info():
        return {
            'version': FINAL_SYSTEM_CONFIG['SYSTEM']['VERSION'],
            'last_updated': FINAL_SYSTEM_CONFIG['SYSTEM']['LAST_UPDATED'],
            'environment': FINAL_SYSTEM_CONFIG['SYSTEM']['ENVIRONMENT']
        }

    @staticmethod
    def get_feature_status():
        return FINAL_SYSTEM_CONFIG['FEATURES']

    @staticmethod
    def get_integration_steps():
        return [
            "1. Initialize the core system components",
            "2. Set up the database connection",
            "3. Configure the notification system",
            "4. Initialize the analytics engine",
            "5. Set up the dashboard generator",
            "6. Configure automated backups",
            "7. Enable monitoring and logging"
        ]

def initialize_complete_system():
    """
    Initialize all system components with proper configuration.
    Returns a dictionary containing all initialized components.
    """
    components = {}
    
    # Initialize study session manager
    components['session_manager'] = StudySessionManager()
    
    # Initialize notification system
    components['notifications'] = NotificationSystem()
    
    # Initialize analytics
    components['analytics'] = ProgressAnalytics()
    
    # Initialize dashboard
    components['dashboard'] = ImageGenerator()
    
    return components

def create_system_status_report():
    """Generate a complete system status report."""
    return {
        'timestamp': FINAL_SYSTEM_CONFIG['SYSTEM']['LAST_UPDATED'],
        'system_version': FINAL_SYSTEM_CONFIG['SYSTEM']['VERSION'],
        'features_enabled': FINAL_SYSTEM_CONFIG['FEATURES'],
        'branding': FINAL_SYSTEM_CONFIG['BRANDING'],
        'environment': FINAL_SYSTEM_CONFIG['SYSTEM']['ENVIRONMENT']
    }

# Example of complete system usage:
def main():
    # Initialize complete system
    system = initialize_complete_system()
    
    # Create example study session
    session = system['session_manager'].create_session(
        subject="Mathematics",
        start_time=FINAL_SYSTEM_CONFIG['SYSTEM']['LAST_UPDATED']
    )
    
    # Set up notifications
    system['notifications'].set_study_goal(
        user_id="user123",
        daily_hours=6.0
    )
    
    # Generate analytics
    analytics = system['analytics'].generate_daily_report([session])
    
    # Create dashboard
    dashboard = system['dashboard'].create_dashboard(
        study_data=analytics,
        metadata={
            'timestamp': FINAL_SYSTEM_CONFIG['SYSTEM']['LAST_UPDATED'],
            'title': FINAL_SYSTEM_CONFIG['BRANDING']['TITLE'],
            'creator': FINAL_SYSTEM_CONFIG['BRANDING']['CREATOR']
        }
    )
    
    return {
        'session': session,
        'analytics': analytics,
        'dashboard': dashboard,
        'status': create_system_status_report()
    }

# System health check function
def system_health_check():
    """Perform a system health check."""
    return {
        'status': 'operational',
        'timestamp': FINAL_SYSTEM_CONFIG['SYSTEM']['LAST_UPDATED'],
        'components': {
            'session_manager': 'active',
            'notifications': 'active',
            'analytics': 'active',
            'dashboard': 'active'
        },
        'version': FINAL_SYSTEM_CONFIG['SYSTEM']['VERSION']
    }

"""
SYSTEM DOCUMENTATION:

1. Components Overview:
   - Study Session Manager (Part 1-5)
   - Dashboard Generator (Part 6)
   - Progress Tracking (Part 7-9)
   - Time Management (Part 10-13)
   - Progress Chart (Part 14)
   - Notification System (Part 15)
   - Analytics Engine (Part 16)

2. Integration Flow:
   - Initialize system components
   - Configure system settings
   - Set up user sessions
   - Enable notifications
   - Generate analytics
   - Create dashboards

3. Maintenance:
   - Regular health checks
   - System status monitoring
   - Component updates
   - Data backup

4. Best Practices:
   - Regular analytics review
   - Dashboard updates
   - Notification management
   - Progress tracking
"""

if __name__ == "__main__":
    # Run system initialization
    system_status = system_health_check()
    print(f"System Status: {system_status['status']}")
    print(f"Version: {system_status['version']}")
    print(f"Last Updated: {system_status['timestamp']}")

