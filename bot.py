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

app = Flask(__name__)

@app.route('/')
def home():
    return "Study Log Bot is running!", 200

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
SUBJECTS = [
    "CC 🧪", "BACTE 🦠", "VIRO 👾", "MYCO 🍄", "PARA 🪱",
    "CM 🚽💩", "HISTO 🧻🗳️", "MT Laws ⚖️", "HEMA 🩸", "IS ⚛",
    "BB 🩹", "MolBio 🧬", "RECALLS 🤔💭", "General Books 📚",
    "Autopsy ☠"
]

user_sessions = {}

async def remove_message(update):
    """Delete the message that contained buttons"""
    try:
        if hasattr(update, 'callback_query') and update.callback_query.message:
            await update.callback_query.message.delete()
    except Exception as e:
        print(f"Error deleting message: {e}")

async def send_persistent_message(text):
    """Send a message that will stay without buttons"""
    # This is a placeholder - actual implementation is in the handlers
    pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send main menu (will be deleted after selection)"""
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
    """Show subjects (will be deleted after selection)"""
    await remove_message(query)
    
    keyboard = []
    half = len(SUBJECTS) // 2
    for i in range(half):
        keyboard.append([
            InlineKeyboardButton(SUBJECTS[i], callback_data=f"subject_{i}"),
            InlineKeyboardButton(SUBJECTS[i+half], callback_data=f"subject_{i+half}")
        ])
    if len(SUBJECTS) % 2 != 0:
        keyboard.append([InlineKeyboardButton(SUBJECTS[-1], callback_data=f"subject_{len(SUBJECTS)-1}")])
    
    await query.message.reply_text(
        "What subject?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def start_study_session(query, subject) -> None:
    """Start session (message stays, buttons removed)"""
    await remove_message(query)
    
    user_name = query.from_user.first_name
    user_sessions[query.from_user.id] = {
        "subject": subject,
        "user_name": user_name,
        "on_break": False
    }
    
    # Message stays, no buttons
    await query.message.reply_text(f"{user_name} started studying {subject}.")

async def start_break(query) -> None:
    """Start break (message stays, buttons removed)"""
    await remove_message(query)
    
    user_id = query.from_user.id
    if user_id not in user_sessions:
        await query.message.reply_text("No active study session found.")
        return
    
    user_name = user_sessions[user_id]["user_name"]
    user_sessions[user_id]["on_break"] = True
    
    # Message stays, no buttons
    await query.message.reply_text(f"{user_name} started a break.")

async def end_break(query) -> None:
    """End break (message stays, buttons removed)"""
    await remove_message(query)
    
    user_id = query.from_user.id
    if user_id not in user_sessions:
        await query.message.reply_text("No active study session found.")
        return
    
    user_name = user_sessions[user_id]["user_name"]
    subject = user_sessions[user_id]["subject"]
    user_sessions[user_id]["on_break"] = False
    
    # Message stays, no buttons
    await query.message.reply_text(f"{user_name} ended their break and resumed studying {subject}.")

async def end_study_session(query) -> None:
    """End session (message stays, buttons removed)"""
    await remove_message(query)
    
    user_id = query.from_user.id
    if user_id not in user_sessions:
        await query.message.reply_text("No active study session found.")
        return
    
    user_name = user_sessions[user_id]["user_name"]
    subject = user_sessions[user_id]["subject"]
    del user_sessions[user_id]
    
    # Message stays, no buttons
    await query.message.reply_text(f"{user_name} ended their review on {subject}. Congrats {user_name}!")
    
    # Return to main menu
    keyboard = [[InlineKeyboardButton("Start Studying", callback_data="start_studying")]]
    await query.message.reply_text(
        "MAIN MENU BUTTON",
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
