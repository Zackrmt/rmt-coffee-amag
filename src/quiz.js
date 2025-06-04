class Quiz {
    constructor() {
        this.questions = new Map();
        this.currentQuestions = new Map();
        this.userState = new Map();
    }

    startQuestionCreation(userId) {
        this.userState.set(userId, {
            state: 'WAITING_QUESTION',
            questionData: {}
        });
    }

    async handleQuestionCreation(msg, bot) {
        const userId = msg.from.id;
        const userState = this.userState.get(userId);

        if (!userState) return false;

        switch (userState.state) {
            case 'WAITING_QUESTION':
                userState.questionData.question = msg.text;
                userState.state = 'WAITING_CHOICES';
                await bot.sendMessage(msg.chat.id, 'Please enter the choices (one per line) in format:\na) Choice 1\nb) Choice 2\nc) Choice 3\nd) Choice 4\ne) Choice 5');
                return true;

            case 'WAITING_CHOICES':
                const choices = msg.text.split('\n').map(choice => choice.trim());
                if (choices.length < 2) {
                    await bot.sendMessage(msg.chat.id, 'Please provide at least 2 choices.');
                    return true;
                }
                userState.questionData.choices = choices;
                userState.state = 'WAITING_CORRECT_ANSWER';
                await bot.sendMessage(msg.chat.id, 'Which is the correct answer? (Enter the letter only: a, b, c, d, or e)');
                return true;

            case 'WAITING_CORRECT_ANSWER':
                const answer = msg.text.toLowerCase();
                if (!['a', 'b', 'c', 'd', 'e'].includes(answer)) {
                    await bot.sendMessage(msg.chat.id, 'Please enter a valid answer letter (a, b, c, d, or e)');
                    return true;
                }
                userState.questionData.correctAnswer = answer;
                userState.state = 'WAITING_EXPLANATION';
                await bot.sendMessage(msg.chat.id, 'Please provide the explanation for the correct answer');
                return true;

            case 'WAITING_EXPLANATION':
                const questionId = Date.now().toString();
                const questionData = {
                    ...userState.questionData,
                    explanation: msg.text,
                    creator: msg.from.username || msg.from.first_name,
                    id: questionId
                };
                this.questions.set(questionId, questionData);
                this.userState.delete(userId);
                
                // Create the quiz message
                const quizMessage = this.createQuizMessage(questionData);
                const keyboard = this.createAnswerKeyboard(questionId);
                
                await bot.sendMessage(msg.chat.id, quizMessage, {
                    reply_markup: keyboard,
                    parse_mode: 'HTML'
                });
                return true;
        }

        return false;
    }

    createQuizMessage(questionData) {
        let message = `<b>${questionData.question}</b>\n\n`;
        questionData.choices.forEach(choice => {
            message += `${choice}\n`;
        });
        message += `\nQuestion created by @${questionData.creator}`;
        return message;
    }

    createAnswerKeyboard(questionId) {
        return {
            inline_keyboard: [
                ['a', 'b', 'c', 'd', 'e'].map(letter => ({
                    text: letter.toUpperCase(),
                    callback_data: `answer:${questionId}:${letter}`
                }))
            ]
        };
    }

    async handleAnswer(callbackQuery, bot) {
        const [_, questionId, answer] = callbackQuery.data.split(':');
        const question = this.questions.get(questionId);
        
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
                await bot.sendMessage(callbackQuery.message.chat.id, 
                    `<b>Explanation:</b>\n${question.explanation}`, {
                    parse_mode: 'HTML',
                    reply_markup: {
                        inline_keyboard: [[
                            { text: 'Done Reading', callback_data: `done:${questionId}` }
                        ]]
                    }
                });
            }, 5000);
        }
    }
}

module.exports = new Quiz();
