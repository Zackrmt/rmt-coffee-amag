# Current information
CURRENT_USER = "Zackrmt"
STARTUP_TIME = "2025-06-04 20:11:44"

# Conversation states
(CHOOSING_MAIN_MENU,
 SETTING_GOAL,
 CONFIRMING_GOAL,
 CHOOSING_SUBJECT,
 STUDYING,
 ON_BREAK,
 CREATING_QUESTION,
 SETTING_CHOICES,
 CONFIRMING_QUESTION,
 SETTING_CORRECT_ANSWER,
 SETTING_EXPLANATION,
 CHOOSING_DESIGN,
 CHOOSING_QUESTION_SUBJECT,
 CONFIRMING_DELETION) = range(14)

# Message Templates
MESSAGES = {
    'welcome': 'Welcome to MTLE Study Bot! Choose an option:',
    'study_start': '📚 {user} started studying {subject}.',
    'break_start': '☕ {user} started their break.',
    'break_end': '⏰ {user} ended their break and resumed studying.',
    'session_end': '📚 {user} ended their review on {subject}. Congrats {user}!',
    'study_time': 'Your total study time: {hours:02d}:{minutes:02d}',
    'break_time': 'Your total break time: {hours:02d}:{minutes:02d}',
    'goal_time': 'Your goal study time was: {goal}',
    'share_prompt': 'Would you like to create and share a progress image?'
}
