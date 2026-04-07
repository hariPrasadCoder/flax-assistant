import { refreshToken, clearAuth } from './supabase'

/**
 * Authenticated fetch — adds Authorization: Bearer <token> to every request.
 * On 401, automatically refreshes the Supabase session and retries once.
 * If refresh fails, clears auth state and reloads (forces re-login).
 */
export async function authFetch(url: string, options: RequestInit = {}): Promise<Response> {
  const token = localStorage.getItem('flaxie_token') || ''

  const res = await fetch(url, {
    ...options,
    headers: {
      ...(options.headers as Record<string, string> | undefined),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  })

  if (res.status !== 401) return res

  // Token expired — try to refresh once
  const newToken = await refreshToken()
  if (!newToken) {
    clearAuth()
    return res  // clearAuth reloads the page; this line is never reached
  }

  // Retry with fresh token
  return fetch(url, {
    ...options,
    headers: {
      ...(options.headers as Record<string, string> | undefined),
      Authorization: `Bearer ${newToken}`,
    },
  })
}
