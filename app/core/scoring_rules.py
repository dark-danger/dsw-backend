"""
Scoring rules for Faculty/Staff performance leaderboard and Student points logic.
Section 12.4 of Master Build Prompt specifies:
- Task approved on or before due date: +10 points
- Task approved after due date (late): +5 points
- Task declined by admin: -3 points
"""

# Faculty Automatic Ledger Scoring Constants
FACULTY_SCORE_ON_TIME_APPROVAL = 10
FACULTY_SCORE_LATE_APPROVAL = 5
FACULTY_SCORE_DECLINED = -3

def calculate_faculty_task_score(is_late: bool) -> int:
    if is_late:
        return FACULTY_SCORE_LATE_APPROVAL
    return FACULTY_SCORE_ON_TIME_APPROVAL
