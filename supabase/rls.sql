-- ============================================================
-- Flax Assistant — Row Level Security Policies
-- Run this in the Supabase SQL Editor after schema.sql
-- ============================================================

-- Enable RLS on all tables
ALTER TABLE users          ENABLE ROW LEVEL SECURITY;
ALTER TABLE teams          ENABLE ROW LEVEL SECURITY;
ALTER TABLE tasks          ENABLE ROW LEVEL SECURITY;
ALTER TABLE invite_codes   ENABLE ROW LEVEL SECURITY;
ALTER TABLE memories       ENABLE ROW LEVEL SECURITY;
ALTER TABLE nudge_logs     ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_messages  ENABLE ROW LEVEL SECURITY;

-- ── users ──────────────────────────────────────────────────
-- Users can only read/update their own profile
CREATE POLICY "users: read own" ON users
  FOR SELECT USING (id = auth.uid());

CREATE POLICY "users: update own" ON users
  FOR UPDATE USING (id = auth.uid());

CREATE POLICY "users: insert own" ON users
  FOR INSERT WITH CHECK (id = auth.uid());

-- Team members can see each other's basic profile
CREATE POLICY "users: team members can view" ON users
  FOR SELECT USING (
    team_id IS NOT NULL AND
    team_id IN (
      SELECT team_id FROM users WHERE id = auth.uid()
    )
  );

-- ── teams ──────────────────────────────────────────────────
CREATE POLICY "teams: members can read" ON teams
  FOR SELECT USING (
    id IN (SELECT team_id FROM users WHERE id = auth.uid())
  );

CREATE POLICY "teams: creator can update" ON teams
  FOR UPDATE USING (
    id IN (SELECT team_id FROM users WHERE id = auth.uid())
  );

CREATE POLICY "teams: authenticated can create" ON teams
  FOR INSERT WITH CHECK (auth.uid() IS NOT NULL);

-- ── tasks ──────────────────────────────────────────────────
-- Users can see tasks they own or are assigned to
CREATE POLICY "tasks: read own or assigned" ON tasks
  FOR SELECT USING (
    owner_id = auth.uid() OR assignee_id = auth.uid()
  );

-- Team-visible tasks can be seen by teammates
CREATE POLICY "tasks: team can read visible" ON tasks
  FOR SELECT USING (
    is_team_visible = true AND
    (
      owner_id IN (SELECT id FROM users WHERE team_id = (SELECT team_id FROM users WHERE id = auth.uid()))
      OR
      assignee_id IN (SELECT id FROM users WHERE team_id = (SELECT team_id FROM users WHERE id = auth.uid()))
    )
  );

CREATE POLICY "tasks: owner can insert" ON tasks
  FOR INSERT WITH CHECK (owner_id = auth.uid() OR assignee_id = auth.uid());

CREATE POLICY "tasks: owner or assignee can update" ON tasks
  FOR UPDATE USING (owner_id = auth.uid() OR assignee_id = auth.uid());

CREATE POLICY "tasks: owner can delete" ON tasks
  FOR DELETE USING (owner_id = auth.uid());

-- ── memories ───────────────────────────────────────────────
CREATE POLICY "memories: read own" ON memories
  FOR SELECT USING (user_id = auth.uid());

CREATE POLICY "memories: insert own" ON memories
  FOR INSERT WITH CHECK (user_id = auth.uid());

CREATE POLICY "memories: update own" ON memories
  FOR UPDATE USING (user_id = auth.uid());

CREATE POLICY "memories: delete own" ON memories
  FOR DELETE USING (user_id = auth.uid());

-- ── nudge_logs ─────────────────────────────────────────────
CREATE POLICY "nudges: read own" ON nudge_logs
  FOR SELECT USING (user_id = auth.uid());

CREATE POLICY "nudges: insert own" ON nudge_logs
  FOR INSERT WITH CHECK (user_id = auth.uid());

CREATE POLICY "nudges: update own" ON nudge_logs
  FOR UPDATE USING (user_id = auth.uid());

-- ── chat_messages ──────────────────────────────────────────
CREATE POLICY "chat: read own" ON chat_messages
  FOR SELECT USING (user_id = auth.uid());

CREATE POLICY "chat: insert own" ON chat_messages
  FOR INSERT WITH CHECK (user_id = auth.uid());

-- ── invite_codes ───────────────────────────────────────────
-- Anyone authenticated can look up an invite code to join a team
CREATE POLICY "invites: read any" ON invite_codes
  FOR SELECT USING (auth.uid() IS NOT NULL);

CREATE POLICY "invites: team admin can insert" ON invite_codes
  FOR INSERT WITH CHECK (
    created_by = auth.uid()
  );

-- ============================================================
-- IMPORTANT: The backend uses the service role key which bypasses
-- all RLS policies. These policies protect direct Supabase client
-- access (e.g. if anon key were ever used to query data directly).
-- ============================================================
