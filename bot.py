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

async def delete_entire_message(update):
    """Delete the entire message including buttons"""
    try:
        if hasattr(update, 'callback_query') and update.callback_query.message:
            await update.callback_query.message.delete()
        elif hasattr(update, 'message') and update.message:
            await update.message.delete()
    except Exception as e:
        print(f"Error deleting message: {e}")

async def remove_buttons_only(update):
    """Remove buttons but keep the message text"""
    try:
        if hasattr(update, 'callback_query') and update.callback_query.message:
            await update.callback_query.message.edit_reply_markup(reply_markup=None)
    except Exception as e:
        print(f"Error removing buttons: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send main menu (will be completely deleted after selection)"""
    keyboard = [[InlineKeyboardButton("Start Studying", callback_data="start_studying")]]
    sent_msg = await update.message.reply_text(
        "MAIN MENU BUTTON",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    context.user_data['menu_message_id'] = sent_msg.message_id

async def handle_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all button clicks"""
    query = update.callback_query
    await query.answer()
    
    # Delete previous MAIN MENU or SUBJECT SELECTION messages
    if query.data == "start_studying" or query.data.startswith("subject_"):
        await delete_entire_message(query)
    
    if query.data == "start_studying":
        await show_subjects(query, context)
    elif query.data.startswith("subject_"):
        subject_index = int(query.data.split("_")[1])
        await start_study_session(query, context, SUBJECTS[subject_index])
    elif query.data == "start_break":
        await start_break(query, context)
    elif query.data == "end_break":
        await end_break(query, context)
    elif query.data == "end_session":
        await end_study_session(query, context)

async def show_subjects(query, context) -> None:
    """Show subjects (will be completely deleted after selection)"""
    keyboard = []
    half = len(SUBJECTS) // 2
    for i in range(half):
        keyboard.append([
            InlineKeyboardButton(SUBJECTS[i], callback_data=f"subject_{i}"),
            InlineKeyboardButton(SUBJECTS[i+half], callback_data=f"subject_{i+half}")
        ])
    if len(SUBJECTS) % 2 != 0:
        keyboard.append([InlineKeyboardButton(SUBJECTS[-1], callback_data=f"subject_{len(SUBJECTS)-1}")])
    
    sent_msg = await query.message.reply_text(
        "What subject?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    context.user_data['subject_message_id'] = sent_msg.message_id

async def start_study_session(query, context, subject) -> None:
    """Start session (KEEP MESSAGE, REMOVE BUTTONS AFTER CLICK)"""
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
    
    sent_message = await query.message.reply_text(
        f"{user_name} started studying {subject}.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    context.user_data['last_study_message'] = sent_message.message_id

async def start_break(query, context) -> None:
    """Start break (KEEP MESSAGE, REMOVE BUTTONS AFTER CLICK)"""
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
    
    sent_message = await query.message.reply_text(
        f"{user_name} started a break. Break responsibly, {user_name}!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    context.user_data['last_break_message'] = sent_message.message_id
    await remove_buttons_only({'callback_query': query})

async def end_break(query, context) -> None:
    """End break (KEEP MESSAGE, REMOVE BUTTONS AFTER CLICK)"""
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
    
    sent_message = await query.message.reply_text(
        f"{user_name} ended their break and resumed studying {subject}.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    context.user_data['last_resume_message'] = sent_message.message_id
    await remove_buttons_only({'callback_query': query})

async def end_study_session(query, context) -> None:
    """End session (KEEP MESSAGE, REMOVE BUTTONS AFTER CLICK)"""
    user_id = query.from_user.id
    if user_id not in user_sessions:
        await query.message.reply_text("No active study session found.")
        return
    
    user_name = user_sessions[user_id]["user_name"]
    subject = user_sessions[user_id]["subject"]
    del user_sessions[user_id]
    
    keyboard = [[InlineKeyboardButton("Start New Session", callback_data="start_studying")]]
    
    sent_message = await query.message.reply_text(
        f"{user_name} ended their review on {subject}. Congrats {user_name}!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    context.user_data['last_end_message'] = sent_message.message_id
    await remove_buttons_only({'callback_query': query})

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
