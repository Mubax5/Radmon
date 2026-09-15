export type Role = "Viewer" | "Operator" | "Administrator";

export type SessionUser = {
  username: string;
  display_name: string;
  role: Role;
};

export type Station = {
  serid: number;
  name: string;
  location: string;
  warnlevel: number;
  alarmlevel: number;
  unit: string;
  status?: "normal" | "warning" | "alarm" | "offline";
  doserate?: number | null;
  dtom?: string | null;
};

export type WebEvent = {
  type: string;
  [key: string]: unknown;
};

const inFlightReads = new Map<string, Promise<unknown>>();

async function performApi<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    ...init,
  });
  if (!response.ok) {
    if (response.status === 401 && path !== "/auth/login" && path !== "/auth/me") {
      window.dispatchEvent(new Event("radmon:session-expired"));
    }
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch {
      // Preserve HTTP detail when a proxy returns text/html.
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const method = String(init?.method || "GET").toUpperCase();
  if (method !== "GET") return performApi<T>(path, init);

  // All authenticated control-plane reads are same-origin. Sharing an already
  // running GET prevents the initial page load and live SSE refreshes from
  // multiplying identical DB work when the backend is temporarily slow.
  const existing = inFlightReads.get(path);
  if (existing) return existing as Promise<T>;

  const request = performApi<T>(path, init);
  inFlightReads.set(path, request);
  try {
    return await request;
  } finally {
    if (inFlightReads.get(path) === request) inFlightReads.delete(path);
  }
}

export async function currentUser(): Promise<SessionUser | null> {
  try {
    return await api<SessionUser>("/auth/me");
  } catch {
    return null;
  }
}

export async function login(username: string, password: string): Promise<SessionUser> {
  return api<SessionUser>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export async function logout(): Promise<void> {
  await api<{ status: string }>("/auth/logout", { method: "POST" });
}

export function subscribeWebEvents(onEvent: (event: WebEvent) => void): () => void {
  const source = new EventSource("/api/v1/web/events", { withCredentials: true });
  source.onmessage = (message) => {
    try {
      onEvent(JSON.parse(message.data) as WebEvent);
    } catch {
      // Ignore malformed/partial refresh hints. REST remains authoritative.
    }
  };
  return () => source.close();
}
