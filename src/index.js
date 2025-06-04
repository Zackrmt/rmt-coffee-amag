const TelegramBot = require('node-telegram-bot-api');
const moment = require('moment');
const { createCanvas } = require('canvas');
const http = require('http');

// Replace 'YOUR_BOT_TOKEN' with your actual bot token
const token = process.env.BOT_TOKEN;

// Add webhooks configuration for production
const url = process.env.RENDER_EXTERNAL_URL || 'https://your-app-name.onrender.com';
const options = {
    webHook: {
        port: process.env.PORT || 8443
    }
};

// Create bot instance with webhook in production, polling in development
const bot = process.env.NODE_ENV === 'production' 
    ? new TelegramBot(token, options)
    : new TelegramBot(token, { polling: true });

// Set webhook if in production
if (process.env.NODE_ENV === 'production') {
    bot.setWebHook(`${url}/bot${token}`);
}

// Error handling
bot.on('polling_error', (error) => {
    console.log('Polling error:', error.message);
});

bot.on('webhook_error', (error) => {
    console.log('Webhook error:', error.message);
});

bot.on('error', (error) => {
    console.log('General error:', error.message);
});

// Handle /start command
bot.onText(/\/start/, async (msg) => {
    const chatId = msg.chat.id;
    try {
        await bot.sendMessage(chatId, 'Welcome to RMT Coffee Study Logger! 👋');
    } catch (error) {
        console.error('Error sending start message:', error);
    }
});

// Your existing message handler
bot.on('message', (msg) => {
    if (msg.text !== '/start') {
        // Your bot logic here
        console.log('Received message:', msg.text);
    }
});

// Create a basic HTTP server for health checks
const server = http.createServer((req, res) => {
    res.writeHead(200, { 'Content-Type': 'text/plain' });
    res.end('Bot is running!');
});

// Only start separate HTTP server if not using webhooks
if (!process.env.NODE_ENV === 'production') {
    const port = process.env.PORT || 3000;
    server.listen(port, () => {
        console.log(`Server is running on port ${port}`);
    });
}

console.log('Bot is running...');
console.log('Environment:', process.env.NODE_ENV || 'development');
