require('dotenv').config();
const TelegramBot = require('node-telegram-bot-api');
const { handleStart, handleCallback, handleMessage } = require('./handlers');

// Create a bot instance
const bot = new TelegramBot(process.env.BOT_TOKEN, { polling: true });

// Handle /start command
bot.onText(/\/start/, (msg) => handleStart(msg, bot));

// Handle callback queries (button clicks)
bot.on('callback_query', (callbackQuery) => handleCallback(callbackQuery, bot));

// Handle regular messages
bot.on('message', (msg) => handleMessage(msg, bot));

// Error handling
bot.on('polling_error', (error) => {
    console.error(error);
});

console.log('Bot is running...');
