import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { Button, Input, LayerCard } from "@cloudflare/kumo";
import brinLogo from "./assets/brin-logo.png";
import {
  currentUser,
  login as loginRequest,
  logout as logoutRequest,
  type SessionUser,
} from "./api";

export type SessionContextValue = {
  user: SessionUser | null;
  loading: boolean;
  signIn(username: string, password: string): Promise<void>;
  signOut(): Promise<void>;
};

const SessionContext = createContext<SessionContextValue | null>(null);

function moveToLogin(): void {
  if (window.location.pathname !== "/app/login") {
    window.history.replaceState({}, "", "/app/login");
  }
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    void currentUser().then((identity) => {
      if (!active) return;
      setUser(identity);
      setLoading(false);
      if (!identity) moveToLogin();
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const expire = () => {
      setUser(null);
      setLoading(false);
      moveToLogin();
    };
    window.addEventListener("radmon:session-expired", expire);
    return () => window.removeEventListener("radmon:session-expired", expire);
  }, []);

  async function signIn(username: string, password: string) {
    const identity = await loginRequest(username, password);
    setUser(identity);
    window.history.replaceState({}, "", "/app");
    window.dispatchEvent(new PopStateEvent("popstate"));
  }

  async function signOut() {
    try {
      await logoutRequest();
    } finally {
      setUser(null);
      setLoading(false);
      moveToLogin();
    }
  }

  const value = useMemo<SessionContextValue>(
    () => ({ user, loading, signIn, signOut }),
    [user, loading],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside AuthProvider");
  return value;
}

export function LoginPage() {
  const { signIn } = useSession();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await signIn(username, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to sign in");
    } finally {
      setPassword("");
      setBusy(false);
    }
  }

  return (
    <main className="login-shell">
      <LayerCard className="login-card">
        <div className="login-brand">
          <img src={brinLogo} alt="BRIN" />
        </div>
        <h1>Sign in to RadMon</h1>
        <p>Radiation monitoring control plane for authorized users.</p>
        <form onSubmit={submit} className="login-form">
          <Input label="Username" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus autoComplete="username" />
          <Input label="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
          {error ? <div className="form-error">{error}</div> : null}
          <Button type="submit" variant="primary" disabled={busy || !username || !password}>
            {busy ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </LayerCard>
    </main>
  );
}
