require('dotenv').config();
const TelegramBot = require('node-telegram-bot-api');
const { handleStart, handleCallback, handleMessage } = require('./handlers');

let bot;

// Different configurations for production and development
if (process.env.NODE_ENV === 'production') {
    // Production - use webhooks
    bot = new TelegramBot(process.env.BOT_TOKEN, {
        webHook: {
            port: process.env.PORT || 8443
        }
    });
    // This URL must be from your Render deployment
    bot.setWebHook(`${process.env.APP_URL}/bot${process.env.BOT_TOKEN}`);
} else {
    // Development - use long polling
    bot = new TelegramBot(process.env.BOT_TOKEN, {
        polling: {
            autoStart: true,
            params: {
                timeout: 10,
                limit: 100,
                allowed_updates: ['message', 'callback_query']
            }
        }
    });
    bot.deleteWebHook();
}

// Handle /start command
bot.onText(/\/start/, (msg) => handleStart(msg, bot));

// Handle callback queries (button clicks)
bot.on('callback_query', (callbackQuery) => handleCallback(callbackQuery, bot));

// Handle regular messages
bot.on('message', (msg) => handleMessage(msg, bot));

// Error handling with reconnection logic
bot.on('polling_error', (error) => {
    console.error('Polling error:', error);
    if (error.code === 'ETELEGRAM' && error.response.statusCode === 409) {
        console.log('Conflict with another instance, retrying in 10 seconds...');
        setTimeout(() => {
            try {
                bot.startPolling();
            } catch (e) {
                console.error('Failed to restart polling:', e);
            }
        }, 10000);
    }
});

bot.on('webhook_error', (error) => {
    console.error('Webhook error:', error);
});

console.log(`Bot is running in ${process.env.NODE_ENV || 'development'} mode...`);

// Handle process termination
process.on('SIGINT', () => {
    bot.closeWebHook();
    process.exit(0);
});

process.on('SIGTERM', () => {
    bot.closeWebHook();
    process.exit(0);
});
