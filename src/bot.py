import os
import sys
import logging
import asyncio
import datetime
import threading
import time
import signal
import atexit
import json
import io
import re
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, Optional, Set, List, Any
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
    ApplicationBuilder,
    PersistenceInput,
    PicklePersistence
)
from telegram.error import Conflict

# For PDF generation
from reportlab.lib.pagesizes import A4, A5, A6
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.lib.units import inch, cm

# For Google Drive API
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log')
    ]
)
logger = logging.getLogger(__name__)

# Reduce HTTP request logging verbosity
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telegram.request').setLevel(logging.WARNING)

# Timezone configurations
PST_TZ = pytz.timezone('America/Los_Angeles')
MANILA_TZ = pytz.timezone('Asia/Manila')

# Current date and user information
CURRENT_DATE = datetime.datetime.now().strftime("%Y-%m-%d")
CURRENT_USER = "Zackrmt"

# Process ID file for single instance check
PID_FILE = "/tmp/rmt_study_bot.pid"

# Persistence path
PERSISTENCE_PATH = "/tmp/rmt_study_bot.pickle"

# Google Drive API Constants
CREDENTIALS_FILE = "credentials.json"
SCOPES = ['https://www.googleapis.com/auth/drive']
DATABASE_FOLDER_NAME = "RMT_Study_Bot_Database"

# Shared state
class SharedState:
    def __init__(self):
        self.is_shutting_down = False
        self.telegram_bot = None

# Create shared state object
shared_state = SharedState()

# Conversation states
(
    CHOOSING_MAIN_MENU,
    SETTING_GOAL,
    CHOOSING_SUBJECT,
    STUDYING,
    ON_BREAK,
    SETTING_CUSTOM_GOAL,
    CONFIRMING_CANCEL,
) = range(7)

# Subject mapping
SUBJECTS = {
    "CC 🧪": "CC",
    "BACTE 🦠": "BACTE",
    "VIRO 👾": "VIRO",
    "MYCO 🍄": "MYCO",
    "PARA 🪱": "PARA",
    "CM 🚽💩": "CM",
    "HISTO 🧻🗳️": "HISTO",
    "MT Laws ⚖️": "MT_LAWS",
    "HEMA 🩸": "HEMA",
    "IS ⚛": "IS",
    "BB 🩹": "BB",
    "MolBio 🧬": "MOLBIO",
    "Autopsy ☠": "AUTOPSY",
    "General Books 📚": "GB",
    "RECALLS 🤔💭": "RECALLS",
    "ANKI 🎟️": "ANKI",
    "Others🤓": "OTHERS"
}

# Attempt to create credentials file placeholder if it doesn't exist
if not os.path.exists(CREDENTIALS_FILE):
    try:
        # Create a directory for the file if it doesn't exist
        os.makedirs(os.path.dirname(CREDENTIALS_FILE), exist_ok=True)
        # Inform user about missing credentials
        logger.warning(f"Google Drive credentials file {CREDENTIALS_FILE} not found.")
    except Exception as e:
        logger.error(f"Failed to create credentials directory: {e}")

# ================== GOOGLE DRIVE DATABASE ==================
class GoogleDriveDB:
    def __init__(self):
        self.drive_service = None
        self.database_folder_id = None
        self.initialized = False
        self.local_backup = {}  # For fallback when Google Drive is unavailable
        
    def initialize(self):
        """Initialize Google Drive API client with retries."""
        max_retries = 3
        retry_delay = 5  # seconds
        
        for attempt in range(max_retries):
            try:
                if not os.path.exists(CREDENTIALS_FILE):
                    logger.warning(f"Credentials file {CREDENTIALS_FILE} not found. Running with local storage only.")
                    return False
                    
                credentials = service_account.Credentials.from_service_account_file(
                    CREDENTIALS_FILE, scopes=SCOPES)
                self.drive_service = build('drive', 'v3', credentials=credentials)
                
                # Create or find the database folder
                self.database_folder_id = self._get_or_create_folder(DATABASE_FOLDER_NAME)
                
                self.initialized = True
                logger.info("Google Drive database initialized successfully")
                return True
                
            except Exception as e:
                logger.error(f"Drive initialization attempt {attempt+1} failed: {e}")
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # exponential backoff
                else:
                    logger.error("All Google Drive initialization attempts failed")
                    return False
            
    def _get_or_create_folder(self, folder_name):
        """Get or create a folder in Google Drive."""
        # Check if folder already exists
        query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        results = self.drive_service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
        folders = results.get('files', [])
        
        # Return existing folder if found
        if folders:
            logger.info(f"Found existing folder: {folder_name}")
            return folders[0]['id']
        
        # Create new folder
        folder_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        folder = self.drive_service.files().create(
            body=folder_metadata, fields='id').execute()
        logger.info(f"Created new folder: {folder_name}")
        return folder.get('id')
        
    def save_user_data(self, user_id, data):
        """Save user data to Google Drive."""
        if not self.initialized:
            if not self.initialize():
                # Store in local backup
                self.local_backup[user_id] = data
                logger.warning(f"Saved data for user {user_id} to local backup only")
                return True
                
        try:
            # Convert data to JSON string
            json_data = json.dumps(data, default=self._json_serializer)
            
            # Check if file already exists
            file_name = f"user_{user_id}_data.json"
            file_id = self._get_file_id(file_name)
            
            # Create file media
            media = MediaIoBaseUpload(
                io.BytesIO(json_data.encode()),
                mimetype='application/json',
                resumable=True
            )
            
            if file_id:
                # Update existing file
                self.drive_service.files().update(
                    fileId=file_id,
                    media_body=media
                ).execute()
                logger.info(f"Updated data for user {user_id}")
            else:
                # Create new file
                file_metadata = {
                    'name': file_name,
                    'parents': [self.database_folder_id]
                }
                self.drive_service.files().create(
                    body=file_metadata,
                    media_body=media,
                    fields='id'
                ).execute()
                logger.info(f"Created new data file for user {user_id}")
                
            # Also update local backup
            self.local_backup[user_id] = data
            return True
        except Exception as e:
            logger.error(f"Error saving user data to Drive: {e}")
            # Store in local backup
            self.local_backup[user_id] = data
            logger.warning(f"Saved data for user {user_id} to local backup only")
            return True  # Return True since we saved to local backup
            
    def load_user_data(self, user_id):
        """Load user data from Google Drive or local backup."""
        # Try to load from local backup first for speed
        if user_id in self.local_backup:
            logger.info(f"Loaded data for user {user_id} from local backup")
            return self.local_backup[user_id]
            
        # Try to load from Google Drive
        if not self.initialized:
            if not self.initialize():
                return None
                
        try:
            file_name = f"user_{user_id}_data.json"
            file_id = self._get_file_id(file_name)
            
            if not file_id:
                logger.info(f"No data found for user {user_id}")
                return None
                
            # Get file content
            file_content = self.drive_service.files().get_media(fileId=file_id).execute()
            
            # Parse JSON
            if isinstance(file_content, bytes):
                data = json.loads(file_content.decode())
            else:
                data = json.loads(file_content)
                
            logger.info(f"Loaded data for user {user_id} from Google Drive")
            
            # Update local backup
            self.local_backup[user_id] = data
            return data
        except Exception as e:
            logger.error(f"Error loading user data from Drive: {e}")
            return None
            
    def _get_file_id(self, file_name):
        """Get file ID by name."""
        query = f"name='{file_name}' and '{self.database_folder_id}' in parents and trashed=false"
        results = self.drive_service.files().list(
            q=query, spaces='drive', fields='files(id, name)').execute()
        files = results.get('files', [])
        
        if files:
            return files[0]['id']
        return None
        
    def _json_serializer(self, obj):
        """Custom JSON serializer for objects not serializable by default json code."""
        if isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()
        if hasattr(obj, '__dict__'):
            return obj.__dict__
        raise TypeError(f"Type {type(obj)} not serializable")

    def save_study_session(self, user_id, user_name, study_session):
        """Save study session to the user's session history."""
        try:
            # Convert StudySession to serializable dict
            session_dict = {
                'user_id': study_session.user_id,
                'subject': study_session.subject,
                'goal_time': study_session.goal_time,
                'start_time': study_session.start_time.isoformat(),
                'end_time': study_session.end_time.isoformat() if study_session.end_time else None,
                'break_periods': [
                    {
                        'start': period['start'].isoformat(),
                        'end': period['end'].isoformat()
                    } 
                    for period in study_session.break_periods
                ],
                'total_study_time': study_session.get_total_study_time().total_seconds(),
                'total_break_time': study_session.get_total_break_time().total_seconds(),
                'study_break_ratio': study_session.get_study_break_ratio(),
                'progress_percentage': study_session.get_progress_percentage()
            }
            
            # Get existing data or create new
            data = self.load_user_data(user_id) or {'user_name': user_name, 'sessions': []}
            
            # Add to sessions list
            data['sessions'].append(session_dict)
            
            # Save back to Drive or local backup
            return self.save_user_data(user_id, data)
            
        except Exception as e:
            logger.error(f"Error saving study session: {e}")
            return False

    def get_user_study_sessions(self, user_id):
        """Get all study sessions for a user."""
        try:
            data = self.load_user_data(user_id)
            if not data or 'sessions' not in data:
                logger.info(f"No sessions found for user {user_id}")
                return []
                
            sessions = data['sessions']
            logger.info(f"Loaded {len(sessions)} raw sessions for user {user_id}")
            
            # Convert ISO dates to datetime objects
            for session in sessions:
                try:
                    # Check if start_time is already a datetime object
                    if isinstance(session['start_time'], str):
                        session['start_time'] = datetime.datetime.fromisoformat(session['start_time'])
                    
                    # Check if end_time exists and is a string
                    if session['end_time'] and isinstance(session['end_time'], str):
                        session['end_time'] = datetime.datetime.fromisoformat(session['end_time'])
                    
                    # Process break periods only if they exist and are in string format
                    for break_period in session.get('break_periods', []):
                        if isinstance(break_period.get('start'), str):
                            break_period['start'] = datetime.datetime.fromisoformat(break_period['start'])
                        if isinstance(break_period.get('end'), str):
                            break_period['end'] = datetime.datetime.fromisoformat(break_period['end'])
                except Exception as e:
                    logger.error(f"Error parsing session dates: {e}")
                    logger.error(f"Problematic session data: {session}")
                    
            logger.info(f"Successfully processed {len(sessions)} sessions for user {user_id}")
            return sessions
        except Exception as e:
            logger.error(f"Error getting user study sessions: {e}")
            return []

    def get_sessions_for_date(self, user_id, date):
        """Get study sessions for a specific date."""
        all_sessions = self.get_user_study_sessions(user_id)
        
        # Debug logging
        logger.info(f"Looking for sessions on date: {date} for user {user_id}")
        logger.info(f"Total sessions found: {len(all_sessions)}")
        
        # Filter sessions for the specific date
        date_sessions = []
        for session in all_sessions:
            try:
                # Handle case where start_time might not be a datetime object yet
                if isinstance(session['start_time'], str):
                    session['start_time'] = datetime.datetime.fromisoformat(session['start_time'])
                    
                # Convert to Manila timezone for comparison
                manila_time = session['start_time'].astimezone(MANILA_TZ)
                session_date = manila_time.date()
                
                logger.info(f"Session date: {session_date}, comparing with: {date}")
                
                if session_date == date:
                    date_sessions.append(session)
                    logger.info(f"Match found for session starting at {manila_time}")
            except Exception as e:
                logger.error(f"Error processing session during date filtering: {e}")
                # Log the session data for debugging
                logger.error(f"Problematic session data: {session}")
        
        logger.info(f"Found {len(date_sessions)} sessions for date {date}")
        return date_sessions
    
# ================== PDF REPORT GENERATOR ==================
class PDFReportGenerator:
    def __init__(self):
        self.styles = getSampleStyleSheet()
        
        # Define pastel color palette
        self.pastel_colors = {
            'primary': colors.Color(0.6, 0.8, 0.9),        # Pastel blue
            'secondary': colors.Color(0.9, 0.8, 0.6),      # Pastel orange/tan
            'accent1': colors.Color(0.8, 0.9, 0.8),        # Pastel green
            'accent2': colors.Color(0.9, 0.8, 0.9),        # Pastel purple
            'accent3': colors.Color(0.9, 0.9, 0.7),        # Pastel yellow
            'accent4': colors.Color(0.8, 0.7, 0.9),        # Pastel lavender
            'accent5': colors.Color(0.7, 0.9, 0.9),        # Pastel cyan
            'text': colors.Color(0.2, 0.3, 0.4),           # Dark blue-gray
            'contrast': colors.Color(0.95, 0.95, 0.95),    # Light gray
            'chart1': colors.Color(0.7, 0.8, 0.9),         # Light blue
            'chart2': colors.Color(0.9, 0.7, 0.7)          # Light pink
        }
        
        # Create custom styles with professional appearance and UNIQUE names
        self.styles.add(ParagraphStyle(
            name='RMT_ReportTitle',
            parent=self.styles['Heading1'],
            fontSize=16,
            alignment=1,  # Center
            spaceAfter=12,
            fontName='Helvetica-Bold',
            textColor=self.pastel_colors['text']
        ))
        
        self.styles.add(ParagraphStyle(
            name='RMT_ReportSubtitle',
            parent=self.styles['Heading2'],
            fontSize=14,
            alignment=1,
            spaceAfter=10,
            fontName='Helvetica-Bold',
            textColor=self.pastel_colors['text']
        ))
        
        self.styles.add(ParagraphStyle(
            name='RMT_BodyText',
            parent=self.styles['Normal'],
            fontSize=10,
            spaceAfter=8,
            leading=14,  # Better line spacing
            fontName='Helvetica'
        ))
        
        self.styles.add(ParagraphStyle(
            name='RMT_SmallText',
            parent=self.styles['Normal'],
            fontSize=8,
            spaceAfter=6,
            leading=10,
            fontName='Helvetica'
        ))
        
        self.styles.add(ParagraphStyle(
            name='RMT_Footer',
            parent=self.styles['Normal'],
            fontSize=8,
            alignment=1,  # Center
            textColor=colors.gray
        ))
        
        self.styles.add(ParagraphStyle(
            name='RMT_TableHeader',
            parent=self.styles['Normal'],
            fontSize=10,
            alignment=1,
            textColor=colors.white,
            backColor=self.pastel_colors['primary'],
            fontName='Helvetica-Bold'
        ))
        
        self.styles.add(ParagraphStyle(
            name='RMT_SectionHeader',
            parent=self.styles['Heading3'],
            fontSize=12,
            fontName='Helvetica-Bold',
            textColor=self.pastel_colors['text'],
            spaceAfter=6,
            spaceBefore=12
        ))
    
    def _remove_emojis(self, subject):
        """Remove emojis from subject names."""
        # Remove anything that looks like an emoji (characters between spaces and non-alphanumeric)
        import re
        # Find emoji-like patterns (non-alphanumeric characters at the end)
        clean_subject = re.sub(r'\s+[^\w\s]+$', '', subject)
        # Also clean any at the beginning
        clean_subject = re.sub(r'^[^\w\s]+\s+', '', clean_subject)
        return clean_subject.strip()
        
    def _format_time(self, seconds):
        """Format seconds into hours and minutes."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"
        
    def _rgb_to_hex(self, rgb_color):
        """Convert RGB color object to hex string for HTML."""
        r = int(rgb_color.red * 255)
        g = int(rgb_color.green * 255)
        b = int(rgb_color.blue * 255)
        return f"#{r:02x}{g:02x}{b:02x}"
        
    def generate_session_report(self, user_name, session):
        """Generate a PDF report for a single study session."""
        buffer = io.BytesIO()
        # Use A6 instead of A7 for better readability
        doc = SimpleDocTemplate(buffer, pagesize=A6)
        story = []
        
        # Clean subject name by removing emojis
        clean_subject = self._remove_emojis(session['subject'])
        
        # Title
        title = Paragraph(f"Study Session Report", self.styles['RMT_ReportTitle'])
        story.append(title)
        
        # User - reduce spacing after user subtitle
        user_subtitle = Paragraph(f"{user_name}, RMT", self.styles['RMT_ReportSubtitle'])
        story.append(user_subtitle)
        story.append(Spacer(1, 0.1*inch))  # REDUCED from 0.2*inch
        
        # Session details
        subject = Paragraph(f"Subject: {clean_subject}", self.styles['RMT_BodyText'])
        story.append(subject)
        
        # Format times for display
        start_time = session['start_time'].astimezone(MANILA_TZ).strftime('%Y-%m-%d %I:%M %p')
        end_time = session['end_time'].astimezone(MANILA_TZ).strftime('%I:%M %p') if session['end_time'] else "Ongoing"
        
        times = Paragraph(f"Started: {start_time}<br/>Ended: {end_time}", self.styles['RMT_BodyText'])
        story.append(times)
        
        # Key statistics - removed spacer before stats table
        stats_data = [
            ['Metric', 'Value'],
            ['Study Time', self._format_time(session['total_study_time'])],
            ['Break Time', self._format_time(session['total_break_time'])]
        ]
        
        if 'goal_time' in session and session['goal_time']:
            stats_data.append(['Goal Progress', f"{session['progress_percentage']}%"])
        
        stats_table = Table(stats_data, colWidths=[1.5*inch, 1.5*inch])
        stats_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), self.pastel_colors['primary']),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),  # REDUCED padding
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BOX', (0, 0), (-1, -1), 1, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        story.append(stats_table)
        
        # Break details if any - reduced spacing before break details
        if session['break_periods']:
            story.append(Spacer(1, 0.15*inch))  # REDUCED from 0.3*inch
            breaks_title = Paragraph("Break Details:", self.styles['RMT_SectionHeader'])
            story.append(breaks_title)
            
            break_data = [['#', 'Start', 'End', 'Duration']]
            
            for i, break_period in enumerate(session['break_periods']):
                break_start = break_period['start'].astimezone(MANILA_TZ).strftime('%I:%M %p')
                break_end = break_period['end'].astimezone(MANILA_TZ).strftime('%I:%M %p')
                duration = (break_period['end'] - break_period['start']).total_seconds()
                duration_str = f"{int(duration // 60)}m {int(duration % 60)}s"
                
                break_data.append([f"{i+1}", break_start, break_end, duration_str])
            
            break_table = Table(break_data, colWidths=[0.3*inch, 1.0*inch, 1.0*inch, 0.7*inch])
            break_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), self.pastel_colors['primary']),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 6),  # REDUCED padding
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('BOX', (0, 0), (-1, -1), 1, colors.black),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            story.append(break_table)
        
        # Add productivity chart if session has ended - reduced spacing and adjusted chart size
        if session['end_time']:
            study_time = session['total_study_time']
            break_time = session['total_break_time']
            
            if study_time > 0 or break_time > 0:  # Avoid division by zero
                story.append(Spacer(1, 0.15*inch))  # REDUCED from 0.3*inch
                chart_title = Paragraph("Time Distribution", self.styles['RMT_SectionHeader'])
                story.append(chart_title)
                
                # Create pie chart for study vs break time - ADJUSTED size and positioning
                drawing = Drawing(3*inch, 1.5*inch)  # REDUCED height from 1.8*inch
                pie = Pie()
                pie.x = 0.75*inch  # Center horizontally 
                pie.y = 0.15*inch  # ADJUSTED y position higher
                pie.width = 1.3*inch  # REDUCED from 1.5*inch
                pie.height = 1.3*inch  # REDUCED from 1.5*inch
                
                pie.data = [study_time, break_time]
                pie.labels = ['Study', 'Break']
                pie.slices.strokeWidth = 0.5
                pie.slices[0].fillColor = self.pastel_colors['chart1']
                pie.slices[1].fillColor = self.pastel_colors['chart2']
                drawing.add(pie)
                story.append(drawing)
                
                # Add legend with pastel colors - no extra spacing after
                legend = Paragraph(
                    f"<font color='{self._rgb_to_hex(self.pastel_colors['chart1'])}'>■</font> Study: {self._format_time(study_time)} ({100*study_time/(study_time+break_time):.1f}%)<br/>"
                    f"<font color='{self._rgb_to_hex(self.pastel_colors['chart2'])}'>■</font> Break: {self._format_time(break_time)} ({100*break_time/(study_time+break_time):.1f}%)",
                    self.styles['RMT_SmallText']
                )
                story.append(legend)
                # Removed extra spacing here
        
        # Add creator footer - reduced spacing before footer
        story.append(Spacer(1, 0.15*inch))  # REDUCED from 0.3*inch
        footer = Paragraph("Study tracker created by Eli.", self.styles['RMT_Footer'])
        story.append(footer)
        
        # Build PDF
        doc.build(story)
        buffer.seek(0)
        return buffer
        
    def generate_daily_report(self, user_name, date, sessions):
        """Generate a PDF report for a specific day."""
        buffer = io.BytesIO()
        # Use A5 instead of A7 for better readability
        doc = SimpleDocTemplate(buffer, pagesize=A5)
        story = []
        
        # Title
        title = Paragraph(f"Daily Study Report", self.styles['RMT_ReportTitle'])
        story.append(title)
        
        # User and Date
        user_date = Paragraph(f"{user_name}, RMT<br/>{date.strftime('%Y-%m-%d')}", self.styles['RMT_ReportSubtitle'])
        story.append(user_date)
        story.append(Spacer(1, 0.3*inch))
        
        if not sessions:
            no_data = Paragraph("No study sessions recorded for this date.", self.styles['RMT_BodyText'])
            story.append(no_data)
        else:
            # Clean subject names by removing emojis
            for session in sessions:
                session['subject'] = self._remove_emojis(session['subject'])
                
            # Summary statistics
            total_study_time = sum(session['total_study_time'] for session in sessions)
            total_break_time = sum(session['total_break_time'] for session in sessions)
            
            stats_title = Paragraph("Summary Statistics", self.styles['RMT_SectionHeader'])
            story.append(stats_title)
            
            stats_data = [
                ['Metric', 'Value'],
                ['Total Study Time', self._format_time(total_study_time)],
                ['Total Break Time', self._format_time(total_break_time)],
                ['Total Sessions', str(len(sessions))]
            ]
            
            ratio = "N/A"
            if total_break_time > 0:
                study_minutes = int(total_study_time / 60)
                break_minutes = int(total_break_time / 60)
                
                def gcd(a, b):
                    while b:
                        a, b = b, a % b
                    return a
                
                divisor = gcd(study_minutes, break_minutes)
                if divisor > 0:
                    ratio = f"{study_minutes//divisor}:{break_minutes//divisor}"
            
            stats_data.append(['Study:Break Ratio', ratio])
            
            stats_table = Table(stats_data, colWidths=[2*inch, 2*inch])
            stats_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), self.pastel_colors['primary']),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('BOX', (0, 0), (-1, -1), 1, colors.black),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            story.append(stats_table)
            story.append(Spacer(1, 0.3*inch))
            
            # Time distribution chart
            chart_title = Paragraph("Time Distribution", self.styles['RMT_SectionHeader'])
            story.append(chart_title)
            
            if total_study_time > 0 or total_break_time > 0:
                # Add page break to put chart on a new page
                story.append(PageBreak())
                # Re-add the chart title on the new page
                chart_title = Paragraph("Time Distribution", self.styles['RMT_SectionHeader'])
                story.append(chart_title)
                
                drawing = Drawing(4*inch, 2.5*inch)  # Increased height
                pie = Pie()
                pie.x = 2*inch
                pie.y = 1.25*inch  # Adjusted y position
                pie.width = 2*inch
                pie.height = 2*inch
                pie.data = [total_study_time, total_break_time]
                pie.labels = ['Study', 'Break']
                pie.slices.strokeWidth = 0.5
                pie.slices[0].fillColor = self.pastel_colors['chart1']
                pie.slices[1].fillColor = self.pastel_colors['chart2']
                drawing.add(pie)
                story.append(drawing)
                
                # Add legend with pastel colors
                total_time = total_study_time + total_break_time
                if total_time > 0:
                    legend = Paragraph(
                        f"<font color='{self._rgb_to_hex(self.pastel_colors['chart1'])}'>■</font> Study: {self._format_time(total_study_time)} ({100*total_study_time/total_time:.1f}%)<br/>"
                        f"<font color='{self._rgb_to_hex(self.pastel_colors['chart2'])}'>■</font> Break: {self._format_time(total_break_time)} ({100*total_break_time/total_time:.1f}%)",
                        self.styles['RMT_BodyText']
                    )
                    story.append(legend)
                    
                # Add extra spacing after the chart
                story.append(Spacer(1, 0.5*inch))  # Increased spacing
            
            # Subject breakdown - put on a new page
            story.append(PageBreak())
            subject_title = Paragraph("Subject Breakdown", self.styles['RMT_SectionHeader'])
            story.append(subject_title)
            
            # Group sessions by subject
            sessions_by_subject = {}
            for session in sessions:
                subject = session['subject']
                if subject not in sessions_by_subject:
                    sessions_by_subject[subject] = 0
                sessions_by_subject[subject] += session['total_study_time']
            
            if sessions_by_subject:
                subject_data = [['Subject', 'Time', 'Percentage']]
                
                for subject, time in sorted(sessions_by_subject.items(), key=lambda x: x[1], reverse=True):
                    percentage = (time / total_study_time) * 100 if total_study_time > 0 else 0
                    subject_data.append([
                        subject, 
                        self._format_time(time), 
                        f"{percentage:.1f}%"
                    ])
                
                subject_table = Table(subject_data, colWidths=[2*inch, 1*inch, 1*inch])
                subject_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), self.pastel_colors['primary']),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                    ('BOX', (0, 0), (-1, -1), 1, colors.black),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ]))
                story.append(subject_table)
            
            story.append(Spacer(1, 0.3*inch))
            
            # Session details - add to a new page
            story.append(PageBreak())
            session_title = Paragraph("Session Details", self.styles['RMT_SectionHeader'])
            story.append(session_title)
            
            session_data = [['Subject', 'Start', 'End', 'Duration']]
            
            for session in sorted(sessions, key=lambda x: x['start_time']):
                start_time = session['start_time'].astimezone(MANILA_TZ).strftime('%I:%M %p')
                end_time = 'Ongoing' if not session['end_time'] else session['end_time'].astimezone(MANILA_TZ).strftime('%I:%M %p')
                
                session_data.append([
                    session['subject'],
                    start_time,
                    end_time,
                    self._format_time(session['total_study_time'])
                ])
            
            session_table = Table(session_data, colWidths=[1*inch, 1*inch, 1*inch, 1*inch])
            session_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), self.pastel_colors['primary']),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('BOX', (0, 0), (-1, -1), 1, colors.black),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            story.append(session_table)
        
        # Add creator footer
        story.append(Spacer(1, 0.5*inch))
        footer = Paragraph("Study tracker created by Eli.", self.styles['RMT_Footer'])
        story.append(footer)
        
        # Build PDF
        doc.build(story)
        buffer.seek(0)
        return buffer
        
    def generate_full_report(self, user_name, sessions):
        """Generate a comprehensive PDF report of all study sessions."""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        story = []
        
        # Title
        title = Paragraph(f"Study Progress Report of {user_name}, RMT", self.styles['RMT_ReportTitle'])
        story.append(title)
        story.append(Spacer(1, 0.5*inch))
        
        if not sessions:
            no_data = Paragraph("No study sessions recorded yet.", self.styles['RMT_BodyText'])
            story.append(no_data)
            
            # Add creator footer even when there's no data
            story.append(Spacer(1, 0.5*inch))
            footer = Paragraph("Study tracker created by Eli.", self.styles['RMT_Footer'])
            story.append(footer)
            
            doc.build(story)
            buffer.seek(0)
            return buffer
        
        # Clean subject names by removing emojis
        for session in sessions:
            session['subject'] = self._remove_emojis(session['subject'])
        
        # Sort sessions by date
        sessions.sort(key=lambda x: x['start_time'])
        
        # Group sessions by date
        sessions_by_date = {}
        for session in sessions:
            date_key = session['start_time'].date()
            if date_key not in sessions_by_date:
                sessions_by_date[date_key] = []
            sessions_by_date[date_key].append(session)
        
        # Calculate overall statistics
        total_study_time = sum(session['total_study_time'] for session in sessions)
        total_break_time = sum(session['total_break_time'] for session in sessions)
        total_days = len(sessions_by_date)
        first_date = min(sessions_by_date.keys())
        last_date = max(sessions_by_date.keys())
        days_span = (last_date - first_date).days + 1
        
        # Add key statistics section
        stats_title = Paragraph("Key Statistics", self.styles['RMT_SectionHeader'])
        story.append(stats_title)
        
        stats_data = [
            ['Metric', 'Value'],
            ['Total Study Time', self._format_time(total_study_time)],
            ['Total Break Time', self._format_time(total_break_time)],
            ['Days Studied', str(total_days)],
            ['Study Span', f"{days_span} days ({first_date.strftime('%Y-%m-%d')} to {last_date.strftime('%Y-%m-%d')})"],
            ['Avg. Study Time/Day', self._format_time(total_study_time / max(1, total_days))],
            ['Total Sessions', str(len(sessions))]
        ]
        
        ratio = "N/A"
        if total_break_time > 0:
            study_minutes = int(total_study_time / 60)
            break_minutes = int(total_break_time / 60)
            
            def gcd(a, b):
                while b:
                    a, b = b, a % b
                return a
            
            divisor = gcd(study_minutes, break_minutes)
            if divisor > 0:
                ratio = f"{study_minutes//divisor}:{break_minutes//divisor}"
        
        stats_data.append(['Study:Break Ratio', ratio])
        
        stats_table = Table(stats_data, colWidths=[2.5*inch, 2.5*inch])
        stats_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), self.pastel_colors['primary']),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BOX', (0, 0), (-1, -1), 1, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        story.append(stats_table)
        story.append(Spacer(1, 0.3*inch))
        
        # Move the Daily Timeline to page 2
        story.append(PageBreak())
        timeline_title = Paragraph("Daily Timeline", self.styles['RMT_ReportTitle'])  # Use ReportTitle for prominence
        story.append(timeline_title)
        story.append(Spacer(1, 0.3*inch))
        
        # Create date for the report generation - Fix the datetime.now issue
        from datetime import datetime  # Add this import explicitly
        report_date = datetime.now(MANILA_TZ).strftime('%Y-%m-%d %I:%M %p')
        report_info = Paragraph(f"Generated on: {report_date} | User: {user_name}", self.styles['RMT_BodyText'])
        story.append(report_info)
        story.append(Spacer(1, 0.2*inch))
        
        # Create a grouped timeline by date - NEW IMPLEMENTATION
        # We'll create a table for each date
        for date, day_sessions in sorted(sessions_by_date.items(), reverse=True):
            # Date header
            date_header = Paragraph(f"<b>{date.strftime('%Y-%m-%d')}</b>", self.styles['RMT_SectionHeader'])
            story.append(date_header)
            
            # Create session table for this date
            session_data = [['Subject', 'Start Time', 'End Time', 'Duration']]  # Header row
            
            # Add session rows
            for session in sorted(day_sessions, key=lambda x: x['start_time']):
                start_time = session['start_time'].astimezone(MANILA_TZ).strftime('%I:%M %p')
                end_time = 'Ongoing' if not session['end_time'] else session['end_time'].astimezone(MANILA_TZ).strftime('%I:%M %p')
                
                session_data.append([
                    session['subject'],
                    start_time,
                    end_time,
                    self._format_time(session['total_study_time'])
                ])
            
            # Calculate day total
            day_total = sum(session['total_study_time'] for session in day_sessions)
            
            # Add total row
            session_data.append([
                "<b>Total</b>",
                "",
                "",
                f"<b>{self._format_time(day_total)}</b>"
            ])
            
            # Create and style the table
            date_table = Table(session_data, colWidths=[2*inch, 1.3*inch, 1.3*inch, 1.2*inch])
            
            # Apply styling
            row_styles = []
            for i in range(len(session_data)):
                if i == 0:  # Header row
                    row_styles.append(('BACKGROUND', (0, i), (-1, i), self.pastel_colors['primary']))
                    row_styles.append(('TEXTCOLOR', (0, i), (-1, i), colors.white))
                    row_styles.append(('FONTNAME', (0, i), (-1, i), 'Helvetica-Bold'))
                    row_styles.append(('ALIGN', (0, i), (-1, i), 'CENTER'))
                elif i == len(session_data) - 1:  # Total row
                    row_styles.append(('BACKGROUND', (0, i), (-1, i), self.pastel_colors['accent1']))
                    row_styles.append(('ALIGN', (-1, i), (-1, i), 'RIGHT'))
                else:  # Data rows
                    if i % 2 == 1:  # Alternate row coloring
                        row_styles.append(('BACKGROUND', (0, i), (-1, i), self.pastel_colors['contrast']))
                    row_styles.append(('ALIGN', (-1, i), (-1, i), 'RIGHT'))  # Right-align duration
                    row_styles.append(('ALIGN', (1, i), (2, i), 'CENTER'))  # Center-align times
            
            # General table styling
            date_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('BOX', (0, 0), (-1, -1), 1, colors.black),
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                *row_styles
            ]))
            
            story.append(date_table)
            story.append(Spacer(1, 0.3*inch))  # Add space between date sections
        
        # Add a grand total
        grand_total = sum(sum(session['total_study_time'] for session in day_sessions) 
                         for day_sessions in sessions_by_date.values())
        total_text = Paragraph(f"<b>Grand Total: {self._format_time(grand_total)}</b>", self.styles['RMT_BodyText'])
        story.append(total_text)
        
        # Overall time distribution chart - put on a new page
        story.append(PageBreak())
        chart_title = Paragraph("Overall Time Distribution", self.styles['RMT_SectionHeader'])
        story.append(chart_title)
        
        if total_study_time > 0 or total_break_time > 0:
            drawing = Drawing(5*inch, 3*inch)  # Increased height
            pie = Pie()
            pie.x = 2.5*inch
            pie.y = 1.5*inch  # Adjusted y position
            pie.width = 2.5*inch
            pie.height = 2.5*inch
            pie.data = [total_study_time, total_break_time]
            pie.labels = ['Study', 'Break']
            pie.slices.strokeWidth = 0.5
            pie.slices[0].fillColor = self.pastel_colors['chart1']
            pie.slices[1].fillColor = self.pastel_colors['chart2']
            drawing.add(pie)
            story.append(drawing)
            
            # Add legend with pastel colors
            total_time = total_study_time + total_break_time
            if total_time > 0:
                legend = Paragraph(
                    f"<font color='{self._rgb_to_hex(self.pastel_colors['chart1'])}'>■</font> Study: {self._format_time(total_study_time)} ({100*total_study_time/total_time:.1f}%)<br/>"
                    f"<font color='{self._rgb_to_hex(self.pastel_colors['chart2'])}'>■</font> Break: {self._format_time(total_break_time)} ({100*total_break_time/total_time:.1f}%)",
                    self.styles['RMT_BodyText']
                )
                story.append(legend)
                
            # Add extra spacing after the chart
            story.append(Spacer(1, 0.5*inch))  # Increased spacing
        
        # Daily study time chart - add to a new page
        story.append(PageBreak())
        daily_chart_title = Paragraph("Daily Study Time", self.styles['RMT_SectionHeader'])
        story.append(daily_chart_title)
        
        daily_data = []
        daily_labels = []
        
        for date, day_sessions in sorted(sessions_by_date.items()):
            day_total = sum(session['total_study_time'] for session in day_sessions) / 3600  # Convert to hours
            daily_data.append(day_total)
            daily_labels.append(date.strftime("%m/%d"))
        
        drawing = Drawing(500, 200)
        bc = VerticalBarChart()
        bc.x = 50
        bc.y = 50
        bc.height = 125
        bc.width = 400
        bc.data = [daily_data]
        bc.strokeColor = colors.black
        bc.fillColor = self.pastel_colors['primary']
        
        bc.valueAxis.valueMin = 0
        bc.valueAxis.valueMax = max(daily_data) * 1.1 if daily_data else 5
        bc.valueAxis.valueStep = 1
        bc.valueAxis.labelTextFormat = '%0.1f h'
        bc.categoryAxis.labels.boxAnchor = 'ne'
        bc.categoryAxis.labels.dx = 8
        bc.categoryAxis.labels.dy = -2
        bc.categoryAxis.labels.angle = 30
        bc.categoryAxis.categoryNames = daily_labels
        
        drawing.add(bc)
        story.append(drawing)
        story.append(Spacer(1, 0.5*inch))  # Increased spacing
        
        # Subject breakdown - add to a new page
        story.append(PageBreak())
        subject_title = Paragraph("Subject Breakdown", self.styles['RMT_SectionHeader'])
        story.append(subject_title)
        
        # Group study time by subject
        subject_times = {}
        for session in sessions:
            subject = session['subject']
            if subject not in subject_times:
                subject_times[subject] = 0
            subject_times[subject] += session['total_study_time']
        
        # Create table for subject breakdown
        subject_data = [['Subject', 'Total Time', 'Percentage']]
        
        for subject, time in sorted(subject_times.items(), key=lambda x: x[1], reverse=True):
            percentage = (time / total_study_time) * 100 if total_study_time > 0 else 0
            subject_data.append([
                subject, 
                self._format_time(time), 
                f"{percentage:.1f}%"
            ])
        
        subject_table = Table(subject_data, colWidths=[2.5*inch, 2*inch, 1.5*inch])
        subject_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), self.pastel_colors['primary']),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BOX', (0, 0), (-1, -1), 1, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        
        story.append(subject_table)
        story.append(Spacer(1, 0.5*inch))  # Increased spacing
        
        # Subject pie chart - add to a new page with adjusted positioning
        story.append(PageBreak())
        subject_pie_title = Paragraph("Subject Distribution", self.styles['RMT_SectionHeader'])
        story.append(subject_pie_title)
        
        # Add extra spacing before the chart
        story.append(Spacer(1, 0.5*inch))  # Add more space before the chart
        
        if subject_times:
            # Increase the drawing height and adjust pie position
            drawing = Drawing(500, 400)  # Increased height from 300 to 400
            pie = Pie()
            pie.x = 100  # Center horizontally
            pie.y = 250  # Moved down 4x from 150 to 200
            pie.width = 250
            pie.height = 250
            
            # Get top 5 subjects by time, group others as "Other"
            top_subjects = sorted(subject_times.items(), key=lambda x: x[1], reverse=True)
            if len(top_subjects) > 5:
                data_values = [t[1] for t in top_subjects[:5]]
                data_labels = [t[0] for t in top_subjects[:5]]
                
                other_time = sum(t[1] for t in top_subjects[5:])
                data_values.append(other_time)
                data_labels.append('Other')
            else:
                data_values = [t[1] for t in top_subjects]
                data_labels = [t[0] for t in top_subjects]
            
            pie.data = data_values
            pie.labels = data_labels
            pie.slices.strokeWidth = 0.5
            
            # Set a palette of pastel colors
            colors_palette = [
                self.pastel_colors['primary'],
                self.pastel_colors['secondary'],
                self.pastel_colors['accent1'],
                self.pastel_colors['accent2'],
                self.pastel_colors['accent3'],
                self.pastel_colors['accent4']
            ]
            
            for i in range(len(data_values)):
                pie.slices[i].fillColor = colors_palette[i % len(colors_palette)]
            
            drawing.add(pie)
            story.append(drawing)
            
            # Add extra spacing for the legend to ensure it's well below the chart
            story.append(Spacer(1, 0.3*inch))
            
            # Add legend with pastel colors
            legend_text = ""
            for i, (subject, time) in enumerate(zip(data_labels, data_values)):
                color = colors_palette[i % len(colors_palette)]
                percentage = (time / total_study_time) * 100 if total_study_time > 0 else 0
                hex_color = self._rgb_to_hex(color)
                legend_text += f"<font color='{hex_color}'>■</font> {subject}: {self._format_time(time)} ({percentage:.1f}%)<br/>"
            
            legend = Paragraph(legend_text, self.styles['RMT_BodyText'])
            story.append(legend)
            story.append(Spacer(1, 0.5*inch))  # Increased spacing
        
        # Subject detail pages - add each to a new page
        for subject in sorted(subject_times.keys()):
            story.append(PageBreak())
            
            subject_page_title = Paragraph(f"Subject: {subject}", self.styles['RMT_ReportTitle'])
            story.append(subject_page_title)
            story.append(Spacer(1, 0.3*inch))
            
            subject_total = subject_times[subject]
            subject_sessions = [s for s in sessions if s['subject'] == subject]
            subject_percentage = (subject_total / total_study_time) * 100 if total_study_time > 0 else 0
            
            subject_summary = Paragraph(
                f"Total Time: {self._format_time(subject_total)}<br/>"
                f"Percentage of Total Study Time: {subject_percentage:.1f}%<br/>"
                f"Number of Sessions: {len(subject_sessions)}", 
                self.styles['RMT_BodyText']
            )
            story.append(subject_summary)
            story.append(Spacer(1, 0.3*inch))
            
            # Daily progress for this subject
            subject_by_date = {}
            for session in subject_sessions:
                date_key = session['start_time'].date()
                if date_key not in subject_by_date:
                    subject_by_date[date_key] = 0
                subject_by_date[date_key] += session['total_study_time']
            
            if subject_by_date:
                daily_subject_title = Paragraph(f"Daily Progress for {subject}", self.styles['RMT_SectionHeader'])
                story.append(daily_subject_title)
                
                daily_data = []
                daily_labels = []
                
                for date, time in sorted(subject_by_date.items()):
                    hours = time / 3600  # Convert to hours
                    daily_data.append(hours)
                    daily_labels.append(date.strftime("%m/%d"))
                
                drawing = Drawing(500, 200)
                bc = VerticalBarChart()
                bc.x = 50
                bc.y = 50
                bc.height = 125
                bc.width = 400
                bc.data = [daily_data]
                bc.strokeColor = colors.black
                bc.fillColor = self.pastel_colors['secondary']
                
                bc.valueAxis.valueMin = 0
                bc.valueAxis.valueMax = max(daily_data) * 1.1 if daily_data else 5
                bc.valueAxis.valueStep = 1
                bc.valueAxis.labelTextFormat = '%0.1f h'
                bc.categoryAxis.labels.boxAnchor = 'ne'
                bc.categoryAxis.labels.dx = 8
                bc.categoryAxis.labels.dy = -2
                bc.categoryAxis.labels.angle = 30
                bc.categoryAxis.categoryNames = daily_labels
                
                drawing.add(bc)
                story.append(drawing)
                story.append(Spacer(1, 0.5*inch))  # Increased spacing
            
            # Sessions for this subject - group by date like the main timeline
            sessions_title = Paragraph("Sessions", self.styles['RMT_SectionHeader'])
            story.append(sessions_title)
            
            if subject_sessions:
                # Group sessions by date
                subject_sessions_by_date = {}
                for session in subject_sessions:
                    date_key = session['start_time'].date()
                    if date_key not in subject_sessions_by_date:
                        subject_sessions_by_date[date_key] = []
                    subject_sessions_by_date[date_key].append(session)
                
                # Create session tables for each date
                for date, day_sessions in sorted(subject_sessions_by_date.items(), reverse=True):
                    # Date header
                    date_header = Paragraph(f"<b>{date.strftime('%Y-%m-%d')}</b>", self.styles['RMT_BodyText'])
                    story.append(date_header)
                    
                    # Create session table for this date
                    session_data = [['Start Time', 'End Time', 'Duration']]  # Header row
                    
                    # Add session rows
                    for session in sorted(day_sessions, key=lambda x: x['start_time']):
                        start_time = session['start_time'].astimezone(MANILA_TZ).strftime('%I:%M %p')
                        end_time = 'Ongoing' if not session['end_time'] else session['end_time'].astimezone(MANILA_TZ).strftime('%I:%M %p')
                        
                        session_data.append([
                            start_time,
                            end_time,
                            self._format_time(session['total_study_time'])
                        ])
                    
                    # Calculate day total
                    day_total = sum(session['total_study_time'] for session in day_sessions)
                    
                    # Add total row
                    session_data.append([
                        "<b>Total</b>",
                        "",
                        f"<b>{self._format_time(day_total)}</b>"
                    ])
                    
                    # Create and style the table
                    date_table = Table(session_data, colWidths=[1.5*inch, 1.5*inch, 1.5*inch])
                    
                    # Apply styling
                    row_styles = []
                    for i in range(len(session_data)):
                        if i == 0:  # Header row
                            row_styles.append(('BACKGROUND', (0, i), (-1, i), self.pastel_colors['primary']))
                            row_styles.append(('TEXTCOLOR', (0, i), (-1, i), colors.white))
                            row_styles.append(('FONTNAME', (0, i), (-1, i), 'Helvetica-Bold'))
                            row_styles.append(('ALIGN', (0, i), (-1, i), 'CENTER'))
                        elif i == len(session_data) - 1:  # Total row
                            row_styles.append(('BACKGROUND', (0, i), (-1, i), self.pastel_colors['accent1']))
                            row_styles.append(('ALIGN', (-1, i), (-1, i), 'RIGHT'))
                        else:  # Data rows
                            if i % 2 == 1:  # Alternate row coloring
                                row_styles.append(('BACKGROUND', (0, i), (-1, i), self.pastel_colors['contrast']))
                            row_styles.append(('ALIGN', (-1, i), (-1, i), 'RIGHT'))  # Right-align duration
                            row_styles.append(('ALIGN', (0, i), (1, i), 'CENTER'))  # Center-align times
                    
                    # General table styling
                    date_table.setStyle(TableStyle([
                        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                        ('BOX', (0, 0), (-1, -1), 1, colors.black),
                        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                        ('TOPPADDING', (0, 0), (-1, -1), 6),
                        *row_styles
                    ]))
                    
                    story.append(date_table)
                    story.append(Spacer(1, 0.3*inch))  # Add space between date sections
            else:
                no_sessions = Paragraph("No sessions recorded for this subject.", self.styles['RMT_BodyText'])
                story.append(no_sessions)
            
            # Add creator footer to each subject page
            story.append(Spacer(1, 0.5*inch))
            footer = Paragraph("Study tracker created by Eli.", self.styles['RMT_Footer'])
            story.append(footer)
        
        # For the main page, add creator footer at the end
        if not subject_times:
            story.append(Spacer(1, 0.5*inch))
            footer = Paragraph("Study tracker created by Eli.", self.styles['RMT_Footer'])
            story.append(footer)
        
        # Build PDF
        doc.build(story)
        buffer.seek(0)
        return buffer

# ================== SINGLE INSTANCE CHECK ==================
def ensure_single_instance():
    """Ensure only one instance of the bot is running with better conflict resolution."""
    try:
        # First, forcefully clear the bot's webhook if any
        token = os.getenv('TELEGRAM_BOT_TOKEN')
        if token:
            try:
                webhook_clear_url = f"https://api.telegram.org/bot{token}/deleteWebhook?drop_pending_updates=true"
                response = requests.get(webhook_clear_url, timeout=10)
                if response.status_code == 200:
                    logger.info("Successfully cleared any existing webhook")
                    # Allow time for webhook clearing to take effect
                    time.sleep(2)
                else:
                    logger.warning(f"Failed to clear webhook: {response.status_code} {response.text}")
            except Exception as e:
                logger.error(f"Error clearing webhook: {e}")
        
        # Check if PID file exists
        if os.path.exists(PID_FILE):
            try:
                with open(PID_FILE, 'r') as f:
                    old_pid = int(f.read().strip())
                
                # On Render, sometimes the PID file persists after restart
                # So we need to check if this is a fresh deployment
                pid_file_age = time.time() - os.path.getmtime(PID_FILE)
                
                # If file is less than 60 seconds old, assume it's from a concurrent startup
                if pid_file_age < 60:
                    logger.warning(f"Recent PID file found ({pid_file_age:.1f}s old). Checking process...")
                    
                    try:
                        # Try to kill the old process directly
                        os.kill(old_pid, signal.SIGTERM)
                        logger.info(f"Sent SIGTERM to previous process with PID {old_pid}")
                        time.sleep(5)  # Give it time to terminate
                    except OSError:
                        logger.info(f"No process with PID {old_pid} found, safe to continue")
                
                # If PID file is older, it might be stale
                else:
                    logger.info(f"Found old PID file ({pid_file_age:.1f}s old). Assuming stale.")
            except Exception as e:
                logger.error(f"Error processing existing PID file: {e}")
        
        # Write our PID to the file
        with open(PID_FILE, 'w') as f:
            f.write(str(os.getpid()))
        logger.info(f"PID {os.getpid()} written to {PID_FILE}")
        
        # Register cleanup to remove PID file on exit
        def cleanup_pid_file():
            try:
                if os.path.exists(PID_FILE):
                    os.remove(PID_FILE)
                    logger.info(f"Removed PID file {PID_FILE}")
            except Exception as e:
                logger.error(f"Error removing PID file: {e}")
        
        atexit.register(cleanup_pid_file)
        
    except Exception as e:
        logger.error(f"Error in single instance check: {e}")

# ================== RESOURCE MONITOR ==================
class ResourceMonitor:
    @staticmethod
    def get_status():
        try:
            import psutil
            return {
                "cpu": psutil.cpu_percent(),
                "memory": psutil.virtual_memory().percent,
                "boot_time": datetime.datetime.fromtimestamp(psutil.boot_time()).isoformat(),
                "process_uptime": time.time() - psutil.Process().create_time(),
                "threads": threading.active_count()
            }
        except Exception as e:
            logger.error(f"Resource monitoring error: {e}")
            return {
                "cpu": "N/A",
                "memory": "N/A",
                "boot_time": "N/A",
                "process_uptime": "N/A",
                "threads": "N/A"
            }

# ================== KEEPALIVE SERVER ==================
class KeepaliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health' or self.path == '/':  # Add root path for UptimeRobot
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Bot is alive!')  # Changed from 'OK' to 'Bot is alive!'
        elif self.path == '/ping':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(f"pong {datetime.datetime.now().isoformat()}".encode())
        elif self.path == '/status':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            resources = ResourceMonitor.get_status()
            
            # Handle case where telegram_bot might not be initialized yet
            active_sessions = 0
            pending_sessions = 0
            last_activity_time = datetime.datetime.now()
            
            if shared_state.telegram_bot:
                active_sessions = len(shared_state.telegram_bot.study_sessions)
                pending_sessions = len(shared_state.telegram_bot.pending_sessions)
                last_activity_time = shared_state.telegram_bot.last_activity
            
            status = "Running" if not shared_state.is_shutting_down else "Shutting Down"
            status_class = "good" if not shared_state.is_shutting_down else "warning"
            
            current_utc_time = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            
            status_html = f"""
            <html>
                <head>
                    <title>RMT Study Bot Status</title>
                    <meta http-equiv="refresh" content="60">
                    <style>
                        body {{ font-family: Arial, sans-serif; margin: 20px; }}
                        h1 {{ color: #2c3e50; }}
                        .status-box {{ 
                            border: 1px solid #ddd; 
                            padding: 15px; 
                            margin-bottom: 20px; 
                            border-radius: 5px;
                            background-color: #f9f9f9;
                        }}
                        .metric {{ margin-bottom: 10px; }}
                        .metric-name {{ font-weight: bold; }}
                        .session-list {{ margin-top: 20px; }}
                        .good {{ color: green; }}
                        .warning {{ color: orange; }}
                        .bad {{ color: red; }}
                    </style>
                </head>
                <body>
                    <h1>📚 RMT Study Bot Status</h1>
                    <div class="status-box">
                        <h2>System Health</h2>
                        <div class="metric">
                            <span class="metric-name">Status:</span> 
                            <span class="{status_class}">{status}</span>
                        </div>
                        <div class="metric">
                            <span class="metric-name">Last Activity:</span> 
                            {last_activity_time.strftime('%Y-%m-%d %H:%M:%S')}
                        </div>
                        <div class="metric">
                            <span class="metric-name">Active Sessions:</span> 
                            {active_sessions}
                        </div>
                        <div class="metric">
                            <span class="metric-name">Pending Sessions:</span> 
                            {pending_sessions}
                        </div>
                        <div class="metric">
                            <span class="metric-name">CPU Usage:</span> 
                            {resources['cpu']}%
                        </div>
                        <div class="metric">
                            <span class="metric-name">Memory Usage:</span> 
                            {resources['memory']}%
                        </div>
                        <div class="metric">
                            <span class="metric-name">System Uptime:</span> 
                            {resources['boot_time']}
                        </div>
                        <div class="metric">
                            <span class="metric-name">Process Uptime:</span> 
                            {int(resources['process_uptime'])} seconds
                        </div>
                        <div class="metric">
                            <span class="metric-name">Process ID:</span> 
                            {os.getpid()}
                        </div>
                        <div class="metric">
                            <span class="metric-name">Active Threads:</span> 
                            {resources['threads']}
                        </div>
                        <div class="metric">
                            <span class="metric-name">Current Date and Time (Manila):</span> 
                            {datetime.datetime.now(MANILA_TZ).strftime('%Y-%m-%d %H:%M:%S %Z')}
                        </div>
                        <div class="metric">
                            <span class="metric-name">Current Date and Time (UTC - YYYY-MM-DD HH:MM:SS):</span> 
                            {current_utc_time}
                        </div>
                        <div class="metric">
                            <span class="metric-name">Current User's Login:</span> 
                            {CURRENT_USER}
                        </div>
                        <div class="metric">
                            <span class="metric-name">Environment:</span> 
                            {'Production' if os.getenv('RENDER') else 'Development'}
                        </div>
                        <div class="metric">
                            <span class="metric-name">Data Persistence:</span> 
                            {'Enabled' if os.path.exists(PERSISTENCE_PATH) else 'Not Enabled'}
                        </div>
                    </div>
                </body>
            </html>
            """
            self.wfile.write(status_html.encode())
        elif self.path == '/shutdown':
            # Security: In a real production app, you would add authentication here
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Shutting down...')
            
            # Initiate shutdown
            shared_state.is_shutting_down = True
            threading.Thread(target=self.shutdown_application).start()
        else:
            self.send_response(404)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Not Found')

    def shutdown_application(self):
        """Shut down the application gracefully."""
        time.sleep(1)  # Give the response time to complete
        os.kill(os.getpid(), signal.SIGTERM)

    # Override all methods to handle UptimeRobot requests
    def do_HEAD(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        
    def do_POST(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'Bot is alive!')  # Changed from 'OK' to 'Bot is alive!'
        
    def do_PUT(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'Bot is alive!')  # Changed from 'OK' to 'Bot is alive!'
        
    def do_DELETE(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'Bot is alive!')  # Changed from 'OK' to 'Bot is alive!'

    def log_message(self, format, *args):
        if args[0].startswith(('GET /health', 'GET /ping', 'GET / HTTP')):
            return  # Don't log health check requests
        logger.info("%s - - [%s] %s" % (self.client_address[0], self.log_date_time_string(), format % args))

class KeepaliveServer:
    def __init__(self):
        self.server = None
        self.thread = None
        
    def start(self):
        """Start the health check server in a separate thread."""
        # Use HEALTH_CHECK_PORT if available, otherwise fall back to PORT, then to default 10001
        port = int(os.getenv('HEALTH_CHECK_PORT', os.getenv('PORT', 10001)))
        self.server = HTTPServer(('0.0.0.0', port), KeepaliveHandler)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()
        logger.info(f"Keepalive server started on port {port}")
        
    def stop(self):
        """Stop the server gracefully."""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            logger.info("Keepalive server stopped")

# ================== STUDY SESSION CLASS ==================
class StudySession:
    def __init__(self, user_id: int, subject: str, goal_time: Optional[str] = None):
        self.user_id = user_id
        self.subject = subject
        self.goal_time = goal_time
        self.start_time = datetime.datetime.now(PST_TZ)
        self.end_time = None
        self.break_periods = []
        self.break_start = None
        self.is_on_break = False

    def start_break(self):
        """Start a break period."""
        if not self.is_on_break:
            self.break_start = datetime.datetime.now(PST_TZ)
            self.is_on_break = True

    def end_break(self):
        """End a break period."""
        if self.is_on_break and self.break_start:
            break_end = datetime.datetime.now(PST_TZ)
            self.break_periods.append({
                'start': self.break_start,
                'end': break_end
            })
            self.break_start = None
            self.is_on_break = False

    def end(self):
        """End the study session."""
        if self.is_on_break:
            self.end_break()
        self.end_time = datetime.datetime.now(PST_TZ)

    def get_total_study_time(self) -> datetime.timedelta:
        """Calculate total study time excluding breaks."""
        if not self.end_time:
            current_time = datetime.datetime.now(PST_TZ)
        else:
            current_time = self.end_time

        total_duration = current_time - self.start_time
        break_duration = self.get_total_break_time()
        return total_duration - break_duration

    def get_total_break_time(self) -> datetime.timedelta:
        """Calculate total break time."""
        total_break = datetime.timedelta()
        
        for break_period in self.break_periods:
            total_break += break_period['end'] - break_period['start']
        
        if self.is_on_break and self.break_start:
            current_time = datetime.datetime.now(PST_TZ)
            total_break += current_time - self.break_start
        
        return total_break

    def get_study_break_ratio(self) -> str:
        """Calculate the study to break ratio."""
        study_time = self.get_total_study_time()
        break_time = self.get_total_break_time()
        
        study_minutes = int(study_time.total_seconds() / 60)
        break_minutes = int(break_time.total_seconds() / 60)
        
        if break_minutes == 0:
            return f"{study_minutes}:0"
        
        def gcd(a, b):
            while b:
                a, b = b, a % b
            return a
        
        divisor = gcd(study_minutes, break_minutes)
        if divisor == 0:  # Avoid division by zero
            return f"{study_minutes}:{break_minutes}"
        return f"{study_minutes//divisor}:{break_minutes//divisor}"

    def get_progress_percentage(self) -> int:
        """Calculate progress percentage based on goal."""
        if not self.goal_time:
            return 0
        
        try:
            if ':' in self.goal_time:
                hours, minutes = map(int, self.goal_time.split(':'))
                goal_minutes = hours * 60 + minutes
            else:
                goal_minutes = int(self.goal_time) * 60
        except ValueError:
            return 0

        study_time = self.get_total_study_time()
        actual_minutes = study_time.total_seconds() / 60
        progress = (actual_minutes / goal_minutes) * 100
        return min(100, int(progress))

    def get_formatted_manila_times(self) -> dict:
        """Get all times formatted in Manila timezone."""
        times = {
            'start': self.start_time.astimezone(MANILA_TZ),
            'end': self.end_time.astimezone(MANILA_TZ) if self.end_time else None,
            'breaks': []
        }
        
        for break_period in self.break_periods:
            times['breaks'].append({
                'start': break_period['start'].astimezone(MANILA_TZ),
                'end': break_period['end'].astimezone(MANILA_TZ)
            })
            
        return times
        
    def to_dict(self):
        """Convert session to a dictionary for storage."""
        return {
            'user_id': self.user_id,
            'subject': self.subject,
            'goal_time': self.goal_time,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'break_periods': self.break_periods,
            'total_study_time': self.get_total_study_time().total_seconds(),
            'total_break_time': self.get_total_break_time().total_seconds(),
            'study_break_ratio': self.get_study_break_ratio(),
            'progress_percentage': self.get_progress_percentage()
        }

# ================== PENDING SESSION CLASS ==================
class PendingSession:
    def __init__(self, user_id: int, chat_id: int, message_ids: list, start_time: datetime.datetime):
        self.user_id = user_id
        self.chat_id = chat_id
        self.message_ids = message_ids
        self.start_time = start_time
        self.thread_id = None

# ================== TELEGRAM BOT CLASS ==================
class TelegramBot:
    def __init__(self):
        self.study_sessions: Dict[int, StudySession] = {}
        self.pending_sessions: Dict[int, PendingSession] = {}
        self.last_activity = datetime.datetime.now()
        self.start_command_handlers: Set[int] = set()  # Track users who have already triggered /start
        self.application = None
        self.db = GoogleDriveDB()
        self.pdf_generator = PDFReportGenerator()
        
        # Initialize Google Drive DB
        self.db.initialize()

    async def reset_user_data(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Reset/delete user data from the database."""
        self.record_activity()
        user = update.effective_user
        user_id = user.id
        
        # Check if the user has data in the database
        user_data = self.db.load_user_data(user_id)
        if not user_data:
            await update.message.reply_text("You don't have any stored data to reset.")
            return
        
        # Create confirmation buttons
        buttons = [
            [
                InlineKeyboardButton("Yes, delete my data ✅", callback_data='confirm_reset_data'),
                InlineKeyboardButton("No, keep my data ❌", callback_data='cancel_reset_data')
            ]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)
        
        # Store the thread_id if the message is in a topic
        if update.message and update.message.is_topic_message:
            context.user_data['thread_id'] = update.message.message_thread_id
        
        await update.message.reply_text(
            "⚠️ WARNING: This will permanently delete all your study session data. Are you sure?",
            reply_markup=reply_markup
        )
    
    async def handle_reset_confirmation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the data reset confirmation."""
        self.record_activity()
        query = update.callback_query
        await query.answer()
        
        # Check if we're in a topic/thread
        if update.callback_query.message and update.callback_query.message.is_topic_message:
            # Update the thread_id in user_data
            context.user_data['thread_id'] = update.callback_query.message.message_thread_id
        
        if query.data == 'confirm_reset_data':
            user_id = update.effective_user.id
            
            # Create an empty data structure and save it to overwrite existing data
            empty_data = {
                'user_name': update.effective_user.first_name or update.effective_user.username or "User",
                'sessions': []
            }
            success = self.db.save_user_data(user_id, empty_data)
            
            if success:
                await query.edit_message_text("✅ All your study data has been reset successfully.")
            else:
                await query.edit_message_text("❌ There was an error resetting your data. Please try again later.")
        else:  # cancel_reset_data
            await query.edit_message_text("Operation cancelled. Your data remains unchanged.")

    async def cleanup_all_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Clean up ALL messages including those marked to keep."""
        messages_to_delete = context.user_data.get('messages_to_delete', [])
        messages_to_keep = context.user_data.get('messages_to_keep', [])
        
        all_messages = messages_to_delete + messages_to_keep
        
        for message_id in all_messages:
            try:
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id,
                    message_id=message_id
                )
            except Exception as e:
                logger.error(f"Error deleting message {message_id}: {e}")
        
        context.user_data['messages_to_delete'] = []
        context.user_data['messages_to_keep'] = []
    
    async def cleanup_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Clean up messages that should be deleted."""
        messages_to_delete = context.user_data.get('messages_to_delete', [])
        
        for message_id in messages_to_delete:
            try:
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id,
                    message_id=message_id
                )
            except Exception as e:
                logger.error(f"Error deleting message {message_id}: {e}")
        
        context.user_data['messages_to_delete'] = []
        
        # Also remove this user from pending sessions if they exist
        user_id = update.effective_user.id
        if user_id in self.pending_sessions:
            del self.pending_sessions[user_id]

    async def send_bot_message(
        self, 
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        text: str,
        reply_markup: InlineKeyboardMarkup = None,
        should_delete: bool = True
    ) -> int:
        """Send a bot message and track it for cleanup if needed."""
        # Update last activity timestamp
        self.record_activity()
        
        thread_id = None
        if 'thread_id' in context.user_data:
            thread_id = context.user_data['thread_id']
        elif context.user_data.get('current_thread_id'):
            thread_id = context.user_data['current_thread_id']
        
        # Log the thread_id for debugging
        if thread_id:
            logger.debug(f"Sending message to thread {thread_id}")
        else:
            logger.debug("Sending message to main chat (no thread)")
        
        message = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            message_thread_id=thread_id
        )
        
        if should_delete:
            if 'messages_to_delete' not in context.user_data:
                context.user_data['messages_to_delete'] = []
            context.user_data['messages_to_delete'].append(message.message_id)
            
        return message.message_id

    async def send_document(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        document,
        filename: str,
        caption: str = None,
        should_delete: bool = False
    ):
        """Send a document with proper thread ID handling."""
        self.record_activity()
        
        # Get thread_id from user_data if available
        thread_id = None
        if 'thread_id' in context.user_data:
            thread_id = context.user_data['thread_id']
        elif context.user_data.get('current_thread_id'):
            thread_id = context.user_data['current_thread_id']
        
        # Send the document with thread_id if in a topic
        message = await context.bot.send_document(
            chat_id=chat_id,
            document=document,
            filename=filename,
            caption=caption,
            message_thread_id=thread_id
        )
        
        if should_delete:
            if 'messages_to_delete' not in context.user_data:
                context.user_data['messages_to_delete'] = []
            context.user_data['messages_to_delete'].append(message.message_id)
        
        return message.message_id

    def record_activity(self):
        """Update last activity timestamp"""
        self.last_activity = datetime.datetime.now()

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Start the conversation and ask if user wants to study."""
        # Fix for duplicate welcome message
        user_id = update.effective_user.id
        
        # Check if this user has already triggered the /start command
        if user_id in self.start_command_handlers:
            # If they have, just return without doing anything
            return ConversationHandler.END
        
        # Add user to the set of users who have triggered /start
        self.start_command_handlers.add(user_id)
        
        # Clear the set after a brief delay to allow future /start commands
        asyncio.create_task(self.clear_start_handler(user_id, 5))  # 5 seconds delay
        
        await self.cleanup_messages(update, context)
        self.record_activity()
        
        # Store the thread_id if the message is in a topic
        # This is the key part that needs fixing - ensure we capture message_thread_id
        if update.message and update.message.is_topic_message:
            context.user_data['thread_id'] = update.message.message_thread_id
            logger.info(f"Started in thread {update.message.message_thread_id}")
        elif update.effective_message and update.effective_message.is_topic_message:
            # This catches cases when clicking on old messages in threads
            context.user_data['thread_id'] = update.effective_message.message_thread_id
            logger.info(f"Started in thread (from effective_message) {update.effective_message.message_thread_id}")
        else:
            # Clear any existing thread_id if this is in main chat
            if 'thread_id' in context.user_data:
                del context.user_data['thread_id']
        
        # Modified buttons array to include the "LAST SESSION REPORT" button
        buttons = [
            [InlineKeyboardButton("Start Studying 📚", callback_data='start_studying')],
            [InlineKeyboardButton("MY OVERALL PROGRESS 📊", callback_data='overall_progress')],
            [InlineKeyboardButton("STUDY REPORT TODAY 📋", callback_data='today_report')],
            [InlineKeyboardButton("LAST SESSION REPORT 📄", callback_data='last_session_report')]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)
        
        welcome_text = "Welcome to RMT Study Bot! 📚✨"
        
        message = await self.send_bot_message(
            context,
            update.effective_chat.id,
            welcome_text,
            reply_markup=reply_markup,
            should_delete=False
        )
        
        # Store this message to keep it
        if 'messages_to_keep' not in context.user_data:
            context.user_data['messages_to_keep'] = []
        context.user_data['messages_to_keep'].append(message)
        
        # Add this user to pending sessions
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        
        # Get thread_id from either message or effective_message
        thread_id = None
        if update.message and update.message.is_topic_message:
            thread_id = update.message.message_thread_id
        elif update.effective_message and update.effective_message.is_topic_message:
            thread_id = update.effective_message.message_thread_id
        
        # Create a pending session
        self.pending_sessions[user_id] = PendingSession(
            user_id=user_id,
            chat_id=chat_id,
            message_ids=[message],
            start_time=datetime.datetime.now()
        )
        self.pending_sessions[user_id].thread_id = thread_id
        
        # Schedule cleanup task for this pending session
        asyncio.create_task(self.schedule_pending_session_cleanup(user_id))
        
        return CHOOSING_MAIN_MENU

    async def clear_start_handler(self, user_id: int, delay: int):
        """Clear a user from the start handler set after a delay."""
        await asyncio.sleep(delay)
        if user_id in self.start_command_handlers:
            self.start_command_handlers.remove(user_id)

    async def schedule_pending_session_cleanup(self, user_id: int):
        """Schedule cleanup of a pending session after 30 minutes."""
        try:
            await asyncio.sleep(30 * 60)  # 30 minutes
            
            # Check if this pending session still exists and hasn't been completed
            if user_id in self.pending_sessions and self.application:
                pending_session = self.pending_sessions[user_id]
                
                # Silently delete all associated messages
                for message_id in pending_session.message_ids:
                    try:
                        await self.application.bot.delete_message(
                            chat_id=pending_session.chat_id,
                            message_id=message_id
                        )
                    except Exception as e:
                        logger.error(f"Error deleting pending session message {message_id}: {e}")
                
                # Remove the pending session silently - no notification sent
                del self.pending_sessions[user_id]
                logger.info(f"Silently cleaned up pending session for user {user_id} after timeout")
        
        except Exception as e:
            logger.error(f"Error in pending session cleanup: {e}")

    async def ask_goal(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Ask user to set a study goal."""
        self.record_activity()
        context.user_data['previous_state'] = CHOOSING_MAIN_MENU
        query = update.callback_query
        await query.answer()
        
        # Check if we're in a topic/thread
        if update.callback_query.message and update.callback_query.message.is_topic_message:
            # Update the thread_id in user_data
            context.user_data['thread_id'] = update.callback_query.message.message_thread_id
            
        await self.cleanup_messages(update, context)

        buttons = [
            [
                InlineKeyboardButton("1 Hour", callback_data='goal_1'),
                InlineKeyboardButton("2 Hours", callback_data='goal_2'),
                InlineKeyboardButton("3 Hours", callback_data='goal_3')
            ],
            [
                InlineKeyboardButton("4 Hours", callback_data='goal_4'),
                InlineKeyboardButton("5 Hours", callback_data='goal_5'),
                InlineKeyboardButton("6 Hours", callback_data='goal_6')
            ],
            [
                InlineKeyboardButton("✨ Custom Goal (HH:MM) ✨", callback_data='goal_custom')
            ],
            [
                InlineKeyboardButton("No Goal ❌", callback_data='no_goal'),
                InlineKeyboardButton("Cancel ⬅️", callback_data='cancel_operation')
            ]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)
        
        message_id = await self.send_bot_message(
            context,
            update.effective_chat.id,
            "How long would you like to study? 🎯\nChoose a goal or set a custom duration (HH:MM):",
            reply_markup=reply_markup
        )
        
        # Update pending session for this user
        user_id = update.effective_user.id
        if user_id in self.pending_sessions:
            self.pending_sessions[user_id].message_ids.append(message_id)
        
        try:
            await query.message.delete()
        except Exception as e:
            logger.error(f"Error deleting message: {e}")
        
        return SETTING_GOAL

    async def handle_goal_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle goal selection or prompt for custom goal."""
        self.record_activity()
        query = update.callback_query
        await query.answer()
        
        # Check if we're in a topic/thread
        if update.callback_query.message and update.callback_query.message.is_topic_message:
            # Update the thread_id in user_data
            context.user_data['thread_id'] = update.callback_query.message.message_thread_id
        
        try:
            await query.message.delete()
        except Exception as e:
            logger.error(f"Error deleting message: {e}")

        if query.data == 'goal_custom':
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Please enter your study goal in HH:MM format (e.g., 01:30 for 1 hour 30 minutes):"
            )
            
            # Update pending session for this user
            user_id = update.effective_user.id
            if user_id in self.pending_sessions:
                self.pending_sessions[user_id].message_ids.append(message_id)
                
            return SETTING_CUSTOM_GOAL
        
        goal_time = query.data.split('_')[1] if query.data != 'no_goal' else None
        context.user_data['goal_time'] = goal_time
        
        return await self.show_subject_selection(update, context)

    async def handle_custom_goal(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle custom goal time input."""
        self.record_activity()
        try:
            goal_input = update.message.text.strip()
            hours, minutes = map(int, goal_input.split(':'))
            
            if hours < 0 or minutes < 0 or minutes >= 60:
                raise ValueError
                
            context.user_data['goal_time'] = goal_input
            
            # Store the thread_id if the message is in a topic
            if update.message and update.message.is_topic_message:
                context.user_data['thread_id'] = update.message.message_thread_id
            
            try:
                await update.message.delete()
            except Exception as e:
                logger.error(f"Error deleting message: {e}")
            
            return await self.show_subject_selection(update, context)
            
        except ValueError:
            message_id = await self.send_bot_message(
                context,
                update.effective_chat.id,
                "⚠️ Please enter a valid time in HH:MM format (e.g., 01:30 for 1 hour 30 minutes):"
            )
            
            # Update pending session for this user
            user_id = update.effective_user.id
            if user_id in self.pending_sessions:
                self.pending_sessions[user_id].message_ids.append(message_id)
                
            return SETTING_CUSTOM_GOAL

    async def show_subject_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Show subject selection buttons."""
        self.record_activity()
        context.user_data['previous_state'] = SETTING_GOAL
        buttons = []
        current_row = []
        
        for subject_name, subject_code in SUBJECTS.items():
            current_row.append(InlineKeyboardButton(
                subject_name, 
                callback_data=f'subject_{subject_code}'
            ))
            
            if len(current_row) == 3:
                buttons.append(current_row)
                current_row = []
        
        if current_row:
            buttons.append(current_row)
            
        buttons.append([InlineKeyboardButton("Cancel ⬅️", callback_data='cancel_operation')])
        
        reply_markup = InlineKeyboardMarkup(buttons)
        
        message_id = await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Choose your subject: 📚",
            reply_markup=reply_markup,
            should_delete=True
        )
        
        # Update pending session for this user
        user_id = update.effective_user.id
        if user_id in self.pending_sessions:
            self.pending_sessions[user_id].message_ids.append(message_id)
        
        return CHOOSING_SUBJECT

    async def start_studying(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Start a study session for the selected subject."""
        self.record_activity()
        query = update.callback_query
        await query.answer()
        
        # Check if we're in a topic/thread
        if update.callback_query.message and update.callback_query.message.is_topic_message:
            # Update the thread_id in user_data
            context.user_data['thread_id'] = update.callback_query.message.message_thread_id
        
        try:
            await query.message.delete()
        except Exception as e:
            logger.error(f"Error deleting message: {e}")

        user = update.effective_user
        subject_code = query.data.split('_')[1]
        subject_name = next((name for name, code in SUBJECTS.items() if code == subject_code), subject_code)
        
        self.study_sessions[user.id] = StudySession(
            user_id=user.id,
            subject=subject_name,
            goal_time=context.user_data.get('goal_time')
        )
        
        session_start_time = self.study_sessions[user.id].start_time.astimezone(MANILA_TZ)
        
        user_name = user.first_name or user.username or "User"
        await self.send_bot_message(
            context,
            update.effective_chat.id,
            f"🚀 {user_name} started a new session!",
            should_delete=False
        )
        
        await self.send_bot_message(
            context,
            update.effective_chat.id,
            f"Subject: {subject_name}",
            should_delete=False
        )
        
        await self.send_bot_message(
            context,
            update.effective_chat.id,
            f"Started at: {session_start_time.strftime('%I:%M %p')}",
            should_delete=True
        )
        
        if context.user_data.get('goal_time'):
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"Goal: {context.user_data['goal_time']}h",
                should_delete=True
            )

        buttons = [
            [
                InlineKeyboardButton("Take a Break ☕", callback_data='start_break'),
                InlineKeyboardButton("End Session ⏹️", callback_data='end_session')
            ],
            [InlineKeyboardButton("Cancel ⬅️", callback_data='cancel_operation')]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)

        await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Session Controls:",
            reply_markup=reply_markup,
            should_delete=True
        )
        
        # Remove this user from pending sessions as they've completed setup
        if user.id in self.pending_sessions:
            del self.pending_sessions[user.id]
        
        return STUDYING

    async def handle_break(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle break start/end."""
        self.record_activity()
        query = update.callback_query
        await query.answer()
        
        # Check if we're in a topic/thread
        if update.callback_query.message and update.callback_query.message.is_topic_message:
            # Update the thread_id in user_data
            context.user_data['thread_id'] = update.callback_query.message.message_thread_id
        
        try:
            await query.message.delete()
        except Exception as e:
            logger.error(f"Error deleting message: {e}")
    
        user = update.effective_user
        session = self.study_sessions.get(user.id)
        
        if not session:
            # CHANGED: Don't call start() here, just show an error message
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "No active study session found. Please start a new session."
            )
            buttons = [[InlineKeyboardButton("Start New Study Session 📚", callback_data='start_studying')]]
            reply_markup = InlineKeyboardMarkup(buttons)
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Start a new session?",
                reply_markup=reply_markup
            )
            return CHOOSING_MAIN_MENU
    
        if query.data == 'start_break':
            session.start_break()
            buttons = [
                [
                    InlineKeyboardButton("End Break ▶️", callback_data='end_break'),
                    InlineKeyboardButton("End Session ⏹️", callback_data='end_session')
                ],
                [InlineKeyboardButton("Cancel ⬅️", callback_data='cancel_operation')]
            ]
            reply_markup = InlineKeyboardMarkup(buttons)
            
            break_start_time = datetime.datetime.now(PST_TZ).astimezone(MANILA_TZ)
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"☕ Break started at {break_start_time.strftime('%I:%M %p')}",
                reply_markup=reply_markup,
                should_delete=False
            )
            return ON_BREAK
                
        elif query.data == 'end_break':
            session.end_break()
            buttons = [
                [
                    InlineKeyboardButton("Take a Break ☕", callback_data='start_break'),
                    InlineKeyboardButton("End Session ⏹️", callback_data='end_session')
                ],
                [InlineKeyboardButton("Cancel ⬅️", callback_data='cancel_operation')]
            ]
            reply_markup = InlineKeyboardMarkup(buttons)
            
            break_end_time = datetime.datetime.now(PST_TZ).astimezone(MANILA_TZ)
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"▶️ Break ended at {break_end_time.strftime('%I:%M %p')}\nBack to studying!",
                reply_markup=reply_markup,
                should_delete=False
            )
            return STUDYING

    async def end_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """End the study session and show summary."""
        self.record_activity()
        query = update.callback_query
        await query.answer()
        
        # Check if we're in a topic/thread
        if update.callback_query.message and update.callback_query.message.is_topic_message:
            # Update the thread_id in user_data
            context.user_data['thread_id'] = update.callback_query.message.message_thread_id
        
        try:
            await query.message.delete()
        except Exception as e:
            logger.error(f"Error deleting message: {e}")
    
        user = update.effective_user
        session = self.study_sessions.get(user.id)
        
        if not session:
            # CHANGED: Don't call start() here, just show an error message
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "No active study session found. Please start a new session."
            )
            buttons = [[InlineKeyboardButton("Start New Study Session 📚", callback_data='start_studying')]]
            reply_markup = InlineKeyboardMarkup(buttons)
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Start a new session?",
                reply_markup=reply_markup
            )
            return CHOOSING_MAIN_MENU
    
        session.end()
        manila_times = session.get_formatted_manila_times()
        
        try:
            user_name = user.first_name or user.username or "User"
            summary_msg = await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"🚧 {user_name} ended the session 🚧",
                should_delete=False
            )
            
            if 'messages_to_keep' not in context.user_data:
                context.user_data['messages_to_keep'] = []
            context.user_data['messages_to_keep'].append(summary_msg)
    
            study_time = session.get_total_study_time()
            study_time_msg = await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"Total Study Time: {int(study_time.total_seconds() // 3600)}h {int((study_time.total_seconds() % 3600) // 60)}m",
                should_delete=False
            )
            context.user_data['messages_to_keep'].append(study_time_msg)
    
            session_info = [
                f"Started: {manila_times['start'].strftime('%I:%M %p')}",
                f"Ended: {manila_times['end'].strftime('%I:%M %p')}"
            ]
            
            if context.user_data.get('goal_time'):
                progress_percentage = session.get_progress_percentage()
                session_info.append("")
                session_info.append(f"Goal Progress: {progress_percentage}%")
            
            if session.break_periods:
                session_info.append("")
                session_info.append("Break Details:")
                for break_period in manila_times['breaks']:
                    session_info.append(
                        f"Break: {break_period['start'].strftime('%I:%M %p')} - "
                        f"{break_period['end'].strftime('%I:%M %p')}"
                    )
            
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "\n".join(session_info),
                should_delete=True
            )
    
            celebration_msg = await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"🎉",
                should_delete=False
            )
            context.user_data['messages_to_keep'].append(celebration_msg)
    
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                f"꧁RMT KA NA SA AUGUST꧂",
                should_delete=True
            )
    
            # Save completed session to database
            user_name = user.first_name or user.username or "User"
            self.db.save_study_session(user.id, user_name, session)
            
            # Store the session dictionary for PDF generation
            session_dict = session.to_dict()
            context.user_data['last_session'] = session_dict
            
            # Add buttons to download study reports
            buttons = [
                [
                    InlineKeyboardButton("THIS SESSION", callback_data='report_session')
                ]
            ]
            report_markup = InlineKeyboardMarkup(buttons)
            
            report_msg = await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Would you like to check your progress report in PDF?",
                reply_markup=report_markup,
                should_delete=True
            )
            
            buttons = [[InlineKeyboardButton("Start New Study Session 📚", callback_data='start_studying')]]
            reply_markup = InlineKeyboardMarkup(buttons)
            
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Ready to start another study session?",
                reply_markup=reply_markup
            )
    
        except Exception as e:
            logger.error(f"Error in end_session: {e}")
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "There was an error ending your session. Please try again."
            )
    
        del self.study_sessions[user.id]
        return CHOOSING_MAIN_MENU

    async def generate_session_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Generate and send PDF report for the last completed session."""
        self.record_activity()
        query = update.callback_query
        await query.answer()
        
        # Check if we're in a topic/thread
        if update.callback_query.message and update.callback_query.message.is_topic_message:
            # Update the thread_id in user_data
            context.user_data['thread_id'] = update.callback_query.message.message_thread_id
        
        try:
            await query.message.delete()
        except Exception as e:
            logger.error(f"Error deleting message: {e}")
        
        user = update.effective_user
        user_name = user.first_name or user.username or "User"
        
        # Get the last session from context
        last_session = context.user_data.get('last_session')
        
        if not last_session:
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Sorry, I couldn't find your last session data.",
                should_delete=True
            )
            return CHOOSING_MAIN_MENU
        
        await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Generating your session report... Please wait...",
            should_delete=True
        )
        
        try:
            # Generate PDF
            pdf_buffer = self.pdf_generator.generate_session_report(user_name, last_session)
            
            # Send the PDF file
            await self.send_document(
                context,
                update.effective_chat.id,
                pdf_buffer,
                filename=f"Session Report - {user_name}, RMT.pdf",
                caption=f"Here's your session report, {user_name}!"
            )
            
            # Delete the PDF generation message
            buttons = [[InlineKeyboardButton("Start New Study Session 📚", callback_data='start_studying')]]
            reply_markup = InlineKeyboardMarkup(buttons)
            
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Ready to start another study session?",
                reply_markup=reply_markup,
                should_delete=True
            )
            
        except Exception as e:
            logger.error(f"Error generating session report: {e}")
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Sorry, there was an error generating your session report.",
                should_delete=True
            )
            
        return CHOOSING_MAIN_MENU

    async def generate_day_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Generate and send PDF report for today's sessions."""
        self.record_activity()
        query = update.callback_query
        await query.answer()
        
        # Check if we're in a topic/thread
        if update.callback_query.message and update.callback_query.message.is_topic_message:
            # Update the thread_id in user_data
            context.user_data['thread_id'] = update.callback_query.message.message_thread_id
        
        try:
            await query.message.delete()
        except Exception as e:
            logger.error(f"Error deleting message: {e}")
        
        user = update.effective_user
        user_name = user.first_name or user.username or "User"
        
        # Get today's date
        today = datetime.datetime.now(MANILA_TZ).date()
        
        await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Generating your daily study report... Please wait...",
            should_delete=True
        )
        
        try:
            # Get today's sessions
            today_sessions = self.db.get_sessions_for_date(user.id, today)
            
            if not today_sessions:
                await self.send_bot_message(
                    context,
                    update.effective_chat.id,
                    "No study sessions found for today.",
                    should_delete=True
                )
                return CHOOSING_MAIN_MENU
            
            # Generate PDF
            pdf_buffer = self.pdf_generator.generate_daily_report(user_name, today, today_sessions)
            
            # Send the PDF file
            await self.send_document(
                context,
                update.effective_chat.id,
                pdf_buffer,
                filename=f"Daily Study Report {today.strftime('%Y-%m-%d')} - {user_name}, RMT.pdf",
                caption=f"Here's your daily study report, {user_name}!"
            )
            
            # Delete the PDF generation message
            buttons = [[InlineKeyboardButton("Start New Study Session 📚", callback_data='start_studying')]]
            reply_markup = InlineKeyboardMarkup(buttons)
            
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Ready to start another study session?",
                reply_markup=reply_markup,
                should_delete=True
            )
            
        except Exception as e:
            logger.error(f"Error generating day report: {e}")
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Sorry, there was an error generating your daily report.",
                should_delete=True
            )
            
        return CHOOSING_MAIN_MENU

    async def generate_overall_progress_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Generate and send overall progress report as PDF."""
        self.record_activity()
        
        # Handle callback query if this was triggered by button
        if update.callback_query:
            query = update.callback_query
            await query.answer()
            
            # Check if we're in a topic/thread
            if update.callback_query.message and update.callback_query.message.is_topic_message:
                # Update the thread_id in user_data
                context.user_data['thread_id'] = update.callback_query.message.message_thread_id
            
            try:
                # Don't delete the main menu message
                if update.callback_query.message.text != "Welcome to RMT Study Bot! 📚✨":
                    await query.message.delete()
            except Exception as e:
                logger.error(f"Error deleting message: {e}")
        
        user = update.effective_user
        user_name = user.first_name or user.username or "User"
        
        await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Generating your overall study progress report... Please wait...",
            should_delete=True
        )
        
        try:
            # Get all study sessions for this user
            all_sessions = self.db.get_user_study_sessions(user.id)
            
            if not all_sessions:
                await self.send_bot_message(
                    context,
                    update.effective_chat.id,
                    "You don't have any study sessions recorded yet. Start studying to build your progress report!",
                    should_delete=True
                )
                return CHOOSING_MAIN_MENU
            
            # Generate PDF
            pdf_buffer = self.pdf_generator.generate_full_report(user_name, all_sessions)
            
            # Send the PDF file
            await self.send_document(
                context,
                update.effective_chat.id,
                pdf_buffer,
                filename=f"Study Progress Report of {user_name}, RMT.pdf",
                caption=f"Here's your complete study progress report, {user_name}!"
            )
            
            # Show start studying button
            buttons = [[InlineKeyboardButton("Start New Study Session 📚", callback_data='start_studying')]]
            reply_markup = InlineKeyboardMarkup(buttons)
            
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Ready to start another study session?",
                reply_markup=reply_markup,
                should_delete=True
            )
            
            return CHOOSING_MAIN_MENU
            
        except Exception as e:
            logger.error(f"Error generating overall progress report: {e}")
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Sorry, there was an error generating your progress report. Please try again later.",
                should_delete=True
            )
            return CHOOSING_MAIN_MENU

    async def generate_today_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Generate and send today's study report as PDF."""
        self.record_activity()
        
        # Handle callback query if this was triggered by button
        if update.callback_query:
            query = update.callback_query
            await query.answer()
            
            # Check if we're in a topic/thread
            if update.callback_query.message and update.callback_query.message.is_topic_message:
                # Update the thread_id in user_data
                context.user_data['thread_id'] = update.callback_query.message.message_thread_id
            
            try:
                # Don't delete the main menu message
                if update.callback_query.message.text != "Welcome to RMT Study Bot! 📚✨":
                    await query.message.delete()
            except Exception as e:
                logger.error(f"Error deleting message: {e}")
        
        user = update.effective_user
        user_name = user.first_name or user.username or "User"
        
        await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Generating your study report for today... Please wait...",
            should_delete=True
        )
        
        try:
            # Get today's date in Manila timezone
            today = datetime.datetime.now(MANILA_TZ).date()
            logger.info(f"Today's date in Manila: {today}")
            
            # Get all sessions for debugging
            all_sessions = self.db.get_user_study_sessions(user.id)
            logger.info(f"User has {len(all_sessions)} total sessions")
            
            # Debug: Print all session dates
            for idx, session in enumerate(all_sessions):
                try:
                    # Make sure start_time is a datetime
                    if isinstance(session['start_time'], str):
                        session['start_time'] = datetime.datetime.fromisoformat(session['start_time'])
                        
                    manila_time = session['start_time'].astimezone(MANILA_TZ)
                    logger.info(f"Session {idx}: {manila_time.date()}")
                except Exception as e:
                    logger.error(f"Error examining session {idx}: {e}")
                    
            # Get study sessions for today
            today_sessions = self.db.get_sessions_for_date(user.id, today)
            
            logger.info(f"Found {len(today_sessions)} sessions for user {user.id} on {today}")
            
            if not today_sessions:
                await self.send_bot_message(
                    context,
                    update.effective_chat.id,
                    "You don't have any study sessions recorded for today. Start studying to build your daily report!",
                    should_delete=True
                )
                return CHOOSING_MAIN_MENU
            
            # Generate PDF
            pdf_buffer = self.pdf_generator.generate_daily_report(user_name, today, today_sessions)
            
            # Send the PDF file
            await self.send_document(
                context,
                update.effective_chat.id,
                pdf_buffer,
                filename=f"Daily Study Report {today.strftime('%Y-%m-%d')} - {user_name}, RMT.pdf",
                caption=f"Here's your study report for today, {user_name}!"
            )
            
            # Show start studying button
            buttons = [[InlineKeyboardButton("Start New Study Session 📚", callback_data='start_studying')]]
            reply_markup = InlineKeyboardMarkup(buttons)
            
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Ready to start another study session?",
                reply_markup=reply_markup,
                should_delete=True
            )
            
            return CHOOSING_MAIN_MENU
            
        except Exception as e:
            logger.error(f"Error generating today's report: {e}")
            import traceback
            logger.error(traceback.format_exc())  # Print full traceback
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Sorry, there was an error generating your daily report. Please try again later.",
                should_delete=True
            )
            return CHOOSING_MAIN_MENU
    
    async def get_last_session_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Generate and send the last completed session report."""
        self.record_activity()
        
        # Handle callback query if this was triggered by button
        if update.callback_query:
            query = update.callback_query
            await query.answer()
            
            # Check if we're in a topic/thread
            if update.callback_query.message and update.callback_query.message.is_topic_message:
                # Update the thread_id in user_data
                context.user_data['thread_id'] = update.callback_query.message.message_thread_id
            
            try:
                # Don't delete the main menu message
                if update.callback_query.message.text != "Welcome to RMT Study Bot! 📚✨":
                    await query.message.delete()
            except Exception as e:
                logger.error(f"Error deleting message: {e}")
        
        user = update.effective_user
        user_name = user.first_name or user.username or "User"
        
        await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Retrieving your last study session report... Please wait...",
            should_delete=True
        )
        
        try:
            # Get all study sessions for this user
            all_sessions = self.db.get_user_study_sessions(user.id)
            
            if not all_sessions:
                await self.send_bot_message(
                    context,
                    update.effective_chat.id,
                    "You don't have any study sessions recorded yet. Start studying to generate session reports!",
                    should_delete=True
                )
                return CHOOSING_MAIN_MENU
            
            # Find the most recent completed session
            last_session = max(all_sessions, key=lambda s: s['start_time'])
            
            # Generate PDF
            pdf_buffer = self.pdf_generator.generate_session_report(user_name, last_session)
            
            # Send the PDF file
            await self.send_document(
                context,
                update.effective_chat.id,
                pdf_buffer,
                filename=f"Last Session Report - {user_name}, RMT.pdf",
                caption=f"Here's your last study session report, {user_name}!"
            )
            
            # Show start studying button
            buttons = [[InlineKeyboardButton("Start New Study Session 📚", callback_data='start_studying')]]
            reply_markup = InlineKeyboardMarkup(buttons)
            
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Ready to start another study session?",
                reply_markup=reply_markup,
                should_delete=True
            )
            
        except Exception as e:
            logger.error(f"Error generating last session report: {e}")
            import traceback
            logger.error(traceback.format_exc())  # Print full traceback
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Sorry, there was an error generating your last session report. Please try again later.",
                should_delete=True
            )
        
        return CHOOSING_MAIN_MENU
        
    async def cancel_operation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Show cancel confirmation dialog."""
        self.record_activity()
        query = update.callback_query
        if query:
            await query.answer()
            
            # Check if we're in a topic/thread
            if update.callback_query.message and update.callback_query.message.is_topic_message:
                # Update the thread_id in user_data
                context.user_data['thread_id'] = update.callback_query.message.message_thread_id
            
            try:
                await query.message.delete()
            except Exception as e:
                logger.error(f"Error deleting message: {e}")

        buttons = [
            [
                InlineKeyboardButton("Yes ✅", callback_data='confirm_cancel'),
                InlineKeyboardButton("No ❌", callback_data='reject_cancel')
            ]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)
        
        message_id = await self.send_bot_message(
            context,
            update.effective_chat.id,
            "Are you sure you want to cancel?",
            reply_markup=reply_markup,
            should_delete=True
        )
        
        # Update pending session for this user
        user_id = update.effective_user.id
        if user_id in self.pending_sessions:
            self.pending_sessions[user_id].message_ids.append(message_id)
        
        return CONFIRMING_CANCEL

    async def handle_cancel_confirmation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the cancel confirmation response."""
        self.record_activity()
        query = update.callback_query
        await query.answer()
        
        # Check if we're in a topic/thread
        if update.callback_query.message and update.callback_query.message.is_topic_message:
            # Update the thread_id in user_data
            context.user_data['thread_id'] = update.callback_query.message.message_thread_id
        
        try:
            await query.message.delete()
        except Exception as e:
            logger.error(f"Error deleting message: {e}")
    
        if query.data == 'confirm_cancel':
            user = update.effective_user
            if user.id in self.study_sessions:
                del self.study_sessions[user.id]
            
            # Also remove from pending sessions
            if user.id in self.pending_sessions:
                del self.pending_sessions[user.id]
            
            await self.cleanup_messages(update, context)
            
            # CHANGED: Don't call start() which creates a new conversation
            # Instead, just show options to start a new session
            buttons = [[InlineKeyboardButton("Start New Study Session 📚", callback_data='start_studying')]]
            reply_markup = InlineKeyboardMarkup(buttons)
            
            await self.send_bot_message(
                context,
                update.effective_chat.id,
                "Operation cancelled. Would you like to start a new session?",
                reply_markup=reply_markup,
                should_delete=True
            )
            return CHOOSING_MAIN_MENU
            
        else:
            return context.user_data.get('previous_state', CHOOSING_MAIN_MENU)

# ================== ERROR HANDLER ==================
async def error_handler(update, context):
    """Handle errors in the telegram bot."""
    if isinstance(context.error, Conflict):  # Using Conflict directly now that it's properly imported
        logger.error("Conflict error detected: Another instance is running. Shutting down this instance.")
        shared_state.is_shutting_down = True
        os._exit(1)  # Force exit to allow Render to restart a fresh instance
    else:
        logger.error(f"Exception while handling an update: {context.error}")

# ================== SELF-PING FUNCTION ==================
def self_ping():
    """Ping our own health endpoint to keep the service alive."""
    try:
        import urllib.request
        port = int(os.getenv('HEALTH_CHECK_PORT', os.getenv('PORT', 10001)))
        urllib.request.urlopen(f"http://localhost:{port}/health", timeout=10)
    except Exception as e:
        logger.warning(f"Self-ping failed: {e}")

# ================== FORCE CLEAR UPDATES ==================
async def force_clear_telegram_updates(token):
    """Force clear any pending updates from Telegram."""
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            # First try to get current update_id
            url = f"https://api.telegram.org/bot{token}/getUpdates?limit=1"
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    updates = data.get('result', [])
                    if updates:
                        next_update = updates[0]['update_id'] + 1
                        # Clear all updates by setting offset
                        clear_url = f"https://api.telegram.org/bot{token}/getUpdates?offset={next_update}"
                        async with session.get(clear_url, timeout=10) as clear_response:
                            if clear_response.status == 200:
                                logger.info("Successfully cleared pending updates")
                            else:
                                logger.warning(f"Failed to clear updates: {await clear_response.text()}")
                    else:
                        logger.info("No pending updates to clear")
                else:
                    logger.warning(f"Failed to get updates: {await response.text()}")
    except Exception as e:
        logger.error(f"Error in force_clear_updates: {e}")

# ================== RELIABILITY IMPROVEMENTS ==================
async def run_bot_with_retries():
    """Run the bot with automatic retries and permanent operation"""
    keepalive_server = KeepaliveServer()
    keepalive_server.start()
    
    max_retries = 10
    retry_delay = 30
    
    for attempt in range(max_retries):
        if shared_state.is_shutting_down:
            logger.info("Shutdown signal received. Exiting...")
            break
            
        try:
            # Create application with proper token
            token = os.getenv('TELEGRAM_BOT_TOKEN')
            if not token:
                logger.error("No TELEGRAM_BOT_TOKEN provided in environment variables")
                sys.exit(1)
            
            # First forcefully delete any existing webhook and clear updates
            await force_clear_telegram_updates(token)
            
            # Make sure persistence directory exists
            persistence_dir = os.path.dirname(PERSISTENCE_PATH)
            if persistence_dir and not os.path.exists(persistence_dir):
                try:
                    os.makedirs(persistence_dir, exist_ok=True)
                except Exception as e:
                    logger.warning(f"Could not create persistence directory: {e}")
            
            # Create persistence object to maintain conversation state across restarts
            try:
                persistence = PicklePersistence(
                    filepath=PERSISTENCE_PATH,
                    store_data=PersistenceInput(
                        chat_data=True,
                        user_data=True,
                        bot_data=True,
                        callback_data=True  # Important for buttons to work after restart
                    ),
                    update_interval=60,  # Save every 60 seconds
                )
                logger.info(f"Created persistence with file: {PERSISTENCE_PATH}")
            except Exception as e:
                logger.error(f"Error creating persistence: {e}")
                persistence = None
                
            # Set up proper drop_pending_updates to avoid handling old messages
            builder = ApplicationBuilder().token(token)
            if persistence:
                builder = builder.persistence(persistence)
            
            application = builder.build()
            
            telegram_bot = TelegramBot()
            telegram_bot.application = application
            
            # Store in shared state
            shared_state.telegram_bot = telegram_bot
            
            # Add command handlers
            application.add_handler(CommandHandler('start', telegram_bot.start))
            application.add_handler(CommandHandler('MYSTUDYdownload', telegram_bot.generate_overall_progress_report))
            application.add_handler(CommandHandler('MYSTUDYtoday', telegram_bot.generate_today_report))
            application.add_handler(CommandHandler('reset_mydata', telegram_bot.reset_user_data))
            
            # Add reset data confirmation handlers
            application.add_handler(CallbackQueryHandler(telegram_bot.handle_reset_confirmation, pattern='^confirm_reset_data$'))
            application.add_handler(CallbackQueryHandler(telegram_bot.handle_reset_confirmation, pattern='^cancel_reset_data$'))
            
            conv_handler = ConversationHandler(
                entry_points=[
                    CallbackQueryHandler(telegram_bot.ask_goal, pattern='^start_studying$'),
                    CallbackQueryHandler(telegram_bot.generate_overall_progress_report, pattern='^overall_progress$'),
                    CallbackQueryHandler(telegram_bot.generate_today_report, pattern='^today_report$'),
                    CallbackQueryHandler(telegram_bot.generate_session_report, pattern='^report_session$'),
                    CallbackQueryHandler(telegram_bot.generate_day_report, pattern='^report_day$'),
                    CallbackQueryHandler(telegram_bot.generate_overall_progress_report, pattern='^report_overall$'),
                    # Add the new handler for last session report
                    CallbackQueryHandler(telegram_bot.get_last_session_report, pattern='^last_session_report$')
                ],
                states={
                    CONFIRMING_CANCEL: [
                        CallbackQueryHandler(telegram_bot.handle_cancel_confirmation, pattern='^confirm_cancel$'),
                        CallbackQueryHandler(telegram_bot.handle_cancel_confirmation, pattern='^reject_cancel$')
                    ],
                    CHOOSING_MAIN_MENU: [
                        CallbackQueryHandler(telegram_bot.ask_goal, pattern='^start_studying$'),
                        CallbackQueryHandler(telegram_bot.generate_overall_progress_report, pattern='^overall_progress$'),
                        CallbackQueryHandler(telegram_bot.generate_today_report, pattern='^today_report$'),
                        CallbackQueryHandler(telegram_bot.generate_session_report, pattern='^report_session$'),
                        CallbackQueryHandler(telegram_bot.generate_day_report, pattern='^report_day$'),
                        CallbackQueryHandler(telegram_bot.generate_overall_progress_report, pattern='^report_overall$'),
                        # Add the new handler for last session report
                        CallbackQueryHandler(telegram_bot.get_last_session_report, pattern='^last_session_report$')
                    ],
                    SETTING_GOAL: [
                        CallbackQueryHandler(telegram_bot.handle_goal_selection, pattern='^goal_'),
                        CallbackQueryHandler(telegram_bot.handle_goal_selection, pattern='^no_goal$'),
                        CallbackQueryHandler(telegram_bot.cancel_operation, pattern='^cancel_operation$')
                    ],
                    SETTING_CUSTOM_GOAL: [
                        MessageHandler(filters.TEXT & ~filters.COMMAND, telegram_bot.handle_custom_goal),
                        CallbackQueryHandler(telegram_bot.cancel_operation, pattern='^cancel_operation$')
                    ],
                    CHOOSING_SUBJECT: [
                        CallbackQueryHandler(telegram_bot.start_studying, pattern='^subject_'),
                        CallbackQueryHandler(telegram_bot.cancel_operation, pattern='^cancel_operation$')
                    ],
                    STUDYING: [
                        CallbackQueryHandler(telegram_bot.handle_break, pattern='^start_break$'),
                        CallbackQueryHandler(telegram_bot.end_session, pattern='^end_session$'),
                        CallbackQueryHandler(telegram_bot.cancel_operation, pattern='^cancel_operation$')
                    ],
                    ON_BREAK: [
                        CallbackQueryHandler(telegram_bot.handle_break, pattern='^end_break$'),
                        CallbackQueryHandler(telegram_bot.end_session, pattern='^end_session$'),
                        CallbackQueryHandler(telegram_bot.cancel_operation, pattern='^cancel_operation$')
                    ]
                },
                fallbacks=[
                    CallbackQueryHandler(telegram_bot.cancel_operation, pattern='^cancel_operation$'),
                    # Add these lines to ensure buttons work even outside state handling
                    CallbackQueryHandler(telegram_bot.handle_break, pattern='^start_break$'),
                    CallbackQueryHandler(telegram_bot.handle_break, pattern='^end_break$'), 
                    CallbackQueryHandler(telegram_bot.end_session, pattern='^end_session$')
                ],
                per_chat=True,
                name="main_conversation",
                persistent=True if persistence else False  # Enable persistence only if available
            )

            application.add_handler(conv_handler)

            application.add_handler(CallbackQueryHandler(telegram_bot.handle_break, pattern='^start_break$'))
            application.add_handler(CallbackQueryHandler(telegram_bot.handle_break, pattern='^end_break$'))
            application.add_handler(CallbackQueryHandler(telegram_bot.end_session, pattern='^end_session$'))

            application.add_error_handler(error_handler)
            
            # First try to delete any existing webhook
            await application.bot.delete_webhook(drop_pending_updates=True)
            
            # Initialize and start the application
            await application.initialize()
            await application.start()
            
            # Start polling with critical fix: force drop_pending_updates=True
            # This fixes the "terminated by other getUpdates request" error
            await application.updater.start_polling(
                poll_interval=3,
                timeout=30,
                drop_pending_updates=True,
                read_timeout=30,
                write_timeout=30
            )
            
            logger.info("Bot is now running and polling 24/7")
            logger.info(f"Current Date and Time (UTC - YYYY-MM-DD HH:MM:SS formatted): {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info(f"Current User's Login: {CURRENT_USER}")

            # Self-healing watchdog
            last_health_check = datetime.datetime.now()
            while not shared_state.is_shutting_down:
                current_time = datetime.datetime.now()
                
                # Check for inactivity and perform health check
                inactive_time = (current_time - telegram_bot.last_activity).total_seconds()
                health_check_due = (current_time - last_health_check).total_seconds() > 300  # Every 5 minutes
                
                if inactive_time > 3600:  # 1 hour inactivity threshold
                    logger.warning(f"No activity for {inactive_time//60} minutes, performing health check...")
                    try:
                        await application.bot.get_me()
                        logger.info("Health check passed despite inactivity")
                        telegram_bot.last_activity = current_time  # Reset activity timer
                    except Exception as e:
                        logger.error(f"Health check failed after inactivity: {e}")
                        raise RuntimeError("Activity timeout and health check failure")
                
                # Periodic health check regardless of activity
                if health_check_due:
                    try:
                        await application.bot.get_me()
                        logger.debug("Periodic health check passed")
                        last_health_check = current_time
                    except Exception as e:
                        logger.error(f"Periodic health check failed: {e}")
                        raise RuntimeError("Health check failure")
                
                # Perform a self-ping to keep Render instance alive
                if current_time.minute % 10 == 0 and current_time.second < 10:
                    try:
                        self_ping()
                        logger.debug("Self-ping performed")
                    except Exception as e:
                        logger.warning(f"Self-ping failed: {e}")
                
                await asyncio.sleep(10)  # Check more frequently
            
            # Clean shutdown if we get here
            logger.info("Shutting down bot gracefully...")
            await application.stop()
            await application.shutdown()
            break
            
        except Conflict as e:  # Using Conflict directly now that it's properly imported
            logger.error(f"Conflict error: {e}. Another instance is likely running.")
            shared_state.is_shutting_down = True
            break
            
        except Exception as e:
            logger.error(f"Attempt {attempt + 1} failed: {str(e)}")
            if attempt < max_retries - 1 and not shared_state.is_shutting_down:
                logger.info(f"Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 1.5, 300)  # Exponential backoff, max 5 minutes
            else:
                logger.error("Max retries reached or shutdown requested. Exiting...")
                break
    
    # Stop the keepalive server
    keepalive_server.stop()
    
    if shared_state.is_shutting_down:
        logger.info("Process is shutting down.")
    else:
        logger.error("Bot failed to start after maximum retries.")

# ================== SIGNAL HANDLERS ==================
def handle_sigterm(signum, frame):
    """Handle SIGTERM gracefully."""
    logger.info("Received SIGTERM signal. Initiating shutdown...")
    shared_state.is_shutting_down = True

# ================== MAIN ENTRY POINT ==================
def main():
    """Main entry point with reliability enhancements"""
    try:
        # Register signal handlers
        signal.signal(signal.SIGTERM, handle_sigterm)
        signal.signal(signal.SIGINT, handle_sigterm)
        
        # Try to ensure we're the only instance running
        try:
            ensure_single_instance()
        except Exception as e:
            logger.error(f"Error in single instance check: {e}")
        
        # Add version and startup info
        logger.info(f"Starting RMT Study Bot v1.2.0 - 24/7 Edition with Google Drive Persistence")
        logger.info(f"Current Date and Time (UTC - YYYY-MM-DD HH:MM:SS formatted): {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Current User's Login: {CURRENT_USER}")
        logger.info(f"Process ID: {os.getpid()}")
        
        # Run the bot with retries
        asyncio.run(run_bot_with_retries())
        
        logger.info("Bot has shutdown gracefully.")
        sys.exit(0)
        
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        sys.exit(1)

if __name__ == '__main__':
    main()
