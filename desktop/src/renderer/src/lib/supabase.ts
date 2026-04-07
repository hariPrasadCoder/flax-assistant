import { createClient, SupabaseClient } from '@supabase/supabase-js'

let _client: SupabaseClient | null = null

export function getSupabase(): SupabaseClient | null {
  if (_client) return _client
  const url = import.meta.env.VITE_SUPABASE_URL as string | undefined
  const key = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined
  if (url && key) {
    _client = createClient(url, key)
    return _client
  }
  return null
}

/** Refresh the Supabase session and persist the new access token. Returns the new token or null. */
export async function refreshToken(): Promise<string | null> {
  const supabase = getSupabase()
  if (!supabase) return null
  try {
    const { data, error } = await supabase.auth.refreshSession()
    if (error || !data.session) return null
    localStorage.setItem('flaxie_token', data.session.access_token)
    return data.session.access_token
  } catch {
    return null
  }
}

/** Clear all stored auth state and force re-login. */
export function clearAuth() {
  localStorage.removeItem('flaxie_token')
  localStorage.removeItem('flaxie_user_id')
  localStorage.removeItem('flaxie_user_name')
  localStorage.removeItem('flaxie_team_id')
  window.location.reload()
}
