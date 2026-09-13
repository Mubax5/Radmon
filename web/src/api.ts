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

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    ...init,
  });
  if (!response.ok) {
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
