const TelegramBot = require('node-telegram-bot-api');
const moment = require('moment');
const { createCanvas } = require('canvas');

// Replace 'YOUR_BOT_TOKEN' with your actual bot token
const token = process.env.BOT_TOKEN;
const bot = new TelegramBot(token, {polling: true});

bot.on('message', (msg) => {
    // Your bot logic here
});

console.log('Bot is running...');
