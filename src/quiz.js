/**
 * quiz.js
 * Created by: Zackrmt
 * Created at: 2025-06-04 12:53:25 UTC
 */

const { mainMenuButtons, questionCreationCancelButton } = require('./buttons');
const { ACTIONS } = require('./constants');

class Quiz {
    constructor() {
        this.questions = new Map();
        this.currentQuestions = new Map();
        this.userState = new Map();
    }

    startQuestionCreation(userId) {
        this.userState.set(userId, {
            state: 'WAITING_SUBJECT',
            questionData: {},
            tempMessages: [] // Array to store message IDs to be deleted
        });
    }

    async cleanupMessages(chatId, bot) {
        const userStates = Array.from(this.userState.values());
        for (const state of userStates) {
            if (state.tempMessages && state.tempMessages.length > 0) {
                // Delete messages in reverse order to avoid issues
                for (const messageId of state.tempMessages.reverse()) {
                    try {
                        await bot.deleteMessage(chatId, messageId);
                    } catch (error) {
                        console.error('Error deleting message:', error);
                    }
                }
                state.tempMessages = [];
            }
        }
    }

    async addTempMessage(userId, messageId) {
        const userState = this.userState.get(userId);
        if (userState) {
            if (!userState.tempMessages) {
                userState.tempMessages = [];
            }
            userState.tempMessages.push(messageId);
        }
    }

    formatChoices(rawChoices) {
        return rawChoices
            .filter(choice => choice.trim() !== '')
            .map((choice, index) => `${String.fromCharCode(97 + index)}) ${choice.trim()}`);
    }

    createChoiceConfirmationMessage(choices) {
        let message = '<b>Are these the correct choices?</b>\n\n';
        choices.forEach(choice => {
            message += `${choice}\n`;
        });
        return message;
    }

    createAnswerConfirmationMessage(questionData, answer) {
        let message = '<b>Please confirm:</b>\n\n';
        message += `Question: ${questionData.question}\n\n`;
        questionData.choices.forEach(choice => {
            message += `${choice}\n`;
        });
        message += `\nSelected answer: ${answer.toUpperCase()}) ${questionData.choices.find(c => c.startsWith(answer + ')'))}`;
        return message;
    }

    async handleQuestionCreation(msg, bot) {
        const userId = msg.from.id;
        const userState = this.userState.get(userId);
        const messageThreadId = msg.message_thread_id;

        if (!userState) return false;

        const messageOptions = (options) => {
            return messageThreadId ? 
                { ...options, message_thread_id: messageThreadId, disable_notification: true } : 
                { ...options, disable_notification: true };
        };

        // Add both user message and bot response to temp list for cleanup
        if (msg.message_id) {
            await this.addTempMessage(userId, msg.message_id);
        }

        // Handle image upload
        if (msg.photo && userState.state === 'WAITING_QUESTION') {
            userState.questionData.image = {
                file_id: msg.photo[msg.photo.length - 1].file_id,
                caption: msg.caption || ''
            };
            
            if (msg.caption) {
                userState.questionData.question = msg.caption;
                userState.state = 'WAITING_CHOICES';
                const botMsg = await bot.sendMessage(
                    msg.chat.id,
                    'Enter each choice on a new line (2-5 choices):',
                    messageOptions(questionCreationCancelButton)
                );
                await this.addTempMessage(userId, botMsg.message_id);
            } else {
                const botMsg = await bot.sendMessage(
                    msg.chat.id,
                    'Image received! Now, please type your question:',
                    messageOptions(questionCreationCancelButton)
                );
                await this.addTempMessage(userId, botMsg.message_id);
            }
            return true;
        }

        switch (userState.state) {
            case 'WAITING_QUESTION':
                if (msg.text) {
                    userState.questionData.question = msg.text;
                    userState.state = 'WAITING_CHOICES';
                    const botMsg = await bot.sendMessage(
                        msg.chat.id,
                        'Enter each choice on a new line (2-5 choices):',
                        messageOptions(questionCreationCancelButton)
                    );
                    await this.addTempMessage(userId, botMsg.message_id);
                }
                return true;

            case 'WAITING_CHOICES':
                if (!msg.text) return true;

                const rawChoices = msg.text.split('\n');
                if (rawChoices.length < 2 || rawChoices.length > 5) {
                    const botMsg = await bot.sendMessage(
                        msg.chat.id,
                        'Please provide between 2 and 5 choices.',
                        messageOptions(questionCreationCancelButton)
                    );
                    await this.addTempMessage(userId, botMsg.message_id);
                    return true;
                }

                const formattedChoices = this.formatChoices(rawChoices);
                userState.questionData.tempChoices = formattedChoices;

                const confirmMsg = await bot.sendMessage(
                    msg.chat.id,
                    this.createChoiceConfirmationMessage(formattedChoices),
                    {
                        ...messageOptions({}),
                        parse_mode: 'HTML',
                        reply_markup: {
                            inline_keyboard: [
                                [
                                    { text: '✅ Yes', callback_data: 'confirm_choices' },
                                    { text: '❌ No, I need to correct', callback_data: 'retry_choices' }
                                ]
                            ]
                        }
                    }
                );
                await this.addTempMessage(userId, confirmMsg.message_id);
                return true;

            case 'WAITING_CORRECT_ANSWER':
                if (!msg.text) return true;

                const answer = msg.text.toLowerCase();
                const maxChoice = userState.questionData.choices.length;
                const validAnswers = Array.from({ length: maxChoice }, (_, i) => String.fromCharCode(97 + i));
                
                if (!validAnswers.includes(answer)) {
                    const botMsg = await bot.sendMessage(
                        msg.chat.id,
                        `Please enter a valid answer letter (${validAnswers.join(', ')})`,
                        messageOptions(questionCreationCancelButton)
                    );
                    await this.addTempMessage(userId, botMsg.message_id);
                    return true;
                }

                userState.questionData.tempAnswer = answer;
                const answerConfirmMsg = await bot.sendMessage(
                    msg.chat.id,
                    this.createAnswerConfirmationMessage(userState.questionData, answer),
                    {
                        ...messageOptions({}),
                        parse_mode: 'HTML',
                        reply_markup: {
                            inline_keyboard: [
                                [
                                    { text: '✅ Yes', callback_data: 'confirm_answer' },
                                    { text: '❌ No, I need to correct', callback_data: 'retry_answer' }
                                ]
                            ]
                        }
                    }
                );
                await this.addTempMessage(userId, answerConfirmMsg.message_id);
                return true;

            case 'WAITING_EXPLANATION':
                const questionId = Date.now().toString();
                const questionData = {
                    ...userState.questionData,
                    explanation: msg.text,
                    creatorId: msg.from.id,
                    creatorName: msg.from.first_name || `User${msg.from.id}`,
                    id: questionId,
                    createdAt: new Date().toISOString(),
                    messageThreadId
                };

                // Clean up all temporary messages
                await this.cleanupMessages(msg.chat.id, bot);

                this.questions.set(questionId, questionData);
                this.userState.delete(userId);
                
                // Create and send the final quiz message
                await this.sendQuizMessage(questionData, msg.chat.id, bot, messageThreadId);
                return true;
        }

        return false;
    }

    async sendQuizMessage(questionData, chatId, bot, messageThreadId) {
        const messageOptions = {
            parse_mode: 'HTML',
            reply_markup: this.createAnswerKeyboard(questionData.id, questionData.creatorId)
        };

        if (messageThreadId) {
            messageOptions.message_thread_id = messageThreadId;
        }

        if (questionData.image) {
            messageOptions.caption = this.createQuizMessage(questionData);
            await bot.sendPhoto(chatId, questionData.image.file_id, messageOptions);
        } else {
            await bot.sendMessage(chatId, this.createQuizMessage(questionData), messageOptions);
        }
    }

    createQuizMessage(questionData) {
        let message = `<b>Subject: ${questionData.subject}</b>\n\n`;
        message += `<b>${questionData.question}</b>\n\n`;
        questionData.choices.forEach(choice => {
            message += `${choice}\n`;
        });
        message += `\nQuestion created by ${questionData.creatorName}`;
        return message;
    }

    createAnswerKeyboard(questionId, creatorId) {
        const question = this.questions.get(questionId);
        const numChoices = question ? question.choices.length : 5;
        
        const choices = Array.from({ length: numChoices }, (_, i) => ({
            text: String.fromCharCode(65 + i),
            callback_data: `answer:${questionId}:${String.fromCharCode(97 + i)}`
        }));

        const keyboard = {
            inline_keyboard: [
                choices,
                [
                    { text: '➕ Add New Question', callback_data: `add_confirm:${questionId}` }
                ],
                creatorId ? [
                    {
                        text: '🗑️ Delete Question',
                        callback_data: `delete_confirm_1:${questionId}`
                    }
                ] : []
            ].filter(row => row.length > 0)
        };

        return keyboard;
    }

    createAddConfirmationKeyboard(questionId) {
        return {
            inline_keyboard: [
                [
                    { text: 'Yes', callback_data: 'start_new_question' },
                    { text: 'No', callback_data: `add_cancel:${questionId}` }
                ]
            ]
        };
    }

    createDeleteConfirmation1Keyboard(questionId) {
        return {
            inline_keyboard: [
                [
                    { text: 'Yes', callback_data: `delete_confirm_2:${questionId}` },
                    { text: 'No', callback_data: `delete_cancel:${questionId}` }
                ]
            ]
        };
    }

    createDeleteConfirmation2Keyboard(questionId) {
        return {
            inline_keyboard: [
                [
                    { text: 'YES, I AM SURE', callback_data: `delete_question:${questionId}` },
                    { text: 'NO', callback_data: `delete_cancel:${questionId}` }
                ]
            ]
        };
    }

    async handleAddConfirmation(questionId, chatId, bot, messageThreadId) {
        const question = this.questions.get(questionId);
        if (!question) return false;

        const options = messageThreadId ? { message_thread_id: messageThreadId } : {};
        await bot.sendMessage(
            chatId,
            'Do you want to add a new question?',
            {
                ...options,
                reply_markup: this.createAddConfirmationKeyboard(questionId)
            }
        );
        return true;
    }

    async handleAddCancel(questionId, chatId, messageId, bot, messageThreadId) {
        try {
            // Delete the confirmation message
            await bot.deleteMessage(chatId, messageId);
        } catch (error) {
            console.error('Error deleting confirmation message:', error);
        }
    }

    async handleDeleteConfirmation1(questionId, userId, chatId, bot, messageThreadId) {
        const question = this.questions.get(questionId);
        if (!question || question.creatorId !== userId) return false;

        const options = messageThreadId ? { message_thread_id: messageThreadId } : {};
        await bot.sendMessage(
            chatId,
            'Are you sure you want to delete this question?',
            {
                ...options,
                reply_markup: this.createDeleteConfirmation1Keyboard(questionId)
            }
        );
        return true;
    }

    async handleDeleteConfirmation2(questionId, userId, chatId, bot, messageThreadId) {
        const question = this.questions.get(questionId);
        if (!question || question.creatorId !== userId) return false;

        const options = messageThreadId ? { message_thread_id: messageThreadId } : {};
        await bot.sendMessage(
            chatId,
            'REALLY? Are you sure?',
            {
                ...options,
                reply_markup: this.createDeleteConfirmation2Keyboard(questionId)
            }
        );
        return true;
    }

    async handleDeleteCancel(questionId, userId, chatId, bot, messageThreadId) {
        const question = this.questions.get(questionId);
        if (!question) return false;
        
        await this.sendQuizMessage(question, chatId, bot, messageThreadId);
        return true;
    }

    async handleAnswer(callbackQuery, bot) {
        const [_, questionId, answer] = callbackQuery.data.split(':');
        const question = this.questions.get(questionId);
        const messageThreadId = callbackQuery.message.message_thread_id;
        
        if (!question) return;

        const isCorrect = answer === question.correctAnswer;
        const responseMessage = isCorrect ? '✅ Correct!' : '❌ Wrong!';

        await bot.answerCallbackQuery(callbackQuery.id, {
            text: responseMessage,
            show_alert: true
        });

        // Show explanation after 3 seconds, but keep the original question
        setTimeout(async () => {
            const correctChoice = question.choices.find(choice => 
                choice.toLowerCase().startsWith(question.correctAnswer.toLowerCase())
            );
            
            const options = messageThreadId ? 
                { message_thread_id: messageThreadId, parse_mode: 'HTML' } : 
                { parse_mode: 'HTML' };
            
            const explanationMessage = isCorrect ?
                `✅ <b>Correct!</b>\n\n<b>Explanation:</b>\n${question.explanation}` :
                `❌ <b>The correct answer is:</b>\n${correctChoice}\n\n<b>Explanation:</b>\n${question.explanation}`;
            
            // Send explanation as a separate message
            const explanationMsg = await bot.sendMessage(
                callbackQuery.message.chat.id,
                explanationMessage,
                {
                    ...options,
                    reply_markup: {
                        inline_keyboard: [[
                            { text: 'Done Reading', callback_data: `done:${questionId}` }
                        ]]
                    }
                }
            );
        }, 3000);
    }

    async handleDoneReading(questionId, chatId, messageId, bot, messageThreadId) {
        try {
            // Only delete the explanation message
            await bot.deleteMessage(chatId, messageId);
        } catch (error) {
            console.error('Error deleting explanation message:', error);
        }
    }

    async deleteQuestion(questionId, userId, chatId, bot, messageThreadId) {
        const question = this.questions.get(questionId);
        if (question && question.creatorId === userId) {
            this.questions.delete(questionId);
            const options = messageThreadId ? { message_thread_id: messageThreadId } : {};
            await bot.sendMessage(
                chatId, 
                'Question has been deleted.',
                {
                    ...options,
                    reply_markup: {
                        inline_keyboard: [[
                            { text: '➕ Create New Question', callback_data: ACTIONS.CREATE_QUESTION }
                        ]]
                    }
                }
            );
            return true;
        }
        return false;
    }

    cancelQuestionCreation(userId) {
        this.userState.delete(userId);
    }

    async handleConfirmChoices(userId, chatId, bot, messageThreadId) {
        const userState = this.userState.get(userId);
        if (!userState || !userState.questionData.tempChoices) return false;

        userState.questionData.choices = userState.questionData.tempChoices;
        delete userState.questionData.tempChoices;
        userState.state = 'WAITING_CORRECT_ANSWER';

        const botMsg = await bot.sendMessage(
            chatId,
            `Please enter the correct answer (${Array.from({ length: userState.questionData.choices.length }, 
                (_, i) => String.fromCharCode(97 + i)).join(', ')}):`,
            messageThreadId ? 
                { message_thread_id: messageThreadId, ...questionCreationCancelButton, disable_notification: true } : 
                { ...questionCreationCancelButton, disable_notification: true }
        );
        await this.addTempMessage(userId, botMsg.message_id);
        return true;
    }

    async handleRetryChoices(userId, chatId, bot, messageThreadId) {
        const userState = this.userState.get(userId);
        if (!userState) return false;

        userState.state = 'WAITING_CHOICES';
        delete userState.questionData.tempChoices;

        const botMsg = await bot.sendMessage(
            chatId,
            'Enter each choice on a new line (2-5 choices):',
            messageThreadId ? 
                { message_thread_id: messageThreadId, ...questionCreationCancelButton, disable_notification: true } : 
                { ...questionCreationCancelButton, disable_notification: true }
        );
        await this.addTempMessage(userId, botMsg.message_id);
        return true;
    }

    async handleConfirmAnswer(userId, chatId, bot, messageThreadId) {
        const userState = this.userState.get(userId);
        if (!userState || !userState.questionData.tempAnswer) return false;

        userState.questionData.correctAnswer = userState.questionData.tempAnswer;
        delete userState.questionData.tempAnswer;
        userState.state = 'WAITING_EXPLANATION';

        const botMsg = await bot.sendMessage(
            chatId,
            'Please explain why this is the correct answer:',
            messageThreadId ? 
                { message_thread_id: messageThreadId, ...questionCreationCancelButton, disable_notification: true } : 
                { ...questionCreationCancelButton, disable_notification: true }
        );
        await this.addTempMessage(userId, botMsg.message_id);
        return true;
    }

    async handleRetryAnswer(userId, chatId, bot, messageThreadId) {
        const userState = this.userState.get(userId);
        if (!userState) return false;

        userState.state = 'WAITING_CORRECT_ANSWER';
        delete userState.questionData.tempAnswer;

        const botMsg = await bot.sendMessage(
            chatId,
            `Please enter the correct answer (${Array.from({ length: userState.questionData.choices.length }, 
                (_, i) => String.fromCharCode(97 + i)).join(', ')}):`,
            messageThreadId ? 
                { message_thread_id: messageThreadId, ...questionCreationCancelButton, disable_notification: true } : 
                { ...questionCreationCancelButton, disable_notification: true }
        );
        await this.addTempMessage(userId, botMsg.message_id);
        return true;
    }
}

module.exports = new Quiz();
