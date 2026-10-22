const API_ORIGIN = import.meta.env.VITE_API_URL?.trim().replace(/\/+$/, '') ?? '';
const API = `${API_ORIGIN}/api`;
const TOKEN_KEY = 'fourfold.session';

function apiUrl(path: string) {
  if (!import.meta.env.DEV && !API_ORIGIN) {
    throw new Error('Production API is not configured. Set VITE_API_URL in Vercel and redeploy.');
  }
  return `${API}${path}`;
}

export function getSocketUrl() {
  if (import.meta.env.DEV) return '/';
  if (!API_ORIGIN) {
    throw new Error('Production API is not configured. Set VITE_API_URL in Vercel and redeploy.');
  }
  return import.meta.env.VITE_SOCKET_URL?.trim().replace(/\/+$/, '') || API_ORIGIN;
}

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const response = await fetch(apiUrl(path), {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: 'The request could not be completed.' }));
    if (response.status === 401) localStorage.removeItem(TOKEN_KEY);
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export async function downloadResults(format: 'json' | 'csv', roomCode: string) {
  const token = getToken();
  const response = await fetch(apiUrl(`/results/${format}`), {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: 'Could not download the results.' }));
    if (response.status === 401) localStorage.removeItem(TOKEN_KEY);
    throw new Error(body.detail || `Download failed (${response.status})`);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `guessing-game-results-${roomCode}.${format}`;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
