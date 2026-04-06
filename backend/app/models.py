"""
SQLAlchemy models for Flax Assistant.

Schema design philosophy:
- Everything is time-stamped so the AI can reason about time
- Memory has type + importance so we can compress intelligently
- Nudge log tracks what was sent + response so AI doesn't repeat itself
"""

from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Float, DateTime, Boolean, Text, ForeignKey, Enum
)
from sqlalchemy.orm import relationship, DeclarativeBase
import enum
import uuid


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


# ── Teams & Users ──────────────────────────────────────────────────────────────

class Team(Base):
    __tablename__ = "teams"

    id = Column(String, primary_key=True, default=new_id)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    users = relationship("User", back_populates="team")
    tasks = relationship("Task", back_populates="team")


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=new_id)
    team_id = Column(String, ForeignKey("teams.id"), nullable=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    timezone = Column(String, default="UTC")
    created_at = Column(DateTime, default=datetime.utcnow)

    # Focus / DND mode
    focus_until = Column(DateTime, nullable=True)

    # Google Calendar OAuth tokens (JSON string)
    google_calendar_token = Column(Text, nullable=True)

    # Reflection cycle tracking
    last_reflection_at = Column(DateTime, nullable=True)

    team = relationship("Team", back_populates="users")
    tasks_owned = relationship("Task", foreign_keys="Task.owner_id", back_populates="owner")
    tasks_assigned = relationship("Task", foreign_keys="Task.assignee_id", back_populates="assignee")
    memories = relationship("Memory", back_populates="user")
    nudges = relationship("NudgeLog", back_populates="user")


# ── Tasks ─────────────────────────────────────────────────────────────────────

class TaskStatus(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    done = "done"


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=new_id)
    team_id = Column(String, ForeignKey("teams.id"), nullable=True)
    owner_id = Column(String, ForeignKey("users.id"), nullable=True)
    assignee_id = Column(String, ForeignKey("users.id"), nullable=True)

    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(Enum(TaskStatus), default=TaskStatus.open)

    # Time awareness — critical for AI reasoning
    deadline = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    # Nudge tracking — so AI doesn't over-nudge
    nudge_count = Column(Integer, default=0)
    last_nudged_at = Column(DateTime, nullable=True)

    # Source: "chat" (user told Flaxie), "meeting_notes", "manual", "recurring"
    source = Column(String, default="chat")

    # Is this task visible to the team or private?
    is_team_visible = Column(Boolean, default=True)

    # Priority: 1 (low/background) to 5 (critical)
    priority = Column(Integer, default=3)

    # Blocked state
    is_blocked = Column(Boolean, default=False)
    blocked_reason = Column(String, nullable=True)

    # Recurring task settings
    is_recurring = Column(Boolean, default=False)
    recurrence_days = Column(Integer, nullable=True)

    owner = relationship("User", foreign_keys=[owner_id], back_populates="tasks_owned")
    assignee = relationship("User", foreign_keys=[assignee_id], back_populates="tasks_assigned")
    team = relationship("Team", back_populates="tasks")
    nudge_logs = relationship("NudgeLog", back_populates="task")


# ── Invite Codes ──────────────────────────────────────────────────────────────

class InviteCode(Base):
    __tablename__ = "invite_codes"

    code = Column(String, primary_key=True)
    team_id = Column(String, ForeignKey("teams.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    used = Column(Boolean, default=False)


# ── Memory Layer ──────────────────────────────────────────────────────────────

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


class Memory(Base):
    __tablename__ = "memories"

    id = Column(String, primary_key=True, default=new_id)
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    team_id = Column(String, ForeignKey("teams.id"), nullable=True)

    type = Column(Enum(MemoryType), nullable=False)
    content = Column(Text, nullable=False)  # The actual memory text

    # Time context — when this memory was formed
    created_at = Column(DateTime, default=datetime.utcnow)
    # When this memory expires (None = permanent)
    expires_at = Column(DateTime, nullable=True)

    # Importance 0.0-1.0 (used for compression priority)
    importance = Column(Float, default=0.5)

    # Has this been compressed into a higher-level learning?
    compressed = Column(Boolean, default=False)

    # For task_event memories: which task
    task_id = Column(String, ForeignKey("tasks.id"), nullable=True)

    user = relationship("User", back_populates="memories")


# ── Nudge Log ─────────────────────────────────────────────────────────────────

class NudgeLog(Base):
    __tablename__ = "nudge_logs"

    id = Column(String, primary_key=True, default=new_id)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    task_id = Column(String, ForeignKey("tasks.id"), nullable=True)

    message = Column(Text, nullable=False)
    action_options = Column(String, default="Got it,Let's talk")  # comma-separated

    sent_at = Column(DateTime, default=datetime.utcnow)
    user_response = Column(String, nullable=True)  # which action they picked
    responded_at = Column(DateTime, nullable=True)

    # Was this nudge dismissed without action?
    dismissed = Column(Boolean, default=False)

    user = relationship("User", back_populates="nudges")
    task = relationship("Task", back_populates="nudge_logs")


# ── Chat History ──────────────────────────────────────────────────────────────

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(String, primary_key=True, default=new_id)
    user_id = Column(String, nullable=False)
    role = Column(String, nullable=False)  # "user" | "assistant"
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    task_ids = Column(String, nullable=True)  # comma-separated task IDs referenced
