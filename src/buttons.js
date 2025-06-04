const { SUBJECTS, ACTIONS } = require('./constants');

const mainMenuButtons = {
    reply_markup: {
        inline_keyboard: [
            [
                { text: 'Start Studying 📖', callback_data: ACTIONS.START_STUDYING },
                { text: 'Start Creating Questions 🤔💡', callback_data: ACTIONS.CREATE_QUESTION }
            ]
        ]
    }
};

const subjectButtons = {
    reply_markup: {
        inline_keyboard: [
            ...Object.entries(SUBJECTS).map(([_, subject]) => [
                { text: subject, callback_data: `${ACTIONS.SELECT_SUBJECT}:${subject}` }
            ]),
            [{ text: '❌ Cancel', callback_data: ACTIONS.CANCEL_STUDYING }] // Add cancel button
        ]
    }
};

const questionCreationCancelButton = {
    reply_markup: {
        inline_keyboard: [
            [{ text: '❌ Cancel', callback_data: ACTIONS.CANCEL_QUESTION }]
        ]
    }
};

// ... (other button configurations remain the same)

module.exports = {
    mainMenuButtons,
    subjectButtons,
    studySessionButtons,
    breakButtons,
    questionCreationCancelButton
};
