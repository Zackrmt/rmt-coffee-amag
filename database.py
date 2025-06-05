import sqlite3
from datetime import datetime
from typing import Dict, List, Optional
from config import DB_CONFIG, SYSTEM_CONFIG

class Database:
    def __init__(self):
        self.conn = sqlite3.connect('study_bot.db')
        self.cur = self.conn.cursor()
        self.setup_database()
    
    def setup_database(self):
        """Create necessary tables if they don't exist."""
        self.cur.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT,
                created_at TEXT,
                last_active TEXT
            );
            
            CREATE TABLE IF NOT EXISTS study_sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT,
                subject TEXT,
                start_time TEXT,
                end_time TEXT,
                duration INTEGER,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            );
            
            CREATE TABLE IF NOT EXISTS breaks (
                break_id TEXT PRIMARY KEY,
                session_id TEXT,
                start_time TEXT,
                end_time TEXT,
                duration INTEGER,
                FOREIGN KEY (session_id) REFERENCES study_sessions (session_id)
            );
            
            CREATE TABLE IF NOT EXISTS study_goals (
                user_id TEXT,
                daily_hours REAL,
                subject TEXT,
                created_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            );
        ''')
        self.conn.commit()
    
    def add_user(self, user_id: str, username: str) -> bool:
        """Add new user to database."""
        try:
            self.cur.execute('''
                INSERT OR REPLACE INTO users (user_id, username, created_at, last_active)
                VALUES (?, ?, ?, ?)
            ''', (user_id, username, SYSTEM_CONFIG['TIMESTAMP'], SYSTEM_CONFIG['TIMESTAMP']))
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Error adding user: {e}")
            return False
    
    def create_study_session(self, user_id: str, subject: str) -> str:
        """Create new study session."""
        session_id = f"session_{int(datetime.now().timestamp())}"
        try:
            self.cur.execute('''
                INSERT INTO study_sessions (session_id, user_id, subject, start_time)
                VALUES (?, ?, ?, ?)
            ''', (session_id, user_id, subject, SYSTEM_CONFIG['TIMESTAMP']))
            self.conn.commit()
            return session_id
        except Exception as e:
            print(f"Error creating session: {e}")
            return None
    
    def end_study_session(self, session_id: str) -> bool:
        """End study session and calculate duration."""
        try:
            self.cur.execute('''
                UPDATE study_sessions
                SET end_time = ?,
                    duration = (
                        strftime('%s', ?) - 
                        strftime('%s', start_time)
                    )
                WHERE session_id = ?
            ''', (SYSTEM_CONFIG['TIMESTAMP'], SYSTEM_CONFIG['TIMESTAMP'], session_id))
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Error ending session: {e}")
            return False
    
    def get_user_stats(self, user_id: str) -> Dict:
        """Get user's study statistics."""
        try:
            self.cur.execute('''
                SELECT 
                    COUNT(*) as total_sessions,
                    SUM(duration) as total_duration,
                    AVG(duration) as avg_duration
                FROM study_sessions
                WHERE user_id = ? AND end_time IS NOT NULL
            ''', (user_id,))
            stats = self.cur.fetchone()
            return {
                'total_sessions': stats[0],
                'total_duration': stats[1] or 0,
                'avg_duration': stats[2] or 0
            }
        except Exception as e:
            print(f"Error getting stats: {e}")
            return {}

    def close(self):
        """Close database connection."""
        self.conn.close()
