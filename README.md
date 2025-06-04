# MTLE Study Bot

A Telegram bot for tracking study sessions and creating study questions.

## Features

- Track study sessions with breaks
- Set study goals
- Generate progress images
- Create and share study questions
- Support for multiple subjects

## Setup

1. Clone the repository
```bash
git clone https://github.com/Zackrmt/rmt-coffee-amag.git
cd rmt-coffee-amag
```

2. Create and activate virtual environment
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies
```bash
pip install -r requirements.txt
```

4. Set up environment variables
- Create a `.env` file
- Add your Telegram bot token: `TELEGRAM_BOT_TOKEN=your_bot_token_here`

5. Add required fonts
- Download Poppins font files (Bold, Light, SemiBold)
- Place them in the project root directory

6. Run the bot
```bash
python bot.py
```

## Usage

1. Start the bot with `/start`
2. Choose to start studying or create questions
3. Follow the prompts to:
   - Set study goals
   - Track study sessions
   - Create study questions
   - Review and answer questions

## Contributing

Feel free to submit issues and enhancement requests!
