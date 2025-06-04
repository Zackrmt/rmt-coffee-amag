/**
 * sessionManager.js
 * Created by: Zackrmt
 * Created at: 2025-06-04 13:41:41 UTC
 */

const moment = require('moment');

class SessionManager {
    constructor() {
        this.activeSessions = new Map();
        this.lastMenuMessage = null;
        this.lastSubjectMessage = null;
        this.sessionMessages = new Map(); // Store messages that need to be deleted on new session
        this.temporaryMessages = new Map(); // Store temporary messages for cleanup
    }

    startSession(userId, subject, goalTimeMinutes = 0) {
        // Clean up any messages from previous session
        this.clearSessionMessages(userId);

        this.activeSessions.set(userId, {
            subject,
            status: 'studying',
            startTime: moment(),
            goalTimeMinutes,
            breaks: [],
            currentBreak: null,
            totalBreakMinutes: 0,
            messages: [] // Messages to clean up on next session
        });
    }

    endSession(userId) {
        const session = this.activeSessions.get(userId);
        if (session) {
            const endTime = moment();
            const totalStudyMinutes = this.calculateStudyTime(session, endTime);
            const stats = {
                subject: session.subject,
                goalTime: session.goalTimeMinutes,
                actualTime: totalStudyMinutes,
                breakTime: session.totalBreakMinutes,
                totalTime: totalStudyMinutes + session.totalBreakMinutes,
                startTime: session.startTime,
                endTime,
                percentage: session.goalTimeMinutes ? 
                    Math.round((totalStudyMinutes / session.goalTimeMinutes) * 100) : 100
            };
            this.activeSessions.delete(userId);
            return stats;
        }
        return null;
    }

    startBreak(userId) {
        const session = this.activeSessions.get(userId);
        if (session && session.status === 'studying') {
            session.status = 'break';
            session.currentBreak = moment();
            this.activeSessions.set(userId, session);
        }
    }

    endBreak(userId) {
        const session = this.activeSessions.get(userId);
        if (session && session.status === 'break' && session.currentBreak) {
            const breakEnd = moment();
            const breakMinutes = breakEnd.diff(session.currentBreak, 'minutes');
            session.totalBreakMinutes += breakMinutes;
            session.breaks.push({
                start: session.currentBreak,
                end: breakEnd,
                duration: breakMinutes
            });
            session.currentBreak = null;
            session.status = 'studying';
            this.activeSessions.set(userId, session);
        }
    }

    calculateStudyTime(session, endTime) {
        const totalMinutes = endTime.diff(session.startTime, 'minutes');
        return totalMinutes - session.totalBreakMinutes;
    }

    getSession(userId) {
        return this.activeSessions.get(userId);
    }

    updateSessionStatus(userId, status) {
        const session = this.activeSessions.get(userId);
        if (session) {
            session.status = status;
            this.activeSessions.set(userId, session);
        }
    }

    setGoalTime(userId, minutes) {
        const session = this.activeSessions.get(userId);
        if (session) {
            session.goalTimeMinutes = minutes;
            this.activeSessions.set(userId, session);
        }
    }

    addSessionMessage(userId, messageId) {
        const messages = this.sessionMessages.get(userId) || [];
        messages.push(messageId);
        this.sessionMessages.set(userId, messages);
    }

    getSessionMessages(userId) {
        return this.sessionMessages.get(userId) || [];
    }

    clearSessionMessages(userId) {
        this.sessionMessages.delete(userId);
    }

    addTemporaryMessage(userId, messageId) {
        const messages = this.temporaryMessages.get(userId) || [];
        messages.push(messageId);
        this.temporaryMessages.set(userId, messages);
    }

    getTemporaryMessages(userId) {
        return this.temporaryMessages.get(userId) || [];
    }

    clearTemporaryMessages(userId) {
        this.temporaryMessages.delete(userId);
    }

    formatTime(minutes) {
        const hours = Math.floor(minutes / 60);
        const mins = minutes % 60;
        return `${hours}:${mins.toString().padStart(2, '0')}`;
    }

    getBreakCount(userId) {
        const session = this.activeSessions.get(userId);
        return session ? session.breaks.length : 0;
    }

    getCurrentStats(userId) {
        const session = this.activeSessions.get(userId);
        if (!session) return null;

        const currentTime = moment();
        const totalStudyMinutes = this.calculateStudyTime(session, currentTime);

        return {
            subject: session.subject,
            goalTime: session.goalTimeMinutes,
            actualTime: totalStudyMinutes,
            breakTime: session.totalBreakMinutes,
            totalTime: totalStudyMinutes + session.totalBreakMinutes,
            startTime: session.startTime,
            currentTime,
            breakCount: session.breaks.length,
            percentage: session.goalTimeMinutes ? 
                Math.round((totalStudyMinutes / session.goalTimeMinutes) * 100) : 100
        };
    }
}

module.exports = new SessionManager();
