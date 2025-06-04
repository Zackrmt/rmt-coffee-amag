const { SUBJECTS, ACTIONS } = require('./constants');

const mainMenuButtons = {
    reply_markup: {
        inline_keyboard: [
            [
                { text: 'Start Studying', callback_data: ACTIONS.START_STUDYING },
                { text: 'Start Creating Questions', callback_data: ACTIONS.CREATE_QUESTION }
            ]
        ]
    }
};

const subjectButtons = {
    reply_markup: {
        inline_keyboard: Object.entries(SUBJECTS).map(([_, subject]) => [
            { text: subject, callback_data: `${ACTIONS.SELECT_SUBJECT}:${subject}` }
        ])
    }
};

const studySessionButtons = {
    reply_markup: {
        inline_keyboard: [
            [
                { text: 'START BREAK', callback_data: ACTIONS.START_BREAK },
                { text: 'END STUDY SESSION', callback_data: ACTIONS.END_SESSION }
            ]
        ]
    }
};

const breakButtons = {
    reply_markup: {
        inline_keyboard: [
            [
                { text: 'END BREAK', callback_data: ACTIONS.END_BREAK },
                { text: 'END STUDY SESSION', callback_data: ACTIONS.END_SESSION }
            ]
        ]
    }
};

module.exports = {
    mainMenuButtons,
    subjectButtons,
    studySessionButtons,
    breakButtons
};
