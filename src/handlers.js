class SessionManager {
    // ... (previous code remains the same)
}

const sessionManager = new SessionManager();

async function handleStart(msg, bot) {
    const chatId = msg.chat.id;
    const message = await bot.sendMessage(chatId, 'Welcome to Study Logger Bot!', mainMenuButtons);
    
    // Store message ID for later deletion
    sessionManager.lastMenuMessage = {
        chatId,
        messageId: message.message_id
    };
}

async function handleCallback(callbackQuery, bot) {
    const msg = callbackQuery.message;
    const data = callbackQuery.data;
    const userId = callbackQuery.from.id;
    const userName = callbackQuery.from.first_name || `User${userId}`;

    if (data.startsWith('answer:')) {
        await quiz.handleAnswer(callbackQuery, bot);
        return;
    }

    if (data.startsWith('delete_question:')) {
        const questionId = data.split(':')[1];
        await quiz.deleteQuestion(questionId, userId, msg.chat.id, bot);
        // Delete the question message
        try {
            await bot.deleteMessage(msg.chat.id, msg.message_id);
        } catch (error) {
            console.error('Error deleting message:', error);
        }
        return;
    }

    if (data.startsWith('done:')) {
        // Delete the explanation message and show the question again
        await bot.deleteMessage(msg.chat.id, msg.message_id);
        const questionId = data.split(':')[1];
        const question = quiz.questions.get(questionId);
        if (question) {
            const quizMessage = quiz.createQuizMessage(question);
            const keyboard = quiz.createAnswerKeyboard(questionId, question.creatorId);
            await bot.sendMessage(msg.chat.id, quizMessage, {
                reply_markup: keyboard,
                parse_mode: 'HTML'
            });
        }
        return;
    }

    switch (data) {
        case ACTIONS.START_STUDYING:
            // Delete previous main menu message if exists
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
            
            const subjectMessage = await bot.sendMessage(msg.chat.id, 'What subject?', subjectButtons);
            sessionManager.lastSubjectMessage = {
                chatId: msg.chat.id,
                messageId: subjectMessage.message_id
            };
            break;

        case ACTIONS.START_BREAK:
            // Only delete the button, keep the message
            await bot.editMessageReplyMarkup(
                { inline_keyboard: [] },
                {
                    chat_id: msg.chat.id,
                    message_id: msg.message_id
                }
            );
            
            sessionManager.updateSessionStatus(userId, 'break');
            await bot.sendMessage(
                msg.chat.id,
                `${userName} started a break. Break Responsibly, ${userName}!`,
                breakButtons
            );
            break;

        case ACTIONS.END_BREAK:
            // Only delete the button, keep the message
            await bot.editMessageReplyMarkup(
                { inline_keyboard: [] },
                {
                    chat_id: msg.chat.id,
                    message_id: msg.message_id
                }
            );
            
            sessionManager.updateSessionStatus(userId, 'studying');
            await bot.sendMessage(
                msg.chat.id,
                `${userName} ended their break and started studying.`,
                studySessionButtons
            );
            break;

        case ACTIONS.END_SESSION:
            // Only delete the button, keep the message
            await bot.editMessageReplyMarkup(
                { inline_keyboard: [] },
                {
                    chat_id: msg.chat.id,
                    message_id: msg.message_id
                }
            );
            
            const session = sessionManager.getSession(userId);
            if (session) {
                await bot.sendMessage(
                    msg.chat.id,
                    `${userName} ended their review on ${session.subject}. Congrats ${userName}. If you want to start a study session again, just click the button below`,
                    mainMenuButtons
                );
                sessionManager.endSession(userId);
            }
            break;

        case ACTIONS.CREATE_QUESTION:
            // Delete previous main menu message if exists
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
            await bot.sendMessage(msg.chat.id, 'Please enter your question:');
            break;

        default:
            if (data.startsWith(`${ACTIONS.SELECT_SUBJECT}:`)) {
                const subject = data.split(':')[1];
                
                // Delete the subject selection message
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
                    studySessionButtons
                );
            }
    }
}

async function handleMessage(msg, bot) {
    if (await quiz.handleQuestionCreation(msg, bot)) {
        // Message deletion is handled inside handleQuestionCreation
        return;
    }
}

module.exports = {
    handleStart,
    handleCallback,
    handleMessage
};
