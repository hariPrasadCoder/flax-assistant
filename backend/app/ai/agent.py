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


# ── Agent state ───────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    context: dict           # tasks, memories, learnings, recent_nudges, user_name
    actions_taken: list     # accumulated actions to execute after the graph runs
    mascot_state: str
    next_check_minutes: int


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
- set_mascot_state: ALWAYS call this — it controls the icon + loop timing
- be_silent: when there's nothing worth saying (still call set_mascot_state)

Decision rules (these are guidelines, not code — you reason about them):
- Don't nudge about the same task twice within 45 minutes
- A task overdue by hours is critical; one due in 3 days is just worth watching
- Sunday evening ≠ Monday 9am — use time of day to calibrate urgency
- If you nudged something 3 times with no response, change approach
- You can take multiple actions in one cycle if there are genuinely multiple things worth saying
- If there are no active tasks, go dormant and check back in 90 minutes

Always call set_mascot_state to close out every cycle.
"""


def build_context_message(context: dict) -> str:
    """Build the context block injected into the agent's system message."""
    now = datetime.now(timezone.utc)
    day = now.strftime("%A")
    time_str = now.strftime("%I:%M %p")
    date_str = now.strftime("%B %d, %Y")
    name = context.get("user_name") or "the user"

    lines = [
        f"=== CONTEXT FOR {name.upper()} ===",
        f"Now: {time_str} on {day}, {date_str} (UTC)",
        "",
    ]

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

            lines.append(
                f"  [{t['id']}]{urgency_tag} \"{t['title']}\" | {t['status'].upper()} | {dl}"
                f" | open {days_open}d | nudged {t.get('nudge_count', 0)}x{last_nudged}"
            )
    else:
        lines.append("ACTIVE TASKS: none")

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
        print(f"[agent] think_node error: {e}")
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
    """After thinking, if there are tool calls → act. Otherwise → end."""
    last_msg = state["messages"][-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "act"
    return "end"


# ── Build graph ───────────────────────────────────────────────────────────────

def build_agent_graph() -> Any:
    graph = StateGraph(AgentState)
    graph.add_node("observe", observe_node)
    graph.add_node("think", think_node)
    graph.add_node("act", act_node)

    graph.set_entry_point("observe")
    graph.add_edge("observe", "think")
    graph.add_conditional_edges("think", should_continue, {"act": "act", "end": END})
    graph.add_edge("act", END)

    return graph.compile()


_agent_graph = None

def get_agent_graph():
    global _agent_graph
    if _agent_graph is None:
        _agent_graph = build_agent_graph()
    return _agent_graph


# ── Public API ────────────────────────────────────────────────────────────────

async def run_agent(
    tasks: List[dict],
    memories: List[dict],
    learnings: List[dict],
    recent_nudges: List[dict],
    user_name: Optional[str] = None,
) -> dict:
    """
    Run Flaxie's autonomous agent cycle.
    Returns: { actions, mascot_state, next_check_minutes }
    """
    graph = get_agent_graph()

    initial_state: AgentState = {
        "messages": [],
        "context": {
            "tasks": tasks,
            "memories": memories,
            "learnings": learnings,
            "recent_nudges": recent_nudges,
            "user_name": user_name,
        },
        "actions_taken": [],
        "mascot_state": "idle",
        "next_check_minutes": 30,
    }

    result = await graph.ainvoke(initial_state)

    return {
        "actions": result.get("actions_taken", []),
        "mascot_state": result.get("mascot_state", "idle"),
        "next_check_minutes": max(5, min(240, result.get("next_check_minutes", 30))),
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
