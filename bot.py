import os
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)

# Initialize Flask app (required for Render web service)
app = Flask(__name__)

@app.route('/')
def home():
    return "Study Log Bot is running!", 200

# Bot Token from environment variable
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

# Subjects list
SUBJECTS = [
    "CC 🧪", "BACTE 🦠", "VIRO 👾", "MYCO 🍄", "PARA 🪱",
    "CM 🚽💩", "HISTO 🧻🗳️", "MT Laws ⚖️", "HEMA 🩸", "IS ⚛",
    "BB 🩹", "MolBio 🧬", "RECALLS 🤔💭", "General Books 📚"
]

# User study sessions storage
user_sessions = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send main menu when the command /start is issued."""
    # Verify it's being used in a group topic
    if not update.message or not update.message.chat.type in ["group", "supergroup"]:
        await update.message.reply_text("❌ Please use this command in a group topic!")
        return

    keyboard = [
        [InlineKeyboardButton("Start Studying", callback_data="start_studying")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "MAIN MENU BUTTON",
        reply_markup=reply_markup
    )

async def handle_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle button clicks."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "start_studying":
        await show_subjects(query)
    elif data.startswith("subject_"):
        subject_index = int(data.split("_")[1])
        subject = SUBJECTS[subject_index]
        await start_study_session(query, subject)
    elif data == "start_break":
        await start_break(query)
    elif data == "end_break":
        await end_break(query)
    elif data == "end_session":
        await end_study_session(query)

async def show_subjects(query) -> None:
    """Show list of subjects to choose from."""
    keyboard = []
    for i, subject in enumerate(SUBJECTS):
        keyboard.append([InlineKeyboardButton(subject, callback_data=f"subject_{i}")])
    
    await query.edit_message_text(
        text="What subject?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def start_study_session(query, subject) -> None:
    """Start a new study session with proper topic detection."""
    try:
        # Modern topic detection (Telegram API 5.0+)
        if hasattr(query.message, 'message_thread') and query.message.message_thread:
            topic_name = query.message.message_thread.name
        # Legacy topic detection
        elif query.message.reply_to_message and hasattr(query.message.reply_to_message, 'forum_topic_created'):
            topic_name = query.message.reply_to_message.forum_topic_created.name
        else:
            topic_name = "General"  # Fallback name
    except Exception as e:
        print(f"Topic detection error: {e}")
        topic_name = "Review Session"  # Default name

    user_sessions[query.from_user.id] = {
        "subject": subject,
        "topic_name": topic_name,
        "on_break": False
    }
    
    keyboard = [
        [
            InlineKeyboardButton("START BREAK", callback_data="start_break"),
            InlineKeyboardButton("END STUDY SESSION", callback_data="end_session")
        ]
    ]
    
    await query.edit_message_text(
        text=f"[{topic_name}] started studying [{subject}].",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def start_break(query) -> None:
    """Start a break during study session."""
    user_id = query.from_user.id
    if user_id not in user_sessions:
        await query.edit_message_text(text="No active study session found.")
        return
    
    user_sessions[user_id]["on_break"] = True
    topic_name = user_sessions[user_id]["topic_name"]
    
    keyboard = [
        [
            InlineKeyboardButton("END BREAK", callback_data="end_break"),
            InlineKeyboardButton("END STUDY SESSION", callback_data="end_session")
        ]
    ]
    
    await query.edit_message_text(
        text=f"[{topic_name}] started a break. Break Responsibly, [{topic_name}]!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def end_break(query) -> None:
    """End the break and resume studying."""
    user_id = query.from_user.id
    if user_id not in user_sessions:
        await query.edit_message_text(text="No active study session found.")
        return
    
    user_sessions[user_id]["on_break"] = False
    topic_name = user_sessions[user_id]["topic_name"]
    subject = user_sessions[user_id]["subject"]
    
    keyboard = [
        [
            InlineKeyboardButton("START BREAK", callback_data="start_break"),
            InlineKeyboardButton("END STUDY SESSION", callback_data="end_session")
        ]
    ]
    
    await query.edit_message_text(
        text=f"[{topic_name}] ended their break and started studying.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def end_study_session(query) -> None:
    """End the current study session."""
    user_id = query.from_user.id
    if user_id not in user_sessions:
        await query.edit_message_text(text="No active study session found.")
        return
    
    topic_name = user_sessions[user_id]["topic_name"]
    subject = user_sessions[user_id]["subject"]
    del user_sessions[user_id]
    
    keyboard = [
        [InlineKeyboardButton("Start Studying", callback_data="start_studying")]
    ]
    
    await query.edit_message_text(
        text=f"[{topic_name}] ended their review on [{subject}]. Congrats [{topic_name}]. If you want to start a study session again, just click the button below",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def main() -> None:
    """Start the bot and web server."""
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(handle_button_click))

    # Run Flask server in a thread if on Render
    if os.getenv('RENDER'):
        from threading import Thread
        Thread(target=app.run, kwargs={'host': '0.0.0.0', 'port': 10000}).start()
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
