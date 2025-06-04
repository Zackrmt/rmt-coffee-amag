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

        // Delete the user's message immediately
        try {
            await bot.deleteMessage(msg.chat.id, msg.message_id);
        } catch (error) {
            console.error('Error deleting message:', error);
        }

        const messageOptions = (options) => {
            return messageThreadId ? { ...options, message_thread_id: messageThreadId } : options;
        };

        switch (userState.state) {
            case 'WAITING_SUBJECT':
                const subject = msg.text;
                if (!Object.values(require('./constants').SUBJECTS).includes(subject)) {
                    await bot.sendMessage(
                        msg.chat.id,
                        'Please select a valid subject from the list.',
                        messageOptions(questionCreationCancelButton)
                    );
                    return true;
                }
                userState.questionData.subject = subject;
                userState.state = 'WAITING_QUESTION';
                await bot.sendMessage(
                    msg.chat.id,
                    'Please enter your question:',
                    messageOptions(questionCreationCancelButton)
                );
                return true;

            case 'WAITING_QUESTION':
                userState.questionData.question = msg.text;
                userState.state = 'WAITING_CHOICES';
                await bot.sendMessage(
                    msg.chat.id,
                    'Please enter the choices (one per line) in format:\na) Choice 1\nb) Choice 2\nc) Choice 3\nd) Choice 4\ne) Choice 5',
                    messageOptions(questionCreationCancelButton)
                );
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
                    'Please provide the explanation for the correct answer',
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
                    subject: userState.questionData.subject,
                    id: questionId,
                    createdAt: new Date().toISOString(),
                    messageThreadId
                };
                this.questions.set(questionId, questionData);
                this.userState.delete(userId);
                
                // Create the quiz message
                const quizMessage = this.createQuizMessage(questionData);
                const keyboard = this.createAnswerKeyboard(questionId, msg.from.id);
                
                await bot.sendMessage(
                    msg.chat.id,
                    quizMessage,
                    messageOptions({
                        reply_markup: keyboard,
                        parse_mode: 'HTML'
                    })
                );
                return true;
        }

        return false;
    }

    createQuizMessage(questionData) {
        let message = `<b>${questionData.question}</b>\n\n`;
        questionData.choices.forEach(choice => {
            message += `${choice}\n`;
        });
        message += `\nSubject: ${questionData.subject}`;
        message += `\nQuestion created by ${questionData.creatorName} (ID: ${questionData.creatorId})`;
        return message;
    }

    createAnswerKeyboard(questionId, creatorId) {
        return {
            inline_keyboard: [
                ['a', 'b', 'c', 'd', 'e'].map(letter => ({
                    text: letter.toUpperCase(),
                    callback_data: `answer:${questionId}:${letter}`
                })),
                creatorId ? [
                    {
                        text: '🗑️ Delete Question',
                        callback_data: `delete_question:${questionId}`
                    }
                ] : []
            ].filter(row => row.length > 0)
        };
    }

    async handleAnswer(callbackQuery, bot) {
        const [_, questionId, answer] = callbackQuery.data.split(':');
        const question = this.questions.get(questionId);
        const messageThreadId = callbackQuery.message.message_thread_id;
        
        if (!question) return;

        const isCorrect = answer === question.correctAnswer;
        const responseMessage = isCorrect ? 
            '✅ Correct!' : 
            `❌ Wrong! The correct answer is ${question.correctAnswer.toUpperCase()}`;

        await bot.answerCallbackQuery(callbackQuery.id, {
            text: responseMessage,
            show_alert: true
        });

        if (!isCorrect) {
            setTimeout(async () => {
                const options = messageThreadId ? 
                    { message_thread_id: messageThreadId, parse_mode: 'HTML' } : 
                    { parse_mode: 'HTML' };
                
                await bot.sendMessage(
                    callbackQuery.message.chat.id,
                    `<b>Explanation:</b>\n${question.explanation}`,
                    {
                        ...options,
                        reply_markup: {
                            inline_keyboard: [[
                                { text: 'Done Reading', callback_data: `done:${questionId}` }
                            ]]
                        }
                    }
                );
            }, 5000);
        }
    }

    async deleteQuestion(questionId, userId, chatId, bot, messageThreadId) {
        const question = this.questions.get(questionId);
        if (question && question.creatorId === userId) {
            this.questions.delete(questionId);
            const options = messageThreadId ? { message_thread_id: messageThreadId } : {};
            await bot.sendMessage(chatId, 'Question has been deleted.', options);
            return true;
        }
        return false;
    }

    cancelQuestionCreation(userId) {
        this.userState.delete(userId);
    }
}

module.exports = new Quiz();
