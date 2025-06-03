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

async def delete_previous_message(update):
    """Delete the previous message"""
    if hasattr(update, 'callback_query') and update.callback_query.message:
        try:
            await update.callback_query.message.delete()
        except:
            pass

async def remove_buttons_only(message):
    """Remove buttons but keep the message text"""
    try:
        await message.edit_reply_markup(reply_markup=None)
    except:
        pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send main menu (will be deleted after clicking START STUDYING)"""
    keyboard = [[InlineKeyboardButton("Start Studying", callback_data="start_studying")]]
    message = await update.message.reply_text(
        "MAIN MENU BUTTON",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    context.user_data['last_menu_message'] = message.message_id

async def handle_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all button clicks with proper message deletion"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "start_studying":
        # Delete MAIN MENU BUTTON
        if 'last_menu_message' in context.user_data:
            try:
                await context.bot.delete_message(
                    chat_id=query.message.chat_id,
                    message_id=context.user_data['last_menu_message']
                )
            except:
                pass
        await show_subjects(query, context)
        
    elif query.data.startswith("subject_"):
        # Delete "What subject?" message
        await delete_previous_message(query)
        subject_index = int(query.data.split("_")[1])
        await start_study_session(query, context, SUBJECTS[subject_index])
        
    elif query.data == "start_break":
        await remove_buttons_only(query.message)
        await start_break(query, context)
        
    elif query.data == "end_break":
        await remove_buttons_only(query.message)
        await end_break(query, context)
        
    elif query.data == "end_session":
        await remove_buttons_only(query.message)
        await end_study_session(query, context)

async def show_subjects(query, context) -> None:
    """Show subjects (will be deleted after selection)"""
    keyboard = []
    half = len(SUBJECTS) // 2
    for i in range(half):
        keyboard.append([
            InlineKeyboardButton(SUBJECTS[i], callback_data=f"subject_{i}"),
            InlineKeyboardButton(SUBJECTS[i+half], callback_data=f"subject_{i+half}")
        ])
    if len(SUBJECTS) % 2 != 0:
        keyboard.append([InlineKeyboardButton(SUBJECTS[-1], callback_data=f"subject_{len(SUBJECTS)-1}")])
    
    message = await query.message.reply_text(
        "What subject?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    context.user_data['last_menu_message'] = message.message_id

async def start_study_session(query, context, subject) -> None:
    """Start session (KEEP MESSAGE, buttons stay until clicked)"""
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

async def start_break(query, context) -> None:
    """Start break (KEEP MESSAGE, buttons stay until clicked)"""
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

async def end_break(query, context) -> None:
    """End break (KEEP MESSAGE, buttons stay until clicked)"""
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

async def end_study_session(query, context) -> None:
    """End session (KEEP MESSAGE, buttons stay until clicked)"""
    user_id = query.from_user.id
    if user_id not in user_sessions:
        await query.message.reply_text("No active study session found.")
        return
    
    user_name = user_sessions[user_id]["user_name"]
    subject = user_sessions[user_id]["subject"]
    del user_sessions[user_id]
    
    keyboard = [[InlineKeyboardButton("Start New Session", callback_data="start_studying")]]
    
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
