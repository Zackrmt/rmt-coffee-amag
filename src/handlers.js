const { mainMenuButtons, subjectButtons, studySessionButtons, breakButtons } = require('./buttons');
const { ACTIONS } = require('./constants');
const quiz = require('./quiz');

class SessionManager {
    constructor() {
        this.activeSessions = new Map();
    }

    startSession(userId, subject) {
        this.activeSessions.set(userId, { subject, status: 'studying' });
    }

    endSession(userId) {
        this.activeSessions.delete(userId);
    }

    getSession(userId) {
        return this.activeSessions.get(userId);
    }

    updateSessionStatus(userId, status) {
        const session = this.activeSessions.get(userId);
        if (session) {
            session.status = status;
            this.activeSessions.set(userId, session);
        }
    }
}

const sessionManager = new SessionManager();

async function handleStart(msg, bot) {
    const chatId = msg.chat.id;
    await bot.sendMessage(chatId, 'Welcome to Study Logger Bot!', mainMenuButtons);
}

async function handleCallback(callbackQuery, bot) {
    const msg = callbackQuery.message;
    const data = callbackQuery.data;
    const userId = callbackQuery.from.id;
    const username = callbackQuery.from.username || callbackQuery.from.first_name;

    if (data.startsWith('answer:')) {
        await quiz.handleAnswer(callbackQuery, bot);
        return;
    }

    if (data.startsWith('done:')) {
        // Delete the explanation message and show the question again
        await bot.deleteMessage(msg.chat.id, msg.message_id);
        const questionId = data.split(':')[1];
        const question = quiz.questions.get(questionId);
        if (question) {
            const quizMessage = quiz.createQuizMessage(question);
            const keyboard = quiz.createAnswerKeyboard(questionId);
            await bot.sendMessage(msg.chat.id, quizMessage, {
                reply_markup: keyboard,
                parse_mode: 'HTML'
            });
        }
        return;
    }

    // Try to delete the previous message to keep chat clean
    try {
        await bot.deleteMessage(msg.chat.id, msg.message_id);
    } catch (error) {
        console.error('Error deleting message:', error);
    }

    switch (data) {
        case ACTIONS.START_STUDYING:
            await bot.sendMessage(msg.chat.id, 'What subject?', subjectButtons);
            break;

        case ACTIONS.START_BREAK:
            sessionManager.updateSessionStatus(userId, 'break');
            await bot.sendMessage(
                msg.chat.id,
                `${username} started a break. Break Responsibly, ${username}!`,
                breakButtons
            );
            break;

        case ACTIONS.END_BREAK:
            sessionManager.updateSessionStatus(userId, 'studying');
            await bot.sendMessage(
                msg.chat.id,
                `${username} ended their break and started studying.`,
                studySessionButtons
            );
            break;

        case ACTIONS.END_SESSION:
            const session = sessionManager.getSession(userId);
            if (session) {
                await bot.sendMessage(
                    msg.chat.id,
                    `${username} ended their review on ${session.subject}. Congrats ${username}. If you want to start a study session again, just click the button below`,
                    mainMenuButtons
                );
                sessionManager.endSession(userId);
            }
            break;

        case ACTIONS.CREATE_QUESTION:
            quiz.startQuestionCreation(userId);
            await bot.sendMessage(msg.chat.id, 'Please enter your question:');
            break;

        default:
            if (data.startsWith(`${ACTIONS.SELECT_SUBJECT}:`)) {
                const subject = data.split(':')[1];
                sessionManager.startSession(userId, subject);
                await bot.sendMessage(
                    msg.chat.id,
                    `${username} started studying ${subject}.`,
                    studySessionButtons
                );
            }
    }
}

async function handleMessage(msg, bot) {
    if (await quiz.handleQuestionCreation(msg, bot)) {
        // Try to delete the user's message to keep the quiz creation private
        try {
            await bot.deleteMessage(msg.chat.id, msg.message_id);
        } catch (error) {
            console.error('Error deleting message:', error);
        }
    }
}

module.exports = {
    handleStart,
    handleCallback,
    handleMessage
};
