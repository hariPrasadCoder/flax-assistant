"""
Enums for Flax Assistant.

SQLAlchemy ORM classes have been removed — the database is now Supabase (PostgREST).
Only the Python enums needed by the rest of the code are kept here.
"""

import enum
import uuid


def new_id() -> str:
    return str(uuid.uuid4())


class TaskStatus(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    done = "done"


class MemoryType(str, enum.Enum):
    # Short-term: conversation turns, recent events
    conversation = "conversation"
    # Task events: created, updated, completed
    task_event = "task_event"
    # Long-term pattern: "Hari procrastinates on design tasks"
    learning = "learning"
    # Context snapshot: what Flaxie knew at a key moment
    context_snapshot = "context_snapshot"
    # Meeting notes pasted by user
    meeting_notes = "meeting_notes"
