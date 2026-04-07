-- Flax Assistant — Supabase schema
-- Run this in the Supabase SQL editor (Dashboard → SQL Editor → New query)
-- Order matters: referenced tables must exist before referencing ones.

-- ── Teams ─────────────────────────────────────────────────────────────────────
create table if not exists teams (
  id text primary key,
  name text not null,
  created_at timestamptz default now()
);

-- ── Users ─────────────────────────────────────────────────────────────────────
-- id matches Supabase Auth user.id (set by the client after OTP verification)
create table if not exists users (
  id text primary key,
  team_id text references teams(id),
  name text not null,
  email text unique not null,
  hashed_password text,          -- nullable: not used with OTP auth
  timezone text default 'UTC',
  created_at timestamptz default now(),
  focus_until timestamptz,
  google_calendar_token text,
  last_reflection_at timestamptz
);

-- ── Tasks ─────────────────────────────────────────────────────────────────────
create table if not exists tasks (
  id text primary key,
  team_id text references teams(id),
  owner_id text references users(id),
  assignee_id text references users(id),
  title text not null,
  description text,
  status text default 'open' check (status in ('open', 'in_progress', 'done')),
  deadline timestamptz,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  completed_at timestamptz,
  nudge_count integer default 0,
  last_nudged_at timestamptz,
  source text default 'chat',
  is_team_visible boolean default true,
  priority integer default 3,
  is_blocked boolean default false,
  blocked_reason text,
  is_recurring boolean default false,
  recurrence_days integer
);

-- ── Invite Codes ──────────────────────────────────────────────────────────────
create table if not exists invite_codes (
  code text primary key,
  team_id text references teams(id) not null,
  created_at timestamptz default now(),
  expires_at timestamptz,
  used boolean default false
);

-- ── Memories ──────────────────────────────────────────────────────────────────
create table if not exists memories (
  id text primary key,
  user_id text references users(id),
  team_id text references teams(id),
  type text not null check (type in ('conversation', 'task_event', 'learning', 'context_snapshot', 'meeting_notes')),
  content text not null,
  created_at timestamptz default now(),
  expires_at timestamptz,
  importance float default 0.5,
  compressed boolean default false,
  task_id text references tasks(id)
);

-- ── Nudge Logs ────────────────────────────────────────────────────────────────
create table if not exists nudge_logs (
  id text primary key,
  user_id text references users(id) not null,
  task_id text references tasks(id),
  message text not null,
  action_options text default 'Got it,Let''s talk',
  sent_at timestamptz default now(),
  user_response text,
  responded_at timestamptz,
  dismissed boolean default false
);

-- ── Chat Messages ─────────────────────────────────────────────────────────────
create table if not exists chat_messages (
  id text primary key,
  user_id text not null,
  role text not null,
  content text not null,
  created_at timestamptz default now(),
  task_ids text
);

-- ── Indexes (performance) ─────────────────────────────────────────────────────
create index if not exists idx_tasks_assignee_id on tasks(assignee_id);
create index if not exists idx_tasks_owner_id on tasks(owner_id);
create index if not exists idx_tasks_team_id on tasks(team_id);
create index if not exists idx_tasks_status on tasks(status);
create index if not exists idx_memories_user_id on memories(user_id);
create index if not exists idx_memories_type on memories(type);
create index if not exists idx_memories_created_at on memories(created_at);
create index if not exists idx_nudge_logs_user_id on nudge_logs(user_id);
create index if not exists idx_nudge_logs_sent_at on nudge_logs(sent_at);
create index if not exists idx_chat_messages_user_id on chat_messages(user_id);
create index if not exists idx_chat_messages_created_at on chat_messages(created_at);
create index if not exists idx_users_email on users(email);
create index if not exists idx_users_team_id on users(team_id);
