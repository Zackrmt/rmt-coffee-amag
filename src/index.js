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

// Handle /start command with inline keyboard buttons
bot.onText(/\/start/, async (msg) => {
    const chatId = msg.chat.id;
    try {
        const options = {
            reply_markup: {
                inline_keyboard: [
                    [
                        { text: '☕ Log Coffee Study', callback_data: 'log_study' },
                        { text: '📊 View Statistics', callback_data: 'view_stats' }
                    ],
                    [
                        { text: '📋 View History', callback_data: 'view_history' },
                        { text: '⚙️ Settings', callback_data: 'settings' }
                    ]
                ]
            }
        };

        await bot.sendMessage(
            chatId, 
            'Welcome to RMT Coffee Study Logger! 👋\n\nWhat would you like to do?',
            options
        );
    } catch (error) {
        console.error('Error sending start message:', error);
    }
});

// Handle callback queries from inline keyboard buttons
bot.on('callback_query', async (callbackQuery) => {
    const chatId = callbackQuery.message.chat.id;
    const action = callbackQuery.data;

    try {
        // Acknowledge the button press
        await bot.answerCallbackQuery(callbackQuery.id);

        switch (action) {
            case 'log_study':
                await bot.sendMessage(chatId, 'Please tell me about your coffee study session:');
                break;
            case 'view_stats':
                await bot.sendMessage(chatId, 'Here are your study statistics:');
                break;
            case 'view_history':
                await bot.sendMessage(chatId, 'Here is your study history:');
                break;
            case 'settings':
                await bot.sendMessage(chatId, 'Settings:');
                break;
        }
    } catch (error) {
        console.error('Error handling callback query:', error);
        await bot.sendMessage(chatId, 'Sorry, there was an error processing your request.');
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
