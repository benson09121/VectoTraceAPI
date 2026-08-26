"use client";

import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { api, ApiNetworkError, currentOrg, tokens } from "./api";
import type { Organization, User } from "./types";

interface AuthState {
  user: User | null;
  orgs: Organization[];
  org: Organization | null;
  loading: boolean;
  setOrg: (org: Organization) => void;
  refreshOrgs: () => Promise<Organization[]>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [org, setOrgState] = useState<Organization | null>(null);
  const [loading, setLoading] = useState(true);

  const setOrg = useCallback((next: Organization) => {
    setOrgState(next);
    currentOrg.set(next.id);
  }, []);

  const refreshOrgs = useCallback(async () => {
    const list = await api.listOrgs();
    setOrgs(list);
    return list;
  }, []);

  useEffect(() => {
    // Everything runs inside the async body so no setState happens
    // synchronously during the effect.
    (async () => {
      if (!tokens.access()) {
        setLoading(false);
        router.replace("/login");
        return;
      }

      let profile;
      try {
        // Identity is what the session depends on. If this fails the token is
        // no good and signing out is correct.
        profile = await api.me();
      } catch (error) {
        // An unavailable API is not an invalid session. Keep the credentials
        // so the user can retry after the backend recovers.
        if (error instanceof ApiNetworkError) {
          setLoading(false);
          return;
        }
        tokens.clear();
        router.replace("/login");
        setLoading(false);
        return;
      }
      setUser(profile);

      // The org list failing must NOT end the session — a brand new user has
      // no organizations yet, and logging them out here would make it
      // impossible to ever create the first one.
      try {
        const list = await api.listOrgs();
        setOrgs(list);

        // Restore the last-used org if it's still one the user belongs to.
        const saved = currentOrg.get();
        const restored = list.find((o) => String(o.id) === saved) ?? list[0] ?? null;
        if (restored) setOrg(restored);
      } catch {
        setOrgs([]);
      } finally {
        setLoading(false);
      }
    })();
  }, [router, setOrg]);

  const logout = useCallback(async () => {
    await api.logout();
    setUser(null);
    setOrgs([]);
    setOrgState(null);
    router.replace("/login");
  }, [router]);

  return (
    <AuthContext.Provider
      value={{ user, orgs, org, loading, setOrg, refreshOrgs, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
