class Quiz {
    // ... (previous methods remain the same until createQuizMessage)

    createQuizMessage(questionData) {
        let message = `<b>${questionData.question}</b>\n\n`;
        questionData.choices.forEach(choice => {
            message += `${choice}\n`;
        });
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

    async handleQuestionCreation(msg, bot) {
        const userId = msg.from.id;
        const userState = this.userState.get(userId);

        if (!userState) return false;

        // Delete the user's message immediately
        try {
            await bot.deleteMessage(msg.chat.id, msg.message_id);
        } catch (error) {
            console.error('Error deleting message:', error);
        }

        switch (userState.state) {
            // ... (previous cases remain the same until the final case)

            case 'WAITING_EXPLANATION':
                const questionId = Date.now().toString();
                const questionData = {
                    ...userState.questionData,
                    explanation: msg.text,
                    creatorId: msg.from.id,
                    creatorName: msg.from.first_name || `User${msg.from.id}`,
                    id: questionId
                };
                this.questions.set(questionId, questionData);
                this.userState.delete(userId);
                
                // Create the quiz message
                const quizMessage = this.createQuizMessage(questionData);
                const keyboard = this.createAnswerKeyboard(questionId, msg.from.id);
                
                await bot.sendMessage(msg.chat.id, quizMessage, {
                    reply_markup: keyboard,
                    parse_mode: 'HTML'
                });
                return true;
        }

        return false;
    }

    async deleteQuestion(questionId, userId, chatId, bot) {
        const question = this.questions.get(questionId);
        if (question && question.creatorId === userId) {
            this.questions.delete(questionId);
            await bot.sendMessage(chatId, 'Question has been deleted.');
            return true;
        }
        return false;
    }
}

module.exports = new Quiz();
