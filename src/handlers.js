const { mainMenuButtons, subjectButtons, studySessionButtons, breakButtons, questionCreationCancelButton } = require('./buttons');
const { ACTIONS } = require('./constants');
const quiz = require('./quiz');

class SessionManager {
    constructor() {
        this.activeSessions = new Map();
        this.lastMenuMessage = null;
        this.lastSubjectMessage = null;
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
    const messageThreadId = msg.message_thread_id;
    
    // Only respond if message is in a topic or is a private chat
    if (!messageThreadId && msg.chat.type !== 'private') {
        return;
    }
    
    const messageOptions = {
        ...mainMenuButtons
    };
    
    if (messageThreadId) {
        messageOptions.message_thread_id = messageThreadId;
    }

    const message = await bot.sendMessage(chatId, 'Welcome to Study Logger Bot!', messageOptions);
    
    sessionManager.lastMenuMessage = {
        chatId,
        messageId: message.message_id,
        messageThreadId
    };
}

async function handleCallback(callbackQuery, bot) {
    const msg = callbackQuery.message;
    const data = callbackQuery.data;
    const userId = callbackQuery.from.id;
    const userName = callbackQuery.from.first_name || `User${userId}`;
    const messageThreadId = msg.message_thread_id;

    const createMessageOptions = (baseOptions = {}) => {
        return messageThreadId ? { ...baseOptions, message_thread_id: messageThreadId } : baseOptions;
    };

    if (data.startsWith('answer:')) {
        await quiz.handleAnswer(callbackQuery, bot);
        return;
    }

    if (data.startsWith('delete_question:')) {
        const questionId = data.split(':')[1];
        await quiz.deleteQuestion(questionId, userId, msg.chat.id, bot, messageThreadId);
        try {
            await bot.deleteMessage(msg.chat.id, msg.message_id);
        } catch (error) {
            console.error('Error deleting message:', error);
        }
        return;
    }

    if (data.startsWith('done:')) {
        await bot.deleteMessage(msg.chat.id, msg.message_id);
        const questionId = data.split(':')[1];
        const question = quiz.questions.get(questionId);
        if (question) {
            const quizMessage = quiz.createQuizMessage(question);
            const keyboard = quiz.createAnswerKeyboard(questionId, question.creatorId);
            await bot.sendMessage(msg.chat.id, quizMessage, createMessageOptions({
                reply_markup: keyboard,
                parse_mode: 'HTML'
            }));
        }
        return;
    }

    switch (data) {
        case ACTIONS.START_STUDYING:
            if (sessionManager.lastMenuMessage) {
                try {
                    await bot.deleteMessage(
                        sessionManager.lastMenuMessage.chatId,
                        sessionManager.lastMenuMessage.messageId
                    );
                } catch (error) {
                    console.error('Error deleting menu message:', error);
                }
            }
            
            const subjectMessage = await bot.sendMessage(
                msg.chat.id, 
                'What subject?', 
                createMessageOptions(subjectButtons)
            );
            
            sessionManager.lastSubjectMessage = {
                chatId: msg.chat.id,
                messageId: subjectMessage.message_id,
                messageThreadId
            };
            break;

        case ACTIONS.START_BREAK:
            await bot.editMessageReplyMarkup(
                { inline_keyboard: [] },
                {
                    chat_id: msg.chat.id,
                    message_id: msg.message_id,
                    message_thread_id: messageThreadId
                }
            );
            
            sessionManager.updateSessionStatus(userId, 'break');
            await bot.sendMessage(
                msg.chat.id,
                `${userName} started a break. Break Responsibly, ${userName}!`,
                createMessageOptions(breakButtons)
            );
            break;

        case ACTIONS.END_BREAK:
            await bot.editMessageReplyMarkup(
                { inline_keyboard: [] },
                {
                    chat_id: msg.chat.id,
                    message_id: msg.message_id,
                    message_thread_id: messageThreadId
                }
            );
            
            sessionManager.updateSessionStatus(userId, 'studying');
            await bot.sendMessage(
                msg.chat.id,
                `${userName} ended their break and started studying.`,
                createMessageOptions(studySessionButtons)
            );
            break;

        case ACTIONS.END_SESSION:
            await bot.editMessageReplyMarkup(
                { inline_keyboard: [] },
                {
                    chat_id: msg.chat.id,
                    message_id: msg.message_id,
                    message_thread_id: messageThreadId
                }
            );
            
            const session = sessionManager.getSession(userId);
            if (session) {
                await bot.sendMessage(
                    msg.chat.id,
                    `${userName} ended their review on ${session.subject}. Congrats ${userName}. If you want to start a study session again, just click the button below`,
                    createMessageOptions(mainMenuButtons)
                );
                sessionManager.endSession(userId);
            }
            break;

        case ACTIONS.CANCEL_QUESTION:
            try {
                await bot.deleteMessage(msg.chat.id, msg.message_id);
            } catch (error) {
                console.error('Error deleting message:', error);
            }

            quiz.cancelQuestionCreation(userId);
            await bot.sendMessage(
                msg.chat.id,
                'Creating a question CANCELLED.',
                createMessageOptions(mainMenuButtons)
            );
            break;

        case ACTIONS.CANCEL_STUDYING:
            if (sessionManager.lastSubjectMessage) {
                try {
                    await bot.deleteMessage(
                        sessionManager.lastSubjectMessage.chatId,
                        sessionManager.lastSubjectMessage.messageId
                    );
                } catch (error) {
                    console.error('Error deleting subject message:', error);
                }
            }

            await bot.sendMessage(
                msg.chat.id,
                'Studying was mistakenly clicked. Session CANCELLED.',
                createMessageOptions(mainMenuButtons)
            );
            break;

        case ACTIONS.CREATE_QUESTION:
            if (sessionManager.lastMenuMessage) {
                try {
                    await bot.deleteMessage(
                        sessionManager.lastMenuMessage.chatId,
                        sessionManager.lastMenuMessage.messageId
                    );
                } catch (error) {
                    console.error('Error deleting menu message:', error);
                }
            }
            
            quiz.startQuestionCreation(userId);
            await bot.sendMessage(
                msg.chat.id,
                'Please select the subject for your question:',
                createMessageOptions(subjectButtons)
            );
            break;

        default:
            if (data.startsWith(`${ACTIONS.SELECT_SUBJECT}:`)) {
                const subject = data.split(':')[1];
                
                if (sessionManager.lastSubjectMessage) {
                    try {
                        await bot.deleteMessage(
                            sessionManager.lastSubjectMessage.chatId,
                            sessionManager.lastSubjectMessage.messageId
                        );
                    } catch (error) {
                        console.error('Error deleting subject message:', error);
                    }
                }
                
                sessionManager.startSession(userId, subject);
                await bot.sendMessage(
                    msg.chat.id,
                    `${userName} started studying ${subject}.`,
                    createMessageOptions(studySessionButtons)
                );
            }
    }
}

async function handleMessage(msg, bot) {
    // Only process messages in topics or private chats
    if (!msg.message_thread_id && msg.chat.type !== 'private') {
        return;
    }
    
    if (await quiz.handleQuestionCreation(msg, bot)) {
        return;
    }
}

module.exports = {
    handleStart,
    handleCallback,
    handleMessage
};
