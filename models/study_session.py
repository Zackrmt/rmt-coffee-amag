from datetime import datetime, timedelta
from typing import Dict, List, Optional

class StudySession:
    def __init__(self):
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self.subject: Optional[str] = None
        self.goal_time: Optional[str] = None
        self.breaks: List[Dict[str, datetime]] = []
        self.current_break: Optional[Dict[str, datetime]] = None
        self.messages_to_delete: List[int] = []
        self.messages_to_keep: List[int] = []
        self.design_choice: str = 'bar'  # Default design
        self.thread_id: Optional[int] = None

    def start(self, subject: str, goal_time: Optional[str] = None):
        self.start_time = datetime.now(datetime.UTC)
        self.subject = subject
        self.goal_time = goal_time

    def start_break(self):
        self.current_break = {'start': datetime.now(datetime.UTC)}

    def end_break(self):
        if self.current_break:
            self.current_break['end'] = datetime.now(datetime.UTC)
            self.breaks.append(self.current_break)
            self.current_break = None

    def end(self):
        self.end_time = datetime.now(datetime.UTC)

    def get_total_study_time(self) -> timedelta:
        if not self.start_time or not self.end_time:
            return timedelta()
        total_time = self.end_time - self.start_time
        break_time = self.get_total_break_time()
        return total_time - break_time

    def get_total_break_time(self) -> timedelta:
        total_break = timedelta()
        for break_session in self.breaks:
            total_break += break_session['end'] - break_session['start']
        return total_break

    def add_message_to_delete(self, message_id: int):
        self.messages_to_delete.append(message_id)

    def add_message_to_keep(self, message_id: int):
        self.messages_to_keep.append(message_id)
