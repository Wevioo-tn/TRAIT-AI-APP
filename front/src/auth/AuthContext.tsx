import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import * as api from "../api/client";
import { ApiError, AUTH_STORAGE_KEY } from "../api/client";

interface StoredSession {
  token: string;
  username: string;
}

function loadStoredSession(): StoredSession | null {
  try {
    const raw = localStorage.getItem(AUTH_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as StoredSession) : null;
  } catch {
    return null;
  }
}

interface AuthState {
  isAuthenticated: boolean;
  username: string;
  login: (username: string, password: string) => Promise<boolean>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<StoredSession | null>(() => loadStoredSession());

  useEffect(() => {
    api.setAuthToken(session?.token ?? null);
  }, [session]);

  useEffect(() => {
    // A 401 anywhere (e.g. the token expired mid-session) forces the same
    // clean logout as clicking "Déconnexion" — no stale token left behind.
    api.setUnauthorizedHandler(() => setSession(null));
    return () => api.setUnauthorizedHandler(null);
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      isAuthenticated: session !== null,
      username: session?.username ?? "",
      login: async (username: string, password: string) => {
        try {
          const result = await api.login(username.trim(), password);
          const next: StoredSession = { token: result.access_token, username: result.username };
          localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(next));
          setSession(next);
          return true;
        } catch (error) {
          if (error instanceof ApiError) return false;
          throw error;
        }
      },
      logout: () => {
        localStorage.removeItem(AUTH_STORAGE_KEY);
        setSession(null);
      },
    }),
    [session],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside an AuthProvider");
  return context;
}
