/**
 * Authenticated fetch — adds Authorization: Bearer <token> to every request.
 * Falls back to unauthenticated if no token is stored (e.g. during onboarding).
 */
export function authFetch(url: string, options: RequestInit = {}): Promise<Response> {
  const token = localStorage.getItem('flaxie_token') || ''
  return fetch(url, {
    ...options,
    headers: {
      ...(options.headers as Record<string, string> | undefined),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  })
}
