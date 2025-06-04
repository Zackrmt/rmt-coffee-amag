/**
 * constants.js
 * Created by: Zackrmt
 * Created at: 2025-06-04 14:00:04 UTC
 */

const ACTIONS = {
    START_STUDYING: 'start_studying',
    START_BREAK: 'start_break',
    END_BREAK: 'end_break',
    END_SESSION: 'end_session',
    WHAT_SUBJECT: 'what_subject',
    CREATE_QUESTION: 'create_question',
    CANCEL_STUDYING: 'cancel_studying',
    CANCEL_QUESTION: 'cancel_question',
    SET_GOAL: 'set_goal',
    SKIP_GOAL: 'skip_goal',
    CONFIRM_GOAL: 'confirm_goal',
    RETRY_GOAL: 'retry_goal',
    SELECT_DESIGN: 'select_design',
    SHARE_INSTAGRAM: 'share_instagram',
    SHARE_FACEBOOK: 'share_facebook',
    DONT_SHARE: 'dont_share'
};

const SUBJECTS = {
    CC: 'CC 🧪',
    BACTE: 'BACTE 🦠',
    VIRO: 'VIRO 👾',
    MYCO: 'MYCO 🍄',
    PARA: 'PARA 🪱',
    CM: 'CM 🚽💩',
    HISTO: 'HISTO 🧻🗳️',
    MT_LAWS: 'MT Laws ⚖️',
    HEMA: 'HEMA 🩸',
    IS: 'IS ⚛',
    BB: 'BB 🩹',
    MOLBIO: 'MolBio 🧬',
    AUTOPSY: 'Autopsy ☠',
    GENERAL_BOOKS: 'General Books 📚',
    RECALLS: 'RECALLS 🤔💭'
};

module.exports = {
    ACTIONS,
    SUBJECTS
};
