/** Base API client — proxied through Next.js rewrites to the API Gateway */

const API_BASE = "/api/v1";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function readResponseBody<T>(res: Response): Promise<T> {
  if (res.status === 204 || res.status === 205) return undefined as T;
  const text = await res.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("auth_token");
}

function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("auth_refresh_token");
}

let isRefreshing = false;
let refreshPromise: Promise<string | null> | null = null;

async function attemptTokenRefresh(): Promise<string | null> {
  // Deduplicate concurrent refresh calls
  if (isRefreshing && refreshPromise) return refreshPromise;

  isRefreshing = true;
  refreshPromise = (async () => {
    try {
      const refreshToken = getRefreshToken();
      if (!refreshToken) return null;
      const res = await fetch(`${API_BASE}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!res.ok) {
        localStorage.removeItem("auth_token");
        localStorage.removeItem("auth_refresh_token");
        return null;
      }
      const data = await res.json();
      const newToken: string = data?.data?.access_token;
      const newRefresh: string = data?.data?.refresh_token;
      if (newToken) {
        localStorage.setItem("auth_token", newToken);
        if (newRefresh) localStorage.setItem("auth_refresh_token", newRefresh);
      }
      return newToken ?? null;
    } catch {
      return null;
    } finally {
      isRefreshing = false;
      refreshPromise = null;
    }
  })();

  return refreshPromise;
}

export async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token = getToken();
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers ?? {}),
    },
  });

  // Auto-refresh on 401
  if (res.status === 401 && !path.startsWith("/auth/")) {
    const newToken = await attemptTokenRefresh();
    if (newToken) {
      const retryRes = await fetch(`${API_BASE}${path}`, {
        ...options,
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${newToken}`,
          ...(options.headers ?? {}),
        },
      });
      if (!retryRes.ok) {
        const body = await retryRes.text().catch(() => "");
        throw new ApiError(retryRes.status, body || retryRes.statusText);
      }
      return readResponseBody<T>(retryRes);
    }
    // Refresh failed — throw 401 for the caller to handle (e.g. redirect to login)
    throw new ApiError(
      401,
      "セッションが切れました。再度ログインしてください。",
    );
  }

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new ApiError(res.status, body || res.statusText);
  }

  return readResponseBody<T>(res);
}

/**
 * 生の `fetch` を使う箇所でも認証ヘッダを付けられるようにする。
 * apiRequest と違い URL の前置・401 リトライは行わない。
 */
export function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export function get<T>(path: string) {
  return apiRequest<T>(path);
}

export function post<T>(path: string, body: unknown) {
  return apiRequest<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function put<T>(path: string, body: unknown) {
  return apiRequest<T>(path, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export function patch<T>(path: string, body: unknown) {
  return apiRequest<T>(path, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function del<T>(path: string) {
  return apiRequest<T>(path, { method: "DELETE" });
}
