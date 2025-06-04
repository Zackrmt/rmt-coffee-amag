/**
 * quiz.js
 * Created by: Zackrmt
 * Created at: 2025-06-04 03:10:20 UTC
 */

const { mainMenuButtons, questionCreationCancelButton } = require('./buttons');

class Quiz {
    constructor() {
        this.questions = new Map();
        this.currentQuestions = new Map();
        this.userState = new Map();
    }

    startQuestionCreation(userId) {
        this.userState.set(userId, {
            state: 'WAITING_SUBJECT',
            questionData: {}
        });
    }

    async handleQuestionCreation(msg, bot) {
        const userId = msg.from.id;
        const userState = this.userState.get(userId);
        const messageThreadId = msg.message_thread_id;

        if (!userState) return false;

        const messageOptions = (options) => {
            return messageThreadId ? { ...options, message_thread_id: messageThreadId } : options;
        };

        // Handle image upload
        if (msg.photo && userState.state === 'WAITING_QUESTION') {
            userState.questionData.image = {
                file_id: msg.photo[msg.photo.length - 1].file_id,
                caption: msg.caption || ''
            };
            
            if (msg.caption) {
                userState.questionData.question = msg.caption;
                userState.state = 'WAITING_CHOICES';
                await bot.sendMessage(
                    msg.chat.id,
                    'Please enter the choices (one per line) in format:\na) Choice 1\nb) Choice 2\nc) Choice 3\nd) Choice 4\ne) Choice 5',
                    messageOptions(questionCreationCancelButton)
                );
            } else {
                await bot.sendMessage(
                    msg.chat.id,
                    'Image received! Now, please type your question:',
                    messageOptions(questionCreationCancelButton)
                );
            }
            return true;
        }

        // Delete text messages immediately
        if (!msg.photo) {
            try {
                await bot.deleteMessage(msg.chat.id, msg.message_id);
            } catch (error) {
                console.error('Error deleting message:', error);
            }
        }

        switch (userState.state) {
            case 'WAITING_QUESTION':
                if (msg.text) {
                    userState.questionData.question = msg.text;
                    userState.state = 'WAITING_CHOICES';
                    await bot.sendMessage(
                        msg.chat.id,
                        'Please enter the choices (one per line) in format:\na) Choice 1\nb) Choice 2\nc) Choice 3\nd) Choice 4\ne) Choice 5',
                        messageOptions(questionCreationCancelButton)
                    );
                } else if (!msg.photo) {
                    await bot.sendMessage(
                        msg.chat.id,
                        'You can either:\n1. Type your question directly, or\n2. Send an image with your question in the caption',
                        messageOptions(questionCreationCancelButton)
                    );
                }
                return true;

            case 'WAITING_CHOICES':
                const choices = msg.text.split('\n').map(choice => choice.trim());
                if (choices.length < 2) {
                    await bot.sendMessage(
                        msg.chat.id,
                        'Please provide at least 2 choices.',
                        messageOptions(questionCreationCancelButton)
                    );
                    return true;
                }
                userState.questionData.choices = choices;
                userState.state = 'WAITING_CORRECT_ANSWER';
                await bot.sendMessage(
                    msg.chat.id,
                    'Which is the correct answer? (Enter the letter only: a, b, c, d, or e)',
                    messageOptions(questionCreationCancelButton)
                );
                return true;

            case 'WAITING_CORRECT_ANSWER':
                const answer = msg.text.toLowerCase();
                if (!['a', 'b', 'c', 'd', 'e'].includes(answer)) {
                    await bot.sendMessage(
                        msg.chat.id,
                        'Please enter a valid answer letter (a, b, c, d, or e)',
                        messageOptions(questionCreationCancelButton)
                    );
                    return true;
                }
                userState.questionData.correctAnswer = answer;
                userState.state = 'WAITING_EXPLANATION';
                await bot.sendMessage(
                    msg.chat.id,
                    'Please explain why this is the correct answer:',
                    messageOptions(questionCreationCancelButton)
                );
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
                this.questions.set(questionId, questionData);
                this.userState.delete(userId);
                
                // Create and send the quiz message with image if exists
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
        const choices = ['a', 'b', 'c', 'd', 'e'].map(letter => ({
            text: letter.toUpperCase(),
            callback_data: `answer:${questionId}:${letter}`
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

        // Always show explanation after 3 seconds, regardless of correct/incorrect
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
            
            try {
                // Delete the original question message
                await bot.deleteMessage(callbackQuery.message.chat.id, callbackQuery.message.message_id);
            } catch (error) {
                console.error('Error deleting original message:', error);
            }

            // Send the explanation with the question
            if (question.image) {
                const messageOptions = {
                    ...options,
                    caption: this.createQuizMessage(question) + '\n\n' + explanationMessage,
                    reply_markup: {
                        inline_keyboard: [[
                            { text: 'Done Reading', callback_data: `done:${questionId}` }
                        ]]
                    }
                };
                await bot.sendPhoto(callbackQuery.message.chat.id, question.image.file_id, messageOptions);
            } else {
                await bot.sendMessage(
                    callbackQuery.message.chat.id,
                    this.createQuizMessage(question) + '\n\n' + explanationMessage,
                    {
                        ...options,
                        reply_markup: {
                            inline_keyboard: [[
                                { text: 'Done Reading', callback_data: `done:${questionId}` }
                            ]]
                        }
                    }
                );
            }
        }, 3000);
    }

    async handleDoneReading(questionId, chatId, messageId, bot, messageThreadId) {
        try {
            // Delete the explanation message
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
                    reply_markup: mainMenuButtons.reply_markup
                }
            );
            return true;
        }
        return false;
    }

    cancelQuestionCreation(userId) {
        this.userState.delete(userId);
    }
}

module.exports = new Quiz();
