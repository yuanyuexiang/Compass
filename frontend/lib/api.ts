// 统一 fetch 封装：自动携带 Bearer token，401 跳转登录页，错误统一为中文 Error

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8300';

const TOKEN_KEY = 'access_token';
const USER_KEY = 'user';

export function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setSession(token: string, user: unknown): void {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export function getCachedUser<T>(): T | null {
  if (typeof window === 'undefined') return null;
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...((options.headers as Record<string, string>) ?? {}),
  };
  const token = getToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  } catch {
    throw new Error('无法连接服务器，请确认后端服务已启动');
  }

  // 登录接口自身的 401 属于凭证错误，不做跳转
  if (res.status === 401 && !path.startsWith('/api/auth/')) {
    if (typeof window !== 'undefined') {
      clearSession();
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
    }
    throw new Error('登录已过期，请重新登录');
  }

  if (!res.ok) {
    let msg = `请求失败（HTTP ${res.status}）`;
    try {
      const data = (await res.json()) as { detail?: unknown; message?: unknown };
      if (typeof data.detail === 'string' && data.detail) msg = data.detail;
      else if (typeof data.message === 'string' && data.message) msg = data.message;
    } catch {
      // 忽略响应体解析失败
    }
    throw new Error(msg);
  }

  return (await res.json()) as T;
}
