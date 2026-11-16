/* Gọi API kèm danh tính (AUTH1): token đăng nhập + mã trình duyệt cho khách vãng lai.

Mọi lời gọi API của giao diện đi qua apiFetch, kể cả luồng chat SSE (lib/sse.ts),
để máy chủ luôn biết ai đang hỏi. Bật/tắt kiểm tra quyền là ở máy chủ (AUTH_REQUIRED).
*/

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "";

const TOKEN_KEY = "lawvn_token";
const CLIENT_KEY = "lawvn_client_id";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage bị chặn: phiên chỉ sống trong tab này */
  }
}

/** Mã trình duyệt ổn định cho khách vãng lai — hạn mức ngày tính theo mã này. */
export function clientId(): string {
  try {
    let id = localStorage.getItem(CLIENT_KEY);
    if (!id) {
      id = crypto.randomUUID
        ? crypto.randomUUID()
        : Math.random().toString(16).slice(2) + Date.now().toString(16);
      localStorage.setItem(CLIENT_KEY, id);
    }
    return id;
  } catch {
    return "no-storage";
  }
}

/** Headers danh tính; dùng cho cả fetch thường và luồng SSE. */
export function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = { "X-Client-Id": clientId() };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

/** fetch có kèm Authorization + X-Client-Id; `path` là "/api/..." (hoặc URL tuyệt đối). */
export function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const url = path.startsWith("http") ? path : `${API_BASE}${path}`;
  const headers = new Headers(init.headers);
  for (const [name, value] of Object.entries(authHeaders())) {
    if (!headers.has(name)) headers.set(name, value);
  }
  return fetch(url, { ...init, headers });
}
