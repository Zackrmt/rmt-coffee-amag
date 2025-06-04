/**
 * index.js
 * Created by: Zackrmt
 * Created at: 2025-06-04 13:36:34 UTC
 */

const TelegramBot = require('node-telegram-bot-api');
const { handleStart, handleCallback, handleMessage } = require('./src/handlers');

// Replace 'YOUR_BOT_TOKEN' with your actual bot token
const token = 'YOUR_BOT_TOKEN';
const bot = new TelegramBot(token, { polling: true });

// Start command
bot.onText(/\/start/, async (msg) => {
    await handleStart(msg, bot);
});

// Handle callback queries
bot.on('callback_query', async (callbackQuery) => {
    await handleCallback(callbackQuery, bot);
});

// Handle messages
bot.on('message', async (msg) => {
    if (msg.text === '/start') return;
    await handleMessage(msg, bot);
});

console.log('Bot is running...');
