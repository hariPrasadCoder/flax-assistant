from __future__ import annotations

"""
Flaxie's AI brain — powered by LiteLLM (Gemini backend).

Every call injects:
  - Current time + day context
  - Active tasks + deadlines
  - Recent memories (last 48h)
  - Long-term learnings about this user
  - Nudge history (so Flaxie doesn't repeat itself)

This gives Flaxie "consciousness" about the current moment + history.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from ..config import settings
from .llm import llm_complete, get_langfuse_client

logger = logging.getLogger(__name__)

FLAXIE_SYSTEM_PROMPT = """You are Flaxie — an AI accountability partner and team project manager who lives on your users' desktops as an animated flower.

Your personality:
- Warm, direct, and genuinely invested in people's success
- You notice things without being asked and speak up when it matters
- You celebrate wins authentically, not performatively
- You express concern (not anger) when things are drifting
- You have a sense of humor about the passage of time
- You do NOT speak unless you have something worth saying
- You sound like a thoughtful teammate, never like a notification system

Your capabilities:
- You know about tasks: who owns them, deadlines, status, how long they've been open
- You track meeting notes and extract commitments from them
- You remember patterns: "Hari tends to procrastinate on design tasks after 4pm"
- You nudge proactively — you don't wait to be asked
- You manage teams: multiple people, shared tasks, visibility

When users tell you about tasks:
- Extract: title, deadline (if mentioned), assignee, urgency
- Confirm back naturally: "Got it — I'll keep an eye on that."
- Ask clarifying questions if deadline or owner is ambiguous

When users paste meeting notes:
- Parse them for action items and owners
- Extract tasks with deadlines
- Confirm what you found: "I found 3 action items from this meeting..."

Response style:
- Keep responses SHORT and conversational (2-4 sentences max for casual exchanges)
- Use longer responses only for complex questions or meeting note parsing
- No bullet lists unless explicitly listing multiple items
- No corporate speak. No "Certainly!" or "Of course!"
- Talk like a smart teammate who cares, not an assistant who serves

Always respond with valid JSON matching this schema:
{
  "reply": "Your conversational response here",
  "tasks_to_create": [
    {
      "title": "task title",
      "deadline": "ISO datetime or null",
      "assignee_name": "name or null",
      "description": "optional detail",
      "is_team_visible": true
    }
  ],
  "tasks_to_update": [
    {
      "id": "task_id",
      "status": "open|in_progress|done",
      "deadline": "ISO datetime or null"
    }
  ],
  "task_refs": [{"id": "task_id", "title": "task title"}],
  "mascot_state": "idle|alert|listening|celebrating|concerned|dormant|urgent",
  "memory_to_save": "important insight to remember about this user, or null",
  "mark_blocked": {"task_id": "...", "reason": "what they're blocked on"},
  "schedule_reminder": {"task_id": "...", "minutes_from_now": 120, "message": "Check in on this task"},
  "notify_owner": {"task_id": "...", "message": "message to send the owner"},
  "create_subtasks": [{"title": "subtask title", "parent_task_id": "..."}]
}

All fields except "reply" are optional — only include them when the conversation warrants it:
- "mark_blocked": use when user says they're blocked, waiting on someone, or can't proceed. Captures the blocker.
- "schedule_reminder": use when user commits to a specific time ("I'll do it in 2 hours", "tomorrow morning", "after lunch"). Convert to minutes_from_now.
- "notify_owner": use when user is stuck on a task that has an owner/team lead who should know. Only when it would genuinely help.
- "create_subtasks": use when user asks to break down a task, or the task seems overwhelming and breaking it down would help.
"""


def build_context(
    tasks: list[dict],
    memories: list[dict],
    learnings: list[dict],
    recent_nudges: list[dict],
) -> str:
    """Build the time-aware context block injected into every Gemini call."""
    now = datetime.now(timezone.utc)
    day_name = now.strftime("%A")
    time_str = now.strftime("%I:%M %p")
    date_str = now.strftime("%B %d, %Y")

    lines = [
        f"=== CURRENT CONTEXT ===",
        f"Time: {time_str} on {day_name}, {date_str} (UTC)",
        "",
    ]

    # Active tasks with time analysis
    if tasks:
        lines.append("ACTIVE TASKS:")
        for t in tasks:
            deadline_str = ""
            urgency = ""
            if t.get("deadline"):
                try:
                    dl = datetime.fromisoformat(t["deadline"].replace("Z", "").replace("+00:00", "")).replace(tzinfo=timezone.utc)
                    hours_left = (dl - now).total_seconds() / 3600
                    if hours_left < 0:
                        deadline_str = f"⚠️ OVERDUE by {abs(int(hours_left))}h"
                        urgency = " [CRITICAL]"
                    elif hours_left < 2:
                        deadline_str = f"⏰ Due in {int(hours_left * 60)}min"
                        urgency = " [URGENT]"
                    elif hours_left < 24:
                        deadline_str = f"Due in {int(hours_left)}h"
                        urgency = " [TODAY]"
                    else:
                        days = int(hours_left / 24)
                        deadline_str = f"Due in {days} day{'s' if days != 1 else ''}"
                except Exception:
                    deadline_str = t.get("deadline", "")

            created = datetime.fromisoformat(t["created_at"].replace("Z", "")).replace(tzinfo=timezone.utc) if t.get("created_at") else now
            days_open = (now - created).days
            assignee = f" → @{t['assignee']}" if t.get("assignee") else ""
            lines.append(
                f"  [{t['status'].upper()}]{urgency} {t['title']}{assignee} | {deadline_str} | Open {days_open}d | Nudged {t.get('nudge_count', 0)}x"
            )
    else:
        lines.append("ACTIVE TASKS: None")

    lines.append("")

    # Recent memories (last 48h)
    if memories:
        lines.append("RECENT CONTEXT (last 48h):")
        for m in memories[-8:]:  # Last 8 memories
            lines.append(f"  [{m.get('type', 'memory')}] {m['content']}")
        lines.append("")

    # Long-term learnings
    if learnings:
        lines.append("WHAT I KNOW ABOUT THIS USER:")
        for l in learnings[-5:]:
            lines.append(f"  • {l['content']}")
        lines.append("")

    # Recent nudges (so we don't repeat)
    if recent_nudges:
        lines.append("RECENT NUDGES SENT (avoid repeating):")
        for n in recent_nudges[-3:]:
            response = f" → User: '{n['response']}'" if n.get("response") else " (no response)"
            lines.append(f"  {n['sent_at']}: \"{n['message']}\"{response}")
        lines.append("")

    lines.append("=== END CONTEXT ===")
    return "\n".join(lines)


async def chat(
    user_message: str,
    history: list[dict],
    tasks: list[dict],
    memories: list[dict],
    learnings: list[dict],
    recent_nudges: list[dict],
    user_name: Optional[str] = None,
    nudge_context: Optional[str] = None,
    focal_task: Optional[dict] = None,
) -> dict:
    """
    Send a message to Flaxie and get a structured response.
    Returns the parsed JSON response dict.
    """
    if not settings.gemini_api_key:
        return {
            "reply": "I'm not configured yet — add your GEMINI_API_KEY to the .env file.",
            "tasks_to_create": [],
            "tasks_to_update": [],
            "task_refs": [],
            "mascot_state": "idle",
            "memory_to_save": None,
        }

    context = build_context(tasks, memories, learnings, recent_nudges)
    name_prefix = f"The user's name is {user_name}. " if user_name else ""

    # Build nudge-triggered conversation block if applicable
    nudge_block = ""
    if nudge_context or focal_task:
        lines = [
            "=== NUDGE-TRIGGERED CONVERSATION ===",
            "This conversation was opened directly from a nudge notification.",
            "The user clicked a button on your notification — they want to talk about a specific task.",
            "",
        ]
        if nudge_context:
            lines.append(f"Nudge that triggered this: \"{nudge_context}\"")
            lines.append("")
        if focal_task:
            ft = focal_task
            lines.append("FOCAL TASK:")
            lines.append(f"  Title: {ft.get('title', 'Unknown')}")
            lines.append(f"  Status: {ft.get('status', 'unknown')}")
            lines.append(f"  Days in progress: {ft.get('days_open', 0)}")
            lines.append(f"  Deadline: {ft.get('deadline_str') or 'None set'}")
            lines.append(f"  Nudged {ft.get('nudge_count', 0)} times total")
            if ft.get("owner_name"):
                lines.append(f"  Owner: {ft['owner_name']}")
            blocked = ft.get("is_blocked", False)
            blocked_reason = ft.get("blocked_reason")
            lines.append(f"  Blocked: {blocked}" + (f" ({blocked_reason})" if blocked_reason else ""))
            if ft.get("last_nudge_message"):
                lines.append(f"  Last nudge: \"{ft['last_nudge_message']}\"")
            lines.append(f"  User's button response: \"{user_message}\"")
            lines.append("")
        lines += [
            "Your job: Open with a specific, warm question about THIS task. Don't say \"how can I help?\" —",
            "dig into what's actually happening. If nudged multiple times with no progress, change strategy:",
            "ask about the blocker, offer to break it down, or ask if it should be reassigned.",
            "=== END NUDGE CONTEXT ===",
            "",
        ]
        nudge_block = "\n".join(lines) + "\n"

    system = f"{FLAXIE_SYSTEM_PROMPT}\n\n{nudge_block}{name_prefix}{context}"

    # Convert history to OpenAI format for LiteLLM
    lm_messages = []
    for msg in history[-12:]:
        role = "user" if msg["role"] == "user" else "assistant"
        lm_messages.append({"role": role, "content": msg["content"]})
    lm_messages.append({"role": "user", "content": user_message})

    try:
        import json
        langfuse = get_langfuse_client()
        raw = await llm_complete(
            system=system,
            messages=lm_messages,
            model="gemini/gemini-2.5-flash",
            temperature=0.85,
            max_tokens=2048,
            json_mode=True,
            trace_name="flaxie-chat",
            trace_user_id=None,  # user_id not available in brain.py
            langfuse_client=langfuse,
        )
        raw = raw.strip()
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            last_brace = raw.rfind('}')
            result = json.loads(raw[:last_brace + 1]) if last_brace != -1 else json.loads(raw)

        # Ensure required fields exist
        result.setdefault("tasks_to_create", [])
        result.setdefault("tasks_to_update", [])
        result.setdefault("task_refs", [])
        result.setdefault("mascot_state", "listening")
        result.setdefault("memory_to_save", None)

        return result

    except Exception as e:
        logger.error("[brain] LLM chat failed: %s", e, exc_info=True)
        return {
            "reply": "I'm having a moment — could you try again in a few seconds?",
            "tasks_to_create": [],
            "tasks_to_update": [],
            "task_refs": [],
            "mascot_state": "idle",
            "memory_to_save": None,
        }


async def decide_nudge(
    tasks: list[dict],
    memories: list[dict],
    learnings: list[dict],
    recent_nudges: list[dict],
    user_name: Optional[str] = None,
) -> dict:
    """
    Proactive nudge decision engine.
    AI decides: should I nudge? what do I say? what state am I in? when to check next?
    """
    if not settings.gemini_api_key or not tasks:
        return {
            "should_nudge": False,
            "mascot_state": "idle",
            "nudge_message": None,
            "action_options": ["Got it", "Let's talk"],
            "next_check_minutes": 30,
            "task_id": None,
        }

    context = build_context(tasks, memories, learnings, recent_nudges)
    name = user_name or "the user"

    nudge_prompt = f"""You are deciding whether to proactively nudge {name} right now.

{context}

Rules:
1. Do NOT nudge if all tasks are done or there's nothing urgent
2. Do NOT nudge if you nudged about the same task in the last 45 minutes
3. DO nudge if a deadline is within 2 hours and this task hasn't been nudged yet today
4. DO nudge if a task is overdue and the user hasn't acknowledged it
5. Keep nudge messages warm and specific — mention the actual task name
6. The mascot_state reflects the emotional context (concerned for overdue, urgent for imminent deadline, idle if all fine)
7. next_check_minutes should be adaptive: 10 if urgent, 20 if deadline today, 30 normally, 120 if evening/quiet

Respond with JSON:
{{
  "should_nudge": true or false,
  "mascot_state": "idle|alert|listening|celebrating|concerned|dormant|urgent",
  "nudge_message": "warm message if nudging, null if not",
  "action_options": ["Got it", "Let's talk"],
  "next_check_minutes": 30,
  "task_id": "task ID to reference, or null"
}}"""

    try:
        import json
        langfuse = get_langfuse_client()
        raw = await llm_complete(
            system="You are Flaxie, an AI accountability partner.",
            messages=[{"role": "user", "content": nudge_prompt}],
            model="gemini/gemini-2.5-flash",
            temperature=0.7,
            max_tokens=256,
            json_mode=True,
            trace_name="flaxie-nudge-decision",
            langfuse_client=langfuse,
        )
        result = json.loads(raw.strip())
        result.setdefault("should_nudge", False)
        result.setdefault("mascot_state", "idle")
        result.setdefault("nudge_message", None)
        result.setdefault("action_options", ["Got it", "Let's talk"])
        result.setdefault("next_check_minutes", 30)
        result.setdefault("task_id", None)
        return result

    except Exception as e:
        logger.error("[brain] decide_nudge failed: %s", e, exc_info=True)
        return {
            "should_nudge": False,
            "mascot_state": "idle",
            "nudge_message": None,
            "action_options": ["Got it", "Let's talk"],
            "next_check_minutes": 30,
            "task_id": None,
        }
