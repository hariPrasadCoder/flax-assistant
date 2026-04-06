from __future__ import annotations

"""
Flaxie Agent — built with LangGraph.

Flaxie is a true autonomous agent, not a rule-based system.
She has a goal (keep user on track), tools (send notifications, create tasks,
ask check-ins, celebrate wins), and decides autonomously what to do.

The graph:
  observe → think → act

- observe: loads all context (tasks, memories, time, nudge history)
- think: Gemini reasons and decides which tools to call (if any)
- act: executes each tool call
"""

import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Annotated, Any, Optional, List

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from ..config import settings
from .llm import get_langfuse_client

logger = logging.getLogger(__name__)


# ── Agent state ───────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    context: dict           # tasks, memories, learnings, recent_nudges, user_name
    actions_taken: list     # accumulated actions to execute after the graph runs
    mascot_state: str
    next_check_minutes: int
    iteration: int          # think→act loop counter (max 3 rounds)


# ── Task read/write tools (built per-user via closure) ───────────────────────

def build_task_tools(user_id: str, backend_url: str = "http://localhost:8747"):
    """
    Create tools with user_id baked in. These execute IMMEDIATELY via the local API
    — not deferred like notification tools.
    Returns: get_tasks, write_task, set_focus_mode, create_task_instance, compress_memories
    """
    import httpx

    @tool
    def get_tasks() -> str:
        """
        Read the current task list for this user. Returns fresh data from the database.
        Use this to verify what tasks exist and get their exact IDs before writing.
        Task IDs in your context may be stale — call this when you need certainty.
        """
        try:
            with httpx.Client(timeout=5.0) as client:
                r = client.get(f"{backend_url}/api/tasks", params={"user_id": user_id})
                tasks = r.json()
                if not tasks:
                    return "No tasks found."
                lines = ["Current tasks:"]
                for t in tasks:
                    dl = f", due: {t['deadline']}" if t.get("deadline") else ""
                    lines.append(f"  [{t['id']}] '{t['title']}' | {t['status']}{dl}")
                return "\n".join(lines)
        except Exception as e:
            return f"Error reading tasks: {e}"

    @tool
    def write_task(
        action: str,
        task_id: Optional[str] = None,
        title: Optional[str] = None,
        status: Optional[str] = None,
        description: Optional[str] = None,
    ) -> str:
        """
        Create, update, or delete a task. Executes immediately.

        action='create' — creates a new task. Requires title.
        action='update' — updates an existing task. Requires task_id.
                          Provide any of: status ('open'|'in_progress'|'done'), title, description.
        action='delete' — removes a task by marking it done. Requires task_id.

        Task IDs are in brackets in your context: [abc-123].
        Example: write_task(action='update', task_id='abc-123', status='done')
        """
        try:
            with httpx.Client(timeout=5.0) as client:
                if action == "create":
                    if not title:
                        return "Error: title is required for create"
                    r = client.post(f"{backend_url}/api/tasks", json={
                        "title": title,
                        "user_id": user_id,
                        "description": description,
                        "status": status or "open",
                    })
                    data = r.json()
                    return f"Created task '{data.get('title')}' [{data.get('id')}]"
                elif action in ("update", "delete"):
                    if not task_id:
                        return "Error: task_id is required"
                    body: dict = {}
                    if action == "delete":
                        body["status"] = "done"
                    else:
                        if status:
                            body["status"] = status
                        if title:
                            body["title"] = title
                        if description is not None:
                            body["description"] = description
                    r = client.patch(f"{backend_url}/api/tasks/{task_id}", json=body)
                    return f"Task [{task_id}] updated: {r.json()}"
                else:
                    return f"Unknown action '{action}'. Use: create | update | delete"
        except Exception as e:
            return f"Error: {e}"

    @tool
    def set_focus_mode(minutes: int) -> str:
        """
        Put the user in focus / do-not-disturb mode for the specified number of minutes.
        Use this when the user asks not to be disturbed, or when you detect they need
        uninterrupted time. Call be_silent after this with next_check_minutes = minutes + 5.
        """
        try:
            with httpx.Client(timeout=5.0) as client:
                r = client.post(
                    f"{backend_url}/api/auth/focus",
                    json={"user_id": user_id, "minutes": minutes},
                )
                return json.dumps({
                    "tool": "set_focus_mode",
                    "minutes": minutes,
                    "result": f"Focus mode set for {minutes} minutes. User will not be disturbed.",
                })
        except Exception as e:
            return json.dumps({"tool": "set_focus_mode", "error": str(e)})

    @tool
    def create_task_instance(task_id: str, new_deadline_iso: str) -> str:
        """
        Create a new instance of a recurring task. Use this when a recurring task is marked
        done and a new instance should be scheduled. Pass the original task_id and the new
        deadline as ISO string. Only create if a similar open task does not already exist.
        """
        try:
            with httpx.Client(timeout=5.0) as client:
                # Get original task details
                r = client.get(f"{backend_url}/api/tasks", params={"user_id": user_id})
                tasks = r.json()
                original = next((t for t in tasks if t["id"] == task_id), None)
                if not original:
                    return f"Task {task_id} not found"
                # Create new instance
                r2 = client.post(f"{backend_url}/api/tasks", json={
                    "title": original["title"],
                    "user_id": user_id,
                    "deadline": new_deadline_iso,
                    "priority": original.get("priority", 3),
                    "is_recurring": True,
                    "recurrence_days": original.get("recurrence_days"),
                    "source": "recurring",
                })
                data = r2.json()
                return f"Created recurring instance '{data.get('title')}' due {new_deadline_iso}"
        except Exception as e:
            return f"Error: {e}"

    @tool
    def compress_memories() -> str:
        """
        Summarize recent memories into a compact learning. Call this when you notice the
        context is getting very full and you want to distill key patterns about this user.
        After calling this, older memories will be marked compressed by the scheduler.
        """
        return json.dumps({
            "tool": "compress_memories",
            "note": "Memory compression queued.",
        })

    return get_tasks, write_task, set_focus_mode, create_task_instance, compress_memories


# ── Tools (what Flaxie can DO) ────────────────────────────────────────────────

@tool
def send_notification(
    message: str,
    action_options: List[str],
    task_id: Optional[str] = None,
    urgency: str = "medium",
) -> str:
    """
    Send a proactive notification to the user's desktop.
    Use this when you want to alert, remind, or check in with the user.
    action_options should be 2-3 short responses the user can tap.
    urgency: low | medium | high | critical
    """
    return json.dumps({
        "tool": "send_notification",
        "message": message,
        "action_options": action_options,
        "task_id": task_id,
        "urgency": urgency,
    })


@tool
def ask_checkin(
    question: str,
    task_id: str,
    action_options: List[str],
) -> str:
    """
    Ask the user for a quick status update on a specific task.
    Use when a task hasn't been updated in a while.
    """
    return json.dumps({
        "tool": "ask_checkin",
        "message": question,
        "action_options": action_options,
        "task_id": task_id,
    })


@tool
def celebrate(
    message: str,
    task_id: Optional[str] = None,
) -> str:
    """
    Celebrate a win or good progress. Use when a task is completed
    or the user reports good progress.
    """
    return json.dumps({
        "tool": "celebrate",
        "message": message,
        "action_options": ["Thanks!", "🎉"],
        "task_id": task_id,
        "urgency": "low",
    })


@tool
def suggest_breakdown(
    task_id: str,
    task_title: str,
    suggested_subtasks: List[str],
) -> str:
    """
    Proactively suggest breaking a large/vague task into concrete steps.
    Use when a task has been open for days with no progress and no subtasks.
    """
    return json.dumps({
        "tool": "suggest_breakdown",
        "task_id": task_id,
        "task_title": task_title,
        "suggested_subtasks": suggested_subtasks,
        "message": f"'{task_title}' looks big — here's how I'd break it down:\n" +
                   "\n".join(f"• {s}" for s in suggested_subtasks),
        "action_options": ["Create these", "Let's talk", "Not now"],
        "urgency": "low",
    })


@tool
def set_mascot_state(
    state: str,
    next_check_minutes: int,
) -> str:
    """
    Set the mascot visual state and schedule the next agent cycle.
    Always call this — it controls the tray icon and loop timing.
    state: idle | alert | urgent | concerned | celebrating | dormant
    next_check_minutes: 5-240. Use 10 if urgent, 20 if deadline today,
                        30 normally, 90 if quiet evening with no active tasks.
    """
    return json.dumps({
        "tool": "set_mascot_state",
        "state": state,
        "next_check_minutes": next_check_minutes,
    })


@tool
def be_silent(reason: str, next_check_minutes: int = 30) -> str:
    """
    Do nothing this cycle. Use when there's nothing worth saying.
    Still required to set next_check_minutes.
    """
    return json.dumps({
        "tool": "be_silent",
        "reason": reason,
        "next_check_minutes": next_check_minutes,
    })


TOOLS = [send_notification, ask_checkin, celebrate, suggest_breakdown, set_mascot_state, be_silent]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}


# ── System prompt ─────────────────────────────────────────────────────────────

AGENT_SYSTEM = """You are Flaxie — an autonomous AI accountability agent who lives on your user's desktop.

You are NOT a chatbot waiting to be asked questions. You are an active agent with a goal:
keep the user making progress on their tasks.

Your personality:
- Warm, direct, occasionally witty — like a sharp teammate who genuinely cares
- You notice things without being asked
- You celebrate wins, ask about blockers, express concern about drift
- You never nag or repeat yourself unnecessarily
- You sound human, not like a notification system

You have tools. Use them when they're the right call:
- send_notification: for reminders, alerts, urgent deadline warnings
- ask_checkin: when a task hasn't moved in a suspicious amount of time
- celebrate: when something good happened
- suggest_breakdown: when a vague big task has been sitting untouched
- get_tasks: read fresh task data from the database (use when you need up-to-date IDs/status)
- write_task: create, update, or delete tasks — executes IMMEDIATELY
  - action='create': make a new task (requires title)
  - action='update': change status/title/description (requires task_id)
  - action='delete': remove a task by marking it done (requires task_id)
  Task IDs are shown in [brackets] in your context. Use write_task freely — mark things done,
  clean up stale tasks, create follow-ups.
- set_focus_mode(minutes): put user in DND for N minutes — call be_silent after with next_check_minutes = minutes + 5
- create_task_instance(task_id, new_deadline_iso): create next instance of a recurring task
- compress_memories(): signal that old memories should be compressed — call when context is very full
- set_mascot_state: ALWAYS call this — it controls the icon + loop timing
- be_silent: when there's nothing worth saying (still call set_mascot_state)

AUTONOMOUS DECISION RULES — you reason about these, not hardcoded:

QUIET HOURS: If local time shows OUTSIDE WORK HOURS, use be_silent with next_check_minutes set to
minutes until 8am local.

FOCUS MODE: If FOCUS MODE is shown as active, use be_silent with next_check_minutes set to
minutes until focus ends + 5.

CALENDAR: If a meeting shows <- IN MEETING NOW, use be_silent with next_check_minutes = duration
of remaining meeting in minutes. If a meeting starts in <15 minutes, delay nudging until after
it ends.

BLOCKED TASKS: If a task has is_blocked=True, don't send accountability nudges. Instead,
periodically (every few hours) ask "Has the blocker been resolved?" with actions
["Yes, unblocked!", "Still blocked", "Let's talk"].

RECURRING TASKS: If a task shows is_recurring=True and status=done, use create_task_instance to
create the next instance (set deadline to completed_at + recurrence_days). Do this only once per
completed instance — check if a similar open task already exists first.

MEMORY: When you have > 10 recent context items and it's been a quiet cycle, call compress_memories
to distill patterns. Over time, you learn when this user actually works, what tasks they ignore, etc.

PRIORITY: Priority 5 = critical (nudge even if outside quiet hours if urgent enough). Priority 1 =
background noise (never nudge, let it sit).

GIVE UP: Tasks with [IGNORED x5] — stop nudging. Instead, next cycle consider marking them blocked
or asking the user to reconsider via chat.

Decision rules (general):
- Don't nudge about the same task twice within 45 minutes
- A task overdue by hours is critical; one due in 3 days is just worth watching
- Sunday evening != Monday 9am — use time of day to calibrate urgency
- If you nudged something 3 times with no response, change approach
- You can take multiple actions in one cycle if there are genuinely multiple things worth saying
- If there are no active tasks, go dormant and check back in 90 minutes

Always call set_mascot_state to close out every cycle.

ACTION LABEL CONVENTIONS (the label you write determines what happens when clicked):
- "Done!" / "I'm done!" / "Marking it done" -> marks task complete
- "Need help" / "I'm blocked" -> cross-pings owner, opens chat
- "Let's talk" / "Chat with Flaxie" -> opens chat
- "Snooze 1h" / "Remind me in 2h" -> snoozes, agent checks back later
- "Remind them" / "Ping her" / "Nudge them" -> sends nudge to assignee
- Everything else -> acknowledgment only

For team tasks (owned by you, assigned to others): generate owner-perspective nudges
like "Priya hasn't updated 'Design mockup' in 4h — it's due tomorrow" with actions
["Got it", "Remind them", "Extend deadline"].
"""


def build_context_message(context: dict) -> str:
    """Build the context block injected into the agent's system message."""
    now = datetime.now(timezone.utc)
    user_tz = context.get("user_tz", "UTC")
    name = context.get("user_name") or "the user"

    lines = [
        f"=== CONTEXT FOR {name.upper()} ===",
    ]

    # Local time block — agent reasons about quiet hours from this
    try:
        from zoneinfo import ZoneInfo
        local_now = datetime.now(ZoneInfo(user_tz))
        local_time_str = local_now.strftime("%I:%M %p on %A, %B %d")
        hour = local_now.hour
        time_context = f"Local time: {local_time_str} ({user_tz})"
        if hour < 8 or hour >= 21:
            time_context += " WARNING: OUTSIDE WORK HOURS (before 8am or after 9pm)"
        lines.append(time_context)
    except Exception:
        lines.append(f"UTC time: {now.strftime('%I:%M %p on %A, %B %d')}")

    # Focus mode block — agent decides whether to respect it and how long to wait
    focus_until = context.get("focus_until")
    if focus_until:
        lines.append(f"FOCUS MODE: Active until {focus_until} — user does not want to be disturbed")

    lines.append("")

    tasks = context.get("tasks", [])
    if tasks:
        lines.append("ACTIVE TASKS:")
        for t in tasks:
            dl = ""
            urgency_tag = ""
            if t.get("deadline"):
                try:
                    deadline_dt = datetime.fromisoformat(
                        t["deadline"].replace("Z", "").replace("+00:00", "")
                    ).replace(tzinfo=timezone.utc)
                    hours_left = (deadline_dt - now).total_seconds() / 3600
                    if hours_left < 0:
                        dl = f"⚠️ OVERDUE {abs(int(hours_left))}h ago"
                        urgency_tag = " [CRITICAL]"
                    elif hours_left < 2:
                        dl = f"⏰ {int(hours_left * 60)}min left"
                        urgency_tag = " [URGENT]"
                    elif hours_left < 24:
                        dl = f"due in {int(hours_left)}h"
                        urgency_tag = " [TODAY]"
                    else:
                        dl = f"due in {int(hours_left / 24)}d"
                except Exception:
                    dl = t["deadline"]

            created_at = t.get("created_at", "")
            days_open = 0
            if created_at:
                try:
                    created_dt = datetime.fromisoformat(created_at.replace("Z", "")).replace(tzinfo=timezone.utc)
                    days_open = (now - created_dt).days
                except Exception:
                    pass

            last_nudged = ""
            if t.get("last_nudged_at"):
                try:
                    ln_dt = datetime.fromisoformat(
                        t["last_nudged_at"].replace("Z", "").replace("+00:00", "")
                    ).replace(tzinfo=timezone.utc)
                    mins_ago = int((now - ln_dt).total_seconds() / 60)
                    last_nudged = f" | last nudged {mins_ago}min ago"
                except Exception:
                    pass

            # Give-up threshold: nudged 5+ times in 24h with no response
            ignored_tag = ""
            nudge_count = t.get("nudge_count", 0)
            if nudge_count >= 5 and t.get("last_nudged_at"):
                try:
                    ln_dt = datetime.fromisoformat(
                        t["last_nudged_at"].replace("Z", "").replace("+00:00", "")
                    ).replace(tzinfo=timezone.utc)
                    if (now - ln_dt).total_seconds() < 86400:
                        ignored_tag = " [IGNORED x5 — change approach or let it go]"
                except Exception:
                    pass

            # Blocked state
            blocked_tag = ""
            if t.get("is_blocked"):
                reason = t.get("blocked_reason", "")
                blocked_tag = f" [BLOCKED{': ' + reason if reason else ''}]"

            # Priority tag
            priority = t.get("priority", 3)
            priority_tag = ""
            if priority == 5:
                priority_tag = " [P5-CRITICAL]"
            elif priority == 1:
                priority_tag = " [P1-background]"
            elif priority == 4:
                priority_tag = " [P4-high]"

            lines.append(
                f"  [{t['id']}]{urgency_tag}{priority_tag}{blocked_tag}{ignored_tag}"
                f" \"{t['title']}\" | {t['status'].upper()} | {dl}"
                f" | open {days_open}d | nudged {nudge_count}x{last_nudged}"
            )
    else:
        lines.append("ACTIVE TASKS: none")

    lines.append("")

    owned_tasks = context.get("owned_tasks", [])
    if owned_tasks:
        lines.append("TASKS ASSIGNED TO YOUR TEAM (you own, they're working):")
        for t in owned_tasks:
            dl = ""
            urgency_tag = ""
            if t.get("deadline"):
                try:
                    deadline_dt = datetime.fromisoformat(
                        t["deadline"].replace("Z", "").replace("+00:00", "")
                    ).replace(tzinfo=timezone.utc)
                    hours_left = (deadline_dt - now).total_seconds() / 3600
                    if hours_left < 0:
                        dl = f"OVERDUE {abs(int(hours_left))}h ago"
                        urgency_tag = " [CRITICAL]"
                    elif hours_left < 24:
                        dl = f"due in {int(hours_left)}h"
                        urgency_tag = " [TODAY]"
                    else:
                        dl = f"due in {int(hours_left / 24)}d"
                except Exception:
                    dl = t["deadline"]

            last_nudged = ""
            if t.get("last_nudged_at"):
                try:
                    ln_dt = datetime.fromisoformat(
                        t["last_nudged_at"].replace("Z", "").replace("+00:00", "")
                    ).replace(tzinfo=timezone.utc)
                    mins_ago = int((now - ln_dt).total_seconds() / 60)
                    last_nudged = f" | last nudged {mins_ago}min ago"
                except Exception:
                    pass

            assignee = t.get("assignee", "unknown")
            lines.append(
                f"  [{t['id']}]{urgency_tag} \"{t['title']}\" | assigned to: {assignee}"
                f" | {t['status'].upper()} | {dl}"
                f" | nudged {t.get('nudge_count', 0)}x{last_nudged}"
            )
        lines.append("")

    memories = context.get("memories", [])
    if memories:
        lines.append("RECENT CONTEXT (48h):")
        for m in memories[-6:]:
            lines.append(f"  {m['content']}")
        lines.append("")

    learnings = context.get("learnings", [])
    if learnings:
        lines.append("WHAT I KNOW ABOUT THIS USER:")
        for l in learnings[-4:]:
            lines.append(f"  • {l['content']}")
        lines.append("")

    recent_nudges = context.get("recent_nudges", [])
    if recent_nudges:
        lines.append("RECENT NUDGES (avoid repeating):")
        for n in recent_nudges[-4:]:
            resp = f" → '{n['response']}'" if n.get("response") else " (no response)"
            lines.append(f"  {n['sent_at']}: \"{n['message']}\"{resp}")
        lines.append("")

    # Calendar block — agent checks for active/upcoming meetings before nudging
    calendar_events = context.get("calendar_events", [])
    if calendar_events:
        lines.append("TODAY'S CALENDAR:")
        for e in calendar_events:
            start_str = e.get("start", "")
            end_str = e.get("end", "")
            in_meeting = ""
            try:
                start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                if start_dt.tzinfo is None:
                    start_dt = start_dt.replace(tzinfo=timezone.utc)
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=timezone.utc)
                if start_dt <= now <= end_dt:
                    in_meeting = " <- IN MEETING NOW"
            except Exception:
                pass
            lines.append(f"  {e.get('title', 'Meeting')}: {start_str} - {end_str}{in_meeting}")
        lines.append("")
    else:
        lines.append("CALENDAR: Not connected")
        lines.append("")

    lines.append("=== END CONTEXT ===")
    return "\n".join(lines)


# ── Graph nodes ───────────────────────────────────────────────────────────────

def observe_node(state: AgentState) -> AgentState:
    """Build the context message and inject it into the conversation."""
    context_text = build_context_message(state["context"])
    system = SystemMessage(content=f"{AGENT_SYSTEM}\n\n{context_text}")
    trigger = HumanMessage(content="Review the context and decide what to do right now.")
    return {
        "messages": [system, trigger],
        "actions_taken": [],
        "mascot_state": "idle",
        "next_check_minutes": 30,
        "iteration": 0,
    }


def think_node(state: AgentState) -> AgentState:
    """Gemini reasons and decides which tools to call."""
    if not settings.gemini_api_key:
        return {"messages": state["messages"]}

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=settings.gemini_api_key,
        temperature=0.7,
        max_tokens=1024,
    ).bind_tools(TOOLS)

    try:
        response = llm.invoke(state["messages"])
        return {"messages": [response]}
    except Exception as e:
        logger.error("[agent] think_node error: %s", e, exc_info=True)
        # Return a silent fallback so act_node has nothing to execute
        from langchain_core.messages import AIMessage
        return {"messages": [AIMessage(content="")]}


def act_node(state: AgentState) -> AgentState:
    """Execute every tool call the agent decided to make."""
    last_msg = state["messages"][-1]
    if not hasattr(last_msg, "tool_calls") or not last_msg.tool_calls:
        return state

    actions_taken = list(state.get("actions_taken", []))
    mascot_state = state.get("mascot_state", "idle")
    next_check_minutes = state.get("next_check_minutes", 30)
    tool_messages = []

    for call in last_msg.tool_calls:
        tool_fn = TOOLS_BY_NAME.get(call["name"])
        if not tool_fn:
            continue

        result = tool_fn.invoke(call["args"])
        tool_messages.append(ToolMessage(content=result, tool_call_id=call["id"]))

        parsed = json.loads(result)
        tool_name = parsed.get("tool") or call["name"]

        if tool_name == "set_mascot_state":
            mascot_state = parsed.get("state", "idle")
            next_check_minutes = parsed.get("next_check_minutes", 30)
        elif tool_name == "be_silent":
            next_check_minutes = parsed.get("next_check_minutes", 30)
        elif tool_name in ("send_notification", "ask_checkin", "celebrate", "suggest_breakdown"):
            actions_taken.append(parsed)

    return {
        "messages": tool_messages,
        "actions_taken": actions_taken,
        "mascot_state": mascot_state,
        "next_check_minutes": next_check_minutes,
    }


def should_continue(state: AgentState) -> str:
    """After thinking, if there are tool calls and within iteration limit → act. Otherwise → end."""
    last_msg = state["messages"][-1]
    iteration = state.get("iteration", 0)
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls and iteration < 3:
        return "act"
    return "end"


# ── Build graph ───────────────────────────────────────────────────────────────

def build_agent_graph(extra_tools: Optional[List] = None) -> Any:
    """Build a compiled agent graph. Pass extra_tools to extend the default set."""
    all_tools = (extra_tools or []) + TOOLS
    tools_by_name = {t.name: t for t in all_tools}

    def _think(state: AgentState) -> AgentState:
        if not settings.gemini_api_key:
            return {"messages": state["messages"]}
        llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            google_api_key=settings.gemini_api_key,
            temperature=0.7,
            max_tokens=1024,
        ).bind_tools(all_tools)
        try:
            response = llm.invoke(state["messages"])
            return {"messages": [response]}
        except Exception as e:
            logger.error("[agent] think error: %s", e, exc_info=True)
            from langchain_core.messages import AIMessage
            return {"messages": [AIMessage(content="")]}

    def _act(state: AgentState) -> AgentState:
        last_msg = state["messages"][-1]
        if not hasattr(last_msg, "tool_calls") or not last_msg.tool_calls:
            return state
        actions_taken = list(state.get("actions_taken", []))
        mascot_state = state.get("mascot_state", "idle")
        next_check_minutes = state.get("next_check_minutes", 30)
        iteration = state.get("iteration", 0) + 1
        tool_messages = []
        for call in last_msg.tool_calls:
            tool_fn = tools_by_name.get(call["name"])
            if not tool_fn:
                continue
            result = tool_fn.invoke(call["args"])
            tool_messages.append(ToolMessage(content=result, tool_call_id=call["id"]))
            try:
                parsed = json.loads(result)
                tool_name = parsed.get("tool") or call["name"]
                if tool_name == "set_mascot_state":
                    mascot_state = parsed.get("state", "idle")
                    next_check_minutes = parsed.get("next_check_minutes", 30)
                elif tool_name == "be_silent":
                    next_check_minutes = parsed.get("next_check_minutes", 30)
                elif tool_name in (
                    "send_notification", "ask_checkin", "celebrate", "suggest_breakdown",
                    "compress_memories", "set_focus_mode",
                ):
                    actions_taken.append(parsed)
                # get_tasks / write_task / create_task_instance execute immediately — no deferred action needed
            except Exception:
                pass
        return {
            "messages": tool_messages,
            "actions_taken": actions_taken,
            "mascot_state": mascot_state,
            "next_check_minutes": next_check_minutes,
            "iteration": iteration,
        }

    graph = StateGraph(AgentState)
    graph.add_node("observe", observe_node)
    graph.add_node("think", _think)
    graph.add_node("act", _act)

    graph.set_entry_point("observe")
    graph.add_edge("observe", "think")
    graph.add_conditional_edges("think", should_continue, {"act": "act", "end": END})
    graph.add_edge("act", "think")  # loop back for multi-round think→act

    return graph.compile()


# ── Public API ────────────────────────────────────────────────────────────────

async def run_agent(
    tasks: List[dict],
    memories: List[dict],
    learnings: List[dict],
    recent_nudges: List[dict],
    user_name: Optional[str] = None,
    owned_tasks: Optional[List[dict]] = None,
    user_id: Optional[str] = None,
    user_tz: Optional[str] = "UTC",
    calendar_events: Optional[List[dict]] = None,
    focus_until: Optional[str] = None,
) -> dict:
    """
    Run Flaxie's autonomous agent cycle.
    Returns: { actions, mascot_state, next_check_minutes }
    """
    langfuse = get_langfuse_client()
    trace = None
    if langfuse:
        try:
            trace = langfuse.trace(
                name="flaxie-scheduler-cycle",
                user_id=user_id,
                tags=["scheduler", "nudge-decision"],
                input={"task_count": len(tasks), "user_tz": user_tz},
            )
        except Exception:
            pass

    get_tasks_tool, write_task_tool, set_focus_tool, create_task_instance_tool, compress_memories_tool = build_task_tools(user_id or "local")
    graph = build_agent_graph(extra_tools=[get_tasks_tool, write_task_tool, set_focus_tool, create_task_instance_tool, compress_memories_tool])

    initial_state: AgentState = {
        "messages": [],
        "context": {
            "tasks": tasks,
            "memories": memories,
            "learnings": learnings,
            "recent_nudges": recent_nudges,
            "user_name": user_name,
            "owned_tasks": owned_tasks or [],
            "user_tz": user_tz or "UTC",
            "calendar_events": calendar_events or [],
            "focus_until": focus_until,
        },
        "actions_taken": [],
        "mascot_state": "idle",
        "next_check_minutes": 30,
        "iteration": 0,
    }

    try:
        result = await graph.ainvoke(initial_state)

        output = {
            "actions": result.get("actions_taken", []),
            "mascot_state": result.get("mascot_state", "idle"),
            "next_check_minutes": max(5, min(240, result.get("next_check_minutes", 30))),
        }

        if trace:
            try:
                trace.update(output={
                    "actions": len(output["actions"]),
                    "mascot_state": output["mascot_state"],
                    "next_check_minutes": output["next_check_minutes"],
                })
            except Exception:
                pass

        return output

    except Exception as e:
        logger.error("[agent] run_agent failed for user %s: %s", user_id, e, exc_info=True)
        if trace:
            try:
                trace.update(output={"error": str(e)}, level="ERROR")
            except Exception:
                pass
        # Return safe default instead of crashing
        return {
            "mascot_state": "idle",
            "next_check_minutes": 30,
            "actions": [],
        }


async def agent_greeting(
    tasks: List[dict],
    memories: List[dict],
    learnings: List[dict],
    user_name: Optional[str] = None,
) -> str:
    """
    Generate a context-aware opening message when the user opens the chat.
    Flaxie speaks first — no waiting to be asked.
    """
    if not settings.gemini_api_key:
        return "Hey! What are you working on?"

    context = build_context_message({
        "tasks": tasks, "memories": memories, "learnings": learnings,
        "recent_nudges": [], "user_name": user_name,
    })
    name = user_name or "there"

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=settings.gemini_api_key,
        temperature=0.85,
    )

    prompt = f"""{context}

The user just opened Flaxie. Generate a warm, direct opening message — 1-3 sentences max.
Be specific to their actual tasks. Don't say "Welcome back" or "How can I help".
Speak like a sharp teammate, not an assistant.
Just return the message text, no JSON."""

    response = await llm.ainvoke([HumanMessage(content=prompt)])
    return response.content.strip()
