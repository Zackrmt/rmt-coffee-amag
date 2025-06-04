/**
 * handlers.js
 * Created by: Zackrmt
 * Created at: 2025-06-04 13:43:04 UTC
 */

const { mainMenuButtons, subjectButtons, studySessionButtons, breakButtons, questionCreationCancelButton } = require('./buttons');
const { ACTIONS } = require('./constants');
const quiz = require('./quiz');
const sessionManager = require('./sessionManager');
const imageGenerator = require('./imageGenerator');

// Helper function to validate time format
function isValidTimeFormat(time) {
    return /^([0-9]|0[0-9]|1[0-9]|2[0-3]):[0-5][0-9]$/.test(time);
}

// Helper function to convert HH:MM to minutes
function convertToMinutes(timeStr) {
    const [hours, minutes] = timeStr.split(':').map(Number);
    return (hours * 60) + minutes;
}

async function cleanupMessages(chatId, bot, messageIds) {
    for (const messageId of messageIds) {
        try {
            await bot.deleteMessage(chatId, messageId);
        } catch (error) {
            console.error('Error deleting message:', error);
        }
    }
}

async function handleStart(msg, bot) {
    const chatId = msg.chat.id;
    const messageThreadId = msg.message_thread_id;
    
    if (!messageThreadId && msg.chat.type !== 'private') {
        return;
    }
    
    const messageOptions = {
        ...mainMenuButtons
    };
    
    if (messageThreadId) {
        messageOptions.message_thread_id = messageThreadId;
    }

    // Cleanup any previous menu message
    if (sessionManager.lastMenuMessage) {
        try {
            await bot.deleteMessage(
                sessionManager.lastMenuMessage.chatId,
                sessionManager.lastMenuMessage.messageId
            );
        } catch (error) {
            console.error('Error deleting previous menu:', error);
        }
    }

    const message = await bot.sendMessage(chatId, 'Welcome to Study Logger Bot!', messageOptions);
    
    sessionManager.lastMenuMessage = {
        chatId,
        messageId: message.message_id,
        messageThreadId
    };
}

async function handleStudyGoal(msg, bot, messageThreadId) {
    const goalMessage = await bot.sendMessage(
        msg.chat.id,
        'Study hours goal for this session:',
        {
            message_thread_id: messageThreadId,
            reply_markup: {
                inline_keyboard: [
                    [
                        { text: '⏱️ Set Goal', callback_data: ACTIONS.SET_GOAL },
                        { text: '⏭️ Skip', callback_data: ACTIONS.SKIP_GOAL }
                    ]
                ]
            }
        }
    );
    sessionManager.addSessionMessage(msg.from.id, goalMessage.message_id);
}

async function handleCallback(callbackQuery, bot) {
    const msg = callbackQuery.message;
    const data = callbackQuery.data;
    const userId = callbackQuery.from.id;
    const userName = callbackQuery.from.first_name || `User${userId}`;
    const messageThreadId = msg.message_thread_id;

    const createMessageOptions = (baseOptions = {}) => {
        return messageThreadId ? 
            { ...baseOptions, message_thread_id: messageThreadId } : 
            baseOptions;
    };

    // Start Studying Flow
    if (data === ACTIONS.START_STUDYING) {
        // Clean up previous messages
        const previousMessages = sessionManager.getSessionMessages(userId);
        await cleanupMessages(msg.chat.id, bot, previousMessages);
        sessionManager.clearSessionMessages(userId);

        await handleStudyGoal(msg, bot, messageThreadId);
        return;
    }

    // Goal Setting Flow
    if (data === ACTIONS.SET_GOAL) {
        const promptMsg = await bot.sendMessage(
            msg.chat.id,
            'Please enter your study goal in HH:MM format (e.g., 2:00 for 2 hours):',
            createMessageOptions(questionCreationCancelButton)
        );
        sessionManager.addSessionMessage(userId, promptMsg.message_id);
        return;
    }

    if (data === ACTIONS.SKIP_GOAL) {
        // Show subject selection
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
        return;
    }

    if (data === ACTIONS.CONFIRM_GOAL) {
        const session = sessionManager.getSession(userId);
        if (session && session.tempGoalMinutes) {
            sessionManager.setGoalTime(userId, session.tempGoalMinutes);
            delete session.tempGoalMinutes;

            // Show subject selection
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
        }
        return;
    }

    if (data === ACTIONS.RETRY_GOAL) {
        const session = sessionManager.getSession(userId);
        if (session) {
            delete session.tempGoalMinutes;
        }
        
        const promptMsg = await bot.sendMessage(
            msg.chat.id,
            'Please enter your study goal in HH:MM format (e.g., 2:00 for 2 hours):',
            createMessageOptions(questionCreationCancelButton)
        );
        sessionManager.addSessionMessage(userId, promptMsg.message_id);
        return;
    }

    // Subject Selection
    if (data.startsWith(`${ACTIONS.SELECT_SUBJECT}:`)) {
        const subject = data.split(':')[1];
        
        // Start new session
        sessionManager.startSession(userId, subject);
        
        const message = await bot.sendMessage(
            msg.chat.id,
            `Started studying ${subject}`,
            createMessageOptions(studySessionButtons)
        );
        
        sessionManager.addSessionMessage(userId, message.message_id);
        return;
    }

    // Break Handling
    if (data === ACTIONS.START_BREAK) {
        sessionManager.startBreak(userId);
        const message = await bot.sendMessage(
            msg.chat.id,
            'Break started',
            createMessageOptions(breakButtons)
        );
        sessionManager.addSessionMessage(userId, message.message_id);
        return;
    }

    if (data === ACTIONS.END_BREAK) {
        sessionManager.endBreak(userId);
        const message = await bot.sendMessage(
            msg.chat.id,
            'Break ended',
            createMessageOptions(studySessionButtons)
        );
        sessionManager.addSessionMessage(userId, message.message_id);
        return;
    }

    // End Session
    if (data === ACTIONS.END_SESSION) {
        const session = sessionManager.getSession(userId);
        if (session) {
            const stats = sessionManager.endSession(userId);

            // Message 1 - Permanent completion message
            await bot.sendMessage(
                msg.chat.id,
                `${userName} ended their review on ${session.subject}. Congrats ${userName}.`,
                createMessageOptions({})
            );

            // Message 2 - Goal time (temporary)
            const goalMsg = await bot.sendMessage(
                msg.chat.id,
                `Your goal study time for this session was ${sessionManager.formatTime(stats.goalTime)}`,
                createMessageOptions({})
            );
            sessionManager.addSessionMessage(userId, goalMsg.message_id);

            // Message 3 - Study time (permanent)
            await bot.sendMessage(
                msg.chat.id,
                `Your total study time for this session is ${sessionManager.formatTime(stats.actualTime)}`,
                createMessageOptions({})
            );

            // Message 4 - Break time (temporary)
            const breakMsg = await bot.sendMessage(
                msg.chat.id,
                `Your total break time was ${sessionManager.formatTime(stats.breakTime)}`,
                createMessageOptions({})
            );
            sessionManager.addSessionMessage(userId, breakMsg.message_id);

            // Message 5 - Design selection
            const designMsg = await bot.sendMessage(
                msg.chat.id,
                'Select a design to share your progress:',
                {
                    ...createMessageOptions({}),
                    reply_markup: {
                        inline_keyboard: [
                            [
                                { text: 'Design 1', callback_data: 'select_design:1' },
                                { text: 'Design 2', callback_data: 'select_design:2' },
                                { text: 'Design 3', callback_data: 'select_design:3' }
                            ]
                        ]
                    }
                }
            );
            sessionManager.addSessionMessage(userId, designMsg.message_id);
        }
        return;
    }

    // Design Selection and Sharing
    if (data.startsWith('select_design:')) {
        const designNumber = data.split(':')[1];
        const stats = sessionManager.getCurrentStats(userId);
        if (!stats) return;

        let imageBuffer;
        switch (designNumber) {
            case '1':
                imageBuffer = await imageGenerator.generateDesign1(stats);
                break;
            case '2':
                imageBuffer = await imageGenerator.generateDesign2(stats);
                break;
            case '3':
                imageBuffer = await imageGenerator.generateDesign3(stats);
                break;
        }

        // Send the generated image with sharing options
        const shareMsg = await bot.sendPhoto(msg.chat.id, imageBuffer, {
            ...createMessageOptions({}),
            caption: 'Share your progress:',
            reply_markup: {
                inline_keyboard: [
                    [
                        { text: 'Share to Instagram Story', callback_data: ACTIONS.SHARE_INSTAGRAM },
                        { text: 'Share to Facebook Story', callback_data: ACTIONS.SHARE_FACEBOOK }
                    ],
                    [
                        { text: "Don't Share", callback_data: ACTIONS.DONT_SHARE }
                    ]
                ]
            }
        });
        sessionManager.addSessionMessage(userId, shareMsg.message_id);
        return;
    }

    if (data === ACTIONS.SHARE_INSTAGRAM || data === ACTIONS.SHARE_FACEBOOK) {
        await bot.answerCallbackQuery(callbackQuery.id, {
            text: 'Opening sharing...',
            show_alert: false
        });
        // Here you would implement the actual sharing functionality
        return;
    }

    if (data === ACTIONS.DONT_SHARE) {
        const newSessionMsg = await bot.sendMessage(
            msg.chat.id,
            'If you want to start a study session again, just click the button below',
            createMessageOptions({
                reply_markup: {
                    inline_keyboard: [[
                        { text: '📚 Start Studying', callback_data: ACTIONS.START_STUDYING }
                    ]]
                }
            })
        );
        sessionManager.addSessionMessage(userId, newSessionMsg.message_id);
        return;
    }

    // Cancel Actions
    if (data === ACTIONS.CANCEL_STUDYING) {
        sessionManager.endSession(userId);
        await handleStart(msg, bot);
        return;
    }

    // Question Creation
    if (data === ACTIONS.CREATE_QUESTION) {
        quiz.startQuestionCreation(userId);
        const message = await bot.sendMessage(
            msg.chat.id,
            'Please upload an image with your question or type your question:',
            createMessageOptions(questionCreationCancelButton)
        );
        sessionManager.addSessionMessage(userId, message.message_id);
        return;
    }

    if (data === ACTIONS.CANCEL_QUESTION) {
        quiz.cancelQuestionCreation(userId);
        await handleStart(msg, bot);
        return;
    }

    // Handle other quiz-related callbacks
    await quiz.handleCallback(callbackQuery, bot);
}

async function handleMessage(msg, bot) {
    if (!msg.message_thread_id && msg.chat.type !== 'private') {
        return;
    }

    const userId = msg.from.id;

    // Handle study goal time input
    const session = sessionManager.getSession(userId);
    if (session && !session.goalTimeMinutes && msg.text) {
        if (isValidTimeFormat(msg.text)) {
            const minutes = convertToMinutes(msg.text);
            
            // Show confirmation message
            const confirmMsg = await bot.sendMessage(
                msg.chat.id,
                `Confirm study goal time: ${msg.text}?`,
                {
                    reply_markup: {
                        inline_keyboard: [
                            [
                                { text: '✅ Yes', callback_data: ACTIONS.CONFIRM_GOAL },
                                { text: '❌ No', callback_data: ACTIONS.RETRY_GOAL }
                            ]
                        ]
                    }
                }
            );
            session.tempGoalMinutes = minutes;
            sessionManager.addSessionMessage(userId, confirmMsg.message_id);
            return;
        } else {
            const errorMsg = await bot.sendMessage(
                msg.chat.id,
                'Please enter time in HH:MM format (e.g., 2:00 for 2 hours)',
                { reply_markup: questionCreationCancelButton.reply_markup }
            );
            sessionManager.addSessionMessage(userId, errorMsg.message_id);
            return;
        }
    }
    
    // Handle quiz question creation
    if (await quiz.handleQuestionCreation(msg, bot)) {
        return;
    }
}

module.exports = {
    handleStart,
    handleCallback,
    handleMessage
};
