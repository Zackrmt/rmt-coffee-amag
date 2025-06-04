/**
 * buttons.js
 * Created by: Zackrmt
 * Created at: 2025-06-04 13:38:04 UTC
 */

const { ACTIONS } = require('./constants');

const mainMenuButtons = {
    reply_markup: {
        inline_keyboard: [
            [
                { text: '📚 Start Studying', callback_data: ACTIONS.START_STUDYING }
            ],
            [
                { text: '➕ Create Question', callback_data: ACTIONS.CREATE_QUESTION }
            ]
        ]
    }
};

const subjectButtons = {
    reply_markup: {
        inline_keyboard: [
            [
                { text: '📐 Mathematics', callback_data: `${ACTIONS.SELECT_SUBJECT}:Mathematics` },
                { text: '🔬 Science', callback_data: `${ACTIONS.SELECT_SUBJECT}:Science` }
            ],
            [
                { text: '📚 English', callback_data: `${ACTIONS.SELECT_SUBJECT}:English` },
                { text: '🌏 Social Studies', callback_data: `${ACTIONS.SELECT_SUBJECT}:Social Studies` }
            ],
            [
                { text: '💻 Computer', callback_data: `${ACTIONS.SELECT_SUBJECT}:Computer` },
                { text: '📝 Professional Education', callback_data: `${ACTIONS.SELECT_SUBJECT}:Professional Education` }
            ]
        ]
    }
};

const studySessionButtons = {
    reply_markup: {
        inline_keyboard: [
            [
                { text: '⏸️ Start Break', callback_data: ACTIONS.START_BREAK }
            ],
            [
                { text: '⏹️ End Session', callback_data: ACTIONS.END_SESSION }
            ]
        ]
    }
};

const breakButtons = {
    reply_markup: {
        inline_keyboard: [
            [
                { text: '▶️ End Break', callback_data: ACTIONS.END_BREAK }
            ],
            [
                { text: '⏹️ End Session', callback_data: ACTIONS.END_SESSION }
            ]
        ]
    }
};

const questionCreationCancelButton = {
    reply_markup: {
        inline_keyboard: [
            [
                { text: '❌ Cancel', callback_data: ACTIONS.CANCEL_QUESTION }
            ]
        ]
    }
};

module.exports = {
    mainMenuButtons,
    subjectButtons,
    studySessionButtons,
    breakButtons,
    questionCreationCancelButton
};
