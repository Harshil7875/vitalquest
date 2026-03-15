import { authStorage } from '../../features/auth/authStorage';

// ─── API Client ───────────────────────────────────────────────────────────────
// Thin fetch wrapper that:
//   1. Automatically injects the stored JWT as Bearer token
//   2. Throws typed errors on non-2xx responses
//   3. Points to the Nginx gateway (port 80) which routes to health_service
//      or game_service based on path prefix

// Dev: Nginx listens on port 80. In production update to your deployed domain.
const API_BASE_URL =
  process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:80';

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: unknown,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const token = await authStorage.getToken();

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init.headers as Record<string, string>),
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
  });

  if (!res.ok) {
    let body: unknown;
    try {
      body = await res.json();
    } catch {
      body = await res.text();
    }
    throw new ApiError(res.status, body, `API ${res.status}: ${path}`);
  }

  // 204 No Content
  if (res.status === 204) return null as T;

  return res.json() as Promise<T>;
}

export const apiClient = {
  get: <T>(path: string) => request<T>(path),

  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: 'POST',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),

  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
};
