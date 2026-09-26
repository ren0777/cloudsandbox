// The only way the UI talks to the backend (see CLAUDE.md conventions).
// Same-origin cookies; CSRF double-submit header on mutations; one silent refresh on token expiry.

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public requestId: string | null = null,
    public extra: Record<string, unknown> = {},
    public retryAfter: number | null = null,
  ) {
    super(message);
  }
}

function cookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const m = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return m ? decodeURIComponent(m[1]) : null;
}

let refreshing: Promise<boolean> | null = null;
async function refresh(): Promise<boolean> {
  refreshing ??= fetch("/api/auth/refresh", {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": cookie("cl_csrf") ?? "" },
  })
    .then((r) => r.ok)
    .finally(() => setTimeout(() => (refreshing = null), 0));
  return refreshing;
}

type Opts = { method?: string; body?: unknown; form?: FormData; headers?: Record<string, string> };

export async function api<T = unknown>(path: string, opts: Opts = {}, retried = false): Promise<T> {
  const method = opts.method ?? "GET";
  const headers: Record<string, string> = { ...(opts.headers ?? {}) };
  if (method !== "GET") headers["X-CSRF-Token"] = cookie("cl_csrf") ?? "";
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, { method, headers, body, credentials: "same-origin", cache: "no-store" });
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const e = data?.error ?? {};
    if (res.status === 401 && e.code === "token_expired" && !retried && (await refresh())) {
      return api<T>(path, opts, true);
    }
    const { code, message, request_id, ...extra } = e;
    const ra = res.headers.get("Retry-After");
    throw new ApiError(res.status, code ?? "http_error", message ?? res.statusText, request_id ?? null,
      extra, ra ? Number(ra) : null);
  }
  return data as T;
}

export const newIdempotencyKey = () =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}-${Math.random().toString(16).slice(2)}`;

/** Capacity-full retry schedule (PLAN §13): 3s → 5s → 8s → 12s, then every 12s, ±20% jitter. */
export function capacityDelayMs(attempt: number): number {
  const base = [3000, 5000, 8000, 12000][Math.min(attempt, 3)];
  return Math.round(base * (0.8 + Math.random() * 0.4));
}
