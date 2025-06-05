from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

# System Configuration
SYSTEM_CONFIG = {
    'VERSION': '2.0.0',
    'TIMESTAMP': "2025-06-05 06:15:05",  # Current timestamp
    'TIMEZONE': 'UTC',
    'ENVIRONMENT': 'production'
}

# Branding Configuration
BRANDING_CONFIG = {
    'TITLE': 'MTLE 2025',
    'CREATOR': 'Created by Eli'
}

# Bot Configuration
BOT_CONFIG = {
    'TOKEN': os.getenv('BOT_TOKEN'),
    'ADMINS': os.getenv('ADMIN_IDS', '').split(','),
    'DEBUG_MODE': os.getenv('DEBUG_MODE', 'False').lower() == 'true'
}

# Database Configuration
DB_CONFIG = {
    'URL': os.getenv('DATABASE_URL', 'sqlite:///study_bot.db'),
    'DEBUG': os.getenv('DB_DEBUG', 'False').lower() == 'true'
}

# Study Session Configuration
STUDY_CONFIG = {
    'MIN_SESSION_LENGTH': 15,  # minutes
    'MAX_BREAK_LENGTH': 30,    # minutes
    'DEFAULT_DAILY_GOAL': 6    # hours
}

# Dashboard Configuration
DASHBOARD_CONFIG = {
    'WIDTH': 800,
    'HEIGHT': 600,
    'COLORS': {
        'BACKGROUND': 'white',
        'PRIMARY': '#4CAF50',
        'SECONDARY': '#FFA726',
        'TEXT': '#333333'
    }
}
