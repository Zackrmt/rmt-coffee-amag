const TelegramBot = require('node-telegram-bot-api');
const moment = require('moment');
const { createCanvas } = require('canvas');
const http = require('http');

// Replace 'YOUR_BOT_TOKEN' with your actual bot token
const token = process.env.BOT_TOKEN;
const bot = new TelegramBot(token, {polling: true});

// Create a basic HTTP server
const server = http.createServer((req, res) => {
    res.writeHead(200, { 'Content-Type': 'text/plain' });
    res.end('Bot is running!');
});

// Get port from environment variable or default to 3000
const port = process.env.PORT || 3000;
server.listen(port, () => {
    console.log(`Server is running on port ${port}`);
});

bot.on('message', (msg) => {
    // Your bot logic here
});

console.log('Bot is running...');
