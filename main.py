import os
import logging
from flask import Flask, request
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
)
import asyncio
from collections import defaultdict

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
WEBHOOK_URL = os.environ["WEBHOOK_URL"]

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# In-memory storage (for demo, swap with DB for production)
user_sessions = defaultdict(dict)
question_sessions = defaultdict(dict)
question_id_counter = [1]

SUBJECTS = [
    ("CC 🧪", "cc"),
    ("BACTE 🦠", "bacte"),
    ("VIRO 👾", "viro"),
    ("MYCO 🍄", "myco"),
    ("PARA 🪱", "para"),
    ("CM 🚽💩", "cm"),
    ("HISTO 🧻🗳️", "histo"),
    ("MT Laws ⚖️", "mtlaws"),
    ("HEMA 🩸", "hema"),
    ("IS ⚛", "is"),
    ("BB 🩹", "bb"),
    ("MolBio 🧬", "molbio"),
    ("Autopsy ☠", "autopsy"),
    ("General Books 📚", "genbooks"),
    ("RECALLS 🤔💭", "recalls"),
]

def main_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Start Studying", callback_data="start_studying"),
            InlineKeyboardButton("Start Creating Questions", callback_data="create_questions"),
        ]
    ])

def subjects_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(text, callback_data=f"subject_{key}")]
        for text, key in SUBJECTS
    ])

def studying_buttons():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("START BREAK", callback_data="start_break"),
            InlineKeyboardButton("END STUDY SESSION", callback_data="end_study"),
        ]
    ])

def break_buttons():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("END BREAK", callback_data="end_break"),
            InlineKeyboardButton("END STUDY SESSION", callback_data="end_study"),
        ]
    ])

def done_reading_button():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Done Reading", callback_data="done_reading")]
    ])

def question_choices_keyboard(choices, qid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(choice, callback_data=f"answer_{qid}_{idx}")]
        for idx, choice in enumerate(choices)
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_sessions[update.effective_user.id].clear()
    msg = await update.effective_message.reply_text(
        "MAIN MENU", reply_markup=main_menu()
    )
    user_sessions[update.effective_user.id]['main_menu_msg'] = msg.message_id

async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    # Delete MAIN MENU BUTTON message
    if 'main_menu_msg' in user_sessions[user_id]:
        try:
            await context.bot.delete_message(chat_id=query.message.chat_id, message_id=user_sessions[user_id]['main_menu_msg'])
        except Exception:
            pass
        del user_sessions[user_id]['main_menu_msg']

    if query.data == "start_studying":
        msg = await query.message.reply_text(
            "What subject?", reply_markup=subjects_menu()
        )
        user_sessions[user_id]['state'] = 'choosing_subject'
        user_sessions[user_id]['subjects_menu_msg'] = msg.message_id
    elif query.data == "create_questions":
        # Start Q&A creation flow
        user_sessions[user_id]['state'] = 'creating_question'
        user_sessions[user_id]['question_step'] = 'ask_text'
        user_sessions[user_id]['question_data'] = {}
        msg = await query.message.reply_text("Please type your question:")
        user_sessions[user_id]['question_msg_ids'] = [msg.message_id]

async def handle_subject_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    # Delete subject menu
    if 'subjects_menu_msg' in user_sessions[user_id]:
        try:
            await context.bot.delete_message(chat_id=query.message.chat_id, message_id=user_sessions[user_id]['subjects_menu_msg'])
        except Exception:
            pass
        del user_sessions[user_id]['subjects_menu_msg']

    subject_key = query.data.replace("subject_", "")
    subject_name = next(t for t, k in SUBJECTS if k == subject_key)
    user_sessions[user_id]['subject'] = subject_name
    user_sessions[user_id]['state'] = 'studying'

    msg = await query.message.reply_text(
        f"{query.from_user.first_name} started studying {subject_name}.",
        reply_markup=studying_buttons()
    )
    user_sessions[user_id]['current_study_msg'] = msg.message_id

async def handle_studying_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    state = user_sessions[user_id].get('state')
    subject = user_sessions[user_id].get('subject', 'Subject')

    # Remove previous message's buttons
    try:
        await context.bot.edit_message_reply_markup(
            chat_id=query.message.chat_id, message_id=query.message.message_id, reply_markup=None)
    except Exception:
        pass

    if query.data == "start_break":
        user_sessions[user_id]['state'] = 'on_break'
        msg = await query.message.reply_text(
            f"{query.from_user.first_name} started a break. Break Responsibly, {query.from_user.first_name}!",
            reply_markup=break_buttons()
        )
        user_sessions[user_id]['current_study_msg'] = msg.message_id
    elif query.data == "end_break":
        user_sessions[user_id]['state'] = 'studying'
        msg = await query.message.reply_text(
            f"{query.from_user.first_name} ended their break and started studying.",
            reply_markup=studying_buttons()
        )
        user_sessions[user_id]['current_study_msg'] = msg.message_id
    elif query.data == "end_study":
        user_sessions[user_id]['state'] = None
        msg = await query.message.reply_text(
            f"{query.from_user.first_name} ended their review on {subject}. Congrats {query.from_user.first_name}. "
            "If you want to start a study session again, just click the button below",
            reply_markup=main_menu()
        )
        user_sessions[user_id]['main_menu_msg'] = msg.message_id
        user_sessions[user_id].pop('subject', None)

async def handle_create_question_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    step = user_sessions[user_id].get('question_step')
    qdata = user_sessions[user_id].get('question_data', {})
    message = update.effective_message

    # Clean up previous bot/user messages in creation flow
    for msg_id in user_sessions[user_id].get('question_msg_ids', []):
        try:
            await context.bot.delete_message(chat_id=message.chat_id, message_id=msg_id)
        except Exception:
            pass
    user_sessions[user_id]['question_msg_ids'] = []

    if step == 'ask_text':
        qdata['text'] = message.text
        user_sessions[user_id]['question_step'] = 'ask_choices'
        msg = await message.reply_text("Type the choices separated by ';' (e.g. a) Choice1; b) Choice2; c) Choice3 ...):")
        user_sessions[user_id]['question_msg_ids'].append(msg.message_id)
    elif step == 'ask_choices':
        # Parse choices
        choices = [c.strip() for c in message.text.split(';') if c.strip()]
        qdata['choices'] = choices
        user_sessions[user_id]['question_step'] = 'ask_correct'
        msg = await message.reply_text("Which letter is the correct answer? (a, b, c, d, e):")
        user_sessions[user_id]['question_msg_ids'].append(msg.message_id)
    elif step == 'ask_correct':
        correct = message.text.strip().lower()
        idx = ord(correct) - ord('a')
        if idx < 0 or idx >= len(qdata['choices']):
            msg = await message.reply_text("Invalid choice. Please enter a valid letter (a, b, c, d, e):")
            user_sessions[user_id]['question_msg_ids'].append(msg.message_id)
            return
        qdata['correct'] = idx
        user_sessions[user_id]['question_step'] = 'ask_explanation'
        msg = await message.reply_text("Please explain why it's the correct answer:")
        user_sessions[user_id]['question_msg_ids'].append(msg.message_id)
    elif step == 'ask_explanation':
        qdata['explanation'] = message.text
        # Store the question
        chat_id = message.chat_id
        qid = question_id_counter[0]
        question_id_counter[0] += 1
        question_sessions[chat_id][qid] = {
            'creator': update.effective_user.first_name,
            'text': qdata['text'],
            'choices': qdata['choices'],
            'correct': qdata['correct'],
            'explanation': qdata['explanation'],
        }
        # Delete all creation messages
        for mid in user_sessions[user_id]['question_msg_ids']:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=mid)
            except Exception:
                pass

        await message.reply_text("Question created! Posting to the group…")
        await post_question(context, chat_id, qid)
        user_sessions[user_id]['state'] = None
        user_sessions[user_id]['question_step'] = None
        user_sessions[user_id]['question_data'] = {}
        user_sessions[user_id]['question_msg_ids'] = []

async def post_question(context, chat_id, qid):
    q = question_sessions[chat_id][qid]
    choices_text = '\n'.join([f"{chr(ord('a')+i)}) {c}" for i, c in enumerate(q['choices'])])
    message_text = (
        f"{q['text']}\n\n{choices_text}\n\n"
        f"Question created by {q['creator']}"
    )
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=message_text,
        reply_markup=question_choices_keyboard(q['choices'], qid)
    )
    # Store the question message id for later edits
    q['message_id'] = msg.message_id

async def handle_question_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    data = query.data  # e.g., answer_1_0
    _, qid, ans_idx = data.split("_")
    qid, ans_idx = int(qid), int(ans_idx)
    q = question_sessions[chat_id][qid]
    is_correct = ans_idx == q['correct']
    correct_letter = chr(ord('a') + q['correct'])
    if is_correct:
        reply = f"✅ Correct! Well done, {query.from_user.first_name}."
    else:
        reply = (f"❌ Wrong! The correct answer was {correct_letter}) {q['choices'][q['correct']]}.\n"
                 f"Try again!")

    # Remove buttons
    try:
        await context.bot.edit_message_reply_markup(chat_id=chat_id, message_id=query.message.message_id, reply_markup=None)
    except Exception:
        pass

    # Send result message
    msg = await query.message.reply_text(reply)
    # After 5s, show explanation and a "Done Reading" button
    await context.application.create_task(
        show_explanation(context, chat_id, qid, msg.message_id)
    )

async def show_explanation(context, chat_id, qid, reply_msg_id):
    import asyncio
    await asyncio.sleep(5)
    q = question_sessions[chat_id][qid]
    await context.bot.send_message(
        chat_id=chat_id, 
        text=f"Explanation: {q['explanation']}",
        reply_markup=done_reading_button()
    )

async def handle_done_reading(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    # Reshow the question (so others can answer, and answers are not visible)
    for qid, q in question_sessions[chat_id].items():
        if 'message_id' in q:
            await post_question(context, chat_id, qid)
            break
    # Remove the done reading button
    try:
        await context.bot.edit_message_reply_markup(chat_id=chat_id, message_id=query.message.message_id, reply_markup=None)
    except Exception:
        pass

async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = user_sessions[user_id].get('state')
    if state == 'creating_question':
        await handle_create_question_flow(update, context)

def setup_bot():
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler('start', start))
    application.add_handler(CallbackQueryHandler(handle_menu, pattern="^(start_studying|create_questions)$"))
    application.add_handler(CallbackQueryHandler(handle_subject_choice, pattern="^subject_"))
    application.add_handler(CallbackQueryHandler(handle_studying_buttons, pattern="^(start_break|end_break|end_study)$"))
    application.add_handler(CallbackQueryHandler(handle_question_answer, pattern="^answer_"))
    application.add_handler(CallbackQueryHandler(handle_done_reading, pattern="^done_reading$"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_router))
    return application

telegram_app = setup_bot()

@app.route(f"/webhook/{TOKEN}", methods=["POST"])
async def webhook():
    update = Update.de_json(request.get_json(force=True), telegram_app.bot)
    await telegram_app.process_update(update)
    return "ok"

if __name__ == "__main__":
    # Set the webhook before starting Flask
    asyncio.run(telegram_app.bot.set_webhook(f"{WEBHOOK_URL}/webhook/{TOKEN}"))
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
