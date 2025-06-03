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

# Initialize Flask app
app = Flask(__name__)

@app.route('/')
def home():
    return "Study Log Bot is running!", 200

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
SUBJECTS = [
    "CC 🧪", "BACTE 🦠", "VIRO 👾", "MYCO 🍄", "PARA 🪱",
    "CM 🚽💩", "HISTO 🧻🗳️", "MT Laws ⚖️", "HEMA 🩸", "IS ⚛",
    "BB 🩹", "MolBio 🧬", "RECALLS 🤔💭", "General Books 📚"
]

user_sessions = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send main menu as new message"""
    keyboard = [[InlineKeyboardButton("Start Studying", callback_data="start_studying")]]
    await update.message.reply_text(
        "MAIN MENU BUTTON",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all button clicks"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "start_studying":
        await show_subjects(query)
    elif query.data == "new_session":
        await start(update, context)  # Trigger /start automatically
        return
    elif query.data.startswith("subject_"):
        subject_index = int(query.data.split("_")[1])
        await start_study_session(query, SUBJECTS[subject_index])
    elif query.data == "start_break":
        await start_break(query)
    elif query.data == "end_break":
        await end_break(query)
    elif query.data == "end_session":
        await end_study_session(query)

async def show_subjects(query) -> None:
    """Show subjects as new message"""
    keyboard = []
    for i, subject in enumerate(SUBJECTS):
        keyboard.append([InlineKeyboardButton(subject, callback_data=f"subject_{i}")])
    
    await query.message.reply_text(
        "What subject?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def start_study_session(query, subject) -> None:
    """Start session with new message"""
    user_name = query.from_user.first_name
    
    user_sessions[query.from_user.id] = {
        "subject": subject,
        "user_name": user_name,
        "on_break": False
    }
    
    keyboard = [
        [InlineKeyboardButton("START BREAK", callback_data="start_break")],
        [InlineKeyboardButton("END STUDY SESSION", callback_data="end_session")]
    ]
    
    await query.message.reply_text(
        f"{user_name} started studying {subject}.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def start_break(query) -> None:
    """Start break with new message"""
    user_id = query.from_user.id
    if user_id not in user_sessions:
        await query.message.reply_text("No active study session found.")
        return
    
    user_name = user_sessions[user_id]["user_name"]
    user_sessions[user_id]["on_break"] = True
    
    keyboard = [
        [InlineKeyboardButton("END BREAK", callback_data="end_break")],
        [InlineKeyboardButton("END STUDY SESSION", callback_data="end_session")]
    ]
    
    await query.message.reply_text(
        f"{user_name} started a break. Break responsibly, {user_name}!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def end_break(query) -> None:
    """End break with new message"""
    user_id = query.from_user.id
    if user_id not in user_sessions:
        await query.message.reply_text("No active study session found.")
        return
    
    user_name = user_sessions[user_id]["user_name"]
    subject = user_sessions[user_id]["subject"]
    user_sessions[user_id]["on_break"] = False
    
    keyboard = [
        [InlineKeyboardButton("START BREAK", callback_data="start_break")],
        [InlineKeyboardButton("END STUDY SESSION", callback_data="end_session")]
    ]
    
    await query.message.reply_text(
        f"{user_name} ended their break and resumed studying {subject}.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def end_study_session(query) -> None:
    """End session with new message and updated button"""
    user_id = query.from_user.id
    if user_id not in user_sessions:
        await query.message.reply_text("No active study session found.")
        return
    
    user_name = user_sessions[user_id]["user_name"]
    subject = user_sessions[user_id]["subject"]
    del user_sessions[user_id]
    
    keyboard = [[InlineKeyboardButton("START A NEW SESSION", callback_data="new_session")]]
    
    await query.message.reply_text(
        f"{user_name} ended their review on {subject}. Congrats {user_name}!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def main() -> None:
    """Start the bot"""
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(handle_button_click))

    if os.getenv('RENDER'):
        from threading import Thread
        Thread(target=app.run, kwargs={'host': '0.0.0.0', 'port': 10000}).start()
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
