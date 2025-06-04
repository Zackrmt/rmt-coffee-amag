import os
import logging
from telegram.ext import Application, ContextTypes
from config.constants import STARTUP_TIME, CURRENT_USER
from handlers import setup_handlers
from healthcheck import start_health_server

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors caused by Updates."""
    logger.error("Exception while handling an update:", exc_info=context.error)

def main():
    """Start the bot."""
    # Add startup logging
    logger.info(f"Bot starting at {STARTUP_TIME} UTC")
    logger.info(f"Started by user: {CURRENT_USER}")
    logger.info("Initializing bot application...")
    
    # Health check server setup
    try:
        start_health_server()
        logger.info("Health check server started successfully")
    except Exception as e:
        logger.error(f"Error starting health check server: {str(e)}")

    # Create the Application and pass it your bot's token.
    application = Application.builder().token(os.environ["TELEGRAM_TOKEN"]).build()
    
    # Setup all handlers
    setup_handlers(application)
    
    # Add error handler
    application.add_error_handler(error_handler)

    # Start the Bot
    logger.info("Starting bot polling...")
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
        logger.info("Bot polling started successfully")
    except Exception as e:
        logger.error(f"Error starting bot: {str(e)}")
        raise

if __name__ == '__main__':
    main()
